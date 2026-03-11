# Colourmap Limits — Implementation Plan
*Authored: 2026-03-08*

## Problem

Rasters display as "washed out" when the data's full value range is much wider
than the range of interest. For example, a DEM spanning 0–3000 m where the
catchment sits between 200–800 m: the colour ramp wastes most of its range on
irrelevant extremes, leaving the area of interest compressed into a narrow band
of similar colours. The 2% percentile clip (already implemented) helps but is
automatic and cannot be tuned. User-set vmin / vmax gives direct control.

---

## Design Principle

- **vmin / vmax are per-layer, user-set overrides**
- If set: the colour ramp maps `vmin → colour_0`, `vmax → colour_1`, data
  outside the range is clipped to the nearest colour endpoint
- If not set: fall back to the existing 2% percentile clip (automatic)
- **"Reset to Auto"** removes the override and restores percentile clip
- Settings persist in `project_state.json` across sessions
- The **"2b — Terrain Rendering"** section in p02 is preserved exactly as-is
  (it controls GRASS parameters, not Python colour rendering)

---

## Architecture Overview

```
Layers dock ⚙ button
  → LayerLimitsDialog(state_attr, state, map_view)
      reads  state.layer_display_limits[state_attr]
      reads  raster data stats (actual min / p2 / p98 / p98 / max)
      user edits vmin / vmax spinboxes
      Apply  → state.layer_display_limits[state_attr] = [vmin, vmax]
               map_view.rerender_by_state_attr(state_attr, vmin, vmax)
      Reset  → del state.layer_display_limits[state_attr]
               map_view.rerender_by_state_attr(state_attr, None, None)
      state.save() on either action
```

```
map_view.add_raster_overlay(name, path, ..., state_attr="")
  → stores (path, cmap, alpha, blend_mode, hillshade, log_scale,
            clip_bounds, vmin, vmax)
     in _active_rasters[name]
  → stores _state_attr_to_overlay[state_attr] = name   ← new reverse lookup

map_view.rerender_by_state_attr(state_attr, vmin, vmax)
  → looks up overlay_name from _state_attr_to_overlay[state_attr]
  → updates _active_rasters[overlay_name] with new vmin/vmax
  → calls _start_raster_render(overlay_name, ..., vmin=vmin, vmax=vmax)
```

---

## 1. State changes — `gui/state.py`

Add one new field:

```python
layer_display_limits: dict = field(default_factory=dict)
# {state_attr: [vmin, vmax]}   — None value means "auto" (percentile clip)
# e.g. {"accum_path": [0.0, 50000.0], "filled_dem_path": [150.0, 1200.0]}
# Stored as list (not tuple) for JSON serialisation compatibility.
# Key absent OR value None → use 2% percentile clip.
```

No changes needed to `save()` / `load()` — dicts serialise correctly, and
`load()` already filters unknown keys.

---

## 2. `raster_to_base64()` — `gui/widgets/map_widget.py`

Add two optional parameters:

```python
def raster_to_base64(path: str, cmap: str = "terrain",
                     alpha: float = 0.7,
                     max_dim: int = 1024,
                     hillshade: bool = False,
                     clip_bounds: tuple | None = None,
                     log_scale: bool = False,
                     vmin: float | None = None,
                     vmax: float | None = None) -> tuple[str, list]:
```

### Single-band stretch logic (replace current block)

```python
if log_scale:
    # Apply optional raw-data clipping BEFORE log transform
    # (user sets limits in original units, e.g. accumulation cells)
    if vmin is not None:
        data = np.where(mask, np.nan, np.maximum(data, vmin))
    if vmax is not None:
        data = np.where(mask, np.nan, np.minimum(data, vmax))
    data = np.where(mask, np.nan, np.log1p(np.maximum(data, 0)))
    valid = data[~mask]
    # Always use percentile clip on log-transformed data
    p2, p98 = np.nanpercentile(valid, [2, 98])
    normed = np.clip((data - p2) / max(p98 - p2, 1e-6), 0, 1)
else:
    valid = data[~mask]
    if vmin is not None and vmax is not None:
        # User-set limits — map directly, clip outside range
        lo, hi = float(vmin), float(vmax)
    elif vmin is not None:
        lo = float(vmin)
        hi = float(np.nanpercentile(valid, 98))
    elif vmax is not None:
        lo = float(np.nanpercentile(valid, 2))
        hi = float(vmax)
    else:
        # Both None → 2% percentile clip (existing behaviour)
        lo, hi = np.nanpercentile(valid, [2, 98])
    normed = np.clip((data - lo) / max(hi - lo, 1e-6), 0, 1)
```

### Multi-band (RGB) rasters
vmin / vmax do not apply — multi-band rasters (GRASS r.shade outputs) are
already in byte range and rendered directly. No change needed.

### Hillshade mode
vmin / vmax do not apply — hillshade is always rendered as greyscale
in the natural [0, 255] range. No change needed.

---

## 3. `add_raster_overlay()` — `gui/widgets/map_view.py`

### Signature change

```python
def add_raster_overlay(self, name: str, path: str,
                       cmap: str = "terrain", alpha: float = 0.7,
                       blend_mode: str = "normal",
                       hillshade: bool = False,
                       clip_bounds: tuple | None = None,
                       log_scale: bool = False,
                       vmin: float | None = None,
                       vmax: float | None = None,
                       state_attr: str = "") -> None:
```

New `state_attr` parameter enables the reverse lookup from Layers dock.

### Store in `_active_rasters`

```python
# Old tuple (7 items):
self._active_rasters[name] = (path, cmap, alpha, blend_mode,
                               hillshade, log_scale, clip_bounds)

# New tuple (9 items):
self._active_rasters[name] = (path, cmap, alpha, blend_mode,
                               hillshade, log_scale, clip_bounds,
                               vmin, vmax)
```

### New reverse lookup dict

```python
# In __init__:
self._state_attr_to_overlay: dict[str, str] = {}   # state_attr → overlay_name

# In add_raster_overlay, after storing _active_rasters:
if state_attr:
    self._state_attr_to_overlay[state_attr] = name
```

Reset in `clear_all_overlays`:
```python
self._state_attr_to_overlay.clear()
```

### Fix index references after tuple expansion

`_on_raster_rendered` and `_on_zoom_timeout` reference `_active_rasters`
tuple indices. Update these:

```python
# Hillshade flag is index 4 (unchanged — tuple positions 0-6 are same)
eff_alpha = 1.0 if self._active_rasters[name][4] else alpha

# In _on_zoom_timeout, unpack all 9 values:
path, cmap, alpha, blend_mode, hillshade, log_scale, clip_bounds, vmin, vmax = params

# Pass vmin/vmax to _start_raster_render and to the JS call
```

### New method `rerender_by_state_attr`

```python
def rerender_by_state_attr(self, state_attr: str,
                           vmin: float | None,
                           vmax: float | None) -> None:
    """Re-render a specific raster by its state attribute name."""
    name = self._state_attr_to_overlay.get(state_attr)
    if not name or name not in self._active_rasters:
        return
    params = list(self._active_rasters[name])
    params[7] = vmin   # update vmin
    params[8] = vmax   # update vmax
    self._active_rasters[name] = tuple(params)
    # Invalidate cache for this layer
    self._render_cache.pop(name, None)
    # Re-render at current zoom
    max_dim = _zoom_to_max_dim(self._zoom_level)
    path, cmap, alpha, blend_mode, hillshade, log_scale, clip_bounds, _, _ = params
    self._start_raster_render(name, path, cmap, alpha, blend_mode,
                              hillshade, log_scale, clip_bounds,
                              max_dim, vmin=vmin, vmax=vmax)
```

---

## 4. `RasterRenderWorker` — `gui/workers/raster_render_worker.py`

Add `vmin` and `vmax` parameters:

```python
def __init__(self, name, path, cmap, alpha, blend_mode, hillshade,
             log_scale, clip_bounds, max_dim,
             vmin=None, vmax=None, parent=None):
    ...
    self._vmin = vmin
    self._vmax = vmax

def run(self):
    b64, bounds = raster_to_base64(
        self._path, cmap=self._cmap, alpha=self._alpha,
        max_dim=self._max_dim, hillshade=self._hillshade,
        clip_bounds=self._clip_bounds, log_scale=self._log_scale,
        vmin=self._vmin, vmax=self._vmax,
    )
    self.finished_render.emit(self._name, b64, bounds,
                              self._blend_mode, self._alpha)
```

---

## 5. Panel changes — pass `state_attr` and `vmin`/`vmax`

All panels that call `add_raster_overlay` need two additions:
1. Pass `state_attr=` so the reverse lookup works
2. Look up `vmin`/`vmax` from `state.layer_display_limits`

### Helper function (add to `gui/panels/__init__.py` or inline)

```python
def _get_limits(state, state_attr):
    """Return (vmin, vmax) tuple from state, or (None, None) if not set."""
    lims = getattr(state, "layer_display_limits", {}).get(state_attr)
    if lims and len(lims) == 2:
        return float(lims[0]), float(lims[1])
    return None, None
```

### p02 `on_activated` — terrain composite

```python
vmin, vmax = _get_limits(s, "shaded_relief_path")
mv.add_raster_overlay("Terrain", s.shaded_relief_path,
                      alpha=0.9, clip_bounds=clip,
                      vmin=vmin, vmax=vmax,
                      state_attr="shaded_relief_path")
```

### p03 `_rebuild_map` — flow accumulation (if displayed on map)

```python
vmin, vmax = _get_limits(s, "accum_path")
mv.add_raster_overlay("Flow Accumulation", s.accum_path,
                      cmap="Blues", log_scale=True,
                      clip_bounds=clip,
                      vmin=vmin, vmax=vmax,
                      state_attr="accum_path")
```

### p04 `on_activated` — terrain background

```python
vmin, vmax = _get_limits(s, "shaded_relief_path")
mv.add_raster_overlay("Terrain", s.shaded_relief_path,
                      alpha=0.9, clip_bounds=clip,
                      vmin=vmin, vmax=vmax,
                      state_attr="shaded_relief_path")
```

Apply the same pattern to any other `add_raster_overlay` calls in panels.

---

## 6. Layers dock — `gui/widgets/layers_dock.py`

### New signal

```python
layer_limits_changed = pyqtSignal(str, object, object)
# state_attr, vmin (float or None), vmax (float or None)
```

### New ⚙ button per raster layer

In `_add_opacity_slider` (or alongside it), add a second child row with a
"⚙ Colour Limits" button. Clicking opens `LayerLimitsDialog`.

```python
def _add_style_row(self, item: QTreeWidgetItem) -> None:
    """Add a 'Colour Limits' row as a child item below the opacity slider."""
    # Guard: don't add duplicates
    for ci in range(item.childCount()):
        if item.child(ci).data(0, Qt.ItemDataRole.UserRole) == {"type": "style_row"}:
            return

    style_item = QTreeWidgetItem(item)
    style_item.setFlags(style_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
    style_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "style_row"})

    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(20, 1, 4, 1)

    btn = QPushButton("⚙ Colour Limits")
    btn.setFixedHeight(20)
    btn.setStyleSheet("font-size:10px; color:#ffe082;")

    data = item.data(0, Qt.ItemDataRole.UserRole)
    state_attr = data.get("attr", "")    # ← needs attr in stored data (see below)
    btn.clicked.connect(lambda: self._open_limits_dialog(state_attr))

    layout.addWidget(btn)
    layout.addStretch()
    self._tree.setItemWidget(style_item, 0, widget)
```

### Store `attr` in item data

Currently `_LAYER_DEFS` stores `state_attr` but it is not saved in the item's
`UserRole` data. Fix this in `refresh_from_state`:

```python
item.setData(0, Qt.ItemDataRole.UserRole,
             {"type": ltype, "name": label, "path": path,
              "cmap": cmap, "attr": attr})   # ← add "attr": attr
```

### Show style row when layer is checked (alongside opacity slider)

In `_on_item_changed`:
```python
if visible:
    self._add_opacity_slider(item)
    if ltype == "raster":
        self._add_style_row(item)
else:
    self._remove_opacity_slider(item)
    self._remove_style_row(item)
```

`_remove_style_row` mirrors `_remove_opacity_slider` — finds the child with
`{"type": "style_row"}` and removes it.

### `_open_limits_dialog(state_attr)`

Opens `LayerLimitsDialog` (see below). Dialog emits `applied(state_attr, vmin, vmax)`.
Connect: `dialog.applied.connect(lambda a, lo, hi: self.layer_limits_changed.emit(a, lo, hi))`.

---

## 7. New dialog — `LayerLimitsDialog`

Can live in `gui/widgets/layers_dock.py` or a new `gui/widgets/layer_limits_dialog.py`.

```python
class LayerLimitsDialog(QDialog):
    """Modal dialog for setting vmin/vmax colour limits on a raster layer."""

    applied = pyqtSignal(str, object, object)  # state_attr, vmin|None, vmax|None

    def __init__(self, state_attr: str, state, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Colour Limits")
        self._state_attr = state_attr
        self._state = state
        self._build_ui()
        self._load_data_stats()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Data stats row (read-only, informational)
        self._stats_label = QLabel("Reading data range…")
        self._stats_label.setStyleSheet("color:#aaa; font-size:11px;")
        self._stats_label.setWordWrap(True)
        layout.addWidget(self._stats_label)

        form = QFormLayout()

        self._vmin_spin = QDoubleSpinBox()
        self._vmin_spin.setRange(-1e9, 1e9)
        self._vmin_spin.setDecimals(2)
        self._vmin_spin.setSpecialValueText("Auto")   # shown when at sentinel value
        form.addRow("Min value:", self._vmin_spin)

        self._vmax_spin = QDoubleSpinBox()
        self._vmax_spin.setRange(-1e9, 1e9)
        self._vmax_spin.setDecimals(2)
        self._vmax_spin.setSpecialValueText("Auto")
        form.addRow("Max value:", self._vmax_spin)

        layout.addLayout(form)

        # Populate with existing limits if set
        lims = self._state.layer_display_limits.get(state_attr)
        if lims:
            self._vmin_spin.setValue(lims[0])
            self._vmax_spin.setValue(lims[1])

        # Buttons
        btn_row = QHBoxLayout()
        self._apply_btn  = QPushButton("Apply")
        self._reset_btn  = QPushButton("Reset to Auto")
        self._close_btn  = QPushButton("Close")
        self._apply_btn.setProperty("primary", "true")
        self._reset_btn.clicked.connect(self._on_reset)
        self._apply_btn.clicked.connect(self._on_apply)
        self._close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self._apply_btn)
        btn_row.addWidget(self._reset_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._close_btn)
        layout.addLayout(btn_row)

    def _load_data_stats(self):
        """Read actual data statistics from the raster file (background)."""
        path = getattr(self._state, self._state_attr, None)
        if not path or not os.path.exists(path):
            self._stats_label.setText("File not found.")
            return
        try:
            import numpy as np
            import rasterio
            with rasterio.open(path) as src:
                data = src.read(1).astype("float64")
                nodata = src.nodata
            if nodata is not None:
                data[np.isclose(data, nodata)] = np.nan
            valid = data[np.isfinite(data)]
            if valid.size == 0:
                self._stats_label.setText("No valid data in file.")
                return
            dmin = float(np.nanmin(valid))
            dmax = float(np.nanmax(valid))
            p2   = float(np.nanpercentile(valid, 2))
            p98  = float(np.nanpercentile(valid, 98))
            self._stats_label.setText(
                f"Data range:  {dmin:.2f} → {dmax:.2f}\n"
                f"Auto limits (2%–98%):  {p2:.2f} → {p98:.2f}"
            )
            # Pre-fill spinboxes with auto values if limits not yet set
            if self._state_attr not in self._state.layer_display_limits:
                self._vmin_spin.setValue(p2)
                self._vmax_spin.setValue(p98)
        except Exception as exc:
            self._stats_label.setText(f"Could not read stats: {exc}")

    def _on_apply(self):
        vmin = self._vmin_spin.value()
        vmax = self._vmax_spin.value()
        if vmin >= vmax:
            # Swap silently
            vmin, vmax = vmax, vmin
        self._state.layer_display_limits[self._state_attr] = [vmin, vmax]
        self._state.save()
        self.applied.emit(self._state_attr, vmin, vmax)

    def _on_reset(self):
        self._state.layer_display_limits.pop(self._state_attr, None)
        self._state.save()
        self.applied.emit(self._state_attr, None, None)
        self._stats_label.setText(
            self._stats_label.text() + "\n→ Reset to auto (2% percentile clip)."
        )
```

---

## 8. `app.py` — wire the new signal

`LayersDock` emits `layer_limits_changed(state_attr, vmin, vmax)`.
`MainWindow` connects it to `MapView.rerender_by_state_attr`:

```python
# In _setup_signals or wherever dock signals are connected:
self._layers_dock.layer_limits_changed.connect(
    lambda attr, lo, hi: self._map_view.rerender_by_state_attr(attr, lo, hi)
)
```

---

## 9. What stays unchanged

- **"2b — Terrain Rendering" section in p02** — completely preserved. It controls
  GRASS parameters (`r.relief` azimuth / altitude / zscale / brighten / colour
  scheme). These are independent of Python-side colour limits.
- **2% percentile clip** — still the default when no limits are set. User limits
  only override when explicitly applied.
- **Multi-band rasters** (GRASS r.shade composites) — vmin/vmax do not apply.
  Their "washed out" look is controlled by GRASS `brighten` in "2b — Terrain
  Rendering".
- **Hillshade multiply blend** — not affected.
- **Log scale for flow accumulation** — limits apply to raw cell counts before
  the log transform, so the user sets meaningful values (e.g., 0–50000 cells).

---

## 10. File change summary

| File | Change |
|------|--------|
| `gui/state.py` | Add `layer_display_limits: dict` |
| `gui/widgets/map_widget.py` | `raster_to_base64`: add `vmin`, `vmax` params; update stretch logic |
| `gui/widgets/map_view.py` | `add_raster_overlay`: add `vmin`, `vmax`, `state_attr`; expand `_active_rasters` tuple (9 items); add `_state_attr_to_overlay` dict; add `rerender_by_state_attr()`; fix index refs after tuple expansion; clear new dict in `clear_all_overlays` |
| `gui/workers/raster_render_worker.py` | Add `vmin`, `vmax` params; pass to `raster_to_base64` |
| `gui/widgets/layers_dock.py` | Store `"attr"` in item data; add `layer_limits_changed` signal; add `_add_style_row` / `_remove_style_row`; call from `_on_item_changed`; add `_open_limits_dialog`; new `LayerLimitsDialog` class (inline or separate file) |
| `gui/app.py` | Connect `layer_limits_changed` → `map_view.rerender_by_state_attr` |
| `gui/panels/p02_dem_processing.py` | Pass `vmin`, `vmax`, `state_attr` to `add_raster_overlay` |
| `gui/panels/p03_watershed.py` | Same |
| `gui/panels/p04_stream_network.py` | Same |
| `gui/panels/__init__.py` | Add `_get_limits(state, attr)` helper |

---

## 11. Implementation order

1. `gui/state.py` — add field (1 line)
2. `gui/widgets/map_widget.py` — add `vmin`/`vmax` to `raster_to_base64` stretch logic
3. `gui/workers/raster_render_worker.py` — add `vmin`/`vmax` params
4. `gui/widgets/map_view.py` — expand tuple, add `state_attr` param, `_state_attr_to_overlay`, `rerender_by_state_attr`; fix index refs
5. `gui/panels/__init__.py` — add `_get_limits` helper; update panels p02/p03/p04
6. `gui/widgets/layers_dock.py` — add `"attr"` to item data; `_add_style_row`; `LayerLimitsDialog`; new signal
7. `gui/app.py` — connect signal

Steps 1–5 give full functionality (limits respected on panel activation and zoom).
Steps 6–7 add the UI for users to set limits without restarting.

---

*See also:*
- *`PyTOPKAPI GUI - Feature Plans.md` — Features 1, 2, 3*
- *`PyTOPKAPI GUI - Map Display Research.md` — rendering best practices*
- *`memory/shaded_relief_improvements.md` — previous rendering fixes*

# PyTOPKAPI GUI — Feature Plans
*Authored: 2026-03-08*

Three features planned below. Each section contains motivation, design decisions,
exact file-level changes, and implementation notes so any session can pick up
where the previous one left off.

---

## Feature 1 — User-Controllable Map Display Settings

### Motivation
All GRASS rendering parameters (zscale, azimuth, altitude, brighten) and Python
display parameters (colourmap, log scale, stream width scale) are currently
hard-coded. Users should be able to iterate on the look of their terrain until it
is both accurate and visually clear, without editing source code.

### Design decisions

Split settings into two tiers:

| Tier | Parameters | Effect | Where shown |
|------|-----------|--------|-------------|
| **GRASS parameters** | azimuth, altitude, zscale, brighten (relief), brighten (accum) | Require re-running `r.relief` + `r.shade` to take effect | p02 form — "Terrain Rendering" group |
| **Display parameters** | colourmap per layer, stream width scale, hillshade blend weight | Take effect on next map activation / overlay toggle | Layers dock — per-layer "Style" popover |

Separating these avoids re-running expensive GRASS jobs just to change a colour.

### State fields to add (`gui/state.py`)

```python
# GRASS rendering
relief_azimuth:    float = 315.0
relief_altitude:   float = 45.0
# relief_zscale already exists
relief_brighten:   int   = 30
accum_brighten:    int   = 80
elevation_colors:  str   = "elevation"   # GRASS r.colors scheme

# Display-only
stream_width_scale:      float = 0.8   # Leaflet px per Strahler order
hillshade_blend_weight:  float = 0.6   # 0=no effect, 1=full multiply
layer_colormaps:         dict  = field(default_factory=dict)
# e.g. {"accum_path": "Blues", "slope_path": "YlOrRd"}
```

### UI changes

#### p02 — "Terrain Rendering" group (new QGroupBox in build_form)

Controls:
- `QDoubleSpinBox` — zscale (0.5–20.0, step 0.5, default 3.0)
- `QDoubleSpinBox` — azimuth (0–360°, step 15°, default 315°)
- `QDoubleSpinBox` — altitude (5–85°, step 5°, default 45°)
- `QSpinBox`       — brighten relief (−50 to 80, default 30)
- `QComboBox`      — elevation colour scheme: `elevation`, `srtm`, `dem`, `terrain`, `viridis`, `grey.eq`
- `QPushButton`    — "Re-run Terrain Rendering" (re-runs r.relief + r.shade only, not the full GRASS pipeline)

A dedicated lightweight worker `ReliefWorker` (new file) runs only:
```
r.colors map=filled color=<scheme> flags=e
r.relief input=filled output=relief azimuth=<az> altitude=<alt> zscale=<z> overwrite=True
r.shade shade=relief color=filled output=shaded_relief brighten=<b> overwrite=True
r.out.gdal input=relief output=relief.tif ...
r.out.gdal input=shaded_relief output=shaded_relief.tif ...
```
This avoids re-running fill + watershed + basins. Completes in seconds.

#### Layers dock — per-layer style button

Add a small "⚙" button beside each layer's opacity slider. Clicking it opens a
`QDialog` (or inline expander) with:
- `QComboBox` — colourmap (terrain, viridis, Blues, YlOrRd, RdYlGn, grey, etc.)
- `QSlider` — display opacity (already exists; move here)

On change: call `MapView.add_raster_overlay(name, path, cmap=new_cmap)` to re-render.

#### p04 — stream width control

Add `QDoubleSpinBox` for stream width scale (0.3–3.0, default 0.8).
On change: call `MapView._run_js(f"window._setStreamWidthScale({scale})")` + JS
function `_setStreamWidthScale(s)` that updates the Strahler weight formula.

### Files to change

| File | Change |
|------|--------|
| `gui/state.py` | Add 7 new fields listed above |
| `gui/workers/relief_worker.py` | New file — lightweight GRASS r.relief + r.shade only |
| `gui/panels/p02_dem_processing.py` | Add "Terrain Rendering" group, wire to ReliefWorker |
| `gui/panels/p04_stream_network.py` | Add stream width scale spinbox |
| `gui/widgets/layers_dock.py` | Add ⚙ style button + colourmap combo per layer |
| `gui/widgets/map_widget.py` JS | Add `_setStreamWidthScale(s)` function; use `state.stream_width_scale` |
| `gui/widgets/map_view.py` | Forward `log_scale` from `layer_colormaps` in state |

### Implementation notes
- `r.colors flags=e` applies histogram equalisation — important for flat-terrain projects
- GRASS `r.relief` does NOT need the full mapset; import only the filled DEM, run r.relief + r.shade, export, done
- `ReliefWorker` can re-use the same GRASS `--tmp-location` pattern as FillWorker
- Store `layer_colormaps` as a plain dict in state; `layers_dock.py` reads it in `refresh_from_state()`

---

## Feature 2 — Multi-Basin Selection for DEM Clipping

### Motivation
A watershed is often made up of several sub-basins. Currently only one basin can
be selected at a time. Users need to click multiple basins, see them all
highlighted, then merge and clip in one operation.

### Design decisions

- Keep the same JS click handler but change single-select → toggle multi-select
- Maintain the selection list in Python (not JS) — simpler to manage and serialise
- "Merge & Clip" button dissolves all selected basins using `shapely.ops.unary_union`
  then passes the merged polygon to `ClipWorker`
- Visual: selected basins turn gold; clicking a selected basin deselects (returns to normal)
- Label shows count: "3 basins selected" rather than individual IDs

### JS changes (`gui/widgets/map_widget.py` — `_BRIDGE_JS`)

Current state: `window._selectedBasinLayer` (single layer reference).

Replace with a `Map` keyed by a stable feature identifier:

```javascript
window._selectedBasinLayers = {};   // key = feature id/cat, value = flayer

// In onEachFeature click handler:
flayer.on('click', function(e) {
    L.DomEvent.stopPropagation(e);
    var fid = (feature.properties && (feature.properties.cat
               || feature.properties.value
               || feature.properties.id)) || JSON.stringify(feature.geometry);

    if (window._selectedBasinLayers[fid]) {
        // Deselect
        window._overlays[name] && window._overlays[name].resetStyle(flayer);
        delete window._selectedBasinLayers[fid];
    } else {
        // Select
        flayer.setStyle({color:'#FFD700', weight:3,
                         fillColor:'#FFD700', fillOpacity:0.45});
        window._selectedBasinLayers[fid] = flayer;
    }
    // Send toggle event to Python — same bridge slot
    var payload = JSON.stringify({
        overlay: name,
        feature: JSON.stringify(feature),
        selected: !!window._selectedBasinLayers[fid]
    });
    sendOrQueue(function() { bridge.onFeatureClicked(payload); });
});
```

Also reset `window._selectedBasinLayers = {}` inside `_clearAllOverlays`.

### Python changes

#### `gui/panels/p02_dem_processing.py`

Change `_selected_basin_geojson: str | None` → `_selected_basins: list[str]` (list of GeoJSON Feature strings).

`_on_feature_clicked` becomes a toggle:

```python
def _on_feature_clicked(self, overlay_name: str, feature_json: str) -> None:
    import json as _j
    if overlay_name != "Basins":
        return
    data = _j.loads(feature_json)
    feature_str = data.get("feature", "{}")
    is_selected = data.get("selected", True)

    if is_selected:
        if feature_str not in self._selected_basins:
            self._selected_basins.append(feature_str)
    else:
        self._selected_basins = [f for f in self._selected_basins
                                  if f != feature_str]

    n = len(self._selected_basins)
    if n == 0:
        self._selected_basin_label.setText("No basins selected — click polygons on the map.")
        self._selected_basin_label.setStyleSheet("color:#777; font-size:11px;")
        self._clip_btn.setEnabled(False)
    else:
        self._selected_basin_label.setText(
            f"✅ {n} basin{'s' if n>1 else ''} selected — click 'Merge & Clip DEM'."
        )
        self._selected_basin_label.setStyleSheet("color:#FFD700; font-size:11px;")
        self._clip_btn.setEnabled(True)
```

Button label changes: "Clip DEM to Selected Basin" → "Merge & Clip DEM".

`_clip_to_selected_basin` dissolves all selected features before clipping:

```python
def _clip_to_selected_basin(self):
    if not self._selected_basins:
        return
    import json as _j
    from shapely.geometry import shape
    from shapely.ops import unary_union

    geoms = [shape(_j.loads(f)["geometry"]) for f in self._selected_basins]
    merged = unary_union(geoms)

    # Build a single GeoJSON Feature from the merged geometry
    merged_feature = _j.dumps({
        "type": "Feature",
        "geometry": merged.__geo_interface__,
        "properties": {"merged_basins": len(geoms)}
    })

    worker = ClipWorker(self._state, geojson_str=merged_feature, label="basin")
    ...
```

Reset `_selected_basins = []` and reset JS selection via a new JS function:

```javascript
window._clearBasinSelection = function() {
    Object.values(window._selectedBasinLayers || {}).forEach(function(flayer) {
        // resetStyle on individual layers via the parent overlay
    });
    window._selectedBasinLayers = {};
};
```

Call `mv._run_js("window._clearBasinSelection && window._clearBasinSelection()")`
after a successful clip.

### Files to change

| File | Change |
|------|--------|
| `gui/widgets/map_widget.py` JS | Replace single-select with toggle multi-select; add `_clearBasinSelection`; reset on `_clearAllOverlays` |
| `gui/panels/p02_dem_processing.py` | `_selected_basins: list`, toggle logic, dissolve on clip, reset after success |

### No changes needed
- `ClipWorker` — already accepts a GeoJSON Feature string; the merged polygon is just another Feature
- `map_view.py` — no changes; feature routing unchanged
- `app.py` — no changes; routing already delegates to `panel._on_feature_clicked`

---

## Feature 3 — Zoom-Responsive Raster Resolution (fix pixelation)

### Motivation
Rasters are exported as fixed-resolution PNGs (max 1024 px). Zooming in on the
Leaflet map reveals the pixel grid. Contour lines were added as a visual workaround
but they are distracting. The proper fix is to re-render rasters at higher resolution
when the user zooms in, and remove auto-contours.

### Design decisions

- **Zoom-event re-render**: listen to Leaflet `zoomend`, send zoom level to Python,
  re-render affected rasters at zoom-appropriate resolution
- **Background thread**: rendering is done in a `RasterRenderWorker` (QThread) so
  the UI stays responsive
- **Per-layer render cache**: `{layer_name: {zoom_bucket: (b64, bounds)}}` avoids
  re-encoding when zooming back out
- **Debounce**: 400 ms timer prevents rapid zoom scrolling from queuing many renders
- **Contours removed**: the contour overlay in p02's `on_activated` is removed once
  this feature is in place; contours become an opt-in layer in the Layers dock only

### Zoom bucket → max_dim mapping

| Leaflet zoom | Context | max_dim |
|---|---|---|
| ≤ 10 | Whole region | 512 |
| 11–12 | Watershed scale | 1024 |
| 13–14 | Catchment detail | 2048 |
| ≥ 15 | Stream / cell detail | 4096 |

Use buckets (not exact zoom) so nearby zoom levels share the same cached render.

```python
def _zoom_to_max_dim(zoom: int) -> int:
    if zoom <= 10: return 512
    if zoom <= 12: return 1024
    if zoom <= 14: return 2048
    return 4096
```

### New file: `gui/workers/raster_render_worker.py`

```python
class RasterRenderWorker(QThread):
    """Re-renders a raster overlay at a new resolution in the background."""
    finished = pyqtSignal(str, str, list)  # name, b64, bounds

    def __init__(self, name, path, cmap, alpha, hillshade, log_scale,
                 clip_bounds, max_dim):
        ...

    def run(self):
        from gui.widgets.map_widget import raster_to_base64
        b64, bounds = raster_to_base64(path, cmap=cmap, alpha=alpha,
                                        hillshade=hillshade,
                                        log_scale=log_scale,
                                        clip_bounds=clip_bounds,
                                        max_dim=max_dim)
        self.finished.emit(self.name, b64, bounds)
```

### Changes to `MapView` (`gui/widgets/map_view.py`)

New instance variables:
```python
self._zoom_level: int = 12
self._active_rasters: dict = {}
# {name: (path, cmap, alpha, blend_mode, hillshade, log_scale, clip_bounds)}
self._render_cache: dict = {}
# {name: {zoom_bucket: (b64, bounds)}}
self._zoom_timer: QTimer  # 400ms debounce
self._render_workers: list = []  # track running workers
```

`add_raster_overlay` — also stores layer params to `_active_rasters` and
current b64 to `_render_cache[name][current_zoom_bucket]`.

`clear_all_overlays` — clears `_active_rasters` and `_render_cache`.

New method `_on_zoom_changed(zoom: int)`:
```python
def _on_zoom_changed(self, zoom: int) -> None:
    bucket = _zoom_to_max_dim(zoom)
    old_bucket = _zoom_to_max_dim(self._zoom_level)
    self._zoom_level = zoom
    if bucket == old_bucket:
        return   # same resolution tier — no re-render needed
    for name, params in self._active_rasters.items():
        cached = self._render_cache.get(name, {}).get(bucket)
        if cached:
            b64, bounds = cached
            self._run_js(f"window._addRasterOverlay({json.dumps(name)}, '{b64}', "
                         f"{json.dumps(bounds)}, {params[2]}, {json.dumps(params[3])})")
        else:
            self._start_raster_render(name, *params, max_dim=bucket)
```

`_start_raster_render` starts a `RasterRenderWorker` in a thread, connects
`finished` to `_on_raster_rendered`.

`_on_raster_rendered(name, b64, bounds)` — updates cache + calls `_addRasterOverlay`.

### Changes to `MapBridge` / `MapWidget` (`gui/widgets/map_widget.py`)

New bridge slot:
```python
@pyqtSlot(str)
def onMapZoom(self, zoom_str: str):
    try:
        self.zoom_changed.emit(int(zoom_str))
    except ValueError:
        pass
```

New signal: `zoom_changed = pyqtSignal(int)` on `MapBridge`.

Wired in `MapWidget.__init__`: `self._bridge.zoom_changed.connect(self.zoom_changed)`.

New signal on `MapWidget`: `zoom_changed = pyqtSignal(int)`.

In `MapView._setup_signals` (or wherever map_view wires the widget):
```python
self._map_widget.zoom_changed.connect(self._zoom_debounce)
```

Where `_zoom_debounce` restarts a `QTimer(400ms)` that calls `_on_zoom_changed`.

JS change — add in `hookMap()`:
```javascript
m.on('zoomend', function() {
    sendOrQueue(function() { bridge.onMapZoom(String(m.getZoom())); });
});
```

### Changes to `p02_dem_processing.py`

Remove the auto-contour overlay:
```python
# DELETE this block (lines ~89-94):
dem_for_contours = s.filled_dem_path or s.proj_dem_path
if dem_for_contours and os.path.exists(dem_for_contours) and clip:
    mv.add_contour_overlay(...)
```

Contours are still available via the Layers dock as an opt-in overlay — the
`add_contour_overlay` method stays, just not called automatically.

### Estimated re-render times (RasterRenderWorker)

| max_dim | Typical raster (~200k cells filled DEM) | Notes |
|---|---|---|
| 512 | ~0.3 s | Zoom-out; usually cached |
| 1024 | ~0.8 s | Default; usually already cached |
| 2048 | ~2.5 s | First zoom-in; visible loading gap |
| 4096 | ~8 s | Very detailed; rare |

For 2048+ consider showing a "Loading..." label in the map hint area during render.

### Files to change

| File | Change |
|------|--------|
| `gui/workers/raster_render_worker.py` | New file — wraps `raster_to_base64` in QThread |
| `gui/widgets/map_widget.py` | New `onMapZoom` slot + `zoom_changed` signal; JS `zoomend` listener |
| `gui/widgets/map_view.py` | `_active_rasters`, `_render_cache`, `_on_zoom_changed`, debounce timer, `_start_raster_render`, `_on_raster_rendered`; store params in `add_raster_overlay` |
| `gui/panels/p02_dem_processing.py` | Remove auto-contour block |

---

## Implementation Order

All three features are independent and can be implemented in any order.
Suggested sequence:

1. **Feature 2** (multi-basin) — pure Python + small JS change; lowest risk; highest
   user value; can be done in one session
2. **Feature 1** (display settings) — add state fields first, then ReliefWorker,
   then UI controls; can be done incrementally
3. **Feature 3** (zoom-responsive) — most architectural change; do last once the
   other two are stable

---

## Key Architectural Notes

### How basin selection currently works (for Feature 2 context)

```
Map click
  → JS onEachFeature handler
  → bridge.onFeatureClicked(JSON payload)
  → MapBridge.onFeatureClicked slot (Python)
  → feature_clicked signal(overlay_name, feature_json)
  → MapWidget.feature_clicked signal
  → app.py _on_map_feature_clicked
  → active_panel._on_feature_clicked(overlay_name, feature_json)
  → p02_dem_processing._on_feature_clicked (stores single basin)
```

The routing chain (app.py → panel) does not need to change. Only the JS
multi-select toggle and the panel's storage list change.

### How raster overlays currently work (for Feature 3 context)

```
Panel.on_activated
  → MapView.add_raster_overlay(name, path, ...)
  → raster_to_base64(path, max_dim=1024)    ← synchronous, on main thread
  → _addRasterOverlay JS call               ← injects static PNG
```

Feature 3 adds a parallel async path triggered by zoom events, caching the
result by zoom bucket. The initial render on activation continues to run
synchronously (acceptable — happens only once on activation, not on every zoom).

### How contours work (for Feature 3 context)

Contours are generated by `dem_to_contours_geojson()` in `map_widget.py` — it
warps the DEM to a small array, runs matplotlib `ax.contour()`, and converts
the paths to GeoJSON LineStrings. This is a vector overlay (not raster), so it
stays sharp at any zoom. It was used as a substitute for high-res raster display.
Once zoom-responsive re-render is in place, contours are no longer needed as an
automatic overlay, but the function is worth keeping for opt-in display.

---

*Saved to project directory for future sessions.*
*See also: `memory/shaded_relief_improvements.md` for map rendering research.*

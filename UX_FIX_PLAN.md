# PyTOPKAPI GUI — UX Fix Plan

Based on the UX review, organised by priority and difficulty. Each fix includes the affected file(s) and what needs to change.

---

## Fix 1 — Welcome banner on launch (Easy)

**Problem:** On launch, the map shows with no guidance.

**File:** `gui/app.py` — `_build_ui()` and `__init__()`

**Change:**
- After building the map, set a welcome hint that persists until the user clicks a stage:
  ```python
  self._map_view.set_hint("Welcome — click 'Setup' in the ribbon to create a project")
  ```
- In `_on_stage_selected()`, clear this welcome hint (each panel's `on_activated()` already sets its own hint or clears it).

**Lines:** `app.py:176` (after the "ready" log line), and `app.py:312` (`_on_stage_selected`).

---

## Fix 2 — Highlight the active tool button in the ribbon (Easy)

**Problem:** The second ribbon row shows tool buttons (e.g. "Create Project", "Process DEM") but none is visually highlighted when active.

**File:** `gui/widgets/ribbon.py` — `_rebuild_tool_row()` and `_on_step_clicked()`

**Change:**
- Track `self._active_tool_idx` (the old panel index of the currently active tool button).
- In `_rebuild_tool_row()`, compare each `panel_idx` to `_active_tool_idx` and apply a highlighted style (use `_TAB_ACTIVE` background or a distinct border-bottom).
- When `panel_requested` is emitted, also update `_active_tool_idx` and re-style.
- Add a public method `set_active_tool(panel_idx)` called from `MainWindow._on_panel_requested()`.

**Details:**
```python
# In _rebuild_tool_row(), when creating each button:
if panel_idx == self._active_tool_idx:
    btn.setStyleSheet(f"""
        QPushButton {{
            background: {_TAB_ACTIVE.name()};
            color: #ffffff;
            border: 1px solid {_TAB_ACTIVE.name()};
            border-radius: 4px;
            padding: 3px 10px;
            font-size: 11px;
            font-weight: bold;
        }}
    """)
```

Also need to update `MainWindow._on_panel_requested()` and `_on_stage_selected()` to call `self._ribbon.set_active_tool(panel_idx)`.

---

## Fix 3 — Add tooltips to map toolbar buttons (Easy)

**Problem:** Zoom controls and extent buttons are unlabelled.

**File:** `gui/widgets/map_view.py` — `_build_ui()`

**Status:** Already done! Tooltips are already set at lines 86-88:
```python
self._btn_zoom_in  = self._make_btn("+",  "Zoom in  (also: scroll wheel)")
self._btn_zoom_out = self._make_btn("−",  "Zoom out (also: scroll wheel)")
self._btn_zoom_fit = self._make_btn("[ ]", "Zoom to full extent")
```

**No change needed** — tooltips appear on hover. Could optionally add text labels next to the icons for more visibility, but this is low priority.

---

## Fix 4 — Make AOI draw instruction more prominent (Easy)

**Problem:** The instruction "Draw a rectangle..." is easy to miss — appears only in the hint label at the right end of the toolbar.

**File:** `gui/widgets/map_view.py` — `_build_ui()` and hint label styling

**Change:**
- Style the hint label to be more visible: use a highlight background colour, slightly larger font, and/or a left-side icon.
- Add pulsing or highlighted styling to make it stand out:
```python
self._hint_label.setStyleSheet("""
    color: #FFD54F;
    font-size: 12px;
    font-weight: bold;
    background: rgba(26, 111, 196, 0.25);
    border-radius: 4px;
    padding: 2px 8px;
""")
```

---

## Fix 5 — Post-action "next step" prompts (Medium)

**Problem:** After drawing AOI, downloading DEM, or completing terrain analysis, there's no prompt telling the user what to do next.

**Files:** `gui/panels/p01_study_area.py`, `gui/panels/p02_dem_processing.py`

**Changes:**

### p01 — After AOI drawn (`_on_bbox_drawn`):
Add a hint label update or log message:
```python
self._mw.set_map_hint("AOI set — now download the DEM below, or move to 'Process DEM'")
```

### p01 — After DEM download (in `refresh_from_state` when `dem_path` is set):
```python
self._dem_status_label.setText(f"DEM downloaded. Click 'Process DEM' in the ribbon to continue.")
```

### p02 — After terrain analysis (`_reload_map_after_grass`):
```python
self._mw.set_map_hint("Terrain analysis complete — proceed to Catchment & Streams")
```

### General pattern:
Add a `_next_step_label` QLabel to each panel form that updates dynamically to show the next action. Style it with a distinct colour (e.g. `#4ec9b0` teal) so it stands out.

---

## Fix 6 — Update map hint when switching to Process DEM (Easy)

**Problem:** When moving from "Create Project" to "Process DEM", the map hint still says "Draw a rectangle to define the area of interest".

**File:** `gui/panels/p02_dem_processing.py` — `on_activated()`

**Change:** Line 69 already calls `mv.set_draw_mode('none')`, but there's no `set_map_hint()` call. Add:
```python
if s.proj_dem_path:
    self._mw.set_map_hint("Run Terrain Analysis to compute flow routing and shaded relief")
elif s.dem_path:
    self._mw.set_map_hint("Click 'Reproject DEM' to convert to the project CRS")
else:
    self._mw.set_map_hint("Download a DEM first in the 'Create Project' tool")
```

---

## Fix 7 — Preserve layer checkbox state across panel transitions (Medium)

**Problem:** Previously selected layers in the layer panel are deselected when switching panels.

**File:** `gui/widgets/layers_dock.py` — `refresh_from_state()`, and `gui/app.py` — `_on_worker_finished()`

**Root cause:** `refresh_from_state()` calls `self._tree.clear()` and rebuilds all items with `CheckState.Unchecked`. This is called both on worker finish AND on panel transitions (indirectly via `_on_worker_finished`).

**Change:**
1. Before clearing the tree, save which layers are currently checked:
```python
def _save_checked_state(self) -> set:
    """Return set of layer names that are currently checked."""
    checked = set()
    for gi in range(self._tree.topLevelItemCount()):
        group = self._tree.topLevelItem(gi)
        data = group.data(0, Qt.ItemDataRole.UserRole)
        if data and data.get("type") == "basemap":
            if group.checkState(0) == Qt.CheckState.Checked:
                checked.add(data["name"])
            continue
        for ci in range(group.childCount()):
            child = group.child(ci)
            child_data = child.data(0, Qt.ItemDataRole.UserRole)
            if child_data and child.checkState(0) == Qt.CheckState.Checked:
                checked.add(child_data.get("name", ""))
    return checked
```

2. After rebuilding the tree, restore checked state:
```python
def _restore_checked_state(self, checked: set) -> None:
    """Re-check layers that were previously checked."""
    for gi in range(self._tree.topLevelItemCount()):
        group = self._tree.topLevelItem(gi)
        data = group.data(0, Qt.ItemDataRole.UserRole)
        if data and data.get("name") in checked:
            group.setCheckState(0, Qt.CheckState.Checked)
            continue
        for ci in range(group.childCount()):
            child = group.child(ci)
            child_data = child.data(0, Qt.ItemDataRole.UserRole)
            if child_data and child_data.get("name") in checked:
                child.setCheckState(0, Qt.CheckState.Checked)
```

3. Call both in `refresh_from_state()`:
```python
def refresh_from_state(self, state) -> None:
    checked = self._save_checked_state()
    self._suppress_changed = True
    self._tree.clear()
    # ... rebuild tree ...
    self._restore_checked_state(checked)
    self._suppress_changed = False
```

**Note:** Need to also re-add opacity sliders for restored checked layers, and emit visibility signals so overlays are re-added to the map. However, since `on_activated()` already clears all overlays and re-adds them programmatically, we need to be careful not to double-add. The cleanest approach: only preserve the UI checkbox state (visual), and let `on_activated()` handle which overlays are actually on the map. Then the user can re-check any additional layers they want after switching panels.

---

## Fix 8 — Clean up GRASS progress log formatting (Medium)

**Problem:** Progress percentages in the log display run together on one line.

**File:** `gui/workers/fill_worker.py` — `_grass_all()`, stdout streaming loop

**Root cause:** GRASS tools (especially `r.watershed`) output progress as `\r`-terminated lines (carriage return without newline) to overwrite the same line in a terminal. When captured by `subprocess.PIPE` with `text=True`, these `\r` characters cause multiple progress updates to appear concatenated on one line.

**Change:** In the stdout processing loop (line 219-239), filter or clean up progress lines:
```python
for raw_line in proc.stdout:
    line = raw_line.rstrip('\n')
    if not line:
        continue
    # GRASS progress: lines with \r contain terminal progress updates
    # Split on \r and only log the last segment (most recent progress)
    if '\r' in line:
        parts = line.split('\r')
        line = parts[-1].strip()
        if not line:
            continue
        # Skip noisy percentage-only lines (e.g. " 45%")
        if line.rstrip('%').strip().isdigit():
            continue
    self.log_message.emit(line)
```

Apply the same fix to all workers that stream GRASS output: `fill_worker.py`, `stream_worker.py`, `relief_worker.py`.

---

## Fix 9 — Suppress non-fatal GRASS error messages (Easy)

**Problem:** The error `ERROR 6: relief.tif, band 1: SetColorTable() only supported for Byte or UInt16 bands in TIFF format.` is shown to the user.

**File:** `gui/workers/fill_worker.py` — stdout processing loop

**Change:** Filter known non-fatal GDAL/GRASS warnings:
```python
# Known non-fatal messages to suppress
_SUPPRESS_PATTERNS = [
    "SetColorTable() only supported for",
    "color table of type",
]

for raw_line in proc.stdout:
    line = raw_line.rstrip()
    if not line:
        continue
    # Suppress known non-fatal GDAL/GRASS messages
    if any(pat in line for pat in _SUPPRESS_PATTERNS):
        continue
    self.log_message.emit(line)
```

---

## Fix 10 — Layer toggle bugs (Critical — hardest fix)

**Problem:** Multiple layers can't be toggled off: flow accumulation, basins vector, shaded relief.

**Root cause analysis:**

There are TWO independent layer display systems that conflict:

1. **Panel `on_activated()`** — Programmatically adds overlays directly to the map (e.g. `mv.add_raster_overlay("Terrain", ...)` in p02 line 85). These overlays use names like "Terrain", "Basins".

2. **LayersDock checkboxes** — When a user checks a layer, `layer_visibility_changed` signal fires, and `MainWindow._on_layer_visibility_changed()` calls `add_raster_overlay()` or `_add_vector_to_map()` using the display name from `_LAYER_DEFS` (e.g. "Shaded Relief", "Basins (vector)").

The problem: **name mismatch**. When p02 adds "Terrain" overlay, unchecking "Shaded Relief" in the layer dock calls `toggle_overlay("Shaded Relief", False)` — but the JS overlay store has it under "Terrain", not "Shaded Relief". So the toggle has no effect.

Similarly, p02 adds basins as "Basins" but the layer dock refers to it as "Basins (vector)".

**Fix — two approaches (pick one):**

### Approach A: Standardise overlay names (recommended)
Make panels use the same names as `_LAYER_DEFS` in `layers_dock.py`:
- In `p02_dem_processing.py:on_activated()`: change `"Terrain"` → `"Shaded Relief"` (line 85)
- In `p02_dem_processing.py:_add_vector_gpkg_selectable()`: change `"Basins"` → `"Basins (vector)"` (line 543)
- In `p04_stream_network.py`: ensure stream overlays use the same names as _LAYER_DEFS
- Review all panels for name consistency

### Approach B: Overlay name registry
Add a lookup table mapping `_LAYER_DEFS` display names to actual overlay names, and use it in toggle/opacity operations. More complex, less desirable.

**Additional issue:** The `_on_layer_visibility_changed` handler in `app.py` (line 509-531) calls `add_raster_overlay()` when `visible=True` but only `toggle_overlay()` when `visible=False`. The `toggle_overlay()` JS function uses `m.removeLayer(layer)` which is correct, but only works if the overlay name matches what's in `window._overlays`. This is the same name-mismatch problem.

**Also:** When panel `on_activated()` calls `mv.clear_all_overlays()` then re-adds layers, it doesn't update the layer dock's checkbox state. So checked layers in the dock become "phantom" — checked but not actually on the map. This ties into Fix 7.

---

## Fix 11 — Shaded relief rendering degradation after brightness change (Medium)

**Problem:** After re-rendering terrain with brightness=60, the shaded relief degrades significantly.

**File:** `gui/workers/relief_worker.py`

**Investigation needed:** Read the ReliefWorker to understand how it handles the brighten parameter. The issue may be:
1. Relief raster being re-exported as 8-bit (lossy) when brighten > ~40 causes clipping
2. The r.shade `brighten` parameter range may be different from what the UI suggests
3. The re-render may use a different DEM input (filled vs clipped) than the original

**Likely fix:** Clamp brighten values to a reasonable range (0-50), add a warning in the UI if the user sets it too high, or adjust the r.shade command to handle high brighten values better.

---

## Fix 12 — Step progress indicator in ribbon (Easy)

**Problem:** No step-of-N indicator to orient the user.

**File:** `gui/widgets/ribbon.py` — `_StepButton.paintEvent()` or `_rebuild_tool_row()`

**Change:** Already partially implemented! The `_StepButton` paints a stage number (1-5) on each tab (line 166). To make it clearer, add "Step N of 5" text to the tool row:

In `_rebuild_tool_row()`, change the step label (line 273):
```python
step_label = QLabel(f"  Step {idx + 1} of 5 — {STAGE_TITLES[idx]}")
```

---

## Implementation Order (recommended)

1. **Fix 10** — Layer toggle bugs (critical, blocks usability)
2. **Fix 7** — Preserve layer checkbox state (high impact)
3. **Fix 8** — Log formatting (easy, high visibility)
4. **Fix 9** — Suppress GRASS errors (easy, quick win)
5. **Fix 2** — Highlight active tool button (easy, high impact)
6. **Fix 6** — Update map hint on panel switch (easy)
7. **Fix 1** — Welcome banner (easy)
8. **Fix 4** — AOI instruction prominence (easy)
9. **Fix 5** — Next-step prompts (medium, many touchpoints)
10. **Fix 12** — Step progress indicator (easy)
11. **Fix 11** — Shaded relief degradation (needs investigation)
12. ~~Fix 3~~ — Already done (tooltips exist)

---

## Summary of files to modify

| File | Fixes |
|------|-------|
| `gui/app.py` | 1, 2, 7 |
| `gui/widgets/ribbon.py` | 2, 12 |
| `gui/widgets/map_view.py` | 4 |
| `gui/widgets/layers_dock.py` | 7 |
| `gui/panels/p01_study_area.py` | 5 |
| `gui/panels/p02_dem_processing.py` | 5, 6, 10 |
| `gui/panels/p04_stream_network.py` | 10 |
| `gui/workers/fill_worker.py` | 8, 9 |
| `gui/workers/stream_worker.py` | 8 |
| `gui/workers/relief_worker.py` | 8, 11 |

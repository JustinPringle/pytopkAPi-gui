# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the App

```bash
python main.py
```
or user clicks

```
PyTOPKAPI GUI.app
```

The README shows `streamlit run app.py` but the current codebase is a **PyQt6 desktop app**, not Streamlit. The entry point is `main.py`.

## Environment Setup (macOS)

PyQt6 comes from Homebrew, not PyPI. Scientific packages live in a separate venv at `~/.pyenvs/pytopkapi-gui/` (outside iCloud to avoid a macOS Python 3.14 `.pth` file bug). `main.py` wires these paths together at startup.

```bash
# 1. Create the scientific packages venv
python3 -m venv ~/.pyenvs/pytopkapi-gui
source ~/.pyenvs/pytopkapi-gui/bin/activate
pip install -r requirements.txt

# 2. PyQt6 via Homebrew (macOS only)
brew install pyqt@6 qt-webengine

# 3. Install PyTOPKAPI model from fork
pip install git+https://github.com/JustinPringle/PyTOPKAPI.git

# 4. System GDAL + GRASS GIS
brew install gdal grass
```

On macOS, `requirements.txt` lists `PyQt6>=6.7.0` but that line is effectively documentation — the actual PyQt6 used is the Homebrew one.

## Application Purpose

PyTOPKAPI GUI guides the user through four high-level objectives:

1. **Pre-treat the catchment** to create:
   - DEM, slopes, stream network
   - Manning's roughness n (channels + overland)
   - Soil parameters (depth, saturated/residual moisture, conductivity)
2. **Create model input files**: rainfall, ET, external flows, global parameter file
3. **Run the model**
4. **Analyse the simulation**

## Architecture

### Top-level layout

```
main.py              — entry point; patches sys.path for PyQt6/venv/vendor
gui/
  app.py             — MainWindow (QMainWindow): ribbon + central tabs + layer dock + form dock + log dock
  state.py           — ProjectState dataclass: all project data, persisted as project_state.json
  panels/            — 10 workflow step panels (p01–p10), all extending BasePanel
  workers/           — QThread subclasses for background processing, all extending BaseWorker
  widgets/           — Reusable widgets (MapWidget, MapView, LayersDock, RasterCanvas, LogDock, etc.)
core/
  soil_params.py     — HWSD soil code → PyTOPKAPI parameter lookup tables
vendor/
  create_file.py     — vendored PyTOPKAPI parameter file generator (uses networkx for flow routing)
```

### GUI layout

```
+---------------------------------------------------------------+
|  WorkflowRibbon  (5 stage tabs + tool buttons per stage)      |
+----------+----------------------------------+-----------------+
| Layers   |  QTabWidget (Map | Charts)       |  Form Dock      |
| Dock     |                                  |  (right)        |
| (left)   |  MapView wraps a MapWidget       |  Panel forms    |
|          |  (Folium/Leaflet) with toolbar:  |  shown inline   |
|          |  zoom, coordinates, hint label   |  in scrollable  |
|          |                                  |  dock widget    |
+----------+----------------------------------+-----------------+
|  LogDock  (timestamped processing messages)                   |
+---------------------------------------------------------------+
|  StatusBar: label + QProgressBar                              |
+---------------------------------------------------------------+
```

- **5 workflow stages** in ribbon (consolidated from 10 steps): Setup, Catchment, Surface, Model, Results
- **Right dock** — panel forms shown inline in a QDockWidget (replaces floating QDialogs)
- **3-state completion badges**: none (gray), partial (orange), done (green)
- **Only 2 central tabs**: Map and Charts (no separate Raster or Layers tab)
- **Satellite basemap** (Esri World Imagery) is the default tile layer; no OpenStreetMap in DEM Processing map
- **Layers dock** shows checkboxes for all available rasters/vectors; checking a layer overlays it on the Leaflet map with an inline opacity slider (0–100%)

### State flow

`ProjectState` (`gui/state.py`) is a single Python dataclass that acts as the entire application model. It is passed by reference to every panel and worker. Workers must **not** mutate state directly — they emit `finished(dict)` with `{state_field: new_value}` patches, which `MainWindow._on_worker_finished()` applies via `setattr`, then calls `state.save()`. State is persisted as `<project_dir>/project_state.json`. The last-used project directory is remembered in `~/.pytopkapi_gui_recent.json`.

### Panel / Worker pattern

- **Panels** (`gui/panels/p0N_*.py`) each subclass `BasePanel` and implement three methods:
  - `build_form()` — builds and returns a QWidget (called once, cached in `self._form`)
  - `on_activated()` — called when the panel is activated; loads map/raster into central tabs
  - `refresh_from_state()` — called after a worker finishes; updates form widgets from state
  - Forms are shown in the right dock widget (MainWindow._show_panel_form) not as floating dialogs

- **Workers** (`gui/workers/*_worker.py`) each subclass `BaseWorker` (a `QThread`) and emit four signals:
  - `log_message(str)` — plain-text line for the bottom LogDock
  - `progress(int)` — 0–100 for the status bar progress bar
  - `finished(dict)` — state patches to apply
  - `error(str)` — shown as `QMessageBox.critical()`

  Only one worker runs at a time (enforced by `MainWindow.start_worker()`). Workers use a `self.task` string discriminator when one class handles multiple tasks (e.g. `DemWorker` handles `"download"`, `"download_tiles"`, `"reproject"`, `"hillshade"`).

- Panels call `self.start_worker(worker)` which delegates to `MainWindow.start_worker()`.

### Map overlay system

Rasters and vectors are overlaid on the Leaflet map (not in separate tabs):

- **Raster overlays**: `raster_to_base64()` in `map_widget.py` converts GeoTIFF to base64 PNG, added via `L.imageOverlay` in JS
- **Vector overlays**: Read with geopandas, reprojected to WGS84, added via `L.geoJSON` in JS
  - Stream vectors auto-detect `strahler` column for line-width scaling
- **Layer management JS functions** in `_BRIDGE_JS`:
  - `window._addRasterOverlay(name, base64png, bounds, opacity)`
  - `window._addVectorOverlay(name, geojsonStr, color, weight, fillOpacity, weightColumn)`
  - `window._setOverlayOpacity(name, opacity)`
  - `window._toggleOverlay(name, visible)`
  - `window._removeOverlay(name)`
  - `window._toggleBaseMap(visible)`
- **MapView.add_raster_overlay(name, path, cmap, alpha)** — Python-side helper that calls `raster_to_base64` then injects JS
- **LayersDock** emits `layer_visibility_changed` and `layer_opacity_changed` signals wired through MainWindow to MapView

### DEM & Stream Network UX Flow

The guided workflow for DEM and river creation (implemented in p01–p04):

#### Step 1 — Study Area (p01)
1. User opens the app → sees a global satellite map
2. Draws a rectangle over the area of interest
3. Selects project CRS (default: UTM Zone 36S for KwaZulu-Natal)
4. Downloads 30m SRTM data (free AWS tiles, no key required)

#### Step 2 — DEM Processing (p02)  [4 guided sections]
1. **Reproject DEM** — one button, converts WGS84 → project CRS via gdalwarp
2. **Terrain Analysis** — single GRASS session with two user controls:
   - `relief_zscale` (float, default 3.0) — vertical exaggeration for `r.relief`; user can iterate until the terrain "feels right"
   - `stream_threshold` (int, default 500) — accumulation cells for basin delineation; larger = fewer, bigger basins
   - After completion: **shaded relief appears on the map automatically** — satellite imagery is replaced by the beautiful GRASS terrain render. A legend is also plotted showing the elevation.
3. **Reference Overlays** — optional shapefiles (rivers, gauges, boundaries) added as map overlays

#### Step 3 — Watershed (p03)
1. GRASS `r.watershed` computes the watershed, user defined the threshold, smaller = larger water shed.
2. GRASS `r.to_vect` converts the watersheds to vectors.
3. GRASS `v.extract` is used to extract all the watersheds the user wants to work with.
4. GRASS `d.vect` is used to display the vector with a colour = white but no fill.
5. steps 1-4 are re run for the larger watershed that contains all the smaller ones. this is used as the mask to clip the DEM.
6. GRASS `r.slope.aspect` computes slope raster

#### Step 4 — Stream Network (p04)
1. GRASS `r.watershed` is then used to create the flow accumulation. This is also plotted using `r.shade` and the legend is plotted on a log scale.
2. GRASS `r.stream.extract` + `r.stream.order` extract streams and compute Strahler ordering. The elevation var is the DEM, and the accumulation is the flow accumulation as previous.
3. the colours are made with: `r.colors map=strahler color=water`
4. To visualize stream order set the line weight of the vector map of streams to one of the stream order attributes in the table with d.vect. Set the symbol size to zero to hide the stream vertices. Optionally add a scale factor for the line width. Then set the color table to the same stream order attribute with v.colors.
- On activation: **shaded relief + Strahler-colored stream network displayed on map**
- Strahler order drives line width (thicker = higher order)
- Final map should resemble the cartographic reference in `elevation-with-streams.png`

### Cartographic target (elevation-with-streams.png)

The desired final display for Step 4:
- Shaded relief as background (GRASS `r.shade` composite: elevation draped over relief)
- Stream network coloured blue, line width proportional to Strahler order
- Strahler order legend
- Clean, dark cartographic style

GRASS commands to achieve this (already implemented in workers):
```python
# Flow accumulation + accumulation shading
r.watershed -a -b elevation=elevation threshold=10000 accumulation=flow_accumulation
r.shade shade=relief color=flow_accumulation output=shaded_accumulation brighten=80

# Stream network extraction + ordering
r.stream.extract elevation=elevation accumulation=flow_accumulation threshold=200 \
    stream_raster=stream_raster direction=flow_direction
r.stream.order stream_rast=stream_raster direction=flow_direction elevation=elevation \
    accumulation=flow_accumulation stream_vect=streams strahler=strahler
```

### GRASS GIS workers

All GRASS workers follow the same pattern: write a Python script to a temp file, run `grass --tmp-location EPSG:<N> --exec python3 <script.py>`, stream stdout for progress, parse output, export GeoTIFFs.

| Worker | GRASS Commands | Key Outputs |
|--------|---------------|-------------|
| **FillWorker** | r.fill.dir, r.watershed (-ab), r.relief (zscale from state.relief_zscale), r.shade (brighten=30), r.to.vect | filled DEM, flow dir, accumulation, drainage, basins (raster+vector), relief, shaded relief |
| **WatershedWorker** | r.water.outlet, r.slope.aspect | catchment mask, slope |
| **StreamWorker** | g.extension (r.stream.order), r.stream.extract, r.stream.order, v.out.ogr | stream network raster, Strahler raster, streams vector (GeoPackage) |

Tutorial reference: https://baharmon.github.io/watersheds-in-grass

### Project directory structure (created by Step 1)

```
<project_dir>/
  project_state.json
  rasters/           — GeoTIFFs + GeoPackages (DEM, flow direction, accumulation, basins, relief, mask, slope, streams, soil, land cover)
  parameter_files/   — cell_param.dat, global_param.dat, TOPKAPI.ini, param_setup.ini
  forcing_variables/ — rainfields.h5, ET.h5
  results/           — simulation_output.h5
```

### Workflow stages (5-stage ribbon) and their key outputs

| Stage | Name | Old Panels | Key state fields set |
|-------|------|-----------|----------------------|
| 1 | Project Setup | p01 + p02 | `bbox`, `dem_path`, `proj_dem_path`, `filled_dem_path`, `fdir_path`, `accum_path`, `drain_ws_path`, `basins_path`, `relief_path`, `shaded_relief_path`, `relief_zscale` |
| 2 | Catchment & Streams | p03 + p04 | `mask_path`, `slope_path`, `outlet_xy`, `streamnet_path`, `strahler_path`, `streams_gpkg_path` |
| 3 | Surface Properties | p05 + p06 | `hwsd_*_path` fields, `soil_ready=True`, `mannings_path`, `landcover_ready=True` |
| 4 | Run Model | p07 + p08 + p09 | `cell_param_path`, `global_param_path`, `ini_path`, `rainfields_path`, `et_path`, `results_path` |
| 5 | Results | p10 | (reads `results_path`) |

Stage completion uses 3 states: `none` (gray), `partial` (orange), `done` (green) — see `state.stage_status()`.

### External tool dependencies

Several workers shell out via `subprocess` to system tools that must be on `PATH`:
- `gdalwarp`, `gdaldem` — DEM reprojection and hillshade
- `grass` — DEM sink-filling (`r.fill.dir`), flow routing (`r.watershed`), relief (`r.relief`, `r.shade`), basin vectorization (`r.to.vect`), slope (`r.slope.aspect`), outlet delineation (`r.water.outlet`), stream extraction (`r.stream.extract`, `r.stream.order`)

### Panel lazy loading

Panels are imported on first activation via `importlib.import_module()` in `app.py:_load_panel_class()` to keep startup time low. Panel instances are cached in `MainWindow._panels[0..9]`.

### GUI colour display theme

- Minimalistic, dark background with light fonts
- Google Fonts (Lato family preferred — matches GRASS tutorial aesthetic)
- Accent colours on completed workflow tasks (green badge = done, orange = partial)
- Satellite imagery as default basemap (no OpenStreetMap in DEM processing)
- Shaded relief (GRASS r.shade output) replaces satellite basemap after terrain analysis
- Clean cartographic style inspired by GRASS watershed tutorial visualisations
- Stream colours: blue (#1565C0) with Strahler-proportional line weight
- Basin boundaries: light blue (#4FC3F7), thin stroke, low fill opacity

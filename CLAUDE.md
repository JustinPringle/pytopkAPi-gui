# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the App

```bash
python main.py
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

# 4. System GDAL (for gdalwarp / gdaldem subprocess calls)
brew install gdal
```

On macOS, `requirements.txt` lists `PyQt6>=6.7.0` but that line is effectively documentation — the actual PyQt6 used is the Homebrew one.

## Architecture

### Top-level layout

```
main.py              — entry point; patches sys.path for PyQt6/venv/vendor
gui/
  app.py             — MainWindow (QMainWindow): docks + central tabs + worker management
  state.py           — ProjectState dataclass: all project data, persisted as project_state.json
  panels/            — 10 workflow step panels (p01–p10), all extending BasePanel
  workers/           — QThread subclasses for background processing, all extending BaseWorker
  widgets/           — Reusable widgets (MapWidget, RasterCanvas, HydrographCanvas, LogDock, SoilTable)
core/
  soil_params.py     — HWSD soil code → PyTOPKAPI parameter lookup tables
vendor/
  create_file.py     — vendored PyTOPKAPI parameter file generator (uses networkx for flow routing)
```

### State flow

`ProjectState` (`gui/state.py`) is a single Python dataclass that acts as the entire application model. It is passed by reference to every panel and worker. Workers must **not** mutate state directly — they emit `finished(dict)` with `{state_field: new_value}` patches, which `MainWindow._on_worker_finished()` applies via `setattr`, then calls `state.save()`. State is persisted as `<project_dir>/project_state.json`. The last-used project directory is remembered in `~/.pytopkapi_gui_recent.json`.

### Panel / Worker pattern

- **Panels** (`gui/panels/p0N_*.py`) each subclass `BasePanel` and implement three methods:
  - `build_form()` — builds and returns the right-dock QWidget (called once, cached in `self._form`)
  - `on_activated()` — called when the user navigates to this step; loads map/raster into central tabs
  - `refresh_from_state()` — called after a worker finishes; updates form widgets from state

- **Workers** (`gui/workers/*_worker.py`) each subclass `BaseWorker` (a `QThread`) and emit four signals:
  - `log_message(str)` — plain-text line for the bottom LogDock
  - `progress(int)` — 0–100 for the status bar progress bar
  - `finished(dict)` — state patches to apply
  - `error(str)` — shown as `QMessageBox.critical()`

  Only one worker runs at a time (enforced by `MainWindow.start_worker()`). Workers use a `self.task` string discriminator when one class handles multiple tasks (e.g. `DemWorker` handles `"download"`, `"download_tiles"`, `"reproject"`, `"hillshade"`).

- Panels call `self.start_worker(worker)` which delegates to `MainWindow.start_worker()`.

### Central tab system

`MainWindow` owns three central tabs (Map, Raster, Charts). Panels swap their content by calling `self._mw.set_map_widget(w)`, `set_raster_widget(w)`, or `set_chart_widget(w)`.

- **MapWidget** (`gui/widgets/map_widget.py`) — `QWebEngineView` rendering Folium HTML with a `QWebChannel` bridge (`MapBridge`) that receives rectangle AOI draws and outlet marker placements back from JavaScript.
- **RasterCanvas** — matplotlib `FigureCanvas` for displaying GeoTIFF rasters.
- **HydrographCanvas** — matplotlib `FigureCanvas` for simulation results (hydrograph, FDC).

### Project directory structure (created by Step 1)

```
<project_dir>/
  project_state.json
  rasters/           — GeoTIFFs (DEM, flow direction, accumulation, mask, slope, streams, soil, land cover)
  parameter_files/   — cell_param.dat, global_param.dat, TOPKAPI.ini, param_setup.ini
  forcing_variables/ — rainfields.h5, ET.h5
  results/           — simulation_output.h5
```

### Workflow steps and their key outputs in state

| Step | Panel | Key state fields set |
|------|-------|----------------------|
| 1 | Study Area | `bbox`, `dem_path`, `proj_dem_path`, `ot_api_key` |
| 2 | DEM Processing | `filled_dem_path`, `fdir_path`, `accum_path` |
| 3 | Watershed | `mask_path`, `slope_path`, `outlet_xy` |
| 4 | Stream Network | `streamnet_path`, `strahler_path` |
| 5 | Soil Parameters | `hwsd_*_path` fields, `soil_ready=True` |
| 6 | Land Cover | `mannings_path`, `landcover_ready=True` |
| 7 | Parameter Files | `cell_param_path`, `global_param_path`, `ini_path` |
| 8 | Forcing Data | `rainfields_path`, `et_path` |
| 9 | Run Model | `results_path` |
| 10 | Results | (reads `results_path`) |

### External tool dependencies

Several workers shell out via `subprocess` to system tools that must be on `PATH`:
- `gdalwarp`, `gdaldem` — DEM reprojection and hillshade
- `grass` — DEM sink-filling (`r.fill.dir`), watershed delineation (`r.watershed`), slope (`r.slope.aspect`), outlet delineation (`r.water.outlet`)

### Panel lazy loading

Panels are imported on first activation via `importlib.import_module()` in `app.py:_load_panel_class()` to keep startup time low. Panel instances are cached in `MainWindow._panels[0..9]`.

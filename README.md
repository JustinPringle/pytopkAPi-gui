# PyTOPKAPI GUI

A Streamlit-based graphical interface for setting up and running the
[PyTOPKAPI](https://github.com/JustinPringle/PyTOPKAPI) physically-based
distributed hydrological model — similar in concept to PCSWMM but built
entirely in Python.

## Workflow

| Step | Page | Description |
|------|------|-------------|
| 1 | Study Area | Define AOI on interactive map & download SRTM DEM |
| 2 | DEM Processing | Fill sinks, compute flow direction & accumulation |
| 3 | Watershed | Set outlet point & delineate watershed mask |
| 4 | Stream Network | Extract streams, Strahler order, channel Manning's n |
| 5 | Soil Parameters | HWSD → hydraulic soil properties |
| 6 | Land Cover | Land cover classification → overland Manning's n |
| 7 | Parameter Files | Generate `cell_param.dat` & `global_param.dat` |
| 8 | Forcing Data | Obscape rainfall + ET → HDF5 forcing files |
| 9 | Run Model | Configure calibration factors & run PyTOPKAPI |
| 10 | Results | Hydrograph, FDC, soil moisture maps & export |

## Installation

```bash
# 1. Clone this repo
git clone https://github.com/JustinPringle/pytopkapi-gui.git
cd pytopkapi-gui

# 2. Create conda environment
conda create -n pytopkapi-gui python=3.11 gdal rasterio -c conda-forge
conda activate pytopkapi-gui

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Install PyTOPKAPI from fork
pip install git+https://github.com/JustinPringle/PyTOPKAPI.git

# 5. Run the app
streamlit run app.py
```

## Data Requirements

- **OpenTopography API key** — free at https://opentopography.org/developers
- **HWSD raster** (`hwsd.bil`) — from https://www.fao.org/soils-portal/soil-survey/soil-maps-and-databases/harmonized-world-soil-database-v12/
- **Obscape API credentials** — for real-time/historical rainfall

## Key Dependencies

| Library | Purpose |
|---------|---------|
| `streamlit` | Web-based GUI framework |
| `pysheds` | DEM processing & watershed delineation |
| `rasterio` / `gdal` | Raster I/O |
| `h5py` | HDF5 forcing file creation |
| `folium` / `streamlit-folium` | Interactive maps |
| `plotly` | Interactive result plots |
| `bmi-topography` | OpenTopography API (SRTM download) |

## References

- Fatoyinbo, B.S. (2018). *Modelling in Ungauged Catchments Using PyTOPKAPI: A Case Study of Mhlanga Catchment*. MSc Thesis, UKZN.
- Liu, Z. & Todini, E. (2002). Towards a comprehensive physically-based rainfall-runoff model. *Hydrology and Earth System Sciences*, 6(5), 859–881.
- Rawls, W.J. et al. (1982). Estimation of soil water properties. *Transactions of the ASAE*, 25(5), 1316–1320.

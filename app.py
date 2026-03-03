"""
PyTOPKAPI GUI
=============
A Streamlit-based graphical interface for setting up and running
the PyTOPKAPI physically-based distributed hydrological model.

Run with:
    streamlit run app.py
"""

import streamlit as st

# ── Page configuration ────────────────────────────────────────────────────────
st.set_page_config(
    page_title="PyTOPKAPI GUI",
    page_icon="🌊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Session state defaults ────────────────────────────────────────────────────
defaults = {
    "project_dir": None,
    "project_name": None,
    "bbox": None,               # (south, north, west, east) in WGS84
    "crs": "EPSG:32736",        # Default: UTM Zone 36S (KwaZulu-Natal)
    "dem_path": None,
    "filled_dem_path": None,
    "fdir_path": None,
    "accum_path": None,
    "mask_path": None,
    "slope_path": None,
    "streamnet_path": None,
    "strahler_path": None,
    "cell_param_path": None,
    "global_param_path": None,
    "rainfields_path": None,
    "et_path": None,
    "results_path": None,
    "n_cells": None,
    "outlet_xy": None,          # (lon, lat) WGS84
    "stream_threshold": 500,    # default accumulation threshold
    "obscape_api_key": None,
    "obscape_base_url": None,
}

for key, val in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = val

# ── Landing page ──────────────────────────────────────────────────────────────
st.title("🌊 PyTOPKAPI GUI")
st.markdown(
    """
    A step-by-step interface for building and running the
    [PyTOPKAPI](https://github.com/JustinPringle/PyTOPKAPI)
    physically-based distributed hydrological model.

    ---
    ### Workflow
    Use the **sidebar** to navigate through the model setup steps in order:

    | Step | Page | Description |
    |------|------|-------------|
    | 1 | 📍 Study Area | Define catchment boundary & download SRTM DEM |
    | 2 | 🏔️ DEM Processing | Fill sinks, compute flow direction & accumulation |
    | 3 | 🗺️ Watershed | Set outlet point & delineate watershed mask |
    | 4 | 🌊 Stream Network | Extract streams, compute Strahler order & slopes |
    | 5 | 🪨 Soil Parameters | Apply HWSD soil data → hydraulic properties |
    | 6 | 🌿 Land Cover | Classify land cover → overland Manning's roughness |
    | 7 | 📄 Parameter Files | Generate `cell_param.dat` & `global_param.dat` |
    | 8 | 🌧️ Forcing Data | Fetch Obscape rainfall & compute ET → HDF5 files |
    | 9 | ▶️ Run Model | Configure & run PyTOPKAPI |
    | 10 | 📈 Results | Hydrograph, soil moisture maps & flow statistics |

    ---
    ### Getting Started
    👈 **Start with Step 1 in the sidebar** — define your study area.
    """
)

# ── Sidebar status panel ──────────────────────────────────────────────────────
with st.sidebar:
    st.header("Project Status")

    checks = [
        ("Study area defined",   st.session_state.bbox is not None),
        ("DEM downloaded",       st.session_state.dem_path is not None),
        ("DEM processed",        st.session_state.filled_dem_path is not None),
        ("Watershed delineated", st.session_state.mask_path is not None),
        ("Stream network ready", st.session_state.streamnet_path is not None),
        ("Soil rasters ready",   st.session_state.get("soil_ready", False)),
        ("Land cover ready",     st.session_state.get("landcover_ready", False)),
        ("Parameter files ready",st.session_state.cell_param_path is not None),
        ("Forcing files ready",  st.session_state.rainfields_path is not None),
        ("Results available",    st.session_state.results_path is not None),
    ]

    for label, done in checks:
        icon = "✅" if done else "⬜"
        st.write(f"{icon} {label}")

    st.divider()
    if st.session_state.project_dir:
        st.caption(f"📁 `{st.session_state.project_dir}`")
    if st.session_state.n_cells:
        st.caption(f"🔢 {st.session_state.n_cells:,} catchment cells")

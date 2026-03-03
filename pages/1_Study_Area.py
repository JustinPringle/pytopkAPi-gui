"""
Page 1 — Study Area
===================
- Define Area of Interest by drawing a bounding box on an interactive map
- Set project directory and CRS
- Download SRTM DEM via OpenTopography API (bmi-topography)
- Preview downloaded DEM
"""

import os
import streamlit as st
import folium
from streamlit_folium import st_folium
import numpy as np

st.set_page_config(page_title="Study Area | PyTOPKAPI GUI", page_icon="📍", layout="wide")
st.title("📍 Step 1 — Study Area")

# ── Project setup ─────────────────────────────────────────────────────────────
st.header("1.1  Project Setup")

col1, col2 = st.columns(2)
with col1:
    project_name = st.text_input(
        "Project name",
        value=st.session_state.get("project_name") or "umhlanga",
        help="Used as the working directory name.",
    )
with col2:
    base_dir = st.text_input(
        "Base directory",
        value=os.path.expanduser("~/Documents/projects/pytopkapi-gui/project"),
        help="Parent folder for all project files.",
    )

project_dir = os.path.join(base_dir, project_name)

if st.button("📁 Create / Open Project"):
    os.makedirs(os.path.join(project_dir, "rasters"), exist_ok=True)
    os.makedirs(os.path.join(project_dir, "parameter_files"), exist_ok=True)
    os.makedirs(os.path.join(project_dir, "forcing_variables"), exist_ok=True)
    os.makedirs(os.path.join(project_dir, "results"), exist_ok=True)
    st.session_state.project_dir = project_dir
    st.session_state.project_name = project_name
    st.success(f"Project ready at `{project_dir}`")

# ── CRS ───────────────────────────────────────────────────────────────────────
st.header("1.2  Coordinate Reference System")

crs_options = {
    "UTM Zone 36S — WGS84 (KwaZulu-Natal, EPSG:32736)": "EPSG:32736",
    "UTM Zone 35S — WGS84 (EPSG:32735)": "EPSG:32735",
    "Lo31 / Cape (EPSG:22235)": "EPSG:22235",
    "Custom": "custom",
}
crs_label = st.selectbox("Target projection for all rasters", list(crs_options.keys()))
if crs_options[crs_label] == "custom":
    crs = st.text_input("Enter EPSG code (e.g. EPSG:32736)")
else:
    crs = crs_options[crs_label]
st.session_state.crs = crs
st.caption(f"Selected CRS: `{crs}`")

# ── Interactive AOI map ───────────────────────────────────────────────────────
st.header("1.3  Define Area of Interest")
st.info(
    "🖱️ **Draw a rectangle** on the map to define your catchment bounding box.  \n"
    "Use the draw toolbar on the left side of the map."
)

# Centred on uMhlanga by default
default_centre = [-29.71, 31.06]
m = folium.Map(location=default_centre, zoom_start=11, tiles="OpenStreetMap")

# Add satellite imagery as an optional layer
folium.TileLayer(
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attr="Esri",
    name="Satellite",
).add_to(m)

# Enable rectangle drawing
from folium.plugins import Draw
Draw(
    draw_options={
        "polyline": False, "polygon": False, "circle": False,
        "marker": False, "circlemarker": False,
        "rectangle": True,
    },
    edit_options={"edit": True},
).add_to(m)

folium.LayerControl().add_to(m)

map_data = st_folium(m, width=900, height=500, returned_objects=["all_drawings"])

# Parse drawn rectangle
bbox = None
if map_data and map_data.get("all_drawings"):
    drawings = map_data["all_drawings"]
    if drawings:
        coords = drawings[-1]["geometry"]["coordinates"][0]
        lons = [c[0] for c in coords]
        lats = [c[1] for c in coords]
        bbox = {
            "south": min(lats), "north": max(lats),
            "west":  min(lons), "east":  max(lons),
        }
        st.session_state.bbox = bbox

if st.session_state.bbox:
    b = st.session_state.bbox
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("South", f"{b['south']:.4f}°")
    col2.metric("North", f"{b['north']:.4f}°")
    col3.metric("West",  f"{b['west']:.4f}°")
    col4.metric("East",  f"{b['east']:.4f}°")
    area_km2 = (b['north'] - b['south']) * 111 * (b['east'] - b['west']) * 111 * np.cos(np.radians((b['north'] + b['south']) / 2))
    st.caption(f"Approximate bounding box area: **{area_km2:.1f} km²**")
else:
    st.warning("No bounding box drawn yet — draw a rectangle on the map above.")

# ── SRTM Download ─────────────────────────────────────────────────────────────
st.header("1.4  Download SRTM DEM")

col1, col2 = st.columns(2)
with col1:
    dem_type = st.selectbox(
        "DEM dataset",
        ["SRTMGL1",   # 30m
         "SRTMGL3",   # 90m
         "COP30",     # Copernicus 30m
         "NASADEM"],  # NASA DEM 30m
        help="SRTMGL1 = 30m resolution (recommended for PyTOPKAPI at 30m cell size).",
    )
with col2:
    api_key = st.text_input(
        "OpenTopography API key",
        type="password",
        value=st.session_state.get("ot_api_key", ""),
        help="Get a free key at https://opentopography.org/developers",
    )
    if api_key:
        st.session_state["ot_api_key"] = api_key

if st.button("⬇️ Download DEM", disabled=(st.session_state.bbox is None or not api_key)):
    if not st.session_state.project_dir:
        st.error("Create a project first (Step 1.1).")
    else:
        b = st.session_state.bbox
        out_path = os.path.join(st.session_state.project_dir, "rasters", "raw_dem.tif")

        with st.spinner(f"Downloading {dem_type} DEM from OpenTopography…"):
            try:
                import requests
                url = (
                    f"https://portal.opentopography.org/API/globaldem"
                    f"?demtype={dem_type}"
                    f"&south={b['south']}&north={b['north']}"
                    f"&west={b['west']}&east={b['east']}"
                    f"&outputFormat=GTiff"
                    f"&API_Key={api_key}"
                )
                r = requests.get(url, timeout=120)
                r.raise_for_status()
                with open(out_path, "wb") as f:
                    f.write(r.content)
                st.session_state.dem_path = out_path
                st.success(f"DEM saved to `{out_path}`")
            except Exception as e:
                st.error(f"Download failed: {e}")

# ── Preview DEM ───────────────────────────────────────────────────────────────
if st.session_state.dem_path and os.path.exists(st.session_state.dem_path):
    st.header("1.5  DEM Preview")
    try:
        import rasterio
        import matplotlib.pyplot as plt
        import matplotlib.colors as mcolors

        with rasterio.open(st.session_state.dem_path) as src:
            data = src.read(1).astype(float)
            nodata = src.nodata
            if nodata is not None:
                data[data == nodata] = np.nan
            res = src.res
            shape = src.shape

        col1, col2, col3 = st.columns(3)
        col1.metric("Columns × Rows", f"{shape[1]} × {shape[0]}")
        col2.metric("Resolution", f"{res[0]:.1f}° × {res[1]:.1f}°")
        col3.metric("Elevation range", f"{np.nanmin(data):.0f} – {np.nanmax(data):.0f} m")

        fig, ax = plt.subplots(figsize=(10, 5))
        im = ax.imshow(data, cmap="terrain", interpolation="nearest")
        plt.colorbar(im, ax=ax, label="Elevation (m)")
        ax.set_title("Raw SRTM DEM")
        ax.axis("off")
        st.pyplot(fig)
        plt.close()
    except Exception as e:
        st.warning(f"Could not preview DEM: {e}")

# ── Navigation hint ───────────────────────────────────────────────────────────
st.divider()
if st.session_state.dem_path:
    st.success("✅ Study area and DEM ready. Proceed to **🏔️ DEM Processing** in the sidebar.")

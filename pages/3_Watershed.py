"""
Page 3 — Watershed Delineation
================================
- User clicks outlet point on map
- Snap to highest accumulation cell
- Delineate watershed mask (r_mask.tif)
- Compute slope raster (r_slope.tif)
- Clip all rasters to watershed extent
"""

import os
import numpy as np
import streamlit as st
import folium
from streamlit_folium import st_folium
import matplotlib.pyplot as plt

st.set_page_config(page_title="Watershed | PyTOPKAPI GUI", page_icon="🗺️", layout="wide")
st.title("🗺️ Step 3 — Watershed Delineation")

if not st.session_state.get("accum_path"):
    st.warning("⚠️ Complete **Step 2 — DEM Processing** first.")
    st.stop()

# ── 3.1 Select outlet point ───────────────────────────────────────────────────
st.header("3.1  Select Outlet Point")
st.info("🖱️ **Click on the map** at the river mouth / catchment outlet.")

b = st.session_state.bbox or {}
centre = [
    (b.get("south", -29.71) + b.get("north", -29.65)) / 2,
    (b.get("west",  31.00)  + b.get("east",  31.10))  / 2,
]

m = folium.Map(location=centre, zoom_start=12, tiles="OpenStreetMap")
folium.TileLayer(
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attr="Esri", name="Satellite",
).add_to(m)
from folium.plugins import Draw
Draw(
    draw_options={
        "marker": True, "polyline": False, "polygon": False,
        "rectangle": False, "circle": False, "circlemarker": False,
    }
).add_to(m)

# Show existing outlet if set
if st.session_state.outlet_xy:
    lon, lat = st.session_state.outlet_xy
    folium.Marker([lat, lon], tooltip="Outlet", icon=folium.Icon(color="red", icon="star")).add_to(m)

folium.LayerControl().add_to(m)
map_data = st_folium(m, width=900, height=450, returned_objects=["last_clicked", "all_drawings"])

# Parse clicked point
if map_data and map_data.get("all_drawings"):
    drawings = map_data["all_drawings"]
    if drawings:
        coords = drawings[-1]["geometry"]["coordinates"]
        st.session_state.outlet_xy = (coords[0], coords[1])  # (lon, lat)

if st.session_state.outlet_xy:
    lon, lat = st.session_state.outlet_xy
    st.success(f"Outlet set at **{lat:.5f}°N, {lon:.5f}°E**")
else:
    st.warning("No outlet point placed yet — click on the map above.")

# ── 3.2 Delineate Watershed ───────────────────────────────────────────────────
st.header("3.2  Delineate Watershed")

mask_path  = os.path.join(st.session_state.project_dir, "rasters", "r_mask.tif")
slope_path = os.path.join(st.session_state.project_dir, "rasters", "r_slope.tif")

if st.button("🗺️ Delineate Watershed", disabled=(not st.session_state.outlet_xy)):
    with st.spinner("Delineating watershed with pysheds…"):
        try:
            from pysheds.grid import Grid
            import rasterio
            from rasterio.transform import from_bounds
            from pyproj import Transformer

            grid = Grid.from_raster(st.session_state.filled_dem_path)
            dem  = grid.read_raster(st.session_state.filled_dem_path)
            fdir = grid.flowdir(dem)
            acc  = grid.accumulation(fdir)

            # Transform outlet from WGS84 → raster CRS
            lon, lat = st.session_state.outlet_xy
            with rasterio.open(st.session_state.filled_dem_path) as src:
                raster_crs = src.crs.to_epsg()

            if raster_crs and raster_crs != 4326:
                transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{raster_crs}", always_xy=True)
                x_out, y_out = transformer.transform(lon, lat)
            else:
                x_out, y_out = lon, lat

            # Snap to highest accumulation
            x_snap, y_snap = grid.snap_to_mask(acc > 100, (x_out, y_out))

            # Delineate catchment
            catch = grid.catchment(x_snap, y_snap, fdir, xytype="coordinate")
            catch_arr = np.array(catch).astype(np.uint8)

            # Save mask (1 = catchment, 0 = outside)
            with rasterio.open(st.session_state.filled_dem_path) as src:
                profile = src.profile.copy()
            profile.update(dtype="uint8", nodata=255)
            with rasterio.open(mask_path, "w", **profile) as dst:
                dst.write(catch_arr, 1)

            n_cells = int(catch_arr.sum())
            st.session_state.mask_path  = mask_path
            st.session_state.n_cells    = n_cells
            st.success(f"Watershed delineated — **{n_cells:,} cells** ({n_cells * 0.0009:.2f} km² at 30m)")

        except Exception as e:
            st.error(f"Watershed delineation failed: {e}")

if st.session_state.mask_path and os.path.exists(st.session_state.mask_path):
    import rasterio
    with rasterio.open(st.session_state.mask_path) as src:
        mask = src.read(1).astype(float)
        mask[mask == 255] = np.nan
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.imshow(mask, cmap="Greens", interpolation="nearest")
    ax.set_title(f"Watershed Mask  ({st.session_state.n_cells:,} cells)")
    ax.axis("off")
    st.pyplot(fig)
    plt.close()

# ── 3.3 Compute Slope ─────────────────────────────────────────────────────────
st.header("3.3  Compute Surface Slope")
st.caption("Slope in degrees — used for hillslope tangent (tan β) in cell_param.dat.")

if st.button("📐 Compute Slope", disabled=(not st.session_state.mask_path)):
    with st.spinner("Computing slope…"):
        try:
            import subprocess, rasterio
            result = subprocess.run([
                "gdaldem", "slope",
                st.session_state.filled_dem_path,
                slope_path,
                "-p",          # output in degrees (not percent)
                "-of", "GTiff",
            ], capture_output=True, text=True)
            if result.returncode != 0:
                st.error(f"gdaldem error: {result.stderr}")
            else:
                st.session_state.slope_path = slope_path
                st.success(f"Slope raster saved to `{slope_path}`")
        except Exception as e:
            st.error(f"Slope computation failed: {e}")

if st.session_state.slope_path and os.path.exists(st.session_state.slope_path):
    import rasterio
    with rasterio.open(st.session_state.slope_path) as src:
        slope = src.read(1).astype(float)
        nd = src.nodata
        if nd:
            slope[slope == nd] = np.nan
    fig, ax = plt.subplots(figsize=(8, 4))
    im = ax.imshow(slope, cmap="YlOrRd", interpolation="nearest", vmin=0, vmax=30)
    plt.colorbar(im, ax=ax, label="Slope (degrees)", shrink=0.8)
    ax.set_title("Surface Slope")
    ax.axis("off")
    st.pyplot(fig)
    plt.close()

st.divider()
if st.session_state.slope_path:
    st.success("✅ Watershed delineated. Proceed to **🌊 Stream Network** in the sidebar.")

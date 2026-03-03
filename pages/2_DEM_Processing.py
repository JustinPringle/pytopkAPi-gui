"""
Page 2 — DEM Processing
=======================
- Reproject raw DEM to local UTM CRS
- Fill pits, depressions, and resolve flats (pysheds)
- Compute D8 flow direction (GRASS coding, 1-8)
- Compute flow accumulation
- Preview each output
"""

import os
import numpy as np
import streamlit as st
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors

st.set_page_config(page_title="DEM Processing | PyTOPKAPI GUI", page_icon="🏔️", layout="wide")
st.title("🏔️ Step 2 — DEM Processing")

if not st.session_state.get("dem_path"):
    st.warning("⚠️ No DEM found. Complete **Step 1 — Study Area** first.")
    st.stop()


def show_raster(data, title, cmap="terrain", label=""):
    """Helper to plot a 2-D numpy array."""
    fig, ax = plt.subplots(figsize=(8, 4))
    im = ax.imshow(data, cmap=cmap, interpolation="nearest")
    plt.colorbar(im, ax=ax, label=label, shrink=0.8)
    ax.set_title(title)
    ax.axis("off")
    st.pyplot(fig)
    plt.close()


# ── 2.1 Reproject ─────────────────────────────────────────────────────────────
st.header("2.1  Reproject to Local CRS")
st.caption(f"Target CRS: `{st.session_state.crs}`")

proj_path = os.path.join(st.session_state.project_dir, "rasters", "dem_projected.tif")

if st.button("🔁 Reproject DEM"):
    with st.spinner(f"Reprojecting to {st.session_state.crs}…"):
        try:
            import subprocess
            result = subprocess.run([
                "gdalwarp",
                "-t_srs", st.session_state.crs,
                "-r", "bilinear",
                "-of", "GTiff",
                st.session_state.dem_path,
                proj_path,
            ], capture_output=True, text=True)
            if result.returncode != 0:
                st.error(f"gdalwarp error: {result.stderr}")
            else:
                st.session_state["proj_dem_path"] = proj_path
                st.success(f"Reprojected DEM saved to `{proj_path}`")
        except Exception as e:
            st.error(f"Reprojection failed: {e}")

if os.path.exists(proj_path):
    st.session_state["proj_dem_path"] = proj_path
    st.caption(f"✅ Reprojected DEM exists at `{proj_path}`")

# ── 2.2 Fill DEM ──────────────────────────────────────────────────────────────
st.header("2.2  Fill DEM (Pits → Depressions → Flats)")
st.info(
    "Three conditioning steps remove artifacts that would prevent proper flow routing:\n"
    "- **Fill pits** — single-cell local minima\n"
    "- **Fill depressions** — multi-cell enclosed basins\n"
    "- **Resolve flats** — areas of constant elevation"
)

filled_path = os.path.join(st.session_state.project_dir, "rasters", "dem_filled.tif")

if st.button("🏔️ Fill DEM", disabled=(not st.session_state.get("proj_dem_path"))):
    src_path = st.session_state.get("proj_dem_path") or st.session_state.dem_path
    with st.spinner("Filling DEM with pysheds…"):
        try:
            from pysheds.grid import Grid
            import rasterio
            from rasterio.transform import from_bounds

            grid = Grid.from_raster(src_path)
            dem  = grid.read_raster(src_path)

            pit_filled  = grid.fill_pits(dem)
            dep_filled  = grid.fill_depressions(pit_filled)
            flat_filled = grid.resolve_flats(dep_filled)

            # Write filled DEM
            with rasterio.open(src_path) as src:
                profile = src.profile.copy()
            profile.update(dtype="float32", nodata=-9999.0)
            arr = np.array(flat_filled).astype("float32")
            with rasterio.open(filled_path, "w", **profile) as dst:
                dst.write(arr, 1)

            st.session_state.filled_dem_path = filled_path
            st.session_state["_pysheds_grid"] = grid
            st.session_state["_pysheds_fdem"] = flat_filled
            st.success("DEM filled successfully.")
        except Exception as e:
            st.error(f"DEM filling failed: {e}")

if st.session_state.filled_dem_path and os.path.exists(st.session_state.filled_dem_path):
    import rasterio
    with rasterio.open(st.session_state.filled_dem_path) as src:
        data = src.read(1).astype(float)
        data[data == src.nodata] = np.nan
    show_raster(data, "Filled DEM", cmap="terrain", label="Elevation (m)")

# ── 2.3 Flow Direction ────────────────────────────────────────────────────────
st.header("2.3  Flow Direction (D8)")
st.caption(
    "GRASS GIS convention (1-8) is used to match `create_file.cell_connectivity(source='GRASS')`."
)

fdir_path = os.path.join(st.session_state.project_dir, "rasters", "r_flow_dir.tif")

# Mapping from pysheds cardinal directions to GRASS 1-8 codes
PYSHEDS_TO_GRASS = {
    64:  1,  # NE
    128: 2,  # N
    1:   3,  # NW
    2:   4,  # W
    4:   5,  # SW
    8:   6,  # S
    16:  7,  # SE
    32:  8,  # E
}

if st.button("🧭 Compute Flow Direction", disabled=(not st.session_state.filled_dem_path)):
    with st.spinner("Computing D8 flow direction…"):
        try:
            from pysheds.grid import Grid
            import rasterio

            grid = Grid.from_raster(st.session_state.filled_dem_path)
            dem  = grid.read_raster(st.session_state.filled_dem_path)
            fdir = grid.flowdir(dem)  # pysheds uses power-of-2 ESRI coding

            # Recode to GRASS 1-8
            fdir_arr = np.array(fdir)
            grass_arr = np.full_like(fdir_arr, -32768, dtype=np.int16)
            for ps_val, grass_val in PYSHEDS_TO_GRASS.items():
                grass_arr[fdir_arr == ps_val] = grass_val

            with rasterio.open(st.session_state.filled_dem_path) as src:
                profile = src.profile.copy()
            profile.update(dtype="int16", nodata=-32768)
            with rasterio.open(fdir_path, "w", **profile) as dst:
                dst.write(grass_arr, 1)

            st.session_state.fdir_path = fdir_path
            st.session_state["_pysheds_fdir"] = fdir
            st.session_state["_pysheds_grid"] = grid
            st.success("Flow direction computed.")
        except Exception as e:
            st.error(f"Flow direction failed: {e}")

if st.session_state.fdir_path and os.path.exists(st.session_state.fdir_path):
    import rasterio
    with rasterio.open(st.session_state.fdir_path) as src:
        data = src.read(1).astype(float)
        data[data == src.nodata] = np.nan
    show_raster(data, "Flow Direction (GRASS 1-8 codes)", cmap="tab10", label="Direction code")

# ── 2.4 Flow Accumulation ─────────────────────────────────────────────────────
st.header("2.4  Flow Accumulation")

accum_path = os.path.join(st.session_state.project_dir, "rasters", "r_flow_accum.tif")

if st.button("🌊 Compute Flow Accumulation", disabled=(not st.session_state.fdir_path)):
    with st.spinner("Computing flow accumulation…"):
        try:
            from pysheds.grid import Grid
            import rasterio

            grid = Grid.from_raster(st.session_state.filled_dem_path)
            dem  = grid.read_raster(st.session_state.filled_dem_path)
            fdir = grid.flowdir(dem)
            acc  = grid.accumulation(fdir)

            acc_arr = np.array(acc).astype("float64")
            with rasterio.open(st.session_state.filled_dem_path) as src:
                profile = src.profile.copy()
            profile.update(dtype="float64", nodata=-1.0)
            with rasterio.open(accum_path, "w", **profile) as dst:
                dst.write(acc_arr, 1)

            st.session_state.accum_path = accum_path
            st.session_state["_pysheds_acc"] = acc
            st.session_state["_pysheds_fdir"] = fdir
            st.session_state["_pysheds_grid"] = grid
            st.success("Flow accumulation computed.")
        except Exception as e:
            st.error(f"Flow accumulation failed: {e}")

if st.session_state.accum_path and os.path.exists(st.session_state.accum_path):
    import rasterio
    with rasterio.open(st.session_state.accum_path) as src:
        data = src.read(1).astype(float)
        data[data <= 0] = np.nan
    show_raster(np.log1p(data), "Flow Accumulation (log scale)", cmap="Blues", label="log(cells)")

# ── Navigation hint ───────────────────────────────────────────────────────────
st.divider()
if st.session_state.accum_path:
    st.success("✅ DEM processed. Proceed to **🗺️ Watershed** in the sidebar.")

"""
Page 4 — Stream Network & Strahler Order
=========================================
- Interactive threshold slider → stream network raster
- Compute Strahler stream order (pysheds)
- Assign channel Manning's n from Strahler lookup
- Preview network on map
"""

import os
import numpy as np
import streamlit as st
import matplotlib.pyplot as plt

st.set_page_config(page_title="Stream Network | PyTOPKAPI GUI", page_icon="🌊", layout="wide")
st.title("🌊 Step 4 — Stream Network & Strahler Order")

if not st.session_state.get("mask_path"):
    st.warning("⚠️ Complete **Step 3 — Watershed** first.")
    st.stop()

# ── 4.1 Stream Network ────────────────────────────────────────────────────────
st.header("4.1  Extract Stream Network")

st.info(
    "Set the **minimum upstream area** (in cells) needed to initiate a channel.  \n"
    "Lower = more streams; higher = fewer, larger channels.  \n"
    "Adjust until the network matches known topographic maps."
)

threshold = st.slider(
    "Stream initiation threshold (upstream cells)",
    min_value=50, max_value=5000,
    value=st.session_state.get("stream_threshold", 500), step=50,
)
st.session_state.stream_threshold = threshold
threshold_area_km2 = threshold * 0.0009   # at 30m resolution
st.caption(f"Threshold area ≈ **{threshold_area_km2:.2f} km²** at 30 m resolution")

streamnet_path = os.path.join(st.session_state.project_dir, "rasters", "r_streamnet.tif")

if st.button("🌊 Extract Stream Network"):
    with st.spinner("Extracting stream network…"):
        try:
            from pysheds.grid import Grid
            import rasterio

            grid = Grid.from_raster(st.session_state.filled_dem_path)
            dem  = grid.read_raster(st.session_state.filled_dem_path)
            fdir = grid.flowdir(dem)
            acc  = grid.accumulation(fdir)

            # Load mask
            with rasterio.open(st.session_state.mask_path) as src:
                mask_arr = src.read(1)

            # Stream network: accumulation > threshold AND within mask
            acc_arr    = np.array(acc)
            stream_arr = np.where((acc_arr >= threshold) & (mask_arr == 1), 1, 0).astype(np.uint8)

            with rasterio.open(st.session_state.filled_dem_path) as src:
                profile = src.profile.copy()
            profile.update(dtype="uint8", nodata=255)

            # Cells outside mask → nodata
            stream_arr[mask_arr != 1] = 255

            with rasterio.open(streamnet_path, "w", **profile) as dst:
                dst.write(stream_arr, 1)

            n_chan = int((stream_arr == 1).sum())
            st.session_state.streamnet_path = streamnet_path
            st.session_state["_pysheds_acc"]  = acc
            st.session_state["_pysheds_fdir"] = fdir
            st.session_state["_pysheds_grid"] = grid
            st.success(f"Stream network extracted — **{n_chan:,} channel cells** ({n_chan/st.session_state.n_cells*100:.1f}% of catchment)")

        except Exception as e:
            st.error(f"Stream extraction failed: {e}")

if st.session_state.get("streamnet_path") and os.path.exists(st.session_state.streamnet_path):
    import rasterio
    with rasterio.open(st.session_state.streamnet_path) as src:
        snet = src.read(1).astype(float)
        snet[snet == 255] = np.nan
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.imshow(snet, cmap="Blues", interpolation="nearest")
    ax.set_title(f"Stream Network (threshold = {threshold} cells)")
    ax.axis("off")
    st.pyplot(fig)
    plt.close()

# ── 4.2 Strahler Order ────────────────────────────────────────────────────────
st.header("4.2  Strahler Stream Order")

strahler_path = os.path.join(st.session_state.project_dir, "rasters", "r_strahler.tif")

if st.button("🔢 Compute Strahler Order", disabled=(not st.session_state.get("streamnet_path"))):
    with st.spinner("Computing Strahler order (pysheds)…"):
        try:
            from pysheds.grid import Grid
            import rasterio

            grid = Grid.from_raster(st.session_state.filled_dem_path)
            dem  = grid.read_raster(st.session_state.filled_dem_path)
            fdir = grid.flowdir(dem)
            acc  = grid.accumulation(fdir)

            branches = grid.extract_river_network(
                fdir, acc >= threshold, dirmap=(64, 128, 1, 2, 4, 8, 16, 32)
            )
            order = grid.stream_order(
                fdir, acc >= threshold, dirmap=(64, 128, 1, 2, 4, 8, 16, 32)
            )
            order_arr = np.array(order).astype(np.int16)

            with rasterio.open(st.session_state.filled_dem_path) as src:
                profile = src.profile.copy()
            profile.update(dtype="int16", nodata=-1)

            with rasterio.open(strahler_path, "w", **profile) as dst:
                dst.write(order_arr, 1)

            max_order = int(order_arr[order_arr > 0].max()) if (order_arr > 0).any() else 0
            st.session_state.strahler_path = strahler_path
            st.success(f"Strahler order computed — max order = **{max_order}**")

        except Exception as e:
            st.error(f"Strahler order failed: {e}")

if st.session_state.get("strahler_path") and os.path.exists(st.session_state.strahler_path):
    import rasterio
    with rasterio.open(st.session_state.strahler_path) as src:
        strahler = src.read(1).astype(float)
        strahler[strahler <= 0] = np.nan
    fig, ax = plt.subplots(figsize=(8, 4))
    im = ax.imshow(strahler, cmap="RdYlBu_r", interpolation="nearest")
    plt.colorbar(im, ax=ax, label="Strahler order", shrink=0.8)
    ax.set_title("Strahler Stream Order")
    ax.axis("off")
    st.pyplot(fig)
    plt.close()

# ── 4.3 Channel Manning's n ───────────────────────────────────────────────────
st.header("4.3  Channel Manning's Roughness (n_c from Strahler Order)")

st.caption("Based on Liu & Todini (2002) — same lookup used in `create_file.strahler_to_channel_manning()`.")

default_manning = {1: 0.050, 2: 0.040, 3: 0.035, 4: 0.030, 5: 0.030, 6: 0.025}
st.markdown("**Edit values if needed:**")

cols = st.columns(6)
manning_nc = {}
for i, (order, n) in enumerate(default_manning.items()):
    with cols[i]:
        manning_nc[order] = st.number_input(
            f"Order {order}", value=n, min_value=0.001, max_value=0.5,
            format="%.3f", key=f"nc_{order}"
        )

st.session_state["manning_nc_lookup"] = manning_nc
st.caption("✅ Manning's n_c lookup saved — will be applied during parameter file generation.")

st.divider()
if st.session_state.get("strahler_path"):
    st.success("✅ Stream network ready. Proceed to **🪨 Soil Parameters** in the sidebar.")

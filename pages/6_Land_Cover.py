"""
Page 6 — Land Cover & Overland Manning's n
==========================================
- Upload a land cover raster OR use a built-in global dataset
- Editable class → Manning's n_o table
- Resample to catchment 30m grid → r_mannings.tif
"""

import os, sys
import numpy as np
import streamlit as st
import matplotlib.pyplot as plt
import pandas as pd

st.set_page_config(page_title="Land Cover | PyTOPKAPI GUI", page_icon="🌿", layout="wide")
st.title("🌿 Step 6 — Land Cover & Overland Manning's Roughness")

if not st.session_state.get("mask_path"):
    st.warning("⚠️ Complete **Step 3 — Watershed** first.")
    st.stop()

# ── 6.1 Land cover source ─────────────────────────────────────────────────────
st.header("6.1  Land Cover Data Source")

source = st.radio(
    "Choose a land cover source:",
    [
        "Upload my own raster",
        "Use Fatoyinbo (2018) Mhlanga classes (recommended for Umhlanga)",
    ],
    index=1,
)

# ── Option A: Upload ──────────────────────────────────────────────────────────
if source == "Upload my own raster":
    uploaded = st.file_uploader(
        "Upload land cover GeoTIFF", type=["tif", "tiff"],
        help="Should be an integer raster where each pixel value is a land cover class code."
    )
    if uploaded:
        lc_path = os.path.join(st.session_state.project_dir, "rasters", "landcover_raw.tif")
        with open(lc_path, "wb") as f:
            f.write(uploaded.read())
        st.session_state["lc_path_raw"] = lc_path
        st.success(f"Saved to `{lc_path}`")

# ── Option B: Fatoyinbo classes ───────────────────────────────────────────────
else:
    st.info(
        "Uses the 4 land cover classes identified in Fatoyinbo (2018) for the Mhlanga catchment.  \n"
        "You can edit the class proportions or Manning's values below."
    )

# ── 6.2 Manning's n_o lookup table ────────────────────────────────────────────
st.header("6.2  Manning's n_o — Overland Roughness")
st.caption("Source: Asante et al. (2008) as used in Fatoyinbo (2018).")

default_classes = pd.DataFrame([
    {"Class code": 1, "Description": "Vegetation / Mixed shrubland / Sugarcane", "n_o": 0.050},
    {"Class code": 2, "Description": "Urban / Built-up land",                   "n_o": 0.030},
    {"Class code": 3, "Description": "Bare soil / Sparsely vegetated",           "n_o": 0.030},
    {"Class code": 4, "Description": "Water bodies",                             "n_o": 0.035},
])

edited_lc = st.data_editor(
    default_classes, use_container_width=True, num_rows="dynamic",
    column_config={
        "n_o": st.column_config.NumberColumn("Manning's n_o", min_value=0.001, max_value=1.0, format="%.3f"),
    }
)
st.session_state["lc_manning_df"] = edited_lc

# ── 6.3 Generate Manning's n_o raster ─────────────────────────────────────────
st.header("6.3  Generate Overland Manning's Raster")

mode = st.radio(
    "How to assign values across the catchment?",
    [
        "Uniform — assign dominant class to all cells",
        "From uploaded raster (reclassify codes → n_o)",
    ],
    index=0,
)

if mode == "Uniform — assign dominant class to all cells":
    dominant_class = st.selectbox(
        "Dominant land cover class for the whole catchment:",
        options=list(edited_lc["Class code"]),
        format_func=lambda x: f"{x} — {edited_lc.loc[edited_lc['Class code']==x,'Description'].values[0]}",
    )
    dominant_n = float(edited_lc.loc[edited_lc["Class code"] == dominant_class, "n_o"].values[0])
    st.caption(f"Will assign n_o = **{dominant_n:.3f}** to all catchment cells.")

if st.button("🌿 Generate Manning's Raster"):
    with st.spinner("Generating overland Manning's roughness raster…"):
        try:
            import rasterio

            with rasterio.open(st.session_state.mask_path) as src:
                mask_arr = src.read(1)
                profile = src.profile.copy()
            profile.update(dtype="float32", nodata=-9999.0)

            n_arr = np.full(mask_arr.shape, -9999.0, dtype=np.float32)

            if mode == "Uniform — assign dominant class to all cells":
                n_arr[mask_arr == 1] = dominant_n
            else:
                lc_raw = st.session_state.get("lc_path_raw")
                if not lc_raw or not os.path.exists(lc_raw):
                    st.error("Upload a land cover raster first.")
                    st.stop()
                # Reproject LC raster to match mask
                from rasterio.warp import reproject, Resampling
                with rasterio.open(lc_raw) as src_lc, \
                     rasterio.open(st.session_state.mask_path) as src_m:
                    lc_repr = np.zeros(src_m.shape, dtype=np.int16)
                    reproject(
                        source=rasterio.band(src_lc, 1),
                        destination=lc_repr,
                        src_transform=src_lc.transform,
                        src_crs=src_lc.crs,
                        dst_transform=src_m.transform,
                        dst_crs=src_m.crs,
                        resampling=Resampling.nearest,
                    )
                for _, row in edited_lc.iterrows():
                    code = int(row["Class code"])
                    n_val = float(row["n_o"])
                    n_arr[(lc_repr == code) & (mask_arr == 1)] = n_val

            man_path = os.path.join(st.session_state.project_dir, "rasters", "r_mannings.tif")
            with rasterio.open(man_path, "w", **profile) as dst:
                dst.write(n_arr, 1)

            st.session_state["landcover_ready"] = True
            st.success(f"Saved to `{man_path}`")

        except Exception as e:
            st.error(f"Failed: {e}")

# Preview
if st.session_state.get("landcover_ready"):
    import rasterio
    man_path = os.path.join(st.session_state.project_dir, "rasters", "r_mannings.tif")
    with rasterio.open(man_path) as src:
        n_data = src.read(1).astype(float)
        n_data[n_data == src.nodata] = np.nan
    fig, ax = plt.subplots(figsize=(8, 4))
    im = ax.imshow(n_data, cmap="YlGn", interpolation="nearest")
    plt.colorbar(im, ax=ax, label="Manning's n_o", shrink=0.8)
    ax.set_title("Overland Manning's Roughness (n_o)")
    ax.axis("off")
    st.pyplot(fig)
    plt.close()

st.divider()
if st.session_state.get("landcover_ready"):
    st.success("✅ Manning's roughness ready. Proceed to **📄 Parameter Files** in the sidebar.")

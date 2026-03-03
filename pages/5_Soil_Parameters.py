"""
Page 5 — Soil Parameters
=========================
- Load HWSD raster (hwsd.bil) and clip to catchment
- Reclassify HWSD codes → Ks, θs, θr, ψb, λ, depth rasters
- Editable lookup table (Rawls 1982 defaults pre-filled)
- Save all soil rasters to project/rasters/
"""

import os
import sys
import numpy as np
import streamlit as st
import matplotlib.pyplot as plt
import pandas as pd

st.set_page_config(page_title="Soil Parameters | PyTOPKAPI GUI", page_icon="🪨", layout="wide")
st.title("🪨 Step 5 — Soil Parameters")

if not st.session_state.get("mask_path"):
    st.warning("⚠️ Complete **Step 3 — Watershed** first.")
    st.stop()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.soil_params import HWSD_PARAMS, DEFAULT_PARAMS

# ── 5.1 HWSD raster location ──────────────────────────────────────────────────
st.header("5.1  HWSD Raster")

default_hwsd = os.path.expanduser(
    "~/Library/CloudStorage/GoogleDrive-justin.j.pringle@gmail.com/My Drive/UKZN/data/HWSD_RASTER/hwsd.bil"
)
hwsd_path = st.text_input(
    "Path to hwsd.bil",
    value=default_hwsd if os.path.exists(default_hwsd) else "",
    help="Global HWSD raster — 1km resolution, 16-bit integer soil unit codes.",
)

if hwsd_path and os.path.exists(hwsd_path):
    st.success(f"✅ HWSD raster found: `{hwsd_path}`")
else:
    st.error("HWSD raster not found. Check the path above.")
    st.stop()

# ── 5.2 Clip HWSD to catchment & identify soil codes ─────────────────────────
st.header("5.2  Identify Soil Units in Catchment")

soil_codes_in_catchment = st.session_state.get("soil_codes_in_catchment", [])

if st.button("🔍 Clip & Identify Soil Codes"):
    with st.spinner("Clipping HWSD to catchment…"):
        try:
            import rasterio
            from rasterio.warp import reproject, Resampling
            from rasterio.enums import Resampling as RS

            # Read mask
            with rasterio.open(st.session_state.mask_path) as src_mask:
                mask_arr = src_mask.read(1)
                mask_transform = src_mask.transform
                mask_crs = src_mask.crs
                mask_shape = src_mask.shape

            # Reproject/resample HWSD to match mask grid
            with rasterio.open(hwsd_path) as src_hwsd:
                hwsd_repr = np.zeros(mask_shape, dtype=np.int32)
                reproject(
                    source=rasterio.band(src_hwsd, 1),
                    destination=hwsd_repr,
                    src_transform=src_hwsd.transform,
                    src_crs=src_hwsd.crs,
                    dst_transform=mask_transform,
                    dst_crs=mask_crs,
                    resampling=Resampling.nearest,
                )

            # Find unique soil codes inside catchment
            catchment_hwsd = hwsd_repr[mask_arr == 1]
            unique_codes = sorted([int(c) for c in np.unique(catchment_hwsd) if c > 0])

            st.session_state["soil_codes_in_catchment"] = unique_codes
            st.session_state["_hwsd_repr"] = hwsd_repr
            soil_codes_in_catchment = unique_codes
            st.success(f"Found **{len(unique_codes)}** HWSD soil units in catchment: {unique_codes}")

        except Exception as e:
            st.error(f"Failed: {e}")

if soil_codes_in_catchment:
    st.write(f"**Soil codes present:** {soil_codes_in_catchment}")

# ── 5.3 Editable lookup table ─────────────────────────────────────────────────
st.header("5.3  Soil Parameter Lookup Table")
st.caption("Pre-filled with Rawls (1982) values. Edit any value before generating rasters.")

if soil_codes_in_catchment:
    rows = []
    for code in soil_codes_in_catchment:
        p = HWSD_PARAMS.get(code, DEFAULT_PARAMS)
        rows.append({
            "HWSD code": code,
            "Texture": p["texture"],
            "Depth (m)": p["depth"],
            "Ks (m/s)": p["Ks"],
            "θs": p["theta_s"],
            "θr": p["theta_r"],
            "ψb (cm)": p["psi_b"],
            "λ": p["lambda"],
        })
    df = pd.DataFrame(rows)
    edited = st.data_editor(df, use_container_width=True, num_rows="fixed")
    st.session_state["soil_lookup_df"] = edited
else:
    st.info("Run 'Clip & Identify Soil Codes' first.")

# ── 5.4 Generate soil rasters ─────────────────────────────────────────────────
st.header("5.4  Generate Soil Rasters")

RASTER_MAP = {
    "r_soil_depth.tif":  "Depth (m)",
    "r_hwsd_ks.tif":     "Ks (m/s)",
    "r_hwsd_theta.tif":  "θs",
    "r_hwsd_theta_r.tif":"θr",
    "r_hwsd_psi_b.tif":  "ψb (cm)",
    "r_hwsd_pore.tif":   "λ",
}

if st.button(
    "🪨 Generate Soil Rasters",
    disabled=(not st.session_state.get("soil_lookup_df") is not None
              and not soil_codes_in_catchment)
):
    with st.spinner("Generating soil parameter rasters…"):
        try:
            import rasterio

            edited_df = st.session_state.get("soil_lookup_df")
            if edited_df is None:
                st.error("Run 'Clip & Identify' first.")
                st.stop()

            # Build code → values mapping from edited table
            lookup = {}
            for _, row in edited_df.iterrows():
                lookup[int(row["HWSD code"])] = {
                    "Depth (m)": row["Depth (m)"],
                    "Ks (m/s)":  row["Ks (m/s)"],
                    "θs":        row["θs"],
                    "θr":        row["θr"],
                    "ψb (cm)":   row["ψb (cm)"],
                    "λ":         row["λ"],
                }

            hwsd_repr = st.session_state["_hwsd_repr"]

            with rasterio.open(st.session_state.mask_path) as src:
                profile = src.profile.copy()
                mask_arr = src.read(1)
            profile.update(dtype="float32", nodata=-9999.0)

            for fname, col in RASTER_MAP.items():
                out_arr = np.full(mask_arr.shape, -9999.0, dtype=np.float32)
                for code, vals in lookup.items():
                    out_arr[(hwsd_repr == code) & (mask_arr == 1)] = vals[col]
                out_path = os.path.join(st.session_state.project_dir, "rasters", fname)
                with rasterio.open(out_path, "w", **profile) as dst:
                    dst.write(out_arr, 1)

            st.session_state["soil_ready"] = True
            st.success(f"Generated {len(RASTER_MAP)} soil rasters in `{st.session_state.project_dir}/rasters/`")

        except Exception as e:
            st.error(f"Failed: {e}")

# Preview
if st.session_state.get("soil_ready"):
    import rasterio
    st.subheader("Preview: Saturated Hydraulic Conductivity (Ks)")
    ks_path = os.path.join(st.session_state.project_dir, "rasters", "r_hwsd_ks.tif")
    if os.path.exists(ks_path):
        with rasterio.open(ks_path) as src:
            ks = src.read(1).astype(float)
            ks[ks == src.nodata] = np.nan
        fig, ax = plt.subplots(figsize=(8, 4))
        im = ax.imshow(ks, cmap="viridis", interpolation="nearest")
        plt.colorbar(im, ax=ax, label="Ks (m/s)", shrink=0.8)
        ax.set_title("Saturated Hydraulic Conductivity")
        ax.axis("off")
        st.pyplot(fig)
        plt.close()

st.divider()
if st.session_state.get("soil_ready"):
    st.success("✅ Soil rasters ready. Proceed to **🌿 Land Cover** in the sidebar.")

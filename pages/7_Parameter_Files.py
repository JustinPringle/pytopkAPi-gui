"""
Page 7 — Parameter File Generation
====================================
- Review all raster inputs
- Edit global parameters and initial conditions
- Run generate_param_file() → cell_param.dat
- Create global_param.dat
"""

import os, sys
import streamlit as st
import pandas as pd
import numpy as np

st.set_page_config(page_title="Parameter Files | PyTOPKAPI GUI", page_icon="📄", layout="wide")
st.title("📄 Step 7 — Parameter File Generation")

for key in ["mask_path", "soil_ready", "landcover_ready", "strahler_path"]:
    if not st.session_state.get(key):
        st.warning(f"⚠️ Please complete all previous steps first (missing: `{key}`).")
        st.stop()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

project_dir = st.session_state.project_dir

# ── 7.1 Raster checklist ──────────────────────────────────────────────────────
st.header("7.1  Input Raster Summary")

rasters = {
    "DEM":                    ("r_dem.tif",           "m"),
    "Catchment mask":         ("r_mask.tif",           "0/1"),
    "Slope":                  ("r_slope.tif",          "degrees"),
    "Flow direction":         ("r_flow_dir.tif",       "GRASS 1-8"),
    "Stream network":         ("r_streamnet.tif",      "0/1"),
    "Soil depth":             ("r_soil_depth.tif",     "m"),
    "Sat. conductivity (Ks)": ("r_hwsd_ks.tif",        "m/s"),
    "Sat. moisture (θs)":     ("r_hwsd_theta.tif",     "-"),
    "Resid. moisture (θr)":   ("r_hwsd_theta_r.tif",   "-"),
    "Bubbling pressure (ψb)": ("r_hwsd_psi_b.tif",     "cm"),
    "Pore size dist. (λ)":    ("r_hwsd_pore.tif",      "-"),
    "Overland Manning (n_o)": ("r_mannings.tif",       "-"),
}

rows = []
for label, (fname, units) in rasters.items():
    path = os.path.join(project_dir, "rasters", fname)
    exists = os.path.exists(path)
    rows.append({"Raster": label, "File": fname, "Units": units, "Status": "✅" if exists else "❌"})

st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

missing = [r["File"] for r in rows if r["Status"] == "❌"]

# Copy filled DEM as r_dem.tif if needed
dem_out = os.path.join(project_dir, "rasters", "r_dem.tif")
if not os.path.exists(dem_out) and st.session_state.get("filled_dem_path"):
    import shutil
    shutil.copy2(st.session_state.filled_dem_path, dem_out)
    st.info("Copied filled DEM → r_dem.tif")

if missing:
    st.warning(f"Missing rasters: {missing}. Complete earlier steps.")

# ── 7.2 Global parameters ─────────────────────────────────────────────────────
st.header("7.2  Global Parameters")

col1, col2 = st.columns(2)
with col1:
    X          = st.number_input("Cell size X (m)",          value=30,      step=10)
    Dt         = st.number_input("Time step Δt (s)",         value=86400,   step=3600,
                                 help="86400 = daily; 3600 = hourly")
    alpha_s    = st.number_input("α_s (pore size dist.)",    value=2.5,     format="%.2f")
with col2:
    alpha_oc   = st.number_input("α_o / α_c (Manning exp.)", value=1.6667,  format="%.4f",
                                 help="5/3 ≈ 1.6667 from Manning's equation")
    A_thres    = st.number_input("A_threshold (m²)",         value=1_000_000, step=100_000,
                                 help="Min upstream area to initiate a channel. 1 km² = 1,000,000 m²")
    W_min      = st.number_input("W_min — min channel width (m)", value=2.0,  format="%.1f")
    W_max      = st.number_input("W_max — max channel width (m)", value=25.0, format="%.1f")

# ── 7.3 Initial conditions ────────────────────────────────────────────────────
st.header("7.3  Initial Conditions")
st.caption("Fatoyinbo (2018) recommends pVs_t0 = 60% for the Umhlanga catchment.")

col1, col2, col3, col4 = st.columns(4)
pVs_t0 = col1.number_input("Initial soil saturation (%)", value=60.0, min_value=0.0, max_value=100.0)
Vo_t0  = col2.number_input("Initial overland vol (m³)",   value=0.0,  min_value=0.0)
Qc_t0  = col3.number_input("Initial channel Q (m³/s)",    value=0.0,  min_value=0.0)
Kc     = col4.number_input("Crop factor Kc",               value=1.0,  min_value=0.1, max_value=2.0)

# ── 7.4 Generate files ────────────────────────────────────────────────────────
st.header("7.4  Generate Parameter Files")

param_dir = os.path.join(project_dir, "parameter_files")
ini_path  = os.path.join(project_dir, "param_setup.ini")

if st.button("📄 Generate cell_param.dat + global_param.dat", disabled=bool(missing)):
    # Write param_setup.ini
    ini_content = f"""[raster_files]
dem_fname                    = {os.path.join(project_dir, 'rasters', 'r_dem.tif')}
mask_fname                   = {st.session_state.mask_path}
soil_depth_fname             = {os.path.join(project_dir, 'rasters', 'r_soil_depth.tif')}
conductivity_fname           = {os.path.join(project_dir, 'rasters', 'r_hwsd_ks.tif')}
hillslope_fname              = {st.session_state.slope_path}
sat_moisture_content_fname   = {os.path.join(project_dir, 'rasters', 'r_hwsd_theta.tif')}
resid_moisture_content_fname = {os.path.join(project_dir, 'rasters', 'r_hwsd_theta_r.tif')}
bubbling_pressure_fname      = {os.path.join(project_dir, 'rasters', 'r_hwsd_psi_b.tif')}
pore_size_dist_fname         = {os.path.join(project_dir, 'rasters', 'r_hwsd_pore.tif')}
overland_manning_fname       = {os.path.join(project_dir, 'rasters', 'r_mannings.tif')}
channel_network_fname        = {st.session_state.streamnet_path}
flowdir_fname                = {st.session_state.fdir_path}
flowdir_source               = GRASS

[output]
param_fname = {os.path.join(param_dir, 'cell_param.dat')}

[numerical_values]
pVs_t0 = {pVs_t0}
Vo_t0  = {Vo_t0}
Qc_t0  = {Qc_t0}
Kc     = {Kc}
"""
    with open(ini_path, "w") as f:
        f.write(ini_content)

    with st.spinner("Running generate_param_file()…"):
        try:
            # Try to import from project or installed pytopkapi
            try:
                from pytopkapi import pretreatment as pt
                import create_file
                create_file.generate_param_file(ini_path)
            except ImportError:
                # Fall back to local copy
                create_file_path = os.path.join(
                    os.path.expanduser("~/Library/CloudStorage"),
                    "GoogleDrive-justin.j.pringle@gmail.com",
                    "My Drive/UKZN/Projects/waterQ/umhlanga/pytopkapi/create_file.py"
                )
                import importlib.util
                spec = importlib.util.spec_from_file_location("create_file", create_file_path)
                cf = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(cf)
                cf.generate_param_file(ini_path)

            cell_param_path = os.path.join(param_dir, "cell_param.dat")
            st.session_state.cell_param_path = cell_param_path

            # Write global_param.dat
            global_param_path = os.path.join(param_dir, "global_param.dat")
            with open(global_param_path, "w") as f:
                f.write(f"{X} {Dt} {alpha_s} {alpha_oc} {alpha_oc} {A_thres} {W_min} {W_max}\n")
            st.session_state.global_param_path = global_param_path

            st.success(f"✅ Parameter files generated in `{param_dir}/`")

            # Show preview
            import pandas as pd
            df = pd.read_csv(cell_param_path, sep=" ", header=None,
                             names=["label","X","Y","chan","chan_len","dam",
                                    "tan_b","tan_bc","depth","Ks","thr","ths",
                                    "no","nc","cell_down","pVs","Vo","Qc","Kc","psib","lam"])
            st.metric("Total cells", f"{len(df):,}")
            st.metric("Channel cells", f"{(df.chan == 1).sum():,}")
            st.dataframe(df.head(10), use_container_width=True)

        except Exception as e:
            st.error(f"Parameter file generation failed: {e}")
            st.exception(e)

st.divider()
if st.session_state.cell_param_path:
    st.success("✅ Parameter files ready. Proceed to **🌧️ Forcing Data** in the sidebar.")

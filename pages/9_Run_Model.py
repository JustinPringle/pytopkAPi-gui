"""
Page 9 — Run Model
==================
- Auto-generate TOPKAPI.ini
- Set calibration multipliers
- Run pytopkapi.run() with live log output
- Show runoff ratio vs Schreiber target
"""

import os
import streamlit as st
import numpy as np

st.set_page_config(page_title="Run Model | PyTOPKAPI GUI", page_icon="▶️", layout="wide")
st.title("▶️ Step 9 — Run PyTOPKAPI")

required = ["cell_param_path", "global_param_path", "rainfields_path", "et_path"]
for key in required:
    if not st.session_state.get(key):
        st.warning(f"⚠️ Complete earlier steps first (missing: `{key}`).")
        st.stop()

project_dir = st.session_state.project_dir

# ── 9.1 TOPKAPI.ini ───────────────────────────────────────────────────────────
st.header("9.1  Model Configuration (TOPKAPI.ini)")

group_name = st.text_input("HDF5 group name (must match forcing files)", value="sample event")
results_path = os.path.join(project_dir, "results", "simulation_output.h5")

ini_content = f"""[input_files]
file_global_param = {st.session_state.global_param_path}
file_cell_param   = {st.session_state.cell_param_path}
file_rain         = {st.session_state.rainfields_path}
file_ET           = {st.session_state.et_path}

[output_files]
file_out      = {results_path}
append_output = False

[groups]
group_name = {group_name}

[external_flow]
external_flow = False

[numerical_options]
solve_s             = 1
solve_o             = 1
solve_c             = 1
only_channel_output = False

[calib_params]
fac_L   = {{fac_L}}
fac_Ks  = {{fac_Ks}}
fac_n_o = {{fac_n_o}}
fac_n_c = {{fac_n_c}}
"""

# ── 9.2 Calibration multipliers ───────────────────────────────────────────────
st.header("9.2  Calibration Parameters")
st.info(
    "Fatoyinbo (2018) calibrated: **fac_Ks = 0.68, fac_L = 1.0** for the Umhlanga catchment.  \n"
    "Target runoff ratio: **Q/AR = 16%** (Schreiber equation)."
)

col1, col2, col3, col4 = st.columns(4)
fac_L   = col1.number_input("fac_L   (soil depth)",        value=1.00, min_value=0.01, max_value=10.0, format="%.2f")
fac_Ks  = col2.number_input("fac_Ks  (conductivity)",      value=0.68, min_value=0.01, max_value=10.0, format="%.2f")
fac_n_o = col3.number_input("fac_n_o (overland Manning)",  value=1.00, min_value=0.01, max_value=10.0, format="%.2f")
fac_n_c = col4.number_input("fac_n_c (channel Manning)",   value=1.00, min_value=0.01, max_value=10.0, format="%.2f")

# Write and display TOPKAPI.ini
ini_rendered = ini_content.format(
    fac_L=fac_L, fac_Ks=fac_Ks, fac_n_o=fac_n_o, fac_n_c=fac_n_c
)
ini_path = os.path.join(project_dir, "TOPKAPI.ini")
with open(ini_path, "w") as f:
    f.write(ini_rendered)

with st.expander("📄 View TOPKAPI.ini"):
    st.code(ini_rendered, language="ini")

# ── 9.3 Run ───────────────────────────────────────────────────────────────────
st.header("9.3  Run Model")

if st.button("▶️ Run PyTOPKAPI", type="primary"):
    log_box = st.empty()
    progress = st.progress(0)
    log_lines = []

    with st.spinner("Running PyTOPKAPI…"):
        try:
            import pytopkapi
            import io, contextlib

            # Capture stdout from pytopkapi
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                pytopkapi.run(ini_path)

            log_lines = buf.getvalue().split("\n")
            log_box.code("\n".join(log_lines[-50:]), language="text")
            progress.progress(100)

            st.session_state.results_path = results_path
            st.success(f"✅ Model run complete! Results saved to `{results_path}`")

        except ImportError:
            st.error(
                "pytopkapi is not installed in the current environment.  \n"
                "Install with:  \n"
                "```\npip install git+https://github.com/JustinPringle/PyTOPKAPI.git\n```"
            )
        except Exception as e:
            st.error(f"Model run failed: {e}")
            st.exception(e)

# ── 9.4 Quick runoff ratio check ──────────────────────────────────────────────
if st.session_state.get("results_path") and os.path.exists(st.session_state.results_path):
    st.header("9.4  Runoff Ratio Check")

    try:
        import h5py, pandas as pd

        with h5py.File(st.session_state.results_path, "r") as f:
            # Outlet cell is last in sorted order (most downstream)
            qc = f[f"{group_name}/Channel/Qc_out"][:]

        outlet_q = qc[:, -1]  # last column = outlet cell

        rain_series = st.session_state.get("rain_series")
        n_cells = st.session_state.n_cells
        cell_area = 30 * 30  # m²

        if rain_series is not None:
            dt = 86400  # seconds/day
            total_Q_m3  = float(outlet_q.sum()) * dt
            total_P_m3  = float(rain_series.sum()) / 1000.0 * n_cells * cell_area
            runoff_ratio = total_Q_m3 / total_P_m3

            col1, col2, col3 = st.columns(3)
            col1.metric("Simulated runoff ratio", f"{runoff_ratio*100:.1f}%")
            col2.metric("Target (Schreiber)",      "16.0%")
            diff = runoff_ratio * 100 - 16.0
            col3.metric("Difference", f"{diff:+.1f}%", delta_color="inverse")

            if abs(diff) < 1.0:
                st.success("✅ Runoff ratio within ±1% of target — good calibration!")
            elif diff > 0:
                st.warning(f"Model over-generating runoff. Try increasing fac_Ks or decreasing fac_L.")
            else:
                st.warning(f"Model under-generating runoff. Try decreasing fac_Ks or increasing fac_L.")

    except Exception as e:
        st.warning(f"Could not compute runoff ratio: {e}")

st.divider()
if st.session_state.results_path:
    st.success("✅ Model run complete. Proceed to **📈 Results** in the sidebar.")

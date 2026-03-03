"""
Page 10 — Results
==================
- Outlet hydrograph (plotly, interactive)
- Flow duration curve
- Runoff ratio statistics
- Soil moisture maps with time slider
- Export to CSV
"""

import os
import numpy as np
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd

st.set_page_config(page_title="Results | PyTOPKAPI GUI", page_icon="📈", layout="wide")
st.title("📈 Step 10 — Results")

if not st.session_state.get("results_path") or not os.path.exists(st.session_state.results_path):
    st.warning("⚠️ No results found. Run the model in **Step 9** first.")
    st.stop()

import h5py

results_path = st.session_state.results_path
group_name   = st.session_state.get("run_group_name", "sample event")

# Load results
with h5py.File(results_path, "r") as f:
    groups = list(f.keys())

group_name = st.selectbox("Select simulation group", groups)

with h5py.File(results_path, "r") as f:
    try:
        Qc_out = f[f"{group_name}/Channel/Qc_out"][:]    # (timesteps, cells)
        V_o    = f[f"{group_name}/Overland/V_o"][:]      # (timesteps, cells)
        V_s    = f[f"{group_name}/Soil/V_s"][:]          # (timesteps, cells)
    except KeyError as e:
        st.error(f"Unexpected results structure: {e}")
        st.stop()

n_steps, n_cells = Qc_out.shape
st.caption(f"Results: **{n_steps} timesteps × {n_cells:,} cells**")

# Date index
rain_series = st.session_state.get("rain_series")
if rain_series is not None and len(rain_series) >= n_steps:
    dates = rain_series.index[:n_steps]
else:
    dates = pd.date_range("2000-01-01", periods=n_steps, freq="D")

# Outlet = last cell in sorted order
outlet_q = Qc_out[:, -1]

# ── Tab layout ─────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs(["💧 Hydrograph", "📊 Flow Duration Curve", "🌱 Soil Moisture", "📥 Export"])

# ── Tab 1: Hydrograph ─────────────────────────────────────────────────────────
with tab1:
    st.subheader("Outlet Hydrograph")

    fig = go.Figure()

    # Rainfall (inverted axis, background bars)
    if rain_series is not None:
        rain_vals = rain_series.values[:n_steps]
        fig.add_trace(go.Bar(
            x=dates, y=rain_vals,
            name="Rainfall (mm/day)",
            yaxis="y2",
            marker_color="steelblue",
            opacity=0.5,
        ))

    fig.add_trace(go.Scatter(
        x=dates, y=outlet_q,
        mode="lines",
        name="Simulated Q (m³/s)",
        line=dict(color="tomato", width=1.5),
    ))

    fig.update_layout(
        xaxis_title="Date",
        yaxis=dict(title="Discharge (m³/s)", side="left"),
        yaxis2=dict(title="Rainfall (mm/day)", side="right",
                    overlaying="y", autorange="reversed", showgrid=False),
        hovermode="x unified",
        height=450,
        legend=dict(x=0.01, y=0.99),
    )
    st.plotly_chart(fig, use_container_width=True)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Mean Q",  f"{outlet_q.mean():.3f} m³/s")
    col2.metric("Peak Q",  f"{outlet_q.max():.3f} m³/s")
    col3.metric("Min Q",   f"{outlet_q.min():.4f} m³/s")
    col4.metric("Total vol.", f"{outlet_q.sum() * 86400 / 1e6:.2f} Mm³")

# ── Tab 2: Flow Duration Curve ─────────────────────────────────────────────────
with tab2:
    st.subheader("Flow Duration Curve (Outlet)")

    sorted_q = np.sort(outlet_q)[::-1]
    exceed   = np.linspace(0, 100, len(sorted_q))

    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(
        x=exceed, y=sorted_q,
        mode="lines", name="Simulated",
        line=dict(color="tomato", width=2),
    ))
    fig2.update_layout(
        xaxis_title="Exceedance probability (%)",
        yaxis_title="Discharge (m³/s)",
        yaxis_type="log",
        height=400,
    )
    st.plotly_chart(fig2, use_container_width=True)

# ── Tab 3: Soil Moisture Maps ──────────────────────────────────────────────────
with tab3:
    st.subheader("Soil Moisture Maps")
    st.caption("Soil store volume Vs (m³) per cell across the catchment over time.")

    import matplotlib.pyplot as plt
    import rasterio

    timestep = st.slider("Timestep", 0, n_steps - 1, 0)
    st.caption(f"Date: {dates[timestep].date()}")

    # Reconstruct spatial map from flat cell array
    if st.session_state.mask_path and os.path.exists(st.session_state.mask_path):
        with rasterio.open(st.session_state.mask_path) as src:
            mask_arr = src.read(1)

        vs_t = V_s[timestep, :]
        vs_map = np.full(mask_arr.shape, np.nan)
        catchment_idx = np.where(mask_arr.flatten() == 1)[0]
        if len(catchment_idx) == len(vs_t):
            rows, cols = np.unravel_index(np.where(mask_arr == 1), mask_arr.shape)
            vs_map[rows, cols] = vs_t

        fig3, ax = plt.subplots(figsize=(9, 5))
        im = ax.imshow(vs_map, cmap="Blues", interpolation="nearest")
        plt.colorbar(im, ax=ax, label="Soil store volume (m³)", shrink=0.8)
        ax.set_title(f"Soil Moisture — {dates[timestep].date()}")
        ax.axis("off")
        st.pyplot(fig3)
        plt.close()
    else:
        st.info("Mask raster not available — cannot reconstruct spatial map.")

# ── Tab 4: Export ─────────────────────────────────────────────────────────────
with tab4:
    st.subheader("Export Results")

    df_out = pd.DataFrame({
        "date":          dates,
        "Q_outlet_m3s":  outlet_q,
        "Vs_mean_m3":    V_s.mean(axis=1),
        "Vo_mean_m3":    V_o.mean(axis=1),
    })
    if rain_series is not None:
        df_out["rainfall_mm"] = rain_series.values[:n_steps]

    csv = df_out.to_csv(index=False)
    st.download_button(
        "⬇️ Download results CSV",
        data=csv,
        file_name="pytopkapi_results.csv",
        mime="text/csv",
    )

    # Runoff ratio summary
    if rain_series is not None:
        total_q_m3 = float(outlet_q.sum()) * 86400
        total_p_m3 = float(rain_series.values[:n_steps].sum()) / 1000.0 * n_cells * (30 * 30)
        rr = total_q_m3 / total_p_m3 if total_p_m3 > 0 else 0
        st.metric("Simulated runoff ratio (Q/AR)", f"{rr*100:.1f}%")
        st.caption("Target for Umhlanga: **16%** (Schreiber equation, Fatoyinbo 2018)")

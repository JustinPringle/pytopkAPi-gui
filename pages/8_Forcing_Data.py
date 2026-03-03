"""
Page 8 — Forcing Data
======================
- Upload rainfall data (CSV / Excel) from any source (Obscape export, SAWS, etc.)
- Support single gauge or multi-gauge spatial averaging
- Set evapotranspiration (Fatoyinbo 2018 defaults, upload, or constant)
- Write rainfields.h5 and ET.h5 in PyTOPKAPI HDF5 format
"""

import os
import numpy as np
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import h5py

st.set_page_config(page_title="Forcing Data | PyTOPKAPI GUI", page_icon="🌧️", layout="wide")
st.title("🌧️ Step 8 — Forcing Data (Rainfall & ET)")

# ── session-state defaults ────────────────────────────────────────────────────
for key, default in {
    "project_dir": "",
    "n_cells": None,
    "Dt": 86400,
    "rain_series": None,
    "et_series": None,
    "rainfields_path": None,
    "et_path": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

project_dir = st.session_state.get("project_dir", "")
n_cells     = st.session_state.get("n_cells")

if not project_dir:
    st.warning("⚠️ No project directory set. Complete **Step 1 — Study Area** first.")
    st.stop()

forcing_dir = os.path.join(project_dir, "forcing_variables")
os.makedirs(forcing_dir, exist_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 1 — RAINFALL
# ══════════════════════════════════════════════════════════════════════════════
st.header("8.1  Rainfall")

st.markdown(
    """
Upload a **CSV or Excel** file exported from any rainfall source
(Obscape, SAWS, a weather station logger, etc.).

**Expected format:**

| Date | Gauge_A | Gauge_B | … |
|------|---------|---------|---|
| 2015-01-01 | 3.2 | 4.1 | … |

- The **date/datetime column** can have any name — select it below.
- Each additional column is treated as a **separate rain gauge** (mm per time-step).
- Multiple gauges can be spatially averaged or weighted using Thiessen coefficients.
- Data can be at **any sub-daily or daily time-step** — you can optionally resample to daily.
"""
)

uploaded_rain = st.file_uploader(
    "Upload rainfall file",
    type=["csv", "xlsx", "xls", "txt"],
    key="rain_upload",
)

rain_series = None

if uploaded_rain is not None:
    try:
        if uploaded_rain.name.lower().endswith((".xlsx", ".xls")):
            rain_raw = pd.read_excel(uploaded_rain)
        else:
            rain_raw = pd.read_csv(uploaded_rain)

        st.success(f"Loaded **{uploaded_rain.name}** — {len(rain_raw):,} rows × {len(rain_raw.columns)} columns")
        st.dataframe(rain_raw.head(8), use_container_width=True)

        all_cols = rain_raw.columns.tolist()

        # ── column selection ──────────────────────────────────────────────────
        col1, col2 = st.columns(2)
        with col1:
            date_col = st.selectbox("Date/time column", all_cols, index=0)
        with col2:
            gauge_cols = st.multiselect(
                "Gauge column(s)",
                [c for c in all_cols if c != date_col],
                default=[c for c in all_cols if c != date_col],
                help="Select all rain gauges you want to use.",
            )

        if not gauge_cols:
            st.warning("Select at least one gauge column to continue.")
            st.stop()

        # Parse dates
        try:
            rain_raw[date_col] = pd.to_datetime(rain_raw[date_col])
        except Exception as exc:
            st.error(f"Cannot parse '{date_col}' as dates: {exc}")
            st.stop()

        rain_raw = rain_raw.sort_values(date_col).reset_index(drop=True)
        rain_raw = rain_raw.set_index(date_col)

        # ── resample option ───────────────────────────────────────────────────
        st.subheader("Time-step")
        do_resample = st.checkbox(
            "Resample to daily totals (tick if data is sub-daily e.g. hourly)",
            value=False,
        )
        if do_resample:
            rain_raw = rain_raw[gauge_cols].resample("D").sum()
        else:
            rain_raw = rain_raw[gauge_cols]

        model_ts = st.selectbox(
            "Model time-step to use for HDF5",
            ["Daily (86400 s)", "Hourly (3600 s)"],
            index=0,
        )
        st.session_state["Dt"] = 86400 if "Daily" in model_ts else 3600

        # ── spatial combination ───────────────────────────────────────────────
        st.subheader("Spatial averaging")

        if len(gauge_cols) == 1:
            st.info(f"Single gauge selected: **{gauge_cols[0]}**")
            combined = rain_raw[gauge_cols[0]].fillna(0.0)
        else:
            agg_method = st.radio(
                "How to combine multiple gauges?",
                ["Simple (equal) average", "Thiessen-weighted average", "Use one gauge only"],
                horizontal=True,
            )

            if agg_method == "Simple (equal) average":
                combined = rain_raw[gauge_cols].mean(axis=1).fillna(0.0)

            elif agg_method == "Thiessen-weighted average":
                st.markdown("Enter the **Thiessen weight** (0–1) for each gauge. Weights must sum to 1.")
                weights = {}
                w_cols = st.columns(min(len(gauge_cols), 4))
                for i, gc in enumerate(gauge_cols):
                    default_w = round(1.0 / len(gauge_cols), 3)
                    weights[gc] = w_cols[i % 4].number_input(
                        gc, min_value=0.0, max_value=1.0, value=default_w, step=0.01, key=f"w_{gc}"
                    )
                total_w = sum(weights.values())
                if abs(total_w - 1.0) > 0.01:
                    st.warning(f"Weights sum to {total_w:.3f} — they should sum to 1.0")
                combined = sum(rain_raw[gc].fillna(0.0) * w for gc, w in weights.items())

            else:  # single gauge from multiselect
                chosen = st.selectbox("Select gauge to use", gauge_cols)
                combined = rain_raw[chosen].fillna(0.0)

        rain_series = combined.values.astype(np.float64)

        # ── preview ───────────────────────────────────────────────────────────
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=combined.index,
            y=rain_series,
            name="Rainfall (mm)",
            marker_color="#1565C0",
        ))
        fig.update_layout(
            title="Combined catchment rainfall",
            xaxis_title="Date",
            yaxis_title="Rainfall (mm)",
            height=280,
            margin=dict(t=40, b=20),
        )
        st.plotly_chart(fig, use_container_width=True)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Time steps", f"{len(rain_series):,}")
        m2.metric("Total (mm)", f"{rain_series.sum():.1f}")
        m3.metric("Max step (mm)", f"{rain_series.max():.1f}")
        m4.metric("Dry steps", f"{(rain_series == 0).sum():,}")

        st.session_state["rain_series"] = combined
        st.session_state["rain_date_index"] = combined.index

    except Exception as exc:
        st.error(f"Error processing file: {exc}")
        st.stop()


# ── write rainfields.h5 ───────────────────────────────────────────────────────
if st.session_state.get("rain_series") is not None:
    st.divider()
    st.subheader("Write rainfields.h5")

    if n_cells is None:
        n_cells = st.number_input(
            "Number of catchment cells (from Step 3)", min_value=1, value=319, step=1, key="n_cells_rain"
        )
        n_cells = int(n_cells)

    rain_group = st.text_input(
        "HDF5 group name (must match `rain_groups` in TOPKAPI.ini)",
        value="sample event",
        key="rain_group",
    )

    if st.button("💾  Write rainfields.h5", type="primary", key="btn_rain"):
        rain_arr = st.session_state["rain_series"].values.astype(np.float64)
        n_t = len(rain_arr)
        rain_2d = np.tile(rain_arr.reshape(-1, 1), (1, n_cells))

        rain_path = os.path.join(forcing_dir, "rainfields.h5")
        with h5py.File(rain_path, "w") as h:
            g = h.create_group(rain_group)
            g.create_dataset(
                "rainfall", data=rain_2d,
                chunks=True, compression="gzip", compression_opts=9,
            )
        st.session_state["rainfields_path"] = rain_path
        st.session_state["n_cells"] = n_cells
        st.success(f"✅ Saved `rainfields.h5` — shape {rain_2d.shape}  →  `{rain_path}`")

st.divider()


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 2 — EVAPOTRANSPIRATION
# ══════════════════════════════════════════════════════════════════════════════
st.header("8.2  Evapotranspiration (ET)")

# Fatoyinbo (2018) mean monthly ETo — Mhlanga/Umhlanga catchment (mm/day)
FATOYINBO_ETO = {1:5.2, 2:5.0, 3:4.5, 4:3.8, 5:3.2, 6:2.8,
                 7:2.9, 8:3.4, 9:4.0, 10:4.7, 11:5.1, 12:5.3}

et_source = st.radio(
    "ET source",
    [
        "Fatoyinbo (2018) monthly defaults — Umhlanga catchment",
        "Upload ET file (CSV / Excel)",
        "Constant daily ETo",
    ],
    index=0,
    horizontal=True,
)

et_series = None

# ── A: Fatoyinbo defaults ─────────────────────────────────────────────────────
if et_source.startswith("Fatoyinbo"):
    st.caption(
        "Mean monthly ETo (mm/day) from Fatoyinbo (2018), FAO Penman-Monteith, "
        "Mhlanga catchment. Edit values if needed."
    )
    eto_df = pd.DataFrame(
        {"Month": list(FATOYINBO_ETO.keys()), "ETo (mm/day)": list(FATOYINBO_ETO.values())}
    )
    edited = st.data_editor(eto_df, use_container_width=False, num_rows="fixed", hide_index=True)
    monthly_map = dict(zip(edited["Month"], edited["ETo (mm/day)"]))

    date_idx = st.session_state.get("rain_date_index")
    if date_idx is not None:
        eto_vals = pd.Series(date_idx).dt.month.map(monthly_map).values.astype(np.float64)
        et_series = pd.Series(eto_vals, index=date_idx, name="ETo_mm")
        st.caption(f"Generated {len(et_series)}-step ET series from monthly means.")
    else:
        st.info("Upload rainfall data first to set the date range for ET.")

# ── B: Upload ET file ──────────────────────────────────────────────────────────
elif et_source.startswith("Upload"):
    st.markdown(
        "Upload a file with a **date column** and **ETo** (grass reference, mm/time-step). "
        "An **ETr** (alfalfa) column is optional — if absent ETr = ETo × 1.15."
    )
    uploaded_et = st.file_uploader("Upload ET file", type=["csv", "xlsx", "xls"], key="et_upload")
    if uploaded_et is not None:
        try:
            if uploaded_et.name.lower().endswith((".xlsx", ".xls")):
                et_raw = pd.read_excel(uploaded_et)
            else:
                et_raw = pd.read_csv(uploaded_et)

            st.dataframe(et_raw.head(5), use_container_width=True)
            et_cols = et_raw.columns.tolist()

            col1, col2, col3 = st.columns(3)
            with col1:
                et_date_col = st.selectbox("Date column", et_cols, key="et_date_col")
            with col2:
                eto_col = st.selectbox("ETo column (grass ref, mm)", et_cols, key="eto_col")
            with col3:
                etr_opts = ["— compute as ETo × 1.15 —"] + et_cols
                etr_col  = st.selectbox("ETr column (optional)", etr_opts, key="etr_col")

            et_raw[et_date_col] = pd.to_datetime(et_raw[et_date_col])
            et_raw = et_raw.sort_values(et_date_col).set_index(et_date_col)
            eto_vals = et_raw[eto_col].fillna(0.0).values.astype(np.float64)
            et_series = pd.Series(eto_vals, index=et_raw.index, name="ETo_mm")
            st.success(f"Loaded {len(et_series):,} rows of ET data.")
        except Exception as exc:
            st.error(f"Error reading ET file: {exc}")

# ── C: Constant ETo ────────────────────────────────────────────────────────────
else:
    const_eto = st.number_input("Constant ETo (mm/day)", min_value=0.0, value=4.0, step=0.1)
    date_idx = st.session_state.get("rain_date_index")
    if date_idx is not None:
        eto_vals = np.full(len(date_idx), const_eto, dtype=np.float64)
        et_series = pd.Series(eto_vals, index=date_idx, name="ETo_mm")
    else:
        st.info("Upload rainfall data first to set the date range for ET.")

# Preview ET
if et_series is not None:
    fig_et = go.Figure()
    fig_et.add_trace(go.Scatter(
        x=et_series.index, y=et_series.values,
        mode="lines", line=dict(color="#E53935", width=1.5), name="ETo (mm/day)"
    ))
    fig_et.update_layout(
        title="Reference ET series", xaxis_title="Date",
        yaxis_title="ETo (mm/day)", height=230, margin=dict(t=40, b=20)
    )
    st.plotly_chart(fig_et, use_container_width=True)
    st.session_state["et_series"] = et_series


# ── write ET.h5 ───────────────────────────────────────────────────────────────
if st.session_state.get("et_series") is not None:
    st.divider()
    st.subheader("Write ET.h5")

    n_cells_et = st.session_state.get("n_cells") or n_cells

    et_group = st.text_input(
        "HDF5 group name for ET (must match `ET_groups` in TOPKAPI.ini)",
        value="sample_event",
        key="et_group",
    )

    if st.button("💾  Write ET.h5", type="primary", key="btn_et"):
        if n_cells_et is None:
            st.error("Number of cells unknown — write rainfields.h5 first (or enter above).")
        else:
            n_cells_et = int(n_cells_et)
            eto_arr = st.session_state["et_series"].values.astype(np.float64)
            etr_arr = eto_arr * 1.15  # alfalfa reference

            eto_2d = np.tile(eto_arr.reshape(-1, 1), (1, n_cells_et))
            etr_2d = np.tile(etr_arr.reshape(-1, 1), (1, n_cells_et))

            et_path = os.path.join(forcing_dir, "ET.h5")
            with h5py.File(et_path, "w") as h:
                g = h.create_group(et_group)
                g.create_dataset("ETo", data=eto_2d, chunks=True, compression="gzip", compression_opts=9)
                g.create_dataset("ETr", data=etr_2d, chunks=True, compression="gzip", compression_opts=9)

            st.session_state["et_path"] = et_path
            st.success(f"✅ Saved `ET.h5` — shape {eto_2d.shape}  →  `{et_path}`")


# ══════════════════════════════════════════════════════════════════════════════
#  STATUS SUMMARY
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
c1, c2 = st.columns(2)
with c1:
    if st.session_state.get("rainfields_path"):
        st.success("✅ rainfields.h5 ready")
    else:
        st.info("⬜ rainfields.h5 not yet written")
with c2:
    if st.session_state.get("et_path"):
        st.success("✅ ET.h5 ready")
    else:
        st.info("⬜ ET.h5 not yet written")

if st.session_state.get("rainfields_path") and st.session_state.get("et_path"):
    st.success("🎉 Both forcing files ready — proceed to **▶️ Step 9 · Run Model**")

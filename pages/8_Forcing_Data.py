"""
Page 8 — Forcing Data
======================
- Connect to Obscape API → fetch historical rainfall → aggregate to model timestep
- Compute reference ET (FAO Penman-Monteith or upload CSV)
- Write rainfields.h5 and ET.h5 in PyTOPKAPI HDF5 format
"""

import os
import numpy as np
import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from datetime import date, timedelta

st.set_page_config(page_title="Forcing Data | PyTOPKAPI GUI", page_icon="🌧️", layout="wide")
st.title("🌧️ Step 8 — Forcing Data (Rainfall & ET)")

if not st.session_state.get("cell_param_path"):
    st.warning("⚠️ Complete **Step 7 — Parameter Files** first.")
    st.stop()

project_dir = st.session_state.project_dir
forcing_dir = os.path.join(project_dir, "forcing_variables")
os.makedirs(forcing_dir, exist_ok=True)

# ── 8.1 Obscape API connection ────────────────────────────────────────────────
st.header("8.1  Obscape Rainfall — API Connection")

col1, col2 = st.columns(2)
with col1:
    base_url = st.text_input(
        "Obscape API base URL",
        value=st.session_state.get("obscape_base_url", ""),
        placeholder="https://api.obscape.com/...",
    )
with col2:
    api_key = st.text_input(
        "API key / token",
        type="password",
        value=st.session_state.get("obscape_api_key", ""),
        help="Stored only in session memory — never written to disk.",
    )

if base_url:
    st.session_state.obscape_base_url = base_url
if api_key:
    st.session_state.obscape_api_key = api_key

station_id = st.text_input(
    "Station ID(s) (comma-separated for multiple)",
    value=st.session_state.get("obscape_station_id", ""),
    placeholder="e.g.  umhlanga_01, umhlanga_02",
)
if station_id:
    st.session_state.obscape_station_id = station_id

# ── Date range ────────────────────────────────────────────────────────────────
col1, col2 = st.columns(2)
with col1:
    start_date = st.date_input("Simulation start", value=date(2015, 1, 1))
with col2:
    end_date   = st.date_input("Simulation end",   value=date(2020, 12, 31))

n_days = (end_date - start_date).days + 1
st.caption(f"Simulation period: **{n_days} days** ({start_date} → {end_date})")

# ── Fetch rainfall ─────────────────────────────────────────────────────────────
if st.button(
    "⬇️ Fetch Rainfall from Obscape",
    disabled=(not base_url or not api_key or not station_id),
):
    with st.spinner("Fetching rainfall data from Obscape API…"):
        try:
            import requests

            stations = [s.strip() for s in station_id.split(",")]
            all_series = []

            for stn in stations:
                # NOTE: update this endpoint pattern once Obscape API details confirmed
                endpoint = f"{base_url.rstrip('/')}/data"
                params = {
                    "station": stn,
                    "start":   start_date.isoformat(),
                    "end":     end_date.isoformat(),
                    "variable": "rainfall",
                }
                headers = {"Authorization": f"Bearer {api_key}"}
                r = requests.get(endpoint, params=params, headers=headers, timeout=60)
                r.raise_for_status()
                data = r.json()

                # Expect list of {"timestamp": "...", "value": ...}
                df_stn = pd.DataFrame(data)
                df_stn["timestamp"] = pd.to_datetime(df_stn["timestamp"])
                df_stn = df_stn.set_index("timestamp").rename(columns={"value": stn})
                all_series.append(df_stn)

            df_rain = pd.concat(all_series, axis=1)
            # Average across stations → catchment-wide daily rainfall (mm/day)
            df_rain["rainfall_mm"] = df_rain.mean(axis=1)
            # Resample to daily totals if sub-daily
            df_daily = df_rain["rainfall_mm"].resample("D").sum()
            # Reindex to full simulation period (fill missing days with 0)
            date_range = pd.date_range(start_date, end_date, freq="D")
            df_daily = df_daily.reindex(date_range, fill_value=0.0)

            st.session_state["rain_series"] = df_daily
            st.success(
                f"Fetched {len(df_daily)} days from {len(stations)} station(s).  \n"
                f"Mean daily rainfall: **{df_daily.mean():.2f} mm/day**"
            )
        except Exception as e:
            st.error(f"Fetch failed: {e}  \n\nCheck base URL, API key and station IDs.")

# ── Or upload CSV ─────────────────────────────────────────────────────────────
st.markdown("---  *or* ---")
uploaded_rain = st.file_uploader(
    "Upload rainfall CSV (columns: date, rainfall_mm)",
    type=["csv", "dat", "txt"],
)
if uploaded_rain:
    df_up = pd.read_csv(uploaded_rain, parse_dates=[0], index_col=0)
    df_up.columns = ["rainfall_mm"]
    st.session_state["rain_series"] = df_up["rainfall_mm"]
    st.success(f"Loaded {len(df_up)} rows from uploaded file.")

# Preview rain
if st.session_state.get("rain_series") is not None:
    rain = st.session_state["rain_series"]
    fig, ax = plt.subplots(figsize=(10, 3))
    ax.bar(rain.index, rain.values, width=1, color="steelblue", alpha=0.8)
    ax.set_ylabel("Rainfall (mm/day)")
    ax.set_title("Daily Rainfall Series")
    st.pyplot(fig)
    plt.close()

# ── 8.2 Evapotranspiration ────────────────────────────────────────────────────
st.header("8.2  Evapotranspiration")

et_method = st.radio(
    "ET method",
    ["Upload daily ET CSV", "Use long-term monthly mean (Fatoyinbo 2018 values)"],
    index=1,
)

if et_method == "Upload daily ET CSV":
    uploaded_et = st.file_uploader("Upload ET CSV (columns: date, ETo_mm)", type=["csv","dat","txt"])
    if uploaded_et:
        df_et = pd.read_csv(uploaded_et, parse_dates=[0], index_col=0)
        df_et.columns = ["ETo_mm"]
        st.session_state["et_series"] = df_et["ETo_mm"]
        st.success(f"Loaded {len(df_et)} rows of ET data.")
else:
    # Fatoyinbo (2018) mean monthly ETo for Mhlanga catchment (mm/day)
    monthly_eto = {
         1: 5.2, 2: 5.0, 3: 4.5, 4: 3.8, 5: 3.2, 6: 2.8,
         7: 2.9, 8: 3.4, 9: 4.0, 10: 4.7, 11: 5.1, 12: 5.3,
    }
    st.caption("Mean monthly ETo (mm/day) from Fatoyinbo (2018) — FAO Penman-Monteith:")
    st.write(pd.DataFrame(monthly_eto, index=["ETo (mm/day)"]))

    if start_date and end_date:
        date_range = pd.date_range(start_date, end_date, freq="D")
        et_vals = np.array([monthly_eto[d.month] for d in date_range])
        et_series = pd.Series(et_vals, index=date_range, name="ETo_mm")
        st.session_state["et_series"] = et_series
        st.caption(f"Generated {len(et_series)}-day ET series from monthly means.")

if st.session_state.get("et_series") is not None:
    et = st.session_state["et_series"]
    fig, ax = plt.subplots(figsize=(10, 3))
    ax.plot(et.index, et.values, color="tomato", linewidth=0.8)
    ax.set_ylabel("ETo (mm/day)")
    ax.set_title("Reference ET Series")
    st.pyplot(fig)
    plt.close()

# ── 8.3 Write HDF5 forcing files ──────────────────────────────────────────────
st.header("8.3  Write HDF5 Forcing Files")

group_name = st.text_input(
    "HDF5 group name (must match TOPKAPI.ini [groups] section)",
    value="sample event",
)

can_write = (
    st.session_state.get("rain_series") is not None
    and st.session_state.get("et_series") is not None
)

if st.button("💾 Write rainfields.h5 + ET.h5", disabled=not can_write):
    with st.spinner("Writing HDF5 forcing files…"):
        try:
            import h5py
            import numpy as np

            n_cells = st.session_state.n_cells
            rain = st.session_state["rain_series"].values.astype(np.float64)
            et   = st.session_state["et_series"].values.astype(np.float64)

            # Ensure same length
            n_steps = min(len(rain), len(et))
            rain = rain[:n_steps]
            et   = et[:n_steps]

            # Broadcast: (n_steps,) → (n_steps, n_cells)  [uniform spatial distribution]
            rain_2d = np.tile(rain.reshape(-1, 1), (1, n_cells))
            et_2d   = np.tile(et.reshape(-1,   1), (1, n_cells))

            # rainfields.h5
            rain_path = os.path.join(forcing_dir, "rainfields.h5")
            with h5py.File(rain_path, "w") as h:
                g = h.create_group(group_name)
                g.create_dataset(
                    "rainfall", data=rain_2d,
                    chunks=True, compression="gzip", compression_opts=9,
                )
            st.session_state.rainfields_path = rain_path

            # ET.h5
            et_path = os.path.join(forcing_dir, "ET.h5")
            with h5py.File(et_path, "w") as h:
                g = h.create_group(group_name)
                g.create_dataset("ETo", data=et_2d, chunks=True, compression="gzip", compression_opts=9)
                g.create_dataset("ETr", data=et_2d, chunks=True, compression="gzip", compression_opts=9)
            st.session_state.et_path = et_path

            st.success(
                f"✅ rainfields.h5 — shape {rain_2d.shape}  \n"
                f"✅ ET.h5          — shape {et_2d.shape}  \n"
                f"Written to `{forcing_dir}`"
            )

        except Exception as e:
            st.error(f"HDF5 write failed: {e}")

st.divider()
if st.session_state.rainfields_path:
    st.success("✅ Forcing files ready. Proceed to **▶️ Run Model** in the sidebar.")

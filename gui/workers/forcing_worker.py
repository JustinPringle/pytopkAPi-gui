"""
gui/workers/forcing_worker.py
==============================
ForcingWorker  — converts tabular rainfall / ET data to PyTOPKAPI HDF5 format.

Tasks:
  'rainfall'    : single CSV/Excel → rainfields.h5  (datetime index, numeric cols)
  'obscape'     : folder of Obscape gauge CSVs → rainfields.h5 (auto-averages)
  'et'          : single CSV/Excel ET data → ET.h5  (ETr + ETo datasets)
  'synthetic_et': generate daily ET from KZN monthly means → ET.h5

HDF5 structure:
  rainfields.h5  /{group_name}/rainfall  (T, n_cells)  float32  [mm/day]
  ET.h5          /{group_name}/ETr        (T, n_cells)  float32  [mm/day]
                 /{group_name}/ETo        (T, n_cells)  float32  [mm/day]
"""

import os
import numpy as np
from gui.workers.base_worker import BaseWorker


class ForcingWorker(BaseWorker):
    def __init__(self, state, task: str = "rainfall", source_path: str = ""):
        super().__init__()
        self._state       = state
        self._task        = task
        self._source_path = source_path

    def run(self):
        try:
            if self._task == "rainfall":
                self._rainfall()
            elif self._task == "obscape":
                self._obscape()
            elif self._task == "et":
                self._et()
            elif self._task == "synthetic_et":
                self._synthetic_et()
            else:
                self.error.emit(f"Unknown ForcingWorker task: {self._task!r}")
        except Exception as exc:
            import traceback
            self.error.emit(f"[ForcingWorker/{self._task}] {exc}\n{traceback.format_exc()}")

    # ── Single-file rainfall ───────────────────────────────────────────────────

    def _rainfall(self):
        import h5py

        state = self._state
        if not state.n_cells:
            self.error.emit("n_cells not set. Load catchment mask (Step 3) first.")
            return

        src = self._source_path
        if not src or not os.path.exists(src):
            self.error.emit("Rainfall source file not found.")
            return

        out_dir  = os.path.join(state.project_dir, "forcing_variables")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "rainfields.h5")

        self.log_message.emit(f"Reading rainfall from {os.path.basename(src)}…")
        self.progress.emit(15)

        df = self._read_table(src)
        self.log_message.emit(f"  {len(df)} timesteps, {len(df.columns)} column(s).")
        self.progress.emit(40)

        arr = self._broadcast(df.values.astype(np.float32), state.n_cells)

        self.progress.emit(70)
        self.log_message.emit(f"Writing {out_path}…")
        with h5py.File(out_path, "w") as f:
            grp = f.require_group(state.group_name)
            grp.create_dataset("rainfall", data=arr, compression="gzip")

        self.progress.emit(100)
        self.log_message.emit(
            f"rainfields.h5 written ({arr.shape[0]} timesteps, {arr.shape[1]} cells)."
        )
        self.finished.emit({"rainfields_path": out_path})

    # ── Obscape multi-gauge CSV folder ────────────────────────────────────────

    def _obscape(self):
        import glob
        import pandas as pd
        import h5py

        state = self._state
        if not state.n_cells:
            self.error.emit("n_cells not set. Load catchment mask (Step 3) first.")
            return

        csv_dir = self._source_path
        if not csv_dir or not os.path.isdir(csv_dir):
            self.error.emit("Select a folder containing the Obscape gauge CSV files.")
            return

        csvs = sorted(glob.glob(os.path.join(csv_dir, "*.csv")))
        if not csvs:
            self.error.emit(f"No CSV files found in {csv_dir}")
            return

        self.log_message.emit(f"Found {len(csvs)} CSV file(s) in folder…")
        self.progress.emit(10)

        # Expected Obscape format: columns  ,year,month,day,rain
        series_list = []
        for csv_path in csvs:
            gauge_name = os.path.splitext(os.path.basename(csv_path))[0]
            try:
                df = pd.read_csv(csv_path, index_col=0)
                # Build datetime index from year/month/day columns
                dates = pd.to_datetime(df[["year", "month", "day"]])
                rain  = df["rain"].values.astype(np.float32)
                if rain.sum() < 1.0:
                    self.log_message.emit(
                        f"  Skipping {gauge_name} (total = {rain.sum():.1f} mm — likely broken)"
                    )
                    continue
                s = pd.Series(rain, index=dates, name=gauge_name)
                series_list.append(s)
                self.log_message.emit(
                    f"  {gauge_name}: {len(s)} days, total = {rain.sum():.1f} mm"
                )
            except Exception as exc:
                self.log_message.emit(f"  Warning: could not read {gauge_name}: {exc}")

        if not series_list:
            self.error.emit("No valid gauge data found in folder.")
            return

        self.log_message.emit(
            f"{len(series_list)} valid gauge(s) — computing spatial mean…"
        )
        self.progress.emit(50)

        combined   = pd.concat(series_list, axis=1).sort_index()
        mean_rain  = combined.mean(axis=1).values.astype(np.float32)  # (T,) mm/day

        # Broadcast to (T, n_cells)
        arr = np.tile(mean_rain.reshape(-1, 1), (1, state.n_cells))

        out_dir  = os.path.join(state.project_dir, "forcing_variables")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "rainfields.h5")

        self.progress.emit(80)
        self.log_message.emit(f"Writing {out_path}…")
        with h5py.File(out_path, "w") as f:
            grp = f.require_group(state.group_name)
            grp.create_dataset("rainfall", data=arr, compression="gzip")

        self.progress.emit(100)
        self.log_message.emit(
            f"rainfields.h5 written: {arr.shape[0]} timesteps, "
            f"mean rainfall = {mean_rain.mean():.2f} mm/day"
        )
        self.finished.emit({"rainfields_path": out_path})

    # ── Single-file ET (CSV/Excel) → ETr + ETo ────────────────────────────────

    def _et(self):
        import h5py

        state = self._state
        if not state.n_cells:
            self.error.emit("n_cells not set. Load catchment mask (Step 3) first.")
            return

        src = self._source_path
        if not src or not os.path.exists(src):
            self.error.emit("ET source file not found.")
            return

        out_dir  = os.path.join(state.project_dir, "forcing_variables")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "ET.h5")

        self.log_message.emit(f"Reading ET from {os.path.basename(src)}…")
        self.progress.emit(15)

        df  = self._read_table(src)
        arr = self._broadcast(df.values.astype(np.float32), state.n_cells)

        self.progress.emit(70)
        self.log_message.emit(f"Writing {out_path} (ETr + ETo)…")
        with h5py.File(out_path, "w") as f:
            grp = f.require_group(state.group_name)
            grp.create_dataset("ETr", data=arr, compression="gzip")
            grp.create_dataset("ETo", data=arr, compression="gzip")

        self.progress.emit(100)
        self.log_message.emit(
            f"ET.h5 written ({arr.shape[0]} timesteps, ETr = ETo from file)."
        )
        self.finished.emit({"et_path": out_path})

    # ── Synthetic ET from KZN monthly means ───────────────────────────────────

    def _synthetic_et(self):
        import h5py
        import pandas as pd

        state = self._state
        if not state.n_cells:
            self.error.emit("n_cells not set. Load catchment mask (Step 3) first.")
            return

        # Reference crop ET monthly means (mm/day) for coastal KZN (Durban area)
        # Derived from Schulze (2007) South Africa Atlas of Agrohydrology
        ETR_MONTHLY = {
            1: 4.5, 2: 4.2, 3: 3.8, 4: 3.2,
            5: 2.5, 6: 2.2, 7: 2.4, 8: 2.9,
            9: 3.3, 10: 3.7, 11: 4.1, 12: 4.4,
        }

        self.log_message.emit("Generating synthetic daily ET from KZN monthly means…")
        self.progress.emit(10)

        # Match length to rainfields.h5 if available; otherwise use Obscape period
        n_steps = None
        start_date = "2022-03-01"
        if state.rainfields_path and os.path.exists(state.rainfields_path):
            import h5py as _h5
            with _h5.File(state.rainfields_path, "r") as rf:
                n_steps = rf[f"/{state.group_name}/rainfall"].shape[0]

        if n_steps is None:
            n_steps = 365

        dates = pd.date_range(start_date, periods=n_steps, freq="D")
        self.progress.emit(30)

        etr = np.array([ETR_MONTHLY[d.month] for d in dates], dtype=np.float32)
        eto = (etr * 1.15).astype(np.float32)   # open water slightly higher

        # Broadcast: (T,) → (T, n_cells)
        ETr = np.tile(etr.reshape(-1, 1), (1, state.n_cells))
        ETo = np.tile(eto.reshape(-1, 1), (1, state.n_cells))

        out_dir  = os.path.join(state.project_dir, "forcing_variables")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "ET.h5")

        self.progress.emit(70)
        self.log_message.emit(f"Writing {out_path}…")
        with h5py.File(out_path, "w") as f:
            grp = f.require_group(state.group_name)
            grp.create_dataset("ETr", data=ETr, compression="gzip")
            grp.create_dataset("ETo", data=ETo, compression="gzip")

        self.progress.emit(100)
        self.log_message.emit(
            f"ET.h5 written: {n_steps} timesteps, "
            f"ETr mean = {etr.mean():.2f} mm/day, "
            f"ETo mean = {eto.mean():.2f} mm/day"
        )
        self.finished.emit({"et_path": out_path})

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _read_table(path: str):
        """Read CSV or Excel; return DataFrame of numeric columns only."""
        import pandas as pd
        if path.lower().endswith((".xlsx", ".xls")):
            df = pd.read_excel(path, index_col=0, parse_dates=True)
        else:
            df = pd.read_csv(path, index_col=0, parse_dates=True)
        return df.select_dtypes(include="number")

    @staticmethod
    def _broadcast(arr: np.ndarray, n_cells: int) -> np.ndarray:
        """Ensure shape is (T, n_cells); broadcast single column if needed."""
        if arr.ndim == 1 or arr.shape[1] == 1:
            return np.repeat(arr.reshape(-1, 1), n_cells, axis=1)
        if arr.shape[1] != n_cells:
            return np.repeat(arr[:, 0:1], n_cells, axis=1)
        return arr

"""
gui/workers/forcing_worker.py
==============================
ForcingWorker  — converts tabular rainfall / ET data to PyTOPKAPI HDF5 format.

  task='rainfall' : reads CSV/Excel rainfall data → rainfields.h5
  task='et'       : reads CSV/Excel ET data → ET.h5

The CSV/Excel format expected:
  - First column: datetime strings parseable by pandas
  - Remaining columns: one per catchment cell (or a single column for uniform input)
  - If a single column is provided, it is broadcast across all n_cells

HDF5 structure written:
  /{group_name}/rainfall  shape (n_timesteps, n_cells) float32  [mm/s]
  /{group_name}/ET        shape (n_timesteps, n_cells) float32  [mm/day → mm/s]
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
            elif self._task == "et":
                self._et()
            else:
                self.error.emit(f"Unknown ForcingWorker task: {self._task!r}")
        except Exception as exc:
            self.error.emit(f"[ForcingWorker/{self._task}] {exc}")

    # ──────────────────────────────────────────────────────────────────────────

    def _rainfall(self):
        import pandas as pd
        import h5py

        state = self._state
        if not state.n_cells:
            self.error.emit("n_cells not set. Complete watershed delineation (Step 3) first.")
            return

        src = self._source_path
        if not src or not os.path.exists(src):
            self.error.emit("Rainfall source file not found. Browse to a CSV or Excel file first.")
            return

        out_dir  = os.path.join(state.project_dir, "forcing_variables")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "rainfields.h5")

        self.log_message.emit(f"Reading rainfall data from {os.path.basename(src)}…")
        self.progress.emit(15)

        df = self._read_table(src)
        self.log_message.emit(f"  {len(df)} timesteps read.")
        self.progress.emit(40)

        # Build (n_timesteps, n_cells) array — broadcast if single column
        arr = df.values.astype(np.float32)   # shape (T,) or (T, cols)
        if arr.ndim == 1 or arr.shape[1] == 1:
            arr = np.repeat(arr.reshape(-1, 1), state.n_cells, axis=1)
        elif arr.shape[1] != state.n_cells:
            self.log_message.emit(
                f"  Warning: {arr.shape[1]} columns vs {state.n_cells} cells — "
                "broadcasting first column."
            )
            arr = np.repeat(arr[:, 0:1], state.n_cells, axis=1)

        # Convert mm/h → mm/s (divide by 3600) if needed — leave as-is for now
        # PyTOPKAPI expects mm/s; user is responsible for correct units.

        self.progress.emit(70)
        self.log_message.emit(f"Writing {out_path}…")
        with h5py.File(out_path, "w") as f:
            grp = f.require_group(state.rain_group)
            grp.create_dataset("rainfall", data=arr, compression="gzip")

        self.progress.emit(100)
        self.log_message.emit(f"rainfields.h5 written ({arr.shape[0]} timesteps, {arr.shape[1]} cells).")
        self.finished.emit({"rainfields_path": out_path})

    def _et(self):
        import pandas as pd
        import h5py

        state = self._state
        if not state.n_cells:
            self.error.emit("n_cells not set. Complete watershed delineation (Step 3) first.")
            return

        src = self._source_path
        if not src or not os.path.exists(src):
            self.error.emit("ET source file not found. Browse to a CSV or Excel file first.")
            return

        out_dir  = os.path.join(state.project_dir, "forcing_variables")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "ET.h5")

        self.log_message.emit(f"Reading ET data from {os.path.basename(src)}…")
        self.progress.emit(15)

        df  = self._read_table(src)
        arr = df.values.astype(np.float32)
        if arr.ndim == 1 or arr.shape[1] == 1:
            arr = np.repeat(arr.reshape(-1, 1), state.n_cells, axis=1)
        elif arr.shape[1] != state.n_cells:
            arr = np.repeat(arr[:, 0:1], state.n_cells, axis=1)

        self.progress.emit(70)
        self.log_message.emit(f"Writing {out_path}…")
        with h5py.File(out_path, "w") as f:
            grp = f.require_group(state.et_group)
            grp.create_dataset("ET", data=arr, compression="gzip")

        self.progress.emit(100)
        self.log_message.emit(f"ET.h5 written ({arr.shape[0]} timesteps, {arr.shape[1]} cells).")
        self.finished.emit({"et_path": out_path})

    @staticmethod
    def _read_table(path: str):
        """Read CSV or Excel; return DataFrame of numeric columns only."""
        import pandas as pd
        if path.lower().endswith((".xlsx", ".xls")):
            df = pd.read_excel(path, index_col=0, parse_dates=True)
        else:
            df = pd.read_csv(path, index_col=0, parse_dates=True)
        return df.select_dtypes(include="number")

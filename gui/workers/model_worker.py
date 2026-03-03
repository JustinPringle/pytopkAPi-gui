"""
gui/workers/model_worker.py
============================
ModelWorker  — runs the PyTOPKAPI model in a background QThread.

Calls pytopkapi.run(ini_path) which writes results to the HDF5 file
specified in TOPKAPI.ini → [paths] → result_file.

Emits:
  log_message(str)   : stdout/stderr lines from the model
  progress(int)      : indeterminate (pulsed) — 0 then 50 then 100
  finished(dict)     : {"results_path": path}
  error(str)         : if the model raises an exception
"""

import os
from gui.workers.base_worker import BaseWorker


class ModelWorker(BaseWorker):
    def __init__(self, state):
        super().__init__()
        self._state = state

    def run(self):
        try:
            self._run_model()
        except Exception as exc:
            self.error.emit(f"[ModelWorker] {exc}")

    def _run_model(self):
        import pytopkapi

        state = self._state
        if not state.ini_path or not os.path.exists(state.ini_path):
            self.error.emit("TOPKAPI.ini not found. Generate parameter files (Step 7) first.")
            return

        self.log_message.emit(f"Starting PyTOPKAPI model run…")
        self.log_message.emit(f"  Config: {state.ini_path}")
        self.progress.emit(10)

        # pytopkapi.run() does not provide incremental progress.
        # We emit 50% before the run and 100% after.
        self.progress.emit(50)
        pytopkapi.run(state.ini_path)

        self.progress.emit(100)
        self.log_message.emit("Model run complete.")

        # Determine results path from TOPKAPI.ini
        from configparser import ConfigParser
        cfg = ConfigParser()
        cfg.read(state.ini_path)
        results_path = cfg.get("paths", "result_file", fallback=None)
        if results_path and os.path.exists(results_path):
            self.log_message.emit(f"Results: {results_path}")
            self.finished.emit({"results_path": results_path})
        else:
            self.finished.emit({})
            self.log_message.emit("Warning: results file not found after model run.")

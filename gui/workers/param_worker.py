"""
gui/workers/param_worker.py
============================
ParamWorker  — generates the PyTOPKAPI parameter files:
  1. Writes param_setup.ini  (raster paths + initial conditions)
  2. Calls create_file.generate_param_file(ini_fname) → cell_param.dat
  3. Writes TOPKAPI.ini (full model run config)

Emits finished({"param_setup_path": ..., "cell_param_path": ..., "ini_path": ...}).
"""

import os
from configparser import ConfigParser

from gui.workers.base_worker import BaseWorker


class ParamWorker(BaseWorker):
    def __init__(self, state):
        super().__init__()
        self._state = state

    def run(self):
        try:
            self._generate()
        except Exception as exc:
            self.error.emit(f"[ParamWorker] {exc}")

    def _generate(self):
        import create_file  # from vendor/ via sys.path

        state = self._state
        param_dir = os.path.join(state.project_dir, "parameter_files")
        os.makedirs(param_dir, exist_ok=True)

        # ── Validate required rasters ─────────────────────────────────────
        required = {
            "Filled DEM":     state.filled_dem_path,
            "Catchment mask": state.mask_path,
            "Slope":          state.slope_path,
            "Flow direction": state.fdir_path,
            "Stream network": state.strahler_path,
            "Soil depth":     state.soil_depth_path,
            "Ks":             state.hwsd_ks_path,
            "θs":             state.hwsd_theta_path,
            "θr":             state.hwsd_theta_r_path,
            "ψb":             state.hwsd_psi_b_path,
            "Manning n_o":    state.mannings_path,
        }
        missing = [k for k, v in required.items() if not v or not os.path.exists(v)]
        if missing:
            self.error.emit("Missing required rasters:\n  " + "\n  ".join(missing))
            return

        self.log_message.emit("Writing param_setup.ini…")
        self.progress.emit(15)

        # ── Write param_setup.ini ─────────────────────────────────────────
        cell_param_path = os.path.join(param_dir, "cell_param.dat")
        ini_path        = os.path.join(param_dir, "TOPKAPI.ini")
        setup_path      = os.path.join(param_dir, "param_setup.ini")

        cfg = ConfigParser()
        cfg["raster_files"] = {
            "dem_fname":                    state.filled_dem_path,
            "mask_fname":                   state.mask_path,
            "soil_depth_fname":             state.soil_depth_path,
            "conductivity_fname":           state.hwsd_ks_path,
            "hillslope_fname":              state.slope_path,
            "sat_moisture_content_fname":   state.hwsd_theta_path,
            "resid_moisture_content_fname": state.hwsd_theta_r_path,
            "bubbling_pressure_fname":      state.hwsd_psi_b_path,
            "pore_size_dist_fname":         state.hwsd_pore_path or state.hwsd_psi_b_path,
            "overland_manning_fname":       state.mannings_path,
            "channel_network_fname":        state.strahler_path,
            "flowdir_fname":                state.fdir_path,
            "flowdir_source":               "GRASS",
        }
        cfg["output"] = {
            "param_fname": cell_param_path,
        }
        cfg["numerical_values"] = {
            "pVs_t0": str(state.pVs_t0),
            "Vo_t0":  str(state.Vo_t0),
            "Qc_t0":  str(state.Qc_t0),
            "Kc":     str(state.Kc),
        }
        with open(setup_path, "w") as f:
            cfg.write(f)

        # ── Call create_file.generate_param_file ──────────────────────────
        self.log_message.emit("Generating cell parameter file…")
        self.progress.emit(40)
        create_file.generate_param_file(setup_path)

        if not os.path.exists(cell_param_path):
            self.error.emit("create_file.generate_param_file did not produce cell_param.dat")
            return

        self.log_message.emit(f"cell_param.dat written: {cell_param_path}")
        self.progress.emit(70)

        # ── Write TOPKAPI.ini ─────────────────────────────────────────────
        self.log_message.emit("Writing TOPKAPI.ini…")
        self._write_topkapi_ini(ini_path, cell_param_path, state)
        self.progress.emit(100)
        self.log_message.emit(f"TOPKAPI.ini written: {ini_path}")

        self.finished.emit({
            "param_setup_path": setup_path,
            "cell_param_path":  cell_param_path,
            "ini_path":         ini_path,
        })

    @staticmethod
    def _write_topkapi_ini(ini_path: str, cell_param_path: str, state) -> None:
        """Write the TOPKAPI model run configuration file."""
        param_dir   = os.path.dirname(ini_path)
        results_dir = os.path.join(state.project_dir, "results")
        os.makedirs(results_dir, exist_ok=True)

        results_path = os.path.join(results_dir, "simulation_output.h5")

        cfg = ConfigParser()
        cfg["topkapi_options"] = {
            "field_names": "0",
        }
        cfg["paths"] = {
            "param_file":   cell_param_path,
            "rain_file":    state.rainfields_path or "",
            "ET_file":      state.et_path or "",
            "result_file":  results_path,
        }
        cfg["groups"] = {
            "rain_group": state.rain_group,
            "ET_group":   state.et_group,
        }
        cfg["numerical_values"] = {
            "dt":           str(state.dt_s),
            "alpha_s":      str(state.alpha_s),
            "alpha_oc":     str(state.alpha_oc),
            "alpha_c":      str(state.alpha_oc),
            "A_thres":      str(state.A_thres),
            "W_min":        str(state.W_min),
            "W_max":        str(state.W_max),
        }
        cfg["calibration"] = {
            "fac_L":   str(state.fac_L),
            "fac_Ks":  str(state.fac_Ks),
            "fac_n_o": str(state.fac_n_o),
            "fac_n_c": str(state.fac_n_c),
        }
        with open(ini_path, "w") as f:
            cfg.write(f)

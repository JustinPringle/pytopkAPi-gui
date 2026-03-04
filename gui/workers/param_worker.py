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
        from pytopkapi.parameter_utils import create_file

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

        cell_param_path  = os.path.join(param_dir, "cell_param.dat")
        global_param_path = os.path.join(param_dir, "global_param.dat")
        ini_path          = os.path.join(param_dir, "TOPKAPI.ini")
        setup_path        = os.path.join(param_dir, "param_setup.ini")

        # ── Write global_param.dat ────────────────────────────────────────
        self.log_message.emit("Writing global_param.dat…")
        self.progress.emit(10)
        self._write_global_param(global_param_path, state)
        self.log_message.emit(f"global_param.dat written: {global_param_path}")

        # ── Write param_setup.ini ─────────────────────────────────────────
        self.log_message.emit("Writing param_setup.ini…")
        self.progress.emit(20)

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
        self.progress.emit(75)

        # ── Write TOPKAPI.ini ─────────────────────────────────────────────
        self.log_message.emit("Writing TOPKAPI.ini…")
        self._write_topkapi_ini(ini_path, cell_param_path, global_param_path, state)
        self.progress.emit(100)
        self.log_message.emit(f"TOPKAPI.ini written: {ini_path}")

        self.finished.emit({
            "param_setup_path":  setup_path,
            "cell_param_path":   cell_param_path,
            "global_param_path": global_param_path,
            "ini_path":          ini_path,
        })

    @staticmethod
    def _write_global_param(path: str, state) -> None:
        """Write global_param.dat (header row + space-separated data row)."""
        # PyTOPKAPI pretreatment.read_global_parameters() reads columns:
        # X  Dt  alpha_s  alpha_o  alpha_c  A_thres  W_min  W_max
        header = "X Dt alpha_s alpha_o alpha_c A_thres W_min W_max"
        values = (
            f"{state.cell_size_m:.1f} "
            f"{state.dt_s} "
            f"{state.alpha_s} "
            f"{state.alpha_oc:.8f} "
            f"{state.alpha_oc:.8f} "
            f"{state.A_thres:.1f} "
            f"{state.W_min:.2f} "
            f"{state.W_max:.2f}"
        )
        with open(path, "w") as f:
            f.write(header + "\n")
            f.write(values + "\n")

    @staticmethod
    def _write_topkapi_ini(ini_path: str, cell_param_path: str,
                           global_param_path: str, state) -> None:
        """Write the TOPKAPI model run configuration file (correct section names)."""
        results_dir  = os.path.join(state.project_dir, "results")
        os.makedirs(results_dir, exist_ok=True)
        results_path = os.path.join(results_dir, "simulation_output.h5")

        cfg = ConfigParser()

        cfg["numerical_options"] = {
            "solve_s":              "1",
            "solve_o":              "1",
            "solve_c":              "1",
            "only_channel_output":  "False",
        }

        cfg["input_files"] = {
            "file_global_param": global_param_path,
            "file_cell_param":   cell_param_path,
            "file_rain":         state.rainfields_path or "",
            "file_ET":           state.et_path or "",
        }

        cfg["groups"] = {
            "group_name": state.group_name,
        }

        cfg["calib_params"] = {
            "fac_L":   str(state.fac_L),
            "fac_Ks":  str(state.fac_Ks),
            "fac_n_o": str(state.fac_n_o),
            "fac_n_c": str(state.fac_n_c),
        }

        cfg["external_flow"] = {
            "external_flow": "False",
        }

        cfg["output_files"] = {
            "file_out":       results_path,
            "append_output":  "False",
        }

        with open(ini_path, "w") as f:
            cfg.write(f)

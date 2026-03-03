"""
gui/workers/soil_worker.py
===========================
SoilWorker  — QThread worker for soil parameter raster generation:
  task='identify' : clip HWSD GeoTIFF to catchment mask → list of unique codes
  task='generate' : write depth, Ks, theta_s, theta_r, psi_b rasters from
                    the user-edited HWSD→parameter lookup table
"""

import os
import numpy as np
from gui.workers.base_worker import BaseWorker


class SoilWorker(BaseWorker):
    def __init__(self, state, task: str = "identify", hwsd_params: dict | None = None):
        super().__init__()
        self._state       = state
        self._task        = task
        self._hwsd_params = hwsd_params  # {code: {depth, Ks, theta_s, theta_r, psi_b}}

    def run(self):
        try:
            if self._task == "identify":
                self._identify()
            elif self._task == "generate":
                self._generate()
            else:
                self.error.emit(f"Unknown SoilWorker task: {self._task!r}")
        except Exception as exc:
            self.error.emit(f"[SoilWorker/{self._task}] {exc}")

    def _identify(self):
        """Clip HWSD raster to catchment mask and find unique soil codes."""
        import rasterio
        from rasterio.warp import reproject, Resampling

        state = self._state
        if not state.hwsd_path or not os.path.exists(state.hwsd_path):
            self.error.emit("HWSD raster path not set. Browse to the HWSD GeoTIFF first.")
            return
        if not state.mask_path or not os.path.exists(state.mask_path):
            self.error.emit("Catchment mask not found. Complete Step 3 first.")
            return

        out_dir  = os.path.join(state.project_dir, "rasters")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "hwsd_clipped.tif")

        self.log_message.emit("Clipping HWSD to catchment mask…")
        self.progress.emit(20)

        with rasterio.open(state.mask_path) as mask_src:
            mask_arr  = mask_src.read(1)
            mask_crs  = mask_src.crs
            mask_tf   = mask_src.transform
            mask_w    = mask_src.width
            mask_h    = mask_src.height
            out_prof  = mask_src.profile.copy()

        with rasterio.open(state.hwsd_path) as hwsd_src:
            hwsd_arr  = np.zeros((mask_h, mask_w), dtype=np.int32)
            reproject(
                source      = rasterio.band(hwsd_src, 1),
                destination = hwsd_arr,
                src_transform  = hwsd_src.transform,
                src_crs        = hwsd_src.crs,
                dst_transform  = mask_tf,
                dst_crs        = mask_crs,
                resampling     = Resampling.nearest,
            )

        self.progress.emit(65)
        hwsd_masked = np.where(mask_arr == 1, hwsd_arr, 0)
        codes = [int(c) for c in np.unique(hwsd_masked) if c != 0]
        self.log_message.emit(f"HWSD codes in catchment: {codes}")

        out_prof.update(dtype="int32", count=1, nodata=0)
        with rasterio.open(out_path, "w", **out_prof) as dst:
            dst.write(hwsd_masked[np.newaxis, :, :])

        self.progress.emit(100)
        self.log_message.emit(f"HWSD clipped: {out_path}")
        self.finished.emit({"hwsd_clipped_path": out_path, "hwsd_codes": codes})

    def _generate(self):
        """Write soil parameter rasters from the user-edited lookup table."""
        import rasterio

        state = self._state
        if not self._hwsd_params:
            self.error.emit("No soil parameter table provided.")
            return
        if not state.hwsd_clipped_path or not os.path.exists(state.hwsd_clipped_path):
            self.error.emit("Clipped HWSD raster not found. Run 'Identify Soils' first.")
            return

        out_dir = os.path.join(state.project_dir, "rasters")
        os.makedirs(out_dir, exist_ok=True)

        raster_fields = {
            "soil_depth_path":   ("depth",   "m",    "soil_depth.tif"),
            "hwsd_ks_path":      ("Ks",      "m/s",  "Ks.tif"),
            "hwsd_theta_path":   ("theta_s", "-",    "theta_s.tif"),
            "hwsd_theta_r_path": ("theta_r", "-",    "theta_r.tif"),
            "hwsd_psi_b_path":   ("psi_b",   "cm",   "psi_b.tif"),
        }

        with rasterio.open(state.hwsd_clipped_path) as src:
            codes_arr = src.read(1)
            profile   = src.profile.copy()
        profile.update(dtype="float32", count=1, nodata=-9999.0)

        result_paths: dict[str, str] = {}
        n_fields = len(raster_fields)
        for i, (state_key, (param, unit, fname)) in enumerate(raster_fields.items()):
            self.log_message.emit(f"Writing {fname}…")
            self.progress.emit(int(10 + 80 * i / n_fields))

            out_arr = np.full(codes_arr.shape, -9999.0, dtype=np.float32)
            for code, params in self._hwsd_params.items():
                out_arr[codes_arr == int(code)] = float(params.get(param, -9999.0))

            out_path = os.path.join(out_dir, fname)
            with rasterio.open(out_path, "w", **profile) as dst:
                dst.write(out_arr[np.newaxis, :, :])
            result_paths[state_key] = out_path

        self.progress.emit(100)
        self.log_message.emit("Soil parameter rasters written.")
        self.finished.emit(result_paths)

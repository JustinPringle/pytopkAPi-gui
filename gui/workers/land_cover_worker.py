"""
gui/workers/land_cover_worker.py
=================================
LandCoverWorker  — writes Manning overland roughness raster (n_o).

  task='generate' :
    If a land cover raster is provided: reclassify its values using the
    user-supplied {lc_code: n_o} table, clip to mask, write n_o.tif.
    If no land cover raster: write a uniform n_o raster over the mask.
"""

import os
import numpy as np
from gui.workers.base_worker import BaseWorker


class LandCoverWorker(BaseWorker):
    def __init__(self, state, task: str = "generate",
                 n_o_table: dict | None = None, uniform_n_o: float = 0.30):
        super().__init__()
        self._state      = state
        self._task       = task
        self._n_o_table  = n_o_table      # {lc_code: n_o_value}
        self._uniform_n_o = uniform_n_o

    def run(self):
        try:
            if self._task == "generate":
                self._generate()
            else:
                self.error.emit(f"Unknown LandCoverWorker task: {self._task!r}")
        except Exception as exc:
            self.error.emit(f"[LandCoverWorker/{self._task}] {exc}")

    def _generate(self):
        import rasterio
        from rasterio.warp import reproject, Resampling

        state = self._state
        if not state.mask_path or not os.path.exists(state.mask_path):
            self.error.emit("Catchment mask not found. Complete Step 3 first.")
            return

        out_dir  = os.path.join(state.project_dir, "rasters")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "mannings_no.tif")

        self.log_message.emit("Generating Manning n_o raster…")
        self.progress.emit(15)

        with rasterio.open(state.mask_path) as mask_src:
            mask_arr = mask_src.read(1)
            profile  = mask_src.profile.copy()
            mask_tf  = mask_src.transform
            mask_crs = mask_src.crs
            h, w     = mask_arr.shape
        profile.update(dtype="float32", count=1, nodata=-9999.0)

        n_o_arr = np.full((h, w), -9999.0, dtype=np.float32)

        if state.lc_path and os.path.exists(state.lc_path) and self._n_o_table:
            self.log_message.emit("Reclassifying land cover → n_o…")
            self.progress.emit(35)

            with rasterio.open(state.lc_path) as lc_src:
                lc_repr = np.zeros((h, w), dtype=np.int32)
                reproject(
                    source      = rasterio.band(lc_src, 1),
                    destination = lc_repr,
                    src_transform  = lc_src.transform,
                    src_crs        = lc_src.crs,
                    dst_transform  = mask_tf,
                    dst_crs        = mask_crs,
                    resampling     = Resampling.nearest,
                )

            for lc_code, n_val in self._n_o_table.items():
                n_o_arr[lc_repr == int(lc_code)] = float(n_val)

            # Fill any un-classified cells with the first table value or default
            default_no = list(self._n_o_table.values())[0] if self._n_o_table else 0.30
            n_o_arr[(mask_arr == 1) & (n_o_arr == -9999.0)] = default_no

        else:
            # Uniform n_o over the entire mask
            self.log_message.emit(f"Uniform n_o = {self._uniform_n_o:.3f}")
            n_o_arr[mask_arr == 1] = self._uniform_n_o

        self.progress.emit(80)
        with rasterio.open(out_path, "w", **profile) as dst:
            dst.write(n_o_arr[np.newaxis, :, :])

        self.progress.emit(100)
        self.log_message.emit(f"Manning n_o raster written: {out_path}")
        self.finished.emit({"mannings_path": out_path, "landcover_ready": True})

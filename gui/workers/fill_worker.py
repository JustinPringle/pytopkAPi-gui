"""
gui/workers/fill_worker.py
==========================
FillWorker  — QThread worker for pysheds DEM processing:
  task='fill'    : fill pits + depressions + resolve flats → filled DEM GeoTIFF
  task='flowdir' : compute flow direction, recode ESRI→GRASS, write GeoTIFF
  task='accum'   : compute flow accumulation, write GeoTIFF

Each task emits finished({"<field>": path}) so MainWindow patches ProjectState.

GRASS flow direction coding (required by create_file.py):
    ESRI:  64=E, 128=NE, 1=N,  2=NW, 4=W,  8=SW,  16=S, 32=SE
    GRASS:  1=E,   2=NE, 3=N,  4=NW, 5=W,  6=SW,   7=S,  8=SE
"""

import os
import shutil

import numpy as np

from gui.workers.base_worker import BaseWorker

_ESRI_TO_GRASS = {64: 1, 128: 2, 1: 3, 2: 4, 4: 5, 8: 6, 16: 7, 32: 8}


class FillWorker(BaseWorker):
    """Runs pysheds fill → flowdir → accumulation tasks."""

    def __init__(self, state, task: str = "fill"):
        super().__init__()
        self._state = state
        self._task  = task

    def run(self):
        try:
            if self._task == "fill":
                self._fill()
            elif self._task == "flowdir":
                self._flowdir()
            elif self._task == "accum":
                self._accum()
            else:
                self.error.emit(f"Unknown FillWorker task: {self._task!r}")
        except Exception as exc:
            self.error.emit(f"[FillWorker/{self._task}] {exc}")

    # ──────────────────────────────────────────────────────────────────────────
    # Task implementations
    # ──────────────────────────────────────────────────────────────────────────

    def _fill(self):
        """Fill pits, depressions, and resolve flats in the projected DEM."""
        from pysheds.grid import Grid

        in_path  = self._state.proj_dem_path
        if not in_path or not os.path.exists(in_path):
            self.error.emit("Projected DEM not found. Run Step 1 → Reproject first.")
            return

        out_dir  = os.path.join(self._state.project_dir, "rasters")
        out_path = os.path.join(out_dir, "filled_dem.tif")

        self.log_message.emit("Filling DEM pits and depressions…")
        self.progress.emit(10)

        grid = Grid.from_raster(in_path)
        dem  = grid.read_raster(in_path)

        self.progress.emit(25)
        self.log_message.emit("Filling pits…")
        pit_filled = grid.fill_pits(dem)

        self.progress.emit(45)
        self.log_message.emit("Filling depressions…")
        flooded = grid.fill_depressions(pit_filled)

        self.progress.emit(65)
        self.log_message.emit("Resolving flats…")
        inflated = grid.resolve_flats(flooded)

        self.progress.emit(80)
        self.log_message.emit(f"Writing filled DEM → {out_path}")
        grid.to_raster(inflated, out_path)

        self.progress.emit(100)
        self.log_message.emit("DEM filling complete.")
        self.finished.emit({"filled_dem_path": out_path})

    def _flowdir(self):
        """Compute flow direction (pysheds ESRI) and recode to GRASS convention."""
        import rasterio
        from rasterio.transform import from_bounds
        from pysheds.grid import Grid

        in_path = self._state.filled_dem_path
        if not in_path or not os.path.exists(in_path):
            self.error.emit("Filled DEM not found. Run 'Fill DEM' first.")
            return

        out_dir  = os.path.join(self._state.project_dir, "rasters")
        out_path = os.path.join(out_dir, "flow_dir.tif")

        self.log_message.emit("Computing flow direction…")
        self.progress.emit(20)

        grid  = Grid.from_raster(in_path)
        dem   = grid.read_raster(in_path)

        self.progress.emit(40)
        fdir_esri = grid.flowdir(dem)

        self.progress.emit(65)
        self.log_message.emit("Recoding ESRI → GRASS flow direction…")
        fdir_arr  = np.array(fdir_esri, dtype=np.int16)
        fdir_grass = np.zeros_like(fdir_arr)
        for esri_val, grass_val in _ESRI_TO_GRASS.items():
            fdir_grass[fdir_arr == esri_val] = grass_val

        self.progress.emit(80)
        # Write to GeoTIFF preserving spatial reference
        with rasterio.open(in_path) as src:
            profile = src.profile.copy()
        profile.update(dtype="int16", count=1, nodata=-1)

        os.makedirs(out_dir, exist_ok=True)
        with rasterio.open(out_path, "w", **profile) as dst:
            dst.write(fdir_grass[np.newaxis, :, :])

        self.progress.emit(100)
        self.log_message.emit("Flow direction complete.")
        self.finished.emit({"fdir_path": out_path})

    def _accum(self):
        """Compute flow accumulation from the filled DEM."""
        import rasterio
        from pysheds.grid import Grid

        in_path = self._state.filled_dem_path
        if not in_path or not os.path.exists(in_path):
            self.error.emit("Filled DEM not found. Run 'Fill DEM' first.")
            return

        out_dir  = os.path.join(self._state.project_dir, "rasters")
        out_path = os.path.join(out_dir, "flow_accum.tif")

        self.log_message.emit("Computing flow accumulation…")
        self.progress.emit(20)

        grid = Grid.from_raster(in_path)
        dem  = grid.read_raster(in_path)

        self.progress.emit(35)
        fdir = grid.flowdir(dem)

        self.progress.emit(60)
        self.log_message.emit("Accumulating flow…")
        acc = grid.accumulation(fdir)

        self.progress.emit(85)
        acc_arr = np.array(acc, dtype=np.float32)

        with rasterio.open(in_path) as src:
            profile = src.profile.copy()
        profile.update(dtype="float32", count=1, nodata=-1.0)

        os.makedirs(out_dir, exist_ok=True)
        with rasterio.open(out_path, "w", **profile) as dst:
            dst.write(acc_arr[np.newaxis, :, :])

        self.progress.emit(100)
        self.log_message.emit("Flow accumulation complete.")
        self.finished.emit({"accum_path": out_path})

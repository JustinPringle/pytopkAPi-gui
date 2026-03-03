"""
gui/workers/stream_worker.py
=============================
StreamWorker  — QThread worker for stream network extraction:
  task='extract'  : acc >= threshold → binary stream raster GeoTIFF
  task='strahler' : Strahler stream ordering → order raster GeoTIFF
"""

import os
import numpy as np
from gui.workers.base_worker import BaseWorker


class StreamWorker(BaseWorker):
    def __init__(self, state, task: str = "extract"):
        super().__init__()
        self._state = state
        self._task  = task

    def run(self):
        try:
            if self._task == "extract":
                self._extract()
            elif self._task == "strahler":
                self._strahler()
            else:
                self.error.emit(f"Unknown StreamWorker task: {self._task!r}")
        except Exception as exc:
            self.error.emit(f"[StreamWorker/{self._task}] {exc}")

    def _extract(self):
        import rasterio
        from pysheds.grid import Grid

        state = self._state
        if not state.accum_path or not os.path.exists(state.accum_path):
            self.error.emit("Flow accumulation not found. Complete Step 2 first.")
            return
        if not state.mask_path or not os.path.exists(state.mask_path):
            self.error.emit("Catchment mask not found. Complete Step 3 first.")
            return

        out_dir  = os.path.join(state.project_dir, "rasters")
        out_path = os.path.join(out_dir, "streamnet.tif")
        threshold = state.stream_threshold

        self.log_message.emit(f"Extracting streams (threshold = {threshold} cells)…")
        self.progress.emit(20)

        with rasterio.open(state.accum_path) as src:
            acc     = src.read(1).astype(float)
            profile = src.profile.copy()
        with rasterio.open(state.mask_path) as src:
            mask = src.read(1)

        self.progress.emit(50)
        stream = ((acc >= threshold) & (mask == 1)).astype(np.int16)
        n_stream = int(stream.sum())
        self.log_message.emit(f"Stream cells: {n_stream:,}")

        profile.update(dtype="int16", count=1, nodata=0)
        os.makedirs(out_dir, exist_ok=True)
        with rasterio.open(out_path, "w", **profile) as dst:
            dst.write(stream[np.newaxis, :, :])

        self.progress.emit(100)
        self.log_message.emit(f"Stream network written: {out_path}")
        self.finished.emit({"streamnet_path": out_path})

    def _strahler(self):
        import rasterio
        from pysheds.grid import Grid

        state = self._state
        if not state.filled_dem_path or not os.path.exists(state.filled_dem_path):
            self.error.emit("Filled DEM not found. Complete Step 2 first.")
            return
        if not state.streamnet_path or not os.path.exists(state.streamnet_path):
            self.error.emit("Stream network not found. Extract streams first.")
            return

        out_dir  = os.path.join(state.project_dir, "rasters")
        out_path = os.path.join(out_dir, "strahler.tif")

        self.log_message.emit("Computing Strahler stream orders…")
        self.progress.emit(20)

        grid = Grid.from_raster(state.filled_dem_path)
        dem  = grid.read_raster(state.filled_dem_path)

        self.progress.emit(35)
        fdir = grid.flowdir(dem)

        self.progress.emit(55)
        # Use the stream mask as a boolean mask
        with rasterio.open(state.streamnet_path) as src:
            stream_arr = src.read(1).astype(bool)

        # pysheds stream_order requires a flow direction and stream boolean mask
        order = grid.stream_order(fdir, stream_arr)
        order_arr = np.array(order, dtype=np.int16)

        self.progress.emit(85)
        with rasterio.open(state.filled_dem_path) as src:
            profile = src.profile.copy()
        profile.update(dtype="int16", count=1, nodata=0)

        os.makedirs(out_dir, exist_ok=True)
        with rasterio.open(out_path, "w", **profile) as dst:
            dst.write(order_arr[np.newaxis, :, :])

        max_order = int(order_arr.max())
        self.progress.emit(100)
        self.log_message.emit(f"Strahler orders complete (max order = {max_order}).")
        self.finished.emit({"strahler_path": out_path})

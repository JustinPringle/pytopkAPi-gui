"""
gui/workers/watershed_worker.py
================================
WatershedWorker  — QThread worker for watershed delineation:
  task='delineate' : pysheds catchment delineation from outlet point → mask GeoTIFF
  task='slope'     : gdaldem slope on filled DEM → slope GeoTIFF (degrees)

The outlet coordinates are stored in state as (lon, lat) WGS84.
Delineation reprojects the outlet to the project CRS before snapping.
"""

import os
import shutil
import subprocess

import numpy as np

from gui.workers.base_worker import BaseWorker


class WatershedWorker(BaseWorker):
    """Delineate catchment and/or compute slope."""

    def __init__(self, state, task: str = "delineate"):
        super().__init__()
        self._state = state
        self._task  = task

    def run(self):
        try:
            if self._task == "delineate":
                self._delineate()
            elif self._task == "slope":
                self._slope()
            else:
                self.error.emit(f"Unknown WatershedWorker task: {self._task!r}")
        except Exception as exc:
            self.error.emit(f"[WatershedWorker/{self._task}] {exc}")

    # ──────────────────────────────────────────────────────────────────────────

    def _delineate(self):
        """Delineate catchment using pysheds from the stored outlet point."""
        import rasterio
        from pysheds.grid import Grid
        from pyproj import Transformer

        state = self._state
        if not state.filled_dem_path or not os.path.exists(state.filled_dem_path):
            self.error.emit("Filled DEM not found. Complete Step 2 first.")
            return
        if not state.fdir_path or not os.path.exists(state.fdir_path):
            self.error.emit("Flow direction not found. Complete Step 2 first.")
            return
        if not state.accum_path or not os.path.exists(state.accum_path):
            self.error.emit("Flow accumulation not found. Complete Step 2 first.")
            return
        if not state.outlet_xy:
            self.error.emit("No outlet set. Click the outlet marker on the map in Step 3.")
            return

        out_dir  = os.path.join(state.project_dir, "rasters")
        os.makedirs(out_dir, exist_ok=True)
        mask_path = os.path.join(out_dir, "mask.tif")

        self.log_message.emit("Delineating catchment…")
        self.progress.emit(10)

        # ── Transform outlet WGS84 → project CRS ─────────────────────────
        lon, lat = state.outlet_xy
        with rasterio.open(state.filled_dem_path) as src:
            crs_proj = src.crs.to_epsg()

        self.log_message.emit(f"Transforming outlet ({lat:.5f}, {lon:.5f}) → EPSG:{crs_proj}")
        transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{crs_proj}", always_xy=True)
        x_proj, y_proj = transformer.transform(lon, lat)

        self.progress.emit(25)

        # ── pysheds catchment delineation ─────────────────────────────────
        grid = Grid.from_raster(state.filled_dem_path)
        dem  = grid.read_raster(state.filled_dem_path)
        fdir = grid.flowdir(dem)
        acc  = grid.accumulation(fdir)

        self.progress.emit(50)
        self.log_message.emit("Snapping outlet to highest-accumulation cell…")

        # Snap to highest-accumulation cell within 1 km
        x_snap, y_snap = grid.snap_to_mask(acc > 100, (x_proj, y_proj))

        self.progress.emit(65)
        self.log_message.emit("Computing catchment…")
        catch = grid.catchment(x_snap, y_snap, fdir, xytype="coordinate")

        self.progress.emit(80)
        catch_arr = np.array(catch, dtype=np.int16)
        n_cells   = int(catch_arr.sum())
        self.log_message.emit(f"Catchment delineated: {n_cells:,} cells")

        # ── Write mask GeoTIFF ────────────────────────────────────────────
        with rasterio.open(state.filled_dem_path) as src:
            profile = src.profile.copy()
        profile.update(dtype="int16", count=1, nodata=0)

        with rasterio.open(mask_path, "w", **profile) as dst:
            dst.write(catch_arr[np.newaxis, :, :])

        self.progress.emit(100)
        self.log_message.emit(f"Mask written: {mask_path}")
        self.finished.emit({"mask_path": mask_path, "n_cells": n_cells})

    def _slope(self):
        """Run gdaldem slope on the filled DEM to produce a slope raster (degrees)."""
        if shutil.which("gdaldem") is None:
            self.error.emit(
                "gdaldem not found on PATH.\n"
                "Install GDAL (e.g. brew install gdal on macOS) and try again."
            )
            return

        state = self._state
        if not state.filled_dem_path or not os.path.exists(state.filled_dem_path):
            self.error.emit("Filled DEM not found. Complete Step 2 first.")
            return

        out_dir    = os.path.join(state.project_dir, "rasters")
        os.makedirs(out_dir, exist_ok=True)
        slope_path = os.path.join(out_dir, "slope.tif")

        self.log_message.emit("Computing slope with gdaldem…")
        self.progress.emit(20)

        cmd = [
            "gdaldem", "slope",
            state.filled_dem_path,
            slope_path,
            "-of", "GTiff",
            "-b", "1",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            self.error.emit(f"gdaldem slope failed:\n{result.stderr}")
            return

        self.progress.emit(100)
        self.log_message.emit(f"Slope raster written: {slope_path}")
        self.finished.emit({"slope_path": slope_path})

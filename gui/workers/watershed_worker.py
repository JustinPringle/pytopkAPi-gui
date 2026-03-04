"""
gui/workers/watershed_worker.py
================================
WatershedWorker — watershed delineation and slope using GRASS GIS.

Tasks:
    'delineate' : GRASS r.water.outlet → catchment mask GeoTIFF
    'slope'     : GRASS r.slope.aspect → slope raster (degrees)

For delineation:
    1. Import filled DEM + drainage direction (from FillWorker / Step 2)
    2. Convert outlet (lon, lat WGS84) → project CRS with pyproj
    3. Run r.water.outlet to trace upstream area from the outlet cell
    4. Count cells and export mask as GeoTIFF

For slope:
    1. Import filled DEM
    2. Run r.slope.aspect with format=degrees
    3. Export slope GeoTIFF

Both tasks call:
    grass --tmp-location EPSG:<N> --exec python3 <script.py>
"""

import os
import shutil
import subprocess
import tempfile

from gui.workers.base_worker import BaseWorker


class WatershedWorker(BaseWorker):
    """GRASS-based watershed delineation and slope."""

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
    # Delineation
    # ──────────────────────────────────────────────────────────────────────────

    def _delineate(self) -> None:
        """
        Delineate catchment using GRASS r.water.outlet.

        Requires:
            state.filled_dem_path  — from Step 2
            state.drain_ws_path    — r.watershed drainage output from Step 2
            state.outlet_xy        — (lon, lat) WGS84 from the map widget
            state.crs              — project CRS (e.g. EPSG:32736)
        """
        import rasterio
        from pyproj import Transformer

        state = self._state

        # ── Validate inputs ────────────────────────────────────────────────
        missing = []
        if not state.filled_dem_path or not os.path.exists(state.filled_dem_path):
            missing.append("Filled DEM (run Step 2 — GRASS processing)")
        if not state.drain_ws_path or not os.path.exists(state.drain_ws_path):
            missing.append("Drainage direction (run Step 2 — GRASS processing)")
        if not state.outlet_xy:
            missing.append("Outlet point (click the outlet on the map in Step 3)")
        if missing:
            self.error.emit(
                "Cannot delineate — missing inputs:\n"
                + "\n".join(f"  • {m}" for m in missing)
            )
            return

        # ── Read EPSG from filled DEM ──────────────────────────────────────
        with rasterio.open(state.filled_dem_path) as src:
            epsg = src.crs.to_epsg()
        if not epsg:
            self.error.emit("Cannot read EPSG from filled DEM CRS.")
            return

        # ── Convert outlet WGS84 → project CRS ────────────────────────────
        lon, lat = state.outlet_xy
        self.log_message.emit(
            f"Converting outlet ({lat:.5f}°N, {lon:.5f}°E) → EPSG:{epsg}…"
        )
        transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
        easting, northing = transformer.transform(lon, lat)
        self.log_message.emit(f"  Outlet in EPSG:{epsg}: E={easting:.1f} N={northing:.1f}")

        out_dir   = os.path.join(state.project_dir, "rasters")
        os.makedirs(out_dir, exist_ok=True)
        mask_path = os.path.join(out_dir, "mask.tif")

        # ── Build GRASS script ─────────────────────────────────────────────
        lines = [
            "import grass.script as gs",
            "import sys",
            "",
            "# Import filled DEM and drainage direction",
            f"gs.run_command('r.in.gdal', input={repr(state.filled_dem_path)},",
            "               output='filled', overwrite=True)",
            f"gs.run_command('r.in.gdal', input={repr(state.drain_ws_path)},",
            "               output='drain', overwrite=True)",
            "gs.run_command('g.region', raster='filled')",
            "",
            "# Delineate watershed from outlet",
            "print('GRASS: r.water.outlet — delineating catchment…', flush=True)",
            f"gs.run_command('r.water.outlet', drainage='drain', output='basin',",
            f"               coordinates='{easting:.3f},{northing:.3f}', overwrite=True)",
            "",
            "# Count cells in basin",
            "stats = gs.read_command('r.stats', input='basin', flags='cn').strip()",
            "n_cells = 0",
            "for line in stats.splitlines():",
            "    parts = line.strip().split()",
            "    if len(parts) == 2 and parts[0] == '1':",
            "        n_cells = int(parts[1])",
            "        break",
            "print(f'N_CELLS={n_cells}', flush=True)",
            "",
            "# Export basin mask",
            "print('GRASS: exporting mask…', flush=True)",
            f"gs.run_command('r.out.gdal', input='basin', output={repr(mask_path)},",
            "               format='GTiff', type='Byte', nodata='255',",
            "               createopt='COMPRESS=LZW', overwrite=True)",
            "print('GRASS: done', flush=True)",
        ]

        grass_script = "\n".join(lines) + "\n"

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", prefix="grass_ws_", delete=False
        )
        tmp.write(grass_script)
        tmp.close()

        grass_bin = shutil.which("grass") or "/opt/local/bin/grass"
        self.log_message.emit(f"Launching GRASS GIS (EPSG:{epsg})…")
        self.progress.emit(5)

        n_cells   = 0
        all_lines = []
        try:
            proc = subprocess.Popen(
                [grass_bin, "--tmp-location", f"EPSG:{epsg}",
                 "--exec", "python3", tmp.name],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            for raw in proc.stdout:
                line = raw.rstrip()
                if not line:
                    continue
                all_lines.append(line)
                self.log_message.emit(line)

                # Parse n_cells from script output
                if line.startswith("N_CELLS="):
                    try:
                        n_cells = int(line.split("=", 1)[1])
                    except ValueError:
                        pass
                elif "r.water.outlet" in line.lower():
                    self.progress.emit(40)
                elif "exporting" in line.lower():
                    self.progress.emit(80)
                elif "done" in line.lower():
                    self.progress.emit(95)

            proc.wait()

        finally:
            os.unlink(tmp.name)

        if proc.returncode != 0:
            self.error.emit(
                f"GRASS delineation failed (exit {proc.returncode}).\n"
                "See the log panel for details."
            )
            return

        if not os.path.exists(mask_path):
            self.error.emit(
                "GRASS ran OK but mask.tif was not created.\n"
                "Check that the outlet point is inside the DEM extent."
            )
            return

        self.progress.emit(100)
        self.log_message.emit(
            f"✅ Watershed delineated — {n_cells:,} cells → {os.path.basename(mask_path)}"
        )
        self.finished.emit({"mask_path": mask_path, "n_cells": n_cells})

    # ──────────────────────────────────────────────────────────────────────────
    # Slope
    # ──────────────────────────────────────────────────────────────────────────

    def _slope(self) -> None:
        """
        Compute slope raster (degrees) using GRASS r.slope.aspect.

        Requires: state.filled_dem_path
        """
        import rasterio

        state = self._state

        if not state.filled_dem_path or not os.path.exists(state.filled_dem_path):
            self.error.emit("Filled DEM not found. Complete Step 2 first.")
            return

        with rasterio.open(state.filled_dem_path) as src:
            epsg = src.crs.to_epsg()
        if not epsg:
            self.error.emit("Cannot read EPSG from filled DEM CRS.")
            return

        out_dir    = os.path.join(state.project_dir, "rasters")
        os.makedirs(out_dir, exist_ok=True)
        slope_path = os.path.join(out_dir, "slope.tif")

        lines = [
            "import grass.script as gs",
            "",
            f"gs.run_command('r.in.gdal', input={repr(state.filled_dem_path)},",
            "               output='filled', overwrite=True)",
            "gs.run_command('g.region', raster='filled')",
            "",
            "print('GRASS: r.slope.aspect — computing slope…', flush=True)",
            "gs.run_command('r.slope.aspect', elevation='filled', slope='slope',",
            "               format='degrees', overwrite=True)",
            "",
            f"gs.run_command('r.out.gdal', input='slope', output={repr(slope_path)},",
            "               format='GTiff', createopt='COMPRESS=LZW', overwrite=True)",
            "print('GRASS: done', flush=True)",
        ]

        grass_script = "\n".join(lines) + "\n"

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", prefix="grass_slope_", delete=False
        )
        tmp.write(grass_script)
        tmp.close()

        grass_bin = shutil.which("grass") or "/opt/local/bin/grass"
        self.log_message.emit(f"Launching GRASS GIS for slope (EPSG:{epsg})…")
        self.progress.emit(5)

        try:
            proc = subprocess.Popen(
                [grass_bin, "--tmp-location", f"EPSG:{epsg}",
                 "--exec", "python3", tmp.name],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            for raw in proc.stdout:
                line = raw.rstrip()
                if not line:
                    continue
                self.log_message.emit(line)
                if "r.slope.aspect" in line.lower():
                    self.progress.emit(40)
                elif "done" in line.lower():
                    self.progress.emit(95)

            proc.wait()

        finally:
            os.unlink(tmp.name)

        if proc.returncode != 0:
            self.error.emit(
                f"GRASS slope failed (exit {proc.returncode}).\n"
                "See the log panel for details."
            )
            return

        if not os.path.exists(slope_path):
            self.error.emit("GRASS ran OK but slope.tif was not created.")
            return

        self.progress.emit(100)
        self.log_message.emit(f"✅ Slope computed → {os.path.basename(slope_path)}")
        self.finished.emit({"slope_path": slope_path})

"""
gui/workers/subcatchment_worker.py
===================================
SubcatchmentWorker — delineate a single sub-basin using GRASS r.water.outlet,
then vectorise the result to a WGS84 GeoJSON polygon.

Inputs (from state):
    filled_dem_path  — depression-free DEM (Step 2 GRASS output)
    drain_ws_path    — r.watershed drainage direction (Step 2 GRASS output)
    outlet_lonlat    — (lon, lat) WGS84 provided by the user

Outputs appended to state lists:
    subcatchment_outlets   — [(lon, lat), …]
    subcatchment_geojsons  — WGS84 GeoJSON Feature strings
    subcatchment_n_cells   — int cell count per sub-basin

The mask raster for sub-basin N is saved as:
    <project_dir>/rasters/subcatchment_N.tif
"""

import json
import os
import shutil
import subprocess
import tempfile

from gui.workers.base_worker import BaseWorker


class SubcatchmentWorker(BaseWorker):
    """GRASS-based subcatchment delineation for one outlet point."""

    def __init__(self, state, outlet_lonlat: tuple):
        """
        Args:
            state:          ProjectState (read-only)
            outlet_lonlat:  (lon, lat) in WGS84
        """
        super().__init__()
        self._state        = state
        self._outlet_lonlat = outlet_lonlat   # (lon, lat)

    def run(self) -> None:
        try:
            self._delineate()
        except Exception as exc:
            self.error.emit(f"[SubcatchmentWorker] {exc}")

    # ──────────────────────────────────────────────────────────────────────────

    def _delineate(self) -> None:
        import rasterio
        from pyproj import Transformer

        state = self._state

        # ── Validate inputs ────────────────────────────────────────────────
        missing = []
        if not state.filled_dem_path or not os.path.exists(state.filled_dem_path):
            missing.append("Filled DEM (complete GRASS processing in Step 2 first)")
        if not state.drain_ws_path or not os.path.exists(state.drain_ws_path):
            missing.append("Drainage direction (complete GRASS processing in Step 2 first)")
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
        lon, lat = self._outlet_lonlat
        transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
        easting, northing = transformer.transform(lon, lat)
        self.log_message.emit(
            f"Subcatchment outlet: ({lat:.5f}°N, {lon:.5f}°E) "
            f"→ E={easting:.1f} N={northing:.1f} (EPSG:{epsg})"
        )

        # ── Output paths ───────────────────────────────────────────────────
        out_dir    = os.path.join(state.project_dir, "rasters")
        os.makedirs(out_dir, exist_ok=True)
        sub_idx    = len(state.subcatchment_outlets or []) + 1  # 1-based
        mask_path  = os.path.join(out_dir, f"subcatchment_{sub_idx}.tif")

        # ── Build GRASS script ─────────────────────────────────────────────
        lines = [
            "import grass.script as gs",
            "import sys",
            "",
            f"gs.run_command('r.in.gdal', input={repr(state.filled_dem_path)},",
            "               output='filled', overwrite=True)",
            f"gs.run_command('r.in.gdal', input={repr(state.drain_ws_path)},",
            "               output='drain', overwrite=True)",
            "gs.run_command('g.region', raster='filled')",
            "",
            "print('GRASS: r.water.outlet — delineating sub-basin…', flush=True)",
            f"gs.run_command('r.water.outlet', drainage='drain', output='basin',",
            f"               coordinates='{easting:.3f},{northing:.3f}', overwrite=True)",
            "",
            "# Count cells",
            "stats = gs.read_command('r.stats', input='basin', flags='cn').strip()",
            "n_cells = 0",
            "for line in stats.splitlines():",
            "    parts = line.strip().split()",
            "    if len(parts) == 2 and parts[0] == '1':",
            "        n_cells = int(parts[1])",
            "        break",
            "print(f'N_CELLS={n_cells}', flush=True)",
            "",
            "print('GRASS: exporting sub-basin mask…', flush=True)",
            f"gs.run_command('r.out.gdal', input='basin', output={repr(mask_path)},",
            "               format='GTiff', type='Byte', nodata='255',",
            "               createopt='COMPRESS=LZW', overwrite=True)",
            "print('GRASS: done', flush=True)",
        ]
        grass_script = "\n".join(lines) + "\n"

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", prefix="grass_sub_", delete=False
        )
        tmp.write(grass_script)
        tmp.close()

        grass_bin = (
            shutil.which("grass")
            or "/opt/local/bin/grass"
            or "/opt/homebrew/bin/grass"
        )

        self.log_message.emit(f"Launching GRASS GIS (EPSG:{epsg}) for sub-basin {sub_idx}…")
        self.progress.emit(5)

        n_cells = 0
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
                if line.startswith("N_CELLS="):
                    try:
                        n_cells = int(line.split("=", 1)[1])
                    except ValueError:
                        pass
                elif "r.water.outlet" in line.lower():
                    self.progress.emit(40)
                elif "exporting" in line.lower():
                    self.progress.emit(75)
            proc.wait()
        finally:
            os.unlink(tmp.name)

        if proc.returncode != 0:
            self.error.emit(
                f"GRASS sub-basin delineation failed (exit {proc.returncode}).\n"
                "Check the log above for details. Ensure the outlet is inside the DEM extent."
            )
            return

        if not os.path.exists(mask_path):
            self.error.emit(
                "GRASS ran OK but the sub-basin mask was not created.\n"
                "Ensure the outlet point falls inside the filled DEM extent."
            )
            return

        self.progress.emit(80)
        self.log_message.emit(
            f"Sub-basin {sub_idx}: {n_cells:,} cells → {os.path.basename(mask_path)}"
        )

        # ── Vectorise mask → WGS84 GeoJSON ────────────────────────────────
        self.log_message.emit("  Converting mask raster → WGS84 polygon…")
        geojson_str = self._mask_to_geojson(mask_path)

        # ── Append to state lists ──────────────────────────────────────────
        outlets   = list(state.subcatchment_outlets  or []) + [self._outlet_lonlat]
        geojsons  = list(state.subcatchment_geojsons or []) + [geojson_str]
        n_list    = list(state.subcatchment_n_cells  or []) + [n_cells]

        self.progress.emit(100)
        self.log_message.emit(f"✅ Sub-basin {sub_idx} delineated — {n_cells:,} cells")
        self.finished.emit({
            "subcatchment_outlets":  outlets,
            "subcatchment_geojsons": geojsons,
            "subcatchment_n_cells":  n_list,
        })

    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _mask_to_geojson(mask_path: str) -> str:
        """Vectorise a binary mask raster (1=cell) to a WGS84 GeoJSON Feature."""
        import numpy as np
        import rasterio
        from rasterio.features import shapes as rio_shapes
        from shapely.geometry import shape
        from shapely.ops import unary_union, transform as shapely_transform
        from pyproj import Transformer

        with rasterio.open(mask_path) as src:
            data      = src.read(1)
            transform = src.transform
            crs       = src.crs

        # Collect all polygons where pixel == 1
        geoms = [
            shape(geom)
            for geom, val in rio_shapes(data.astype(np.int16), transform=transform)
            if val == 1
        ]
        if not geoms:
            return json.dumps({"type": "Feature", "geometry": None, "properties": {}})

        poly = unary_union(geoms)

        # Reproject from DEM CRS → WGS84
        trans    = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
        poly_wgs = shapely_transform(trans.transform, poly)

        return json.dumps({
            "type":       "Feature",
            "geometry":   poly_wgs.__geo_interface__,
            "properties": {},
        })

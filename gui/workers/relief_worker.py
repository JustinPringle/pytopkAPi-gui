"""
gui/workers/relief_worker.py
============================
ReliefWorker — lightweight GRASS worker that re-renders only the terrain
visualisation layers (r.relief + r.shade) without re-running the full
hydrological pipeline (r.fill.dir, r.watershed, r.to.vect).

Reads the filled DEM already in the project and re-generates:
    relief.tif         — greyscale hillshade (r.relief)
    shaded_relief.tif  — hypsometric composite (r.shade over r.colors elevation)

Uses the terrain rendering parameters stored in ProjectState:
    relief_zscale, relief_azimuth, relief_altitude,
    relief_brighten, elevation_colors

Emits finished({"relief_path": ..., "shaded_relief_path": ...}).
"""

import os
import shutil
import subprocess
import tempfile

from gui.workers.base_worker import BaseWorker

# Known non-fatal GDAL/GRASS messages to suppress from the log
_SUPPRESS_PATTERNS = [
    "SetColorTable() only supported for",
    "color table of type",
]


class ReliefWorker(BaseWorker):
    """Re-run r.relief + r.shade only, using current state rendering params."""

    def run(self) -> None:
        try:
            self._run_relief()
        except Exception as exc:
            self.error.emit(f"[ReliefWorker] {exc}")

    def _run_relief(self) -> None:
        import rasterio

        state = self._state

        # Need the filled DEM as input
        in_path = (
            state.clipped_dem_path if (state.clipped_dem_path and
                                        os.path.exists(state.clipped_dem_path))
            else state.filled_dem_path
        )
        if not in_path or not os.path.exists(in_path):
            self.error.emit(
                "No filled DEM found.\n"
                "Run Terrain Analysis (GRASS) in Step 2 first."
            )
            return

        with rasterio.open(in_path) as src:
            epsg = src.crs.to_epsg()
        if not epsg:
            self.error.emit("Cannot determine EPSG code from DEM CRS.")
            return

        out_dir    = os.path.join(state.project_dir, "rasters")
        os.makedirs(out_dir, exist_ok=True)
        relief_path = os.path.join(out_dir, "relief.tif")
        shaded_path = os.path.join(out_dir, "shaded_relief.tif")
        # Temp paths for R/G/B band exports (merged into 3-band after GRASS)
        shaded_r_path = os.path.join(out_dir, "shaded_r.tif")
        shaded_g_path = os.path.join(out_dir, "shaded_g.tif")
        shaded_b_path = os.path.join(out_dir, "shaded_b.tif")

        zscale   = getattr(state, "relief_zscale",   3.0)
        azimuth  = getattr(state, "relief_azimuth",  315.0)
        altitude = getattr(state, "relief_altitude", 45.0)
        brighten = getattr(state, "relief_brighten", 30)
        colors   = getattr(state, "elevation_colors", "elevation")

        lines = [
            "import grass.script as gs",
            "",
            f"gs.run_command('r.in.gdal', input={repr(in_path)}, output='dem', overwrite=True)",
            "gs.run_command('g.region', raster='dem')",
            "",
            "print('ReliefWorker: r.colors — applying colour table…', flush=True)",
            f"gs.run_command('r.colors', map='dem', color={repr(colors)}, flags='e')",
            "",
            "print('ReliefWorker: r.relief — computing hillshade…', flush=True)",
            f"gs.run_command('r.relief', input='dem', output='relief',",
            f"               azimuth={azimuth}, altitude={altitude},",
            f"               zscale={zscale}, overwrite=True)",
            "",
            "print('ReliefWorker: r.shade — compositing…', flush=True)",
            f"gs.run_command('r.shade', shade='relief', color='dem',",
            f"               output='shaded_relief', brighten={brighten}, overwrite=True)",
            "",
            "print('ReliefWorker: exporting…', flush=True)",
            f"gs.run_command('r.out.gdal', input='relief',",
            f"               output={repr(relief_path)},",
            "               format='GTiff', createopt='COMPRESS=LZW', overwrite=True)",
            "# Extract RGB components from GRASS colour table",
            "gs.mapcalc('shaded_r = r#shaded_relief', overwrite=True)",
            "gs.mapcalc('shaded_g = g#shaded_relief', overwrite=True)",
            "gs.mapcalc('shaded_b = b#shaded_relief', overwrite=True)",
            f"gs.run_command('r.out.gdal', input='shaded_r', output={repr(shaded_r_path)},",
            "               format='GTiff', type='Byte', createopt='COMPRESS=LZW', overwrite=True)",
            f"gs.run_command('r.out.gdal', input='shaded_g', output={repr(shaded_g_path)},",
            "               format='GTiff', type='Byte', createopt='COMPRESS=LZW', overwrite=True)",
            f"gs.run_command('r.out.gdal', input='shaded_b', output={repr(shaded_b_path)},",
            "               format='GTiff', type='Byte', createopt='COMPRESS=LZW', overwrite=True)",
            "",
            "print('ReliefWorker: done', flush=True)",
        ]

        grass_script = "\n".join(lines) + "\n"
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", prefix="grass_relief_", delete=False
        )
        tmp.write(grass_script)
        tmp.close()

        grass_bin = shutil.which("grass") or "/opt/local/bin/grass"
        if not shutil.which("grass") and not os.path.exists(grass_bin):
            os.unlink(tmp.name)
            self.error.emit("GRASS GIS not found. Install with: brew install grass")
            return

        self.log_message.emit(f"Re-rendering terrain (azimuth={azimuth}°, altitude={altitude}°, "
                              f"zscale={zscale}, brighten={brighten}, colors={colors})…")
        self.progress.emit(5)

        try:
            proc = subprocess.Popen(
                [grass_bin, "--tmp-location", f"EPSG:{epsg}",
                 "--exec", "python3", tmp.name],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            for raw_line in proc.stdout:
                line = raw_line.rstrip('\n')
                if not line:
                    continue
                # GRASS progress: lines with \r contain terminal progress updates
                # Split on \r and only log the last segment (most recent %)
                if '\r' in line:
                    parts = line.split('\r')
                    line = parts[-1].strip()
                    if not line:
                        continue
                    # Skip noisy percentage-only lines (e.g. " 45%")
                    stripped = line.rstrip('%').strip()
                    if stripped.replace('.', '', 1).isdigit():
                        continue
                # Suppress known non-fatal GDAL/GRASS messages
                if any(pat in line for pat in _SUPPRESS_PATTERNS):
                    continue
                self.log_message.emit(line)
                low = line.lower()
                if "r.colors" in low:
                    self.progress.emit(20)
                elif "r.relief" in low:
                    self.progress.emit(45)
                elif "r.shade" in low:
                    self.progress.emit(70)
                elif "exporting" in low:
                    self.progress.emit(85)
                elif "done" in low:
                    self.progress.emit(95)
            proc.wait()
        finally:
            os.unlink(tmp.name)

        if proc.returncode != 0:
            self.error.emit(
                f"GRASS r.relief failed (exit code {proc.returncode}).\n"
                "See the log panel for details."
            )
            return

        # Merge R/G/B band exports into a single 3-band RGB GeoTIFF
        rgb_parts = [shaded_r_path, shaded_g_path, shaded_b_path]
        if all(os.path.exists(p) for p in rgb_parts):
            with rasterio.open(shaded_r_path) as r_src:
                r_band = r_src.read(1)
                profile = r_src.profile.copy()
            with rasterio.open(shaded_g_path) as g_src:
                g_band = g_src.read(1)
            with rasterio.open(shaded_b_path) as b_src:
                b_band = b_src.read(1)
            profile.update(count=3, dtype='uint8', nodata=None)
            with rasterio.open(shaded_path, 'w', **profile) as dst:
                dst.write(r_band, 1)
                dst.write(g_band, 2)
                dst.write(b_band, 3)
            for p in rgb_parts:
                os.unlink(p)
            self.log_message.emit("Merged R/G/B → 3-band shaded_relief.tif")

        outputs = {}
        if os.path.exists(relief_path):
            outputs["relief_path"] = relief_path
        if os.path.exists(shaded_path):
            outputs["shaded_relief_path"] = shaded_path

        if not outputs:
            self.error.emit("GRASS exited OK but no output files were produced.")
            return

        self.progress.emit(100)
        self.log_message.emit("Terrain re-rendered successfully.")
        self.finished.emit(outputs)

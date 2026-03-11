"""
gui/workers/fill_worker.py
==========================
FillWorker — DEM hydrological processing using GRASS GIS.

Calls:
    grass --tmp-location EPSG:<N> --exec python3 <script.py>

The temporary script runs inside a GRASS session and calls:
    r.in.gdal    → import the projected DEM
    g.region     → set computational region to match the DEM
    r.fill.dir   → fill depressions and compute flow direction (GRASS 1-8 coding)
    r.watershed  → flow accumulation + drainage direction + basins
    r.relief     → shaded relief raster
    r.shade      → composite elevation draped over relief
    r.to.vect    → convert basins raster to vector polygons
    r.out.gdal   → export all results as GeoTIFF
    v.out.ogr    → export basins vector as GeoPackage

Follows the GRASS watershed tutorial:
    https://baharmon.github.io/watersheds-in-grass
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


class FillWorker(BaseWorker):
    """GRASS GIS fill + flow routing worker."""

    def run(self) -> None:
        # Accept any task name — all run the single GRASS pipeline
        try:
            self._grass_all()
        except Exception as exc:
            self.error.emit(f"[FillWorker] {exc}")

    # ──────────────────────────────────────────────────────────────────────────

    def _grass_all(self) -> None:
        """
        Single GRASS session following the watershed tutorial:
          r.fill.dir  → filled DEM + flow direction (GRASS 1-8)
          r.watershed → accumulation + drainage direction + basins
          r.relief    → shaded relief
          r.shade     → composite (elevation draped over relief)
          r.to.vect   → basins as vector polygons
        """
        import rasterio

        state   = self._state
        # Prefer clipped DEM (basin selection) → gives fine-detail analysis
        in_path = (
            state.clipped_dem_path if (state.clipped_dem_path and os.path.exists(state.clipped_dem_path))
            else state.proj_dem_path
        )

        if not in_path or not os.path.exists(in_path):
            self.error.emit(
                "No DEM found to process.\n"
                "Either reproject the downloaded DEM, or clip to a basin first."
            )
            return

        # ── Read EPSG code from DEM ────────────────────────────────────────
        with rasterio.open(in_path) as src:
            epsg = src.crs.to_epsg()

        if not epsg:
            self.error.emit(
                "Cannot determine EPSG code from the DEM's CRS.\n"
                "Ensure the DEM is in a recognised projected CRS "
                "(e.g. UTM 36S / EPSG:32736)."
            )
            return

        out_dir = os.path.join(state.project_dir, "rasters")
        os.makedirs(out_dir, exist_ok=True)

        filled_path     = os.path.join(out_dir, "filled_dem.tif")
        fdir_path       = os.path.join(out_dir, "flow_dir.tif")
        accum_path      = os.path.join(out_dir, "flow_accum.tif")
        drain_ws_path   = os.path.join(out_dir, "drain_ws.tif")
        basins_path     = os.path.join(out_dir, "basins.tif")
        relief_path     = os.path.join(out_dir, "relief.tif")
        shaded_path     = os.path.join(out_dir, "shaded_relief.tif")
        basins_gpkg     = os.path.join(out_dir, "basins.gpkg")
        # Temp paths for R/G/B band exports (merged into 3-band after GRASS)
        shaded_r_path   = os.path.join(out_dir, "shaded_r.tif")
        shaded_g_path   = os.path.join(out_dir, "shaded_g.tif")
        shaded_b_path   = os.path.join(out_dir, "shaded_b.tif")

        # Threshold for r.watershed basin delineation (from state or default)
        threshold = getattr(state, "stream_threshold", 500)
        zscale    = getattr(state, "relief_zscale", 3.0)

        # ── Build the GRASS Python script ─────────────────────────────────
        lines = [
            "import grass.script as gs",
            "",
            "# ── Import projected DEM ────────────────────────────────────",
            f"gs.run_command('r.in.gdal', input={repr(in_path)}, output='dem', overwrite=True)",
            "gs.run_command('g.region', raster='dem')",
            "",
            "# ── Fill depressions + compute flow direction (GRASS 1-8) ──",
            "print('GRASS: r.fill.dir — filling depressions…', flush=True)",
            "gs.run_command('r.fill.dir', input='dem', output='filled',",
            "               direction='fdir', overwrite=True)",
            "",
            "# ── r.watershed — accumulation + drainage + basins ──────────",
            "# -a: positive accumulation values; -b: beautify flat areas.",
            "# basin output drives the clickable polygons in Step 2 section 4.",
            "print('GRASS: r.watershed — flow accumulation + basins…', flush=True)",
            f"gs.run_command('r.watershed', flags='ab', elevation='filled',",
            f"               threshold={threshold},",
            "               accumulation='accum', drainage='drain',",
            "               basin='basins', overwrite=True)",
            "",
            "# ── r.relief — shaded relief ────────────────────────────────",
            "print('GRASS: r.relief — computing shaded relief…', flush=True)",
            f"gs.run_command('r.relief', input='filled', output='relief',",
            f"               zscale={zscale}, overwrite=True)",
            "",
            "# ── r.colors — apply hypsometric tint to filled DEM ────────",
            "print('GRASS: r.colors — applying elevation colour table…', flush=True)",
            "gs.run_command('r.colors', map='filled', color='elevation', flags='e')",
            "",
            "# ── r.shade — composite elevation over relief ───────────────",
            "print('GRASS: r.shade — compositing shaded relief…', flush=True)",
            "gs.run_command('r.shade', shade='relief', color='filled',",
            "               output='shaded_relief', brighten=30, overwrite=True)",
            "",
            "# ── r.to.vect — convert basins to vector ───────────────────",
            "# No -s (smooth) flag: adjacent basins share exact raster-edge",
            "# boundaries, avoiding tiny inter-polygon gaps when merging.",
            "print('GRASS: r.to.vect — vectorising basins…', flush=True)",
            "gs.run_command('r.to.vect', input='basins',",
            "               output='basins_vect', type='area', overwrite=True)",
            "",
            "# ── Export results as GeoTIFF ────────────────────────────────",
            "print('GRASS: exporting rasters…', flush=True)",
            f"gs.run_command('r.out.gdal', input='filled', output={repr(filled_path)},",
            "               format='GTiff', createopt='COMPRESS=LZW', overwrite=True)",
            "",
            "# fdir: Int16, nodata=-32768 to match GRASS convention",
            f"gs.run_command('r.out.gdal', input='fdir', output={repr(fdir_path)},",
            "               format='GTiff', type='Int16', nodata='-32768',",
            "               createopt='COMPRESS=LZW', overwrite=True)",
            "",
            "# accum: Float64 (positive accumulation via -a flag)",
            f"gs.run_command('r.out.gdal', input='accum', output={repr(accum_path)},",
            "               format='GTiff', createopt='COMPRESS=LZW', overwrite=True)",
            "",
            "# drain: Int16 signed, used by r.water.outlet",
            f"gs.run_command('r.out.gdal', input='drain', output={repr(drain_ws_path)},",
            "               format='GTiff', type='Int16', nodata='-32768',",
            "               createopt='COMPRESS=LZW', overwrite=True)",
            "",
            "# basins: auto-delineated watershed boundaries from r.watershed",
            f"gs.run_command('r.out.gdal', input='basins', output={repr(basins_path)},",
            "               format='GTiff', type='Int32',",
            "               createopt='COMPRESS=LZW', overwrite=True)",
            "",
            "# relief: shaded relief greyscale",
            f"gs.run_command('r.out.gdal', input='relief', output={repr(relief_path)},",
            "               format='GTiff', createopt='COMPRESS=LZW', overwrite=True)",
            "",
            "# shaded_relief: extract RGB from GRASS colour table for 3-band export",
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
            "# basins vector as GeoPackage",
            "print('GRASS: exporting basin vectors…', flush=True)",
            f"gs.run_command('v.out.ogr', input='basins_vect', output={repr(basins_gpkg)},",
            "               format='GPKG', overwrite=True)",
            "",
            "print('GRASS: done', flush=True)",
        ]

        grass_script = "\n".join(lines) + "\n"

        # Write script to a temp file
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", prefix="grass_fill_", delete=False
        )
        tmp.write(grass_script)
        tmp.close()

        # ── Find the GRASS binary ─────────────────────────────────────────
        grass_bin = (
            shutil.which("grass")
            or "/opt/local/bin/grass"   # MacPorts default on macOS
        )
        if not os.path.exists(grass_bin) and not shutil.which("grass"):
            os.unlink(tmp.name)
            self.error.emit(
                f"GRASS GIS not found at '{grass_bin}'.\n"
                "Install GRASS GIS (brew install grass or macports) and ensure "
                "it is on the PATH."
            )
            return

        self.log_message.emit(f"Launching GRASS GIS {grass_bin} (EPSG:{epsg})…")
        self.log_message.emit(f"  Input DEM: {os.path.basename(in_path)}")
        self.log_message.emit(f"  Threshold: {threshold} cells")
        self.log_message.emit("  Tools: r.fill.dir + r.watershed + r.relief + r.shade + r.to.vect")
        self.progress.emit(5)

        # ── Run GRASS session ─────────────────────────────────────────────
        try:
            proc = subprocess.Popen(
                [grass_bin, "--tmp-location", f"EPSG:{epsg}",
                 "--exec", "python3", tmp.name],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,   # merge stderr into stdout for streaming
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
                # Update progress based on key milestone messages
                low = line.lower()
                if "r.fill.dir" in low:
                    self.progress.emit(15)
                elif "r.watershed" in low:
                    self.progress.emit(35)
                elif "r.relief" in low:
                    self.progress.emit(55)
                elif "r.shade" in low:
                    self.progress.emit(65)
                elif "r.to.vect" in low:
                    self.progress.emit(70)
                elif "exporting" in low:
                    self.progress.emit(80)
                elif "done" in low:
                    self.progress.emit(95)

            proc.wait()

        finally:
            os.unlink(tmp.name)

        # ── Check return code ─────────────────────────────────────────────
        if proc.returncode != 0:
            self.error.emit(
                f"GRASS processing failed (exit code {proc.returncode}).\n"
                "See the log panel above for details."
            )
            return

        # ── Merge R/G/B band exports into 3-band RGB shaded_relief ──────
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

        # ── Verify core outputs exist ─────────────────────────────────────
        outputs = {
            "filled_dem_path":    filled_path,
            "fdir_path":          fdir_path,
            "accum_path":         accum_path,
            "drain_ws_path":      drain_ws_path,
            "basins_path":        basins_path,
        }
        missing = [k for k, p in outputs.items() if not os.path.exists(p)]
        if missing:
            self.error.emit(
                f"GRASS exited OK but these output files are missing:\n"
                + "\n".join(f"  {k}" for k in missing)
            )
            return

        # Optional outputs (non-fatal if missing)
        if os.path.exists(relief_path):
            outputs["relief_path"] = relief_path
        if os.path.exists(shaded_path):
            outputs["shaded_relief_path"] = shaded_path
        if os.path.exists(basins_gpkg):
            outputs["basins_gpkg_path"] = basins_gpkg

        self.progress.emit(100)
        self.log_message.emit("GRASS processing complete.")
        self.log_message.emit(f"  Filled DEM      -> {os.path.basename(filled_path)}")
        self.log_message.emit(f"  Flow dir        -> {os.path.basename(fdir_path)} (GRASS 1-8)")
        self.log_message.emit(f"  Accumulation    -> {os.path.basename(accum_path)}")
        self.log_message.emit(f"  Drainage        -> {os.path.basename(drain_ws_path)}")
        self.log_message.emit(f"  Basins          -> {os.path.basename(basins_path)} (threshold={threshold})")
        if os.path.exists(relief_path):
            self.log_message.emit(f"  Relief          -> {os.path.basename(relief_path)} (r.relief zscale={zscale})")
        if os.path.exists(shaded_path):
            self.log_message.emit(f"  Shaded relief   -> {os.path.basename(shaded_path)} (r.shade brighten=30)")
        if os.path.exists(basins_gpkg):
            self.log_message.emit(f"  Basins (vector) -> {os.path.basename(basins_gpkg)}")
        self.finished.emit(outputs)

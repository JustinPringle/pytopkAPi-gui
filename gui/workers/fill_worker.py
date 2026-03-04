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
    r.watershed  → flow accumulation + drainage direction (for r.water.outlet)
    r.out.gdal   → export all results as GeoTIFF

Emits finished({
    "filled_dem_path": ...,   # depression-free DEM (GeoTIFF)
    "fdir_path":       ...,   # flow direction, GRASS 1-8 coding (GeoTIFF Int16)
    "accum_path":      ...,   # flow accumulation in cells (GeoTIFF Float64)
    "drain_ws_path":   ...,   # r.watershed drainage direction (for r.water.outlet)
})

Why GRASS over pysheds?
    pysheds outputs ESRI D8 coding (1/2/4/8/16/32/64/128) that must be recoded
    to GRASS convention, which is error-prone. GRASS r.fill.dir natively writes
    GRASS 1-8 — exactly what PyTOPKAPI create_file.py expects.
"""

import os
import shutil
import subprocess
import tempfile

from gui.workers.base_worker import BaseWorker


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
        Single GRASS session:
          r.fill.dir  → filled DEM + flow direction (GRASS 1-8)
          r.watershed → accumulation + drainage direction
        """
        import rasterio

        state   = self._state
        in_path = state.proj_dem_path

        if not in_path or not os.path.exists(in_path):
            self.error.emit(
                "Projected DEM not found.\n"
                "Use 'Reproject DEM' above, or load an existing DEM with the "
                "'Load Existing Rasters' browse button."
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

        filled_path   = os.path.join(out_dir, "filled_dem.tif")
        fdir_path     = os.path.join(out_dir, "flow_dir.tif")
        accum_path    = os.path.join(out_dir, "flow_accum.tif")
        drain_ws_path = os.path.join(out_dir, "drain_ws.tif")

        # ── Build the GRASS Python script ─────────────────────────────────
        #   This script runs inside the GRASS --tmp-location context and only
        #   imports grass.script (which GRASS adds to PYTHONPATH automatically).
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
            "# ── Flow accumulation + drainage direction (for r.water.outlet) ─",
            "print('GRASS: r.watershed — flow accumulation…', flush=True)",
            "gs.run_command('r.watershed', flags='s', elevation='filled',",
            "               accumulation='accum', drainage='drain', overwrite=True)",
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
            "# accum: Float64 (default GRASS type for accumulation)",
            f"gs.run_command('r.out.gdal', input='accum', output={repr(accum_path)},",
            "               format='GTiff', createopt='COMPRESS=LZW', overwrite=True)",
            "",
            "# drain: Int16 signed (negative values = streams), used by r.water.outlet",
            f"gs.run_command('r.out.gdal', input='drain', output={repr(drain_ws_path)},",
            "               format='GTiff', type='Int16', nodata='-32768',",
            "               createopt='COMPRESS=LZW', overwrite=True)",
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
        self.log_message.emit("  Tools: r.fill.dir + r.watershed")
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
                line = raw_line.rstrip()
                if not line:
                    continue
                self.log_message.emit(line)
                # Update progress based on key milestone messages
                low = line.lower()
                if "r.fill.dir" in low:
                    self.progress.emit(20)
                elif "r.watershed" in low:
                    self.progress.emit(55)
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

        # ── Verify all outputs exist ──────────────────────────────────────
        outputs = {
            "filled_dem_path": filled_path,
            "fdir_path":       fdir_path,
            "accum_path":      accum_path,
            "drain_ws_path":   drain_ws_path,
        }
        missing = [k for k, p in outputs.items() if not os.path.exists(p)]
        if missing:
            self.error.emit(
                f"GRASS exited OK but these output files are missing:\n"
                + "\n".join(f"  {k}" for k in missing)
            )
            return

        self.progress.emit(100)
        self.log_message.emit("✅ GRASS fill + flow routing complete.")
        self.log_message.emit(f"  Filled DEM   → {os.path.basename(filled_path)}")
        self.log_message.emit(f"  Flow dir     → {os.path.basename(fdir_path)} (GRASS 1-8)")
        self.log_message.emit(f"  Accumulation → {os.path.basename(accum_path)}")
        self.log_message.emit(f"  Drainage     → {os.path.basename(drain_ws_path)} (for watershed)")
        self.finished.emit(outputs)

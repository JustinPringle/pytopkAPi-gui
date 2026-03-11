"""
gui/workers/stream_worker.py
=============================
StreamWorker — GRASS GIS stream network extraction and Strahler ordering.

Calls:
    grass --tmp-location EPSG:<N> --exec python3 <script.py>

The temporary script runs inside a GRASS session and calls:
    r.in.gdal         → import filled DEM, accumulation, flow direction
    g.region          → set computational region
    r.stream.extract  → extract stream network raster
    r.stream.order    → compute Strahler stream orders + vector output
    r.out.gdal        → export stream network and Strahler order as GeoTIFF
    v.out.ogr         → export stream vector as GeoPackage

Emits finished({
    "streamnet_path":  ...,   # binary stream raster (GeoTIFF Int16)
    "strahler_path":   ...,   # Strahler order raster (GeoTIFF Int16)
})
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


class StreamWorker(BaseWorker):
    """GRASS GIS stream extraction + Strahler ordering worker."""

    def run(self) -> None:
        try:
            self._grass_streams()
        except Exception as exc:
            self.error.emit(f"[StreamWorker] {exc}")

    # ──────────────────────────────────────────────────────────────────────────

    def _grass_streams(self) -> None:
        """
        Single GRASS session:
          r.stream.extract → stream network raster
          r.stream.order   → Strahler ordering + vector streams
        """
        import rasterio

        state = self._state

        # Require filled DEM and accumulation from Step 2
        if not state.filled_dem_path or not os.path.exists(state.filled_dem_path):
            self.error.emit("Filled DEM not found. Complete Step 2 first.")
            return
        if not state.accum_path or not os.path.exists(state.accum_path):
            self.error.emit("Flow accumulation not found. Complete Step 2 first.")
            return
        # ── Read EPSG code from filled DEM ───────────────────────────────
        with rasterio.open(state.filled_dem_path) as src:
            epsg = src.crs.to_epsg()

        if not epsg:
            self.error.emit(
                "Cannot determine EPSG code from the filled DEM's CRS.\n"
                "Ensure the DEM is in a recognised projected CRS "
                "(e.g. UTM 36S / EPSG:32736)."
            )
            return

        out_dir = os.path.join(state.project_dir, "rasters")
        os.makedirs(out_dir, exist_ok=True)

        streamnet_path = os.path.join(out_dir, "streamnet.tif")
        strahler_path  = os.path.join(out_dir, "strahler.tif")
        streams_gpkg   = os.path.join(out_dir, "streams.gpkg")

        threshold = getattr(state, "stream_threshold", 500)

        # ── Build the GRASS Python script ────────────────────────────────
        lines = [
            "import grass.script as gs",
            "import sys",
            "",
            "# ── Import rasters ─────────────────────────────────────────",
            f"gs.run_command('r.in.gdal', input={repr(state.filled_dem_path)}, output='filled', overwrite=True)",
            f"gs.run_command('r.in.gdal', input={repr(state.accum_path)}, output='accum', overwrite=True)",
            "# drain_ws not imported: r.stream.extract computes its own D8 direction",
            "gs.run_command('g.region', raster='filled')",
            "",
            "# ── r.stream.extract — extract stream network ──────────────",
            "# NOTE: we do NOT pass accumulation='accum' here. The accum raster",
            "# from FillWorker uses r.watershed MFD algorithm; r.stream.extract",
            "# uses D8 (SFD). Mixing them produces disconnected stream segments.",
            "# Instead we let r.stream.extract compute its own D8 accumulation",
            "# from the filled DEM, guaranteeing a fully connected network.",
            "print('GRASS: r.stream.extract — extracting streams…', flush=True)",
            f"gs.run_command('r.stream.extract', elevation='filled',",
            f"               threshold={threshold},",
            "               stream_raster='stream_raster',",
            "               stream_vector='streams_extract',",
            "               direction='fdir_extract', overwrite=True)",
            "",
            "# ── Try r.stream.order for Strahler ordering ────────────────",
            "has_stream_order = False",
            "try:",
            "    gs.run_command('g.extension', extension='r.stream.order')",
            "    has_stream_order = True",
            "    print('GRASS: r.stream.order addon available', flush=True)",
            "except Exception:",
            "    print('GRASS: r.stream.order addon not available — skipping Strahler ordering', flush=True)",
            "",
            "if has_stream_order:",
            "    print('GRASS: r.stream.order — computing Strahler orders…', flush=True)",
            "    gs.run_command('r.stream.order', stream_rast='stream_raster',",
            "                   direction='fdir_extract', elevation='filled',",
            "                   accumulation='accum',",
            "                   stream_vect='streams_order', strahler='strahler',",
            "                   overwrite=True)",
            "",
            "# ── Export stream network raster ────────────────────────────",
            "print('GRASS: exporting rasters…', flush=True)",
            # stream_raster contains segment IDs which can exceed Int16 range (>32767)
            # when there are many stream segments — use Int32 to be safe.
            f"gs.run_command('r.out.gdal', input='stream_raster', output={repr(streamnet_path)},",
            "               format='GTiff', type='Int32', nodata='0',",
            "               createopt='COMPRESS=LZW', overwrite=True)",
            "",
            "# ── Export Strahler raster if available ─────────────────────",
            "if has_stream_order:",
            f"    gs.run_command('r.out.gdal', input='strahler', output={repr(strahler_path)},",
            "                   format='GTiff', type='Int32', nodata='0',",
            "                   createopt='COMPRESS=LZW', overwrite=True)",
            "",
            "# ── Export stream vector as GeoPackage ──────────────────────",
            "print('GRASS: exporting stream vectors…', flush=True)",
            "vect_name = 'streams_order' if has_stream_order else 'streams_extract'",
            f"gs.run_command('v.out.ogr', input=vect_name, output={repr(streams_gpkg)},",
            "               format='GPKG', overwrite=True)",
            "",
            "print('GRASS: done', flush=True)",
        ]

        grass_script = "\n".join(lines) + "\n"

        # Write script to a temp file
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", prefix="grass_stream_", delete=False
        )
        tmp.write(grass_script)
        tmp.close()

        # ── Find the GRASS binary ────────────────────────────────────────
        grass_bin = (
            shutil.which("grass")
            or "/opt/local/bin/grass"
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
        self.log_message.emit(f"  Filled DEM:    {os.path.basename(state.filled_dem_path)}")
        self.log_message.emit(f"  Accumulation:  {os.path.basename(state.accum_path)}")
        self.log_message.emit(f"  Threshold:     {threshold} cells")
        self.log_message.emit("  Tools: r.stream.extract + r.stream.order")
        self.progress.emit(5)

        # ── Run GRASS session ────────────────────────────────────────────
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
                if "r.stream.extract" in low:
                    self.progress.emit(25)
                elif "r.stream.order" in low:
                    self.progress.emit(50)
                elif "exporting" in low:
                    self.progress.emit(75)
                elif "done" in low:
                    self.progress.emit(95)

            proc.wait()

        finally:
            os.unlink(tmp.name)

        # ── Check return code ────────────────────────────────────────────
        if proc.returncode != 0:
            self.error.emit(
                f"GRASS processing failed (exit code {proc.returncode}).\n"
                "See the log panel above for details."
            )
            return

        # ── Verify outputs ───────────────────────────────────────────────
        outputs = {
            "streamnet_path": streamnet_path,
        }
        if os.path.exists(strahler_path):
            outputs["strahler_path"] = strahler_path
        if os.path.exists(streams_gpkg):
            outputs["streams_gpkg_path"] = streams_gpkg
            # Log attribute columns so the user can see what Strahler column name GRASS used
            try:
                import geopandas as gpd
                _cols = list(gpd.read_file(streams_gpkg).columns)
                self.log_message.emit(f"  Stream vector columns: {_cols}")
            except Exception:
                pass

        if not os.path.exists(streamnet_path):
            self.error.emit(
                "GRASS exited OK but the stream network raster is missing."
            )
            return

        self.progress.emit(100)
        self.log_message.emit("GRASS stream extraction complete.")
        self.log_message.emit(f"  Stream network -> {os.path.basename(streamnet_path)}")
        if os.path.exists(strahler_path):
            self.log_message.emit(f"  Strahler order -> {os.path.basename(strahler_path)}")
        else:
            self.log_message.emit("  Strahler order -> skipped (addon unavailable)")
        if os.path.exists(streams_gpkg):
            self.log_message.emit(f"  Stream vectors -> {os.path.basename(streams_gpkg)}")
        self.finished.emit(outputs)

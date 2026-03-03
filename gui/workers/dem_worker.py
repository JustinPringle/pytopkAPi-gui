"""
gui/workers/dem_worker.py
=========================
DemWorker — background tasks for DEM download and reprojection.

Tasks:
    'download'  — fetch SRTM/COP30 GeoTIFF from OpenTopography API
    'reproject' — gdalwarp raw DEM to the project CRS
"""

import os
import shutil
import subprocess

from gui.workers.base_worker import BaseWorker


class DemWorker(BaseWorker):

    def run(self) -> None:
        dispatch = {
            "download":  self._download,
            "reproject": self._reproject,
        }
        fn = dispatch.get(self.task)
        if fn is None:
            self.error.emit(f"DemWorker: unknown task '{self.task}'")
            return
        fn()

    # ── Download ──────────────────────────────────────────────────────────────

    def _download(self) -> None:
        try:
            import requests
        except ImportError:
            self.error.emit("'requests' package not installed.")
            return

        b   = self._state.bbox
        key = self._state.ot_api_key
        dem = self._state.dem_type or "SRTMGL1"

        if not b or not key:
            self.error.emit("AOI bbox and API key must be set before downloading.")
            return

        url = (
            "https://portal.opentopography.org/API/globaldem"
            f"?demtype={dem}"
            f"&south={b['south']}&north={b['north']}"
            f"&west={b['west']}&east={b['east']}"
            f"&outputFormat=GTiff&API_Key={key}"
        )

        out_dir  = os.path.join(self._state.project_dir, "rasters")
        out_path = os.path.join(out_dir, "raw_dem.tif")

        self.log_message.emit(f"Downloading {dem} from OpenTopography…")
        self.progress.emit(5)

        try:
            r = requests.get(url, timeout=180, stream=True)

            # OpenTopography returns an error as JSON/text with HTTP 200
            content_type = r.headers.get("Content-Type", "")
            if "application/json" in content_type or "text" in content_type:
                text = r.text[:500]
                self.error.emit(f"OpenTopography error: {text}")
                return

            r.raise_for_status()

            total      = int(r.headers.get("content-length", 0))
            downloaded = 0

            with open(out_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            self.progress.emit(int(downloaded / total * 90))

            self.progress.emit(95)
            size_mb = os.path.getsize(out_path) / 1e6
            self.log_message.emit(f"DEM saved ({size_mb:.1f} MB): {out_path}")
            self.progress.emit(100)
            self.finished.emit({"dem_path": out_path})

        except Exception as exc:
            self.error.emit(f"DEM download failed: {exc}")

    # ── Reproject ─────────────────────────────────────────────────────────────

    def _reproject(self) -> None:
        if not shutil.which("gdalwarp"):
            self.error.emit(
                "gdalwarp not found on PATH.\n"
                "Install GDAL: brew install gdal  (macOS) or OSGeo4W (Windows)"
            )
            return

        src = self._state.dem_path
        if not src or not os.path.exists(src):
            self.error.emit("Raw DEM not found. Download DEM first.")
            return

        out_path = os.path.join(
            self._state.project_dir, "rasters", "dem_projected.tif"
        )
        crs = self._state.crs

        self.log_message.emit(f"Reprojecting DEM to {crs}…")
        self.progress.emit(10)

        result = subprocess.run(
            [
                "gdalwarp",
                "-t_srs", crs,
                "-r", "bilinear",
                "-of", "GTiff",
                "-co", "COMPRESS=LZW",
                src, out_path,
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            self.error.emit(f"gdalwarp failed:\n{result.stderr}")
            return

        self.progress.emit(100)
        self.log_message.emit(f"Reprojected DEM saved: {out_path}")
        self.finished.emit({"proj_dem_path": out_path})

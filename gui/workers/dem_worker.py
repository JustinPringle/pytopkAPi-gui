"""
gui/workers/dem_worker.py
=========================
DemWorker — background tasks for DEM download and reprojection.

Tasks:
    'download'       — fetch DEM GeoTIFF from OpenTopography API (requires API key)
    'download_tiles' — download free SRTM 1-arc-sec tiles from AWS terrain archive
                       (no account or API key needed; same data QGIS SRTM Downloader uses)
    'reproject'      — gdalwarp raw DEM to the project CRS
"""

import gzip
import math
import os
import shutil
import subprocess

from gui.workers.base_worker import BaseWorker


class DemWorker(BaseWorker):

    def run(self) -> None:
        dispatch = {
            "download":       self._download,
            "download_tiles": self._download_tiles,
            "reproject":      self._reproject,
            "hillshade":      self._hillshade,
        }
        fn = dispatch.get(self.task)
        if fn is None:
            self.error.emit(f"DemWorker: unknown task '{self.task}'")
            return
        fn()

    # ── OpenTopography API download (requires API key) ─────────────────────────

    def _download(self) -> None:
        try:
            import requests
        except ImportError:
            self.error.emit("'requests' package not installed.")
            return

        b   = self._state.bbox
        key = self._state.ot_api_key
        dem = self._state.dem_type or "SRTMGL1"

        if not b:
            self.error.emit("AOI bounding box not set. Draw a rectangle on the map first.")
            return
        if not key:
            self.error.emit(
                "OpenTopography now requires an API key for all DEM types.\n\n"
                "Use 'SRTM Tiles (Free)' instead — no key needed.\n"
                "Or get a free key at: opentopography.org  →  My OpenTopo  →  API keys"
            )
            return

        url = (
            "https://portal.opentopography.org/API/globaldem"
            f"?demtype={dem}"
            f"&south={b['south']}&north={b['north']}"
            f"&west={b['west']}&east={b['east']}"
            f"&outputFormat=GTiff"
            f"&API_Key={key}"
        )

        out_dir  = os.path.join(self._state.project_dir, "rasters")
        out_path = os.path.join(out_dir, "raw_dem.tif")

        self.log_message.emit(f"Downloading {dem} from OpenTopography…")
        self.progress.emit(5)

        try:
            r = requests.get(url, timeout=300, stream=True)

            content_type = r.headers.get("Content-Type", "")
            if "application/json" in content_type or "text/xml" in content_type \
                    or "text/html" in content_type:
                self.error.emit(
                    f"OpenTopography error:\n{r.text[:600]}"
                )
                return

            r.raise_for_status()

            total = int(r.headers.get("content-length", 0))
            downloaded = 0
            with open(out_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            self.progress.emit(int(downloaded / total * 90))

            self.progress.emit(100)
            size_mb = os.path.getsize(out_path) / 1e6
            self.log_message.emit(f"DEM saved ({size_mb:.1f} MB): {out_path}")
            self.finished.emit({"dem_path": out_path})

        except Exception as exc:
            self.error.emit(f"DEM download failed: {exc}")

    # ── Free SRTM tile download (AWS terrain archive, no key needed) ───────────

    def _download_tiles(self) -> None:
        """
        Download SRTM 1-arc-sec (30 m) tiles from the AWS Open Data terrain
        archive: s3.amazonaws.com/elevation-tiles-prod/skadi/
        Same source used by QGIS SRTM Downloader.  No API key required.
        Tiles are 1°×1° HGT files, gzip-compressed.
        Multiple tiles are merged with rasterio.
        """
        try:
            import requests
        except ImportError:
            self.error.emit("'requests' package not installed.")
            return
        try:
            import rasterio
            from rasterio.merge import merge as rio_merge
        except ImportError:
            self.error.emit("'rasterio' package not installed.")
            return

        b = self._state.bbox
        if not b:
            self.error.emit("AOI bounding box not set. Draw a rectangle on the map first.")
            return

        out_dir  = os.path.join(self._state.project_dir, "rasters")
        out_path = os.path.join(out_dir, "raw_dem.tif")

        # ── Calculate which 1°×1° tiles overlap the bbox ──────────────────────
        lon_start = math.floor(b["west"])
        lon_end   = math.floor(b["east"])
        lat_start = math.floor(b["south"])
        lat_end   = math.floor(b["north"])

        tiles = []
        for lat in range(lat_start, lat_end + 1):
            for lon in range(lon_start, lon_end + 1):
                lat_str = f"N{lat:02d}"   if lat >= 0 else f"S{abs(lat):02d}"
                lon_str = f"E{lon:03d}"   if lon >= 0 else f"W{abs(lon):03d}"
                tiles.append((lat_str, lon_str, f"{lat_str}{lon_str}"))

        self.log_message.emit(
            f"SRTM tiles needed: {[t[2] for t in tiles]}  "
            f"(AWS terrain archive, free)"
        )
        self.progress.emit(5)

        # ── Download and decompress each tile ─────────────────────────────────
        hgt_paths = []
        n = len(tiles)
        for i, (lat_dir, lon_str, tile_name) in enumerate(tiles):
            url = (
                f"https://s3.amazonaws.com/elevation-tiles-prod/skadi/"
                f"{lat_dir}/{tile_name}.hgt.gz"
            )
            self.log_message.emit(f"  [{i+1}/{n}] Downloading {tile_name}…")
            try:
                r = requests.get(url, timeout=120)
                if r.status_code == 404:
                    self.log_message.emit(
                        f"  {tile_name} not found on server (ocean tile?) — skipping."
                    )
                    continue
                r.raise_for_status()
            except Exception as exc:
                self.error.emit(f"Failed to download tile {tile_name}: {exc}")
                return

            gz_path  = os.path.join(out_dir, f"{tile_name}.hgt.gz")
            hgt_path = os.path.join(out_dir, f"{tile_name}.hgt")
            with open(gz_path, "wb") as f:
                f.write(r.content)
            with gzip.open(gz_path, "rb") as gz_f:
                with open(hgt_path, "wb") as hgt_f:
                    hgt_f.write(gz_f.read())
            os.remove(gz_path)
            hgt_paths.append(hgt_path)
            self.progress.emit(5 + int((i + 1) / n * 70))

        if not hgt_paths:
            self.error.emit("No SRTM tiles could be downloaded for this bounding box.")
            return

        # ── Merge tiles and write GeoTIFF ──────────────────────────────────────
        self.log_message.emit("Merging tiles…")
        try:
            datasets = [rasterio.open(p) for p in hgt_paths]
            mosaic, transform = rio_merge(datasets)
            meta = datasets[0].meta.copy()
            meta.update({
                "driver":    "GTiff",
                "height":    mosaic.shape[1],
                "width":     mosaic.shape[2],
                "transform": transform,
                "compress":  "lzw",
            })
            with rasterio.open(out_path, "w", **meta) as dst:
                dst.write(mosaic)
            for ds in datasets:
                ds.close()
        except Exception as exc:
            self.error.emit(f"Tile merge failed: {exc}")
            return
        finally:
            for p in hgt_paths:
                try:
                    os.remove(p)
                except Exception:
                    pass

        self.progress.emit(100)
        size_mb = os.path.getsize(out_path) / 1e6
        self.log_message.emit(f"DEM saved ({size_mb:.1f} MB): {out_path}")
        self.finished.emit({"dem_path": out_path})

    # ── Reproject ─────────────────────────────────────────────────────────────

    @staticmethod
    def _find_gdal_tool(name: str) -> str | None:
        """Find a GDAL tool, checking common Homebrew/system paths in addition to PATH."""
        found = shutil.which(name)
        if found:
            return found
        search_dirs = [
            "/opt/homebrew/bin",          # Homebrew Apple Silicon
            "/usr/local/bin",             # Homebrew Intel / manual installs
            "/usr/bin",
            "/opt/local/bin",             # MacPorts
        ]
        for d in search_dirs:
            candidate = os.path.join(d, name)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
        return None

    def _reproject(self) -> None:
        gdalwarp = self._find_gdal_tool("gdalwarp")
        if not gdalwarp:
            self.error.emit(
                "gdalwarp not found.\n"
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
        self.log_message.emit(f"  (using {gdalwarp})")
        self.progress.emit(10)

        result = subprocess.run(
            [
                gdalwarp,
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

    # ── Hillshade ─────────────────────────────────────────────────────────────

    def _hillshade(self) -> None:
        """Generate a shaded-relief (hillshade) GeoTIFF using gdaldem hillshade."""
        gdaldem = self._find_gdal_tool("gdaldem")
        if not gdaldem:
            self.error.emit(
                "gdaldem not found.\n"
                "Install GDAL: brew install gdal  (macOS) or OSGeo4W (Windows)"
            )
            return

        # Use filled DEM preferentially; fall back to reprojected DEM
        src = self._state.filled_dem_path or self._state.proj_dem_path
        if not src or not os.path.exists(src):
            self.error.emit(
                "No filled / reprojected DEM found.\n"
                "Load an existing DEM (Section A) or run reprojection (Section B) first."
            )
            return

        out_dir  = os.path.join(self._state.project_dir, "rasters")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "hillshade.tif")

        self.log_message.emit("Generating hillshade…")
        self.log_message.emit(f"  Source: {os.path.basename(src)}")
        self.log_message.emit(f"  (using {gdaldem})")
        self.progress.emit(10)

        result = subprocess.run(
            [
                gdaldem, "hillshade",
                src, out_path,
                "-z", "2",              # vertical exaggeration ×2
                "-co", "COMPRESS=LZW",
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            self.error.emit(f"gdaldem hillshade failed:\n{result.stderr}")
            return

        self.progress.emit(100)
        size_mb = os.path.getsize(out_path) / 1e6
        self.log_message.emit(f"Hillshade saved ({size_mb:.1f} MB): {out_path}")
        self.finished.emit({"hillshade_path": out_path})

"""
gui/workers/shapefile_worker.py
================================
ShapefileWorker — loads a vector file (.shp, .geojson, .gpkg, …),
reprojects all features to WGS84 (EPSG:4326), and returns the result as
a GeoJSON FeatureCollection string.

Primary method: fiona + fiona.transform.transform_geom (fast, pure-Python)
Fallback:       ogr2ogr subprocess (uses the GDAL installation found by
                DemWorker._find_gdal_tool — works even if fiona is absent)

Emits finished({
    "overlay_paths":    [existing…] + [new_path],
    "overlay_names":    [existing…] + [basename],
    "overlay_geojsons": [existing…] + [geojson_str],
})
"""

import json
import os
import subprocess
import tempfile

from gui.workers.base_worker import BaseWorker


class ShapefileWorker(BaseWorker):
    """Load a vector file and reproject to WGS84 GeoJSON."""

    def __init__(self, state, path: str):
        super().__init__()
        self._state = state
        self._path  = path

    def run(self) -> None:
        try:
            self._load()
        except Exception as exc:
            self.error.emit(f"[ShapefileWorker] {exc}")

    # ──────────────────────────────────────────────────────────────────────────

    def _load(self) -> None:
        name = os.path.splitext(os.path.basename(self._path))[0]
        self.log_message.emit(f"Loading layer: {name}…")
        self.progress.emit(10)

        geojson_str = None

        # ── Primary: fiona ────────────────────────────────────────────────
        try:
            geojson_str = self._load_with_fiona(name)
        except ImportError:
            self.log_message.emit("  fiona not available — trying ogr2ogr…")
        except Exception as exc:
            self.log_message.emit(f"  fiona failed ({exc}) — trying ogr2ogr…")

        # ── Fallback: ogr2ogr subprocess ──────────────────────────────────
        if geojson_str is None:
            geojson_str = self._load_with_ogr2ogr(name)

        self.progress.emit(90)

        # Count features for the log message
        try:
            fc = json.loads(geojson_str)
            n = len(fc.get("features", []))
            self.log_message.emit(f"  {n} features loaded from {name}")
        except Exception:
            pass

        # Build updated lists (append to existing)
        paths    = list(self._state.overlay_paths    or []) + [self._path]
        names    = list(self._state.overlay_names    or []) + [name]
        geojsons = list(self._state.overlay_geojsons or []) + [geojson_str]

        self.progress.emit(100)
        self.finished.emit({
            "overlay_paths":    paths,
            "overlay_names":    names,
            "overlay_geojsons": geojsons,
        })

    # ── Fiona approach ────────────────────────────────────────────────────────

    def _load_with_fiona(self, name: str) -> str:
        import fiona
        from fiona.transform import transform_geom

        features = []
        with fiona.open(self._path) as src:
            src_crs = src.crs_wkt or (src.crs.to_wkt() if hasattr(src.crs, "to_wkt") else str(src.crs))
            for feat in src:
                raw_geom = feat.geometry
                if raw_geom is None:
                    continue
                geom_wgs = transform_geom(src_crs, "EPSG:4326", raw_geom)
                props = {k: str(v) for k, v in (feat.properties or {}).items()}
                features.append({
                    "type":       "Feature",
                    "geometry":   geom_wgs,
                    "properties": props,
                })

        return json.dumps({"type": "FeatureCollection", "features": features})

    # ── ogr2ogr fallback ──────────────────────────────────────────────────────

    def _load_with_ogr2ogr(self, name: str) -> str:
        # Reuse DemWorker's path-search helper
        from gui.workers.dem_worker import DemWorker
        ogr2ogr = DemWorker._find_gdal_tool("ogr2ogr")
        if not ogr2ogr:
            raise RuntimeError(
                "ogr2ogr not found. Install GDAL (brew install gdal) "
                "and ensure it is on PATH."
            )

        tmp = tempfile.NamedTemporaryFile(
            suffix=".geojson", prefix="overlay_", delete=False
        )
        tmp_path = tmp.name
        tmp.close()

        try:
            result = subprocess.run(
                [
                    ogr2ogr,
                    "-f", "GeoJSON",
                    "-t_srs", "EPSG:4326",
                    tmp_path,
                    self._path,
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(f"ogr2ogr failed:\n{result.stderr}")

            with open(tmp_path) as f:
                return f.read()
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

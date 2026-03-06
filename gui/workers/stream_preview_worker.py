"""
gui/workers/stream_preview_worker.py
=====================================
StreamPreviewWorker — background QThread that vectorises a flow-accumulation
raster at a given threshold and returns a WGS84 GeoJSON FeatureCollection.

NOT connected to the global start_worker() / _on_worker_finished() pipeline —
the WatershedPanel connects its finished signal directly to its own slot so
that the result is never written to ProjectState and the progress bar is not
consumed.

Emits finished({"stream_geojson": <dict|None>}).
"""

from gui.workers.base_worker import BaseWorker


class StreamPreviewWorker(BaseWorker):
    """Compute a stream-network GeoJSON in the background."""

    def __init__(self, accum_path: str, threshold: int):
        super().__init__()
        self._accum_path = accum_path
        self._threshold  = threshold

    def run(self) -> None:
        try:
            self._compute()
        except Exception as exc:
            self.error.emit(f"[StreamPreviewWorker] {exc}")

    def _compute(self) -> None:
        import numpy as np
        import rasterio
        from rasterio.features import shapes as rio_shapes
        from shapely.geometry import shape
        from shapely.ops import unary_union, transform as shapely_transform
        from pyproj import Transformer

        with rasterio.open(self._accum_path) as src:
            accum     = src.read(1).astype("float64")
            transform = src.transform
            crs       = src.crs
            nodata    = src.nodata

        # Mask nodata before thresholding
        if nodata is not None:
            accum[accum == nodata] = 0

        # Binary stream mask
        stream_mask = (np.abs(accum) >= self._threshold).astype("uint8")
        if stream_mask.sum() == 0:
            self.finished.emit({"stream_geojson": None})
            return

        # Vectorise connected stream regions
        geoms = [
            shape(geom)
            for geom, val in rio_shapes(stream_mask, transform=transform)
            if val == 1
        ]
        if not geoms:
            self.finished.emit({"stream_geojson": None})
            return

        # Simplify + limit to 5 000 polygons for map performance
        cell_size = abs(transform.a)
        geoms = [g.simplify(cell_size * 0.5, preserve_topology=False) for g in geoms]
        geoms = [g for g in geoms if not g.is_empty][:5000]

        # Reproject to WGS84
        trans = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)

        features = []
        for g in geoms:
            g_wgs = shapely_transform(trans.transform, g)
            if not g_wgs.is_empty:
                features.append({
                    "type":       "Feature",
                    "geometry":   g_wgs.__geo_interface__,
                    "properties": {},
                })

        if not features:
            self.finished.emit({"stream_geojson": None})
            return

        self.finished.emit({
            "stream_geojson": {"type": "FeatureCollection", "features": features}
        })

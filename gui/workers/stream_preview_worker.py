"""
gui/workers/stream_preview_worker.py
=====================================
StreamPreviewWorker — background QThread that renders a flow-accumulation
raster at a given threshold as a base64 PNG image overlay (fast) and
optionally as a simplified GeoJSON line network.

NOT connected to the global start_worker() / _on_worker_finished() pipeline —
the WatershedPanel connects its finished signal directly to its own slot.

Emits finished({
    "stream_base64":  <str>,              # base64 PNG of stream mask
    "stream_bounds":  [[s,w],[n,e]],      # WGS84 bounds for the image overlay
    "stream_geojson": <dict|None>,        # optional simplified GeoJSON lines
    "n_stream_cells": <int>,              # number of stream cells
}).
"""

from gui.workers.base_worker import BaseWorker


class StreamPreviewWorker(BaseWorker):
    """Compute a stream-network overlay in the background."""

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
        import base64
        import io

        import numpy as np
        import rasterio
        from PIL import Image
        from pyproj import Transformer

        with rasterio.open(self._accum_path) as src:
            accum     = src.read(1).astype("float64")
            transform = src.transform
            crs       = src.crs
            nodata    = src.nodata
            bounds    = src.bounds

        # Mask nodata before thresholding
        if nodata is not None:
            accum[accum == nodata] = 0

        # Binary stream mask
        stream_mask = np.abs(accum) >= self._threshold
        n_cells = int(stream_mask.sum())

        if n_cells == 0:
            self.finished.emit({"stream_geojson": None, "n_stream_cells": 0})
            return

        # ── Fast path: render stream mask as a transparent blue PNG ────────
        h, w = stream_mask.shape
        # Downsample for very large rasters (keep under 2048px longest side)
        max_dim = 2048
        scale = min(1.0, max_dim / max(h, w))
        if scale < 1.0:
            new_h = max(1, int(h * scale))
            new_w = max(1, int(w * scale))
            # Use PIL nearest-neighbor resize (no scipy dependency)
            mask_img = Image.fromarray(stream_mask.astype(np.uint8) * 255, "L")
            mask_img = mask_img.resize((new_w, new_h), Image.NEAREST)
            stream_mask = np.array(mask_img) > 127

        # Create RGBA image: streams = cyan, non-streams = transparent
        rgba = np.zeros((*stream_mask.shape, 4), dtype=np.uint8)
        rgba[stream_mask, 0] = 0     # R
        rgba[stream_mask, 1] = 191   # G  (#00BFFF = deep sky blue)
        rgba[stream_mask, 2] = 255   # B
        rgba[stream_mask, 3] = 200   # A

        img = Image.fromarray(rgba, "RGBA")
        buf = io.BytesIO()
        img.save(buf, format="PNG", compress_level=6)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        # Reproject bounds to WGS84
        if crs and not crs.is_geographic:
            tr = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
            west, south = tr.transform(bounds.left, bounds.bottom)
            east, north = tr.transform(bounds.right, bounds.top)
        else:
            west, south, east, north = bounds.left, bounds.bottom, bounds.right, bounds.top

        self.finished.emit({
            "stream_base64": b64,
            "stream_bounds": [[south, west], [north, east]],
            "n_stream_cells": n_cells,
            "stream_geojson": None,  # no longer vectorizing for speed
        })

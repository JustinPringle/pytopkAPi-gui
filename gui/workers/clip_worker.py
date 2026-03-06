"""
gui/workers/clip_worker.py
===========================
ClipWorker — clip a raster (DEM) to a polygon mask and create a binary
catchment mask, using rasterio.mask.

Inputs:
    state          — ProjectState (needs filled_dem_path or proj_dem_path)
    geojson_str    — WGS84 GeoJSON Feature string (polygon from subcatchment)
    label          — short name used in output filenames (e.g. "sub1")

Outputs:
    clipped_dem_path  → <project_dir>/rasters/clipped_dem_<label>.tif
    clip_mask_path    → <project_dir>/rasters/clip_mask_<label>.tif
                        (uint8: 1 = active cell, 255 = nodata)

Emits finished({
    "clipped_dem_path": ...,
    "clip_mask_path":   ...,
})
"""

import json
import os

from gui.workers.base_worker import BaseWorker


class ClipWorker(BaseWorker):
    """Clip a raster to a subcatchment polygon and produce a binary mask."""

    def __init__(self, state, geojson_str: str, label: str = "sub"):
        super().__init__()
        self._state       = state
        self._geojson_str = geojson_str
        self._label       = label

    def run(self) -> None:
        try:
            self._clip()
        except Exception as exc:
            self.error.emit(f"[ClipWorker] {exc}")

    # ──────────────────────────────────────────────────────────────────────────

    def _clip(self) -> None:
        import numpy as np
        import rasterio
        from rasterio.mask import mask as rio_mask
        from shapely.geometry import shape, mapping
        from shapely.ops import transform as shapely_transform
        from pyproj import Transformer

        state = self._state

        # ── Select source raster ───────────────────────────────────────────
        src_path = state.filled_dem_path or state.proj_dem_path
        if not src_path or not os.path.exists(src_path):
            self.error.emit(
                "No reprojected / filled DEM found.\n"
                "Complete the GRASS processing in Step 2 first."
            )
            return

        # ── Parse polygon (WGS84) ──────────────────────────────────────────
        try:
            feat     = json.loads(self._geojson_str)
            geom_wgs = shape(feat["geometry"])
        except Exception as exc:
            self.error.emit(f"Invalid GeoJSON for clip: {exc}")
            return

        # ── Reproject polygon → DEM CRS ────────────────────────────────────
        with rasterio.open(src_path) as src:
            dem_crs  = src.crs
            nodata   = src.nodata if src.nodata is not None else -9999

        trans      = Transformer.from_crs("EPSG:4326", dem_crs, always_xy=True)
        geom_proj  = shapely_transform(trans.transform, geom_wgs)

        # ── Output paths ───────────────────────────────────────────────────
        out_dir      = os.path.join(state.project_dir, "rasters")
        os.makedirs(out_dir, exist_ok=True)
        clipped_path = os.path.join(out_dir, f"clipped_dem_{self._label}.tif")
        mask_path    = os.path.join(out_dir, f"clip_mask_{self._label}.tif")

        self.log_message.emit(
            f"Clipping DEM to sub-basin '{self._label}'…\n"
            f"  Source: {os.path.basename(src_path)}"
        )
        self.progress.emit(20)

        # ── 1. Clip DEM ────────────────────────────────────────────────────
        with rasterio.open(src_path) as src:
            out_image, out_transform = rio_mask(
                src,
                [mapping(geom_proj)],
                crop=True,
                nodata=nodata,
                all_touched=False,
            )
            meta = src.meta.copy()

        meta.update(
            driver="GTiff",
            height=out_image.shape[1],
            width=out_image.shape[2],
            transform=out_transform,
            nodata=nodata,
            compress="lzw",
        )
        with rasterio.open(clipped_path, "w", **meta) as dst:
            dst.write(out_image)

        self.log_message.emit(f"  Clipped DEM  → {os.path.basename(clipped_path)}")
        self.progress.emit(60)

        # ── 2. Create binary mask (1 = active, 255 = nodata) ──────────────
        band = out_image[0]
        inside = np.where(band != nodata, np.uint8(1), np.uint8(255))

        mask_meta = meta.copy()
        mask_meta.update(dtype="uint8", nodata=255, count=1)
        with rasterio.open(mask_path, "w", **mask_meta) as dst:
            dst.write(inside[np.newaxis, ...])

        self.log_message.emit(f"  Clip mask    → {os.path.basename(mask_path)}")
        self.progress.emit(100)

        n_active = int((inside == 1).sum())
        self.log_message.emit(
            f"✅ Clip complete — {n_active:,} active cells in '{self._label}'"
        )
        self.finished.emit({
            "clipped_dem_path": clipped_path,
            "clip_mask_path":   mask_path,
        })

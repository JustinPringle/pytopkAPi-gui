"""
gui/workers/raster_render_worker.py
====================================
RasterRenderWorker — thin QThread wrapper around raster_to_base64().

Called by MapView when the Leaflet map zoom level changes to a new resolution
bucket, requesting a higher- (or lower-) resolution re-render of an active
raster overlay.

Emits:
    finished_render(name: str, b64: str, bounds: list, blend_mode: str,
                    opacity: float)
"""

from PyQt6.QtCore import QThread, pyqtSignal


class RasterRenderWorker(QThread):
    finished_render = pyqtSignal(str, str, list, str, float)
    # name, base64_png, [[s,w],[n,e]], blend_mode, opacity

    error = pyqtSignal(str)

    def __init__(self, name: str, path: str, cmap: str, alpha: float,
                 blend_mode: str, hillshade: bool, log_scale: bool,
                 clip_bounds, max_dim: int,
                 vmin: float | None = None,
                 vmax: float | None = None,
                 parent=None):
        super().__init__(parent)
        self._name        = name
        self._path        = path
        self._cmap        = cmap
        self._alpha       = alpha
        self._blend_mode  = blend_mode
        self._hillshade   = hillshade
        self._log_scale   = log_scale
        self._clip_bounds = clip_bounds
        self._max_dim     = max_dim
        self._vmin        = vmin
        self._vmax        = vmax

    def run(self) -> None:
        try:
            from gui.widgets.map_widget import raster_to_base64
            b64, bounds = raster_to_base64(
                self._path,
                cmap=self._cmap,
                alpha=self._alpha,
                max_dim=self._max_dim,
                hillshade=self._hillshade,
                clip_bounds=self._clip_bounds,
                log_scale=self._log_scale,
                vmin=self._vmin,
                vmax=self._vmax,
            )
            self.finished_render.emit(
                self._name, b64, bounds, self._blend_mode, self._alpha
            )
        except Exception as exc:
            self.error.emit(f"[RasterRenderWorker:{self._name}] {exc}")

"""
gui/widgets/map_view.py
=======================
MapView — persistent GIS-style map container.

Wraps any MapWidget in a toolbar that provides:
  • Zoom In / Zoom Out / Zoom to Fit buttons (call Leaflet JS via page())
  • Mouse-coordinate display (lat, lon) fed from MapBridge.coord_moved
  • Scale label (zoom level from Leaflet)

Usage:
    # Created once in MainWindow — never removed or re-parented.
    self._map_view = MapView()
    self._centre_tabs.addTab(self._map_view, "Map")

    # Panels call this when they want to show their MapWidget:
    self._map_view.set_map_widget(panel_map_widget)
"""

from __future__ import annotations

import json

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)


def _zoom_to_max_dim(zoom: int) -> int:
    """Map a Leaflet zoom level to a raster output resolution (px)."""
    if zoom <= 10:
        return 512
    if zoom <= 12:
        return 1024
    if zoom <= 14:
        return 2048
    return 4096


class MapView(QWidget):
    """Persistent toolbar + swappable MapWidget container."""

    # Re-exported so MainWindow can connect to whichever widget is current
    coord_moved     = pyqtSignal(float, float)
    feature_clicked = pyqtSignal(str, str)    # overlay_name, GeoJSON Feature string

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current = None   # current MapWidget (or None)

        # Zoom-responsive raster rendering state
        self._zoom_level: int = 12
        # {name: (path, cmap, alpha, blend_mode, hillshade, log_scale, clip_bounds, vmin, vmax)}
        self._active_rasters: dict = {}
        # {name: {max_dim: (b64, bounds)}}
        self._render_cache: dict = {}
        # Running render workers (kept alive until finished)
        self._render_workers: list = []
        # Debounce timer: fires 500ms after last zoom event
        self._zoom_timer = QTimer(self)
        self._zoom_timer.setSingleShot(True)
        self._zoom_timer.timeout.connect(self._on_zoom_timeout)
        self._pending_zoom: int = 12
        # {state_attr: overlay_name} — reverse lookup for rerender_by_state_attr
        self._state_attr_to_overlay: dict = {}

        self._build_ui()

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Map toolbar ───────────────────────────────────────────────────────
        self._toolbar = QWidget()
        self._toolbar.setFixedHeight(32)
        self._toolbar.setObjectName("mapToolbar")
        tb = QHBoxLayout(self._toolbar)
        tb.setContentsMargins(6, 2, 6, 2)
        tb.setSpacing(3)

        self._btn_zoom_in  = self._make_btn("+",  "Zoom in  (also: scroll wheel)")
        self._btn_zoom_out = self._make_btn("−",  "Zoom out (also: scroll wheel)")
        self._btn_zoom_fit = self._make_btn("[ ]", "Zoom to full extent")
        tb.addWidget(self._btn_zoom_in)
        tb.addWidget(self._btn_zoom_out)
        tb.addWidget(self._btn_zoom_fit)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color:#555; margin: 4px 2px;")
        tb.addWidget(sep)

        self._coord_label = QLabel("Lat: —          Lon: —")
        self._coord_label.setObjectName("coordLabel")
        self._coord_label.setMinimumWidth(240)
        tb.addWidget(self._coord_label)

        tb.addStretch()

        self._hint_label = QLabel("")
        self._hint_label.setObjectName("mapHintLabel")
        tb.addWidget(self._hint_label)

        layout.addWidget(self._toolbar)

        # ── Swappable content area ────────────────────────────────────────────
        self._content_area = QWidget()
        self._content_area.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        ca_layout = QVBoxLayout(self._content_area)
        ca_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._content_area, stretch=1)

        # Placeholder shown before any panel loads a map
        self._placeholder = QLabel("Select a workflow step to load the map.")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color:#555; font-size:14px;")
        ca_layout.addWidget(self._placeholder)

        # Button connections
        self._btn_zoom_in.clicked.connect(self._zoom_in)
        self._btn_zoom_out.clicked.connect(self._zoom_out)
        self._btn_zoom_fit.clicked.connect(self._zoom_fit)

        self._set_buttons_enabled(False)

    @staticmethod
    def _make_btn(text: str, tooltip: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedSize(28, 24)
        btn.setToolTip(tooltip)
        btn.setObjectName("mapToolBtn")
        return btn

    # ── Public API ─────────────────────────────────────────────────────────────

    def set_map_widget(self, widget) -> None:
        """Swap in a new MapWidget (or any QWidget) as the map content."""
        from gui.widgets.map_widget import MapWidget

        # Disconnect signals from the outgoing widget
        if self._current is not None:
            for sig, slot in [
                ("coord_moved", self._on_coord_moved),
                ("zoom_changed", self._on_zoom_debounce),
                ("feature_clicked", self.feature_clicked),
            ]:
                if hasattr(self._current, sig):
                    try:
                        getattr(self._current, sig).disconnect(slot)
                    except Exception:
                        pass

        # Clear content area
        ca_layout = self._content_area.layout()
        while ca_layout.count():
            item = ca_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        self._current = widget
        ca_layout.addWidget(widget)

        # Wire coordinate + zoom + feature signals if the widget supports it
        is_map = isinstance(widget, MapWidget)
        if is_map:
            widget.coord_moved.connect(self._on_coord_moved)
            widget.zoom_changed.connect(self._on_zoom_debounce)
            widget.feature_clicked.connect(self.feature_clicked)
        else:
            self._coord_label.setText("Lat: —          Lon: —")

        self._set_buttons_enabled(is_map)

    def set_hint(self, msg: str) -> None:
        """Show a short instruction hint in the toolbar (e.g. 'Click to place outlet')."""
        self._hint_label.setText(msg)
        if msg:
            self._hint_label.setStyleSheet(
                "color: #FFD54F; font-size: 12px; font-weight: bold; "
                "background: rgba(26, 111, 196, 0.25); "
                "border-radius: 4px; padding: 2px 8px;"
            )
        else:
            self._hint_label.setStyleSheet("")

    def clear_hint(self) -> None:
        self._hint_label.setText("")
        self._hint_label.setStyleSheet("")

    # ── Private ────────────────────────────────────────────────────────────────

    def _on_coord_moved(self, lat: float, lon: float) -> None:
        self._coord_label.setText(f"Lat: {lat:>10.5f}   Lon: {lon:>10.5f}")
        self.coord_moved.emit(lat, lon)

    @pyqtSlot(int)
    def _on_zoom_debounce(self, zoom: int) -> None:
        """Restart the 500ms debounce timer on each zoom event."""
        self._pending_zoom = zoom
        self._zoom_timer.start(500)

    def _on_zoom_timeout(self) -> None:
        """Called 500ms after the last zoom event — trigger re-renders if needed."""
        zoom = self._pending_zoom
        new_dim = _zoom_to_max_dim(zoom)
        old_dim = _zoom_to_max_dim(self._zoom_level)
        self._zoom_level = zoom
        if new_dim == old_dim or not self._active_rasters:
            return
        for name, params in list(self._active_rasters.items()):
            path, cmap, alpha, blend_mode, hillshade, log_scale, clip_bounds, vmin, vmax = params
            cached = self._render_cache.get(name, {}).get(new_dim)
            if cached:
                b64, bounds = cached
                eff_alpha = 1.0 if hillshade else alpha
                self._run_js(
                    f"if(window._addRasterOverlay)"
                    f"  window._addRasterOverlay("
                    f"    {json.dumps(name)},"
                    f"    '{b64}',"
                    f"    {json.dumps(bounds)},"
                    f"    {eff_alpha},"
                    f"    {json.dumps(blend_mode)}"
                    f"  );"
                )
            else:
                self._start_raster_render(name, path, cmap, alpha, blend_mode,
                                          hillshade, log_scale, clip_bounds, new_dim,
                                          vmin=vmin, vmax=vmax)

    def _start_raster_render(self, name, path, cmap, alpha, blend_mode,
                              hillshade, log_scale, clip_bounds, max_dim,
                              vmin=None, vmax=None) -> None:
        """Start a background re-render of one raster overlay."""
        from gui.workers.raster_render_worker import RasterRenderWorker
        worker = RasterRenderWorker(
            name=name, path=path, cmap=cmap, alpha=alpha,
            blend_mode=blend_mode, hillshade=hillshade,
            log_scale=log_scale, clip_bounds=clip_bounds,
            max_dim=max_dim, vmin=vmin, vmax=vmax,
        )
        worker.finished_render.connect(self._on_raster_rendered)
        worker.error.connect(lambda msg: print(msg))
        worker.finished.connect(lambda: self._render_workers.remove(worker)
                                if worker in self._render_workers else None)
        self._render_workers.append(worker)
        worker.start()

    @pyqtSlot(str, str, list, str, float)
    def _on_raster_rendered(self, name: str, b64: str, bounds: list,
                            blend_mode: str, alpha: float) -> None:
        """Called when a background re-render completes."""
        max_dim = _zoom_to_max_dim(self._zoom_level)
        # Cache the result
        if name not in self._render_cache:
            self._render_cache[name] = {}
        self._render_cache[name][max_dim] = (b64, bounds)
        # Only apply if this layer is still active
        if name not in self._active_rasters:
            return
        eff_alpha = 1.0 if self._active_rasters[name][4] else alpha
        self._run_js(
            f"if(window._addRasterOverlay)"
            f"  window._addRasterOverlay("
            f"    {json.dumps(name)},"
            f"    '{b64}',"
            f"    {json.dumps(bounds)},"
            f"    {eff_alpha},"
            f"    {json.dumps(blend_mode)}"
            f"  );"
        )

    def _set_buttons_enabled(self, enabled: bool) -> None:
        for btn in (self._btn_zoom_in, self._btn_zoom_out, self._btn_zoom_fit):
            btn.setEnabled(enabled)

    def _run_js(self, script: str) -> None:
        if self._current is not None:
            self._current.page().runJavaScript(script)

    def _zoom_in(self) -> None:
        self._run_js("if(window._pytopkapi_map) window._pytopkapi_map.zoomIn();")

    def _zoom_out(self) -> None:
        self._run_js("if(window._pytopkapi_map) window._pytopkapi_map.zoomOut();")

    def _zoom_fit(self) -> None:
        self._run_js(
            "if(window._pytopkapi_map){"
            "  var b=window._pytopkapi_map.getBounds();"
            "  if(b.isValid()) window._pytopkapi_map.fitBounds(b);"
            "}"
        )

    # ── Dynamic overlay management ──────────────────────────────────────────

    def add_raster_overlay(self, name: str, path: str,
                           cmap: str = "terrain", alpha: float = 0.7,
                           blend_mode: str = "normal",
                           hillshade: bool = False,
                           clip_bounds: tuple | None = None,
                           log_scale: bool = False,
                           vmin: float | None = None,
                           vmax: float | None = None,
                           state_attr: str = "") -> None:
        """Convert a GeoTIFF to a PNG overlay and display it on the map.

        blend_mode:  CSS mix-blend-mode value ('normal', 'multiply', etc.)
        hillshade:   True → render as opaque multiply-ready greyscale (ignores alpha/cmap)
        clip_bounds: Optional (south, west, north, east) WGS84 tuple to crop
                     the raster before rendering (improves resolution over AOI).
        log_scale:   Apply log1p transform before colormap (use for flow accumulation).
        vmin / vmax: Explicit colour stretch limits (None = auto percentile).
        state_attr:  ProjectState field name for this layer (used by rerender_by_state_attr).
        """
        from gui.widgets.map_widget import raster_to_base64
        try:
            b64, bounds = raster_to_base64(path, cmap=cmap, alpha=alpha,
                                           hillshade=hillshade,
                                           clip_bounds=clip_bounds,
                                           log_scale=log_scale,
                                           vmin=vmin, vmax=vmax)
        except Exception as exc:
            import traceback
            print(f"[MapView] raster overlay error for '{name}': {exc}\n{traceback.format_exc()}")
            return

        # Store params for zoom-responsive re-render
        self._active_rasters[name] = (path, cmap, alpha, blend_mode,
                                       hillshade, log_scale, clip_bounds,
                                       vmin, vmax)
        if state_attr:
            self._state_attr_to_overlay[state_attr] = name
        # Seed render cache with the initial render
        current_dim = _zoom_to_max_dim(self._zoom_level)
        if name not in self._render_cache:
            self._render_cache[name] = {}
        self._render_cache[name][current_dim] = (b64, bounds)

        eff_alpha = 1.0 if hillshade else alpha
        js = (
            f"if(window._addRasterOverlay)"
            f"  window._addRasterOverlay("
            f"    {json.dumps(name)},"
            f"    '{b64}',"
            f"    {json.dumps(bounds)},"
            f"    {eff_alpha},"
            f"    {json.dumps(blend_mode)}"
            f"  );"
        )
        self._run_js(js)

    def add_contour_overlay(self, name: str, path: str,
                            interval: float = 20.0,
                            clip_bounds: tuple | None = None,
                            color: str = "#90a4ae",
                            weight: int = 1) -> None:
        """Generate contour lines from a DEM and add them as a vector overlay.

        interval:    Contour interval in metres.
        clip_bounds: Optional (south, west, north, east) WGS84 crop region.
        """
        from gui.widgets.map_widget import dem_to_contours_geojson
        try:
            geojson_str = dem_to_contours_geojson(path, interval=interval,
                                                   clip_bounds=clip_bounds)
        except Exception as exc:
            import traceback
            print(f"[MapView] contour error for '{name}': {exc}\n{traceback.format_exc()}")
            return
        self.add_vector_overlay(name, geojson_str, color=color, weight=weight,
                                fill_opacity=0.0)

    def add_vector_overlay(self, name: str, geojson_str: str,
                           color: str = "#FF6B35",
                           weight: int = 2,
                           fill_opacity: float = 0.15,
                           weight_column: str = "",
                           selectable: bool = False) -> None:
        """Add a GeoJSON vector overlay to the map.

        Args:
            weight_column: Feature property name used to scale line width
                           (e.g. 'strahler' for Strahler-weighted streams).
            selectable:    If True, clicking a feature sends it back to Python
                           via the feature_clicked signal (used for basin selection).
        """
        escaped = json.dumps(geojson_str)
        wc   = json.dumps(weight_column) if weight_column else "null"
        sel  = "true" if selectable else "false"
        js = (
            f"window._addVectorOverlay("
            f"    {json.dumps(name)}, {escaped}, {json.dumps(color)},"
            f"    {weight}, {fill_opacity}, {wc}, {sel}"
            f");"
        )
        self._run_js(js)

    def set_overlay_opacity(self, name: str, opacity: float) -> None:
        """Set opacity (0.0–1.0) for a named overlay on the map."""
        js = (
            f"if(window._setOverlayOpacity)"
            f"  window._setOverlayOpacity({json.dumps(name)}, {opacity});"
        )
        self._run_js(js)

    def toggle_overlay(self, name: str, visible: bool) -> None:
        """Show/hide a named overlay layer on the map."""
        js = (
            f"if(window._toggleOverlay)"
            f"  window._toggleOverlay({json.dumps(name)}, {'true' if visible else 'false'});"
        )
        self._run_js(js)

    def remove_overlay(self, name: str) -> None:
        """Remove a named overlay completely."""
        js = f"if(window._removeOverlay) window._removeOverlay({json.dumps(name)});"
        self._run_js(js)

    def toggle_basemap(self, visible: bool) -> None:
        """Toggle the satellite base tile layer on/off."""
        js = f"if(window._toggleBaseMap) window._toggleBaseMap({'true' if visible else 'false'});"
        self._run_js(js)

    # ── Draw mode and programmatic items ──────────────────────────────────

    def set_draw_mode(self, mode: str) -> None:
        """Set the active draw tool: 'rectangle', 'marker', 'both', or 'none'."""
        self._run_js(f"if(window._setDrawMode) window._setDrawMode({json.dumps(mode)});")

    def add_marker(self, lat: float, lon: float,
                   tooltip: str = "", color: str = "#e74c3c") -> None:
        """Add a programmatic marker to the map."""
        js = (
            f"if(window._addMarkerItem)"
            f"  window._addMarkerItem({lat}, {lon},"
            f"    {json.dumps(tooltip)}, {json.dumps(color)});"
        )
        self._run_js(js)

    def clear_markers(self) -> None:
        """Remove all programmatic and drawn markers."""
        self._run_js("if(window._clearMarkers) window._clearMarkers();")

    def add_rectangle(self, south: float, west: float,
                      north: float, east: float,
                      color: str = "#1a6fc4") -> None:
        """Add a programmatic rectangle to the map."""
        js = (
            f"if(window._addRectangleItem)"
            f"  window._addRectangleItem({south}, {west}, {north}, {east},"
            f"    {json.dumps(color)});"
        )
        self._run_js(js)

    def clear_rectangles(self) -> None:
        """Remove all programmatic and drawn rectangles."""
        self._run_js("if(window._clearRectangles) window._clearRectangles();")

    def rerender_by_state_attr(self, attr: str, limits: dict) -> None:
        """Re-render the overlay associated with *attr* using updated colour limits.

        limits: {"vmin": float, "vmax": float} — either key may be absent.
        Called by MainWindow when the user changes colour limits in LayersDock.
        """
        name = self._state_attr_to_overlay.get(attr)
        if not name or name not in self._active_rasters:
            return
        path, cmap, alpha, blend_mode, hillshade, log_scale, clip_bounds, _, _ = \
            self._active_rasters[name]
        new_vmin = limits.get("vmin") if limits else None
        new_vmax = limits.get("vmax") if limits else None
        # Update stored params with new limits
        self._active_rasters[name] = (path, cmap, alpha, blend_mode,
                                       hillshade, log_scale, clip_bounds,
                                       new_vmin, new_vmax)
        # Invalidate cache for this layer so next render uses new limits
        self._render_cache.pop(name, None)
        max_dim = _zoom_to_max_dim(self._zoom_level)
        self._start_raster_render(name, path, cmap, alpha, blend_mode,
                                   hillshade, log_scale, clip_bounds, max_dim,
                                   vmin=new_vmin, vmax=new_vmax)

    def clear_all_overlays(self) -> None:
        """Remove all overlays, markers, and rectangles."""
        self._run_js("if(window._clearAllOverlays) window._clearAllOverlays();")
        # Reset zoom-responsive rendering state
        self._active_rasters.clear()
        self._render_cache.clear()
        self._zoom_timer.stop()
        self._state_attr_to_overlay.clear()

    def set_view(self, lat: float, lon: float, zoom: int = 12) -> None:
        """Set the map centre and zoom."""
        self._run_js(f"if(window._setView) window._setView({lat}, {lon}, {zoom});")

    def fit_bounds(self, south: float, west: float,
                   north: float, east: float) -> None:
        """Fit the map to the given bounds."""
        js = (
            f"if(window._fitBounds)"
            f"  window._fitBounds({south}, {west}, {north}, {east});"
        )
        self._run_js(js)

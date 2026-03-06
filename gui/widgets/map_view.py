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

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)


class MapView(QWidget):
    """Persistent toolbar + swappable MapWidget container."""

    # Re-exported so MainWindow can connect to whichever widget is current
    coord_moved = pyqtSignal(float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current = None   # current MapWidget (or None)
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

        # Disconnect coord signal from the outgoing widget
        if self._current is not None and hasattr(self._current, "coord_moved"):
            try:
                self._current.coord_moved.disconnect(self._on_coord_moved)
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

        # Wire coordinate signal if the widget supports it
        is_map = isinstance(widget, MapWidget)
        if is_map:
            widget.coord_moved.connect(self._on_coord_moved)
        else:
            self._coord_label.setText("Lat: —          Lon: —")

        self._set_buttons_enabled(is_map)

    def set_hint(self, msg: str) -> None:
        """Show a short instruction hint in the toolbar (e.g. 'Click to place outlet')."""
        self._hint_label.setText(msg)

    def clear_hint(self) -> None:
        self._hint_label.setText("")

    # ── Private ────────────────────────────────────────────────────────────────

    def _on_coord_moved(self, lat: float, lon: float) -> None:
        self._coord_label.setText(f"Lat: {lat:>10.5f}   Lon: {lon:>10.5f}")
        self.coord_moved.emit(lat, lon)

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

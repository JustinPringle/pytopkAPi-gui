"""
gui/widgets/map_widget.py
=========================
MapWidget  — QWebEngineView that displays Folium maps and receives
             user draw events (rectangle AOI, marker outlet) back in
             Python via the QWebChannel bridge.

MapBridge  — QObject whose slots are exposed to JavaScript as
             window.bridge.onBboxDrawn(jsonStr) and
             window.bridge.onOutletPlaced(jsonStr).

Usage:
    widget = MapWidget()
    widget.bbox_drawn.connect(my_panel._on_bbox_drawn)
    widget.outlet_placed.connect(my_panel._on_outlet_placed)
    html = MapWidget.build_aoi_map(centre=(-29.71, 31.06))
    widget.load_map(html)
    main_window.set_map_widget(widget)

Fix notes:
    1. Full-screen CSS is injected into every map HTML so the Leaflet
       map fills 100 % of the QWebEngineView viewport (no white border).
    2. The JS bridge uses a pending-events queue to handle the async gap
       between the draw:created Leaflet event and QWebChannel init.
       Previously `if (!bridge) return;` silently dropped draw events
       that fired before the bridge was ready.
"""

import json

import folium
from folium.plugins import Draw

from PyQt6.QtCore import QObject, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings


class MapBridge(QObject):
    """Python object exposed to JavaScript as ``window.bridge``.

    JavaScript calls these slots by name; Qt delivers them as signals.
    """

    bbox_drawn    = pyqtSignal(dict)          # {south, north, west, east}
    outlet_placed = pyqtSignal(float, float)  # lat, lon

    @pyqtSlot(str)
    def onBboxDrawn(self, json_str: str) -> None:  # noqa: N802 (matches JS convention)
        try:
            data = json.loads(json_str)
            self.bbox_drawn.emit(data)
        except Exception as exc:
            print(f"[MapBridge] onBboxDrawn parse error: {exc}")

    @pyqtSlot(str)
    def onOutletPlaced(self, json_str: str) -> None:  # noqa: N802
        try:
            data = json.loads(json_str)
            self.outlet_placed.emit(float(data["lat"]), float(data["lon"]))
        except Exception as exc:
            print(f"[MapBridge] onOutletPlaced parse error: {exc}")


# ── CSS injected into every Folium map ────────────────────────────────────────
# Forces the map to fill 100 % of the QWebEngineView viewport.
# Folium normally creates a div with height:500px or similar; this overrides it.
_FULLSCREEN_CSS = """<style>
html, body {
    height: 100%;
    width:  100%;
    margin: 0;
    padding: 0;
    overflow: hidden;
    background: #1e1e1e;
}
.folium-map {
    position: absolute !important;
    top: 0; left: 0; right: 0; bottom: 0;
    width:  100% !important;
    height: 100% !important;
}
/* Hide Leaflet attribution in kiosk-style view */
.leaflet-control-attribution { font-size: 9px; opacity: 0.6; }
</style>
"""

# ── JS snippet injected into every Folium map ──────────────────────────────────
# Fixes a race condition: the Leaflet draw:created event can fire *before* the
# QWebChannel bridge finishes initialising.  We queue any events that arrive
# before the bridge is ready and replay them once it is.
_BRIDGE_JS = """
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<script>
(function() {
    // Bridge object — set once QWebChannel init callback fires.
    var bridge = null;
    // Queue of {fn} calls that arrived before the bridge was ready.
    var pendingCalls = [];

    function flushPending() {
        var calls = pendingCalls.splice(0);
        calls.forEach(function(fn) { fn(); });
    }

    // Initialise the QWebChannel connection to Python
    new QWebChannel(qt.webChannelTransport, function(channel) {
        bridge = channel.objects.bridge;
        flushPending();   // replay any draw events that arrived early
    });

    // Deliver a call now if bridge is ready, otherwise queue it.
    function sendOrQueue(fn) {
        if (bridge) { fn(); } else { pendingCalls.push(fn); }
    }

    // Wait for the Leaflet map to appear in the global scope.
    // Folium registers each map as a global named map_<hash>.
    function findLeafletMap() {
        var keys = Object.keys(window);
        for (var i = 0; i < keys.length; i++) {
            var k = keys[i];
            if (k.startsWith('map_') && window[k] && window[k].on) {
                return window[k];
            }
        }
        return null;
    }

    function hookMap() {
        var m = findLeafletMap();
        if (!m) {
            setTimeout(hookMap, 100);
            return;
        }
        m.on('draw:created', function(e) {
            var layer = e.layer;
            var type  = e.layerType;
            if (type === 'rectangle') {
                var b = layer.getBounds();
                var payload = JSON.stringify({
                    south: b.getSouth(),
                    north: b.getNorth(),
                    west:  b.getWest(),
                    east:  b.getEast()
                });
                sendOrQueue(function() { bridge.onBboxDrawn(payload); });
            } else if (type === 'marker') {
                var ll = layer.getLatLng();
                var payload = JSON.stringify({ lat: ll.lat, lon: ll.lng });
                sendOrQueue(function() { bridge.onOutletPlaced(payload); });
            }
        });
    }

    if (document.readyState === 'complete') {
        hookMap();
    } else {
        window.addEventListener('load', hookMap);
    }
})();
</script>
"""


class MapWidget(QWebEngineView):
    """Interactive Folium map widget with Python ↔ JavaScript bridge."""

    bbox_drawn    = pyqtSignal(dict)
    outlet_placed = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)

        # Dark background so there's no white flash before the map loads
        self.page().setBackgroundColor(QColor("#1e1e1e"))

        # Allow local content to access remote tile servers AND qrc:// scripts
        settings = self.page().settings()
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True
        )

        # Set up the QWebChannel
        self._bridge  = MapBridge()
        self._channel = QWebChannel(self.page())
        self._channel.registerObject("bridge", self._bridge)
        self.page().setWebChannel(self._channel)

        # Forward bridge signals as widget signals
        self._bridge.bbox_drawn.connect(self.bbox_drawn)
        self._bridge.outlet_placed.connect(self.outlet_placed)

    # ── Public API ─────────────────────────────────────────────────────────────

    def load_map(self, html: str) -> None:
        """Inject CSS + QWebChannel bridge script and load the Folium HTML."""
        processed = self._add_fullscreen_css(html)
        processed = self._inject_bridge(processed)
        self.setHtml(processed, baseUrl=QUrl("qrc:///"))

    # ── Static map builders ────────────────────────────────────────────────────

    @staticmethod
    def build_aoi_map(
        centre: tuple = (-29.71, 31.06),
        zoom: int = 11,
        existing_bbox: dict | None = None,
    ) -> str:
        """Folium map with rectangle-draw enabled. Returns HTML string."""
        m = folium.Map(location=list(centre), zoom_start=zoom, prefer_canvas=True)

        # Satellite basemap
        folium.TileLayer(
            tiles=(
                "https://server.arcgisonline.com/ArcGIS/rest/services/"
                "World_Imagery/MapServer/tile/{z}/{y}/{x}"
            ),
            attr="Esri World Imagery",
            name="Satellite",
        ).add_to(m)

        # Draw plugin — rectangle only
        Draw(
            draw_options={
                "rectangle":    {"shapeOptions": {"color": "#1a6fc4"}},
                "polyline":     False,
                "polygon":      False,
                "circle":       False,
                "marker":       False,
                "circlemarker": False,
            },
            edit_options={"edit": False, "remove": True},
        ).add_to(m)

        # Show any previously saved bbox
        if existing_bbox:
            b = existing_bbox
            folium.Rectangle(
                bounds=[[b["south"], b["west"]], [b["north"], b["east"]]],
                color="#1a6fc4",
                weight=2,
                fill=True,
                fill_opacity=0.15,
                tooltip="Current AOI",
            ).add_to(m)

        folium.LayerControl().add_to(m)
        return m._repr_html_()

    @staticmethod
    def build_outlet_map(
        centre: tuple,
        zoom: int = 13,
        existing_outlet: tuple | None = None,
        catchment_geojson: dict | None = None,
    ) -> str:
        """Folium map with marker-draw enabled. Returns HTML string."""
        m = folium.Map(location=list(centre), zoom_start=zoom, prefer_canvas=True)

        folium.TileLayer(
            tiles=(
                "https://server.arcgisonline.com/ArcGIS/rest/services/"
                "World_Imagery/MapServer/tile/{z}/{y}/{x}"
            ),
            attr="Esri World Imagery",
            name="Satellite",
        ).add_to(m)

        # Draw plugin — marker only
        Draw(
            draw_options={
                "marker":       True,
                "rectangle":    False,
                "polyline":     False,
                "polygon":      False,
                "circle":       False,
                "circlemarker": False,
            },
            edit_options={"edit": False, "remove": True},
        ).add_to(m)

        # Show existing outlet marker
        if existing_outlet:
            lat, lon = existing_outlet
            folium.Marker(
                [lat, lon],
                tooltip="Outlet",
                icon=folium.Icon(color="red", icon="star"),
            ).add_to(m)

        # Show delineated catchment boundary if available
        if catchment_geojson:
            folium.GeoJson(
                catchment_geojson,
                style_function=lambda _: {
                    "color": "#2ecc71",
                    "weight": 2,
                    "fillOpacity": 0.15,
                },
                tooltip="Catchment boundary",
            ).add_to(m)

        folium.LayerControl().add_to(m)
        return m._repr_html_()

    # ── Private helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _add_fullscreen_css(html: str) -> str:
        """Inject CSS so the Leaflet map fills 100 % of the viewport."""
        if "<head>" in html:
            return html.replace("<head>", "<head>\n" + _FULLSCREEN_CSS, 1)
        # Fallback: prepend at start
        return _FULLSCREEN_CSS + html

    @staticmethod
    def _inject_bridge(html: str) -> str:
        """Insert the QWebChannel bridge script before </body>."""
        if "</body>" in html:
            return html.replace("</body>", _BRIDGE_JS + "\n</body>", 1)
        return html + _BRIDGE_JS

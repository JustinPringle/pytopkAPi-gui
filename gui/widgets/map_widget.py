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
    polygon_drawn = pyqtSignal(dict)          # GeoJSON Feature dict
    coord_moved   = pyqtSignal(float, float)  # lat, lon (mouse position)
    feature_clicked = pyqtSignal(str, str)    # overlay_name, GeoJSON Feature string
    zoom_changed  = pyqtSignal(int)           # Leaflet zoom level

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

    @pyqtSlot(str)
    def onPolygonDrawn(self, json_str: str) -> None:  # noqa: N802
        try:
            data = json.loads(json_str)
            self.polygon_drawn.emit(data)
        except Exception as exc:
            print(f"[MapBridge] onPolygonDrawn parse error: {exc}")

    @pyqtSlot(str)
    def onMouseMove(self, json_str: str) -> None:  # noqa: N802
        try:
            data = json.loads(json_str)
            self.coord_moved.emit(float(data["lat"]), float(data["lon"]))
        except Exception:
            pass

    @pyqtSlot(str)
    def onFeatureClicked(self, json_str: str) -> None:  # noqa: N802
        """Called when a selectable vector feature is clicked on the map."""
        try:
            data = json.loads(json_str)
            self.feature_clicked.emit(data.get("overlay", ""), json_str)
        except Exception as exc:
            print(f"[MapBridge] onFeatureClicked parse error: {exc}")

    @pyqtSlot(str)
    def onMapZoom(self, zoom_str: str) -> None:  # noqa: N802
        """Called by Leaflet zoomend event with the new zoom level."""
        try:
            self.zoom_changed.emit(int(zoom_str))
        except ValueError:
            pass


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
# Sets up the QWebChannel bridge, overlay management, custom draw controls
# (no CDN dependency — pure Leaflet), programmatic markers/rectangles, and
# view helpers.
#
# Draw mode is stored in window._pendingDrawMode so that Python can call
# _setDrawMode() before hookMap() has completed — the mode is applied once
# the map and toolbar are ready.
_BRIDGE_JS = """
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<script>
(function() {
    var bridge = null;
    var pendingCalls = [];

    function flushPending() {
        var calls = pendingCalls.splice(0);
        calls.forEach(function(fn) { fn(); });
    }

    new QWebChannel(qt.webChannelTransport, function(channel) {
        bridge = channel.objects.bridge;
        flushPending();
    });

    function sendOrQueue(fn) {
        if (bridge) { fn(); } else { pendingCalls.push(fn); }
    }

    // ── Early stubs — defined NOW so Python can call them before hookMap runs ──
    // Calls made before the map is ready are queued and replayed in hookMap.
    window._pendingDrawMode  = 'none';
    window._preHookQueue     = [];   // [{fn, args}] replayed after hookMap

    function _enqueue(name, args) { window._preHookQueue.push({fn: name, args: args}); }

    window._setDrawMode = function(mode) {
        window._pendingDrawMode = mode;
        var rb = document.getElementById('_ptk_draw_rect_btn');
        var mb = document.getElementById('_ptk_draw_marker_btn');
        if (!rb && !mb) return;  // toolbar not ready yet; hookMap will apply mode
        rb.style.display = (mode === 'rectangle' || mode === 'both') ? '' : 'none';
        mb.style.display = (mode === 'marker'    || mode === 'both') ? '' : 'none';
        if (mode === 'none' && window._pytopkapi_map) {
            window._pytopkapi_map.getContainer().style.cursor = '';
        }
    };

    // Overlay stubs — queue until hookMap defines the real functions
    window._addRasterOverlay  = function(n,b,bo,o,bm)  { _enqueue('_addRasterOverlay', [n,b,bo,o,bm]); };
    window._addVectorOverlay  = function(n,g,c,w,f,wc,s){ _enqueue('_addVectorOverlay',[n,g,c,w,f,wc,s]); };
    window._setOverlayOpacity = function(n,o)           { _enqueue('_setOverlayOpacity',[n,o]); };
    window._toggleOverlay     = function(n,v)           { _enqueue('_toggleOverlay',   [n,v]); };
    window._removeOverlay     = function(n)             { _enqueue('_removeOverlay',   [n]); };
    window._toggleBaseMap     = function(v)             { _enqueue('_toggleBaseMap',   [v]); };
    window._clearAllOverlays  = function()              { _enqueue('_clearAllOverlays',[]); };
    window._setView           = function(la,lo,z)       { _enqueue('_setView',         [la,lo,z]); };
    window._fitBounds         = function(s,w,n,e,p)     { _enqueue('_fitBounds',       [s,w,n,e,p]); };
    window._addRectangleItem  = function(s,w,n,e,c)     { _enqueue('_addRectangleItem',[s,w,n,e,c]); };
    window._addMarkerItem     = function(la,lo,t,c)     { _enqueue('_addMarkerItem',   [la,lo,t,c]); };
    window._clearRectangles   = function()              { _enqueue('_clearRectangles', []); };
    window._clearMarkers      = function()              { _enqueue('_clearMarkers',    []); };

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
        if (!m) { setTimeout(hookMap, 100); return; }

        window._pytopkapi_map = m;

        // ── Named overlay store ──────────────────────────────────────────
        window._overlays = {};

        window._baseTileLayer = null;
        m.eachLayer(function(layer) {
            if (!window._baseTileLayer && layer._url && layer._url.indexOf('{z}') !== -1) {
                window._baseTileLayer = layer;
            }
        });

        // ── Multi-selected basin state ───────────────────────────────────
        // Dict keyed by stable feature id → {flayer, feature}
        window._selectedBasins = {};

        window._addRasterOverlay = function(name, base64png, bounds, opacity, blendMode) {
            if (window._overlays[name]) m.removeLayer(window._overlays[name]);
            var url = 'data:image/png;base64,' + base64png;
            var layer = L.imageOverlay(url, bounds, {opacity: opacity || 0.7, className: '_ptk_overlay'});
            layer.addTo(m);
            // Apply CSS blend mode (e.g. 'multiply' for hillshade)
            if (blendMode && blendMode !== 'normal') {
                var el = layer.getElement();
                if (el) { el.style.mixBlendMode = blendMode; }
                else {
                    layer.once('add', function() {
                        var e = layer.getElement();
                        if (e) e.style.mixBlendMode = blendMode;
                    });
                }
            }
            window._overlays[name] = layer;
        };

        // selectable=true → clicking a feature sends it back to Python
        window._addVectorOverlay = function(name, geojsonStr, color, weight, fillOpacity, weightColumn, selectable) {
            if (window._overlays[name]) m.removeLayer(window._overlays[name]);
            var data = JSON.parse(geojsonStr);
            var normalStyle = function(feature) {
                var w = weight || 2;
                var c = color || '#FF6B35';
                if (weightColumn && feature.properties && feature.properties[weightColumn]) {
                    var order = parseFloat(feature.properties[weightColumn]) || 1;
                    w = Math.max(0.5, order * (weight || 0.8));
                }
                return {color: c, weight: w, fillColor: c, fillOpacity: fillOpacity || 0.15,
                        lineCap: 'round', lineJoin: 'round'};
            };
            var layer = L.geoJSON(data, {
                style: normalStyle,
                onEachFeature: selectable ? function(feature, flayer) {
                    // Stable feature id for multi-select tracking
                    var fid = (feature.properties &&
                               (feature.properties.cat ||
                                feature.properties.value ||
                                feature.properties.id)) ||
                               JSON.stringify(feature.geometry).slice(0, 80);

                    flayer.on('click', function(e) {
                        L.DomEvent.stopPropagation(e);
                        var isSelected = !!window._selectedBasins[fid];
                        if (isSelected) {
                            // Deselect — restore normal style
                            window._overlays[name] && window._overlays[name].resetStyle(flayer);
                            delete window._selectedBasins[fid];
                        } else {
                            // Select — highlight gold
                            flayer.setStyle({
                                color: '#FFD700', weight: 3,
                                fillColor: '#FFD700', fillOpacity: 0.45
                            });
                            window._selectedBasins[fid] = {flayer: flayer, feature: feature};
                        }
                        // Send toggle event to Python
                        var payload = JSON.stringify({
                            overlay: name,
                            feature: JSON.stringify(feature),
                            selected: !isSelected
                        });
                        sendOrQueue(function() { bridge.onFeatureClicked(payload); });
                    });
                    flayer.on('mouseover', function() {
                        if (!window._selectedBasins[fid]) {
                            flayer.setStyle({fillOpacity: (fillOpacity || 0.15) + 0.2, weight: (weight||2)+1});
                        }
                    });
                    flayer.on('mouseout', function() {
                        if (!window._selectedBasins[fid]) {
                            window._overlays[name] && window._overlays[name].resetStyle(flayer);
                        }
                    });
                } : null
            });
            layer.addTo(m);
            window._overlays[name] = layer;
        };

        window._setOverlayOpacity = function(name, opacity) {
            var layer = window._overlays[name];
            if (!layer) return;
            if (layer.setOpacity) layer.setOpacity(opacity);
            else if (layer.setStyle) layer.setStyle({opacity: opacity, fillOpacity: opacity * 0.3});
        };

        window._toggleOverlay = function(name, visible) {
            var layer = window._overlays[name];
            if (!layer) return;
            if (visible) m.addLayer(layer); else m.removeLayer(layer);
        };

        window._removeOverlay = function(name) {
            var layer = window._overlays[name];
            if (layer) { m.removeLayer(layer); delete window._overlays[name]; }
        };

        window._toggleBaseMap = function(visible) {
            if (!window._baseTileLayer) return;
            if (visible) m.addLayer(window._baseTileLayer);
            else m.removeLayer(window._baseTileLayer);
        };

        // ── Programmatic markers & rectangles ────────────────────────────
        window._progMarkers    = [];
        window._progRectangles = [];

        window._addMarkerItem = function(lat, lon, tooltip, color) {
            var c = color || '#e74c3c';
            var html = '<div style="background:'+c+';width:14px;height:14px;'
                + 'border-radius:50%;border:2px solid #fff;'
                + 'box-shadow:0 1px 3px rgba(0,0,0,.5);"></div>';
            var icon = L.divIcon({html: html, className: '', iconSize: [18,18], iconAnchor: [9,9]});
            var mk = L.marker([lat, lon], {icon: icon});
            if (tooltip) mk.bindTooltip(tooltip);
            mk.addTo(m);
            window._progMarkers.push(mk);
        };

        window._clearMarkers = function() {
            window._progMarkers.forEach(function(mk) { m.removeLayer(mk); });
            window._progMarkers = [];
        };

        window._addRectangleItem = function(south, west, north, east, color) {
            var rect = L.rectangle([[south, west], [north, east]], {
                color: color || '#1a6fc4', weight: 2, fill: true, fillOpacity: 0.15,
                interactive: false
            });
            rect.addTo(m);
            window._progRectangles.push(rect);
        };

        window._clearRectangles = function() {
            window._progRectangles.forEach(function(r) { m.removeLayer(r); });
            window._progRectangles = [];
        };

        window._clearBasinSelection = function() {
            window._selectedBasins = {};
        };

        window._clearAllOverlays = function() {
            for (var name in window._overlays) {
                m.removeLayer(window._overlays[name]);
            }
            window._overlays = {};
            window._selectedBasins = {};
            window._clearMarkers();
            window._clearRectangles();
        };

        // ── Zoom event → Python ──────────────────────────────────────────
        m.on('zoomend', function() {
            sendOrQueue(function() { bridge.onMapZoom(String(m.getZoom())); });
        });

        // ── View helpers ─────────────────────────────────────────────────
        window._setView = function(lat, lon, zoom) {
            m.setView([lat, lon], zoom);
        };

        window._fitBounds = function(south, west, north, east, padding) {
            m.fitBounds([[south, west], [north, east]], {padding: [padding||20, padding||20]});
        };

        // ── Mouse-coordinate forwarding ───────────────────────────────────
        var _lastMove = 0;
        m.on('mousemove', function(e) {
            var now = Date.now();
            if (now - _lastMove < 100) return;
            _lastMove = now;
            if (bridge) bridge.onMouseMove(JSON.stringify({lat: e.latlng.lat, lon: e.latlng.lng}));
        });

        // ── Custom draw toolbar (no CDN / Leaflet.Draw dependency) ────────
        // A minimal control with rectangle and marker buttons, drawn using
        // native Leaflet mouse events so there's no external library needed.

        var _drawingRect   = false;
        var _drawStartLL   = null;
        var _drawTempLayer = null;

        function _finishDraw() {
            _drawingRect = false;
            _drawStartLL = null;
            m.getContainer().style.cursor = '';
            m.dragging.enable();
            m.off('mousemove', _onRectMove);
            m.off('mouseup',   _onRectUp);
        }

        function _onRectMove(e) {
            if (!_drawStartLL) return;
            if (_drawTempLayer) m.removeLayer(_drawTempLayer);
            _drawTempLayer = L.rectangle([_drawStartLL, e.latlng], {
                color: '#1a6fc4', weight: 2, fillOpacity: 0.15, interactive: false
            }).addTo(m);
        }

        function _onRectUp(e) {
            m.off('mousemove', _onRectMove);
            m.off('mouseup',   _onRectUp);
            _drawingRect = false;
            m.getContainer().style.cursor = 'crosshair';
            m.dragging.enable();

            if (!_drawTempLayer) return;
            var layer = _drawTempLayer;
            _drawTempLayer = null;

            // Replace old drawn rectangle
            window._progRectangles.forEach(function(r) { m.removeLayer(r); });
            window._progRectangles = [layer];

            var b = layer.getBounds();
            if (Math.abs(b.getNorth() - b.getSouth()) < 0.0001 ||
                Math.abs(b.getEast()  - b.getWest())  < 0.0001) {
                // Too small — ignore
                m.removeLayer(layer);
                window._progRectangles = [];
                return;
            }

            var payload = JSON.stringify({
                south: b.getSouth(), north: b.getNorth(),
                west:  b.getWest(),  east:  b.getEast()
            });
            sendOrQueue(function() { bridge.onBboxDrawn(payload); });
        }

        function _startRectDraw() {
            _drawingRect = true;
            m.getContainer().style.cursor = 'crosshair';
        }

        function _startMarkerPlace() {
            m.getContainer().style.cursor = 'crosshair';
            m.once('click', function(e) {
                m.getContainer().style.cursor = '';
                window._progMarkers.forEach(function(mk) { m.removeLayer(mk); });
                window._progMarkers = [];
                var c = '#e74c3c';
                var html = '<div style="background:'+c+';width:14px;height:14px;'
                    + 'border-radius:50%;border:2px solid #fff;'
                    + 'box-shadow:0 1px 3px rgba(0,0,0,.5);"></div>';
                var icon = L.divIcon({html: html, className: '', iconSize: [18,18], iconAnchor: [9,9]});
                var mk = L.marker(e.latlng, {icon: icon}).addTo(m);
                window._progMarkers.push(mk);
                var payload = JSON.stringify({lat: e.latlng.lat, lon: e.latlng.lng});
                sendOrQueue(function() { bridge.onOutletPlaced(payload); });
            });
        }

        // Map-level mousedown: start rectangle when in rect mode
        m.on('mousedown', function(e) {
            if (!_drawingRect) return;
            if (e.originalEvent.button !== 0) return;  // left button only
            m.dragging.disable();
            _drawStartLL = e.latlng;
            if (_drawTempLayer) { m.removeLayer(_drawTempLayer); _drawTempLayer = null; }
            m.on('mousemove', _onRectMove);
            m.on('mouseup',   _onRectUp);
        });

        // ── Custom toolbar control ────────────────────────────────────────
        var DrawToolbar = L.Control.extend({
            options: {position: 'topleft'},
            onAdd: function() {
                var bar = L.DomUtil.create('div', 'leaflet-bar leaflet-control');
                bar.style.background = 'transparent';
                bar.style.border = 'none';
                bar.style.boxShadow = 'none';

                function makeBtn(id, title, svg) {
                    var a = L.DomUtil.create('a', '', bar);
                    a.id = id;
                    a.href = '#';
                    a.title = title;
                    a.style.cssText = 'display:none;width:30px;height:30px;'
                        + 'line-height:30px;text-align:center;font-size:16px;'
                        + 'background:#1e2227;color:#ccc;border:1px solid #444;'
                        + 'border-radius:4px;margin-bottom:2px;cursor:pointer;'
                        + 'text-decoration:none;';
                    a.innerHTML = svg;
                    L.DomEvent.disableClickPropagation(a);
                    return a;
                }

                var rectBtn = makeBtn('_ptk_draw_rect_btn', 'Draw AOI rectangle',
                    '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"'
                    + ' xmlns="http://www.w3.org/2000/svg" style="vertical-align:middle">'
                    + '<rect x="2" y="4" width="12" height="8" rx="1"'
                    + ' stroke="#4FC3F7" stroke-width="1.5" fill="none"/>'
                    + '<circle cx="2" cy="4" r="1.5" fill="#4FC3F7"/>'
                    + '<circle cx="14" cy="4" r="1.5" fill="#4FC3F7"/>'
                    + '<circle cx="2" cy="12" r="1.5" fill="#4FC3F7"/>'
                    + '<circle cx="14" cy="12" r="1.5" fill="#4FC3F7"/>'
                    + '</svg>');

                var markerBtn = makeBtn('_ptk_draw_marker_btn', 'Place outlet marker',
                    '<svg width="14" height="18" viewBox="0 0 14 18" fill="none"'
                    + ' xmlns="http://www.w3.org/2000/svg" style="vertical-align:middle">'
                    + '<path d="M7 0C3.13 0 0 3.13 0 7c0 5.25 7 11 7 11s7-5.75 7-11c0-3.87-3.13-7-7-7z"'
                    + ' fill="#e74c3c"/>'
                    + '<circle cx="7" cy="7" r="2.5" fill="#fff"/>'
                    + '</svg>');

                L.DomEvent.on(rectBtn, 'click', function(e) {
                    L.DomEvent.stop(e);
                    if (_drawingRect) {
                        // Deactivate drawing mode
                        if (_drawTempLayer) { m.removeLayer(_drawTempLayer); _drawTempLayer = null; }
                        _finishDraw();
                        rectBtn.style.background = '#1e2227';
                    } else {
                        _startRectDraw();
                        rectBtn.style.background = '#2a3240';
                    }
                });

                L.DomEvent.on(markerBtn, 'click', function(e) {
                    L.DomEvent.stop(e);
                    _startMarkerPlace();
                });

                return bar;
            }
        });
        new DrawToolbar().addTo(m);

        // ── Flush calls that were made before hookMap completed ───────────
        var queue = window._preHookQueue.splice(0);
        queue.forEach(function(call) {
            var f = window[call.fn];
            if (typeof f === 'function') f.apply(window, call.args);
        });

        // Apply the draw mode that was requested before hookMap ran
        window._setDrawMode(window._pendingDrawMode || 'none');
    }

    if (document.readyState === 'complete') {
        hookMap();
    } else {
        window.addEventListener('load', hookMap);
    }
})();
</script>
"""


def raster_to_base64(path: str, cmap: str = "terrain",
                     alpha: float = 0.7,
                     max_dim: int = 1024,
                     hillshade: bool = False,
                     clip_bounds: tuple | None = None,
                     log_scale: bool = False,
                     vmin: float | None = None,
                     vmax: float | None = None) -> tuple[str, list]:
    """Convert a GeoTIFF to a base64-encoded RGBA PNG + WGS84 bounds.

    Returns (base64_string, [[south, west], [north, east]]).
    Downsamples to max_dim pixels on the longest axis for performance.

    Multi-band (RGB/RGBA) rasters are rendered directly without applying a
    colormap — this handles GRASS r.shade shaded-relief exports correctly.
    Single-band rasters use the supplied matplotlib colormap.

    hillshade=True: renders as an opaque greyscale PNG across the full [0, 1]
    range, intended for CSS mix-blend-mode:multiply over satellite imagery.
    Dark pixels (shadows) darken the satellite; white (fully lit) leaves it
    unchanged.  Pixels with value <= 0 (ocean/edge) are set transparent.

    clip_bounds: optional (south, west, north, east) in WGS84 to crop the
    raster before warping.  When supplied, max_dim is doubled (2048) so the
    visible AOI renders at higher resolution.

    log_scale: apply np.log1p() to single-band data before normalising.
    Use for flow accumulation rasters which span many orders of magnitude.

    vmin / vmax: explicit colour stretch limits for single-band rasters.
    If only one is given the other falls back to the 2% or 98% percentile.
    Both None → automatic 2%–98% percentile stretch (QGIS default).
    vmin/vmax are applied *after* log_scale, so supply log1p-transformed
    values when log_scale=True.
    """
    import base64
    import io

    import numpy as np
    import rasterio
    from pyproj import Transformer

    from rasterio.warp import reproject as _reproject, Resampling, calculate_default_transform

    dst_crs = "EPSG:4326"

    # Boost resolution when cropping to AOI
    if clip_bounds is not None:
        max_dim = max(max_dim, 2048)

    with rasterio.open(path) as src:
        src_crs   = src.crs
        n_bands   = src.count
        nodata    = src.nodata

        # Determine the read window (crop to AOI if clip_bounds supplied)
        if clip_bounds is not None:
            cb_south, cb_west, cb_north, cb_east = clip_bounds
            tf_to_native = Transformer.from_crs("EPSG:4326", src_crs, always_xy=True)
            nx0, ny0 = tf_to_native.transform(cb_west, cb_south)
            nx1, ny1 = tf_to_native.transform(cb_east, cb_north)
            n_left, n_right  = min(nx0, nx1), max(nx0, nx1)
            n_bottom, n_top  = min(ny0, ny1), max(ny0, ny1)
            # Intersect with actual raster extent
            from rasterio.windows import from_bounds as _win_from_bounds
            rl, rb, rr, rt = src.bounds
            w_left   = max(n_left,   rl)
            w_right  = min(n_right,  rr)
            w_bottom = max(n_bottom, rb)
            w_top    = min(n_top,    rt)
            if w_left >= w_right or w_bottom >= w_top:
                # Clip region doesn't overlap raster — fall back to full extent
                read_window  = None
                read_transform = src.transform
                read_w, read_h = src.width, src.height
            else:
                read_window    = _win_from_bounds(w_left, w_bottom, w_right, w_top, src.transform)
                read_transform = src.window_transform(read_window)
                read_w = max(1, int(read_window.width))
                read_h = max(1, int(read_window.height))
        else:
            read_window    = None
            read_transform = src.transform
            read_w, read_h = src.width, src.height

        # Compute WGS84 transform + natural output size, then scale to max_dim
        # Derive bounds from the read transform + dimensions
        rt_left   = read_transform.c
        rt_top    = read_transform.f
        rt_right  = rt_left + read_transform.a * read_w
        rt_bottom = rt_top  + read_transform.e * read_h
        rt_left, rt_right   = min(rt_left, rt_right),   max(rt_left, rt_right)
        rt_bottom, rt_top   = min(rt_bottom, rt_top),   max(rt_bottom, rt_top)
        dst_tf, nat_w, nat_h = calculate_default_transform(
            src_crs, dst_crs, read_w, read_h,
            rt_left, rt_bottom, rt_right, rt_top
        )
        scale = min(1.0, max_dim / max(nat_h, nat_w))
        out_h = max(1, int(nat_h * scale))
        out_w = max(1, int(nat_w * scale))

        # Rescale the affine transform to the downsampled output size
        from rasterio.transform import Affine
        dst_tf_scaled = Affine(
            dst_tf.a * (nat_w / out_w),
            dst_tf.b,
            dst_tf.c,
            dst_tf.d,
            dst_tf.e * (nat_h / out_h),
            dst_tf.f,
        )

        # Derive WGS84 bounds from the scaled output transform
        west  = dst_tf_scaled.c
        north = dst_tf_scaled.f
        east  = west  + dst_tf_scaled.a * out_w
        south = north + dst_tf_scaled.e * out_h

        def _warp_band(band_idx: int) -> np.ndarray:
            """Reproject one band to WGS84 at downsampled resolution."""
            src_data = src.read(band_idx, window=read_window)
            dst_data = np.zeros((out_h, out_w), dtype=src_data.dtype)
            _reproject(
                source=src_data,
                destination=dst_data,
                src_transform=read_transform,
                src_crs=src_crs,
                dst_transform=dst_tf_scaled,
                dst_crs=dst_crs,
                src_nodata=nodata,
                resampling=Resampling.lanczos,
            )
            return dst_data

        if n_bands >= 3:
            # Multi-band (RGB) — warp and render directly.
            # Use 2% percentile clip per channel to avoid outlier pixels
            # skewing the stretch (matches QGIS default behaviour).
            r = _warp_band(1).astype("float64")
            g = _warp_band(2).astype("float64")
            b = _warp_band(3).astype("float64")

            def _to_uint8(arr):
                finite = arr[np.isfinite(arr)]
                if finite.size == 0:
                    return np.zeros_like(arr, dtype=np.uint8)
                if arr.max() <= 255 and arr.min() >= 0:
                    # Already in byte range (GRASS r.shade output)
                    return np.clip(arr, 0, 255).astype(np.uint8)
                p2, p98 = np.nanpercentile(finite, [2, 98])
                stretched = np.clip((arr - p2) / max(p98 - p2, 1e-6), 0, 1) * 255
                return stretched.astype(np.uint8)

            r8, g8, b8 = _to_uint8(r), _to_uint8(g), _to_uint8(b)
            a8 = np.full((out_h, out_w), int(alpha * 255), dtype=np.uint8)
            black = (r8 == 0) & (g8 == 0) & (b8 == 0)
            a8[black] = 0
            rgba_bytes = np.stack([r8, g8, b8, a8], axis=2)

        else:
            data = _warp_band(1).astype("float64")
            nodata_val = nodata if nodata is not None else None

            if nodata_val is not None:
                mask = np.isclose(data, nodata_val) | np.isnan(data)
            else:
                mask = np.isnan(data)

            if hillshade:
                # Opaque greyscale for CSS multiply blend.
                # Full [0, 1] range — shadows are genuinely dark, lit areas
                # are white. Pixels ≤ 0 are transparent (ocean / nodata edge).
                transparent = mask | (data <= 0)
                clipped = np.clip(data, 0, 255)
                grey = clipped / 255.0
                g8 = (grey * 255).astype(np.uint8)
                a8 = np.where(transparent, 0, 255).astype(np.uint8)
                rgba_bytes = np.stack([g8, g8, g8, a8], axis=2)
            else:
                import matplotlib.cm as mcm
                valid = data[~mask]
                if valid.size == 0:
                    rgba_bytes = np.zeros((out_h, out_w, 4), dtype=np.uint8)
                else:
                    # Log-scale for data spanning many orders of magnitude
                    # (e.g. flow accumulation). Apply before percentile stretch.
                    if log_scale:
                        data = np.where(mask, np.nan, np.log1p(np.maximum(data, 0)))
                        valid = data[~mask]
                    # Colour stretch: user vmin/vmax take priority; fall back to
                    # 2% percentile clip per channel (QGIS standard).
                    if vmin is not None and vmax is not None:
                        lo, hi = float(vmin), float(vmax)
                    elif vmin is not None:
                        lo = float(vmin)
                        hi = float(np.nanpercentile(valid, 98))
                    elif vmax is not None:
                        lo = float(np.nanpercentile(valid, 2))
                        hi = float(vmax)
                    else:
                        lo, hi = np.nanpercentile(valid, [2, 98])
                    normed = np.clip((data - lo) / max(hi - lo, 1e-6), 0, 1)
                    rgba = mcm.get_cmap(cmap)(normed)
                    rgba[mask]    = [0, 0, 0, 0]
                    rgba[~mask, 3] = alpha
                    rgba_bytes = (rgba * 255).astype(np.uint8)

    from PIL import Image
    img = Image.fromarray(rgba_bytes, "RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=6)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    return b64, [[south, west], [north, east]]


def dem_to_contours_geojson(path: str,
                            interval: float = 20.0,
                            clip_bounds: tuple | None = None,
                            max_dim: int = 512) -> str:
    """Convert a DEM GeoTIFF to a GeoJSON FeatureCollection of contour lines.

    Args:
        path:        GeoTIFF DEM path.
        interval:    Contour interval in the DEM's vertical units (metres).
        clip_bounds: Optional (south, west, north, east) in WGS84 to crop the
                     DEM before contouring.  Faster and avoids off-AOI noise.
        max_dim:     Max pixel dimension for the intermediate warp.

    Returns:
        GeoJSON string — FeatureCollection of LineString features, each with
        an ``elevation`` property.  Returns an empty FeatureCollection on error.
    """
    import json
    import numpy as np
    import rasterio
    from rasterio.warp import reproject as _reproject, Resampling, calculate_default_transform
    from rasterio.transform import Affine
    from pyproj import Transformer

    _EMPTY = json.dumps({"type": "FeatureCollection", "features": []})

    try:
        dst_crs = "EPSG:4326"

        with rasterio.open(path) as src:
            src_crs = src.crs
            nodata  = src.nodata

            # Crop window
            if clip_bounds is not None:
                cb_south, cb_west, cb_north, cb_east = clip_bounds
                tf_to_native = Transformer.from_crs("EPSG:4326", src_crs, always_xy=True)
                nx0, ny0 = tf_to_native.transform(cb_west, cb_south)
                nx1, ny1 = tf_to_native.transform(cb_east, cb_north)
                from rasterio.windows import from_bounds as _win_from_bounds
                rl, rb, rr, rt = src.bounds
                wl = max(min(nx0, nx1), rl); wr = min(max(nx0, nx1), rr)
                wb = max(min(ny0, ny1), rb); wt = min(max(ny0, ny1), rt)
                if wl < wr and wb < wt:
                    read_window    = _win_from_bounds(wl, wb, wr, wt, src.transform)
                    read_transform = src.window_transform(read_window)
                    read_w = max(1, int(read_window.width))
                    read_h = max(1, int(read_window.height))
                else:
                    read_window = None
                    read_transform = src.transform
                    read_w, read_h = src.width, src.height
            else:
                read_window = None
                read_transform = src.transform
                read_w, read_h = src.width, src.height

            rt_left   = read_transform.c
            rt_top    = read_transform.f
            rt_right  = rt_left + read_transform.a * read_w
            rt_bottom = rt_top  + read_transform.e * read_h
            rt_left, rt_right   = min(rt_left, rt_right),   max(rt_left, rt_right)
            rt_bottom, rt_top   = min(rt_bottom, rt_top),   max(rt_bottom, rt_top)
            dst_tf, nat_w, nat_h = calculate_default_transform(
                src_crs, dst_crs, read_w, read_h,
                rt_left, rt_bottom, rt_right, rt_top
            )
            scale = min(1.0, max_dim / max(nat_h, nat_w))
            out_h = max(1, int(nat_h * scale))
            out_w = max(1, int(nat_w * scale))

            dst_tf_scaled = Affine(
                dst_tf.a * (nat_w / out_w), dst_tf.b, dst_tf.c,
                dst_tf.d, dst_tf.e * (nat_h / out_h), dst_tf.f,
            )

            wgs_west  = dst_tf_scaled.c
            wgs_north = dst_tf_scaled.f
            wgs_east  = wgs_west  + dst_tf_scaled.a * out_w
            wgs_south = wgs_north + dst_tf_scaled.e * out_h

            src_data = src.read(1, window=read_window).astype("float64")
            dst_data = np.zeros((out_h, out_w), dtype="float64")
            _reproject(
                source=src_data, destination=dst_data,
                src_transform=read_transform, src_crs=src_crs,
                dst_transform=dst_tf_scaled, dst_crs=dst_crs,
                src_nodata=nodata, resampling=Resampling.bilinear,
            )

        # Mask nodata / zero-pixels
        if nodata is not None:
            dst_data[np.isclose(dst_data, nodata)] = np.nan
        dst_data[dst_data == 0] = np.nan

        valid = dst_data[np.isfinite(dst_data)]
        if valid.size == 0:
            return _EMPTY

        elev_min = np.floor(valid.min() / interval) * interval
        elev_max = np.ceil(valid.max()  / interval) * interval
        levels = np.arange(elev_min, elev_max + interval, interval)
        if len(levels) < 2:
            return _EMPTY

        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(out_w / 100, out_h / 100), dpi=100)
        cs = ax.contour(dst_data, levels=levels)
        plt.close(fig)

        features = []
        lon_range = wgs_east - wgs_west
        lat_range = wgs_north - wgs_south  # positive (north > south)

        for i, level in enumerate(cs.levels):
            if i >= len(cs.allsegs):
                continue
            for seg in cs.allsegs[i]:
                if len(seg) < 2:
                    continue
                # seg[:,0] = x = column, seg[:,1] = y = row (matplotlib convention)
                lons = wgs_west  + (seg[:, 0] / out_w) * lon_range
                lats = wgs_north - (seg[:, 1] / out_h) * lat_range
                coords = [[float(lo), float(la)] for lo, la in zip(lons, lats)]
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": coords},
                    "properties": {"elevation": float(level)},
                })

        return json.dumps({"type": "FeatureCollection", "features": features})

    except Exception as exc:
        import traceback
        print(f"[dem_to_contours_geojson] {exc}\n{traceback.format_exc()}")
        return _EMPTY


class MapWidget(QWebEngineView):
    """Interactive Folium map widget with Python ↔ JavaScript bridge."""

    bbox_drawn      = pyqtSignal(dict)
    outlet_placed   = pyqtSignal(float, float)
    polygon_drawn   = pyqtSignal(dict)
    coord_moved     = pyqtSignal(float, float)
    feature_clicked = pyqtSignal(str, str)    # overlay_name, GeoJSON Feature string
    zoom_changed    = pyqtSignal(int)         # Leaflet zoom level

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
        self._bridge.polygon_drawn.connect(self.polygon_drawn)
        self._bridge.coord_moved.connect(self.coord_moved)
        self._bridge.feature_clicked.connect(self.feature_clicked)
        self._bridge.zoom_changed.connect(self.zoom_changed)

    # ── Public API ─────────────────────────────────────────────────────────────

    def load_map(self, html: str) -> None:
        """Inject CSS + QWebChannel bridge script and load the Folium HTML.

        QWebEngineView.setHtml() has a 2 MB limit. If the processed HTML
        exceeds that, write to a temp file and load via file URL instead.
        """
        processed = self._add_fullscreen_css(html)
        processed = self._inject_bridge(processed)

        size_bytes = len(processed.encode("utf-8"))
        size_kb = size_bytes / 1024
        # Log to the application log dock instead of stdout
        self._html_size_kb = size_kb
        if size_bytes > 2_000_000:
            import tempfile, os
            fd, path = tempfile.mkstemp(suffix=".html", prefix="pytopkapi_map_")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(processed)
            self.setUrl(QUrl.fromLocalFile(path))
        else:
            self.setHtml(processed, baseUrl=QUrl("qrc:///"))

    # ── Static map builders ────────────────────────────────────────────────────

    @staticmethod
    def build_base_map(
        centre: tuple = (-29.71, 31.06),
        zoom: int = 11,
    ) -> str:
        """Satellite base map for the persistent single-map view.

        Draw controls are created by _BRIDGE_JS using native Leaflet events
        (no CDN dependency). Call mv.set_draw_mode() to show/hide tools.
        """
        m = folium.Map(
            location=list(centre), zoom_start=zoom,
            prefer_canvas=True, tiles=False,
        )

        # Satellite basemap (default)
        folium.TileLayer(
            tiles=(
                "https://server.arcgisonline.com/ArcGIS/rest/services/"
                "World_Imagery/MapServer/tile/{z}/{y}/{x}"
            ),
            attr="Esri World Imagery",
            name="Satellite",
        ).add_to(m)

        return m.get_root().render()

    @staticmethod
    def build_aoi_map(
        centre: tuple = (-29.71, 31.06),
        zoom: int = 11,
        existing_bbox: dict | None = None,
    ) -> str:
        """Folium map with rectangle-draw enabled. Returns HTML string."""
        # tiles=False prevents default OSM; satellite is added explicitly as default
        m = folium.Map(location=list(centre), zoom_start=zoom,
                       prefer_canvas=True, tiles=False)

        # Satellite basemap (added first = shown by default)
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
        return m.get_root().render()

    @staticmethod
    def build_outlet_map(
        centre: tuple,
        zoom: int = 13,
        existing_outlet: tuple | None = None,
        catchment_geojson: dict | None = None,
        stream_geojson: dict | None = None,
    ) -> str:
        """Folium map with marker-draw enabled. Returns HTML string.

        Args:
            centre:           (lat, lon) map centre
            zoom:             initial zoom level
            existing_outlet:  (lat, lon) previously saved outlet — shown as red star
            catchment_geojson: delineated catchment boundary (green polygon)
            stream_geojson:   preview stream network derived from flow accumulation
                              (blue lines) — helps engineer snap outlet to stream
        """
        m = folium.Map(location=list(centre), zoom_start=zoom,
                       prefer_canvas=True, tiles=False)

        # Satellite basemap (default)
        folium.TileLayer(
            tiles=(
                "https://server.arcgisonline.com/ArcGIS/rest/services/"
                "World_Imagery/MapServer/tile/{z}/{y}/{x}"
            ),
            attr="Esri World Imagery",
            name="Satellite",
        ).add_to(m)

        # OpenStreetMap as optional toggle
        folium.TileLayer("OpenStreetMap", name="Streets").add_to(m)

        # Stream network preview — shown BEFORE catchment so it renders underneath
        if stream_geojson:
            folium.GeoJson(
                stream_geojson,
                name="Stream Network (preview)",
                style_function=lambda _: {
                    "color":       "#00BFFF",   # deep sky blue
                    "weight":      2,
                    "fillColor":   "#00BFFF",
                    "fillOpacity": 0.4,
                },
                tooltip="Stream network (flow accumulation threshold)",
            ).add_to(m)

        # Delineated catchment boundary
        if catchment_geojson:
            folium.GeoJson(
                catchment_geojson,
                name="Catchment boundary",
                style_function=lambda _: {
                    "color":       "#2ecc71",
                    "weight":      2,
                    "fillOpacity": 0.15,
                },
                tooltip="Catchment boundary",
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

        folium.LayerControl(collapsed=False).add_to(m)
        return m.get_root().render()

    @staticmethod
    def build_dem_map(
        centre: tuple = (-29.71, 31.06),
        zoom: int = 12,
        bbox: dict | None = None,
        overlays: list | None = None,
        subcatchments: list | None = None,
        allow_outlet_draw: bool = False,
    ) -> str:
        """Folium map for DEM processing: shapefile overlays + subcatchment polygons.

        Args:
            centre:             (lat, lon) map centre
            zoom:               initial zoom level
            bbox:               AOI extent dict {south, north, west, east} — drawn as blue rectangle
            overlays:           list of {"name": str, "geojson": str, "color": str}
            subcatchments:      list of {"geojson": str, "color": str, "label": str}
            allow_outlet_draw:  True → marker draw enabled (for subcatchment outlet placement)
        """
        m = folium.Map(location=list(centre), zoom_start=zoom,
                       prefer_canvas=True, tiles=False)

        # Satellite basemap (default)
        folium.TileLayer(
            tiles=(
                "https://server.arcgisonline.com/ArcGIS/rest/services/"
                "World_Imagery/MapServer/tile/{z}/{y}/{x}"
            ),
            attr="Esri World Imagery",
            name="Satellite",
        ).add_to(m)

        # AOI bounding-box rectangle
        if bbox:
            b = bbox
            folium.Rectangle(
                bounds=[[b["south"], b["west"]], [b["north"], b["east"]]],
                color="#1a6fc4",
                weight=2,
                fill=False,
                tooltip="Area of Interest",
                name="AOI",
            ).add_to(m)

        # Shapefile overlays
        _OVERLAY_COLORS = ["#FF6B35", "#004E89", "#1A936F", "#C6AD8F", "#8B1E3F"]
        for i, ov in enumerate(overlays or []):
            color = ov.get("color") or _OVERLAY_COLORS[i % len(_OVERLAY_COLORS)]
            geojson_data = ov["geojson"] if isinstance(ov["geojson"], dict) else \
                           __import__("json").loads(ov["geojson"])
            folium.GeoJson(
                geojson_data,
                name=ov.get("name", f"Layer {i+1}"),
                style_function=lambda _, c=color: {
                    "color": c,
                    "weight": 2,
                    "fillColor": c,
                    "fillOpacity": 0.15,
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=list(
                        (geojson_data.get("features") or [{}])[0]
                        .get("properties", {}).keys()
                    )[:3],
                    sticky=False,
                ) if geojson_data.get("features") else None,
            ).add_to(m)

        # Subcatchment polygons
        _SUB_COLORS = ["#00AA44", "#AA4400", "#0044AA", "#AA0044", "#44AA00"]
        for i, sub in enumerate(subcatchments or []):
            color = sub.get("color") or _SUB_COLORS[i % len(_SUB_COLORS)]
            geojson_data = sub["geojson"] if isinstance(sub["geojson"], dict) else \
                           __import__("json").loads(sub["geojson"])
            label = sub.get("label", f"Sub-{i+1}")
            folium.GeoJson(
                geojson_data,
                name=label,
                style_function=lambda _, c=color: {
                    "color": c,
                    "weight": 2,
                    "fillColor": c,
                    "fillOpacity": 0.25,
                },
                tooltip=label,
            ).add_to(m)

        # Draw plugin — marker only when capturing subcatchment outlets
        Draw(
            draw_options={
                "marker":       allow_outlet_draw,
                "rectangle":    False,
                "polyline":     False,
                "polygon":      False,
                "circle":       False,
                "circlemarker": False,
            },
            edit_options={"edit": False, "remove": False},
        ).add_to(m)

        folium.LayerControl(collapsed=False).add_to(m)
        return m.get_root().render()

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

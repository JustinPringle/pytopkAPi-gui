# Map Display Best Practices Research
### GIS Raster & Vector Rendering — GRASS / QGIS / SAGA Reference

*Research date: 2026-03-08*

---

## 1. Shaded Relief (Hillshade) Rendering

### Standard azimuth / altitude angles

| Tool | Default Azimuth | Default Altitude | Notes |
|------|----------------|-----------------|-------|
| GRASS `r.relief` | 270° (NW) | 30° | NW lighting is the cartographic convention |
| QGIS Hillshade | 315° (NW) | 45° | Slightly higher sun angle |
| SAGA GIS | 315° | 45° | Same as QGIS defaults |
| `gdaldem hillshade` | 315° | 45° | `gdaldem hillshade -az 315 -alt 45` |

The **NW convention (270–315°)** is universal. The human visual system interprets relief correctly only when light comes from upper-left. Light from the right causes "relief inversion" where hills look like valleys.

**Recommended production values:** azimuth=315°, altitude=45° for most terrains. Use altitude=30° for low-relief plains (more dramatic shadows); altitude=60° for high mountains (avoids over-darkening deep valleys).

### Vertical exaggeration (zscale) by terrain type

| Terrain Type | Recommended zscale | Notes |
|---|---|---|
| Mountain / Alpine | 1.0–1.5 | Already dramatic; no exaggeration needed |
| Hilly / Piedmont | 1.5–3.0 | Moderate exaggeration |
| Rolling plains | 3.0–6.0 | GRASS default of 3.0 targets this zone |
| Flat coastal / deltaic | 6.0–15.0 | Very flat terrain needs strong exaggeration |
| KwaZulu-Natal (this project) | 2.0–3.5 | Mixed escarpment / coastal; 3.0 is appropriate |

**How GRASS `r.relief zscale=` works:** multiplies elevation values by `zscale` before computing the gradient. Higher values make shallow gradients appear steeper, so fine terrain detail becomes visible.

### Multi-directional vs single-direction hillshade

| Approach | When to Use |
|---|---|
| Single direction (315°/45°) | General mapping — most situations |
| Multi-directional (ESRI MDH) | Low-relief terrain where single direction leaves N/S slopes under-lit |

Multi-directional method averages 6 azimuths at 60° intervals with a weighted formula. For KZN terrain a single 315°/45° hillshade is sufficient.

### Blending hillshade with hypsometric tinting

The universal cartographic technique is the **multiply blend mode**:

```
result_pixel = (hillshade_pixel / 255) × color_pixel
```

This darkens the coloured elevation layer in shadowed areas and preserves it where it is lit.

| Layer | Blend mode | Opacity |
|---|---|---|
| Hillshade (greyscale) | Multiply | 50–70% |
| Coloured DEM (hypsometric tint) | Normal | 100% |

QGIS default: hillshade layer on top at **60% multiply opacity**. Most published cartography uses 60% as a starting point.

### `r.shade` brighten parameter

`r.shade` composites a colour raster with a shade raster using:

```
output = color × (shade / 255) × (1 + brighten / 100)
```

| `brighten` value | Effect |
|---|---|
| 0 | Pure multiply blend — often too dark |
| 30 | Slightly lifted shadows — **GRASS recommended default** |
| 50 | Good for web display (compensates for monitor gamma) |
| 80 | Strong brightening — useful for flow accumulation where dark valleys need visibility |
| −20 | Moodier / darker — useful for print |

---

## 2. Colour Ramps for DEMs / Elevation

### Standard colour schemes

| Scheme | Best for | GRASS equivalent |
|---|---|---|
| Hypsometric tint (green → brown → white) | General topographic maps | `r.colors color=elevation` |
| SRTM-style (dark blue → green → tan → white) | DEM data as-is | `r.colors color=srtm` |
| Grey equalized | Hillshade background | `r.colors color=grey.eq` |
| Warm earth tones | General DEM display | `r.colors color=dem` |
| Viridis | Scientific, colorblind-safe | `r.colors color=viridis` |
| Terrain (matplotlib) | General purpose Python | `matplotlib.cm.terrain` |

**For this project:** `r.colors color=elevation` with `flags=e` (histogram-equalised) produces the classic cartographic green-lowlands → tan-highlands → white-peaks scheme and is the right choice for the hypsometric base layer under a hillshade.

### Contrast enhancement: min-max vs 2% clip vs std dev

| Method | Description | When to use |
|---|---|---|
| Min-max stretch | Maps [data_min, data_max] → [0, 255] | Only when no outliers exist |
| **2% clip** (percentile stretch) | Maps [p2, p98] → [0, 255] | **Standard for remote sensing** — eliminates outlier pixels |
| Std dev stretch | Maps [mean − 2σ, mean + 2σ] → [0, 255] | Similar to 2% clip; QGIS default |

**Recommendation:** always use **2% percentile clip** for all raster exports:

```python
p2, p98 = np.nanpercentile(valid_data, [2, 98])
stretched = np.clip((data - p2) / max(p98 - p2, 1e-6), 0, 1)
```

**Exception — elevation:** use exact min/max to preserve relative heights across the project extent.

---

## 3. Flow Accumulation Display

### Why log scale is essential

Flow accumulation values span many orders of magnitude (1 cell → millions of cells). A linear colour ramp produces a map that appears nearly uniform — only the largest river shows colour. **Log scaling is universal practice:**

```python
log_accum = np.log1p(accumulation)   # log1p safely handles zero cells
p2, p98 = np.nanpercentile(log_accum[log_accum > 0], [2, 98])
```

In GRASS:
```bash
r.colors map=flow_accumulation color=water   # log-scaled blues by default
```

### Recommended colour ramps

| Ramp | Description |
|---|---|
| `water` (GRASS) | Light → dark blue; log-scaled by default |
| `blues` (GRASS/matplotlib) | Sequential blue, good for scientific display |
| matplotlib `Blues` | Good for Python PNG export |

### Hillshade + accumulation overlay

**GRASS approach (already in StreamWorker):**
```bash
r.shade shade=relief color=flow_accumulation output=shaded_accumulation brighten=80
```
`brighten=80` is correct here — accumulation maps are inherently dark and need lifting.

**Python numpy approach:**
```python
hillshade_norm = hillshade_array / 255.0
colored = plt.cm.Blues(log_accum_norm)[:, :, :3]
composited = (colored * hillshade_norm[:, :, np.newaxis]).clip(0, 1)
```

---

## 4. Stream Network / Vector Display

### Strahler order line width conventions

There is no single universal standard. Common cartographic practice:

| Strahler Order | QGIS / ArcGIS typical (px) | GRASS d.vect width factor |
|---|---|---|
| 1 | 0.3–0.5 | 1 |
| 2 | 0.5–0.8 | 1.5 |
| 3 | 0.8–1.2 | 2 |
| 4 | 1.2–2.0 | 3 |
| 5 | 2.0–3.0 | 4 |
| 6 | 3.0–4.5 | 6 |
| 7+ | 4.5–6.0 | 8 |

**Recommended formula** (implemented in this app): `width = max(0.8, order × 0.8)` px in Leaflet JS:

```javascript
w = Math.max(0.8, order * 0.8);
// order 1 → 0.8px,  order 3 → 2.4px,  order 5 → 4.0px,  order 7 → 5.6px
```

### Colour conventions for streams

| Style | Hex | Notes |
|---|---|---|
| Standard cartographic blue | `#1565C0` | Used in this app — correct |
| QGIS default | `#4169E1` | Slightly lighter |
| NHD (US National Hydrography) | `#4B75C8` | Similar |
| Dark cartographic (print) | `#0D47A1` | Navy |

For Strahler-coloured maps (different colour per order), use a sequential blue ramp:
```python
colors = plt.cm.Blues(np.linspace(0.3, 1.0, max_order))
# light blue for order 1 → dark navy for high-order rivers
```

### GRASS stream styling commands

```bash
# Line width scaled by Strahler order
d.vect map=streams type=line width_column=strahler width_scale=1.5 color=blue

# Colour by Strahler order
v.colors map=streams use=attr column=strahler color=water
d.vect map=streams type=line width_column=strahler color=none
```

---

## 5. Raster-to-Image Export for Web Display

### Resampling algorithm recommendations

| Algorithm | Use case | Quality | Speed |
|---|---|---|---|
| Nearest neighbour | Categorical rasters (land use, basins) | Preserves classes | Fastest |
| Bilinear | Continuous rasters — intermediate warps | Good | Fast |
| **Cubic** | High-quality DEM display | Better | Medium |
| **Lanczos** | **Final downsampling to PNG** | **Best** | Slower |

**Recommendation:** use **lanczos** for the final warp to PNG output. Bilinear is acceptable for intermediate reprojection steps where the output will be processed further.

### Resolution trade-off for Leaflet display

| Leaflet zoom level | Context | Recommended output |
|---|---|---|
| 8–10 | Whole country / large region | 512×512 px |
| 11–13 | Watershed scale | **1024×1024 px** (sweet spot) |
| 14–16 | Stream / sub-catchment detail | 1024–2048 px |

This app uses `max_dim=1024` (doubles to 2048 when `clip_bounds` is supplied). This is correct for watershed-scale work.

### PNG compression

PNG is lossless — compression only affects file size, not quality.

| `compress_level` | File size | Encode speed | Recommendation |
|---|---|---|---|
| 1 | Large | Very fast | Use when encoding repeatedly in a loop |
| **6** | Medium | Medium | **Default — correct balance** |
| 9 | Small | Slow | Only for archived output |

`optimize=True` (Pillow) performs full Huffman optimisation and is significantly slower. Use `compress_level=6` instead.

**Estimated base64 sizes at 1024×1024:**
- Hillshade (greyscale PNG): ~200–400 KB
- Coloured DEM (RGB PNG): ~400–800 KB
- Flow accumulation (Blues colormap): ~300–600 KB

---

## 6. Compositing Rasters

### Standard technique: multiply blend (QGIS / cartographic standard)

```
R_out = (R_hillshade / 255) × R_color
G_out = (G_hillshade / 255) × G_color
B_out = (B_hillshade / 255) × B_color
```

Pure white hillshade (255, 255, 255) leaves the colour unchanged. Pure black (0, 0, 0) produces black. This modulates the coloured layer's brightness with the hillshade.

**QGIS default:** hillshade at 60% multiply opacity over hypsometric tint.

### Python-side composite (numpy)

```python
import numpy as np
import matplotlib.pyplot as plt

def composite_hillshade_over_dem(elevation, hillshade, cmap='terrain',
                                  hillshade_weight=0.6, vmin=None, vmax=None):
    """Returns RGBA uint8 array. hillshade_weight=0.6 matches QGIS default."""
    if vmin is None: vmin = np.nanpercentile(elevation, 2)
    if vmax is None: vmax = np.nanpercentile(elevation, 98)
    elev_norm  = np.clip((elevation - vmin) / max(vmax - vmin, 1e-6), 0, 1)
    colored    = plt.get_cmap(cmap)(elev_norm)[:, :, :3]          # RGB float [0,1]
    shade_norm = hillshade.astype(float) / 255.0
    # Lerp between colored and (colored × shade); weight controls blend strength
    blended = colored * (1 - hillshade_weight + hillshade_weight * shade_norm[:, :, np.newaxis])
    nodata_mask = np.isnan(elevation)
    alpha = (~nodata_mask).astype(float)
    rgba = np.dstack([
        (blended[:, :, 0] * 255).clip(0, 255).astype(np.uint8),
        (blended[:, :, 1] * 255).clip(0, 255).astype(np.uint8),
        (blended[:, :, 2] * 255).clip(0, 255).astype(np.uint8),
        (alpha * 255).astype(np.uint8),
    ])
    return rgba
```

### What GRASS `r.shade` actually does

`r.shade` implements a **weighted linear blend**, not a pure multiply:

```
output_value = color_value × (shade_value / 255) × (1 + brighten / 100)
```

Key difference from PIL multiply: GRASS operates on per-band values in GRASS colour table space, not on RGB image arrays. The `brighten` factor lifts the result after the multiply to compensate for gamma.

**Python equivalent:**
```python
def r_shade_equivalent(color_rgb, shade_uint8, brighten=30):
    shade_factor   = shade_uint8.astype(float) / 255.0
    brighten_factor = 1.0 + brighten / 100.0
    result = color_rgb.astype(float) * shade_factor[:, :, np.newaxis] * brighten_factor
    return np.clip(result, 0, 255).astype(np.uint8)
```

---

## 7. Summary — Recommended Parameters for This App

| Parameter | Recommended value | Rationale |
|---|---|---|
| `r.relief` azimuth | 315° | NW convention — prevents relief inversion |
| `r.relief` altitude | 45° | QGIS/SAGA standard |
| `r.relief` zscale | 3.0 (KZN) | Appropriate for mixed escarpment/coastal terrain |
| `r.shade` brighten (relief) | 30 | GRASS default — good for terrain |
| `r.shade` brighten (accumulation) | 80 | Lifts dark accumulation maps |
| `r.colors` scheme | `elevation -e` | Histogram-equalised hypsometric tint |
| Raster resampling | lanczos | Best quality for final PNG downsampling |
| Contrast stretch | 2% percentile clip | Eliminates outlier pixels; QGIS default |
| Flow accumulation stretch | log1p then 2% clip | Values span orders of magnitude |
| PNG compression | compress_level=6 | Fast encode, good size |
| Elevation colormap | `terrain` or `elevation` | Cartographic standard |
| Accumulation colormap | `Blues` on log data | Sequential, blue-convention for water |
| Stream colour | `#1565C0` | Mid blue, correct |
| Stream widths (Leaflet) | `max(0.8, order × 0.8)` px | Order 1=0.8, 3=2.4, 5=4.0, 7=5.6 |
| Hillshade multiply weight | 60% | QGIS / cartographic standard |

---

## 8. Reference Commands (GRASS)

```bash
# Full terrain analysis pipeline
r.in.gdal input=dem.tif output=dem overwrite=True
g.region raster=dem

r.fill.dir input=dem output=filled direction=fdir overwrite=True

r.watershed flags=ab elevation=filled threshold=500 \
    accumulation=accum drainage=drain basin=basins overwrite=True

r.relief input=filled output=relief azimuth=315 altitude=45 zscale=3.0 overwrite=True

# Apply hypsometric colour table BEFORE r.shade
r.colors map=filled color=elevation flags=e

r.shade shade=relief color=filled output=shaded_relief brighten=30 overwrite=True

# Stream network
r.stream.extract elevation=filled accumulation=accum threshold=200 \
    stream_raster=stream_raster direction=flow_direction overwrite=True

r.stream.order stream_rast=stream_raster direction=flow_direction \
    elevation=filled accumulation=accum stream_vect=streams strahler=strahler overwrite=True

# Display
r.colors map=strahler color=water
d.vect map=streams type=line width_column=strahler width_scale=1.5
```

---

*Document produced from research into GRASS GIS, QGIS, SAGA GIS, gdaldem, and cartographic best practices. Applied to PyTOPKAPI GUI map display improvements.*

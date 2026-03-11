# PyTOPKAPI GUI — Bug Fix Plan

Three issues observed after initial testing. This document contains root-cause analysis, a tiered fix strategy, and implementation order.

---

## Issue 1 — Patchy sub-basins / holes in clipped DEM + basin polygons appear to overlap

### Symptoms
- After selecting multiple basins and clicking "Merge & Clip DEM", the clipped DEM has nodata holes along basin boundaries.
- Basin polygons rendered on the map appear to slightly overlap one another.

### Root Cause Analysis

1. **`r.to.vect` staircase boundaries with `-s` smooth flag.**
   GRASS converts the basins raster to polygons by tracing cell edges.
   The `-s` (smooth) flag rounds the staircase edges independently per polygon.
   Because each basin's boundary is smoothed separately, neighbouring basins no longer share *exactly* the same coordinates at their common edge — producing tiny slivers/gaps (< 1 cell width) between adjacent polygons.
   These gaps are below the threshold for visual detection but are real geometric holes.

2. **`simplify(0.001)` during display loading.**
   `_add_vector_gpkg_selectable` simplifies geometry to ~100 m tolerance before sending to Leaflet.
   This is fine for display but further displaces polygon boundaries, making the visual overlap/gap worse.
   The actual geometries stored in the GeoPackage are unaffected (display-only), but the user sees jagged edges and apparent overlap in the rendered map.

3. **`unary_union` does not fill inter-polygon gaps.**
   `shapely.ops.unary_union` merges polygons that share or overlap boundaries.
   If there are tiny gaps (even 0.001 m) between adjacent basin polygons, the union creates a merged geometry *with those gaps preserved as interior holes*.
   These holes propagate directly into the clipped DEM, producing nodata patches along every internal basin boundary.

### Fix Strategy

**Tier 1 — Quick (implement today):**
- Remove the `-s` flag from `r.to.vect` in `FillWorker`. The default (non-smoothed) polygon follows cell edges exactly and neighbouring basins share *identical* edge coordinates, eliminating inter-polygon gaps.
- Buffer the merged polygon by 1 DEM cell width before passing to `ClipWorker`. This closes any residual tiny gaps. The cell width is read from the DEM's affine transform (`abs(transform.a)`).
  ```python
  cell_m = abs(rasterio.open(state.proj_dem_path or state.filled_dem_path).transform.a)
  merged = unary_union(geoms).buffer(cell_m * 1.5)
  ```

**Tier 2 — Robust (future session):**
- Replace polygon-based clipping entirely with **raster-based masking**.
  Track the basin raster IDs (`cat` values) of selected polygons instead of storing the GeoJSON geometry.
  In a GRASS session, create a binary mask `r.reclass` or `r.mapcalc` where any pixel whose value is in the selected set = 1, then use `r.out.gdal` to export. Clip the DEM with `r.mask` applied to this raster mask.
  This approach is immune to all polygon topology issues because it operates entirely in raster space.
- Add a `selected_basin_ids: list[int]` to `ProjectState` so IDs survive session save/restore.

---

## Issue 2 — Strahler order not showing on stream network

### Symptoms
- Stream network displays as uniform thin blue lines regardless of stream order.
- Strahler-proportional line widths not visible.

### Root Cause Analysis

1. **Attribute column name mismatch.**
   `r.stream.order` outputs a vector (`stream_vect`) whose attribute columns are named by GRASS internally. Depending on the GRASS version, the Strahler attribute column may be named `strahler`, `ord_strahler`, or `strahler_order`. The current check:
   ```python
   strahler_col = "strahler" if "strahler" in gdf.columns else None
   ```
   is an exact-match that silently returns `None` if the column has any prefix/suffix.

2. **`r.stream.order` addon may not be installed.**
   The GRASS script calls `g.extension extension='r.stream.order'` which installs the addon if not present. If this fails (no network, permission error, or version incompatibility), `has_stream_order = False` and the fallback `streams_extract` vector is used. This vector has *no* stream order attributes. The failure is logged but not surfaced prominently to the user — they just see the streams without any order.

3. **No diagnostic logging of available columns.**
   There is currently no logging of what columns the GeoPackage actually contains, making it impossible to debug the mismatch without opening the file externally.

### Fix Strategy

**Tier 1 — Quick (implement today):**
- Replace exact-match column check with a case-insensitive substring search:
  ```python
  strahler_col = next(
      (c for c in gdf.columns if "strahler" in c.lower()), None
  )
  ```
- Log the available columns when loading streams so the user can see what's there:
  ```python
  self.log(f"Stream columns: {list(gdf.columns)}", "info")
  ```
- In `StreamWorker`, log column names after GRASS completes:
  ```python
  import geopandas as gpd
  _gdf = gpd.read_file(streams_gpkg)
  self.log_message.emit(f"  Stream vector columns: {list(_gdf.columns)}")
  ```

**Tier 2 — Robust (future session):**
- If the strahler column is still missing after the column search, do a raster-value spatial join: sample the `strahler.tif` at the midpoint of each stream vector segment using `rasterio.sample()`, assign the sampled value as `strahler` column. This works even when the `r.stream.order` addon is unavailable (falls back to the raster output which the worker always exports).
- Add a clear warning in the UI when streams are rendered without Strahler order (e.g., `self.log("⚠ No Strahler column found — displaying with uniform width", "warn")`).

---

## Issue 3 — Streams do not connect

### Symptoms
- Stream segments appear as isolated lines that don't join at confluences.
- Network has gaps, especially in headwater areas.

### Root Cause Analysis

1. **Accumulation/flow-direction algorithm mismatch.**
   `FillWorker` computes `accum` using `r.watershed -ab` (Multiple Flow Direction, MFD algorithm).
   `StreamWorker` imports this `accum` and passes it to `r.stream.extract`, which internally uses a Single Flow Direction (SFD / D8) algorithm.
   **These two accumulations are not compatible.** `r.watershed` (MFD) disperses flow across multiple downslope cells; `r.stream.extract` uses D8 to trace a single path per cell.
   When you supply an MFD-derived accumulation to a D8-based stream extractor, the accumulation values along D8 flow paths don't correspond to the actual upstream catchment area, causing breaks where the accumulated threshold is not consistently met along a D8-traced path.

2. **`drain_ws` is imported but unused.**
   The `drain_ws` (drainage direction from `r.watershed`) is imported into the GRASS session as `drain` but `r.stream.extract` outputs its *own* `fdir_extract` — it doesn't use the imported drainage direction as input. The import is wasted computation.

3. **Stream threshold is shared between basin delineation and stream extraction.**
   The single `stream_threshold` value drives both `r.watershed` (for basin delineation) and `r.stream.extract`. If the threshold is appropriate for coarse basin delineation (e.g., 500 cells ≈ large basins), it may be too coarse for stream extraction and skip many tributaries.

### Fix Strategy

**Tier 1 — Definitive fix (implement today):**
- Remove the `accumulation='accum'` argument from `r.stream.extract` in `StreamWorker`.
  Pass only `elevation='filled'` and let `r.stream.extract` compute its own accumulation using D8 internally. This guarantees perfect consistency between the flow direction and accumulation — the stream network will be fully connected.
  ```python
  gs.run_command('r.stream.extract',
                 elevation='filled',
                 threshold=threshold,
                 stream_raster='stream_raster',
                 stream_vector='streams_extract',
                 direction='fdir_extract', overwrite=True)
  ```
- Remove the `r.in.gdal` import of `drain_ws` (no longer needed by `r.stream.extract`).
  Keep the `accum` import for `r.stream.order` which CAN accept it separately.

**Tier 2 — Better UX (future session):**
- Add a separate `stream_extract_threshold` to `ProjectState` (defaults to the same as `stream_threshold` but user-adjustable in p04's form). Stream extraction typically benefits from a lower threshold than basin delineation.
- Add a "Preview streams" button in p04 that uses `StreamPreviewWorker` to quickly show the network at the current threshold before committing to a full extraction run.

---

## Implementation Order (today's session)

In priority order:

| # | Fix | File | Effort |
|---|-----|------|--------|
| 1 | Remove `-s` from `r.to.vect` | `fill_worker.py` | 1 line |
| 2 | Buffer merged polygon before clip | `p02_dem_processing.py` | 5 lines |
| 3 | Remove `accumulation` from `r.stream.extract` | `stream_worker.py` | 2 lines |
| 4 | Case-insensitive strahler column search + column logging | `p04_stream_network.py` + `stream_worker.py` | 10 lines |

All four are safe changes — they either remove a problematic argument or make a check more robust. None require new state fields or UI changes.

---

## Future Session (out of scope today)

- Raster-based basin masking (Issue 1 Tier 2)
- Strahler spatial join fallback (Issue 2 Tier 2)
- Separate stream extraction threshold (Issue 3 Tier 2)
- Investigate why `r.stream.order` addon sometimes fails to install and add a more prominent failure notification

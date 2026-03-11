# PyTOPKAPI GUI Improvement Plan

## Goal
Simplify the GUI from 10 fragmented steps to 5 clear stages. Make it user-friendly, simple, and robust for setting up and running a PyTOPKAPI model.

## Phase 1: Consolidate workflow to 5 stages (CURRENT)

| New Stage | Old Steps | What happens |
|-----------|-----------|--------------|
| **1. Project Setup** | Steps 1-2 | Create project, draw AOI, download DEM, reproject, fill sinks, compute flow |
| **2. Catchment & Streams** | Steps 3-4 | Pick outlet on map, delineate catchment, extract streams + Strahler order, compute slope |
| **3. Surface Properties** | Steps 5-6 | Load/generate soil params + Manning's n |
| **4. Run Model** | Steps 7-9 | Generate parameter files, load forcing data, run simulation |
| **5. Results** | Step 10 | Hydrograph, flow duration curve, soil moisture |

### Implementation approach
- **Keep all 10 existing panel files and workers unchanged**
- Ribbon shows 5 stage tabs; each stage has tool buttons mapping to old panel indices
- Panel forms shown in a right dock widget (replaces floating QDialogs)
- Ribbon shows 3-state completion: none (gray), partial (orange), done (green)
- `state.py` gains `stage_status(idx)` method mapping 5 stages to old 10-step checks

### Files changed
- `gui/widgets/ribbon.py` — 5 stages, `panel_requested(int)` signal
- `gui/app.py` — right dock for forms, stage-based activation
- `gui/state.py` — add `stage_status()` method
- `gui/panels/__init__.py` — QFileDialog parent fix

## Phase 2: Inline forms (FUTURE)
Replace right dock with collapsible sidebar that slides over the map. Keep form + map visible together with better spatial context.

## Phase 3: Guided workflow (FUTURE)
- Each stage shows checklist of done/needed items
- "Run" buttons disabled until prerequisites met
- "Next" button auto-advances to next stage
- Prerequisite validation (CRS checks, extent checks, file format checks)

## Phase 4: Robustness (FUTURE)
- Input validation (CRS, extent, format)
- Better error messages with recovery suggestions
- Progress feedback tracking GRASS operations line-by-line
- Unit tests for state persistence and worker outputs

## GRASS tutorial workflow (reference)
From tutorial.html (Brendan Harmon — Watersheds in GRASS GIS):
1. Terrain Acquisition: g.region, r.in.usgs (or DEM download), r.relief, r.shade
2. Watershed Delineation: r.watershed (threshold), r.to.vect, v.extract, r.mask
3. Flow Accumulation: r.watershed -a -b, r.shade
4. Stream Order: r.stream.extract, r.stream.order (Strahler), d.vect (width_column=strahler)

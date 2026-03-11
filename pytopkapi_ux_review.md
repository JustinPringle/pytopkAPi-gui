# PyTOPKAPI GUI — UX Review & Bug Report

## 1. Onboarding / Initial State
- On launch, the GUI shows a map with no guidance. **Add a clear starting prompt** directing the user to Step 1 (e.g. "Welcome — begin by creating a new project in the Setup ribbon").

---

## 2. Project Creation — Ribbon & Sub-process Clarity
- The bottom ribbon shows three options: *Project Setup*, *Create Project*, and *Process DEM*, but **the active sub-process is not highlighted**. The user needs a clear visual indicator of which step they are currently on.
- **Fix:** Highlight or bold the active sub-process tab, and add a short description of what that step involves.

---

## 3. Area of Interest — Drawing Instructions
- Beneath the map/charts ribbon, zoom controls and extent buttons are present but unlabelled. **Add tooltips** on hover explaining each button's function.
- The instruction *"Draw a rectangle on the map to delineate an area of interest"* is easy to miss — it appears as a small inline label. **Make this more prominent** (e.g. a banner or highlighted callout).
- **Once the AOI is drawn**, the bounding box coordinates display correctly in green — this is good. However, there is **no prompt directing the user to the next step** (downloading the DEM).

---

## 4. DEM Download
- The DEM type selector may confuse inexperienced users. **Add a brief tooltip or help text** explaining each DEM type option.
- The API key field may be unfamiliar to new users. **Add a helper link** to instructions on obtaining a key.
- The DEM downloads correctly, but there is **no post-download prompt** telling the user what to do next (i.e. move to *Process DEM*).

---

## 5. Process DEM — Transition Issues
- When moving from *Create Project* to *Process DEM*, the map correctly zooms to the AOI. However:
  - The instruction still reads *"Draw a rectangle to define the area of interest"* — **this must update** to confirm the AOI is set and guide the user to run terrain analysis.
  - Previously selected layers in the layer panel are **deselected after this transition** — this should be preserved.

---

## 6. Terrain Analysis — Output Log Formatting
- Progress percentages in the output log display incorrectly (run together on one line). **Fix the log formatter** to display each percentage on a new line or as a progress bar.
- The following non-fatal error appears and should be **caught and suppressed or explained** to the user:

```
ERROR 6: relief.tif, band 1: SetColorTable() only supported for Byte or UInt16 bands in TIFF format.
```

---

## 7. Layer Panel — Display & Toggle Bugs

**Critical bugs:**

1. **Flow accumulation renders even when deselected** in the layer panel — layer visibility is not being respected.
2. **The blue basin vector layer cannot be toggled off** — the toggle appears non-functional for this layer.
3. **The shaded relief layer cannot be toggled** either — same issue.
4. After re-rendering terrain (brightness adjusted to 60), the **shaded relief display degrades significantly** — investigate rendering pipeline for brightness/contrast adjustments.
5. Basins with blue outlines appear **unexpectedly after re-render** — this suggests a state management bug where layer styles or visibility flags are being reset.

**Expected behaviour:** All layers in the panel should be independently toggleable, with state preserved across re-renders. The shaded relief should render at the highest available resolution for the current zoom level (responsive raster rendering).

---

## 8. General UX Recommendations
- Each step in the workflow should have a **persistent status label** stating: (a) what was just completed, and (b) what the user should do next.
- Consider a **step progress indicator** (e.g. Step 1 of 4) in the ribbon to orient the user throughout the workflow.

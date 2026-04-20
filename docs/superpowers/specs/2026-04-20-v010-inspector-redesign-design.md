# v0.10 — Inspector redesign + multi-tank + polygon ROI

**Status:** draft — awaiting user confirmation before writing plan.
**Date:** 2026-04-20
**Prior art:** v0.9.0 (algorithm fixes), v0.9.1 (sidebar overflow + CLOSE-button hotfix).

---

## Why this version exists

After field testing v0.9.0 on N-1065, the user flagged five issues that together demand a UI + ROI redesign rather than another hotfix:

1. **"I lost the little settings at the bottom. Inspect / Why? / Edit / Remove — I don't have access anymore."** (Fixed in v0.9.1 by scroll padding; v0.10 replaces the Inspect/Why surface entirely so this class of bug goes away.)
2. **"I can only inspect one tank at a time. I want to inspect multiple."**
3. **"The Inspect panel is cluttered. I don't like how it looks and I can't see what's behind."**
4. **"Give me any kind of shape, not only rectangles. Chemical tanks are round."**
5. **Tank delete/edit has unspecified glitches.** (Repro steps pending from user.)

The algorithm work from v0.9.0 stays intact; this release is UI + ROI geometry only.

---

## Architecture

### Five focused units

1. **`inspector` (client-side Alpine state)** — holds `inspector.tankIds: string[]` (plural; was `inspector.tankId: string | null`). All existing "is this tank inspected?" checks become `inspector.tankIds.includes(t.id)`.
2. **`TankInspectorPanel` (new Alpine component, inline in the right card)** — when a tank is toggled into inspection, its card inline-expands to show sensor histogram, row-fraction chart, level-line preview, η, monotonicity, and Why? reasons. No modal. No canvas overlay.
3. **`ROI geometry` (server + client)** — replace `roi: {x,y,w,h}` with `roi: {shape: "rect"|"polygon"|"quad"|"circle", points: [[x,y], …]}`. `rect` stays as fast-path; other shapes use cv2 fillPoly masking. Analyzer becomes mask-aware.
4. **`Polygon draw tool` (client)** — the `+ Tank` tool grows a shape-selector (Rect / Quad / Polygon / Circle). Quad for tilted rectangles. Polygon for arbitrary. Circle for round tanks.
5. **`Tank CRUD` (server /api/tanks/*)** — audit the delete & edit paths for the reported bug. Likely a stale ID reference in the live results array after a delete; fix with a `state.results` filter by known tank IDs every frame.

### Why Option C (right-panel inline expansion) over modal or floating cards

- **No canvas clutter.** Live feed stays pure thermal. This directly addresses "I don't see what is in" — the overlay gets out of the way.
- **Multi-tank is free.** Each card expands independently; no z-index dance, no focus stealing, no "which tank is active?" ambiguity.
- **Matches SCADA industry conventions.** Industrial HMIs (Ignition, Wonderware, Rockwell) use inline drawer expansion for asset detail.
- **Keyboard + screen-reader friendly.** Tab order follows the DOM; no custom focus traps.
- **Simplest to implement on a 998 MB / 2-core device.** No portal rendering, no canvas-2D overlay math for N tanks.

### Data-flow sketch

```
live frame → analyzer.py (mask-aware) → per-tank result
           → /api/state  → Alpine state.results[]
           → tank card renders
             └─ if inspector.tankIds includes t.id → inline drawer with
                - histogram (D3 or svg sparkline reused)
                - row-fraction chart (horizontal bars)
                - η, monotonicity, threshold_c, reliability reasons
                - "Close inspection" button (replaces "Hide")
```

### Failure modes to design for

- **Polygon ROI partially outside frame** — clamp points to `[0, sensor_w/h-1]`.
- **Polygon with < 3 points** — reject on save, show inline error.
- **Rotating an existing rect tank into a quad** — migration: treat rect as a degenerate quad `[[x,y],[x+w,y],[x+w,y+h],[x,y+h]]`.
- **Delete while inspecting** — remove from `inspector.tankIds` on delete; server already filters; client must also drop stale IDs.
- **Upgrade from v0.9.x** — old config has `roi:{x,y,w,h}`; loader normalizes to `{shape:"rect", points:[...]}`.

### Testing

- Unit tests for mask construction (`polygon_mask`, `quad_mask`, `circle_mask`) — pixel-count parity vs. `rect` on matched geometries.
- Unit test for state hygiene: delete tank → `inspector.tankIds` no longer contains it.
- Synthetic smoke test extended: rotate a half-full tank by 30° and use a quad ROI; level should still read 50 ±2 %.

---

## Out of scope (explicit YAGNI)

- **Bezier / spline ROI.** Polygon is already general; bezier adds complexity with no operator benefit.
- **3D tank volume for non-cylinder shapes.** Stays manual via `geometry.shape` config.
- **Drag-to-reshape existing ROIs.** Edit-via-delete-and-redraw is fine for v0.10.
- **ML / ONNX level detection.** Hardware still can't spare the cycles.

---

## Open questions for user

1. **Shape menu ordering** — Rect / Quad / Polygon / Circle. Is there a 5th I'm missing (ellipse for leaning round tanks? capsule for horizontal cylinders)?
2. **Multi-inspect cap** — no cap, or limit to 3 simultaneous (keeps UI sane on a 1920×1080 screen)?
3. **Delete/edit repro** — what are the exact click sequences that reproduce the bug?

---

## Files that will change

- `thermal/app/analyzer.py` — mask-aware ROI; `_roi_mask()` helper; pass mask into all per-row/per-pixel computations.
- `thermal/app/config.py` (or wherever ROI schema is validated) — schema accepts shape/points.
- `thermal/app/overlay.py` — draws polygon perimeter via `cv2.polylines`; label stack anchors to shape centroid/top.
- `thermal/app/webui.py` — `inspector.tankIds: Set<string>`; inline drawer; new shape toolbar; delete cleanup.
- `thermal/app/routes.py` — `/api/tanks/:id DELETE` cleans up inspector state reference if any server-side cache exists.
- `dev/test_v010.py` — polygon/quad/circle smoke tests.

---

## Decision log

- **2026-04-20** — User picked Option C (right-panel inline expansion) as the inspection redesign direction. Rejected Option A (bottom dock) as too modal; rejected Option B (floating cards) as too chaotic.
- **2026-04-20** — Polygon is the "any shape" answer. Circle and Quad are special cases for ergonomics (easier to draw one click than N).
- **2026-04-20** — No ML. Confirmed N-1065 analyzer still at 112 % CPU, 33 MB RAM; no headroom.

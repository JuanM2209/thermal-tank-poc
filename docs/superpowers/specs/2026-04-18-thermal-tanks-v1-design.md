# Thermal Tank Monitor v1 — Design

**Date:** 2026-04-18
**Status:** Approved by user, implementation in progress
**Supersedes:** ad-hoc Node-RED dashboard + Alpine.js SPA in v0.3.x

## Goal

Ship an operator-grade thermal tank level system for Permian Basin facilities.
Fixes the current dashboard bugs, adds real-world units, auto tank detection,
auto classification (water vs oil), auto thermal calibration, fill/drain rate
estimation, and two redesigned dashboards (operator + supervisor).

## Non-goals

- Hikvision RTSP migration (future, tracked separately)
- Multi-site aggregation (future; schema is multi-site ready but UI is per site)
- SQLite history / CSV export (future)
- YOLOv8 tank detection (we stick with classical OpenCV; v2 candidate)

## Architecture

Two services on the Nucleus, one pipeline:

```
P2 Pro USB-C -> /dev/video0 (YUYV 256x384 dual-frame)
    |
    v
thermal-analyzer (Python/OpenCV, :8080)
  - capture -> auto-detect -> analyze -> /api/state, /api/tanks, /api/calibrate
  - MJPEG at /stream.mjpg
  - Operator Console SPA at /
    |
    | POST /thermal/ingest every 2 s
    v
Node-RED (:1880)
  - data sink -> history, alerts, trends
  - Supervisor Dashboard at /ui (redesigned, no iframe)
```

Port 8080 is the **Operator Console** (hands-on at site): live stream front and
center, per-tank cards with ft/in/bbl/rate, calibration and auto-detect wizards.

Port 1880 is the **Supervisor Dashboard** (for display / remote): 24 h trends,
alert history, KPI cards. No embedded video. Deep-links to `:8080` for the
stream.

Both consume the same tank config. Node-RED holds no configuration.

## Data model

Tank payload every 2 s on `POST /thermal/ingest`:

```json
{
  "ts": 1713456789012,
  "site_id": "N-1065",
  "tanks": [{
    "id": "tank_01",
    "name": "Tank 1",
    "medium": "water",
    "medium_confidence": 0.87,
    "roi": {"x":30,"y":10,"w":40,"h":170},

    "level_pct": 67.4,
    "level_raw_pct": 69.1,
    "confidence": "high",

    "geometry": {
      "height_ft": 22.0,
      "diameter_ft": 12.0,
      "shape": "vertical_cylinder"
    },
    "reading": {
      "level_ft": 14.83,
      "level_in": 177.9,
      "volume_bbl": 1678.2,
      "volume_gal": 70484,
      "ullage_ft": 7.17,
      "fill_rate_bbl_h": 12.4,
      "minutes_to_full": 812,
      "minutes_to_empty": null
    },

    "temp_min": 18.2, "temp_max": 32.1, "temp_avg": 24.7,
    "gradient_peak": 3.82,

    "calibration": {
      "emissivity": 0.96,
      "reflect_temp_c": 22.4,
      "range_locked": true,
      "range_min_c": 12.0, "range_max_c": 42.0,
      "calibrated_at": "2026-04-18T13:45:11Z"
    }
  }]
}
```

## Bug fixes (current)

| Bug | Root cause | Fix |
|---|---|---|
| Live stream iframe stuck "loading..." | `X-Frame-Options: DENY` and strict CSP block cross-subdomain iframe under CF Tunnel | stream route sends `X-Frame-Options: SAMEORIGIN` removed; `Content-Security-Policy: frame-ancestors https://*.datadesng.com` |
| Only Tank 2 gauge visible | single `ui_gauge` node collapses multiple topics | replace with `ui_template` that grids N gauges |
| Timestamp `+058266-03-29` | ts multiplied twice (ms -> us) | publisher sends ts in ms; Node-RED trusts ts as ms; no unit math in the flow |
| Both tanks always 0.6 % | default ROIs point at wall, not tanks | auto-detect wizard replaces manual ROI editing |

## Feature: auto-detect and auto-classify

`detect.py` upgrade:
- detection samples 30 s (median mask across frames) instead of one frame
- classification of each candidate as `water | oil | unknown`:
  - water: higher emissivity, sharper interface gradient, cooler mean vs scene
  - oil: lower emissivity, warmer mean, smoother interface
  - features: (mean - scene_median), temporal variance over 60 s, gradient sharpness
  - logistic blend -> `medium_confidence` in `[0, 1]`
- numbering: sort left-to-right in sensor frame -> `Tank 1`, `Tank 2`, ...

Wizard flow (operator console):
1. press **Auto-detect**
2. analyzer returns candidates with guessed name + medium + confidence, overlaid on the stream
3. operator confirms or edits (name, medium, height ft, diameter ft)
4. save -> config pushed to `/app/data/runtime.json`; next payload carries the new geometry

## Feature: real-world units

Operator enters **height_ft** and **diameter_ft** for each tank. Analyzer
computes every cycle:
- `level_ft = level_pct / 100 * height_ft`
- `level_in = level_ft * 12`
- `volume_ft3 = pi * (diameter_ft / 2)^2 * level_ft`
- `volume_bbl = volume_ft3 * 0.1781`  (1 bbl = 5.6146 ft^3)
- `volume_gal = volume_ft3 * 7.4805`
- `ullage_ft = height_ft - level_ft`

Rate estimation:
- rolling 5-min EMA of `d(volume_bbl)/dt`
- Hampel filter rejects outliers (|x - median| > 3 * MAD)
- `minutes_to_full` / `minutes_to_empty` only when rate has stable sign for > 2 min

UI toggle: `ft` / `in` flips the primary display; volume always bbl; rate bbl/h.

## Feature: auto-calibration

On **Calibrate** button (or first run):
1. sample 10 s of frames
2. emissivity from detected medium: water 0.96, oil 0.94, steel 0.90
3. reflect_temp_c = mean of coldest quartile outside all tank ROIs
4. temp range = [p1, p99] of tank-pixel temps + 2 C margin, locked
5. persist to `runtime.json.calibration`

Optional continuous trim: every 5 min, if range drift > 3 C, re-lock silently.

Confidence gate: if scene's thermal delta < 1.0 C, UI shows a "wait for thermal
delta" banner (common at solar noon) instead of noisy numbers.

## Interfaces

### Operator Console (:8080)

Single-screen SPA, dark theme.

```
+-----------------------------------------------------------------+
|  * Thermal Tank Monitor . N-1065 . live . 25.5 fps  [cal OK]   |
+---------------------------------+-------------------------------+
|                                 |  TANK 1 . water   + high      |
|                                 |  [=========------]  67.4 %    |
|       LIVE STREAM               |  14.83 ft / 22 ft             |
|   (MJPEG, palette, overlays)    |  1,678 bbl   +12.4 bbl/h ^    |
|                                 |  ETA to full: 13 h 32 min     |
|                                 +-------------------------------+
|                                 |  TANK 2 . oil     + high      |
|                                 |  [==============-]  91.2 %    |
|                                 |  14.59 ft / 16 ft             |
+---------------------------------+-------------------------------+
|  [Auto-detect] [Calibrate] [Snap] [Rec] [Settings] [ft|in]      |
+-----------------------------------------------------------------+
```

Stack: existing `webui.py` single-file SPA (Alpine.js + Tailwind CDN). We
rebuild the layout but keep the plumbing.

### Supervisor Dashboard (:1880/ui)

```
+-----------------------------------------------------------------+
|  Site N-1065 . last ingest 2026-04-18 15:02 . 2 tanks online    |
+------------+------------+---------------------------------------+
|  TANK 1    |  TANK 2    |  LEVEL TREND - last 24 h              |
|  67.4 %    |  91.2 %    |  [sparkline both tanks]               |
|  14.83 ft  |  14.59 ft  |                                       |
|  +12.4 b/h |  -3.1 b/h  |                                       |
+------------+------------+---------------------------------------+
|  AVG TEMP . 24 h        |  ALERTS (last 24 h)                   |
|  [line chart, C]        |  13:24 Tank 1 HI-HI   cleared         |
|                         |  09:11 Tank 2 LO-LO   OPEN            |
+-------------------------+---------------------------------------+
|  [Stream ->]  [Calibrate ->]  (deep links to :8080)             |
+-----------------------------------------------------------------+
```

Node-RED `ui_template` KPI cards, no gauges, no iframe. Alerts persisted in a
capped deque on `flow.alerts`.

## Modules and files

New or rewritten:

```
thermal/app/
  geometry.py        NEW  - ft/in/bbl/gal conversions, pure functions
  rate.py            NEW  - Hampel + EMA rate estimator
  classifier.py      NEW  - water/oil logistic classifier (medium + confidence)
  calibration.py     NEW  - auto-calibration logic
  detect.py          edit - multi-frame detection, emits medium_confidence
  analyzer.py        edit - attaches geometry/reading/calibration to payload
  publisher.py       edit - ts in ms, never multiplied, site_id field
  stream.py          edit - CSP + X-Frame headers on stream route;
                            /api/calibrate and /api/tanks endpoints
  webui.py           edit - new operator console layout

node-red/
  tank-dashboard-flow.json   rewrite - KPI cards, alert history, deep links

tests/
  test_geometry.py   NEW
  test_rate.py       NEW
  test_classifier.py NEW
  test_calibration.py NEW
```

## Testing

- unit: geometry, rate, classifier, calibration math (pytest, >= 80 % coverage)
- integration: inject synthetic thermal frames to analyzer, assert payload shape
- e2e: Chrome Cloud against live `:8080` and `:1880/ui`, screenshot each panel

## Risks

- **water/oil classifier** needs field tuning. Mitigation: operator override in wizard; log features so we can retune later.
- **CSP fix** may re-introduce clickjacking exposure. Mitigation: allow iframing only from `*.datadesng.com`, not `*`.
- **hand-edited runtime.json** can break auto-detect. Mitigation: pydantic schema validation on load, fall back to defaults with a loud warning.

## Rollout

v0.4.0 image tag. Deploy via existing `install-on-nucleus.sh` path:
1. build ARMv7 image (`build.ps1 -Tag v0.4.0`)
2. push GitHub release asset
3. re-run installer on N-1065

No breaking changes to the Docker run command or the Node-RED bridge URL.

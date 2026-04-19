# Thermal Tank PoC — Design Decisions

## 1. Transport to Node-RED: HTTP POST + per-tank `topic` label (not MQTT)

**Decision.** Keep HTTP POST to a single Node-RED ingest endpoint, and tag each
tank payload with a `topic` string. Node-RED's `switch`/`change` nodes fan that
out to the right downstream flow.

**Why not MQTT.**

- Node-RED is already running on the Nucleus in every deployment. HTTP POST
  against `host.docker.internal:1880/thermal/ingest` is zero extra
  infrastructure.
- The payload is small (~1 KB per tick × 2 s) and the device has Node-RED
  locally — no broker, no TLS cert juggling, no auth scheme to design.
- Our existing chisel + Cloudflare Tunnel path already securely exposes the
  Node-RED port upstream. Adding MQTT would duplicate that transport layer.
- MQTT would matter if we had >1 subscriber per tank or needed fan-out across
  sites. We don't — ingestion is device-local and single-consumer.

**Shape.** Each element of the `tanks` array now carries a `topic` field:

```json
{
  "ts": 1744912345678,
  "site_id": "N-1065",
  "tanks": [
    { "id": "tank_01", "topic": "nucleus/n-1065/water_tank_1", ... },
    { "id": "tank_02", "topic": "nucleus/n-1065/oil_tank_1", ... }
  ]
}
```

Node-RED routes on `msg.payload.tanks[i].topic`.

**If we later need MQTT.** Add a second publisher class
(`MqttPublisher`) and let `config.publisher.transport: http|mqtt` pick. The
per-tank `topic` field maps straight to an MQTT topic string — no payload
rewrite needed.

---

## 2. Region shape: rectangles for tank ROIs; keep polygon tool for measurements

**Decision.** Tank ROIs stay as axis-aligned rectangles (`{x, y, w, h}`). The
polygon drawing tool stays in the live view but only for ad-hoc temperature
measurements, not as a tank region.

**Why rectangles for tanks.**

- The level-detection algorithm (`analyzer._profile` → `_gradient`) operates on
  the mean of each row across the strip. A rectangle is the natural input
  because `strip.mean(axis=1)` is a clean 1D vertical profile. Polygons
  require a mask, then masked-mean per row, which adds cost and edge cases
  (empty rows, concave polygons) without any accuracy gain on cylindrical
  tanks photographed head-on.
- Auto-detect already returns rectangles — the detector searches for vertical
  gradient-rich strips, and rectangles are how it scores them.
- Storage is one YAML line per tank. Polygons would force us into a list of
  points per tank, complicating the Settings UI and the PATCH payload.

**Why keep polygon in the tool-bar.**

- Operators use it to spot-check temperatures on irregular features
  (heat-exchanger fins, pipe bundles, burned-out motors) — real value,
  orthogonal to tank detection.
- The measurement code already masks pixels correctly via
  `/api/measure` → `polygon` shape.

**If we ever need non-rectangular tanks.** Tilted horizontal cylinders or
tanks photographed off-axis would motivate it. The path would be: store
`roi.mask` as either `{shape:'rect', ...}` or `{shape:'polygon', points:[...]}`
and branch inside `TankAnalyzer.analyze`. The existing polygon measure code
is the template.

---

## 3. Config location: on-device `config.yaml` is canonical; portal is read-through, not write-through

**Decision.** `thermal/config.yaml` on the Nucleus stays as the source of
truth. The portal exposes port 8080 and lets operators edit the config
through the web UI (`PATCH /api/config`, `PATCH /api/tanks/<id>`), which
writes to the local YAML via `runtime.yaml`. The portal itself does **not**
store tank config centrally.

**Why.**

- The device is the only thing that owns its camera geometry. ROIs, topics,
  and tank heights are site-specific — pushing from a central store would
  require the central store to know the camera orientation and viewport for
  every site, which it doesn't (and shouldn't — portals change, devices
  don't).
- The Nucleus is already self-contained: boot with no network, run the
  pipeline, publish locally to Node-RED. Making config depend on the portal
  breaks that isolation. A field tech should be able to SSH in and edit
  config even when the portal is unreachable.
- Edit path is already fast: Alpine.js `PATCH` → `apply_patch` → YAML
  overlay. Adding a portal round-trip would double the latency and add a
  failure mode (portal down = can't edit).

**What the portal *does* track centrally.**

- Device liveness (agent heartbeat) — already in `heartbeats` table.
- Port exposure sessions — already in `port_allocations` + `exposures`.
- Per-device activity events (who exposed what, when) — already in
  `audit_logs`.

These are about fleet ops, not tank config. The split is: **portal owns
fleet state, device owns thermal config.**

**If we ever need bulk push.** A provisioning endpoint that GETs a snapshot
from the central store and writes `config.yaml` on first boot is easy to
bolt on — same as how a field tech pastes a YAML file today, just
automated. That would be additive, not a replacement for local ownership.

---

_Decided 2026-04-18 while scoping v0.5.4 of the thermal PoC._

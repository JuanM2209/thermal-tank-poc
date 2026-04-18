# Thermal Tank Level Detection — PoC

Detección de nivel de tanques de agua/aceite con cámara térmica USB-C (Thermal Master P2 Pro) corriendo en un Nucleus edge device.

**Cámara validada en N-1065 (2026-04-17):**
- USB VID:PID `0bda:5830` → `/dev/video0`
- Formato confirmado: **YUYV 256×384 @ 25fps (dual-frame)** — tienes data térmica raw en °C
- Driver `uvcvideo` built-in (kernel 4.9.88 imx)

## What's new in v0.2.0

- **Slim Docker**: `python:3.11-slim` + `opencv-python-headless` (multi-stage). Target ~120 MB vs 260 MB in v0.1.0.
- **New interactive dashboard** at `http://<nucleus-ip>:8080/`:
  - 10 palettes (iron, rainbow, hot, inferno, plasma, magma, jet, turbo, cividis, grayscale)
  - source switch: thermal / visual / blend
  - **click-to-read temp** at any pixel
  - **draw ROIs** directly on the stream (no more editing config.yaml by hand)
  - overlay toggles (ROI boxes, min/max markers, temp scale, FPS, grid, crosshair)
  - FPS / JPEG quality / upscale / temp unit / emissivity sliders
  - live tank cards + events log
- **Stream is now 20 FPS** (was 5) — smooth motion.
- **Camera auto-detect** by USB VID:PID (no more fighting `/dev/video0` grabs).
- **Event stream**: `level_change`, `low_confidence`, `tank_added`, `config_change`.
- **Runtime overrides persist** to `/app/data/runtime.json` (volume-mounted, survives restart).
- **Node-RED flow** now filters the Level chart by `confidence==='high'` (no more noise spikes) and the iframe auto-rewrites the stream URL for cross-device dashboards.

---

## Flujo — 3 pasos

```
┌─────────────────────────┐   ┌──────────────────────┐   ┌────────────────────┐
│ 1. Docker Desktop (Win) │ → │ 2. GitHub Release    │ → │ 3. Nucleus copy/   │
│    build.ps1            │   │    upload .tar.gz    │   │    paste one-liner │
└─────────────────────────┘   └──────────────────────┘   └────────────────────┘
```

El Nucleus nunca necesita hacer `docker pull` (su Docker 18.03 rompe con manifests modernos) — solo descarga un tarball y hace `docker load`.

---

## Paso 1 — Build local (Docker Desktop en Windows)

Requisitos: Docker Desktop con WSL2, PowerShell 7+.

```powershell
cd Z:\thermal-tank-poc
powershell .\build.ps1 -Tag v0.2.0
```

Produce `dist\thermal-analyzer-armv7.tar.gz` (~120 MB in v0.2.0).

QEMU emulará ARMv7 la primera vez (tarda 5-10 min). Siguientes builds: cache.

## Paso 2 — Publicar en GitHub release

```powershell
# Requiere gh CLI (https://cli.github.com/)
gh auth login

# Crea el repo público (primera vez)
gh repo create thermal-tank-poc --public --source=. --remote=origin --push

# Crea el release y sube el tarball
gh release create v0.1.0 `
  --repo juanmejia109/thermal-tank-poc `
  --title "Thermal Analyzer v0.1.0" `
  --notes "ARMv7 for Nucleus" `
  dist\thermal-analyzer-armv7.tar.gz dist\SHA256SUM
```

O todo en uno: `pwsh .\build.ps1 -Release juanmejia109/thermal-tank-poc -Tag v0.1.0`

## Paso 3 — Instalar en Nucleus (terminal Cockpit)

Edita `install-on-nucleus.sh` line 16-18 con tu usuario/repo/tag antes de commit/push.
Después en el Nucleus:

```bash
curl -fsSL https://raw.githubusercontent.com/juanmejia109/thermal-tank-poc/main/install-on-nucleus.sh | sh
```

Eso:
1. Crea `/opt/thermal/` y baja `config.yaml`
2. Descarga el `.tar.gz` del release + `docker load`
3. Arranca `docker run` con `--device=/dev/video0`, `--network host`, restart policy
4. **No toca** los containers existentes (`nucleus-agent`, `remote-support`, `nucleus-node-red`)

Verificar:

```bash
docker logs -f thermal-analyzer        # debe ver 'frame#N tank_01:..%(h|l)'
curl -s http://127.0.0.1:8080/healthz   # -> ok
# Web preview:   http://<nucleus-ip>:8080/
```

---

## Node-RED integration

El analyzer publica por `POST http://127.0.0.1:1880/thermal/ingest` cada 2 s:

```json
{
  "ts": 1713456789012,
  "tanks": [
    {"id":"tank_01","name":"Tank 1","medium":"water",
     "level_pct":67.4,"temp_min":18.2,"temp_max":32.1,"temp_avg":24.7,
     "gradient_peak":3.82,"confidence":"high"}
  ]
}
```

Importar `node-red/tank-dashboard-flow.json` en el Node-RED existente del Nucleus:
- Menu → Import → Clipboard → pega el JSON → Deploy
- Dashboard en `/ui` → tab "Thermal Tanks" con gauges + charts + MJPEG iframe

---

## Arquitectura

```
  P2 Pro USB-C ──► /dev/video0 (UVC 256×384 YUYV)
                         │
                         ▼
  ┌──────────────────────────────┐
  │ thermal-analyzer (container) │   host network
  │  OpenCV capture              │
  │  └─► split visual + thermal  │
  │      (°C = raw/64 - 273.15)  │
  │  └─► gradient per ROI        │
  │  ├─► HTTP POST :1880  ───────┼──► Node-RED /thermal/ingest → Dashboard /ui
  │  └─► MJPEG :8080      ───────┼──► <nucleus-ip>:8080/stream.mjpg
  └──────────────────────────────┘
```

---

## Ops

| Action | Command |
|--------|---------|
| Follow logs | `docker logs -f thermal-analyzer` |
| Edit ROIs | `nano /opt/thermal/config.yaml && docker restart thermal-analyzer` |
| Stop | `docker stop thermal-analyzer` |
| Remove | `docker rm -f thermal-analyzer` |
| Update image | re-run `install-on-nucleus.sh` after a new release |
| Disk usage | `docker system df` |

---

## Estructura del repo

```
thermal-tank-poc/
├── build.ps1                          # Windows build + release (PS 5.1 safe)
├── install-on-nucleus.sh              # Nucleus one-liner installer
├── thermal/
│   ├── Dockerfile                     # python:3.11-slim + pip (multi-stage)
│   ├── config.yaml                    # ROIs + stream + overlays + UI settings
│   └── app/
│       ├── main.py                    # pipeline orchestrator
│       ├── capture.py                 # UVC YUYV dual-frame decoder
│       ├── camera_detect.py           # USB VID:PID auto-match
│       ├── analyzer.py                # gradient-based level + confidence
│       ├── palette.py                 # colormaps (iron + OpenCV LUTs)
│       ├── overlay.py                 # ROI boxes, markers, temp scale, FPS
│       ├── state.py                   # shared state (main ↔ web)
│       ├── stream.py                  # Flask MJPEG + REST API
│       ├── webui.py                   # single-file SPA (Alpine.js + Tailwind)
│       └── publisher.py               # HTTP POST to Node-RED
├── node-red/tank-dashboard-flow.json  # HTTP-ingest + confidence filter + iframe
├── cloudflare/config.yml.example      # Tunnel to expose externally
├── tools/ (probe.py, roi_picker.py)   # ROI calibration helpers
└── dist/                              # build.ps1 output (gitignored)
```

---

## Tuning / troubleshooting

| Síntoma | Fix |
|---|---|
| `confidence: low` siempre | bajar `min_temp_delta` a 0.8, subir `smoothing_window` a 11, re-deploy |
| Level oscila mucho | subir `interval_seconds` a 5 (reduce frecuencia de publicación) |
| Node-RED no recibe | `docker logs thermal-analyzer` → ver `POST failed`; chequear endpoint |
| ROI fuera de cuadro | correr `tools/roi_picker.py` en una máquina con display + cámara, pegar en config.yaml |
| Container restart loop | `docker logs thermal-analyzer` — probablemente formato UVC cambió, correr `tools/probe.py` |

---

## Roadmap → producción

- [x] Slim Docker (~120 MB)
- [x] Interactive dashboard (palettes, click-to-read, draw ROIs, settings)
- [x] Camera auto-detect by USB VID:PID
- [x] Node-RED confidence filter + cross-device iframe
- [ ] Tune ROIs con tanques reales (calibración: agua helada 0°C + agua caliente 100°C como referencia)
- [ ] **AI tank auto-detect** — OpenCV contour pass first, YOLOv8n once we have ~200 labeled thermal frames
- [ ] Grabación 24h para detectar drift día/noche
- [ ] Alertas Node-RED → Slack cuando level crítico o `confidence: low` > 5 min
- [ ] SQLite local history + CSV/PDF export
- [ ] Dashboard token auth (via portal)
- [ ] Migración a **Hikvision DS-2TD1217** (RTSP/ONVIF + ISAPI, $800-1200) — reemplaza `capture.py` por cliente RTSP
- [ ] Multi-site: cada Nucleus publica a broker central en Oracle VM/Tyrion con `site_id` en el payload

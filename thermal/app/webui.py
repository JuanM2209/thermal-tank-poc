"""Operator Console — single-page Alpine.js SPA for :8080.

Rendered as one HTML string so the container ships one file with no build step.
Tailwind + Alpine come from CDNs; first load may stall on air-gapped sites but
that's intentional for the PoC.
"""

INDEX_HTML = r"""<!doctype html>
<html lang="en" class="dark">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Thermal Tank Monitor</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.14.1/dist/cdn.min.js"></script>
  <style>
    html,body{height:100%;background:#05070a;color:#e6e6e6;font-family:ui-sans-serif,system-ui,sans-serif;overflow:hidden}
    ::-webkit-scrollbar{width:8px;height:8px}
    ::-webkit-scrollbar-thumb{background:#2a323d;border-radius:4px}
    .stream-wrap img{image-rendering:pixelated;width:100%;height:100%;object-fit:contain;background:#000;display:block}
    .stream-wrap canvas.draw{position:absolute;inset:0;pointer-events:auto;cursor:crosshair}
    .stream-wrap canvas.draw.idle{pointer-events:none;cursor:default}

    .card{background:#0d1117;border:1px solid #1f2630;border-radius:12px}
    .card.hi{border-color:#15803d}
    .card.lo{border-color:#a16207}
    .card.al{border-color:#b91c1c;box-shadow:inset 0 0 0 1px #b91c1c}
    .btn{background:#12161c;border:1px solid #2a323d;padding:.4rem .75rem;border-radius:8px;font-size:.8rem;cursor:pointer;color:#e6e6e6;transition:.15s}
    .btn:hover{background:#1a2030;border-color:#3b4250}
    .btn.primary{background:#1d4ed8;border-color:#2563eb}
    .btn.primary:hover{background:#2563eb}
    .btn.success{background:#166534;border-color:#15803d}
    .btn.success:hover{background:#15803d}
    .btn.warn{background:#b45309;border-color:#c2760b}
    .btn.warn:hover{background:#c2760b}
    .btn.rec{background:#b91c1c;border-color:#dc2626;animation:pulse 1.3s infinite}
    .btn.sm{padding:.25rem .5rem;font-size:.7rem}
    @keyframes pulse{50%{opacity:.6}}
    .pill{backdrop-filter:blur(6px);background:rgba(15,23,42,.8);border:1px solid #1f2630;border-radius:999px;padding:.25rem .75rem;font-size:.72rem}
    .dot{width:8px;height:8px;border-radius:999px;display:inline-block}
    .dot.ok{background:#22c55e}.dot.warn{background:#f59e0b}.dot.err{background:#ef4444}.dot.idle{background:#64748b}

    /* SCADA tank card */
    .tank-card{background:linear-gradient(180deg,#0d1218 0%,#0a0e14 100%);border:1px solid #1f2a38;border-radius:14px;padding:14px 16px;position:relative;overflow:hidden}
    .tank-card.water{border-color:#164e63}
    .tank-card.oil{border-color:#7c2d12}
    .tank-card.warning{border-color:#92400e;box-shadow:0 0 0 1px #b45309 inset}
    .tank-card.alert{border-color:#991b1b;box-shadow:0 0 0 1px #b91c1c inset, 0 0 12px rgba(220,38,38,.18)}
    .tank-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:10px}
    .tank-id{font-size:.7rem;letter-spacing:.16em;font-family:ui-monospace,SFMono-Regular,monospace;color:#64748b;text-transform:uppercase}
    .tank-id b{color:#e2e8f0;font-weight:600;letter-spacing:.02em}
    .tank-medium{font-size:.62rem;letter-spacing:.18em;text-transform:uppercase;padding:2px 7px;border-radius:4px;font-weight:700}
    .tank-medium.water{background:#083344;color:#22d3ee;border:1px solid #155e75}
    .tank-medium.oil{background:#431407;color:#fb923c;border:1px solid #9a3412}
    .tank-medium.unknown{background:#1e293b;color:#94a3b8;border:1px solid #334155}
    .tank-status{font-size:.62rem;letter-spacing:.18em;text-transform:uppercase;padding:2px 8px;border-radius:4px;font-weight:700}
    .tank-status.active{background:rgba(16,185,129,.14);color:#34d399;border:1px solid #065f46}
    .tank-status.warning{background:rgba(245,158,11,.14);color:#fbbf24;border:1px solid #92400e}
    .tank-status.alert{background:rgba(239,68,68,.16);color:#f87171;border:1px solid #991b1b}
    .tank-status.lo{background:#1e293b;color:#94a3b8;border:1px solid #334155}

    .tank-body{display:grid;grid-template-columns:40px 1fr;gap:14px;align-items:stretch;margin-bottom:12px}
    .fill-col{position:relative;border-radius:6px;overflow:hidden;background:#050a0f;border:1px solid #1f2937;min-height:96px}
    .fill-col .fill{position:absolute;left:0;right:0;bottom:0;transition:height .5s cubic-bezier(.4,0,.2,1)}
    .fill-col .fill.water{background:linear-gradient(180deg,#22d3ee 0%,#0284c7 60%,#0c4a6e 100%)}
    .fill-col .fill.oil{background:linear-gradient(180deg,#fb923c 0%,#c2410c 60%,#431407 100%)}
    .fill-col .fill.unknown{background:linear-gradient(180deg,#94a3b8 0%,#475569 100%)}
    .fill-col .fill.alert{background:linear-gradient(180deg,#f87171 0%,#991b1b 100%)}
    .fill-col .tick{position:absolute;left:0;right:0;height:1px;background:rgba(148,163,184,.25)}
    .fill-col .tick.t25{bottom:25%}.fill-col .tick.t50{bottom:50%}.fill-col .tick.t75{bottom:75%}

    .tank-hero{display:flex;flex-direction:column;justify-content:center}
    .tank-pct{font-size:2.5rem;font-weight:800;letter-spacing:-.03em;line-height:1;font-variant-numeric:tabular-nums;color:#f1f5f9}
    .tank-pct.water{color:#67e8f9}
    .tank-pct.oil{color:#fdba74}
    .tank-pct.alert{color:#fca5a5}
    .tank-sub{font-size:.62rem;letter-spacing:.16em;text-transform:uppercase;color:#64748b;font-weight:600;margin-top:4px}
    .tank-sub b{color:#cbd5e1;font-weight:600;font-family:ui-monospace,SFMono-Regular,monospace;letter-spacing:.02em}

    .tank-row{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px}
    .tank-cell{background:rgba(15,23,42,.6);border:1px solid #1f2a38;border-radius:8px;padding:7px 10px}
    .tank-cell .l{font-size:.58rem;letter-spacing:.14em;text-transform:uppercase;color:#64748b;font-weight:700;margin-bottom:2px}
    .tank-cell .v{font-size:.95rem;font-weight:700;color:#e2e8f0;font-variant-numeric:tabular-nums;letter-spacing:-.01em}
    .tank-cell .v.up{color:#4ade80}
    .tank-cell .v.dn{color:#fbbf24}

    .tank-temps{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;padding-top:10px;border-top:1px solid #1f2a38}
    .tank-temps .c{display:flex;flex-direction:column;align-items:center;gap:2px}
    .tank-temps .c .l{font-size:.55rem;letter-spacing:.14em;text-transform:uppercase;color:#64748b;font-weight:700}
    .tank-temps .c .v{font-size:.85rem;font-weight:700;font-variant-numeric:tabular-nums;letter-spacing:-.01em;color:#e2e8f0}
    .tank-temps .c.min .v{color:#38bdf8}
    .tank-temps .c.max .v{color:#fb923c}
    .tank-actions{margin-top:10px;display:flex;gap:6px;padding-top:10px;border-top:1px solid #1f2a38}

    /* measurement tools */
    .tool-bar{position:absolute;top:8px;left:8px;z-index:20;display:flex;gap:4px;background:rgba(5,7,10,.85);border:1px solid #1f2630;padding:4px;border-radius:10px;backdrop-filter:blur(6px)}
    .tool-bar button{width:32px;height:32px;border-radius:6px;background:transparent;border:none;color:#cbd5e1;cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:.85rem;font-weight:700;transition:.1s}
    .tool-bar button:hover{background:#1a2030;color:#fff}
    .tool-bar button.active{background:#2563eb;color:#fff}
    .tool-bar button.danger:hover{background:#7f1d1d;color:#fff}
    .tool-bar .sep{width:1px;background:#1f2630;margin:2px 2px}
    .measure-panel{position:absolute;top:8px;right:8px;z-index:20;width:220px;max-height:calc(100% - 16px);overflow-y:auto;background:rgba(5,7,10,.88);border:1px solid #1f2630;border-radius:10px;backdrop-filter:blur(6px);padding:8px}
    .measure-panel .h{font-size:.62rem;letter-spacing:.14em;text-transform:uppercase;color:#64748b;font-weight:700;margin-bottom:6px;display:flex;justify-content:space-between;align-items:center}
    .measure-item{background:rgba(15,23,42,.7);border:1px solid #1f2630;border-radius:6px;padding:6px 8px;margin-bottom:5px;font-size:.72rem}
    .measure-item .tag{display:inline-flex;gap:6px;align-items:center;margin-bottom:4px;font-family:ui-monospace,SFMono-Regular,monospace}
    .measure-item .tag .swatch{width:10px;height:10px;border-radius:2px}
    .measure-item .row{display:flex;justify-content:space-between;color:#94a3b8;font-size:.67rem}
    .measure-item .row b{color:#f1f5f9;font-variant-numeric:tabular-nums;font-weight:700}
    .measure-item .x{float:right;color:#64748b;cursor:pointer;font-size:.7rem}
    .measure-item .x:hover{color:#f87171}

    .seg{display:inline-flex;border:1px solid #2a323d;border-radius:8px;overflow:hidden}
    .seg button{padding:.3rem .6rem;font-size:.72rem;background:#12161c;color:#e6e6e6;border:none;cursor:pointer}
    .seg button.active{background:#2563eb;color:#fff}
    .grid-bg{background-image:radial-gradient(#11161d 1px,transparent 1px);background-size:22px 22px}
    .k{font-family:ui-monospace,SFMono-Regular,monospace}
    .banner{background:linear-gradient(90deg,#581c87,#1e3a8a);border:1px solid #3730a3;border-radius:10px;padding:.5rem .75rem}
    .modal-bg{background:rgba(5,7,10,.7);backdrop-filter:blur(3px)}
    details summary{cursor:pointer;list-style:none}
    details summary::-webkit-details-marker{display:none}
    .arrow-up{color:#4ade80}.arrow-dn{color:#fbbf24}.arrow-zero{color:#64748b}

    /* Alerts floating panel (bottom-right of viewport) */
    .alerts-panel-fixed{position:fixed;right:14px;bottom:46px;z-index:60;width:330px;max-height:320px;background:rgba(5,7,10,.95);border:1px solid #334155;border-radius:12px;box-shadow:0 12px 40px rgba(0,0,0,.6);display:flex;flex-direction:column;backdrop-filter:blur(8px)}
    .alerts-panel-fixed.collapsed{height:36px;overflow:hidden}
    .alerts-panel-fixed .ap-head{display:flex;align-items:center;justify-content:space-between;padding:.45rem .75rem;border-bottom:1px solid #1f2630;cursor:pointer;user-select:none}
    .alerts-panel-fixed .ap-head .title{font-size:.68rem;letter-spacing:.16em;text-transform:uppercase;color:#cbd5e1;font-weight:700}
    .alerts-panel-fixed .ap-head .badge{background:#b91c1c;color:#fff;font-size:.6rem;padding:1px 6px;border-radius:999px;font-weight:700;min-width:16px;text-align:center}
    .alerts-panel-fixed .ap-body{flex:1;overflow-y:auto;padding:.5rem}
    .alert-item{background:rgba(15,23,42,.7);border:1px solid #1f2630;border-radius:8px;padding:6px 8px;margin-bottom:5px;font-size:.72rem}
    .alert-item.al{border-color:#991b1b;background:rgba(60,10,10,.5)}
    .alert-item.warn{border-color:#b45309}
    .alert-item .meta{display:flex;justify-content:space-between;margin-bottom:3px;font-family:ui-monospace,SFMono-Regular,monospace;font-size:.6rem}
    .alert-item .meta .kind{font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:#94a3b8}
    .alert-item.al .meta .kind{color:#f87171}
    .alert-item.warn .meta .kind{color:#fbbf24}
    .alert-item .meta .time{color:#64748b}
    .alert-item .msg{color:#e2e8f0;margin-bottom:4px}
    .alert-item .acts{display:flex;gap:4px;align-items:center}
    .alert-item .acts .btn{padding:.12rem .4rem;font-size:.6rem}
    .alert-item .pushed{font-size:.6rem;color:#34d399;letter-spacing:.1em;text-transform:uppercase}

    /* "+ Tank" tool button */
    .tool-bar button.add{background:#065f46;color:#d1fae5;width:auto;padding:0 .55rem;font-size:.7rem;letter-spacing:.04em}
    .tool-bar button.add:hover{background:#047857;color:#fff}
    .tool-bar button.add.active{background:#10b981;color:#fff}

    /* v1.7 — Tank Inspector overlay on live feed */
    .inspector-overlay{position:absolute;inset:0;pointer-events:none;z-index:15}
    .inspector-box{position:absolute;border:2px solid #38bdf8;box-shadow:0 0 0 9999px rgba(5,7,10,.55);border-radius:2px;transition:all .18s ease}
    .inspector-box.alert{border-color:#f87171;box-shadow:0 0 0 9999px rgba(40,5,5,.6),0 0 20px rgba(248,113,113,.5)}
    .inspector-line{position:absolute;height:0;border-top:2px dashed #fbbf24;left:0;right:0;display:flex;align-items:center;justify-content:center;pointer-events:none}
    .inspector-line .tag{background:#fbbf24;color:#000;font-size:.62rem;font-weight:800;padding:3px 8px;border-radius:3px;letter-spacing:.08em;transform:translateY(-50%);font-family:ui-monospace,SFMono-Regular,monospace}
    .inspector-line.secondary{border-top-color:#a855f7}
    .inspector-line.secondary .tag{background:#a855f7;color:#fff}
    .inspector-alarm-line{position:absolute;height:0;border-top:1px dashed #ef4444;left:0;right:0;opacity:.75}
    .inspector-alarm-line.lo{border-top-color:#f59e0b}
    .inspector-alarm-line .tag{position:absolute;right:2px;top:-8px;background:rgba(15,23,42,.85);color:#ef4444;font-size:.55rem;padding:1px 4px;border-radius:2px;letter-spacing:.1em;font-family:ui-monospace,SFMono-Regular,monospace}
    .inspector-alarm-line.lo .tag{color:#f59e0b}
    .inspector-close{position:absolute;pointer-events:auto;background:rgba(5,7,10,.85);border:1px solid #334155;color:#cbd5e1;font-size:.65rem;padding:4px 10px;border-radius:4px;cursor:pointer;font-weight:700;letter-spacing:.1em}
    .inspector-close:hover{background:#1e293b;color:#fff}

    /* Camera orientation banner (auto-rotate hint) */
    .hint-banner{background:linear-gradient(90deg,#0c4a6e,#1e3a8a);border:1px solid #0369a1;border-radius:10px;padding:.5rem .75rem;display:flex;align-items:center;gap:.5rem}

    /* Sparkline on tank card */
    .spark-row{margin-top:8px;padding-top:8px;border-top:1px solid #1f2a38;display:flex;align-items:center;gap:8px}
    .spark-row svg{flex:1;height:26px;width:100%}
    .spark-row .lbl{font-size:.55rem;letter-spacing:.14em;text-transform:uppercase;color:#64748b;font-weight:700;min-width:42px}

    /* Alarm pills on tank card */
    .alarm-pills{display:flex;gap:4px;flex-wrap:wrap}
    .alarm-pill{font-size:.55rem;letter-spacing:.14em;text-transform:uppercase;font-weight:800;padding:2px 6px;border-radius:3px;font-family:ui-monospace,SFMono-Regular,monospace}
    .alarm-pill.hi{background:rgba(220,38,38,.18);color:#fca5a5;border:1px solid #991b1b}
    .alarm-pill.lo{background:rgba(234,179,8,.18);color:#fde68a;border:1px solid #854d0e}

    /* Tank card inspect / why buttons */
    .tank-actions .btn.sm.inspect{background:#0c4a6e;border-color:#0369a1;color:#bae6fd}
    .tank-actions .btn.sm.inspect:hover{background:#075985}
    .tank-actions .btn.sm.inspect.active{background:#0284c7;color:#fff;border-color:#38bdf8}
    .tank-actions .btn.sm.why{background:#3b0764;border-color:#6b21a8;color:#e9d5ff}
    .tank-actions .btn.sm.why:hover{background:#581c87}

    /* "Why this reading?" modal — gradient trace */
    .why-panel{background:#0b1017;border:1px solid #1f2a38;border-radius:10px;padding:14px 16px}
    .why-panel .hd{font-size:.62rem;letter-spacing:.14em;text-transform:uppercase;color:#94a3b8;font-weight:700;margin-bottom:4px}
    .why-panel .val{font-size:1rem;font-weight:700;color:#e2e8f0;font-variant-numeric:tabular-nums}
    .why-trace{background:#05080c;border:1px solid #1f2a38;border-radius:8px;padding:8px}
    .why-bar{height:8px;border-radius:999px;background:#0f172a;overflow:hidden;margin-top:3px}
    .why-bar .fill{height:100%;background:linear-gradient(90deg,#22d3ee,#6366f1,#a855f7)}
    .why-bar .fill.warn{background:linear-gradient(90deg,#f59e0b,#dc2626)}

    /* Camera orientation section in Settings */
    .cam-orient-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:6px}
    .cam-orient-grid button{padding:.4rem .25rem;border-radius:6px;font-size:.7rem;background:#12161c;border:1px solid #2a323d;color:#cbd5e1;cursor:pointer;display:flex;flex-direction:column;align-items:center;gap:2px;font-weight:600}
    .cam-orient-grid button:hover{background:#1a2030;color:#fff}
    .cam-orient-grid button.active{background:#1d4ed8;border-color:#2563eb;color:#fff}
    .cam-orient-grid button .ic{font-size:1.2rem;font-weight:700;line-height:1}
  </style>
</head>
<body class="h-full grid-bg">
<div x-data="app()" x-init="boot()" x-cloak class="h-full flex flex-col">

<!-- Top bar -->
<header class="flex items-center justify-between px-4 py-3 border-b border-[#1f2630] bg-[#07090d]/90 backdrop-blur">
  <div class="flex items-center gap-3">
    <div class="w-9 h-9 rounded-lg bg-gradient-to-br from-orange-500 via-rose-500 to-indigo-500 flex items-center justify-center font-bold">T</div>
    <div>
      <div class="text-sm font-semibold tracking-wide" x-text="config?.ui?.title || 'Thermal Tank Monitor'"></div>
    </div>
  </div>
  <div class="flex items-center gap-2 flex-wrap">
    <span class="pill flex items-center gap-2"><span class="dot" :class="live?'ok':'err'"></span><span x-text="live?'live':'offline'"></span></span>
    <span class="pill flex items-center gap-2" x-show="config?.calibration?.range_locked">
      <span class="dot ok"></span>calibrated
      <span class="text-slate-400 k" x-text="'+/-'+(config?.ui?.emissivity||'-')+' e'"></span>
    </span>
    <span class="pill flex items-center gap-2" x-show="!config?.calibration?.range_locked">
      <span class="dot warn"></span>uncalibrated
    </span>
    <button class="btn primary" @click="openDetectModal()">Auto-detect</button>
    <button class="btn success" @click="runCalibrate()" :disabled="calibrating" x-text="calibrating?'Calibrating...':'Calibrate'"></button>
    <button class="btn" @click="snapshot()">Snapshot</button>
    <button class="btn" :class="recording.recording?'rec':''" @click="toggleRecord()" x-text="recording.recording ? 'Stop Rec' : 'Record'"></button>
    <button class="btn" @click="panel = panel==='settings'?null:'settings'" :class="panel==='settings'?'primary':''">Settings</button>
  </div>
</header>

<!-- Calibration banner -->
<div class="px-4 pt-2" x-show="banner" x-transition>
  <div class="banner text-xs flex items-center gap-2">
    <span>i</span>
    <span x-text="banner"></span>
    <button class="btn ml-auto" @click="banner=null">dismiss</button>
  </div>
</div>

<!-- Auto-rotate hint banner -->
<div class="px-4 pt-2" x-show="rotateHintVisible()" x-transition>
  <div class="hint-banner text-xs">
    <span class="text-base">&#8634;</span>
    <span>
      Thermal gradient looks stronger horizontally
      (<b x-text="(state.rotate_hint?.ratio_horizontal_to_vertical||0).toFixed(2)"></b>&times;).
      The camera may need to be rotated <b x-text="state.rotate_hint?.suggested + '&deg;'"></b>.
    </span>
    <button class="btn ml-auto" @click="applyRotateHint()">Apply <span x-text="state.rotate_hint?.suggested+'&deg;'"></span></button>
    <button class="btn" @click="dismissRotateHint()">dismiss</button>
  </div>
</div>

<!-- Main 3-pane layout -->
<main class="flex-1 grid grid-cols-[1fr_420px] gap-3 p-3 min-h-0">

  <!-- LEFT: stream + drawing tools -->
  <section class="card overflow-hidden relative flex flex-col">
    <div class="flex items-center justify-between px-3 py-2 border-b border-[#1f2630] text-xs">
      <div class="flex items-center gap-2">
        <span class="font-semibold">LIVE</span>
        <span class="text-slate-400 k" x-text="'frame '+state.frame_idx"></span>
        <span class="text-slate-400 k" x-text="'sensor '+state.w+'x'+state.h+' (' + (state.upscale||1) + 'x)'"></span>
        <span class="text-slate-400 k" x-text="'min '+fmt(state.tmin,1)+' / max '+fmt(state.tmax,1)+' C'"></span>
      </div>
      <div class="flex items-center gap-1">
        <div class="seg">
          <template x-for="p in ['iron','rainbow','hot','inferno','plasma','magma','jet','turbo','cividis','grayscale']" :key="p">
            <button @click="patch({stream:{palette:p}})" :class="config?.stream?.palette===p?'active':''" x-text="p"></button>
          </template>
        </div>
        <div class="seg ml-2">
          <button :class="config?.stream?.source==='thermal'?'active':''" @click="patch({stream:{source:'thermal'}})">thermal</button>
          <button :class="config?.stream?.source==='visual'?'active':''"  @click="patch({stream:{source:'visual'}})">visual</button>
          <button :class="config?.stream?.source==='blend'?'active':''"   @click="patch({stream:{source:'blend'}})">blend</button>
        </div>
      </div>
    </div>

    <div class="stream-wrap flex-1 min-h-0 bg-black relative">
      <img id="mjpeg-img" :src="streamUrl" alt="thermal stream" @load="onImgLoad()"/>

      <!-- Measurement tool bar -->
      <div class="tool-bar" @mousedown.stop @click.stop>
        <button :class="tool==='select'?'active':''"  @click="setTool('select')"  title="Select / pan">S</button>
        <button :class="tool==='point'?'active':''"   @click="setTool('point')"   title="Point">&bull;</button>
        <button :class="tool==='line'?'active':''"    @click="setTool('line')"    title="Line">/</button>
        <button :class="tool==='box'?'active':''"     @click="setTool('box')"     title="Box">[ ]</button>
        <button :class="tool==='polygon'?'active':''" @click="setTool('polygon')" title="Polygon (click to add, dblclick to close, Esc to cancel)">&#9699;</button>
        <div class="sep"></div>
        <button class="add" :class="tool==='add_tank'?'active':''" @click="setTool('add_tank')" title="Draw a perimeter on the live feed to add a new tank (drag a rectangle)">+ Tank</button>
        <div class="sep"></div>
        <button class="danger" @click="clearMeasurements()" title="Clear all measurements">X</button>
      </div>

      <!-- Measurements list -->
      <div class="measure-panel" x-show="measurements.length">
        <div class="h">
          <span>Measurements</span>
          <span class="k" x-text="measurements.length"></span>
        </div>
        <template x-for="m in measurements" :key="m.id">
          <div class="measure-item">
            <div class="tag">
              <span class="swatch" :style="'background:'+m.color"></span>
              <span x-text="m.kind.toUpperCase() + ' #' + m.label"></span>
              <span class="x" @click="removeMeasurement(m.id)">&times;</span>
            </div>
            <div class="row"><span>min</span><b x-text="fmt(m.min,1)+' C'"></b></div>
            <div class="row"><span>avg</span><b x-text="fmt(m.avg,1)+' C'"></b></div>
            <div class="row"><span>max</span><b x-text="fmt(m.max,1)+' C'"></b></div>
            <div class="row" x-show="m.count > 1"><span>px</span><b x-text="m.count"></b></div>
          </div>
        </template>
      </div>

      <!-- Drawing canvas overlay -->
      <canvas id="draw-canvas" class="draw"
              :class="tool==='select'?'idle':''"
              @mousedown="onDown($event)"
              @mousemove="onMove($event)"
              @mouseup="onUp($event)"
              @dblclick="onDblClick($event)"
              @contextmenu.prevent="cancelDraft()"></canvas>

      <!-- Detected-candidate overlay -->
      <div x-show="detect.show" class="absolute inset-0 pointer-events-none" x-transition>
        <template x-for="c in detect.candidates" :key="c.id">
          <div class="absolute border-2 border-emerald-400/80"
               :style="candidateStyle(c)">
            <div class="absolute -top-6 left-0 text-[11px] bg-emerald-600/90 px-1 rounded k" x-text="c.name + ' . ' + c.medium + ' (' + Math.round(c.medium_confidence*100) + '%)'"></div>
          </div>
        </template>
      </div>

      <!-- Tank Inspector overlay (v1.7) — click any tank card's "Inspect"
           button to highlight its perimeter on the live feed with a dashed
           level line and a floating "% · FT · BBL" label, plus optional
           HI/LO alarm guide lines. -->
      <div class="inspector-overlay" x-show="inspector.tankId" x-transition>
        <template x-if="inspectedTank()">
          <div>
            <div class="inspector-box" :class="inspectorBoxCls()" :style="inspectorBoxStyle()"></div>
            <!-- primary level line -->
            <div class="inspector-line" :style="inspectorLineStyle('primary')">
              <span class="tag" x-text="inspectorPrimaryLabel()"></span>
            </div>
            <!-- secondary layer (sludge) when multi_layer on -->
            <template x-if="inspectorHasSecondary()">
              <div class="inspector-line secondary" :style="inspectorLineStyle('secondary')">
                <span class="tag" x-text="inspectorSecondaryLabel()"></span>
              </div>
            </template>
            <!-- HI / LO alarm guides -->
            <template x-if="inspectorAlarmPct('hi') != null">
              <div class="inspector-alarm-line" :style="inspectorAlarmLineStyle('hi')">
                <span class="tag" x-text="'HI ' + inspectorAlarmPct('hi').toFixed(0) + '%'"></span>
              </div>
            </template>
            <template x-if="inspectorAlarmPct('lo') != null">
              <div class="inspector-alarm-line lo" :style="inspectorAlarmLineStyle('lo')">
                <span class="tag" x-text="'LO ' + inspectorAlarmPct('lo').toFixed(0) + '%'"></span>
              </div>
            </template>
            <button class="inspector-close" :style="inspectorCloseStyle()" @click="closeInspector()">CLOSE</button>
          </div>
        </template>
      </div>
    </div>
  </section>

  <!-- RIGHT: SCADA tank cards -->
  <aside class="flex flex-col gap-3 min-h-0 overflow-y-auto pr-1">
    <template x-for="t in state.results" :key="t.id">
      <div class="tank-card" :class="tankCardClass(t)">
        <div class="tank-head">
          <div class="tank-id"><b x-text="t.id.toUpperCase().replace('_','-')"></b></div>
          <div class="flex items-center gap-2">
            <div class="alarm-pills">
              <span class="alarm-pill hi" x-show="t.alarms?.hi" title="HI alarm tripped">HI</span>
              <span class="alarm-pill lo" x-show="t.alarms?.lo" title="LO alarm tripped">LO</span>
            </div>
            <div class="tank-status" :class="tankStatus(t).klass" x-text="tankStatus(t).label"></div>
          </div>
        </div>

        <div class="tank-body">
          <!-- vertical fill bar -->
          <div class="fill-col">
            <div class="tick t25"></div><div class="tick t50"></div><div class="tick t75"></div>
            <div class="fill" :class="fillColorClass(t)"
                 :style="'height:' + Math.max(0, Math.min(100, t.level_pct||0)) + '%'"></div>
          </div>
          <div class="tank-hero">
            <div class="tank-pct" :class="pctColorClass(t)"
                 x-text="(t.level_pct!=null ? t.level_pct.toFixed(1) : '--') + '%'"></div>
            <div class="tank-sub">
              <span>OF </span><b x-text="(t.geometry?.height_ft||'--') + ' FT'"></b>
              <span x-show="t.reading?.volume_bbl != null"> &middot; </span>
              <b x-show="t.reading?.volume_bbl != null"
                 x-text="Math.round(t.reading?.volume_bbl||0).toLocaleString() + ' BBL'"></b>
            </div>
            <div class="tank-sub" style="margin-top:2px">
              <span>TOTAL VOLUME CAPACITY</span>
              <b x-show="t.reading?.volume_full_bbl != null" style="margin-left:6px"
                 x-text="Math.round(t.reading?.volume_full_bbl||0).toLocaleString() + ' BBL'"></b>
            </div>
          </div>
        </div>

        <div class="tank-row">
          <div class="tank-cell">
            <div class="l">Fill Rate</div>
            <div class="v" :class="rateClass(t)" x-text="rateLabel(t)"></div>
          </div>
          <div class="tank-cell">
            <div class="l">ETA <span x-text="etaDir(t)"></span></div>
            <div class="v" x-text="etaLabel(t)"></div>
          </div>
        </div>

        <div class="tank-temps">
          <div class="c min"><div class="l">Min</div><div class="v" x-text="fmt(t.temp_min,1)+'&deg;C'"></div></div>
          <div class="c"><div class="l">Avg</div><div class="v" x-text="fmt(t.temp_avg,1)+'&deg;C'"></div></div>
          <div class="c max"><div class="l">Max</div><div class="v" x-text="fmt(t.temp_max,1)+'&deg;C'"></div></div>
        </div>

        <!-- Sparkline: last ~30 minutes of level_pct sampled client-side. -->
        <div class="spark-row" x-show="sparkLine(t.id).length >= 2">
          <span class="lbl">30 min</span>
          <svg viewBox="0 0 100 26" preserveAspectRatio="none">
            <polyline fill="none" stroke-width="1.4" :stroke="sparkStroke(t)"
                      :points="sparkPoints(t.id)"></polyline>
          </svg>
        </div>

        <details class="mt-2 text-[11px] text-slate-400">
          <summary class="hover:text-slate-200">geometry &amp; roi</summary>
          <div class="k mt-1 leading-5" x-show="t.geometry">
            <div>height <span x-text="t.geometry?.height_ft"></span> ft &middot; D <span x-text="t.geometry?.diameter_ft"></span> ft &middot; <span x-text="t.geometry?.shape"></span></div>
            <div x-show="t.reading">full <span x-text="fmt(t.reading?.volume_full_bbl,0)"></span> bbl &middot; ullage <span x-text="fmt(t.reading?.ullage_ft,1)"></span> ft</div>
            <div x-show="t.alarms?.hi_pct != null || t.alarms?.lo_pct != null">
              alarms: HI <span x-text="t.alarms?.hi_pct != null ? t.alarms.hi_pct.toFixed(0)+'%' : '—'"></span>
              &middot; LO <span x-text="t.alarms?.lo_pct != null ? t.alarms.lo_pct.toFixed(0)+'%' : '—'"></span>
            </div>
          </div>
          <div class="k mt-1" x-text="'roi x=' + t.roi?.x + ' y=' + t.roi?.y + ' w=' + t.roi?.w + ' h=' + t.roi?.h"></div>
        </details>

        <div class="tank-actions">
          <button class="btn sm inspect"
                  :class="inspector.tankId===t.id?'active':''"
                  @click="toggleInspector(t.id)"
                  title="Highlight perimeter + level line on live feed">
            <span x-show="inspector.tankId!==t.id">Inspect</span>
            <span x-show="inspector.tankId===t.id">Hide</span>
          </button>
          <button class="btn sm why" @click="openWhy(t.id)" title="Why is the detector reporting this level?">Why?</button>
          <button class="btn sm" @click="editTank(t)">Edit</button>
          <button class="btn sm" @click="removeTank(t.id)">Remove</button>
        </div>
      </div>
    </template>
    <template x-if="!state.results?.length">
      <div class="card p-4 text-center text-slate-400 text-sm">
        No tanks configured yet. Use <span class="k text-emerald-400">+ Tank</span> to draw a perimeter, or <span class="k">Auto-detect</span>.
      </div>
    </template>
  </aside>
</main>

<!-- Alerts / Events floating panel (bottom-right) -->
<div class="alerts-panel-fixed" :class="alerts.collapsed?'collapsed':''">
  <div class="ap-head" @click="alerts.collapsed=!alerts.collapsed">
    <div class="flex items-center gap-2">
      <span class="dot" :class="unackCount()?'err':'idle'"></span>
      <span class="title">Alerts &amp; Events</span>
      <span class="badge" x-show="unackCount()" x-text="unackCount()"></span>
    </div>
    <div class="flex items-center gap-2">
      <button class="btn sm" @click.stop="clearAlerts()" x-show="alerts.items.length" title="Clear list">clear</button>
      <span class="k text-slate-400 text-[.6rem]" x-text="alerts.collapsed?'show':'hide'"></span>
    </div>
  </div>
  <div class="ap-body" x-show="!alerts.collapsed">
    <template x-if="!alerts.items.length">
      <div class="text-slate-500 text-[.72rem] text-center py-3">No recent alerts.</div>
    </template>
    <template x-for="a in alerts.items" :key="a.seq">
      <div class="alert-item" :class="alertCls(a)">
        <div class="meta">
          <span class="kind" x-text="(a.kind||'').replace(/_/g,' ')"></span>
          <span class="time" x-text="fmtAlertTime(a.ts)"></span>
        </div>
        <div class="msg" x-text="alertMessage(a)"></div>
        <div class="acts">
          <button class="btn" @click="pushAlertToNR(a)" x-show="!a._pushed" title="POST to Node-RED supervisor">Push NR</button>
          <span class="pushed" x-show="a._pushed">pushed</span>
          <button class="btn" @click="ackAlert(a.seq)" x-show="!a._ack">Ack</button>
          <span class="pushed" x-show="a._ack" style="color:#94a3b8">ack</span>
        </div>
      </div>
    </template>
  </div>
</div>

<!-- Bottom controls -->
<footer class="border-t border-[#1f2630] bg-[#07090d]/90 backdrop-blur px-4 py-2 text-[11px] text-slate-400 flex items-center justify-between">
  <div class="flex items-center gap-3">
    <span>Operator Console v1.7</span>
    <span class="k" x-show="config?.calibration?.calibrated_at" x-text="'calibrated ' + config?.calibration?.calibrated_at"></span>
  </div>
  <div class="flex items-center gap-3">
    <span class="k">tool: <b x-text="tool"></b></span>
    <span class="k">measurements: <b x-text="measurements.length"></b></span>
    <a class="hover:underline" :href="supervisorUrl" target="_blank">Supervisor dashboard -></a>
  </div>
</footer>

<!-- Auto-detect modal -->
<div x-show="detect.modal" x-transition class="fixed inset-0 z-50 modal-bg flex items-center justify-center p-6">
  <div class="card w-full max-w-3xl p-5 max-h-[85vh] overflow-y-auto">
    <div class="flex items-center justify-between mb-3">
      <h2 class="text-lg font-semibold">Auto-detect tanks</h2>
      <button class="btn" @click="detect.modal=false;detect.show=false">Close</button>
    </div>
    <p class="text-sm text-slate-400 mb-3">
      We sampled <span x-text="detect.framesUsed"></span> frames and found <span x-text="detect.candidates.length"></span> candidate(s).
      Green boxes on the live feed show the detected perimeters — verify each before accepting.
    </p>
    <div class="flex gap-2 mb-3 flex-wrap">
      <button class="btn primary" @click="runDetect()" :disabled="detect.running" x-text="detect.running?'Scanning...':'Re-scan'"></button>
      <button class="btn success" @click="acceptDetect()" :disabled="!detect.candidates.length">Accept &amp; save</button>
      <div class="seg">
        <button :class="detect.unit==='ft'?'active':''" @click="detect.unit='ft'">ft</button>
        <button :class="detect.unit==='in'?'active':''" @click="detect.unit='in'">in</button>
      </div>
      <span class="text-[11px] text-slate-500 self-center">Height unit for full-scale</span>
    </div>
    <table class="w-full text-xs">
      <thead class="text-left text-slate-400">
        <tr>
          <th class="p-1">#</th><th>Name</th><th>Medium</th>
          <th>Topic</th>
          <th>Full-scale (<span x-text="detect.unit"></span>)</th>
          <th>Dia. ft</th>
          <th>Perimeter [x,y w&times;h]</th>
          <th>Conf.</th>
        </tr>
      </thead>
      <tbody>
        <template x-for="(c,i) in detect.candidates" :key="c.id">
          <tr class="border-t border-[#1f2630] align-top">
            <td class="p-1 k" x-text="i+1"></td>
            <td><input class="bg-black/40 border border-[#1f2630] rounded px-1 py-0.5 w-24" x-model="c.name"></td>
            <td>
              <select class="bg-black/40 border border-[#1f2630] rounded px-1 py-0.5" x-model="c.medium">
                <option value="water">water</option>
                <option value="oil">oil</option>
                <option value="unknown">unknown</option>
              </select>
            </td>
            <td><input class="bg-black/40 border border-[#1f2630] rounded px-1 py-0.5 w-44 k" x-model="c.topic"></td>
            <td><input type="number" step="0.5" min="0" class="bg-black/40 border border-[#1f2630] rounded px-1 py-0.5 w-20"
                       :value="detect.unit==='in' ? (c.geometry.height_ft*12).toFixed(1) : c.geometry.height_ft"
                       @change="c.geometry.height_ft = detect.unit==='in' ? (Number($event.target.value)/12) : Number($event.target.value)"></td>
            <td><input type="number" step="0.5" class="bg-black/40 border border-[#1f2630] rounded px-1 py-0.5 w-20" x-model.number="c.geometry.diameter_ft"></td>
            <td>
              <div class="flex gap-1">
                <input type="number" min="0" title="x"
                       class="bg-black/40 border border-[#1f2630] rounded px-1 py-0.5 w-14 k" x-model.number="c.roi.x">
                <input type="number" min="0" title="y"
                       class="bg-black/40 border border-[#1f2630] rounded px-1 py-0.5 w-14 k" x-model.number="c.roi.y">
                <input type="number" min="1" title="w"
                       class="bg-black/40 border border-[#1f2630] rounded px-1 py-0.5 w-14 k" x-model.number="c.roi.w">
                <input type="number" min="1" title="h"
                       class="bg-black/40 border border-[#1f2630] rounded px-1 py-0.5 w-14 k" x-model.number="c.roi.h">
              </div>
            </td>
            <td class="k" x-text="Math.round((c.medium_confidence||0)*100)+'%'"></td>
          </tr>
        </template>
      </tbody>
    </table>
  </div>
</div>

<!-- Settings drawer (right slide-in) -->
<div x-show="panel==='settings'" x-transition.opacity class="fixed inset-0 z-40 modal-bg" @click="panel=null"></div>
<aside x-show="panel==='settings'" x-transition:enter="transition transform duration-200" x-transition:enter-start="translate-x-full" x-transition:enter-end="translate-x-0"
       x-transition:leave="transition transform duration-150" x-transition:leave-start="translate-x-0" x-transition:leave-end="translate-x-full"
       class="fixed top-0 right-0 z-50 h-full w-[380px] bg-[#0a0e14] border-l border-[#1f2630] shadow-2xl overflow-y-auto">
  <div class="sticky top-0 bg-[#0a0e14] border-b border-[#1f2630] px-4 py-3 flex items-center justify-between z-10">
    <div>
      <div class="text-sm font-semibold">Settings</div>
      <div class="text-[11px] text-slate-400 k">
        <span x-text="siteId"></span> &middot; <span x-text="deviceHost"></span> &middot; <span x-text="fpsLabel"></span>
      </div>
    </div>
    <button class="btn sm" @click="panel=null">Close</button>
  </div>

  <div class="p-4 space-y-5 text-xs">
    <!-- Tanks manager -->
    <section>
      <div class="text-slate-400 uppercase tracking-wider text-[10px] mb-2">Tanks</div>
      <div class="flex items-center justify-between mb-2">
        <div><b class="text-base" x-text="(config?.tanks||[]).length"></b> configured</div>
        <div class="flex gap-1">
          <button class="btn sm" @click="panel=null; setTool('add_tank')" title="Draw a perimeter on the live feed">+ Draw</button>
          <button class="btn sm" @click="addBlankTank()" title="Append a default-sized tank (edit to adjust)">+ Blank</button>
          <button class="btn sm primary" @click="panel=null; openDetectModal()">Auto</button>
        </div>
      </div>
      <div class="flex gap-2 items-center text-[11px] mb-3">
        <span class="text-slate-400">Number of tanks</span>
        <select class="bg-black/40 border border-[#1f2630] rounded px-2 py-1"
                @change="setTankCount(Number($event.target.value))"
                :value="(config?.tanks||[]).length">
          <template x-for="n in [1,2,3,4,5,6]" :key="n">
            <option :value="n" x-text="n + (n===1?' tank':' tanks')"></option>
          </template>
        </select>
      </div>
      <div class="flex flex-col gap-1" x-show="(config?.tanks||[]).length">
        <template x-for="t in (config?.tanks || [])" :key="t.id">
          <div class="flex items-center justify-between bg-black/30 border border-[#1f2630] rounded px-2 py-1 text-[11px]">
            <div class="k truncate" style="max-width:220px"
                 x-text="t.id + ' - ' + (t.geometry?.height_ft||'?') + 'ft'"></div>
            <div class="flex gap-1">
              <button class="btn sm" @click="panel=null; editTank(t)">Edit</button>
              <button class="btn sm" @click="removeTank(t.id)">x</button>
            </div>
          </div>
        </template>
      </div>
      <p class="text-[10px] text-slate-500 mt-2">Tip: pick <b>+ Draw</b> then drag a rectangle on the live feed.
      Per-tank scale (0-100% = 0-X ft/in) is set in the Edit dialog.</p>
    </section>

    <!-- Camera orientation (rotate + flip) — applied live, no restart -->
    <section>
      <div class="text-slate-400 uppercase tracking-wider text-[10px] mb-2">Camera orientation</div>
      <div class="cam-orient-grid mb-2">
        <template x-for="r in [0,90,180,270]" :key="r">
          <button :class="(config?.stream?.rotate||0)===r?'active':''"
                  @click="patch({stream:{rotate:r}})"
                  :title="'Rotate '+r+'&deg;'">
            <span class="ic" x-text="r===0?'&#8593;':(r===90?'&#8594;':(r===180?'&#8595;':'&#8592;'))"></span>
            <span x-text="r + '&deg;'"></span>
          </button>
        </template>
      </div>
      <div class="flex gap-3 items-center">
        <label class="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" :checked="!!config?.stream?.flip_h"
                 @change="patch({stream:{flip_h: $event.target.checked}})">
          <span>Flip horizontal</span>
        </label>
        <label class="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" :checked="!!config?.stream?.flip_v"
                 @change="patch({stream:{flip_v: $event.target.checked}})">
          <span>Flip vertical</span>
        </label>
      </div>
      <p class="text-[10px] text-slate-500 mt-2">Applied live (no restart). If the auto-hint says
        the scene looks horizontal, rotate 90&deg; so the liquid/air interface is vertical.</p>
    </section>

    <!-- Level unit (moved here from top bar) -->
    <section>
      <div class="text-slate-400 uppercase tracking-wider text-[10px] mb-2">Level display unit</div>
      <div class="seg">
        <button :class="unit==='ft'?'active':''" @click="setUnit('ft')">feet</button>
        <button :class="unit==='in'?'active':''" @click="setUnit('in')">inches</button>
      </div>
      <p class="text-[10px] text-slate-500 mt-1">Applies to tank cards and the Edit dialog scale input.</p>
    </section>

    <!-- Overlay toggles -->
    <section>
      <div class="text-slate-400 uppercase tracking-wider text-[10px] mb-2">Stream overlays</div>
      <template x-for="k in overlayKeys" :key="k">
        <label class="flex items-center justify-between py-1">
          <span class="capitalize" x-text="k.replace(/_/g,' ')"></span>
          <input type="checkbox" :checked="config?.stream?.overlay?.[k]"
                 @change="patch({stream:{overlay:{[k]: $event.target.checked}}})">
        </label>
      </template>
    </section>

    <!-- Display timezone -->
    <section>
      <div class="text-slate-400 uppercase tracking-wider text-[10px] mb-2">Overlay timezone</div>
      <input class="w-full bg-black/40 border border-[#1f2630] rounded px-2 py-1"
             placeholder="America/Chicago"
             :value="config?.stream?.overlay?.display_tz || ''"
             @change="patch({stream:{overlay:{display_tz: $event.target.value || null}}})">
      <p class="text-[10px] text-slate-500 mt-1">IANA name. Blank = container local tz.</p>
    </section>

    <!-- Publisher -->
    <section>
      <div class="text-slate-400 uppercase tracking-wider text-[10px] mb-2">Node-RED publisher</div>
      <label class="flex flex-col gap-1 mb-2"><span class="text-slate-400">Endpoint</span>
        <input class="bg-black/40 border border-[#1f2630] rounded px-2 py-1 k"
               :value="config?.publisher?.endpoint || ''"
               @change="patch({publisher:{endpoint: $event.target.value}})">
      </label>
      <label class="flex flex-col gap-1"><span class="text-slate-400">Timeout (s)</span>
        <input type="number" step="0.5" class="bg-black/40 border border-[#1f2630] rounded px-2 py-1"
               :value="config?.publisher?.timeout || 3"
               @change="patch({publisher:{timeout: Number($event.target.value)}})">
      </label>
      <p class="text-[10px] text-slate-500 mt-1">https:// URLs are supported. Each tank payload includes its <b>topic</b> for Node-RED routing.</p>
    </section>

    <!-- Capture -->
    <section>
      <div class="text-slate-400 uppercase tracking-wider text-[10px] mb-2">Capture</div>
      <div class="flex gap-2">
        <button class="btn sm" @click="snapshot()">Snapshot now</button>
        <button class="btn sm" :class="recording.recording?'rec':''" @click="toggleRecord()"
                x-text="recording.recording?'Stop recording':'Start recording'"></button>
      </div>
      <p class="text-[10px] text-slate-500 mt-1">Files land in <span class="k">/app/data/</span> on the Nucleus.</p>
    </section>

    <!-- About -->
    <section class="text-[10px] text-slate-500 pt-2 border-t border-[#1f2630]">
      Operator Console v1.7 &middot; stream <span x-text="fpsLabel"></span> &middot; sensor
      <span x-text="state.w+'x'+state.h"></span>
    </section>
  </div>
</aside>

<!-- Tank edit modal -->
<div x-show="editor.show" x-transition class="fixed inset-0 z-50 modal-bg flex items-center justify-center p-6">
  <div class="card w-full max-w-lg p-5">
    <div class="flex items-center justify-between mb-3">
      <h2 class="text-lg font-semibold">Edit tank</h2>
      <button class="btn" @click="editor.show=false">Close</button>
    </div>
    <div class="grid grid-cols-2 gap-3 text-sm">
      <label class="flex flex-col gap-1"><span class="text-slate-400 text-xs">Name</span>
        <input class="bg-black/40 border border-[#1f2630] rounded px-2 py-1" x-model="editor.tank.name">
      </label>
      <label class="flex flex-col gap-1"><span class="text-slate-400 text-xs">Medium</span>
        <select class="bg-black/40 border border-[#1f2630] rounded px-2 py-1" x-model="editor.tank.medium">
          <option value="water">water</option>
          <option value="oil">oil</option>
          <option value="unknown">unknown</option>
        </select>
      </label>
      <label class="flex flex-col gap-1 col-span-2"><span class="text-slate-400 text-xs">Node-RED topic (routing label)</span>
        <input class="bg-black/40 border border-[#1f2630] rounded px-2 py-1 k" placeholder="nucleus/n-1065/water_tank_1" x-model="editor.tank.topic">
      </label>

      <!-- Scale calibration: 0-100% maps to 0-Height in selected unit -->
      <label class="flex flex-col gap-1"><span class="text-slate-400 text-xs">Height unit</span>
        <select class="bg-black/40 border border-[#1f2630] rounded px-2 py-1" x-model="editor.heightUnit">
          <option value="ft">feet</option>
          <option value="in">inches</option>
        </select>
      </label>
      <label class="flex flex-col gap-1"><span class="text-slate-400 text-xs">Height (full-scale of 100%)</span>
        <input type="number" step="0.1" min="0" class="bg-black/40 border border-[#1f2630] rounded px-2 py-1" x-model.number="editor.heightValue">
      </label>
      <label class="flex flex-col gap-1"><span class="text-slate-400 text-xs">Diameter ft</span>
        <input type="number" step="0.5" class="bg-black/40 border border-[#1f2630] rounded px-2 py-1" x-model.number="editor.tank.geometry.diameter_ft">
      </label>
      <label class="flex flex-col gap-1"><span class="text-slate-400 text-xs">Min temp delta C (confidence gate)</span>
        <input type="number" step="0.1" class="bg-black/40 border border-[#1f2630] rounded px-2 py-1" x-model.number="editor.tank.min_temp_delta">
      </label>

      <!-- Alarm thresholds -->
      <div class="col-span-2 pt-2 border-t border-[#1f2630]">
        <div class="text-slate-400 text-xs mb-2 uppercase tracking-wider">Alarm thresholds (%)</div>
        <div class="grid grid-cols-2 gap-2">
          <label class="flex flex-col gap-1">
            <span class="text-slate-500 text-[10px]">HI alarm (%) — trip when level &ge;</span>
            <input type="number" min="0" max="100" step="1" placeholder="e.g. 90"
                   class="bg-black/40 border border-[#1f2630] rounded px-2 py-1"
                   :value="editor.tank.alarms?.hi_pct ?? ''"
                   @change="editor.tank.alarms = Object.assign({}, editor.tank.alarms, {hi_pct: $event.target.value === '' ? null : Number($event.target.value)})">
          </label>
          <label class="flex flex-col gap-1">
            <span class="text-slate-500 text-[10px]">LO alarm (%) — trip when level &le;</span>
            <input type="number" min="0" max="100" step="1" placeholder="e.g. 10"
                   class="bg-black/40 border border-[#1f2630] rounded px-2 py-1"
                   :value="editor.tank.alarms?.lo_pct ?? ''"
                   @change="editor.tank.alarms = Object.assign({}, editor.tank.alarms, {lo_pct: $event.target.value === '' ? null : Number($event.target.value)})">
          </label>
        </div>
        <p class="text-[10px] text-slate-500 mt-1">Blank = disabled. Crossing events fire in the Alerts panel and on the Inspector overlay.</p>
      </div>

      <!-- Multi-layer detection toggle -->
      <div class="col-span-2">
        <label class="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" :checked="!!editor.tank.multi_layer"
                 @change="editor.tank.multi_layer = $event.target.checked">
          <span class="text-slate-300">Multi-layer detection (air · product · water · sludge)</span>
        </label>
        <p class="text-[10px] text-slate-500 mt-1 ml-6">Looks for a secondary gradient peak (e.g. oil/water interface). Adds a purple line in the Inspector.</p>
      </div>

      <!-- Perimeter / ROI -->
      <div class="col-span-2 pt-2 border-t border-[#1f2630]">
        <div class="text-slate-400 text-xs mb-2 uppercase tracking-wider">Perimeter (pixel ROI)</div>
        <div class="grid grid-cols-4 gap-2">
          <label class="flex flex-col gap-1"><span class="text-slate-500 text-[10px]">x</span>
            <input type="number" min="0" class="bg-black/40 border border-[#1f2630] rounded px-2 py-1" x-model.number="editor.tank.roi.x">
          </label>
          <label class="flex flex-col gap-1"><span class="text-slate-500 text-[10px]">y</span>
            <input type="number" min="0" class="bg-black/40 border border-[#1f2630] rounded px-2 py-1" x-model.number="editor.tank.roi.y">
          </label>
          <label class="flex flex-col gap-1"><span class="text-slate-500 text-[10px]">w</span>
            <input type="number" min="1" class="bg-black/40 border border-[#1f2630] rounded px-2 py-1" x-model.number="editor.tank.roi.w">
          </label>
          <label class="flex flex-col gap-1"><span class="text-slate-500 text-[10px]">h</span>
            <input type="number" min="1" class="bg-black/40 border border-[#1f2630] rounded px-2 py-1" x-model.number="editor.tank.roi.h">
          </label>
        </div>
        <p class="text-[10px] text-slate-500 mt-1">Draw a box on the live view with the <b>[ ]</b> tool to get coordinates, then paste here.</p>
      </div>
    </div>
    <div class="flex gap-2 mt-4">
      <button class="btn primary" @click="saveEditor()">Save</button>
      <button class="btn" @click="editor.show=false">Cancel</button>
    </div>
  </div>
</div>

<!-- "Why this reading?" modal — explains the current level for one tank -->
<div x-show="why.show" x-transition class="fixed inset-0 z-50 modal-bg flex items-center justify-center p-6" @click.self="why.show=false">
  <div class="card w-full max-w-3xl p-5 max-h-[85vh] overflow-y-auto">
    <div class="flex items-center justify-between mb-3">
      <div>
        <h2 class="text-lg font-semibold">Why this reading?</h2>
        <p class="text-xs text-slate-400" x-show="why.live">
          <span x-text="why.live?.id?.toUpperCase().replace('_','-')"></span>
          &middot;
          <span x-text="(why.live?.level_pct||0).toFixed(1) + '%'"></span>
          &middot;
          <span x-text="'gate ' + (why.detail?.min_temp_delta||0).toFixed(1) + '&deg;C'"></span>
        </p>
      </div>
      <button class="btn" @click="why.show=false">Close</button>
    </div>

    <template x-if="why.loading">
      <div class="text-slate-400 text-sm py-8 text-center">Fetching gradient profile...</div>
    </template>

    <template x-if="!why.loading && why.detail">
      <div class="space-y-4">
        <!-- Key numbers -->
        <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div class="why-panel">
            <div class="hd">Peak gradient</div>
            <div class="val" x-text="(why.detail?.peak_val||0).toFixed(2) + ' &deg;C/row'"></div>
            <div class="why-bar"><div class="fill" :style="'width:'+whyPeakPct()+'%'" :class="whyPeakPass()?'':'warn'"></div></div>
            <div class="text-[10px] mt-1" :class="whyPeakPass()?'text-emerald-400':'text-amber-400'"
                 x-text="whyPeakPass()?('PASSES gate '+(why.detail?.min_temp_delta||0).toFixed(2)+' &deg;C'):('BELOW gate '+(why.detail?.min_temp_delta||0).toFixed(2)+' &deg;C \u2014 low confidence')"></div>
          </div>
          <div class="why-panel">
            <div class="hd">Interface row</div>
            <div class="val" x-text="(why.detail?.peak_idx||0) + ' / ' + (why.detail?.roi_height||0)"></div>
            <div class="text-[10px] text-slate-500 mt-1">row of max |dT/dy| inside ROI</div>
          </div>
          <div class="why-panel">
            <div class="hd">Temp range</div>
            <div class="val" x-text="why.live ? (why.live.temp_min?.toFixed(1) + ' \u2192 ' + why.live.temp_max?.toFixed(1) + ' &deg;C') : '\u2014'"></div>
            <div class="text-[10px] text-slate-500 mt-1"
                 x-text="why.live ? ('span ' + ((why.live.temp_max||0) - (why.live.temp_min||0)).toFixed(1) + ' &deg;C') : ''"></div>
          </div>
          <div class="why-panel">
            <div class="hd">Confidence</div>
            <div class="val" x-text="(why.live?.confidence||'-').toUpperCase()"></div>
            <div class="text-[10px] text-slate-500 mt-1"
                 x-text="why.live?.medium_declared ? ('declared ' + why.live.medium_declared) : ('classified ' + (why.live?.medium||'unknown'))"></div>
          </div>
        </div>

        <!-- Gradient trace SVG -->
        <div class="why-trace">
          <div class="flex items-center justify-between mb-2 text-[11px] text-slate-400">
            <span>Per-row gradient magnitude (top = ROI top, bottom = ROI bottom)</span>
            <span class="k">peak row <b class="text-amber-400" x-text="why.detail?.peak_idx"></b></span>
          </div>
          <svg :viewBox="'0 0 200 ' + Math.max(80, (why.detail?.gradient?.length||1))"
               preserveAspectRatio="none"
               class="w-full" style="height:220px;background:#030608;border-radius:6px">
            <!-- zero line -->
            <line x1="0" x2="200" :y1="0" :y2="0" stroke="#1f2a38" stroke-width="1"/>
            <!-- min_temp_delta gate line -->
            <line x1="0" x2="200" :y1="0" :y2="(why.detail?.gradient?.length||1)"
                  stroke="transparent" stroke-dasharray="3 3"/>
            <!-- gradient polyline (horizontal = magnitude scaled to 0..200) -->
            <polyline fill="none" stroke="#22d3ee" stroke-width="1.4"
                      :points="whyGradPoints()"/>
            <!-- peak marker -->
            <line x1="0" x2="200" :y1="why.detail?.peak_idx"
                  :y2="why.detail?.peak_idx"
                  stroke="#fbbf24" stroke-width="1" stroke-dasharray="4 3"/>
            <!-- gate threshold as vertical dashed bar -->
            <line :x1="whyGateX()" :x2="whyGateX()"
                  y1="0" :y2="(why.detail?.gradient?.length||1)"
                  stroke="#ef4444" stroke-width="1" stroke-dasharray="3 2" opacity="0.6"/>
          </svg>
          <div class="flex justify-between text-[10px] text-slate-500 mt-1">
            <span>&larr; stronger gradient at this row means sharper air/liquid boundary</span>
            <span>gate <b class="text-red-400" x-text="why.detail?.min_temp_delta?.toFixed(2)"></b> &deg;C/row</span>
          </div>
        </div>

        <!-- Plain-language explainer -->
        <div class="why-panel text-[12px] leading-relaxed" x-show="why.live">
          <div class="hd mb-2">Interpretation</div>
          <p x-text="whyExplainer()"></p>
        </div>

        <!-- Layers (when multi-layer is on) -->
        <template x-if="why.live?.layers?.length > 1">
          <div class="why-panel">
            <div class="hd mb-2">Detected layers</div>
            <template x-for="layer in why.live.layers" :key="layer.label">
              <div class="flex items-center gap-3 py-1 text-[12px]">
                <span class="alarm-pill" :style="layer.label==='sludge' || layer.label==='upper' ? 'background:rgba(168,85,247,.2);color:#e9d5ff;border:1px solid #6b21a8' : 'background:rgba(251,191,36,.2);color:#fde68a;border:1px solid #854d0e'"
                      x-text="layer.label"></span>
                <span class="k" x-text="'level '+layer.level_pct.toFixed(1)+'% \u00b7 row '+layer.row+' \u00b7 grad '+layer.gradient.toFixed(2)"></span>
              </div>
            </template>
          </div>
        </template>
      </div>
    </template>
  </div>
</div>

</div>

<script>
function app(){
  return {
    // state
    config: null,
    state: { results: [], tmin: 0, tmax: 0, w:0, h:0, frame_idx:0 },
    recording: { recording:false, seconds:0 },
    panel: null,
    unit: 'ft',
    live: false,
    banner: null,
    calibrating: false,
    detect: { modal:false, show:false, running:false, framesUsed:0, candidates:[], unit:'ft' },
    editor: { show:false, tank:null, heightValue:0, heightUnit:'ft', isNew:false },
    alerts: { collapsed:false, items:[], since:0 },

    // v1.7 — Tank Inspector overlay + sparkline + Why modal + rotate hint
    inspector: { tankId: null },
    sparkBuffers: {},              // { [tankId]: number[] }  rolling ~60 samples
    sparkCap: 60,                   // ~30 min at 30s per sample — tick() pushes every call
    sparkTickEvery: 3,              // push sample every Nth tick (~4.5s) to stretch to ~30 min
    _sparkTickCounter: 0,
    why: { show:false, loading:false, tankId:null, detail:null, live:null },
    rotateHintDismissedFor: null,  // rotate value the user dismissed for; re-show if rotate changes


    // Settings drawer: which overlay toggles to show
    overlayKeys: [
      'roi_boxes','level_line','min_marker','max_marker',
      'tank_labels','temp_scale','fps_counter','timestamp',
      'center_crosshair','grid',
    ],

    // measurement tools
    tool: 'select',
    measurements: [],     // {id,label,kind,coords,color,min,avg,max,count}
    draft: null,          // {kind, coords:[[x,y],...], tmp:[x,y]}
    nextMId: 1,
    _canvasNeedsInit: true,

    // stable stream URL — set ONCE at data-init. A getter would re-evaluate
    // on every Alpine reactive tick and, with a cache-buster, would replace
    // the <img> src every few seconds, killing the ongoing MJPEG connection.
    streamUrl: '/stream.mjpg?t=' + Date.now(),

    // derived
    get deviceHost(){ return location.host.replace(/\/$/,''); },
    get siteId(){ return this.config?.site?.id || '-'; },
    get supervisorUrl(){
      try {
        const h = location.hostname;
        const m = h.match(/^p8080-(n-[a-z0-9-]+)-(.*)$/i);
        if (m) return location.protocol + '//p1880-' + m[1] + '-' + m[2] + '/ui';
      } catch(e) {}
      return location.protocol + '//' + location.hostname + ':1880/ui';
    },
    get fpsLabel(){
      const f = this.state?.fps ? this.state.fps.toFixed(1) : '-';
      return f + ' fps';
    },

    async boot(){
      await this.reloadConfig();
      this.unit = this.config?.ui?.level_unit || 'ft';
      this.tick();
      setInterval(()=>this.tick(), 1500);
      setInterval(()=>this.pollRecording(), 2000);
      setInterval(()=>this.refreshMeasurements(), 1500);
      setInterval(()=>this.fetchAlerts(), 3000);
      window.addEventListener('resize', () => this.syncCanvas());
      window.addEventListener('keydown', (e) => this.onKey(e));
      // Canvas gets its size from the <img> once it loads.
      requestAnimationFrame(() => this.syncCanvas());
      // First alerts fetch immediately
      this.fetchAlerts();
    },
    async reloadConfig(){
      try {
        const r = await fetch('/api/config'); this.config = await r.json();
      } catch(e){ this.banner = 'Cannot reach /api/config ('+e+')'; }
    },
    async tick(){
      try {
        const r = await fetch('/api/state'); const s = await r.json();
        this.state = s; this.live = true;
        const cal = this.config?.calibration;
        if (cal?.notes?.length && !this.banner) this.banner = cal.notes[0];
        // Sparkline: append every Nth tick so ~60 samples span ~30 min.
        this._sparkTickCounter = (this._sparkTickCounter + 1) % this.sparkTickEvery;
        if (this._sparkTickCounter === 0 && Array.isArray(s.results)) {
          for (const t of s.results) {
            if (t.level_pct == null) continue;
            let buf = this.sparkBuffers[t.id];
            if (!buf) { buf = []; this.sparkBuffers[t.id] = buf; }
            buf.push(Number(t.level_pct));
            if (buf.length > this.sparkCap) buf.splice(0, buf.length - this.sparkCap);
          }
        }
      } catch(e){ this.live = false; }
    },
    async pollRecording(){
      try {
        const r = await fetch('/api/record/status'); this.recording = await r.json();
      } catch(e){}
    },
    async patch(p){
      await fetch('/api/config', {method:'PATCH', headers:{'Content-Type':'application/json'}, body: JSON.stringify(p)});
      await this.reloadConfig();
    },
    async setUnit(u){
      this.unit = u;
      await this.patch({ui:{level_unit:u}});
    },

    // -------------------- SCADA tank card helpers --------------------
    tankStatus(t){
      const p = t.level_pct || 0;
      if (t.confidence !== 'high') return { klass:'lo', label:'Low Conf' };
      if (p < 10 || p > 95) return { klass:'alert', label:'Alert' };
      if (p < 18 || p > 90) return { klass:'warning', label:'Warning' };
      return { klass:'active', label:'Active' };
    },
    tankCardClass(t){
      const s = this.tankStatus(t);
      const medium = t.medium || 'unknown';
      const cls = [medium];
      if (s.klass === 'alert') cls.push('alert');
      else if (s.klass === 'warning') cls.push('warning');
      return cls.join(' ');
    },
    fillColorClass(t){
      const s = this.tankStatus(t);
      if (s.klass === 'alert') return 'alert';
      return t.medium || 'unknown';
    },
    pctColorClass(t){
      const s = this.tankStatus(t);
      if (s.klass === 'alert') return 'alert';
      return t.medium || 'unknown';
    },
    rateClass(t){
      const r = t.reading?.fill_rate_bbl_h;
      if (r == null || Math.abs(r) < 0.05) return '';
      return r > 0 ? 'up' : 'dn';
    },
    etaDir(t){
      const r = t.reading;
      if (!r) return 'Full';
      if (r.minutes_to_full != null) return 'Full';
      if (r.minutes_to_empty != null) return 'Empty';
      return 'Full';
    },

    primaryLabel(t){
      const r = t.reading;
      if (!r) return (t.level_pct||0).toFixed(1) + ' %';
      if (this.unit === 'in') return (r.level_in||0).toFixed(1) + ' in';
      return (r.level_ft||0).toFixed(2) + ' ft';
    },
    rateLabel(t){
      const rate = t.reading?.fill_rate_bbl_h;
      if (rate == null) return '--';
      const arrow = rate > 0.05 ? '^' : (rate < -0.05 ? 'v' : '=');
      return arrow + ' ' + Math.abs(rate).toFixed(1) + ' bbl/h';
    },
    etaLabel(t){
      const r = t.reading;
      if (!r) return '--';
      if (r.minutes_to_full != null) return this.fmtDur(r.minutes_to_full*60);
      if (r.minutes_to_empty != null) return this.fmtDur(r.minutes_to_empty*60);
      return 'Stable';
    },
    fmtDur(sec){
      if (sec == null) return '--';
      sec = Math.max(0, Math.round(sec));
      const h = Math.floor(sec/3600), m = Math.floor((sec%3600)/60), s = sec%60;
      if (h) return h+'h '+m+'m';
      if (m) return m+'m '+s+'s';
      return s+'s';
    },
    fmt(n, d){ if (n==null) return '-'; return Number(n).toFixed(d==null?1:d); },

    candidateStyle(c){
      const img = document.getElementById('mjpeg-img');
      if (!img || !this.state.w || !this.state.h) return '';
      const rect = img.getBoundingClientRect();
      const wrap = img.parentElement.getBoundingClientRect();
      const sx = rect.width / this.state.w;
      const sy = rect.height / this.state.h;
      const offX = rect.left - wrap.left;
      const offY = rect.top - wrap.top;
      return 'left:'+(offX + c.roi.x*sx)+'px;top:'+(offY + c.roi.y*sy)+'px;width:'+(c.roi.w*sx)+'px;height:'+(c.roi.h*sy)+'px';
    },

    // -------------------- Drawing canvas --------------------
    onImgLoad(){ this.syncCanvas(); },
    syncCanvas(){
      const img = document.getElementById('mjpeg-img');
      const cv = document.getElementById('draw-canvas');
      if (!img || !cv) return;
      const rect = img.getBoundingClientRect();
      const wrap = img.parentElement.getBoundingClientRect();
      cv.style.left = (rect.left - wrap.left) + 'px';
      cv.style.top = (rect.top - wrap.top) + 'px';
      cv.style.width = rect.width + 'px';
      cv.style.height = rect.height + 'px';
      cv.width = Math.round(rect.width);
      cv.height = Math.round(rect.height);
      this.redrawCanvas();
    },
    setTool(t){
      this.tool = t;
      this.cancelDraft();
      this.redrawCanvas();
    },
    cancelDraft(){ this.draft = null; this.redrawCanvas(); },
    onKey(e){
      if (e.key === 'Escape') { this.cancelDraft(); this.setTool('select'); }
      if (e.key === 'Delete' && this.measurements.length) { this.clearMeasurements(); }
    },
    mousePos(ev){
      const cv = document.getElementById('draw-canvas');
      const r = cv.getBoundingClientRect();
      return [ev.clientX - r.left, ev.clientY - r.top];
    },
    // Map canvas-pixel coords → rendered-frame coords. state.w/h are the
    // rendered (upscaled) dimensions the server publishes in /api/state.
    toRendered(xy){
      const cv = document.getElementById('draw-canvas');
      const fw = this.state.w || 512;
      const fh = this.state.h || 384;
      if (!cv.width || !cv.height) return xy;
      return [xy[0] * (fw / cv.width), xy[1] * (fh / cv.height)];
    },
    onDown(ev){
      if (this.tool === 'select' || this.tool === 'polygon') return;
      const p = this.mousePos(ev);
      // add_tank uses a box draft shape so existing renderer handles it
      const kind = this.tool === 'add_tank' ? 'box' : this.tool;
      this.draft = { kind, coords: [p, p], _source: this.tool };
      this.redrawCanvas();
    },
    onMove(ev){
      if (!this.draft) return;
      if (this.tool === 'line' || this.tool === 'box' || this.tool === 'add_tank') {
        const p = this.mousePos(ev);
        this.draft.coords[1] = p;
        this.redrawCanvas();
      }
    },
    async onUp(ev){
      if (this.tool === 'select') return;
      const p = this.mousePos(ev);

      if (this.tool === 'point') {
        await this.commitMeasurement('point', [p]);
        return;
      }
      if (this.tool === 'line' || this.tool === 'box') {
        if (!this.draft) return;
        const a = this.draft.coords[0], b = p;
        const dx = Math.abs(a[0]-b[0]), dy = Math.abs(a[1]-b[1]);
        if (dx < 3 && dy < 3) { this.draft = null; this.redrawCanvas(); return; }
        await this.commitMeasurement(this.tool, [a, b]);
        this.draft = null;
        return;
      }
      if (this.tool === 'add_tank') {
        if (!this.draft) return;
        const a = this.draft.coords[0], b = p;
        const dx = Math.abs(a[0]-b[0]), dy = Math.abs(a[1]-b[1]);
        if (dx < 8 || dy < 8) { this.draft = null; this.redrawCanvas(); return; }
        // canvas -> rendered coords, then rendered / upscale -> sensor coords
        const rA = this.toRendered(a);
        const rB = this.toRendered(b);
        const up = Math.max(1, this.state.upscale || 1);
        const roi = {
          x: Math.max(0, Math.round(Math.min(rA[0], rB[0]) / up)),
          y: Math.max(0, Math.round(Math.min(rA[1], rB[1]) / up)),
          w: Math.max(1, Math.round(Math.abs(rA[0]-rB[0]) / up)),
          h: Math.max(1, Math.round(Math.abs(rA[1]-rB[1]) / up)),
        };
        const id = this.nextTankId();
        const site = this.siteId.toLowerCase().replace(/[^a-z0-9]+/g,'-');
        this.editTank({
          id,
          name: id.replace(/_/g,' '),
          medium: 'unknown',
          roi,
          geometry: { height_ft: 20, diameter_ft: 10, shape: 'vertical_cylinder' },
          min_temp_delta: 0.8,
          topic: 'nucleus/' + site + '/' + id,
        });
        this.editor.isNew = true;
        this.draft = null;
        this.redrawCanvas();
        this.setTool('select');
        return;
      }
      if (this.tool === 'polygon') {
        if (!this.draft) {
          this.draft = { kind:'polygon', coords:[p], tmp:p };
        } else {
          this.draft.coords.push(p);
          this.draft.tmp = p;
        }
        this.redrawCanvas();
      }
    },
    async onDblClick(ev){
      if (this.tool !== 'polygon' || !this.draft) return;
      if (this.draft.coords.length >= 3) {
        await this.commitMeasurement('polygon', this.draft.coords);
      }
      this.draft = null;
      this.redrawCanvas();
    },
    async commitMeasurement(kind, canvasCoords){
      const coords = canvasCoords.map(xy => this.toRendered(xy));
      const body = { shape: kind, coords, coord_space: 'rendered' };
      try {
        const r = await fetch('/api/measure', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
        const j = await r.json();
        if (j.err) { this.banner = 'measure: ' + j.err; return; }
        const id = this.nextMId++;
        const color = this.colorFor(id);
        this.measurements.push({
          id, label: id, kind, color,
          canvas: canvasCoords,
          coords,
          min: j.min, avg: j.avg, max: j.max, count: j.count,
        });
        this.redrawCanvas();
      } catch(e){ this.banner = 'measure failed: ' + e; }
    },
    async refreshMeasurements(){
      if (!this.measurements.length) return;
      for (const m of this.measurements) {
        try {
          const r = await fetch('/api/measure', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({
            shape: m.kind, coords: m.coords, coord_space: 'rendered'
          })});
          const j = await r.json();
          if (!j.err) { m.min = j.min; m.avg = j.avg; m.max = j.max; m.count = j.count; }
        } catch(e){}
      }
    },
    removeMeasurement(id){
      this.measurements = this.measurements.filter(m => m.id !== id);
      this.redrawCanvas();
    },
    clearMeasurements(){
      this.measurements = [];
      this.draft = null;
      this.redrawCanvas();
    },
    colorFor(i){
      const palette = ['#22d3ee','#fb923c','#a78bfa','#4ade80','#f472b6','#facc15','#60a5fa','#f87171','#34d399','#fbbf24'];
      return palette[(i-1) % palette.length];
    },
    redrawCanvas(){
      const cv = document.getElementById('draw-canvas');
      if (!cv) return;
      const ctx = cv.getContext('2d');
      ctx.clearRect(0, 0, cv.width, cv.height);
      ctx.lineWidth = 1.5;
      ctx.font = 'bold 11px ui-monospace, SFMono-Regular, monospace';

      // committed measurements
      for (const m of this.measurements) {
        ctx.strokeStyle = m.color;
        ctx.fillStyle = m.color;
        this._strokeShape(ctx, m.kind, m.canvas);
        const [lx, ly] = m.canvas[0];
        const label = '#' + m.label + ' ' + (m.avg != null ? m.avg.toFixed(1) + 'C' : '');
        this._labelAt(ctx, lx, ly, label, m.color);
      }
      // in-flight draft
      if (this.draft) {
        ctx.strokeStyle = '#e2e8f0';
        ctx.fillStyle = '#e2e8f0';
        ctx.setLineDash([4,3]);
        this._strokeShape(ctx, this.draft.kind, this.draft.coords);
        ctx.setLineDash([]);
      }
    },
    _strokeShape(ctx, kind, pts){
      if (!pts || !pts.length) return;
      if (kind === 'point') {
        const [x, y] = pts[0];
        ctx.beginPath(); ctx.arc(x, y, 5, 0, Math.PI*2); ctx.stroke();
        ctx.beginPath(); ctx.arc(x, y, 2, 0, Math.PI*2); ctx.fill();
      } else if (kind === 'line') {
        const [a, b] = pts;
        ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
      } else if (kind === 'box') {
        const [a, b] = pts;
        const x = Math.min(a[0], b[0]), y = Math.min(a[1], b[1]);
        const w = Math.abs(a[0] - b[0]), h = Math.abs(a[1] - b[1]);
        ctx.strokeRect(x, y, w, h);
      } else if (kind === 'polygon') {
        ctx.beginPath();
        ctx.moveTo(pts[0][0], pts[0][1]);
        for (let i=1; i<pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
        if (pts.length > 2) ctx.closePath();
        ctx.stroke();
        for (const [x, y] of pts) { ctx.beginPath(); ctx.arc(x, y, 2.5, 0, Math.PI*2); ctx.fill(); }
      }
    },
    _labelAt(ctx, x, y, text, color){
      const tw = ctx.measureText(text).width;
      ctx.fillStyle = 'rgba(5,7,10,.85)';
      ctx.fillRect(x + 8, y - 16, tw + 8, 15);
      ctx.fillStyle = color;
      ctx.fillText(text, x + 12, y - 5);
    },

    // -------------------- detect / calibrate / tanks --------------------
    async openDetectModal(){
      this.detect.unit = this.unit || 'ft';
      this.detect.modal = true;
      await this.runDetect();
    },
    async runDetect(){
      this.detect.running = true;
      try {
        const r = await fetch('/api/detect', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({max:6, samples:20, timeout_s:6})});
        const j = await r.json();
        this.detect.framesUsed = j.frames_used || 0;
        // Merge with any existing candidate so user-edited fields (topic,
        // height_ft override) survive a re-scan when the id matches.
        const existing = new Map(this.detect.candidates.map(c => [c.id, c]));
        const site = this.siteId.toLowerCase().replace(/[^a-z0-9]+/g,'-');
        this.detect.candidates = (j.candidates||[]).map(c => {
          const prior = existing.get(c.id) || {};
          return {
            ...c,
            topic: prior.topic || ('nucleus/' + site + '/' + c.id),
            geometry: prior.geometry || { height_ft: 20, diameter_ft: 10, shape: 'vertical_cylinder' },
          };
        });
        this.detect.show = true;
      } catch(e){ this.banner = 'Auto-detect failed: ' + e; }
      this.detect.running = false;
    },
    async acceptDetect(){
      const body = { tanks: this.detect.candidates.map(c => ({
        id: c.id,
        name: c.name,
        medium: c.medium,
        topic: (c.topic || '').trim() || null,
        roi: {
          x: Math.max(0, Math.round(c.roi.x || 0)),
          y: Math.max(0, Math.round(c.roi.y || 0)),
          w: Math.max(1, Math.round(c.roi.w || 1)),
          h: Math.max(1, Math.round(c.roi.h || 1)),
        },
        geometry: c.geometry,
        min_temp_delta: c.min_temp_delta || 0.8,
      }))};
      await fetch('/api/detect/accept', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
      this.detect.modal = false; this.detect.show = false;
      this.banner = 'Saved ' + body.tanks.length + ' tank(s). Perimeters and topics applied.';
      await this.reloadConfig();
    },
    async runCalibrate(){
      this.calibrating = true;
      try {
        const r = await fetch('/api/calibrate', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({samples:30, timeout_s:12})});
        const j = await r.json();
        if (j.error) this.banner = 'Calibration error: ' + j.error;
        else {
          const c = j.calibration;
          this.banner = 'Calibrated: e=' + c.emissivity + ', reflect=' + c.reflect_temp_c + ' C, range ' + c.range_min_c + '..' + c.range_max_c;
        }
      } catch(e){ this.banner = 'Calibration failed: ' + e; }
      this.calibrating = false;
      await this.reloadConfig();
    },
    async snapshot(){
      try { await fetch('/api/snapshot', {method:'POST'}); this.banner = 'Snapshot saved.'; } catch(e){}
    },
    async toggleRecord(){
      try {
        if (this.recording.recording) await fetch('/api/record/stop', {method:'POST'});
        else await fetch('/api/record/start', {method:'POST'});
      } catch(e){}
      await this.pollRecording();
    },
    editTank(t){
      const staged = JSON.parse(JSON.stringify(Object.assign({
        geometry:{height_ft:20, diameter_ft:10, shape:'vertical_cylinder'},
        roi:{x:0, y:0, w:40, h:170},
        topic:'',
        min_temp_delta: 1.0,
        alarms: {hi_pct:null, lo_pct:null},
        multi_layer: false,
      }, t)));
      staged.topic = staged.topic || '';
      staged.roi = Object.assign({x:0,y:0,w:40,h:170}, staged.roi || {});
      staged.geometry = Object.assign({height_ft:20,diameter_ft:10,shape:'vertical_cylinder'}, staged.geometry || {});
      staged.alarms = Object.assign({hi_pct:null, lo_pct:null}, staged.alarms || {});
      staged.multi_layer = !!staged.multi_layer;
      this.editor.tank = staged;
      this.editor.isNew = !((this.config?.tanks || []).some(x => x.id === staged.id));
      // Seed scale inputs from whatever unit the UI currently prefers.
      const ft = Number(staged.geometry.height_ft) || 0;
      this.editor.heightUnit = this.unit === 'in' ? 'in' : 'ft';
      this.editor.heightValue = this.editor.heightUnit === 'in' ? +(ft * 12).toFixed(2) : ft;
      this.editor.show = true;
    },
    async saveEditor(){
      const t = this.editor.tank;
      // Normalise the user-entered scale back to feet (canonical unit).
      const val = Number(this.editor.heightValue) || 0;
      const heightFt = this.editor.heightUnit === 'in' ? +(val / 12).toFixed(3) : val;
      t.geometry = Object.assign({}, t.geometry, { height_ft: heightFt });
      // Normalise alarms: blank inputs are null, valid numbers pass through.
      const alarms = t.alarms ? {
        hi_pct: (t.alarms.hi_pct == null || t.alarms.hi_pct === '') ? null : Number(t.alarms.hi_pct),
        lo_pct: (t.alarms.lo_pct == null || t.alarms.lo_pct === '') ? null : Number(t.alarms.lo_pct),
      } : null;
      const body = {
        id: t.id,
        name: t.name,
        medium: t.medium,
        topic: (t.topic || '').trim() || null,
        roi: {
          x: Math.max(0, Math.round(t.roi?.x || 0)),
          y: Math.max(0, Math.round(t.roi?.y || 0)),
          w: Math.max(1, Math.round(t.roi?.w || 1)),
          h: Math.max(1, Math.round(t.roi?.h || 1)),
        },
        geometry: t.geometry,
        min_temp_delta: t.min_temp_delta,
        alarms,
        multi_layer: !!t.multi_layer,
      };
      try {
        if (this.editor.isNew) {
          const r = await fetch('/api/tanks', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify(body),
          });
          if (!r.ok) {
            const j = await r.json().catch(()=>({}));
            this.banner = 'Save failed: ' + (j.error || r.status);
            return;
          }
        } else {
          await fetch('/api/tanks/'+encodeURIComponent(t.id), {
            method:'PATCH',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify(body),
          });
        }
        this.editor.show = false;
        this.editor.isNew = false;
        this.banner = 'Saved ' + t.id + ' (scale 0-100% = 0-' + val + ' ' + this.editor.heightUnit + ')';
        await this.reloadConfig();
      } catch(e){ this.banner = 'Save failed: ' + e; }
    },
    async removeTank(id){
      if (!confirm('Remove '+id+'?')) return;
      await fetch('/api/tanks/'+encodeURIComponent(id), {method:'DELETE'});
      await this.reloadConfig();
    },
    nextTankId(){
      const taken = new Set((this.config?.tanks || []).map(t => t.id));
      let i = (this.config?.tanks || []).length + 1;
      while (taken.has('tank_' + i)) i++;
      return 'tank_' + i;
    },
    async addBlankTank(){
      const id = this.nextTankId();
      const site = this.siteId.toLowerCase().replace(/[^a-z0-9]+/g,'-');
      const body = {
        id,
        name: id.replace(/_/g,' '),
        medium: 'unknown',
        roi: { x: 40, y: 40, w: 60, h: 180 },
        geometry: { height_ft: 20, diameter_ft: 10, shape: 'vertical_cylinder' },
        min_temp_delta: 0.8,
        topic: 'nucleus/' + site + '/' + id,
      };
      try {
        const r = await fetch('/api/tanks', {
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify(body),
        });
        if (!r.ok) {
          const j = await r.json().catch(()=>({}));
          this.banner = 'Add failed: ' + (j.error || r.status);
          return;
        }
        await this.reloadConfig();
        this.banner = 'Added ' + id + ' — use Edit to adjust perimeter & scale.';
      } catch(e){ this.banner = 'Add failed: ' + e; }
    },
    async setTankCount(target){
      target = Math.max(0, Math.min(12, Number(target) || 0));
      const tanks = (this.config?.tanks || []).slice();
      const cur = tanks.length;
      if (target === cur) return;
      if (target < cur) {
        if (!confirm('Remove ' + (cur - target) + ' tank(s) from the end?')) {
          await this.reloadConfig();
          return;
        }
        for (let i = cur - 1; i >= target; i--) {
          await fetch('/api/tanks/'+encodeURIComponent(tanks[i].id), {method:'DELETE'});
        }
        await this.reloadConfig();
        this.banner = 'Trimmed to ' + target + ' tank(s).';
        return;
      }
      // target > cur — append blanks with non-colliding ids
      for (let i = 0; i < (target - cur); i++) {
        await this.addBlankTank();
      }
    },

    // -------------------- v1.7: Inspector overlay --------------------
    // Resolve the tank object currently targeted by the Inspector.
    inspectedTank(){
      const id = this.inspector.tankId;
      if (!id) return null;
      return (this.state.results || []).find(t => t.id === id) || null;
    },
    toggleInspector(id){
      this.inspector.tankId = (this.inspector.tankId === id) ? null : id;
    },
    closeInspector(){ this.inspector.tankId = null; },
    // Project sensor-space ROI/rows onto the rendered <img> tag — gives us
    // the same scaling the measurement canvas uses. Returns null when the
    // image isn't laid out yet (first frame).
    _inspectorImgRect(){
      const img = document.getElementById('mjpeg-img');
      if (!img) return null;
      const r = img.getBoundingClientRect();
      const w = img.parentElement.getBoundingClientRect();
      if (!r.width || !r.height) return null;
      const sw = this.state.sensor_w || this.state.w || 256;
      const sh = this.state.sensor_h || this.state.h || 192;
      return {
        offX: r.left - w.left, offY: r.top - w.top,
        w: r.width, h: r.height, sw, sh,
        sx: r.width / sw, sy: r.height / sh,
      };
    },
    inspectorBoxStyle(){
      const t = this.inspectedTank();
      const g = this._inspectorImgRect();
      if (!t || !g || !t.roi) return 'display:none';
      const x = g.offX + t.roi.x * g.sx;
      const y = g.offY + t.roi.y * g.sy;
      const w = t.roi.w * g.sx;
      const h = t.roi.h * g.sy;
      return `left:${x}px;top:${y}px;width:${w}px;height:${h}px`;
    },
    inspectorBoxCls(){
      const t = this.inspectedTank();
      if (!t) return '';
      return (t.alarms?.hi || t.alarms?.lo) ? 'alert' : '';
    },
    inspectorLineStyle(layer){
      const t = this.inspectedTank();
      const g = this._inspectorImgRect();
      if (!t || !g) return 'display:none';
      let rowSensor = t.interface_row_sensor;
      if (layer === 'secondary') {
        const sec = (t.layers || []).find(l => l.label !== 'primary');
        if (!sec) return 'display:none';
        rowSensor = sec.row_sensor;
      }
      if (rowSensor == null) return 'display:none';
      const y = g.offY + rowSensor * g.sy;
      const left = g.offX + (t.roi?.x || 0) * g.sx;
      const width = (t.roi?.w || 0) * g.sx;
      return `left:${left}px;top:${y}px;width:${width}px`;
    },
    inspectorPrimaryLabel(){
      const t = this.inspectedTank();
      if (!t) return '';
      const pct = (t.level_pct != null ? t.level_pct.toFixed(1) : '--') + '%';
      const ft = t.reading?.level_ft != null ? (' \u00b7 ' + t.reading.level_ft.toFixed(2) + ' ft') : '';
      const bbl = t.reading?.volume_bbl != null ? (' \u00b7 ' + Math.round(t.reading.volume_bbl) + ' BBL') : '';
      return 'LEVEL ' + pct + ft + bbl;
    },
    inspectorHasSecondary(){
      const t = this.inspectedTank();
      return !!(t && Array.isArray(t.layers) && t.layers.length > 1);
    },
    inspectorSecondaryLabel(){
      const t = this.inspectedTank();
      if (!t) return '';
      const sec = (t.layers || []).find(l => l.label !== 'primary');
      if (!sec) return '';
      return sec.label.toUpperCase() + ' ' + sec.level_pct.toFixed(1) + '%';
    },
    inspectorAlarmPct(kind){
      const t = this.inspectedTank();
      if (!t || !t.alarms) return null;
      const v = (kind === 'hi') ? t.alarms.hi_pct : t.alarms.lo_pct;
      if (v == null) return null;
      return Number(v);
    },
    inspectorAlarmLineStyle(kind){
      const t = this.inspectedTank();
      const g = this._inspectorImgRect();
      if (!t || !g || !t.roi) return 'display:none';
      const pct = this.inspectorAlarmPct(kind);
      if (pct == null) return 'display:none';
      // level_pct is measured from ROI bottom → convert to sensor y.
      const fromBottom = pct / 100;
      const rowRel = t.roi.h - fromBottom * t.roi.h;
      const rowSensor = t.roi.y + rowRel;
      const y = g.offY + rowSensor * g.sy;
      const left = g.offX + t.roi.x * g.sx;
      const width = t.roi.w * g.sx;
      return `left:${left}px;top:${y}px;width:${width}px`;
    },
    inspectorCloseStyle(){
      const t = this.inspectedTank();
      const g = this._inspectorImgRect();
      if (!t || !g || !t.roi) return 'display:none';
      const x = g.offX + (t.roi.x + t.roi.w) * g.sx - 55;
      const y = g.offY + t.roi.y * g.sy - 24;
      return `left:${x}px;top:${Math.max(4, y)}px`;
    },

    // -------------------- v1.7: Sparkline --------------------
    sparkLine(id){ return this.sparkBuffers[id] || []; },
    sparkPoints(id){
      const buf = this.sparkLine(id);
      if (!buf.length) return '';
      const n = buf.length;
      // normalise to 0..100 → SVG y = 26..0 (inverted), x = 0..100
      return buf.map((v, i) => {
        const x = n === 1 ? 50 : (i / (n - 1)) * 100;
        const y = 26 - (Math.max(0, Math.min(100, v)) / 100) * 26;
        return x.toFixed(2) + ',' + y.toFixed(2);
      }).join(' ');
    },
    sparkStroke(t){
      const m = t.medium || 'unknown';
      if (t.alarms?.hi || t.alarms?.lo) return '#f87171';
      if (m === 'water') return '#22d3ee';
      if (m === 'oil') return '#fb923c';
      return '#94a3b8';
    },

    // -------------------- v1.7: Rotate hint banner --------------------
    rotateHintVisible(){
      const h = this.state?.rotate_hint;
      if (!h || h.suggested == null) return false;
      // Hide if the user already dismissed this *exact* suggestion.
      const cur = Number(this.config?.stream?.rotate || 0);
      if (this.rotateHintDismissedFor === cur) return false;
      return true;
    },
    async applyRotateHint(){
      const h = this.state?.rotate_hint;
      if (!h) return;
      await this.patch({stream:{rotate: Number(h.suggested)}});
      this.banner = 'Camera rotated to ' + h.suggested + '\u00b0';
    },
    dismissRotateHint(){
      this.rotateHintDismissedFor = Number(this.config?.stream?.rotate || 0);
    },

    // -------------------- v1.7: Why this reading? modal --------------------
    async openWhy(id){
      this.why = { show:true, loading:true, tankId:id, detail:null, live:null };
      try {
        const r = await fetch('/api/tank/' + encodeURIComponent(id) + '/gradient');
        if (!r.ok) {
          this.banner = 'Why: ' + r.status + ' ' + r.statusText;
          this.why.loading = false;
          return;
        }
        const j = await r.json();
        this.why.detail = j.detail;
        this.why.live = j.live;
      } catch(e){ this.banner = 'Why failed: ' + e; }
      this.why.loading = false;
    },
    whyPeakPct(){
      const d = this.why.detail;
      if (!d) return 0;
      const gate = Math.max(0.01, d.min_temp_delta || 1);
      return Math.min(100, (d.peak_val / (gate * 2)) * 100);
    },
    whyPeakPass(){
      const d = this.why.detail;
      if (!d) return false;
      return (d.peak_val || 0) >= (d.min_temp_delta || 0);
    },
    whyGradPoints(){
      const d = this.why.detail;
      if (!d || !d.gradient?.length) return '';
      const n = d.gradient.length;
      const mx = Math.max(0.01, ...d.gradient);
      // x = magnitude (0..200), y = row index (0..n)
      return d.gradient.map((v, i) => ((v / mx) * 200).toFixed(2) + ',' + i).join(' ');
    },
    whyGateX(){
      const d = this.why.detail;
      if (!d || !d.gradient?.length) return 0;
      const mx = Math.max(0.01, ...d.gradient);
      return ((d.min_temp_delta || 0) / mx) * 200;
    },
    whyExplainer(){
      const d = this.why.detail;
      const lv = this.why.live;
      if (!d || !lv) return '';
      const pass = this.whyPeakPass();
      const pct = (lv.level_pct||0).toFixed(1);
      const row = d.peak_idx;
      const total = d.roi_height;
      const peak = (d.peak_val||0).toFixed(2);
      const gate = (d.min_temp_delta||0).toFixed(2);
      let s = 'Inside the ROI (' + total + ' rows tall) the sharpest vertical temperature change is at row ' + row +
              ' — a gradient magnitude of ' + peak + ' \u00b0C/row. ';
      if (pass) {
        s += 'That is above the confidence gate (' + gate + ' \u00b0C/row), so the detector trusts this as the liquid/air interface. ';
        s += 'The level is reported as ' + pct + '% of the tank height (ROI bottom \u2192 top).';
      } else {
        s += 'That is BELOW the gate (' + gate + ' \u00b0C/row), so the detector flags the reading as LOW CONFIDENCE. ';
        s += 'Common causes: the tank is thermally uniform (empty or full), the ROI is too narrow, or ambient is drifting. ';
        s += 'Lower the min_temp_delta in Edit to accept weaker gradients.';
      }
      return s;
    },

    // -------------------- Alerts / Events --------------------
    async fetchAlerts(){
      try {
        const r = await fetch('/api/alerts?since=' + (this.alerts.since || 0));
        if (!r.ok) return;
        const j = await r.json();
        const items = Array.isArray(j.items) ? j.items : [];
        if (!items.length) return;
        // Server returns oldest→newest for "since"; merge newest-first into state.
        const byId = new Map(this.alerts.items.map(a => [a.seq, a]));
        for (const a of items) if (!byId.has(a.seq)) byId.set(a.seq, a);
        const merged = Array.from(byId.values())
          .sort((a,b) => (b.seq||0) - (a.seq||0))
          .slice(0, 40);
        this.alerts.items = merged;
        this.alerts.since = Math.max(this.alerts.since || 0, ...items.map(a => a.seq || 0));
      } catch(e){}
    },
    unackCount(){
      return (this.alerts.items || []).filter(a => !a._ack).length;
    },
    ackAlert(seq){
      const a = (this.alerts.items || []).find(x => x.seq === seq);
      if (a) a._ack = true;
    },
    clearAlerts(){
      this.alerts.items = [];
    },
    async pushAlertToNR(a){
      try {
        const r = await fetch('/api/alerts/push', {
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify({seq: a.seq}),
        });
        if (r.ok) {
          a._pushed = true;
          this.banner = 'Alert pushed to Node-RED';
        } else {
          const j = await r.json().catch(()=>({}));
          this.banner = 'Push failed: ' + (j.error || r.status);
        }
      } catch(e){ this.banner = 'Push failed: ' + e; }
    },
    alertCls(a){
      if (!a) return '';
      if (a.kind === 'low_confidence') return 'warn';
      if (a.kind === 'level_change') {
        const delta = Math.abs((a.level_pct||0) - (a.prev==null?a.level_pct||0:a.prev));
        if (delta > 20) return 'al';
        return 'warn';
      }
      if (a.kind === 'tank_removed') return 'warn';
      if (a.kind === 'alarm_hi' || a.kind === 'alarm_lo') return 'al';
      if (a.kind === 'alarm_clear') return 'warn';
      return '';
    },
    fmtAlertTime(ts){
      if (!ts) return '';
      const d = new Date(ts * 1000);
      const p = (n) => String(n).padStart(2,'0');
      return p(d.getHours())+':'+p(d.getMinutes())+':'+p(d.getSeconds());
    },
    alertMessage(a){
      if (!a) return '';
      const id = a.id || '-';
      if (a.kind === 'level_change') {
        const prev = (a.prev==null) ? '?' : Number(a.prev).toFixed(1)+'%';
        const cur  = (a.level_pct==null) ? '?' : Number(a.level_pct).toFixed(1)+'%';
        return id + ': level ' + prev + ' -> ' + cur;
      }
      if (a.kind === 'low_confidence') return id + ': low confidence (grad ' + Number(a.gradient_peak||0).toFixed(2) + ')';
      if (a.kind === 'tank_added')     return 'tank ' + id + ' added';
      if (a.kind === 'tank_removed')   return 'tank ' + id + ' removed';
      if (a.kind === 'calibrated')     return 'calibrated (medium=' + (a.medium||'?') + ', locked=' + (a.locked?'yes':'no') + ')';
      if (a.kind === 'auto_detect')    return 'auto-detect: ' + (a.count||0) + ' candidates';
      if (a.kind === 'alarm_hi')       return id + ': HI alarm tripped at ' + Number(a.level_pct||0).toFixed(1) + '% (threshold ' + Number(a.threshold||0).toFixed(0) + '%)';
      if (a.kind === 'alarm_lo')       return id + ': LO alarm tripped at ' + Number(a.level_pct||0).toFixed(1) + '% (threshold ' + Number(a.threshold||0).toFixed(0) + '%)';
      if (a.kind === 'alarm_clear')    return id + ': alarm cleared (' + (a.scope||'') + ') at ' + Number(a.level_pct||0).toFixed(1) + '%';
      return a.kind || 'event';
    },
  };
}
</script>
</body>
</html>
"""

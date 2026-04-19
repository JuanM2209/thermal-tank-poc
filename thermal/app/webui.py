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
      <div class="text-[11px] text-slate-400">
        <span class="k" x-text="siteId"></span>
        &middot; <span class="k" x-text="deviceHost"></span>
        &middot; <span x-text="fpsLabel"></span>
      </div>
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
    <div class="seg" role="tablist">
      <button :class="unit==='ft'?'active':''" @click="setUnit('ft')">ft</button>
      <button :class="unit==='in'?'active':''" @click="setUnit('in')">in</button>
    </div>
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
    </div>
  </section>

  <!-- RIGHT: SCADA tank cards -->
  <aside class="flex flex-col gap-3 min-h-0 overflow-y-auto pr-1">
    <template x-for="t in state.results" :key="t.id">
      <div class="tank-card" :class="tankCardClass(t)">
        <div class="tank-head">
          <div class="tank-id"><b x-text="t.id.toUpperCase().replace('_','-')"></b></div>
          <div class="flex items-center gap-2">
            <div class="tank-medium" :class="t.medium || 'unknown'" x-text="t.medium || 'unknown'"></div>
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

        <details class="mt-2 text-[11px] text-slate-400">
          <summary class="hover:text-slate-200">geometry &amp; roi</summary>
          <div class="k mt-1 leading-5" x-show="t.geometry">
            <div>height <span x-text="t.geometry?.height_ft"></span> ft &middot; D <span x-text="t.geometry?.diameter_ft"></span> ft &middot; <span x-text="t.geometry?.shape"></span></div>
            <div x-show="t.reading">full <span x-text="fmt(t.reading?.volume_full_bbl,0)"></span> bbl &middot; ullage <span x-text="fmt(t.reading?.ullage_ft,1)"></span> ft</div>
          </div>
          <div class="k mt-1" x-text="'roi x=' + t.roi?.x + ' y=' + t.roi?.y + ' w=' + t.roi?.w + ' h=' + t.roi?.h"></div>
          <div class="tank-actions">
            <button class="btn sm" @click="editTank(t)">Edit</button>
            <button class="btn sm" @click="removeTank(t.id)">Remove</button>
          </div>
        </details>
      </div>
    </template>
    <template x-if="!state.results?.length">
      <div class="card p-4 text-center text-slate-400 text-sm">
        No tanks configured yet. Press <span class="chip">Auto-detect</span> to find them.
      </div>
    </template>
  </aside>
</main>

<!-- Bottom controls -->
<footer class="border-t border-[#1f2630] bg-[#07090d]/90 backdrop-blur px-4 py-2 text-[11px] text-slate-400 flex items-center justify-between">
  <div class="flex items-center gap-3">
    <span>Operator Console v1.4</span>
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
      Review each, set height and diameter, then accept.
    </p>
    <div class="flex gap-2 mb-3">
      <button class="btn primary" @click="runDetect()" :disabled="detect.running" x-text="detect.running?'Scanning...':'Re-scan'"></button>
      <button class="btn success" @click="acceptDetect()" :disabled="!detect.candidates.length">Accept &amp; save</button>
    </div>
    <table class="w-full text-xs">
      <thead class="text-left text-slate-400">
        <tr><th class="p-1">#</th><th>Name</th><th>Medium</th><th>Height ft</th><th>Diameter ft</th><th>ROI</th><th>Conf.</th></tr>
      </thead>
      <tbody>
        <template x-for="(c,i) in detect.candidates" :key="c.id">
          <tr class="border-t border-[#1f2630]">
            <td class="p-1 k" x-text="i+1"></td>
            <td><input class="bg-black/40 border border-[#1f2630] rounded px-1 py-0.5 w-24" x-model="c.name"></td>
            <td>
              <select class="bg-black/40 border border-[#1f2630] rounded px-1 py-0.5" x-model="c.medium">
                <option value="water">water</option>
                <option value="oil">oil</option>
                <option value="unknown">unknown</option>
              </select>
            </td>
            <td><input type="number" step="0.5" class="bg-black/40 border border-[#1f2630] rounded px-1 py-0.5 w-20" x-model.number="c.geometry.height_ft"></td>
            <td><input type="number" step="0.5" class="bg-black/40 border border-[#1f2630] rounded px-1 py-0.5 w-20" x-model.number="c.geometry.diameter_ft"></td>
            <td class="k text-slate-500" x-text="'['+c.roi.x+','+c.roi.y+' '+c.roi.w+'x'+c.roi.h+']'"></td>
            <td class="k" x-text="Math.round((c.medium_confidence||0)*100)+'%'"></td>
          </tr>
        </template>
      </tbody>
    </table>
  </div>
</div>

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
      <label class="flex flex-col gap-1"><span class="text-slate-400 text-xs">Height ft</span>
        <input type="number" step="0.5" class="bg-black/40 border border-[#1f2630] rounded px-2 py-1" x-model.number="editor.tank.geometry.height_ft">
      </label>
      <label class="flex flex-col gap-1"><span class="text-slate-400 text-xs">Diameter ft</span>
        <input type="number" step="0.5" class="bg-black/40 border border-[#1f2630] rounded px-2 py-1" x-model.number="editor.tank.geometry.diameter_ft">
      </label>
      <label class="flex flex-col gap-1 col-span-2"><span class="text-slate-400 text-xs">Min temp delta C (confidence gate)</span>
        <input type="number" step="0.1" class="bg-black/40 border border-[#1f2630] rounded px-2 py-1" x-model.number="editor.tank.min_temp_delta">
      </label>
    </div>
    <div class="flex gap-2 mt-4">
      <button class="btn primary" @click="saveEditor()">Save</button>
      <button class="btn" @click="editor.show=false">Cancel</button>
    </div>
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
    detect: { modal:false, show:false, running:false, framesUsed:0, candidates:[] },
    editor: { show:false, tank:null },

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
      window.addEventListener('resize', () => this.syncCanvas());
      window.addEventListener('keydown', (e) => this.onKey(e));
      // Canvas gets its size from the <img> once it loads.
      requestAnimationFrame(() => this.syncCanvas());
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
      this.draft = { kind: this.tool, coords: [p, p] };
      this.redrawCanvas();
    },
    onMove(ev){
      if (!this.draft) return;
      if (this.tool === 'line' || this.tool === 'box') {
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
    async openDetectModal(){ this.detect.modal = true; await this.runDetect(); },
    async runDetect(){
      this.detect.running = true;
      try {
        const r = await fetch('/api/detect', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({max:6, samples:20, timeout_s:6})});
        const j = await r.json();
        this.detect.framesUsed = j.frames_used || 0;
        this.detect.candidates = (j.candidates||[]).map(c => ({
          ...c,
          geometry: { height_ft: 20, diameter_ft: 10, shape: 'vertical_cylinder' }
        }));
        this.detect.show = true;
      } catch(e){ this.banner = 'Auto-detect failed: ' + e; }
      this.detect.running = false;
    },
    async acceptDetect(){
      const body = { tanks: this.detect.candidates.map(c => ({
        id: c.id, name: c.name, medium: c.medium, roi: c.roi,
        geometry: c.geometry, min_temp_delta: c.min_temp_delta || 0.8,
      }))};
      await fetch('/api/detect/accept', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
      this.detect.modal = false; this.detect.show = false;
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
      this.editor.tank = JSON.parse(JSON.stringify(Object.assign({
        geometry:{height_ft:20, diameter_ft:10, shape:'vertical_cylinder'},
        min_temp_delta: 1.0
      }, t)));
      this.editor.show = true;
    },
    async saveEditor(){
      const t = this.editor.tank;
      await fetch('/api/tanks/'+encodeURIComponent(t.id), {method:'PATCH', headers:{'Content-Type':'application/json'}, body: JSON.stringify({
        name: t.name, medium: t.medium, geometry: t.geometry, min_temp_delta: t.min_temp_delta
      })});
      this.editor.show = false;
      await this.reloadConfig();
    },
    async removeTank(id){
      if (!confirm('Remove '+id+'?')) return;
      await fetch('/api/tanks/'+encodeURIComponent(id), {method:'DELETE'});
      await this.reloadConfig();
    },
  };
}
</script>
</body>
</html>
"""

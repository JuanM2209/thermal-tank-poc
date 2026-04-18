"""Single-file HTML for the dashboard (Alpine.js + Tailwind via CDN).

Keeping this as a Python string lets us ship one file, no build step.
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
    html,body{height:100%;background:#0b0d10;color:#e6e6e6;font-family:ui-sans-serif,system-ui,sans-serif}
    ::-webkit-scrollbar{width:8px;height:8px}
    ::-webkit-scrollbar-thumb{background:#333;border-radius:4px}
    .stream-wrap img{image-rendering:pixelated}
    .pill{backdrop-filter:blur(6px);background:rgba(0,0,0,.55)}
    .dot{width:6px;height:6px;border-radius:999px;display:inline-block}
    .ok{background:#22c55e}.warn{background:#f59e0b}.err{background:#ef4444}
    .card{background:#12161c;border:1px solid #1f2630;border-radius:10px}
    .btn{background:#1f2630;border:1px solid #2a323d;padding:.35rem .6rem;border-radius:6px;font-size:.78rem;cursor:pointer;color:#e6e6e6}
    .btn:hover{background:#2a323d}
    .btn.active{background:#2563eb;border-color:#2563eb}
    .btn.red{background:#7f1d1d;border-color:#991b1b}
    .btn.red:hover{background:#991b1b}
    .btn.rec{background:#dc2626;border-color:#ef4444;animation:pulse 1.3s infinite}
    @keyframes pulse{50%{opacity:.6}}
    .muted{color:#8a94a3}
    .grid-bg{background-image:linear-gradient(#11161d 1px,transparent 1px),linear-gradient(90deg,#11161d 1px,transparent 1px);background-size:20px 20px}
    .shimmer{background:linear-gradient(90deg,#121821 0,#1a222d 50%,#121821 100%);background-size:200% 100%;animation:sh 1.6s linear infinite}
    @keyframes sh{0%{background-position:100% 0}100%{background-position:-100% 0}}
    .seg{display:inline-flex;border:1px solid #2a323d;border-radius:6px;overflow:hidden}
    .seg button{padding:.3rem .55rem;font-size:.72rem;background:#1a1f27;color:#e6e6e6;border:none;cursor:pointer}
    .seg button.active{background:#2563eb}
    input[type=range]{accent-color:#2563eb}
  </style>
</head>
<body class="h-full grid-bg">
<div x-data="app()" x-init="boot()" class="h-full flex flex-col">

  <!-- Top bar -->
  <header class="flex items-center justify-between px-4 py-2 border-b border-[#1f2630] bg-[#0d1117]/80 backdrop-blur">
    <div class="flex items-center gap-3">
      <div class="w-8 h-8 rounded-md bg-gradient-to-br from-orange-500 to-rose-600 flex items-center justify-center font-bold">T</div>
      <div>
        <div class="text-sm font-semibold" x-text="config?.ui?.title || 'Thermal Tank Monitor'"></div>
        <div class="text-[11px] muted">device <span x-text="deviceId"></span> &middot; <span x-text="fpsLabel"></span></div>
      </div>
    </div>
    <div class="flex items-center gap-2 flex-wrap">
      <div class="pill rounded-full px-3 py-1 text-xs flex items-center gap-2">
        <span class="dot" :class="live?'ok':'err'"></span>
        <span x-text="live ? 'live' : 'offline'"></span>
      </div>
      <button class="btn" :class="config?.stream?.freeze?'active':''" @click="patch({stream:{freeze:!config.stream.freeze}})" title="Freeze the live frame">❄ Freeze</button>
      <button class="btn" @click="snapshot()" title="Save a PNG of the current frame">📸 Snap</button>
      <button class="btn" :class="recording.recording?'rec':''"
              @click="toggleRecord()"
              x-text="recording.recording ? ('⏹ '+fmtDur(recording.seconds)) : '● Record'"></button>
      <button class="btn" @click="autoDetect()" title="AI auto-detect tanks">✨ Auto-detect</button>
      <div class="w-px h-6 bg-[#1f2630]"></div>
      <button class="btn" @click="panel='tanks'"     :class="panel==='tanks'?'active':''">Tanks</button>
      <button class="btn" @click="panel='palette'"   :class="panel==='palette'?'active':''">Palette</button>
      <button class="btn" @click="panel='image'"     :class="panel==='image'?'active':''">Image</button>
      <button class="btn" @click="panel='overlays'"  :class="panel==='overlays'?'active':''">Overlays</button>
      <button class="btn" @click="panel='settings'"  :class="panel==='settings'?'active':''">Settings</button>
      <button class="btn" @click="panel='files'"     :class="panel==='files'?'active':''">Files</button>
      <button class="btn" @click="panel='events'"    :class="panel==='events'?'active':''">Events</button>
    </div>
  </header>

  <!-- Main split -->
  <main class="flex-1 grid grid-cols-[280px_1fr_340px] gap-3 p-3 min-h-0">

    <!-- LEFT: tank cards -->
    <aside class="card p-3 overflow-y-auto min-h-0">
      <div class="flex items-center justify-between mb-2">
        <h2 class="text-sm font-semibold">Tanks</h2>
        <button class="btn" @click="toolMode='draw_roi'" :class="toolMode==='draw_roi'?'active':''">+ Draw</button>
      </div>

      <template x-if="detectionCandidates.length">
        <div class="card p-2 mb-2 border-emerald-700">
          <div class="text-xs muted mb-1">AI found <span x-text="detectionCandidates.length"></span> candidate(s)</div>
          <template x-for="c in detectionCandidates" :key="c.id">
            <div class="text-[11px] font-mono py-0.5">
              <span class="text-emerald-400" x-text="c.id"></span>
              <span class="muted" x-text="` ${c.hint} score=${c.score}`"></span>
              <span class="muted" x-text="` roi=${c.roi.x},${c.roi.y} ${c.roi.w}×${c.roi.h}`"></span>
            </div>
          </template>
          <div class="flex gap-1 mt-2">
            <button class="btn flex-1" @click="acceptDetection()">Accept all</button>
            <button class="btn" @click="detectionCandidates=[]">Dismiss</button>
          </div>
        </div>
      </template>

      <template x-for="t in tanks" :key="t.id">
        <div class="card p-3 mb-2" :class="resultsById[t.id]?.confidence==='high'?'':'opacity-70'">
          <div class="flex items-center justify-between">
            <div class="font-semibold text-sm" x-text="t.name || t.id"></div>
            <button class="text-xs muted hover:text-red-400" @click="removeTank(t.id)">remove</button>
          </div>
          <div class="text-[11px] muted mb-2" x-text="t.medium || 'medium'"></div>
          <div class="flex items-end gap-2">
            <div class="text-3xl font-bold tabular-nums"
                 x-text="(resultsById[t.id]?.level_pct ?? '—') + (resultsById[t.id] ? '%' : '')"
                 :class="resultsById[t.id]?.confidence==='high'?'text-emerald-400':'text-amber-400'"></div>
            <div class="text-[11px] muted pb-1">
              <span class="dot" :class="resultsById[t.id]?.confidence==='high'?'ok':'warn'"></span>
              <span x-text="resultsById[t.id]?.confidence || '—'"></span>
            </div>
          </div>
          <div class="grid grid-cols-3 gap-2 mt-2 text-[11px]">
            <div><div class="muted">min</div><div class="tabular-nums" x-text="fmtT(resultsById[t.id]?.temp_min)"></div></div>
            <div><div class="muted">avg</div><div class="tabular-nums" x-text="fmtT(resultsById[t.id]?.temp_avg)"></div></div>
            <div><div class="muted">max</div><div class="tabular-nums" x-text="fmtT(resultsById[t.id]?.temp_max)"></div></div>
          </div>
        </div>
      </template>
      <template x-if="!tanks.length && !detectionCandidates.length">
        <div class="text-xs muted">No tanks yet — click <b>✨ Auto-detect</b> or <b>+ Draw</b>.</div>
      </template>
    </aside>

    <!-- CENTER: live stream -->
    <section class="card flex flex-col min-h-0">
      <div class="flex items-center justify-between px-3 py-2 border-b border-[#1f2630]">
        <div class="flex items-center gap-2 text-xs muted">
          <span x-text="frameInfo"></span>
          <template x-if="lastLine">
            <span class="text-sky-300 font-mono">| line: min <span x-text="fmtT(lastLine.min)"></span>
              avg <span x-text="fmtT(lastLine.avg)"></span>
              max <span x-text="fmtT(lastLine.max)"></span>
              (<span x-text="lastLine.length_px"></span>px)</span>
          </template>
        </div>
        <div class="flex items-center gap-2">
          <button class="btn" :class="toolMode==='pan'?'active':''"      @click="toolMode='pan'">Pan</button>
          <button class="btn" :class="toolMode==='probe'?'active':''"    @click="toolMode='probe'">Probe °</button>
          <button class="btn" :class="toolMode==='marker'?'active':''"   @click="toolMode='marker'">Pin</button>
          <button class="btn" :class="toolMode==='line'?'active':''"     @click="toolMode='line'">Line</button>
          <button class="btn" :class="toolMode==='draw_roi'?'active':''" @click="toolMode='draw_roi'">ROI</button>
          <button class="btn" @click="markers=[]; lines=[]; lastLine=null">Clear</button>
        </div>
      </div>

      <div class="flex-1 relative stream-wrap overflow-hidden"
           @mousemove="onMove($event)" @mouseleave="hover=null"
           @mousedown="onDown($event)" @mouseup="onUp($event)">
        <img id="mjpeg" src="/stream.mjpg" class="w-full h-full object-contain select-none pointer-events-none" draggable="false"/>

        <!-- Overlay layer for markers, lines, draw preview -->
        <svg class="absolute inset-0 w-full h-full pointer-events-none" viewBox="0 0 1000 1000" preserveAspectRatio="none">
          <template x-for="(m,i) in markers" :key="i">
            <g>
              <circle :cx="m.vx*1000" :cy="m.vy*1000" r="6" fill="none" stroke="#38bdf8" stroke-width="2"/>
              <text :x="m.vx*1000+10" :y="m.vy*1000-6" font-size="22" fill="#bae6fd" font-family="ui-monospace,monospace" x-text="fmtT(m.t)"></text>
            </g>
          </template>
          <template x-for="(ln,i) in lines" :key="'l'+i">
            <g>
              <line :x1="ln.a.vx*1000" :y1="ln.a.vy*1000" :x2="ln.b.vx*1000" :y2="ln.b.vy*1000"
                    stroke="#22d3ee" stroke-width="2"/>
              <text :x="((ln.a.vx+ln.b.vx)/2)*1000" :y="((ln.a.vy+ln.b.vy)/2)*1000 - 6"
                    font-size="20" fill="#67e8f9" font-family="ui-monospace,monospace"
                    x-text="ln.stats ? (`μ${fmtT(ln.stats.avg)}`) : ''"></text>
            </g>
          </template>
          <template x-if="drawing">
            <rect :x="Math.min(drawStart.vx,drawEnd.vx)*1000"
                  :y="Math.min(drawStart.vy,drawEnd.vy)*1000"
                  :width="Math.abs(drawEnd.vx-drawStart.vx)*1000"
                  :height="Math.abs(drawEnd.vy-drawStart.vy)*1000"
                  fill="rgba(34,197,94,0.12)" stroke="#22c55e" stroke-width="2" stroke-dasharray="6 4"/>
          </template>
          <!-- detection candidate previews -->
          <template x-for="c in detectionCandidates" :key="'d'+c.id">
            <rect :x="(c.roi.x/sensor.w)*1000" :y="(c.roi.y/sensor.h)*1000"
                  :width="(c.roi.w/sensor.w)*1000" :height="(c.roi.h/sensor.h)*1000"
                  fill="rgba(236,72,153,0.12)" stroke="#ec4899" stroke-width="2" stroke-dasharray="4 3"/>
          </template>
        </svg>

        <!-- Hover probe pill -->
        <div x-show="hover" x-transition
             class="absolute pill rounded-md px-2 py-1 text-xs pointer-events-none"
             :style="`left:${hover?.px+10}px; top:${hover?.py+10}px`">
          <span class="font-mono" x-text="hover ? `x:${hover.sx} y:${hover.sy}` : ''"></span>
          &nbsp; <span class="text-orange-300 font-mono" x-text="hover ? fmtT(hover.t) : ''"></span>
        </div>

        <!-- Global min/max pill top-left -->
        <div class="absolute top-2 left-2 pill rounded-md px-2 py-1 text-xs font-mono">
          min <span class="text-sky-300" x-text="fmtT(state.tmin)"></span>
          &nbsp;/&nbsp; max <span class="text-rose-300" x-text="fmtT(state.tmax)"></span>
        </div>

        <!-- Recording pill top-right -->
        <div x-show="recording.recording" class="absolute top-2 right-2 pill rounded-md px-3 py-1 text-xs font-mono flex items-center gap-2">
          <span class="dot err animate-pulse"></span>
          <span>REC</span>
          <span x-text="fmtDur(recording.seconds)"></span>
          <span class="muted" x-text="recording.frames + ' frames'"></span>
        </div>

        <div x-show="!live" class="absolute inset-0 flex items-center justify-center text-xs muted shimmer">connecting…</div>
      </div>
    </section>

    <!-- RIGHT: context panel -->
    <aside class="card p-3 overflow-y-auto min-h-0">

      <!-- Palette -->
      <div x-show="panel==='palette'">
        <h2 class="text-sm font-semibold mb-2">Palette</h2>
        <div class="grid grid-cols-2 gap-1 mb-3">
          <template x-for="p in palettes" :key="p">
            <button class="btn text-left" :class="config?.stream?.palette===p?'active':''"
                    @click="patch({stream:{palette:p}})" x-text="p"></button>
          </template>
        </div>
        <h3 class="text-xs font-semibold mt-4 mb-1">Source</h3>
        <div class="grid grid-cols-3 gap-1">
          <template x-for="s in ['thermal','visual','blend']" :key="s">
            <button class="btn" :class="config?.stream?.source===s?'active':''" @click="patch({stream:{source:s}})" x-text="s"></button>
          </template>
        </div>

        <h3 class="text-xs font-semibold mt-4 mb-1">Temperature range</h3>
        <div class="flex items-center gap-2 mb-2">
          <button class="btn flex-1"
                  :class="config?.stream?.range_min==null ? 'active' : ''"
                  @click="patch({stream:{range_min:null,range_max:null}})">Auto</button>
          <button class="btn flex-1"
                  :class="config?.stream?.range_min!=null ? 'active' : ''"
                  @click="patch({stream:{range_min:Math.floor(state.tmin), range_max:Math.ceil(state.tmax)}})">Lock to current</button>
        </div>
        <template x-if="config?.stream?.range_min != null">
          <div>
            <label class="block mb-1">
              <div class="text-xs muted">min: <span x-text="config.stream.range_min"></span>°C</div>
              <input type="range" min="-20" max="100" step="0.5" class="w-full"
                     :value="config.stream.range_min"
                     @change="patch({stream:{range_min:+$event.target.value}})"/>
            </label>
            <label class="block mb-1">
              <div class="text-xs muted">max: <span x-text="config.stream.range_max"></span>°C</div>
              <input type="range" min="-10" max="200" step="0.5" class="w-full"
                     :value="config.stream.range_max"
                     @change="patch({stream:{range_max:+$event.target.value}})"/>
            </label>
          </div>
        </template>

        <h3 class="text-xs font-semibold mt-4 mb-1">Isotherm highlight</h3>
        <label class="flex items-center justify-between text-sm py-1">
          <span>Enabled</span>
          <input type="checkbox" :checked="config?.stream?.isotherm_enabled"
                 @change="patch({stream:{isotherm_enabled:$event.target.checked}})"/>
        </label>
        <template x-if="config?.stream?.isotherm_enabled">
          <div>
            <label class="block mb-1">
              <div class="text-xs muted">from: <span x-text="config.stream.isotherm_min"></span>°C</div>
              <input type="range" min="-20" max="100" step="0.5" class="w-full"
                     :value="config.stream.isotherm_min"
                     @change="patch({stream:{isotherm_min:+$event.target.value}})"/>
            </label>
            <label class="block mb-1">
              <div class="text-xs muted">to: <span x-text="config.stream.isotherm_max"></span>°C</div>
              <input type="range" min="-10" max="200" step="0.5" class="w-full"
                     :value="config.stream.isotherm_max"
                     @change="patch({stream:{isotherm_max:+$event.target.value}})"/>
            </label>
          </div>
        </template>
      </div>

      <!-- Image transforms -->
      <div x-show="panel==='image'">
        <h2 class="text-sm font-semibold mb-2">Image transforms</h2>
        <h3 class="text-xs font-semibold mt-2 mb-1">Rotate</h3>
        <div class="seg w-full">
          <template x-for="r in [0,90,180,270]" :key="r">
            <button :class="(config?.stream?.rotate||0)===r?'active':''"
                    @click="patch({stream:{rotate:r}})" x-text="r+'°'"></button>
          </template>
        </div>
        <h3 class="text-xs font-semibold mt-4 mb-1">Flip</h3>
        <label class="flex items-center justify-between text-sm py-1">
          <span>Horizontal</span>
          <input type="checkbox" :checked="config?.stream?.flip_h"
                 @change="patch({stream:{flip_h:$event.target.checked}})"/>
        </label>
        <label class="flex items-center justify-between text-sm py-1">
          <span>Vertical</span>
          <input type="checkbox" :checked="config?.stream?.flip_v"
                 @change="patch({stream:{flip_v:$event.target.checked}})"/>
        </label>
        <h3 class="text-xs font-semibold mt-4 mb-1">Freeze frame</h3>
        <label class="flex items-center justify-between text-sm py-1">
          <span>Pause live</span>
          <input type="checkbox" :checked="config?.stream?.freeze"
                 @change="patch({stream:{freeze:$event.target.checked}})"/>
        </label>
        <h3 class="text-xs font-semibold mt-4 mb-1">Quick capture</h3>
        <div class="flex gap-1">
          <button class="btn flex-1" @click="snapshot()">📸 Snapshot PNG</button>
          <button class="btn flex-1" :class="recording.recording?'rec':''" @click="toggleRecord()"
                  x-text="recording.recording?'⏹ Stop':'● Record'"></button>
        </div>
      </div>

      <!-- Overlays -->
      <div x-show="panel==='overlays'">
        <h2 class="text-sm font-semibold mb-2">Overlays</h2>
        <template x-for="k in Object.keys(config?.stream?.overlay || {})" :key="k">
          <label class="flex items-center justify-between py-1 text-sm">
            <span x-text="k.replaceAll('_',' ')"></span>
            <input type="checkbox"
                   :checked="config.stream.overlay[k]"
                   @change="patch({stream:{overlay:{[k]:$event.target.checked}}})"/>
          </label>
        </template>
      </div>

      <!-- Settings -->
      <div x-show="panel==='settings'">
        <h2 class="text-sm font-semibold mb-2">Settings</h2>
        <label class="block mb-2">
          <div class="text-xs muted mb-1">Stream FPS: <span x-text="config?.stream?.fps"></span></div>
          <input type="range" min="1" max="25" step="1" class="w-full"
                 :value="config?.stream?.fps"
                 @change="patch({stream:{fps:+$event.target.value}})"/>
        </label>
        <label class="block mb-2">
          <div class="text-xs muted mb-1">JPEG quality: <span x-text="config?.stream?.jpeg_quality"></span></div>
          <input type="range" min="30" max="95" step="5" class="w-full"
                 :value="config?.stream?.jpeg_quality"
                 @change="patch({stream:{jpeg_quality:+$event.target.value}})"/>
        </label>
        <label class="block mb-2">
          <div class="text-xs muted mb-1">Upscale: <span x-text="config?.stream?.upscale"></span>x</div>
          <input type="range" min="1" max="4" step="1" class="w-full"
                 :value="config?.stream?.upscale"
                 @change="patch({stream:{upscale:+$event.target.value}})"/>
        </label>
        <label class="block mb-2">
          <div class="text-xs muted mb-1">Temp unit</div>
          <div class="flex gap-1">
            <button class="btn flex-1" :class="config?.ui?.temp_unit==='C'?'active':''" @click="patch({ui:{temp_unit:'C'}})">°C</button>
            <button class="btn flex-1" :class="config?.ui?.temp_unit==='F'?'active':''" @click="patch({ui:{temp_unit:'F'}})">°F</button>
          </div>
        </label>
        <label class="block mb-2">
          <div class="text-xs muted mb-1">Emissivity: <span x-text="config?.ui?.emissivity"></span></div>
          <input type="range" min="0.5" max="1.0" step="0.01" class="w-full"
                 :value="config?.ui?.emissivity"
                 @change="patch({ui:{emissivity:+$event.target.value}})"/>
        </label>
      </div>

      <!-- Tanks table -->
      <div x-show="panel==='tanks'">
        <h2 class="text-sm font-semibold mb-2">Tank configuration</h2>
        <template x-for="t in tanks" :key="t.id">
          <div class="card p-2 mb-2 text-xs">
            <div class="flex justify-between mb-1">
              <input class="bg-transparent border-b border-[#2a323d] font-semibold w-1/2"
                     :value="t.name" @change="renameTank(t.id,$event.target.value)"/>
              <span class="muted font-mono" x-text="t.id"></span>
            </div>
            <div class="grid grid-cols-4 gap-1 font-mono">
              <div>x <span x-text="t.roi.x"></span></div>
              <div>y <span x-text="t.roi.y"></span></div>
              <div>w <span x-text="t.roi.w"></span></div>
              <div>h <span x-text="t.roi.h"></span></div>
            </div>
            <label class="block mt-2">
              <div class="muted">min_temp_delta °C: <span x-text="t.min_temp_delta"></span></div>
              <input type="range" min="0.2" max="5" step="0.1" class="w-full"
                     :value="t.min_temp_delta"
                     @change="setTankField(t.id,'min_temp_delta',+$event.target.value)"/>
            </label>
          </div>
        </template>
        <button class="btn w-full mb-1" @click="toolMode='draw_roi'">+ Draw a new ROI</button>
        <button class="btn w-full" @click="autoDetect()">✨ Auto-detect tanks</button>
      </div>

      <!-- Files -->
      <div x-show="panel==='files'">
        <h2 class="text-sm font-semibold mb-2">Captures</h2>
        <h3 class="text-xs font-semibold mt-2 mb-1">Snapshots (<span x-text="files.snapshots?.length||0"></span>)</h3>
        <template x-for="f in (files.snapshots||[])" :key="'s'+f.name">
          <div class="flex items-center justify-between text-[11px] py-1 border-b border-[#1f2630]">
            <a class="text-sky-300 font-mono truncate" :href="'/api/files/snapshots/'+f.name" x-text="f.name"></a>
            <span class="muted" x-text="fmtBytes(f.bytes)"></span>
          </div>
        </template>
        <h3 class="text-xs font-semibold mt-3 mb-1">Recordings (<span x-text="files.recordings?.length||0"></span>)</h3>
        <template x-for="f in (files.recordings||[])" :key="'r'+f.name">
          <div class="flex items-center justify-between text-[11px] py-1 border-b border-[#1f2630]">
            <a class="text-sky-300 font-mono truncate" :href="'/api/files/recordings/'+f.name" x-text="f.name"></a>
            <span class="muted" x-text="fmtBytes(f.bytes)"></span>
          </div>
        </template>
        <button class="btn w-full mt-3" @click="refreshFiles()">Refresh</button>
      </div>

      <!-- Events -->
      <div x-show="panel==='events'">
        <h2 class="text-sm font-semibold mb-2">Events</h2>
        <template x-for="e in events.slice().reverse()" :key="e.seq">
          <div class="text-[11px] font-mono border-b border-[#1f2630] py-1">
            <span class="muted" x-text="new Date(e.ts*1000).toLocaleTimeString()"></span>
            <span class="mx-1" :class="eventColor(e.kind)" x-text="e.kind"></span>
            <span x-text="eventDetail(e)"></span>
          </div>
        </template>
        <div x-show="!events.length" class="text-xs muted">no events yet</div>
      </div>

    </aside>
  </main>
</div>

<script>
function app(){
  return {
    deviceId: location.hostname,
    config: null,
    state:  {tmin:0,tmax:0,results:[],tanks:[]},
    tanks:  [],
    events: [],
    eventSeq: 0,
    live: false,
    panel: 'palette',
    toolMode: 'probe',
    palettes: ['grayscale','iron','rainbow','hot','inferno','plasma','magma','jet','turbo','cividis'],
    hover: null,
    markers: [],
    lines: [],
    lastLine: null,
    drawing: false,
    drawStart: null,
    drawEnd:   null,
    lineStart: null,
    recording: {recording:false, frames:0, seconds:0},
    detectionCandidates: [],
    files: {snapshots:[], recordings:[]},
    sensor: {w: 256, h: 192},
    _probeBusy: false,

    get resultsById(){ const m={}; for(const r of this.state.results||[]) m[r.id]=r; return m; },
    get frameInfo(){
      const s=this.state;
      return `frame ${s.frame_idx||0} · sensor ${this.sensor.w}×${this.sensor.h} · display ${s.w||0}×${s.h||0} (${s.upscale||1}×)`;
    },
    get fpsLabel(){ return (this.state.fps||0).toFixed(1) + ' fps'; },

    fmtT(t){
      if(t===undefined||t===null||Number.isNaN(t)) return '—';
      const u=this.config?.ui?.temp_unit||'C';
      return u==='F' ? (t*9/5+32).toFixed(1)+'°F' : t.toFixed(1)+'°C';
    },
    fmtBytes(b){
      if(!b) return '—';
      if(b<1024) return b+' B';
      if(b<1048576) return (b/1024).toFixed(1)+' KB';
      return (b/1048576).toFixed(1)+' MB';
    },
    fmtDur(s){
      s = Math.floor(s||0);
      const m = Math.floor(s/60), r = s%60;
      return String(m).padStart(2,'0')+':'+String(r).padStart(2,'0');
    },
    eventColor(k){ return {
      'level_change':'text-amber-400','low_confidence':'text-rose-400',
      'tank_added':'text-emerald-400','tank_removed':'text-slate-400',
      'config_change':'text-sky-400','auto_detect':'text-pink-400',
      'snapshot':'text-yellow-300','record_start':'text-red-400','record_stop':'text-red-300'
    }[k] || 'text-slate-200'; },
    eventDetail(e){
      const o = {...e};
      delete o.seq; delete o.ts; delete o.kind;
      return Object.keys(o).length ? JSON.stringify(o).slice(0,150) : '';
    },

    async boot(){
      await this.refreshConfig();
      // Compute sensor dims from first /api/state (upscale=1 gives sensor, else divide)
      this.poll();
      this.pollEvents();
      this.pollRecording();
      this.refreshFiles();
    },
    async refreshConfig(){
      const r=await fetch('/api/config'); this.config=await r.json();
      this.tanks=this.config.tanks||[];
    },
    async poll(){
      try{
        const r=await fetch('/api/state'); const j=await r.json();
        this.state=j; this.live=true;
        if(j.w && j.upscale){ this.sensor={w: Math.round(j.w/j.upscale), h: Math.round(j.h/j.upscale)}; }
      }catch(e){ this.live=false; }
      setTimeout(()=>this.poll(), 800);
    },
    async pollEvents(){
      try{
        const r=await fetch('/api/events?since='+this.eventSeq);
        const arr=await r.json();
        if(arr.length){ this.events.push(...arr); this.eventSeq=arr[arr.length-1].seq; }
      }catch(e){}
      setTimeout(()=>this.pollEvents(), 2000);
    },
    async pollRecording(){
      try{
        const r=await fetch('/api/record/status');
        this.recording=await r.json();
      }catch(e){}
      setTimeout(()=>this.pollRecording(), 1000);
    },
    async refreshFiles(){
      try{
        const r=await fetch('/api/files');
        this.files=await r.json();
      }catch(e){}
    },

    async patch(partial){
      const r=await fetch('/api/config',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(partial)});
      if(r.ok){ await this.refreshConfig(); }
    },

    // ---- snapshot / record / autodetect ----
    async snapshot(){
      const r = await fetch('/api/snapshot',{method:'POST'});
      if(r.ok){ await this.refreshFiles(); }
    },
    async toggleRecord(){
      const url = this.recording.recording ? '/api/record/stop' : '/api/record/start';
      await fetch(url, {method:'POST'});
      await this.refreshFiles();
    },
    async autoDetect(){
      const r = await fetch('/api/detect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({max:4})});
      const j = await r.json();
      this.detectionCandidates = j.candidates || [];
      this.panel = 'tanks';
    },
    async acceptDetection(){
      await fetch('/api/detect/accept',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({tanks:this.detectionCandidates})});
      this.detectionCandidates = [];
      await this.refreshConfig();
    },

    // ---- coord math ----
    mapEvent(e){
      const img=document.getElementById('mjpeg');
      const r=img.getBoundingClientRect();
      const px=e.clientX-r.left, py=e.clientY-r.top;
      const nw=img.naturalWidth||1, nh=img.naturalHeight||1;
      const scale=Math.min(r.width/nw, r.height/nh);
      const dw=nw*scale, dh=nh*scale;
      const ox=(r.width-dw)/2, oy=(r.height-dh)/2;
      const ix=(px-ox)/scale, iy=(py-oy)/scale;
      if(ix<0||iy<0||ix>nw||iy>nh) return null;
      const up=this.config?.stream?.upscale||1;
      const sx=Math.round(ix/up), sy=Math.round(iy/up);
      return {px, py, sx, sy, vx:px/r.width, vy:py/r.height};
    },

    async probe(sx, sy){
      if(this._probeBusy) return null;
      this._probeBusy=true;
      try{
        const r=await fetch(`/api/temp?x=${sx}&y=${sy}`);
        return (await r.json()).t;
      } finally { this._probeBusy=false; }
    },
    async lineStats(a, b){
      const r = await fetch(`/api/line?x1=${a.sx}&y1=${a.sy}&x2=${b.sx}&y2=${b.sy}`);
      return await r.json();
    },

    async onMove(e){
      const m=this.mapEvent(e); if(!m){ this.hover=null; return; }
      const now=performance.now();
      if(!this._lastHover || now-this._lastHover>120){
        this._lastHover=now;
        m.t = await this.probe(m.sx, m.sy);
      } else {
        m.t = this.hover?.t;
      }
      this.hover=m;
      if(this.drawing){ this.drawEnd=m; }
    },

    async onDown(e){
      const m=this.mapEvent(e); if(!m) return;
      if(this.toolMode==='draw_roi'){
        this.drawing=true; this.drawStart=m; this.drawEnd=m;
      } else if(this.toolMode==='marker'){
        const t=await this.probe(m.sx,m.sy);
        this.markers.push({sx:m.sx, sy:m.sy, t, vx:m.vx, vy:m.vy});
      } else if(this.toolMode==='probe'){
        const t=await this.probe(m.sx,m.sy);
        this.markers=[{sx:m.sx, sy:m.sy, t, vx:m.vx, vy:m.vy}];
      } else if(this.toolMode==='line'){
        this.lineStart = m;
      }
    },
    async onUp(e){
      if(this.toolMode==='draw_roi' && this.drawing){
        this.drawing=false;
        const a=this.drawStart, b=this.drawEnd;
        const x=Math.round(Math.min(a.sx,b.sx)), y=Math.round(Math.min(a.sy,b.sy));
        const w=Math.round(Math.abs(a.sx-b.sx)), h=Math.round(Math.abs(a.sy-b.sy));
        if(w>4 && h>6){
          const id='tank_'+String(this.tanks.length+1).padStart(2,'0');
          await fetch('/api/tanks',{method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({id, name:'Tank '+(this.tanks.length+1), medium:'water',
                                 roi:{x,y,w,h}, min_temp_delta:1.0})});
          await this.refreshConfig();
        }
        this.drawStart=null; this.drawEnd=null;
      } else if(this.toolMode==='line' && this.lineStart){
        const m = this.mapEvent(e);
        if(m){
          const stats = await this.lineStats(this.lineStart, m);
          this.lines.push({a:this.lineStart, b:m, stats});
          this.lastLine = stats;
        }
        this.lineStart = null;
      }
    },

    async removeTank(id){
      await fetch('/api/tanks/'+encodeURIComponent(id), {method:'DELETE'});
      await this.refreshConfig();
    },
    async renameTank(id, name){
      await fetch('/api/tanks/'+encodeURIComponent(id), {method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});
      await this.refreshConfig();
    },
    async setTankField(id, field, value){
      await fetch('/api/tanks/'+encodeURIComponent(id), {method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({[field]:value})});
      await this.refreshConfig();
    },
  };
}
</script>
</body>
</html>
"""

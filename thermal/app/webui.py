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
    .stream-wrap img{image-rendering:pixelated;width:100%;height:100%;object-fit:contain;background:#000}
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
    @keyframes pulse{50%{opacity:.6}}
    .pill{backdrop-filter:blur(6px);background:rgba(15,23,42,.8);border:1px solid #1f2630;border-radius:999px;padding:.25rem .75rem;font-size:.72rem}
    .dot{width:8px;height:8px;border-radius:999px;display:inline-block}
    .ok{background:#22c55e}.warn{background:#f59e0b}.err{background:#ef4444}.idle{background:#64748b}
    .tier1{font-size:2.25rem;font-weight:800;letter-spacing:-.02em;line-height:1}
    .tier1.hi{color:#4ade80}.tier1.lo{color:#fbbf24}.tier1.al{color:#f87171}
    .tier2{font-size:.8rem;color:#94a3b8}
    .chip{display:inline-block;padding:.1rem .45rem;border-radius:999px;font-size:.65rem;border:1px solid #334155;color:#cbd5e1;background:#0f172a}
    .chip.water{border-color:#0891b2;color:#67e8f9;background:#083344}
    .chip.oil{border-color:#b45309;color:#fbbf24;background:#78350f}
    .chip.unknown{border-color:#6b7280;color:#cbd5e1;background:#0f172a}
    .bar{height:12px;border-radius:999px;background:#0f172a;overflow:hidden;position:relative}
    .bar .fill{position:absolute;inset:0;right:auto;background:linear-gradient(90deg,#16a34a,#84cc16);transition:width .4s}
    .bar .fill.al{background:linear-gradient(90deg,#dc2626,#f97316)}
    .bar .fill.lo{background:linear-gradient(90deg,#a16207,#f59e0b)}
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

  <!-- LEFT: stream + scale -->
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
      <img :src="streamUrl" alt="thermal stream"/>
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

  <!-- RIGHT: tank cards + settings panel -->
  <aside class="flex flex-col gap-3 min-h-0 overflow-y-auto">
    <template x-for="t in state.results" :key="t.id">
      <div class="card p-4" :class="cardClass(t)">
        <div class="flex items-center justify-between mb-1">
          <div class="flex items-center gap-2">
            <span class="text-sm font-semibold" x-text="t.name"></span>
            <span class="chip" :class="t.medium" x-text="t.medium"></span>
            <span class="text-[10px] text-slate-500 k" x-text="'~' + Math.round((t.medium_confidence||0)*100) + '%'"></span>
          </div>
          <span class="text-[10px] k" :class="t.confidence==='high'?'text-emerald-400':'text-amber-400'" x-text="t.confidence"></span>
        </div>
        <div class="flex items-end justify-between mb-2">
          <div class="tier1" :class="valueTint(t)" x-text="primaryLabel(t)"></div>
          <div class="text-right">
            <div class="tier2 k" x-text="secondaryLabel(t)"></div>
            <div class="tier2 k" x-text="thirdLabel(t)"></div>
          </div>
        </div>
        <div class="bar mb-2"><div class="fill" :class="valueTint(t)" :style="'width:'+Math.max(0,Math.min(100,t.level_pct))+'%'"></div></div>
        <div class="grid grid-cols-3 gap-2 text-[11px] text-slate-300">
          <div class="bg-black/30 rounded p-1">
            <div class="text-slate-500">min / avg / max</div>
            <div class="k" x-text="fmt(t.temp_min,1)+' / '+fmt(t.temp_avg,1)+' / '+fmt(t.temp_max,1)+' C'"></div>
          </div>
          <div class="bg-black/30 rounded p-1">
            <div class="text-slate-500">fill rate</div>
            <div class="k" x-text="rateLabel(t)"></div>
          </div>
          <div class="bg-black/30 rounded p-1">
            <div class="text-slate-500">eta</div>
            <div class="k" x-text="etaLabel(t)"></div>
          </div>
        </div>
        <details class="mt-2 text-[11px] text-slate-400">
          <summary class="hover:text-slate-200">geometry & ROI</summary>
          <div class="k mt-1 leading-5" x-show="t.geometry">
            <div>height <span x-text="t.geometry?.height_ft"></span> ft . D <span x-text="t.geometry?.diameter_ft"></span> ft . <span x-text="t.geometry?.shape"></span></div>
            <div x-show="t.reading">full <span x-text="fmt(t.reading?.volume_full_bbl,0)"></span> bbl . ullage <span x-text="fmt(t.reading?.ullage_ft,1)"></span> ft</div>
          </div>
          <div class="k mt-1" x-text="'roi x=' + t.roi?.x + ' y=' + t.roi?.y + ' w=' + t.roi?.w + ' h=' + t.roi?.h"></div>
          <div class="flex gap-1 mt-2">
            <button class="btn" @click="editTank(t)">Edit</button>
            <button class="btn" @click="removeTank(t.id)">Remove</button>
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

<!-- Bottom controls (stub for now) -->
<footer class="border-t border-[#1f2630] bg-[#07090d]/90 backdrop-blur px-4 py-2 text-[11px] text-slate-400 flex items-center justify-between">
  <div class="flex items-center gap-3">
    <span>Operator Console v1</span>
    <span class="k" x-show="config?.calibration?.calibrated_at" x-text="'calibrated ' + config?.calibration?.calibrated_at"></span>
  </div>
  <div class="flex items-center gap-3">
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
      <button class="btn success" @click="acceptDetect()" :disabled="!detect.candidates.length">Accept & save</button>
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

    // derived
    get deviceHost(){ return location.host.replace(/\/$/,''); },
    get siteId(){ return this.config?.site?.id || '-'; },
    get streamUrl(){ return '/stream.mjpg?t=' + Math.floor(Date.now()/5000); },
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
        // Low-thermal-delta banner
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
    cardClass(t){
      const p = t.level_pct||0;
      if (t.confidence !== 'high') return 'lo';
      if (p < 15 || p > 92) return 'al';
      return 'hi';
    },
    valueTint(t){
      const p = t.level_pct||0;
      if (t.confidence !== 'high') return 'lo';
      if (p < 15 || p > 92) return 'al';
      return 'hi';
    },
    primaryLabel(t){
      const r = t.reading;
      if (!r) return (t.level_pct||0).toFixed(1) + ' %';
      if (this.unit === 'in') return (r.level_in||0).toFixed(1) + ' in';
      return (r.level_ft||0).toFixed(2) + ' ft';
    },
    secondaryLabel(t){
      const r = t.reading;
      if (!r) return '';
      if (this.unit === 'in') return 'of ' + ((t.geometry?.height_ft||0)*12).toFixed(0) + ' in';
      return 'of ' + (t.geometry?.height_ft||0) + ' ft';
    },
    thirdLabel(t){
      const r = t.reading;
      if (!r) return (t.level_pct||0).toFixed(1)+' %';
      return Math.round(r.volume_bbl||0).toLocaleString() + ' bbl (' + (t.level_pct||0).toFixed(0) + '%)';
    },
    rateLabel(t){
      const rate = t.reading?.fill_rate_bbl_h;
      if (rate == null) return '-';
      const sign = rate > 0 ? 'arrow-up' : (rate < 0 ? 'arrow-dn' : 'arrow-zero');
      const arrow = rate > 0 ? '^' : (rate < 0 ? 'v' : '=');
      return arrow + ' ' + Math.abs(rate).toFixed(1) + ' bbl/h';
    },
    etaLabel(t){
      const r = t.reading;
      if (!r) return '-';
      if (r.minutes_to_full != null) return this.fmtDur(r.minutes_to_full*60) + ' to full';
      if (r.minutes_to_empty != null) return this.fmtDur(r.minutes_to_empty*60) + ' to empty';
      return 'stable';
    },
    fmtDur(sec){
      if (sec == null) return '-';
      sec = Math.max(0, Math.round(sec));
      const h = Math.floor(sec/3600), m = Math.floor((sec%3600)/60), s = sec%60;
      if (h) return h+'h '+m+'m';
      if (m) return m+'m '+s+'s';
      return s+'s';
    },
    fmt(n, d){ if (n==null) return '-'; return Number(n).toFixed(d==null?1:d); },
    candidateStyle(c){
      const img = document.querySelector('.stream-wrap img');
      if (!img || !this.state.w || !this.state.h) return '';
      const rect = img.getBoundingClientRect();
      const wrap = img.parentElement.getBoundingClientRect();
      const sx = rect.width / this.state.w;
      const sy = rect.height / this.state.h;
      const offX = rect.left - wrap.left;
      const offY = rect.top - wrap.top;
      return 'left:'+(offX + c.roi.x*sx)+'px;top:'+(offY + c.roi.y*sy)+'px;width:'+(c.roi.w*sx)+'px;height:'+(c.roi.h*sy)+'px';
    },
    async openDetectModal(){
      this.detect.modal = true;
      await this.runDetect();
    },
    async runDetect(){
      this.detect.running = true;
      try {
        const r = await fetch('/api/detect', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({max:6, samples:20, timeout_s:6})});
        const j = await r.json();
        this.detect.framesUsed = j.frames_used || 0;
        // Give every candidate a default geometry so the inputs work.
        this.detect.candidates = (j.candidates||[]).map((c,i) => ({
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

"""Build the premium supervisor dashboard flow JSON.

Takes the current tank-dashboard-flow.json as a base, then:
  - Adds dash-group-actions (new) + tpl-actions (new) between Overview and Config.
  - Replaces tpl-tank-cards format with premium cards (medium-colored hero,
    level-fill background, rate + ETA).
  - Replaces tpl-alerts format with a timeline-style feed.
  - Shifts group orders and bumps the tab info blurb.

Idempotent: re-running is safe.  Output overwrites node-red/tank-dashboard-flow.json.
"""

from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
FLOW_PATH = ROOT / "node-red" / "tank-dashboard-flow.json"


# ---------------------------------------------------------------------------
# 1. Actions bar — buttons for Calibrate / Snapshot / Record toggle / Refresh
# ---------------------------------------------------------------------------
ACTIONS_FORMAT = (
    "<style>\n"
    ".act{display:flex;align-items:center;gap:10px;padding:8px 14px;height:100%;"
    "background:linear-gradient(135deg,#121821,#1a222d);border:1px solid #2a3240;"
    "border-radius:12px;box-sizing:border-box;overflow:hidden;"
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}\n"
    ".act .btn{flex:0 0 auto;display:inline-flex;align-items:center;gap:6px;padding:8px 14px;"
    "border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;border:1px solid #2a3240;"
    "background:#0f1419;color:#cbd5e1;font-family:inherit;transition:all .15s;white-space:nowrap}\n"
    ".act .btn:hover:not(:disabled){background:#1e293b;color:#fff;border-color:#475569}\n"
    ".act .btn.primary{background:#2563eb;color:#fff;border-color:#2563eb;"
    "box-shadow:0 2px 8px rgba(37,99,235,0.25)}\n"
    ".act .btn.primary:hover:not(:disabled){background:#1d4ed8}\n"
    ".act .btn.rec{background:#1a0e0e;color:#f87171;border-color:#3f1d1d}\n"
    ".act .btn.rec.on{background:#b91c1c;color:#fff;border-color:#ef4444;"
    "animation:actp 1.4s ease-in-out infinite}\n"
    ".act .btn:disabled{opacity:0.4;cursor:not-allowed}\n"
    ".act .btn .d{font-size:12px;line-height:1}\n"
    ".act .sep{flex:1 1 auto;min-width:10px}\n"
    ".act .msg{font-size:11px;color:#94a3b8;font-family:monospace;text-align:right;"
    "min-width:160px;padding-right:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}\n"
    ".act .msg.ok{color:#4ade80}.act .msg.err{color:#fca5a5}.act .msg.busy{color:#fbbf24}\n"
    "@keyframes actp{0%,100%{box-shadow:0 0 0 0 rgba(239,68,68,0.5)}"
    "50%{box-shadow:0 0 0 8px rgba(239,68,68,0)}}\n"
    "</style>\n"
    "<div class=\"act\">\n"
    "  <button class=\"btn primary\" id=\"a-cal\" type=\"button\" title=\"10 s auto-calibration\">"
    "<span class=\"d\">\u25b6</span> Calibrate</button>\n"
    "  <button class=\"btn\" id=\"a-snap\" type=\"button\" title=\"Save current frame as PNG\">"
    "<span class=\"d\">\u25a3</span> Snapshot</button>\n"
    "  <button class=\"btn rec\" id=\"a-rec\" type=\"button\" title=\"Toggle video recording\">"
    "<span class=\"d\">\u25cf</span> <span id=\"a-rec-lbl\">Record</span></button>\n"
    "  <button class=\"btn\" id=\"a-refresh\" type=\"button\" title=\"Reload live stream\">"
    "<span class=\"d\">\u21bb</span> Reload Stream</button>\n"
    "  <button class=\"btn\" id=\"a-open\" type=\"button\" title=\"Open full operator console\">"
    "<span class=\"d\">\u2197</span> Console</button>\n"
    "  <div class=\"sep\"></div>\n"
    "  <div class=\"msg\" id=\"a-msg\">ready</div>\n"
    "</div>\n"
    "<script>\n"
    "(function(){\n"
    "  function deriveBase(){ var h=location.hostname; "
    "var m=h.match(/^p1880-(n-[a-z0-9-]+)-(.*)$/i); "
    "return m ? (location.protocol+'//p8080-'+m[1]+'-'+m[2]) : (location.protocol+'//'+h+':8080'); }\n"
    "  function boot(){\n"
    "    var cal=document.getElementById('a-cal'); if(!cal) return setTimeout(boot,100);\n"
    "    var snap=document.getElementById('a-snap'), rec=document.getElementById('a-rec'),\n"
    "        recLbl=document.getElementById('a-rec-lbl'), ref=document.getElementById('a-refresh'),\n"
    "        openBtn=document.getElementById('a-open'), msg=document.getElementById('a-msg'),\n"
    "        base=deriveBase();\n"
    "    function say(t,cls){ msg.textContent=t; msg.className='msg '+(cls||''); }\n"
    "    function call(path,opts){ say('working\u2026','busy'); "
    "return fetch(base+path, Object.assign({method:'POST'}, opts||{})).then(function(r){"
    "if(!r.ok) throw new Error('HTTP '+r.status); return r.text(); })"
    ".catch(function(e){ say('err: '+e.message,'err'); throw e; }); }\n"
    "    cal.onclick=function(){ cal.disabled=true; "
    "call('/api/calibrate').then(function(){ say('calibrated \u2713','ok'); })"
    ".catch(function(){}).then(function(){ setTimeout(function(){cal.disabled=false;},3000); }); };\n"
    "    snap.onclick=function(){ call('/api/snapshot').then(function(r){ "
    "try{ var j=JSON.parse(r); say('saved: '+(j.name||'ok'),'ok'); }"
    "catch(e){ say('snapshot \u2713','ok'); } }).catch(function(){}); };\n"
    "    function refreshRec(){ fetch(base+'/api/record/status').then(function(r){return r.json();})"
    ".then(function(s){ var on=s&&s.recording; rec.classList.toggle('on',!!on); "
    "recLbl.textContent=on?'Stop Rec':'Record'; }).catch(function(){}); }\n"
    "    rec.onclick=function(){ var on=rec.classList.contains('on'); "
    "var path=on?'/api/record/stop':'/api/record/start'; "
    "call(path).then(function(){ say(on?'recording stopped':'recording started','ok'); refreshRec(); })"
    ".catch(function(){}); };\n"
    "    ref.onclick=function(){ var btn=document.getElementById('lv-reload'); "
    "if(btn) btn.click(); say('stream reloaded','ok'); };\n"
    "    openBtn.onclick=function(){ window.open(base+'/','_blank','noopener'); };\n"
    "    refreshRec(); setInterval(refreshRec, 5000);\n"
    "  }\n"
    "  setTimeout(boot, 0);\n"
    "})();\n"
    "</script>"
)


# ---------------------------------------------------------------------------
# 2. Premium tank cards — hero level, medium-colored fill bg, rate + ETA strip
# ---------------------------------------------------------------------------
TANK_CARDS_FORMAT = (
    "<style>\n"
    ".pg{display:flex;flex-direction:column;gap:8px;padding:4px;height:100%;overflow-y:auto;"
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}\n"
    ".pc{position:relative;background:#151b24;border:1px solid #2a3240;border-radius:14px;"
    "overflow:hidden;transition:all .2s;flex:0 0 auto}\n"
    ".pc:hover{border-color:#3b4a5f}\n"
    ".pc.med-water{border-color:#0e4a6e}\n"
    ".pc.med-oil{border-color:#7a3d14}\n"
    ".pc.alert{border-color:#991b1b;box-shadow:0 0 0 1px rgba(239,68,68,0.35) inset}\n"
    ".pc .bg-fill{position:absolute;left:0;right:0;bottom:0;opacity:.10;transition:height .5s;"
    "pointer-events:none}\n"
    ".pc.med-water .bg-fill{background:linear-gradient(180deg,transparent,#38bdf8)}\n"
    ".pc.med-oil   .bg-fill{background:linear-gradient(180deg,transparent,#fb923c)}\n"
    ".pc.alert .bg-fill{background:linear-gradient(180deg,transparent,#ef4444);opacity:.15}\n"
    ".pc .hd{display:flex;justify-content:space-between;align-items:center;"
    "padding:10px 12px 4px 12px;position:relative;gap:8px}\n"
    ".pc .hd .nm{font-size:13px;font-weight:700;color:#e6e6e6;letter-spacing:-.01em;"
    "white-space:nowrap;overflow:hidden;text-overflow:ellipsis}\n"
    ".pc .hd .med{display:inline-flex;align-items:center;gap:4px;padding:3px 9px;"
    "border-radius:10px;font-size:9px;text-transform:uppercase;letter-spacing:.08em;font-weight:800;"
    "flex:0 0 auto}\n"
    ".pc.med-water .hd .med{background:#082f49;color:#38bdf8}\n"
    ".pc.med-oil   .hd .med{background:#3b1d09;color:#fb923c}\n"
    ".pc.med-unknown .hd .med{background:#1e293b;color:#94a3b8}\n"
    ".pc .body{padding:0 12px 10px 12px;position:relative}\n"
    ".pc .hero{display:flex;align-items:baseline;gap:6px;margin-top:2px}\n"
    ".pc .hero .v{font-size:30px;font-weight:800;letter-spacing:-.03em;color:#e6e6e6;"
    "line-height:1;font-variant-numeric:tabular-nums}\n"
    ".pc.med-water .hero .v{color:#7dd3fc}\n"
    ".pc.med-oil   .hero .v{color:#fdba74}\n"
    ".pc.alert .hero .v{color:#fca5a5}\n"
    ".pc .hero .u{font-size:12px;color:#64748b;font-weight:700;text-transform:uppercase;"
    "letter-spacing:.06em}\n"
    ".pc .sub{font-size:10px;color:#64748b;margin-top:2px;font-family:monospace;"
    "text-transform:uppercase;letter-spacing:.05em}\n"
    ".pc .bar{height:6px;background:#0a0e13;border-radius:4px;overflow:hidden;"
    "margin:10px 0 4px 0;position:relative}\n"
    ".pc .bar .fill{height:100%;border-radius:4px;transition:width .4s}\n"
    ".pc.med-water .bar .fill{background:linear-gradient(90deg,#0284c7,#38bdf8,#7dd3fc)}\n"
    ".pc.med-oil   .bar .fill{background:linear-gradient(90deg,#c2410c,#fb923c,#fdba74)}\n"
    ".pc.med-unknown .bar .fill{background:linear-gradient(90deg,#334155,#64748b,#94a3b8)}\n"
    ".pc.alert .bar .fill{background:linear-gradient(90deg,#b91c1c,#ef4444,#fca5a5)}\n"
    ".pc .bar .tick{position:absolute;top:-1px;bottom:-1px;width:1px;background:rgba(255,255,255,0.12)}\n"
    ".pc .rows{display:grid;grid-template-columns:1fr 1fr;gap:4px 12px;margin-top:8px;"
    "font-size:10px;font-family:monospace}\n"
    ".pc .rows .row{display:flex;justify-content:space-between}\n"
    ".pc .rows .k{color:#64748b;letter-spacing:.04em;text-transform:uppercase}\n"
    ".pc .rows .v2{color:#cbd5e1;font-weight:600}\n"
    ".pc .rate{display:flex;justify-content:space-between;align-items:center;padding:7px 12px;"
    "margin-top:6px;background:rgba(0,0,0,0.3);border-top:1px solid #1f2937}\n"
    ".pc .rate .lbl{font-size:9px;color:#64748b;text-transform:uppercase;letter-spacing:.08em;"
    "font-weight:700}\n"
    ".pc .rate .v{font-size:12px;font-weight:700;display:flex;align-items:center;gap:4px}\n"
    ".pc .rate .v.up{color:#4ade80}\n"
    ".pc .rate .v.dn{color:#fbbf24}\n"
    ".pc .rate .v.st{color:#64748b}\n"
    ".pc .rate .eta{color:#64748b;font-weight:500;font-size:10px;margin-left:6px;"
    "font-family:monospace}\n"
    ".pg .empty{padding:30px;text-align:center;color:#64748b;font-size:11px;font-family:monospace}\n"
    "</style>\n"
    "<div class=\"pg\" ng-if=\"msg.payload && msg.payload.tanks && msg.payload.tanks.length\">\n"
    "  <div class=\"pc\"\n"
    "       ng-repeat=\"t in msg.payload.tanks track by (t.id || t.name || $index)\"\n"
    "       ng-class=\"[ 'med-'+(t.medium||'unknown'), { alert: t.level_pct<20||t.level_pct>90 } ]\">\n"
    "    <div class=\"bg-fill\" ng-style=\"{ height: (t.level_pct || 0) + '%' }\"></div>\n"
    "    <div class=\"hd\">\n"
    "      <span class=\"nm\">{{t.name || t.id}}</span>\n"
    "      <span class=\"med\">{{t.medium || 'unknown'}}</span>\n"
    "    </div>\n"
    "    <div class=\"body\">\n"
    "      <div class=\"hero\">\n"
    "        <span class=\"v\" ng-if=\"t.reading && t.reading.level_ft !== undefined && t.reading.level_ft !== null\">{{t.reading.level_ft | number:1}}</span>\n"
    "        <span class=\"u\" ng-if=\"t.reading && t.reading.level_ft !== undefined && t.reading.level_ft !== null\">ft</span>\n"
    "        <span class=\"v\" ng-if=\"!t.reading || t.reading.level_ft === undefined || t.reading.level_ft === null\">{{t.level_pct | number:0}}</span>\n"
    "        <span class=\"u\" ng-if=\"!t.reading || t.reading.level_ft === undefined || t.reading.level_ft === null\">%</span>\n"
    "      </div>\n"
    "      <div class=\"sub\" ng-if=\"t.geometry && t.geometry.height_ft\">of {{t.geometry.height_ft | number:0}} ft &middot; \u2300 {{t.geometry.diameter_ft | number:0}} ft</div>\n"
    "      <div class=\"bar\">\n"
    "        <div class=\"fill\" ng-style=\"{ width: (t.level_pct || 0) + '%' }\"></div>\n"
    "        <div class=\"tick\" style=\"left:25%\"></div><div class=\"tick\" style=\"left:50%\"></div><div class=\"tick\" style=\"left:75%\"></div>\n"
    "      </div>\n"
    "      <div class=\"rows\">\n"
    "        <div class=\"row\"><span class=\"k\">level</span><span class=\"v2\">{{t.level_pct | number:1}}%</span></div>\n"
    "        <div class=\"row\" ng-if=\"t.reading && t.reading.volume_bbl !== undefined && t.reading.volume_bbl !== null\"><span class=\"k\">volume</span><span class=\"v2\">{{t.reading.volume_bbl | number:0}} bbl</span></div>\n"
    "        <div class=\"row\" ng-if=\"t.reading && t.reading.ullage_ft !== undefined && t.reading.ullage_ft !== null\"><span class=\"k\">ullage</span><span class=\"v2\">{{t.reading.ullage_ft | number:1}} ft</span></div>\n"
    "        <div class=\"row\"><span class=\"k\">temp</span><span class=\"v2\">{{t.temp_avg | number:1}}\u00b0C</span></div>\n"
    "        <div class=\"row\"><span class=\"k\">conf</span><span class=\"v2\">{{t.confidence}}</span></div>\n"
    "        <div class=\"row\" ng-if=\"t.medium_confidence !== undefined\"><span class=\"k\">med p</span><span class=\"v2\">{{t.medium_confidence | number:2}}</span></div>\n"
    "      </div>\n"
    "    </div>\n"
    "    <div class=\"rate\" ng-if=\"t.reading && t.reading.fill_rate_bbl_h !== undefined && t.reading.fill_rate_bbl_h !== null\">\n"
    "      <span class=\"lbl\">Rate</span>\n"
    "      <span class=\"v\" ng-class=\"{ up: t.reading.fill_rate_bbl_h > 0.5, dn: t.reading.fill_rate_bbl_h < -0.5, st: t.reading.fill_rate_bbl_h >= -0.5 && t.reading.fill_rate_bbl_h <= 0.5 }\">\n"
    "        <span ng-if=\"t.reading.fill_rate_bbl_h > 0.5\">\u25b2</span><span ng-if=\"t.reading.fill_rate_bbl_h < -0.5\">\u25bc</span><span ng-if=\"t.reading.fill_rate_bbl_h >= -0.5 && t.reading.fill_rate_bbl_h <= 0.5\">\u2500</span>\n"
    "        {{t.reading.fill_rate_bbl_h | number:1}} bbl/h\n"
    "        <span class=\"eta\" ng-if=\"t.reading.eta_hours !== undefined && t.reading.eta_hours !== null\">ETA {{t.reading.eta_hours | number:1}}h</span>\n"
    "      </span>\n"
    "    </div>\n"
    "  </div>\n"
    "</div>\n"
    "<div class=\"empty\" ng-if=\"!msg.payload || !msg.payload.tanks || !msg.payload.tanks.length\">waiting for first payload\u2026</div>"
)


# ---------------------------------------------------------------------------
# 3. Timeline-style alerts feed
# ---------------------------------------------------------------------------
ALERTS_FORMAT = (
    "<style>\n"
    ".at{padding:4px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
    "height:100%;overflow-y:auto}\n"
    ".at .hdr{display:flex;justify-content:space-between;align-items:baseline;"
    "padding:6px 10px 8px 10px;border-bottom:1px solid #1f2937;margin-bottom:4px}\n"
    ".at .hdr .t{font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;"
    "color:#94a3b8}\n"
    ".at .hdr .c{font-size:10px;color:#64748b;font-family:monospace}\n"
    ".at .row{display:flex;align-items:flex-start;gap:12px;padding:9px 12px;"
    "border-left:3px solid #1f2937;border-bottom:1px solid #181e26;transition:background .15s;"
    "margin-bottom:1px}\n"
    ".at .row:hover{background:rgba(15,20,25,0.6)}\n"
    ".at .row.LOW{border-left-color:#f59e0b}\n"
    ".at .row.HIGH{border-left-color:#ef4444}\n"
    ".at .row.OK{border-left-color:#22c55e}\n"
    ".at .row .ts{font-size:10px;color:#64748b;font-family:monospace;white-space:nowrap;"
    "padding-top:2px;min-width:72px;flex:0 0 auto}\n"
    ".at .row .body{flex:1;min-width:0}\n"
    ".at .row .title{display:flex;justify-content:space-between;align-items:baseline;gap:8px}\n"
    ".at .row .title .t{font-size:12px;font-weight:700;color:#e6e6e6;"
    "white-space:nowrap;overflow:hidden;text-overflow:ellipsis}\n"
    ".at .row .title .pill{font-size:9px;padding:2px 8px;border-radius:10px;text-transform:uppercase;"
    "letter-spacing:.06em;font-weight:800;flex:0 0 auto}\n"
    ".at .row.LOW  .pill{background:#2a1f00;color:#fbbf24}\n"
    ".at .row.HIGH .pill{background:#3f1d1d;color:#fca5a5}\n"
    ".at .row.OK   .pill{background:#052e16;color:#4ade80}\n"
    ".at .row .sub{font-size:11px;color:#94a3b8;margin-top:3px;font-family:monospace;"
    "white-space:nowrap;overflow:hidden;text-overflow:ellipsis}\n"
    ".at .empty{text-align:center;padding:40px;color:#475569;font-size:11px;font-family:monospace}\n"
    "</style>\n"
    "<div class=\"at\">\n"
    "  <div class=\"hdr\">\n"
    "    <span class=\"t\">Alert Feed</span>\n"
    "    <span class=\"c\">thresholds: LOW &lt; 20% &middot; HIGH &gt; 90%</span>\n"
    "  </div>\n"
    "  <div class=\"row\" ng-repeat=\"a in alerts | orderBy:'-ts' | limitTo: 40 track by $index\" ng-class=\"a.state\">\n"
    "    <span class=\"ts\">{{a.ts | date:'HH:mm:ss'}}</span>\n"
    "    <div class=\"body\">\n"
    "      <div class=\"title\">\n"
    "        <span class=\"t\">{{a.topic || a.payload}}</span>\n"
    "        <span class=\"pill\">{{a.state}}</span>\n"
    "      </div>\n"
    "      <div class=\"sub\">{{a.payload}}</div>\n"
    "    </div>\n"
    "  </div>\n"
    "  <div class=\"empty\" ng-if=\"!alerts || !alerts.length\">no alerts yet \u2014 tanks within threshold band</div>\n"
    "</div>\n"
    "<script>\n"
    "(function(scope){\n"
    "  scope.alerts = scope.alerts || [];\n"
    "  scope.$watch('msg', function(m){\n"
    "    if (!m) return;\n"
    "    if (Array.isArray(m.payload_history)) { scope.alerts = m.payload_history.slice(); }\n"
    "    else if (m.payload) { scope.alerts.push({ ts: Date.now(), state: m._state || 'OK', topic: m.topic, payload: m.payload });"
    " if (scope.alerts.length > 200) scope.alerts.splice(0, scope.alerts.length - 200); }\n"
    "  });\n"
    "})(scope);\n"
    "</script>"
)


NEW_GROUP_ACTIONS = {
    "id": "dash-group-actions",
    "type": "ui_group",
    "name": "Quick Actions",
    "tab": "dash-tab",
    "order": 2,
    "disp": False,
    "width": "24",
    "collapse": False,
}

NEW_TPL_ACTIONS = {
    "id": "tpl-actions",
    "type": "ui_template",
    "z": "thermal-tab",
    "group": "dash-group-actions",
    "name": "Action bar",
    "order": 1,
    "width": 24,
    "height": 1,
    "format": ACTIONS_FORMAT,
    "storeOutMessages": False,
    "fwdInMessages": False,
    "resendOnRefresh": True,
    "templateScope": "local",
    "x": 640,
    "y": 60,
    "wires": [[]],
}


# Remap existing group orders. dash-group-actions takes slot 2.
GROUP_ORDER = {
    "dash-group-overview": 1,
    "dash-group-actions": 2,
    "dash-group-config": 3,
    "dash-group-live-view": 4,
    "dash-group-tanks": 5,
    "dash-group-trends": 6,
    "dash-group-alerts": 7,
    "dash-group-events": 8,
}


INFO_V2 = (
    "Thermal tank Supervisor dashboard v0.4.3 (premium)\n\n"
    "POST endpoint:   /thermal/ingest  (pushed by the thermal-analyzer container)\n"
    "Thermal API:     flow.thermal_base (default resolved from hostname, override with THERMAL_API)\n\n"
    "Groups (page width = 24 cells):\n"
    "  \u2022 Overview        \u2014 fleet KPI pills + site header + deep link\n"
    "  \u2022 Quick Actions   \u2014 Calibrate / Snapshot / Record toggle / Reload stream (hidden title)\n"
    "  \u2022 Tank Config     \u2014 collapsed: rename tanks + override medium (water/oil/auto)\n"
    "  \u2022 Live View       \u2014 MJPEG stream (server-side timestamp burned in)\n"
    "  \u2022 Tanks           \u2014 premium per-tank cards with level fill, rate, ETA\n"
    "  \u2022 Trends          \u2014 24 h level & temperature history\n"
    "  \u2022 Alerts          \u2014 timeline feed (LOW/HIGH/OK, 200-row ring)\n"
    "  \u2022 Events          \u2014 raw ingest log (collapsed)\n\n"
    "User-configurable overrides live in flow.context('tank_overrides') = {\n"
    "  '<tank_id>': { name: '<display name>', medium: 'auto' | 'water' | 'oil' }\n"
    "}\n"
    "Overrides are applied inside ingest-process before any downstream rendering.\n"
)


def main() -> None:
    data = json.loads(FLOW_PATH.read_text(encoding="utf-8"))

    ids = {n.get("id"): n for n in data}

    # 1. Bump tab info
    if "thermal-tab" in ids:
        ids["thermal-tab"]["info"] = INFO_V2

    # 2. Reorder existing groups
    for gid, order in GROUP_ORDER.items():
        if gid in ids:
            ids[gid]["order"] = order

    # 3. Insert / replace dash-group-actions right after dash-group-overview
    if "dash-group-actions" in ids:
        ids["dash-group-actions"].update(NEW_GROUP_ACTIONS)
    else:
        # Insert after overview group
        idx = next(i for i, n in enumerate(data) if n.get("id") == "dash-group-overview") + 1
        data.insert(idx, dict(NEW_GROUP_ACTIONS))

    # 4. Insert / replace tpl-actions
    if "tpl-actions" in ids:
        ids["tpl-actions"].update(NEW_TPL_ACTIONS)
    else:
        # Put next to tpl-overview
        idx = next(i for i, n in enumerate(data) if n.get("id") == "tpl-overview") + 1
        data.insert(idx, dict(NEW_TPL_ACTIONS))

    # 5. Rebuild id index after inserts
    ids = {n.get("id"): n for n in data}

    # 6. Replace tank cards format
    if "tpl-tank-cards" in ids:
        ids["tpl-tank-cards"]["format"] = TANK_CARDS_FORMAT

    # 7. Replace alerts format
    if "tpl-alerts" in ids:
        ids["tpl-alerts"]["format"] = ALERTS_FORMAT

    FLOW_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote premium flow to {FLOW_PATH}")


if __name__ == "__main__":
    main()

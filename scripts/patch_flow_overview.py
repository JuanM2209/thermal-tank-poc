"""Patch tpl-overview format in tank-dashboard-flow.json to add fleet KPI pills.

Idempotent: run from repo root, writes back to node-red/tank-dashboard-flow.json.
"""

from __future__ import annotations

import json
import pathlib

FLOW_PATH = pathlib.Path(__file__).resolve().parent.parent / "node-red" / "tank-dashboard-flow.json"

NEW_FORMAT = (
    "<style>\n"
    ".ov{display:flex;align-items:center;gap:14px;padding:10px 14px;color:#e6e6e6;"
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;height:100%;"
    "background:linear-gradient(135deg,#121821 0%,#1a222d 100%);border-radius:12px;"
    "border:1px solid #2a3240;box-sizing:border-box}\n"
    ".ov .site{display:flex;flex-direction:column;min-width:0;padding-right:14px;"
    "border-right:1px solid #2a3240;flex:0 0 auto}\n"
    ".ov .site .t1{font-size:17px;font-weight:700;letter-spacing:-0.02em;"
    "white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:240px}\n"
    ".ov .site .t2{font-size:10px;color:#64748b;font-family:monospace;"
    "text-transform:uppercase;letter-spacing:.08em;margin-top:3px}\n"
    ".ov .kpis{display:flex;gap:10px;flex:1 1 auto;min-width:0;overflow:hidden}\n"
    ".ov .kpi{background:#0f1419;border:1px solid #1f2937;border-radius:10px;"
    "padding:7px 14px;display:flex;flex-direction:column;gap:1px;min-width:72px}\n"
    ".ov .kpi .v{font-size:20px;font-weight:700;letter-spacing:-0.02em;line-height:1.1;"
    "font-variant-numeric:tabular-nums;color:#e6e6e6}\n"
    ".ov .kpi .l{font-size:9px;color:#64748b;text-transform:uppercase;letter-spacing:.1em;"
    "font-weight:700}\n"
    ".ov .kpi.oil{border-color:#3b1d09}.ov .kpi.oil .v{color:#fb923c}\n"
    ".ov .kpi.water{border-color:#082f49}.ov .kpi.water .v{color:#38bdf8}\n"
    ".ov .kpi.alert{border-color:#3f1d1d}.ov .kpi.alert .v{color:#fca5a5}\n"
    ".ov .kpi.avg .v{color:#4ade80}\n"
    ".ov .r{display:flex;align-items:center;gap:8px;margin-left:auto;flex:0 0 auto}\n"
    ".ov .chips{display:flex;gap:5px}\n"
    ".ov .chip{font-size:9px;padding:3px 8px;border-radius:8px;letter-spacing:.06em;"
    "text-transform:uppercase;font-weight:700}\n"
    ".ov .chip.ok{background:#052e16;color:#4ade80}\n"
    ".ov .chip.warn{background:#2a1f00;color:#fbbf24}\n"
    ".ov .chip.bad{background:#3f1d1d;color:#fca5a5}\n"
    ".ov .chip.n{background:#1e293b;color:#94a3b8}\n"
    ".ov a.btn{display:inline-flex;align-items:center;gap:5px;padding:7px 12px;"
    "border-radius:8px;background:#2563eb;color:#fff;text-decoration:none;font-size:12px;"
    "font-weight:600;white-space:nowrap;box-shadow:0 2px 8px rgba(37,99,235,0.3)}\n"
    ".ov a.btn:hover{background:#1d4ed8}\n"
    "</style>\n"
    "<div class=\"ov\" ng-init=\"tanks = (msg.payload && msg.payload.tanks) || []\">\n"
    "  <div class=\"site\">\n"
    "    <div class=\"t1\">{{msg.payload.site_id || 'Supervisor'}}</div>\n"
    "    <div class=\"t2\">{{msg.payload.ts ? (msg.payload.ts | date:'yyyy-MM-dd HH:mm:ss') : '--:--:--'}}</div>\n"
    "  </div>\n"
    "  <div class=\"kpis\">\n"
    "    <div class=\"kpi\"><div class=\"v\">{{tanks.length}}</div><div class=\"l\">Tanks</div></div>\n"
    "    <div class=\"kpi oil\"><div class=\"v\">{{(tanks | filter:{medium:'oil'}).length}}</div><div class=\"l\">Oil</div></div>\n"
    "    <div class=\"kpi water\"><div class=\"v\">{{(tanks | filter:{medium:'water'}).length}}</div><div class=\"l\">Water</div></div>\n"
    "    <div class=\"kpi alert\"><div class=\"v\">{{(tanks | filter:alertFn).length}}</div><div class=\"l\">Alerts</div></div>\n"
    "    <div class=\"kpi avg\"><div class=\"v\">{{tanks.length ? (sumLevel(tanks)/tanks.length | number:0) : '--'}}%</div><div class=\"l\">Avg Level</div></div>\n"
    "  </div>\n"
    "  <div class=\"r\">\n"
    "    <div class=\"chips\">\n"
    "      <span class=\"chip\" ng-class=\"{ ok: fresh, warn: !fresh && msg.payload.ts, bad: !msg.payload.ts }\" ng-init=\"fresh = (msg.payload.ts && (Date.now() - msg.payload.ts) < 30000)\">{{fresh ? 'live' : (msg.payload.ts ? 'stale' : 'offline')}}</span>\n"
    "      <span class=\"chip\" ng-class=\"{ ok: msg.payload.calibration && msg.payload.calibration.calibrated_at, n: !msg.payload.calibration || !msg.payload.calibration.calibrated_at }\">{{msg.payload.calibration && msg.payload.calibration.calibrated_at ? 'cal' : 'uncal'}}</span>\n"
    "    </div>\n"
    "    <a class=\"btn\" id=\"op-link\" href=\"#\" target=\"_blank\" rel=\"noopener\">Operator \u2197</a>\n"
    "  </div>\n"
    "</div>\n"
    "<script>\n"
    "(function(){\n"
    "  function apply(){\n"
    "    var a = document.getElementById('op-link');\n"
    "    if (!a) return setTimeout(apply, 100);\n"
    "    var h = location.hostname;\n"
    "    var m = h.match(/^p1880-(n-[a-z0-9-]+)-(.*)$/i);\n"
    "    a.href = m ? (location.protocol + '//p8080-' + m[1] + '-' + m[2] + '/') : (location.protocol + '//' + h + ':8080/');\n"
    "  }\n"
    "  setTimeout(apply, 0);\n"
    "})();\n"
    "</script>"
)

# AngularJS filter helpers need to be attached to scope. The simplest path: register
# helper functions inside an inline <script> that finds the Angular scope of this
# template. But ui_template already binds msg on $scope; we can add helpers via a
# second pass. Easier: rewrite the filters using inline expressions.

SIMPLE_FORMAT = NEW_FORMAT.replace(
    "(tanks | filter:alertFn).length",
    "countAlerts(tanks)",
).replace(
    "sumLevel(tanks)",
    "avgLevel(tanks)",
)

HELPER_SCRIPT = (
    "<script>\n"
    "(function(){\n"
    "  function wait(cb){ var t = document.querySelector('.ov'); "
    "if (!t) return setTimeout(function(){wait(cb);}, 100); "
    "var s = angular.element(t).scope(); if (!s) return setTimeout(function(){wait(cb);}, 100); "
    "cb(s); }\n"
    "  wait(function(scope){\n"
    "    scope.countAlerts = function(ts){ if(!ts) return 0; var n=0; "
    "for (var i=0;i<ts.length;i++){ var p=ts[i].level_pct; if (p===undefined||p===null) continue; "
    "if (p<20||p>90) n++; } return n; };\n"
    "    scope.avgLevel = function(ts){ if(!ts||!ts.length) return 0; var s=0,c=0; "
    "for (var i=0;i<ts.length;i++){ var p=ts[i].level_pct; if (p===undefined||p===null) continue; s+=p; c++; } "
    "return c?s/c:0; };\n"
    "    scope.$applyAsync();\n"
    "  });\n"
    "})();\n"
    "</script>"
)

FINAL_FORMAT = SIMPLE_FORMAT.replace("</script>", "</script>\n" + HELPER_SCRIPT.strip(), 1)


def main() -> None:
    data = json.loads(FLOW_PATH.read_text(encoding="utf-8"))
    for node in data:
        if node.get("id") == "tpl-overview":
            node["format"] = FINAL_FORMAT
            node["height"] = 3  # taller for KPI pills
            break
    else:
        raise SystemExit("tpl-overview not found")
    FLOW_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"patched {FLOW_PATH}")


if __name__ == "__main__":
    main()

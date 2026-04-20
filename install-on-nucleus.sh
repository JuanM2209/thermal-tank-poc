#!/bin/sh
# =====================================================================
# install-on-nucleus.sh — one-shot installer for a Nucleus edge device
#
# Does everything in one shot:
#   1. Stops & removes the previous thermal-analyzer container + old images
#   2. Downloads the new ARMv7 image tarball + config.yaml from the release
#   3. docker load + docker run with --device=/dev/video0 --network host
#   4. Safely merges the Node-RED supervisor flow into the existing NR
#      (only touches the thermal-tab; leaves other flows alone)
#
# Idempotent — re-run after every release to upgrade in place.
#
# Usage on the Nucleus terminal:
#   curl -fsSL https://raw.githubusercontent.com/JuanM2209/thermal-tank-poc/main/install-on-nucleus.sh | sh
# =====================================================================

set -eu

# -----------------------------------------------------------------------------
# EDIT THESE THREE ONLY
# -----------------------------------------------------------------------------
GH_USER="JuanM2209"
GH_REPO="thermal-tank-poc"
TAG="v0.9.1"
# -----------------------------------------------------------------------------

IMG="thermal-analyzer:armv7"
NAME="thermal-analyzer"
NR_URL="${THERMAL_NR_URL:-http://127.0.0.1:1880}"

# Pick a writable persistent path by actually trying to create it.
INSTALL_DIR=""
for candidate in /home/admin/thermal /data/thermal /data/home/admin/thermal /tmp/thermal; do
    if mkdir -p "$candidate" 2>/dev/null && [ -w "$candidate" ] && (touch "$candidate/.writetest" 2>/dev/null); then
        rm -f "$candidate/.writetest"
        INSTALL_DIR="$candidate"
        break
    fi
done
if [ -z "$INSTALL_DIR" ]; then
    echo "no writable location found among /home/admin, /data, /tmp — aborting"
    exit 1
fi
mkdir -p "$INSTALL_DIR/data"   # runtime overrides land here

BASE="https://github.com/${GH_USER}/${GH_REPO}"
RAW_BASE="https://raw.githubusercontent.com/${GH_USER}/${GH_REPO}/main"
IMG_URL="${BASE}/releases/download/${TAG}/thermal-analyzer-armv7.tar.gz"
CFG_URL="${RAW_BASE}/thermal/config.yaml"
FLOW_URL="${RAW_BASE}/node-red/tank-dashboard-flow.json"

say()   { printf '\033[36m[thermal]\033[0m %s\n' "$*"; }
warn()  { printf '\033[33m[thermal]\033[0m %s\n' "$*"; }
err()   { printf '\033[31m[thermal]\033[0m %s\n' "$*"; }

say "1/7 Checking prerequisites…"
for cmd in docker curl gzip; do
    command -v $cmd >/dev/null || { err "missing: $cmd"; exit 1; }
done
docker info >/dev/null 2>&1 || { err "docker daemon not reachable"; exit 1; }
if [ ! -e /dev/video0 ]; then
    warn "/dev/video0 not present — the container will start but camera capture will fail until you plug in the P2 Pro"
fi

say "2/7 Preparing $INSTALL_DIR…"
cd "$INSTALL_DIR"

say "3/7 Downloading config.yaml (only if absent)…"
if [ ! -f config.yaml ]; then
    curl -fsSL "$CFG_URL" -o config.yaml
    say "    -> $INSTALL_DIR/config.yaml  (edit ROIs interactively on the web UI)"
else
    say "    -> keeping existing config.yaml"
fi

say "4/7 Stopping previous $NAME + cleaning up old images…"
if docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then
    docker rm -f "$NAME" >/dev/null
    say "    -> removed container: $NAME"
fi
for old in $(docker images --format '{{.Repository}}:{{.Tag}}' | grep -E "^thermal-analyzer:" || true); do
    if [ "$old" != "$IMG" ]; then
        docker rmi "$old" >/dev/null 2>&1 && say "    -> removed old image: $old" || true
    fi
done
docker rmi "$IMG" >/dev/null 2>&1 || true

say "5/7 Loading new image from GitHub release…"
curl -fL "$IMG_URL" | gunzip | docker load

say "6/7 Starting $NAME…"
docker run -d \
    --name "$NAME" \
    --restart unless-stopped \
    --user 0:0 \
    --device=/dev/video0 \
    --network host \
    -v "$INSTALL_DIR/config.yaml:/app/config.yaml:ro" \
    -v "$INSTALL_DIR/data:/app/data" \
    -e PUBLISH_ENDPOINT="http://127.0.0.1:1880/thermal/ingest" \
    "$IMG" >/dev/null

say "7/7 Importing Node-RED supervisor dashboard…"
curl -fsSL "$FLOW_URL" -o "$INSTALL_DIR/tank-dashboard-flow.json" || {
    warn "    -> could not download flow JSON; will skip NR import"
    skip_nr=1
}

if [ -z "${skip_nr:-}" ]; then
    if ! curl -fs -o /dev/null "$NR_URL/flows"; then
        warn "    -> Node-RED not reachable at $NR_URL — skipping automatic import"
        warn "       (you can import $INSTALL_DIR/tank-dashboard-flow.json manually from NR UI)"
    elif command -v python3 >/dev/null || command -v python >/dev/null; then
        PY=$(command -v python3 || command -v python)
        if "$PY" - "$INSTALL_DIR/tank-dashboard-flow.json" "$NR_URL" <<'PYEOF'
import json, sys, urllib.request

new_flow_path, nr_url = sys.argv[1], sys.argv[2].rstrip("/")

with open(new_flow_path) as f:
    new_nodes = json.load(f)

# Collect every id our flow owns — including legacy v0.3 groups we want to drop
new_ids = {n.get("id") for n in new_nodes if n.get("id")}
LEGACY_GROUPS = {
    "dash-group-controls", "dash-group-levels", "dash-group-stream",
    "dash-group-rec", "dash-group-health",
}
our_ids = new_ids | LEGACY_GROUPS

# Node-RED dashboard allows exactly one `ui_base` per /ui.
# Our flow ships one (id="dash-ui-base") — drop any pre-existing one so
# our theme (dark + blue) wins without creating a duplicate config node.
SINGLETON_TYPES = {"ui_base"}

# Fetch current flows
req = urllib.request.Request(f"{nr_url}/flows", headers={"Accept": "application/json"})
with urllib.request.urlopen(req, timeout=5) as r:
    current = json.load(r)

kept = [
    n for n in current
    if n.get("z") != "thermal-tab"
    and n.get("id") not in our_ids
    and n.get("type") not in SINGLETON_TYPES
]
merged = kept + new_nodes

body = json.dumps(merged).encode()
req = urllib.request.Request(
    f"{nr_url}/flows",
    data=body,
    headers={
        "Content-Type": "application/json",
        "Node-RED-Deployment-Type": "full",
    },
    method="POST",
)
with urllib.request.urlopen(req, timeout=10) as r:
    r.read()
print(f"    -> merged {len(new_nodes)} nodes into Node-RED ({len(kept)} existing nodes preserved)")
PYEOF
        then
            say "    -> Node-RED flow installed"
        else
            warn "    -> automatic NR import failed — import $INSTALL_DIR/tank-dashboard-flow.json manually"
        fi
    else
        warn "    -> no python on host — import $INSTALL_DIR/tank-dashboard-flow.json manually in NR"
    fi
fi

sleep 2
say ""
say "=================================================================="
say " Install complete."
say "=================================================================="
docker ps --filter name="$NAME" --format 'table {{.Names}}\t{{.Status}}'
say ""
say " Operator Console  ->  https://p8080-n-1065-d.datadesng.com/"
say " Supervisor NR/ui  ->  https://p1880-n-1065-d.datadesng.com/ui"
say " Logs              ->  docker logs -f $NAME"
say " Config override   ->  $INSTALL_DIR/config.yaml  (restart container to apply)"
say "=================================================================="

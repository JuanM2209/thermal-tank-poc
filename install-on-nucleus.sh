#!/bin/sh
# =====================================================================
# install-on-nucleus.sh — one-shot installer for a Nucleus edge device
#
# After building the image on Docker Desktop and uploading the .tar.gz to
# a GitHub release, this is the single copy/paste command users run on
# the Nucleus terminal (Cockpit > Terminal, or SSH).
#
# Usage (AFTER you edit the URL below to your real GitHub release asset):
#   curl -fsSL https://raw.githubusercontent.com/USER/REPO/main/install-on-nucleus.sh | sh
#
# The script is idempotent: re-running it pulls a fresh image tarball and
# re-launches the container. It never touches existing Nucleus containers.
# =====================================================================

set -eu

# -----------------------------------------------------------------------------
# EDIT THESE THREE ONLY
# -----------------------------------------------------------------------------
GH_USER="JuanM2209"
GH_REPO="thermal-tank-poc"
TAG="v0.1.0"
# -----------------------------------------------------------------------------

IMG="thermal-analyzer:armv7"
NAME="thermal-analyzer"
# Pick a writable persistent path by actually trying to create it.
# [ -w /data ] can return true while mkdir /data/<x> fails for non-root users,
# because the /data mount root is owned by root. Test for real.
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
IMG_URL="https://github.com/${GH_USER}/${GH_REPO}/releases/download/${TAG}/thermal-analyzer-armv7.tar.gz"
CFG_URL="https://raw.githubusercontent.com/${GH_USER}/${GH_REPO}/main/thermal/config.yaml"

say() { printf '\033[36m[thermal]\033[0m %s\n' "$*"; }

say "1/5 Checking prerequisites..."
for cmd in docker curl gzip; do
    command -v $cmd >/dev/null || { echo "missing: $cmd"; exit 1; }
done
docker info >/dev/null 2>&1 || { echo "docker daemon not reachable"; exit 1; }
[ -e /dev/video0 ] || { echo "/dev/video0 not present — plug in the camera first"; exit 1; }

say "2/5 Preparing $INSTALL_DIR..."
cd "$INSTALL_DIR"

say "3/5 Downloading config.yaml (only if absent)..."
if [ ! -f config.yaml ]; then
    curl -fsSL "$CFG_URL" -o config.yaml
    say "    -> $INSTALL_DIR/config.yaml  (edit ROIs later with roi_picker)"
else
    say "    -> keeping existing config.yaml"
fi

say "4/5 Loading image from GitHub release (~150-200 MB)..."
curl -fL "$IMG_URL" | gunzip | docker load

# Stop/remove only OUR own container — never touch nucleus-agent/node-red/etc.
if docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then
    say "    -> removing previous $NAME container"
    docker rm -f "$NAME" >/dev/null
fi

say "5/5 Starting $NAME..."
docker run -d \
    --name "$NAME" \
    --restart unless-stopped \
    --user 0:0 \
    --device=/dev/video0 \
    --network host \
    -v "$INSTALL_DIR/config.yaml:/app/config.yaml:ro" \
    -e PUBLISH_ENDPOINT="http://127.0.0.1:1880/thermal/ingest" \
    "$IMG" >/dev/null

sleep 2
say "Status:"
docker ps --filter name="$NAME" --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
say "Follow logs:   docker logs -f $NAME"
say "Web preview:   http://<nucleus-ip>:8080/"
say "Node-RED flow: import node-red/tank-dashboard-flow.json at port 1880"

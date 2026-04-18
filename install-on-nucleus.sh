#!/bin/sh
# =====================================================================
# install-on-nucleus.sh — one-shot installer for a Nucleus edge device
#
# Idempotent:
#   - pulls the tarball from the GitHub release
#   - stops/removes the PREVIOUS thermal-analyzer container + image (ours only)
#   - loads the new image, recreates the container
#   - NEVER touches containers that are not named "thermal-analyzer"
#
# Usage (AFTER you edit the URL below to your real GitHub release asset):
#   curl -fsSL https://raw.githubusercontent.com/USER/REPO/main/install-on-nucleus.sh | sh
# =====================================================================

set -eu

# -----------------------------------------------------------------------------
# EDIT THESE THREE ONLY
# -----------------------------------------------------------------------------
GH_USER="JuanM2209"
GH_REPO="thermal-tank-poc"
TAG="v0.3.0"
# -----------------------------------------------------------------------------

IMG="thermal-analyzer:armv7"
NAME="thermal-analyzer"

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

IMG_URL="https://github.com/${GH_USER}/${GH_REPO}/releases/download/${TAG}/thermal-analyzer-armv7.tar.gz"
CFG_URL="https://raw.githubusercontent.com/${GH_USER}/${GH_REPO}/main/thermal/config.yaml"

say() { printf '\033[36m[thermal]\033[0m %s\n' "$*"; }

say "1/6 Checking prerequisites…"
for cmd in docker curl gzip; do
    command -v $cmd >/dev/null || { echo "missing: $cmd"; exit 1; }
done
docker info >/dev/null 2>&1 || { echo "docker daemon not reachable"; exit 1; }
[ -e /dev/video0 ] || { echo "/dev/video0 not present — plug in the camera first"; exit 1; }

say "2/6 Preparing $INSTALL_DIR…"
cd "$INSTALL_DIR"

say "3/6 Downloading config.yaml (only if absent)…"
if [ ! -f config.yaml ]; then
    curl -fsSL "$CFG_URL" -o config.yaml
    say "    -> $INSTALL_DIR/config.yaml  (edit ROIs interactively on the web UI)"
else
    say "    -> keeping existing config.yaml"
fi

say "4/6 Stopping previous $NAME (and cleaning up our old image)…"
if docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then
    docker rm -f "$NAME" >/dev/null
    say "    -> removed container: $NAME"
fi
# Remove ONLY our previous image version so the filesystem doesn't grow
for old in $(docker images --format '{{.Repository}}:{{.Tag}}' | grep -E "^thermal-analyzer:" || true); do
    if [ "$old" != "$IMG" ]; then
        docker rmi "$old" >/dev/null 2>&1 && say "    -> removed old image: $old" || true
    fi
done
# Also flush the current tag before loading fresh (safe: re-loaded right after)
docker rmi "$IMG" >/dev/null 2>&1 || true

say "5/6 Loading new image from GitHub release…"
curl -fL "$IMG_URL" | gunzip | docker load

say "6/6 Starting $NAME…"
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

sleep 2
say "Status:"
docker ps --filter name="$NAME" --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
say "Follow logs:   docker logs -f $NAME"
say "Web preview:   http://<nucleus-ip>:8080/  (interactive dashboard)"
say "Node-RED flow: import node-red/tank-dashboard-flow.json at port 1880"

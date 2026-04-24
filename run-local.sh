#!/usr/bin/env sh
# =====================================================================
# run-local.sh -- bring the thermal analyzer up on a Linux box in ~30s.
#
# Purpose: bypass the ARMv7 Docker build entirely and get http://<host>:8080
# answering *now*, so the camera can be validated before we spend another
# 45 min on a cross-compile.
#
# Works on: x86_64 Ubuntu/Debian/Mint, Fedora, Arch. Uses native wheels
# (~5-10s pip install) instead of source-compiling anything.
#
# Requirements:
#   - Thermal Master P2 Pro plugged in (shows up as /dev/video*)
#   - user is in the 'video' group (or run with sudo once)
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/JuanM2209/thermal-tank-poc/main/run-local.sh | sh
#
# or clone + run:
#   git clone https://github.com/JuanM2209/thermal-tank-poc.git
#   cd thermal-tank-poc && ./run-local.sh
# =====================================================================
set -e  # deliberately NOT -u: venv activate scripts on many distros
        # reference unset vars (_OLD_VIRTUAL_PATH et al.) and die on set -u.

REPO="https://github.com/JuanM2209/thermal-tank-poc.git"
WORKDIR="${HOME}/thermal-tank-poc"
PORT="${PORT:-8080}"

info() { printf '\033[36m[run-local]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[run-local]\033[0m %s\n' "$*"; }
die()  { printf '\033[31m[run-local]\033[0m %s\n' "$*" >&2; exit 1; }

# ---------- 0. refuse to run on the Nucleus itself -------------------
# The Nucleus is ARMv7 + Python 3.5 + Yocto (no apt/yum/opkg python wheels
# for modern opencv). pip install opencv-python on that box would try to
# source-compile the whole toolchain for hours and would OOM inside 490 MB.
# The Nucleus gets the Docker image via install-on-nucleus.sh instead.
ARCH=$(uname -m 2>/dev/null || echo unknown)
case "$ARCH" in
    x86_64|amd64) : ;;  # good
    aarch64|arm64)
        info "Running on aarch64 -- OK, pip has arm64 wheels for opencv/numpy."
        ;;
    armv7l|armv6l|arm)
        die "This host is ARMv7 ($ARCH). Native pip-install opencv is not feasible here (no wheels + too little RAM).
     If this is the Nucleus: use install-on-nucleus.sh with the Docker image instead.
     If this is a Raspberry Pi you want to test on, ask and I'll build a piwheels path."
        ;;
    *)
        warn "Unknown arch '$ARCH' -- proceeding but pip may need to source-compile."
        ;;
esac

# ---------- 1. fetch or refresh the repo ------------------------------
if [ -d "$WORKDIR/.git" ]; then
    info "Repo already at $WORKDIR -- pulling latest main"
    git -C "$WORKDIR" fetch origin main --quiet
    git -C "$WORKDIR" reset --hard origin/main --quiet
else
    info "Cloning $REPO -> $WORKDIR"
    git clone --depth 1 --quiet "$REPO" "$WORKDIR"
fi

cd "$WORKDIR/thermal"

# ---------- 2. install v4l-utils if missing ---------------------------
# Only needed to list /dev/video* and diagnose the camera. opencv itself
# does not need it at runtime on x86_64.
if ! command -v v4l2-ctl >/dev/null 2>&1; then
    info "Installing v4l-utils (requires sudo, one-time)"
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update -qq && sudo apt-get install -y -qq v4l-utils
    elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y -q v4l-utils
    elif command -v pacman >/dev/null 2>&1; then
        sudo pacman -S --noconfirm v4l-utils
    else
        warn "Unknown package manager -- install v4l-utils manually for camera diagnostics"
    fi
fi

# ---------- 3. venv + pip deps ----------------------------------------
# Python 3.9+ is required (f-string with '=' debug form is used).
PY=$(command -v python3 || command -v python)
[ -n "$PY" ] || die "python3 not found. Install: sudo apt install python3 python3-venv python3-pip"

if [ ! -d .venv ]; then
    info "Creating venv at $WORKDIR/thermal/.venv"
    "$PY" -m venv .venv
fi

# Use the venv's python+pip directly instead of sourcing activate.
# activate does  [ -n "$_OLD_VIRTUAL_PATH" ]  etc. which crashes under set -u
# and is brittle across shells (bash, dash, busybox ash). Direct paths are
# boring and work everywhere.
VENV_PY="$WORKDIR/thermal/.venv/bin/python"
VENV_PIP="$WORKDIR/thermal/.venv/bin/pip"
[ -x "$VENV_PY" ] || die "venv python missing at $VENV_PY"

info "Installing runtime deps (opencv-python, numpy, pyyaml, flask)"
"$VENV_PIP" install --quiet --upgrade pip
"$VENV_PIP" install --quiet \
    "opencv-python==4.10.0.84" \
    "numpy<2" \
    "pyyaml==6.0.2" \
    "flask==3.0.3"

# ---------- 4. camera presence check ----------------------------------
# Non-fatal: user may plug it in after launch. We just print what we see.
info "Cameras visible now:"
if command -v v4l2-ctl >/dev/null 2>&1; then
    v4l2-ctl --list-devices 2>/dev/null | sed 's/^/    /' || true
fi
ls /dev/video* 2>/dev/null | sed 's/^/    /' || warn "No /dev/video* found -- plug in the P2 Pro"

# ---------- 5. launch -------------------------------------------------
info "Starting thermal analyzer on port ${PORT}"
info "Open:  http://$(hostname -I 2>/dev/null | awk '{print $1}'):${PORT}/"
info "Press Ctrl+C to stop."

cd app
exec "$VENV_PY" -u main.py

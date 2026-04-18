# Build with:
#   docker buildx build --platform linux/arm/v7 -t thermal-analyzer:armv7 --load .
#
# Target ~120 MB compressed. python:3.11-slim ARMv7 base is ~45 MB;
# OpenCV wheels are pulled from piwheels.org which ships pre-built ARMv7
# binaries for every pip package relevant to the Raspberry Pi ecosystem.
# That avoids a 30+ min from-source compile inside QEMU.

FROM --platform=linux/arm/v7 python:3.11-slim-bookworm AS builder

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# piwheels publishes platform-tagged wheels; --prefer-binary forces pip to pick
# a wheel when one exists (falls back to source if nothing matches).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --upgrade pip wheel && \
    pip install \
        --extra-index-url https://www.piwheels.org/simple \
        --prefer-binary \
        --only-binary ":all:" \
        "opencv-python-headless>=4.6,<4.11" \
        "numpy<2" \
        "pyyaml==6.0.2" \
        "flask==3.0.3"


# ---------- Runtime stage (no compilers, no apt caches) ----------
FROM --platform=linux/arm/v7 python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LANG=C.UTF-8 \
    PATH="/opt/venv/bin:$PATH"

# Runtime shared libs:
#   libgl1 / libglib2.0-0   -> opencv-python-headless
#   libopenblas0            -> piwheels numpy is linked against OpenBLAS
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libopenblas0 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY app/ /app/
COPY config.yaml /app/config.yaml

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,sys; sys.exit(0 if os.path.exists('/tmp/alive') else 1)"

CMD ["python", "-u", "/app/main.py"]

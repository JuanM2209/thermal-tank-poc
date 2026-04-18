# Build with:
#   docker buildx build --platform linux/arm/v7 -t thermal-analyzer:armv7 --load .
#
# The ARMv7 base image is pulled on your Docker Desktop (fast WAN) — the final
# image is then saved to .tar.gz and loaded on the Nucleus, so the Nucleus never
# has to pull anything from Docker Hub.

FROM --platform=linux/arm/v7 debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LANG=C.UTF-8

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-opencv \
        python3-numpy \
        python3-yaml \
        python3-flask \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

WORKDIR /app
COPY app/ /app/
COPY config.yaml /app/config.yaml

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python3 -c "import os,sys; sys.exit(0 if os.path.exists('/tmp/alive') else 1)"

CMD ["python3", "-u", "/app/main.py"]

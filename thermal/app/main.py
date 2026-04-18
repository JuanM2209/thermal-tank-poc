"""Thermal tank level detection — main orchestrator."""

import os
import sys
import time
import signal
import logging
import yaml
import cv2

from capture import ThermalCapture
from analyzer import TankAnalyzer
from publisher import HttpPublisher
from stream import MjpegStreamer

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("main")


def load_config(path="/app/config.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def draw_overlay(img, tanks, results, upscale=1):
    if img is None:
        return None
    out = img.copy()
    res_by_id = {r["id"]: r for r in results}
    for t in tanks:
        r = t["roi"]
        res = res_by_id.get(t["id"])
        color = (0, 255, 0)
        if res is None:
            color = (128, 128, 128)
        elif res["confidence"] != "high":
            color = (0, 165, 255)
        cv2.rectangle(out, (r["x"], r["y"]), (r["x"] + r["w"], r["y"] + r["h"]), color, 1)
        if res is not None:
            iy = r["y"] + res["interface_row"]
            cv2.line(out, (r["x"], iy), (r["x"] + r["w"], iy), (0, 0, 255), 1)
            label = f"{t['id']}:{res['level_pct']:.0f}%"
            cv2.putText(out, label, (r["x"], max(8, r["y"] - 2)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1, cv2.LINE_AA)
    if upscale and upscale > 1:
        out = cv2.resize(out, (out.shape[1] * upscale, out.shape[0] * upscale),
                         interpolation=cv2.INTER_NEAREST)
    return out


def main():
    cfg_path = os.environ.get("CONFIG", "/app/config.yaml")
    cfg = load_config(cfg_path)
    log.info(f"Config loaded: {cfg_path}")

    cap = ThermalCapture(**cfg["camera"])
    cap.open()

    analyzer = TankAnalyzer(
        cfg["tanks"],
        smoothing=cfg["analysis"].get("smoothing_window", 7),
        method=cfg["analysis"].get("gradient_method", "sobel"),
        invert_level=cfg["analysis"].get("invert_level", False),
    )

    pub_cfg = cfg.get("publisher", {})
    endpoint = os.environ.get("PUBLISH_ENDPOINT", pub_cfg.get("endpoint"))
    publisher = None
    if endpoint:
        publisher = HttpPublisher(endpoint, timeout=pub_cfg.get("timeout", 3.0))
    else:
        log.warning("No publisher.endpoint configured — running stream-only")

    streamer = None
    if cfg.get("stream", {}).get("enabled", False):
        s = cfg["stream"]
        streamer = MjpegStreamer(port=s.get("port", 8080), fps=s.get("fps", 5),
                                 jpeg_quality=s.get("jpeg_quality", 75))
        streamer.run()

    interval = cfg["analysis"].get("interval_seconds", 2)
    running = {"v": True}

    def _stop(signo, _frame):
        log.info(f"Received signal {signo}, stopping...")
        running["v"] = False

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    last_publish = 0.0
    frame_count = 0
    open("/tmp/alive", "w").close()

    while running["v"]:
        try:
            visual, thermal = cap.read()
            if thermal is None:
                time.sleep(0.05)
                continue
            frame_count += 1

            results = analyzer.analyze(thermal)

            now = time.time()
            if results and (now - last_publish) >= interval:
                if publisher:
                    publisher.publish(results)
                last_publish = now
                summary = " | ".join(
                    f"{r['id']}:{r['level_pct']:.0f}%({r['confidence'][0]})" for r in results
                )
                log.info(f"frame#{frame_count} {summary}")

            if streamer is not None and cfg["stream"].get("draw_overlay", True):
                overlay = draw_overlay(
                    visual, cfg["tanks"], results,
                    upscale=cfg["stream"].get("upscale", 2),
                )
                if overlay is not None:
                    streamer.update(overlay)

            if frame_count % 50 == 0:
                os.utime("/tmp/alive", None)

        except KeyboardInterrupt:
            break
        except Exception as e:
            log.exception(f"Loop error: {e}")
            time.sleep(1)

    log.info("Shutting down...")
    cap.close()
    if publisher:
        publisher.stop()
    sys.exit(0)


if __name__ == "__main__":
    main()

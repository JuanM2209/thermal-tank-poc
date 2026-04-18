"""
Interactive ROI picker — grabs a frame from the camera, lets you draw rectangles
over each tank, and prints the YAML block to paste into config.yaml.

Usage:
  python3 tools/roi_picker.py                  # /dev/video0 default
  python3 tools/roi_picker.py /dev/video0 3    # pick 3 tanks

Controls: drag to draw, ENTER to accept, ESC to redo the current one, q to finish.
"""
import sys
import cv2
import numpy as np

DEV = sys.argv[1] if len(sys.argv) > 1 else "/dev/video0"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 2


def grab():
    cap = cv2.VideoCapture(DEV, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('Y', 'U', 'Y', 'V'))
    cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 256)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 384)
    for _ in range(5):
        cap.read()
    ok, raw = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError("Failed to capture")
    buf = np.asarray(raw, dtype=np.uint8).reshape(384, 256, 2)
    top = buf[:192]
    return cv2.cvtColor(top, cv2.COLOR_YUV2BGR_YUYV)


def main():
    img = grab()
    big = cv2.resize(img, (img.shape[1] * 3, img.shape[0] * 3), interpolation=cv2.INTER_NEAREST)

    tanks = []
    for i in range(N):
        print(f"\nDraw ROI for tank #{i+1}, ENTER to accept, ESC to redo, c to cancel")
        r = cv2.selectROI(f"tank #{i+1}", big, showCrosshair=True, fromCenter=False)
        cv2.destroyWindow(f"tank #{i+1}")
        if r == (0, 0, 0, 0):
            print("cancelled")
            continue
        # Scale back to native 256x192
        x, y, w, h = [int(v / 3) for v in r]
        tanks.append({"id": f"tank_{i+1:02d}", "name": f"Tank {i+1}",
                      "roi": {"x": x, "y": y, "w": w, "h": h}})

    print("\n=== Paste into config.yaml under `tanks:` ===\n")
    for t in tanks:
        r = t["roi"]
        print(f"  - id: {t['id']}")
        print(f"    name: \"{t['name']}\"")
        print(f"    medium: water")
        print(f"    roi: {{ x: {r['x']}, y: {r['y']}, w: {r['w']}, h: {r['h']} }}")
        print(f"    min_temp_delta: 1.2")


if __name__ == "__main__":
    main()

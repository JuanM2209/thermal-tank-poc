"""
Run FIRST after plugging the camera in. Prints everything we need to know
about the UVC stream before configuring the main app.

Usage (host-side, needs python3 + v4l-utils):
  python3 tools/probe.py                # uses /dev/video0
  python3 tools/probe.py /dev/video1
"""
import subprocess
import sys
import shutil

DEV = sys.argv[1] if len(sys.argv) > 1 else "/dev/video0"


def run(cmd):
    print(f"\n$ {' '.join(cmd)}")
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if out.stdout:
            print(out.stdout.rstrip())
        if out.stderr:
            print(out.stderr.rstrip(), file=sys.stderr)
    except FileNotFoundError:
        print(f"[!] {cmd[0]} not found")
    except Exception as e:
        print(f"[!] {e}")


def main():
    print(f"=== Probing {DEV} ===")

    if shutil.which("lsusb"):
        run(["lsusb"])
    if shutil.which("v4l2-ctl"):
        run(["v4l2-ctl", "--list-devices"])
        run(["v4l2-ctl", "-d", DEV, "--all"])
        run(["v4l2-ctl", "-d", DEV, "--list-formats-ext"])
    else:
        print("[!] install v4l-utils: apt-get install v4l-utils")

    # Quick OpenCV sanity check
    try:
        import cv2
        cap = cv2.VideoCapture(DEV, cv2.CAP_V4L2)
        if cap.isOpened():
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            print(f"\nOpenCV defaults: {w}x{h}@{fps}")
            ok, f = cap.read()
            if ok:
                print(f"Frame shape: {f.shape}, dtype: {f.dtype}, "
                      f"min={f.min()} max={f.max()} mean={f.mean():.1f}")
            cap.release()
    except ImportError:
        print("[i] opencv not installed on host — skipping sample frame")

    print("\n=== Next steps ===")
    print("1. If `list-formats-ext` shows 256x384 YUYV @ 25fps -> dual_yuyv decoder OK")
    print("2. If it shows 256x192 only -> decoder: visual_only (thermal raw not exposed)")
    print("3. Any other geometry -> adjust camera.width/height in config.yaml")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Rebuilds assets/social-preview.png (GitHub repo social preview card, 1280x640).

Pulls real cursor frames straight out of the built Windows cursor set via
curlib.read_cur/read_ani, so the cover always shows actual shipped glyphs
(never mockups). Renders the HTML through a headless Chromium/Edge binary.

Usage:
    python tools/gen_social_preview.py

Requires: dist/windows/Chrome Glass Remastered/ already built (see build.py),
and a Chromium-based browser installed (Edge on Windows, Chrome/Chromium on
Linux/macOS) - set EDGE_PATH env var to override the auto-detected binary.
"""
import base64
import io
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import curlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CUR_DIR = os.path.join(ROOT, "dist", "windows", "Chrome Glass Remastered")
OUT_HTML = os.path.join(ROOT, "tools", "_social_preview.html")
OUT_PNG = os.path.join(ROOT, "assets", "social-preview.png")

# (role in layout) -> (source file, frame index or None for a plain .cur)
CURSORS = {
    "main": ("Arrow.cur", None),
    "t1": ("Arrow_Down.cur", None),
    "t2": ("Wait.ani", 13),
    "t3": ("Handwriting.ani", 0),
}


def load_b64(name, frame_idx):
    path = os.path.join(CUR_DIR, name)
    with open(path, "rb") as f:
        data = f.read()
    if name.endswith(".ani"):
        ani = curlib.read_ani(data)
        frames = curlib.read_cur(ani["frames"][frame_idx])
    else:
        frames = curlib.read_cur(data)
    best = max(frames, key=lambda fr: fr["img"].size[0])
    buf = io.BytesIO()
    best["img"].save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def build_html(images):
    return f"""<!doctype html><html><head><meta charset=utf-8><style>
html,body{{margin:0;padding:0;width:1280px;height:640px;overflow:hidden;font-family:-apple-system,Segoe UI,Arial,sans-serif;}}
.cover{{
  width:1280px;height:640px;position:relative;
  background:
    radial-gradient(1100px 600px at 78% 8%, rgba(70,110,180,0.28), transparent 60%),
    radial-gradient(900px 500px at 10% 100%, rgba(30,58,138,0.35), transparent 55%),
    linear-gradient(160deg,#0a1224 0%,#0b1530 45%,#060a16 100%);
}}
.badges{{position:absolute;left:84px;top:474px;display:flex;gap:14px;}}
.badge{{
  padding:8px 22px;border-radius:999px;border:1px solid rgba(148,180,230,0.55);
  color:#dbe6fb;font-size:19px;font-weight:600;letter-spacing:.2px;
  background:rgba(255,255,255,0.03);
}}
.title{{position:absolute;left:82px;top:56px;font-size:70px;font-weight:800;color:#f3f6fc;line-height:1.03;letter-spacing:-1px;}}
.title .sub{{color:#9db8ee;font-weight:600;display:block;}}
.tagline{{position:absolute;left:84px;top:328px;font-size:26px;color:#c7d2e8;font-weight:400;}}
.tile{{
  position:absolute;border-radius:30px;
  background:linear-gradient(160deg,#eef1f7,#dde3ee);
  box-shadow:0 18px 40px rgba(0,0,0,0.35), inset 0 1px 0 rgba(255,255,255,0.7);
  display:flex;align-items:center;justify-content:center;
}}
.tile img{{filter:drop-shadow(0 6px 10px rgba(0,0,0,0.3)) saturate(1.15) contrast(1.05);}}
.tile-main{{left:820px;width:376px;height:340px;top:64px;}}
.tile-main img{{width:250px;}}
.tile-small{{width:110px;height:110px;top:464px;}}
.tile-small img{{width:74px;}}
.t1{{left:820px;}}
.t2{{left:953px;}}
.t3{{left:1086px;}}
</style></head><body>
<div class=cover>
  <div class=title>Chrome Glass<span class=sub>Remastered</span></div>
  <div class=tagline>The 2006 glass cursors, reborn for 4K</div>
  <div class=badges>
    <div class=badge>32-256 px</div>
    <div class=badge>60 fps</div>
    <div class=badge>Windows</div>
    <div class=badge>Linux</div>
    <div class=badge>macOS</div>
  </div>
  <div class="tile tile-main"><img src="data:image/png;base64,{images['main']}"></div>
  <div class="tile tile-small t1"><img src="data:image/png;base64,{images['t1']}"></div>
  <div class="tile tile-small t2"><img src="data:image/png;base64,{images['t2']}"></div>
  <div class="tile tile-small t3"><img src="data:image/png;base64,{images['t3']}"></div>
</div>
</body></html>"""


def find_browser():
    override = os.environ.get("EDGE_PATH")
    if override and os.path.exists(override):
        return override
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    for name in ("msedge", "google-chrome", "chromium-browser", "chromium"):
        found = shutil.which(name)
        if found:
            return found
    return None


def main():
    if not os.path.isdir(CUR_DIR):
        sys.exit(f"Cursor set not built yet: {CUR_DIR!r} - run build.py first.")

    images = {role: load_b64(*src) for role, src in CURSORS.items()}
    html = build_html(images)

    browser = find_browser()
    if not browser:
        with open(OUT_HTML, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Wrote {OUT_HTML}, but no Chromium/Edge binary found to render it.")
        print("Open it in a browser at 1280x640 and screenshot it manually, "
              "or set EDGE_PATH and re-run.")
        return

    # Render from a real local temp dir - headless Chromium/Edge can't load
    # file:// URIs from network/SMB shares or subst/mapped drives, and on
    # this machine TEMP itself points at one, so pick the real profile temp.
    local_temp = os.path.join(
        os.path.expanduser("~"), "AppData", "Local", "Temp"
    )
    if not os.path.isdir(local_temp):
        local_temp = None  # fall back to tempfile default
    # --headless=new returns control before the screenshot file is actually
    # flushed to disk in some Edge builds, so clean the temp dir up only
    # after the PNG has shown up (avoids deleting the HTML out from under
    # a still-rendering renderer process).
    tmp = tempfile.mkdtemp(dir=local_temp)
    try:
        tmp_html = os.path.join(tmp, "social_preview.html")
        with open(tmp_html, "w", encoding="utf-8") as f:
            f.write(html)
        if os.path.exists(OUT_PNG):
            os.remove(OUT_PNG)
        subprocess.run(
            [
                browser,
                "--headless=new",
                "--disable-gpu",
                f"--screenshot={OUT_PNG}",
                "--window-size=1280,640",
                pathlib.Path(tmp_html).as_uri(),
            ],
            check=True,
        )
        for _ in range(50):
            if os.path.exists(OUT_PNG) and os.path.getsize(OUT_PNG) > 0:
                break
            time.sleep(0.1)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"Wrote {OUT_PNG}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Rebuilds assets/social-preview.png, the card GitHub, search engines and
messengers show for a link to the repo (1280x640, uploaded by hand in the
repo's Settings > Social preview).

The cursors are drawn by the pipeline itself, the same calls gen_hero.py
makes: the author's 32 px Arrow blown up pixel for pixel beside the 2.0
Arrow drawn at 384, on the hero's dark wallpaper. Text is laid out as HTML
and rendered through a headless Chromium/Edge binary.

Usage:
    python tools/gen_social_preview.py

Requires a Chromium-based browser (Edge on Windows, Chrome/Chromium on
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

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from cgr import hybrid as H         # noqa: E402
from gen_hero import DARK, wallpaper  # noqa: E402

ROOT = os.path.dirname(HERE)
OUT_HTML = os.path.join(ROOT, "tools", "_social_preview.html")
OUT_PNG = os.path.join(ROOT, "assets", "social-preview.png")

NEW = 384           # the 2.0 Arrow, shown 1:1
OLD = 6             # the 2006 Arrow, each of its pixels as a 6 px block


def b64(im):
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


def images():
    new = H.frame_image("Arrow", 0, NEW)
    new = new.crop(new.getchannel("A").getbbox())
    old = H.original("Arrow", 0).convert("RGBA")
    old = old.crop(old.getchannel("A").getbbox())
    old = old.resize((old.width * OLD, old.height * OLD), Image.NEAREST)
    return {"bg": b64(wallpaper(1280, 640, DARK).convert("RGB")),
            "new": b64(new), "old": b64(old)}


def build_html(img):
    return f"""<!doctype html><html><head><meta charset=utf-8><style>
html,body{{margin:0;padding:0;width:1280px;height:640px;overflow:hidden;font-family:"Segoe UI",-apple-system,Arial,sans-serif;}}
.cover{{width:1280px;height:640px;position:relative;background:url(data:image/png;base64,{img['bg']});}}
/* GitHub's repo page shows this card as a wide banner and crops the top and
   bottom, keeping roughly the middle 65%; everything that matters stays in
   that band. */
.safe{{position:absolute;left:0;top:120px;width:1280px;height:400px;box-sizing:border-box;
  padding:0 80px 0 88px;display:flex;align-items:center;justify-content:space-between;}}
.left{{display:flex;flex-direction:column;gap:20px;}}
.title{{font-size:76px;font-weight:700;color:#f3f6fc;line-height:1.02;letter-spacing:-1px;}}
.title .sub{{color:#9db8ee;font-weight:600;display:block;}}
.tagline{{font-size:27px;color:#c7d2e8;line-height:1.3;}}
.badges{{display:flex;gap:12px;margin-top:6px;}}
.badge{{padding:7px 18px;border-radius:999px;border:1px solid rgba(148,180,230,0.5);
  color:#dbe6fb;font-size:18px;font-weight:600;background:rgba(255,255,255,0.04);white-space:nowrap;}}
.badge.v{{background:rgba(157,184,238,0.18);border-color:rgba(157,184,238,0.8);}}
.pair{{display:flex;align-items:flex-end;gap:34px;}}
.fig{{display:flex;flex-direction:column;align-items:center;gap:12px;}}
.fig img{{display:block;image-rendering:auto;}}
.fig.old img{{image-rendering:pixelated;opacity:.92;}}
.cap{{font-size:20px;font-weight:600;letter-spacing:.3px;}}
.old .cap{{color:#e8a0a0;}}
.new .cap{{color:#a0e2b0;}}
</style></head><body>
<div class=cover>
  <div class=safe>
    <div class=left>
      <div class=title>Chrome Glass<span class=sub>Remastered</span></div>
      <div class=tagline>The 2006 glass cursors, redrawn<br>sharp at every size up to 512 px</div>
      <div class=badges>
        <div class="badge v">2.0</div>
        <div class=badge>Windows</div>
        <div class=badge>Linux</div>
        <div class=badge>macOS</div>
      </div>
    </div>
    <div class=pair>
      <div class="fig old"><img src="data:image/png;base64,{img['old']}"><div class=cap>2006</div></div>
      <div class="fig new"><img src="data:image/png;base64,{img['new']}"><div class=cap>2.0</div></div>
    </div>
  </div>
</div>
</body></html>"""


def find_browser():
    override = os.environ.get("EDGE_PATH")
    if override:
        if not os.path.exists(override):
            sys.exit(f"EDGE_PATH points at {override!r}, which does not exist.")
        return override
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
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
    html = build_html(images())

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
    local_temp = None
    if sys.platform == "win32":
        cand = os.path.join(os.path.expanduser("~"), "AppData", "Local", "Temp")
        if os.path.isdir(cand):
            local_temp = cand
    # --headless=new returns control before the screenshot file is actually
    # flushed to disk in some Edge builds, so clean the temp dir up only
    # after the PNG has shown up (avoids deleting the HTML out from under
    # a still-rendering renderer process).
    tmp = tempfile.mkdtemp(dir=local_temp)
    try:
        tmp_html = os.path.join(tmp, "social_preview.html")
        with open(tmp_html, "w", encoding="utf-8") as f:
            f.write(html)
        # Render beside the target and move it into place only once it is
        # there. Screenshotting straight onto OUT_PNG meant a browser that
        # failed, hung or wrote nothing left the committed cover deleted -
        # and the old code still printed "Wrote ..." and exited 0.
        staged = os.path.join(tmp, "social_preview.png")
        subprocess.run(
            [
                browser,
                "--headless=new",
                "--disable-gpu",
                f"--screenshot={staged}",
                "--window-size=1280,640",
                pathlib.Path(tmp_html).as_uri(),
            ],
            check=True,
            timeout=120,
        )
        for _ in range(50):
            if os.path.exists(staged) and os.path.getsize(staged) > 0:
                break
            time.sleep(0.1)
        else:
            sys.exit(f"{browser} exited cleanly but produced no screenshot "
                     f"after 5s - {OUT_PNG} left untouched.")
        # The temp dir is deliberately on a local drive while the repo may sit
        # on a mapped/network one, so cross-device: copy next to the target
        # first, then swap within the same filesystem to keep it atomic.
        near = OUT_PNG + ".new"
        shutil.copyfile(staged, near)
        os.replace(near, OUT_PNG)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"Wrote {OUT_PNG}")


if __name__ == "__main__":
    main()

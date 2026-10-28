#!/usr/bin/env python3
"""Side-by-side acceptance sheet: author / release 1.1.0 / HEAD / candidate.

visual_audit.py shows one renderer at every rung; this one puts the sources in
columns so a defect is read against the release and the author in the same
glance (GLASS_PLAN.md stage 0). Per cursor and background, one PNG:

  row 0       the whole cursor at --whole px, one column per source
  rows 1..    crops of the apex, both wing tips and the notch at each --sizes
              rung, CROP_UNITS logical units across, blown up NEAREST

Sources:
  author      art/orig 32 px, NEAREST up to the rung - what was drawn
  1.1.0       the v1.1.0 renderer, extracted with `git archive` under --cache
              and run in a subprocess; frames cached as PNG, rendered once
  HEAD        cgr.hybrid.frame_image
  glass       cgr.glass.frame_image, only if that module exists

Usage:
    python tools/look.py Arrow
    python tools/look.py Arrow Help --bgs grey dark --sizes 128 512
"""
import argparse
import os
import subprocess
import sys
import tarfile
import io

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import visual_audit as VA  # noqa: E402
from cgr import hybrid as H  # noqa: E402
from cgr import vectorlib as V  # noqa: E402

RELEASE = "v1.1.0"
CACHE = os.path.join(HERE, "tmp", "look")
CROP_UNITS = 7.0
CROP_PX = 256             # on-screen side of every crop tile
PARTS = ("apex", "wing_low", "notch", "wing_right")   # order of H._landmarks
# visual_audit's grounds, restated: only _frame and _extremes are borrowed
BGS = {"light": (245, 245, 245), "grey": (128, 128, 128), "dark": (32, 33, 36)}
FG = {"light": (30, 30, 30), "grey": (16, 16, 16), "dark": (216, 218, 224)}
LABEL_W = 86


def _on(img, bg):
    out = Image.new("RGB", img.size, bg)
    out.paste(img, (0, 0), img)
    return out


def _release_src(cache):
    src = os.path.join(cache, RELEASE + "-src")
    if not os.path.exists(os.path.join(src, "hybrid.py")):
        os.makedirs(src, exist_ok=True)
        blob = subprocess.run(["git", "-c", "safe.directory=*", "archive", RELEASE],
                              cwd=HERE, check=True, capture_output=True).stdout
        with tarfile.open(fileobj=io.BytesIO(blob)) as t:
            t.extractall(src, filter="data")
    return src


def _release(cache, name, idx, size):
    """The v1.1.0 frame. Run in its own tree and process: its hybrid.py is a
    different module with the same name, and importing both into one
    interpreter would let one read the other's lru caches."""
    out = os.path.join(cache, RELEASE, "%s_%d_%d.png" % (name, idx, size))
    if not os.path.exists(out):
        os.makedirs(os.path.dirname(out), exist_ok=True)
        code = ("import sys, hybrid as H; "
                "H.frame_image(sys.argv[1], int(sys.argv[2]), int(sys.argv[3])).save(sys.argv[4])")
        subprocess.run([sys.executable, "-c", code, name, str(idx), str(size), out],
                       cwd=_release_src(cache), check=True)
    return Image.open(out).convert("RGBA")


def _author(name, idx, size):
    return H.original(name, idx).convert("RGBA").resize((size, size), Image.NEAREST)


def _sources(cache):
    srcs = [("author 32", _author),
            ("1.1.0", lambda n, i, s: _release(cache, n, i, s)),
            ("HEAD", VA._frame)]
    try:
        from cgr import glass
    except ImportError:
        return srcs
    return srcs + [("glass", glass.frame_image)]


def _points(name, idx):
    lm = H._landmarks(name, idx)
    if lm is None:
        return {k: tuple(v) for k, v in VA._extremes(name, idx).items()}
    return dict(zip(PARTS, lm))


def _crop(img, pt, size):
    s = size / float(V.LOGICAL)
    half = CROP_UNITS * s / 2.0
    box = tuple(int(round(v)) for v in (pt[0] * s - half, pt[1] * s - half,
                                         pt[0] * s + half, pt[1] * s + half))
    return img.crop(box).resize((CROP_PX, CROP_PX), Image.NEAREST)


def sheet(name, idx, bgn, srcs, whole, sizes, frames, font):
    pts = _points(name, idx)
    pad, lab = 8, 16
    cols = len(srcs)
    # the overview is the one resampled tile: it is for orientation, the
    # crops below are where defects are read
    rows = [("whole %d" % whole, [_on(frames[(k, whole)], BGS[bgn])
                                  .resize((CROP_PX, CROP_PX), Image.LANCZOS)
                                  for k, _f in srcs])]
    for size in sizes:
        for part, pt in pts.items():
            rows.append(("%s %d" % (part, size),
                         # cut before compositing: past the canvas edge is
                         # then transparent, not a black bar
                         [_on(_crop(frames[(k, size)], pt, size), BGS[bgn])
                          for k, _f in srcs]))
    W = LABEL_W + pad + cols * (CROP_PX + pad)
    Hh = lab + pad + len(rows) * (CROP_PX + pad)
    out = Image.new("RGB", (W, Hh), BGS[bgn])
    d = ImageDraw.Draw(out)
    for c, (k, _f) in enumerate(srcs):
        d.text((LABEL_W + pad + c * (CROP_PX + pad), 2), k, fill=FG[bgn], font=font)
    for r, (label, tiles) in enumerate(rows):
        y = lab + pad + r * (CROP_PX + pad)
        d.text((2, y), label, fill=FG[bgn], font=font)
        for c, t in enumerate(tiles):
            out.paste(t, (LABEL_W + pad + c * (CROP_PX + pad), y))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("names", nargs="+")
    ap.add_argument("--idx", type=int, default=0)
    ap.add_argument("--bgs", nargs="+", default=["grey", "light", "dark"],
                    choices=sorted(BGS))
    ap.add_argument("--sizes", nargs="+", type=int, default=[64, 128, 256, 512])
    ap.add_argument("--whole", type=int, default=512)
    ap.add_argument("--cache", default=CACHE)
    ap.add_argument("--out", default=os.path.join(CACHE, "sheets"))
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    font = ImageFont.load_default()
    srcs = _sources(args.cache)
    for name in args.names:
        frames = {(k, s): f(name, args.idx, s)
                  for k, f in srcs for s in sorted(set(args.sizes) | {args.whole})}
        for bgn in args.bgs:
            p = os.path.join(args.out, "%s_%d_%s.png" % (name, args.idx, bgn))
            sheet(name, args.idx, bgn, srcs, args.whole, args.sizes, frames, font).save(p)
            print(p)


if __name__ == "__main__":
    main()

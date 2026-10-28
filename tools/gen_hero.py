#!/usr/bin/env python3
"""Rebuilds assets/hero.png, the picture at the top of both READMEs.

Top: the author's 32 px Arrow blown up pixel for pixel beside the remaster
drawn at 512, on a dark wallpaper. Bottom: a row of cursors at 96 px on a
light and on a dark wallpaper, as they sit on a desktop. Drawn at twice the
README column (~880 px) so it stays sharp on HiDPI screens.

The wallpapers are generated (soft colour fields), not photos, and the only
text is numbers: both READMEs embed the same file.

Usage:
    python tools/gen_hero.py
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from cgr import build as B          # noqa: E402
from cgr import hybrid as H         # noqa: E402
from cgr.paths import ASSETS        # noqa: E402

W = 1760
BIG = 512
ROW = 96
ROW_NAMES = [("Arrow", 0), ("Help", 0), ("Pin", 0), ("UpArrow", 0),
             ("NO", B._PREVIEW_STILL["NO"]), ("Wait", 2), ("AppStarting", 2)]

# soft colour fields: (x, y) in share of the panel, radius share of its width, colour
DARK = ((14, 20, 36), [(0.15, 0.2, 0.55, (38, 58, 112)), (0.85, 0.85, 0.6, (70, 34, 92)),
                       (0.6, 0.1, 0.4, (20, 78, 96)), (0.35, 1.0, 0.45, (26, 40, 80))])
LIGHT = ((226, 232, 240), [(0.1, 0.9, 0.6, (250, 236, 220)), (0.9, 0.1, 0.6, (200, 220, 244)),
                           (0.55, 0.55, 0.35, (244, 246, 250))])


def wallpaper(w, h, spec):
    base, blobs = spec
    y, x = np.mgrid[0:h, 0:w].astype(np.float64)
    lin = lambda c: (np.asarray(c, np.float64) / 255.0) ** 2.2
    col = np.broadcast_to(lin(base), (h, w, 3)).copy()
    for bx, by, r, c in blobs:
        g = np.exp(-(((x - bx * w) ** 2 + (y - by * h) ** 2) / (r * w) ** 2))[..., None]
        col = col + (lin(c) - col) * g
    # no dither: the fields are wide enough that steps stay 1 level, and
    # noise made the PNG four times larger
    out = col ** (1 / 2.2) * 255
    return Image.fromarray(np.clip(np.round(out), 0, 255).astype(np.uint8), "RGB").convert("RGBA")


def cursor(name, idx, size):
    if name in B.ANIM:
        return H.frame_image(name, idx, size)
    return B.static_image(name, size)


def centred(im, w, h):
    """Where to put im so its drawn part sits in the middle of a w x h box."""
    x0, y0, x1, y1 = im.getchannel("A").getbbox()
    return (w - (x0 + x1)) // 2, (h - (y0 + y1)) // 2


def main():
    pad, lab = 64, 56
    top_h = pad + BIG + lab + 16
    row_h = ROW + 2 * 56
    sheet = Image.new("RGBA", (W, top_h + row_h))
    f = B._font(30)

    top = wallpaper(W, top_h, DARK)
    d = ImageDraw.Draw(top)
    gap = (W - 2 * BIG) // 3
    old = H.original("Arrow", 0).convert("RGBA").resize((BIG, BIG), Image.NEAREST)
    new = H.frame_image("Arrow", 0, BIG)
    # both shifted alike, by the remaster's drawn part: the pair stays one to one
    dx, dy = centred(new, BIG, BIG)
    for i, (im, text, ink) in enumerate(((old, "2006 - 32 px", (232, 160, 160)),
                                         (new, "2.0 - 512 px", (160, 226, 176)))):
        x = gap + i * (BIG + gap)
        top.alpha_composite(im, (x + dx, pad + dy))
        d.text((x + BIG // 2, pad + BIG + 12), text, fill=ink, font=f, anchor="mt")
    sheet.alpha_composite(top, (0, 0))

    half = W // 2
    step = (half - len(ROW_NAMES) * ROW) // (len(ROW_NAMES) + 1)
    for k, spec in enumerate((LIGHT, DARK)):
        panel = wallpaper(half, row_h, spec)
        for i, (name, idx) in enumerate(ROW_NAMES):
            im = cursor(name, idx, ROW)
            dx, dy = centred(im, ROW, row_h)
            panel.alpha_composite(im, (step + i * (ROW + step) + dx, dy))
        sheet.alpha_composite(panel, (k * half, top_h))

    os.makedirs(ASSETS, exist_ok=True)
    out = os.path.join(ASSETS, "hero.png")
    sheet.convert("RGB").save(out, optimize=True)
    print(out, sheet.size)


if __name__ == "__main__":
    main()

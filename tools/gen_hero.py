#!/usr/bin/env python3
"""Rebuilds assets/hero.png, the picture at the top of both READMEs.

Top: one big Arrow cut in two by a thin chrome seam - the author's 32 px
pixels on the left, the remaster drawn at full size on the right, with small
Apple, Windows and Linux marks under the Arrow to show it is see-through. Bottom: the coloured
cursors in a row, each over a glow of its own colour, Linux's blue arrow
among them. One dark wallpaper under everything, no text, so both READMEs
embed the same file. Drawn at twice the README column (~880 px) so it stays
sharp on HiDPI screens.

Usage:
    python tools/gen_hero.py
"""
import os
import sys

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from cgr import build as B          # noqa: E402
from cgr import hybrid as H         # noqa: E402
from cgr.paths import ASSETS        # noqa: E402

W, HT = 1760, 900
BIG = 640
ROW = 200
# one of each colour, the blue in the middle; NO left out (its arrow hides
# behind the sign), UpArrow too (a paler double of AppStarting's gold)
ROW_NAMES = [("Wait", 2, (255, 100, 40)), ("Arrow_Down", 0, (70, 150, 255)),
             ("AppStarting", 2, (255, 190, 50))]
# where the seam crosses the arrow's box, share of its width at top and bottom
SEAM = (0.62, 0.38)
# the OS marks seen through the Arrow: the largest size tried, px
LOGO = 120

# soft colour fields: (x, y) in share of the panel, radius share of its width, colour
NIGHT = ((10, 12, 26), [(0.2, 0.3, 0.5, (30, 44, 100)), (0.85, 0.75, 0.55, (64, 26, 84)),
                        (0.55, 0.05, 0.35, (16, 70, 92))])


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


def glow(canvas, cx, cy, r, col, a):
    g = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(g).ellipse((cx - r, cy - r, cx + r, cy + r), fill=col + (a,))
    canvas.alpha_composite(g.filter(ImageFilter.GaussianBlur(r * 0.6)))


def put(canvas, im, x, y):
    """im with a soft drop shadow under it, as if a little above the wall."""
    blur = max(6, im.width // 28)
    pad = 3 * blur
    sh = Image.new("RGBA", (im.width + 2 * pad, im.height + 2 * pad), (0, 0, 0, 0))
    a = Image.new("RGBA", im.size, (0, 0, 0, 0))
    a.putalpha(im.getchannel("A").point(lambda v: int(v * 0.55)))
    sh.alpha_composite(a, (pad, pad))
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    canvas.paste(sh, (x + im.width // 40 - pad, y + im.width // 22 - pad), sh)
    canvas.alpha_composite(im, (x, y))


def split_arrow():
    """The 2006 pixels fitted onto the remaster's drawn box, cut along SEAM."""
    new = cursor("Arrow", 0, BIG)
    old32 = H.original("Arrow", 0).convert("RGBA")
    ob, nb = old32.getchannel("A").getbbox(), new.getchannel("A").getbbox()
    old = Image.new("RGBA", (BIG, BIG), (0, 0, 0, 0))
    old.alpha_composite(old32.crop(ob).resize((nb[2] - nb[0], nb[3] - nb[1]), Image.NEAREST),
                        (nb[0], nb[1]))
    # the cut antialiased: coverage from the pixel's distance to the seam
    d, _ = seam_field(BIG, BIG, (BIG * SEAM[0], 0.0), (BIG * SEAM[1], float(BIG)))
    mask = Image.fromarray(np.clip(np.round((0.5 + d) * 255), 0, 255).astype(np.uint8), "L")
    return Image.composite(old, new, mask)


def seam_field(w, h, p, q):
    """Signed distance of every pixel centre to the line p-q (positive on the
    left of it, the 2006 side) and where along p-q it falls, 0 at p, 1 at q."""
    y, x = np.mgrid[0:h, 0:w].astype(np.float64) + 0.5
    dx, dy = q[0] - p[0], q[1] - p[1]
    n = np.hypot(dx, dy)
    d = ((x - p[0]) * dy - (y - p[1]) * dx) / n
    t = ((x - p[0]) * dx + (y - p[1]) * dy) / n ** 2
    return -d, t


def chrome_seam(w, h, p, q):
    """A thin chrome seam: a crisp white hairline with a faint silver halo
    and a soft shade on the glass side, fading in and out at the ends."""
    d, t = seam_field(w, h, p, q)
    a = np.abs(d)
    ends = np.clip(np.minimum(t, 1 - t) / 0.15, 0, 1)
    ends = ends * ends * (3 - 2 * ends)
    core = np.clip(1.3 - a, 0, 1)
    halo = 0.22 * np.exp(-(a / 3.0) ** 2)
    shade = 0.30 * np.exp(-((d + 3.0) / 3.0) ** 2) * (1 - core)
    alpha = np.clip(core + halo * (1 - core) + shade, 0, 1) * ends
    lum = (core * 255 + halo * 215) / np.maximum(core + halo + shade, 1e-6)
    out = np.dstack([lum, lum, np.minimum(lum * 1.02, 255), alpha * 255])
    return Image.fromarray(np.clip(np.round(out), 0, 255).astype(np.uint8), "RGBA")


# OS marks drawn from plain shapes at 4x and scaled down
SS = 4

def _canvas(s): return Image.new("L", (s * SS, s * SS), 0)
def _ell(d, s, cx, cy, rx, ry, fill=255):
    d.ellipse(((cx - rx) * s * SS, (cy - ry) * s * SS, (cx + rx) * s * SS, (cy + ry) * s * SS), fill=fill)
def _down(m, s): return m.resize((s, s), Image.LANCZOS)
def _smooth(m, k=0.04):
    """Rounds the joins between the shapes: blur, then cut at half, still at 4x."""
    r = max(1, int(m.size[0] * k))
    return m.filter(ImageFilter.GaussianBlur(r)).point(lambda v: 255 if v >= 128 else 0)
def _paint(mask, top, bottom):
    s = mask.size[0]
    t = np.linspace(0, 1, s)[:, None, None]
    rgb = np.array(top, float) * (1 - t) + np.array(bottom, float) * t
    rgb = np.broadcast_to(rgb, (s, s, 3))
    return Image.fromarray(np.dstack([rgb, np.asarray(mask, float)]).astype(np.uint8), "RGBA")

def windows(s, top=(90, 200, 255), bottom=(0, 110, 210)):
    m = _canvas(s); d = ImageDraw.Draw(m); g = 0.04; h = 0.5 - g / 2
    for x in (0, 0.5 + g / 2):
        for y in (0, 0.5 + g / 2):
            d.rectangle((x * s * SS, y * s * SS, (x + h) * s * SS, (y + h) * s * SS), fill=255)
    return _paint(_down(m, s), top, bottom)

def apple(s, top=(250, 252, 255), bottom=(170, 178, 192)):
    m = _canvas(s); d = ImageDraw.Draw(m)
    _ell(d, s, 0.34, 0.56, 0.27, 0.30); _ell(d, s, 0.66, 0.56, 0.27, 0.30)
    _ell(d, s, 0.5, 0.66, 0.31, 0.30)
    _ell(d, s, 0.38, 0.86, 0.15, 0.12); _ell(d, s, 0.62, 0.86, 0.15, 0.12)
    _ell(d, s, 0.5, 0.29, 0.07, 0.06, 0)          # notch at the stem
    _ell(d, s, 0.5, 0.995, 0.06, 0.05, 0)         # notch at the base
    _ell(d, s, 0.97, 0.50, 0.14, 0.15, 0)         # the bite
    leaf = _canvas(s); ld = ImageDraw.Draw(leaf)
    _ell(ld, s, 0.5, 0.5, 0.075, 0.15)
    leaf = leaf.rotate(-40, resample=Image.BICUBIC, center=(0.5 * s * SS, 0.5 * s * SS))
    leaf = ImageChops.offset(leaf, int(0.08 * s * SS), int(-0.36 * s * SS))
    m = ImageChops.lighter(_smooth(m), _smooth(leaf, 0.02))
    return _paint(_down(m, s), top, bottom)

def tux(s):
    def layer(fn):
        m = _canvas(s); fn(ImageDraw.Draw(m)); return _down(m, s)
    sil = lambda d: (_ell(d, s, 0.5, 0.6, 0.31, 0.37), _ell(d, s, 0.5, 0.26, 0.2, 0.22),
                     _ell(d, s, 0.2, 0.62, 0.09, 0.22), _ell(d, s, 0.8, 0.62, 0.09, 0.22))
    m = _canvas(s); sil(ImageDraw.Draw(m)); body = _down(_smooth(m), s)
    belly = layer(lambda d: _ell(d, s, 0.5, 0.66, 0.22, 0.28))
    face = layer(lambda d: (_ell(d, s, 0.43, 0.25, 0.075, 0.1), _ell(d, s, 0.57, 0.25, 0.075, 0.1)))
    pupil = layer(lambda d: (_ell(d, s, 0.445, 0.26, 0.03, 0.045), _ell(d, s, 0.555, 0.26, 0.03, 0.045)))
    beak = layer(lambda d: _ell(d, s, 0.5, 0.35, 0.11, 0.055))
    feet = layer(lambda d: (_ell(d, s, 0.33, 0.95, 0.15, 0.055), _ell(d, s, 0.67, 0.95, 0.15, 0.055)))
    out = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    def fill(mask, col):
        im = Image.new("RGBA", (s, s), col + (0,)); im.putalpha(mask); out.alpha_composite(im)
    # a light rim so the black body stays readable on a dark wall
    rim = body.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(2))
    fill(rim, (150, 170, 210))
    fill(body, (22, 24, 30)); fill(belly, (240, 242, 246)); fill(face, (250, 250, 252))
    fill(pupil, (20, 20, 24)); fill(feet, (250, 190, 40)); fill(beak, (250, 190, 40))
    return out


def logo_spots(arrow_new):
    """The biggest mark size, up to LOGO, and three centres in a row for it,
    each mark wholly inside the Arrow (either half) with a margin, on the
    widest line the silhouette has."""
    inside = Image.fromarray(((np.asarray(arrow_new.getchannel("A")) > 20) * 255).astype(np.uint8))
    for size in range(LOGO, 23, -4):
        gap, k = size // 4, size // 2 + 8
        inner = np.asarray(inside.filter(ImageFilter.MinFilter(2 * k + 1))) > 0
        r = int(np.argmax(inner.sum(1)))
        xs = np.nonzero(inner[r])[0]
        if xs.size and xs.max() - xs.min() >= 2 * (size + gap):
            mid = (xs.min() + xs.max()) / 2
            return size, [(mid + (i - 1) * (size + gap), r) for i in range(3)]
    raise SystemExit("the Arrow is too small for three marks")


def main():
    sheet = wallpaper(W, HT, NIGHT)

    arrow = split_arrow()
    ax0, ay0, ax1, ay1 = arrow.getchannel("A").getbbox()
    # the drawn part centred across, 50 px from the top
    x0, y0 = (W - (ax0 + ax1)) // 2, 50 - ay0
    glow(sheet, x0 + (ax0 + ax1) // 2, y0 + (ay0 + ay1) // 2, 330, (90, 140, 255), 60)
    row_y = y0 + ay1 + 50
    step = 420
    left = (W - step * (len(ROW_NAMES) - 1)) // 2
    for i, (_, _, col) in enumerate(ROW_NAMES):
        glow(sheet, left + step * i, row_y + ROW // 2, 90, col, 70)

    size, spots = logo_spots(cursor("Arrow", 0, BIG))
    for im, (cx, cy) in zip((apple(size), windows(size), tux(size)), spots):
        im.putalpha(im.getchannel("A").point(lambda v: int(v * 0.9)))
        sheet.alpha_composite(im, (int(x0 + cx - size / 2), int(y0 + cy - size / 2)))
    put(sheet, arrow, x0, y0)
    # the seam runs a little past the drawn part at both ends
    sx = lambda y: x0 + BIG * (SEAM[0] + (SEAM[1] - SEAM[0]) * y / BIG)
    ya, yb = ay0 - 60, ay1 + 30
    sheet.alpha_composite(chrome_seam(W, HT, (sx(ya), y0 + ya), (sx(yb), y0 + yb)))

    for i, (name, idx, _) in enumerate(ROW_NAMES):
        im = cursor(name, idx, ROW)
        bx0, by0, bx1, by1 = im.getchannel("A").getbbox()
        put(sheet, im, left + step * i - (bx0 + bx1) // 2, row_y + ROW // 2 - (by0 + by1) // 2)

    os.makedirs(ASSETS, exist_ok=True)
    out = os.path.join(ASSETS, "hero.png")
    sheet.convert("RGB").save(out, optimize=True)
    print(out, sheet.size)


if __name__ == "__main__":
    main()

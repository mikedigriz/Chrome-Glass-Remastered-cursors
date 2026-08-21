#!/usr/bin/env python3
"""Visual baseline: every cursor, every rung, on three backgrounds.

Exists because the numbers keep being right about the wrong thing. The rule in
this repo is render first, look, and only then read metrics - this is the tool
that makes looking cheap enough to do before every experiment.

Four kinds of sheet, written under --out (default `audit/`):

  ladder/<size>_<bg>.png   every cursor at one rung, drawn at NATIVE pixel size
  anim/<name>_<bg>.png     every author frame of an animated cursor, rows 32/48/128
  crops/<name>_<part>_<size>_<bg>.png
                           the point, the notch and the middle of the fold,
                           cut in logical units and blown up with NEAREST
  README.txt               what was rendered, with the sizes and the git head

Nothing here resamples a cursor. A tile is the render at that rung, pixel for
pixel: pallor at 32 px is a stage acting in hardware pixels, and any resize in
the viewer would hide exactly the defect the sheet is for. The crops are the one
exception and they use NEAREST, so a blown-up pixel stays a square.

Usage:
    python tools/visual_audit.py --out audit/base
    python tools/visual_audit.py --out audit/x --names Handwriting --anim-only
"""
import argparse
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import build as B
import hybrid as H
import vectorlib as V

# Light is the one the grey family is accused on, dark is what the READMEs use,
# and mid grey is where a too-dark outline and a too-pale fill both show.
BGS = {"light": (245, 245, 245), "grey": (128, 128, 128), "dark": (32, 33, 36)}
FG = {"light": (30, 30, 30), "grey": (16, 16, 16), "dark": (216, 218, 224)}
SIZES = [32, 48, 64, 128, 256, 512]
ANIM_ROWS = [32, 48, 128]
CROP_UNITS = 6.0          # logical units across a crop box
CROP_ZOOM = 8             # NEAREST magnification, at 128 px; scaled per rung
PARTS = ("tip", "notch", "fold")
_LABEL_W = 86            # widest cursor name at font 13, plus air


def _all_names():
    return list(B.STATIC) + list(B.ANIM)


def _nframes(name):
    m = H.BY_NAME.get(name)
    return len(m["frames"]) if m else 1


def _frame(name, idx, size):
    if B.is_glyph(name):
        return B.static_image(name, size)
    return H.frame_image(name, idx, size)


def _on(img, bg):
    out = Image.new("RGB", img.size, bg)
    out.paste(img, (0, 0), img)
    return out


def _sheet(tiles, cols, bgn, font, label_h=18, pad=12):
    """tiles: [(RGBA image, label)], laid out on a flat background."""
    # A 32 px tile is narrower than the word under it, so the column pitch is
    # the wider of the two - otherwise the names of the grey family overprint
    # each other on exactly the sheet they are read on.
    cell = max([t.size[0] for t, _ in tiles] + [_LABEL_W])
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (pad + cols * (cell + pad),
                              pad + rows * (cell + label_h + pad)), BGS[bgn])
    d = ImageDraw.Draw(sheet)
    for i, (img, lab) in enumerate(tiles):
        r, c = divmod(i, cols)
        x0, y0 = pad + c * (cell + pad), pad + r * (cell + label_h + pad)
        sheet.paste(img, (x0 + (cell - img.size[0]) // 2,
                          y0 + (cell - img.size[1]) // 2), img)
        d.text((x0, y0 + cell + 2), lab, fill=FG[bgn], font=font)
    return sheet


def ladders(out, names, sizes, bgs, font):
    d = os.path.join(out, "ladder")
    os.makedirs(d, exist_ok=True)
    for size in sizes:
        # Rendered once per rung and reused for all three backgrounds: a native
        # 512 px render costs seconds, and frame_image's cache is per process.
        tiles = [(_frame(n, 0, size), n) for n in names]
        cols = 6 if size <= 128 else 4
        for bgn in bgs:
            _sheet(list(tiles), cols, bgn, font).save(
                os.path.join(d, "%d_%s.png" % (size, bgn)))
        print("  ladder %3d px  %d cursors" % (size, len(names)))


def anims(out, names, bgs, font):
    d = os.path.join(out, "anim")
    os.makedirs(d, exist_ok=True)
    for name in [n for n in names if n in B.ANIM]:
        n = _nframes(name)
        rows = [[_frame(name, i, size) for i in range(n)] for size in ANIM_ROWS]
        pad, lab, cell = 10, 16, max(ANIM_ROWS)
        W = pad + n * (cell + pad)
        Hh = pad + sum(s + lab + pad for s in ANIM_ROWS)
        for bgn in bgs:
            sheet = Image.new("RGB", (W, Hh), BGS[bgn])
            dr = ImageDraw.Draw(sheet)
            y = pad
            for size, frames in zip(ANIM_ROWS, rows):
                for i, im in enumerate(frames):
                    sheet.paste(im, (pad + i * (cell + pad) + (cell - size) // 2,
                                     y), im)
                    dr.text((pad + i * (cell + pad), y + size + 1), str(i),
                            fill=FG[bgn], font=font)
                dr.text((1, y), str(size), fill=FG[bgn], font=font)
                y += size + lab + pad
            sheet.save(os.path.join(d, "%s_%s.png" % (name, bgn)))
        print("  anim   %-12s %d frames" % (name, n))


def _points(name, idx):
    """{part: (x, y) in logical units} from the outline the tracer already has."""
    if B.is_glyph(name):
        return _extremes(name, idx)     # drawn by glyphs.py, no traced chord
    lm = H._landmarks(name, idx)
    if lm is None:
        return _extremes(name, idx)
    a, _b, j, _c = (np.asarray(p, dtype=float) for p in lm)
    return {"tip": a, "notch": j, "fold": (a + j) / 2.0}


def _extremes(name, idx):
    """Fallback for the cursors with no fold chord - the grey family, Pin,
    Person. Their complaint is the outer half unit of each arm, so the probe
    points are the four ends of the silhouette itself, read off the alpha at
    256 and returned in logical units. `_landmarks` cannot serve these: it is
    built on an arrow's four convex points and one interior edge, and a cross
    has neither."""
    size = 256
    a = np.asarray(_frame(name, idx, size))[..., 3] > 96
    if not a.any():
        return {}
    ys, xs = np.nonzero(a)
    s = size / float(V.LOGICAL)
    cx, cy = xs.mean(), ys.mean()
    out = {}
    for part, sel in (("top", ys.argmin()), ("bottom", ys.argmax()),
                      ("left", xs.argmin()), ("right", xs.argmax())):
        out[part] = np.array([xs[sel] / s, ys[sel] / s])
    out["centre"] = np.array([cx / s, cy / s])
    return out


def crops(out, names, bgs, sizes, font):
    d = os.path.join(out, "crops")
    os.makedirs(d, exist_ok=True)
    for name in names:
        pts = _points(name, 0)
        if not pts:
            print("  crops  %-12s no landmarks, skipped" % name)
            continue
        for size in sizes:
            s = size / float(V.LOGICAL)
            half = CROP_UNITS * s / 2.0
            img = _frame(name, 0, size)
            z = max(1, CROP_ZOOM * 128 // size)     # same on-screen size per rung
            for part, p in pts.items():
                cx, cy = p[0] * s, p[1] * s
                cut = img.crop((int(round(cx - half)), int(round(cy - half)),
                                int(round(cx + half)), int(round(cy + half))))
                cut = cut.resize((cut.size[0] * z, cut.size[1] * z), Image.NEAREST)
                for bgn in bgs:
                    _on(cut, BGS[bgn]).save(os.path.join(
                        d, "%s_%s_%d_%s.png" % (name, part, size, bgn)))
        print("  crops  %-12s %s" % (name, ", ".join(sorted(pts))))


def _band(alpha, px=1):
    """Outer shell of a silhouette: the pixels within `px` of its edge."""
    m = alpha > 32
    inner = m.copy()
    for _ in range(px):
        t = inner.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                t &= np.roll(np.roll(inner, dy, 0), dx, 1)
        inner = t
    return m & ~inner, inner


def _perimeter(m):
    """Boundary length in pixel edges: every side of a filled pixel whose
    neighbour is empty counts once. Not the count of boundary pixels - a pixel
    at a corner has two sides exposed and pressing the outline in moves both."""
    e = 0
    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        e += int((m & ~np.roll(np.roll(m, dy, 0), dx, 1)).sum())
    return float(e)


def coverage(names, sizes):
    """How much of the author's own alpha each cursor carries, and where.

    Three readings, because the obvious one is the misleading one:

    `mass` is the total alpha at a rung, divided by the author's own total
    scaled to that rung. It is scale-invariant by construction, so a number
    that holds along the ladder is a property of the shape and a number that
    drifts is a property of the resampling. Ours hold to the third decimal from
    32 to 256, which is what rules the resize out.

    `band` is the same ratio taken only in the outermost half logical unit,
    against the author's Lanczos at that rung. It reads much worse than mass on
    thin cursors - a crisp edge against a smeared reference always will - so it
    says where the difference sits, not how big it is.

    `press` converts the mass deficit into the width it would take to explain
    it, spread over the silhouette's own perimeter. That is the number to
    compare against the 0.14-0.24 logical units the traced contour is known to
    sit inside its source by (NEXT.md 28.1)."""
    print("mass: total alpha against the author's, normalised per rung")
    head = "%-10s" % "cursor" + "".join("%8d" % s for s in sizes) + "%9s%8s" % ("band48", "press")
    print(head)
    for name in names:
        a0 = np.asarray(H.original(name, 0).convert("RGBA"), dtype=float)[..., 3]             if not B.is_glyph(name) else None
        if a0 is None:
            print("%-10s (drawn by glyphs.py, no author frame)" % name)
            continue
        row = []
        for size in sizes:
            ours = np.asarray(_frame(name, 0, size), dtype=float)[..., 3].sum()
            row.append(ours / (a0.sum() * (size / 32.0) ** 2))
        auth48 = H._resize(H._orig(H._key(name, 0)), 48)[1]
        b, _inner = _band(auth48)
        ours48 = np.asarray(_frame(name, 0, 48), dtype=float)[..., 3]
        band = ours48[b].mean() / max(auth48[b].mean(), 1e-6)
        m = a0 > 128
        press = (1 - row[-1]) * m.sum() / max(_perimeter(m), 1.0)
        print("%-10s" % name + "".join("%8.3f" % v for v in row)
              + "%9.3f%8.3f" % (band, press))


def _head():
    try:
        r = subprocess.run(["git", "-c", "safe.directory=*", "rev-parse",
                            "--short", "HEAD"], cwd=HERE, capture_output=True,
                           text=True, timeout=30)
        return r.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=os.path.join(HERE, "audit"), metavar="DIR")
    ap.add_argument("--names", nargs="+", metavar="NAME", help="default: all 17")
    ap.add_argument("--sizes", nargs="+", type=int, default=SIZES)
    ap.add_argument("--bgs", nargs="+", default=list(BGS), choices=list(BGS))
    ap.add_argument("--crop-sizes", nargs="+", type=int, default=[256, 512],
                    help="rungs the landmark crops are cut from")
    ap.add_argument("--ladder-only", action="store_true")
    ap.add_argument("--anim-only", action="store_true")
    ap.add_argument("--crops-only", action="store_true")
    ap.add_argument("--coverage", action="store_true",
                    help="print the coverage tables and write no sheets")
    args = ap.parse_args(argv)

    known = _all_names()
    names = args.names or known
    unknown = [n for n in names if n not in known]
    if unknown:
        raise SystemExit("unknown cursor(s): %s" % ", ".join(unknown))
    if args.coverage:
        coverage(names, args.sizes)
        return
    only = args.ladder_only or args.anim_only or args.crops_only
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    font = B._font(13)

    print("audit ->", out)
    if args.ladder_only or not only:
        ladders(out, names, args.sizes, args.bgs, font)
    if args.anim_only or not only:
        anims(out, names, args.bgs, font)
    if args.crops_only or not only:
        crops(out, names, args.bgs, args.crop_sizes, font)

    with open(os.path.join(out, "README.txt"), "w", encoding="utf-8") as fh:
        fh.write("git head : %s\n" % _head())
        fh.write("cursors  : %s\n" % ", ".join(names))
        fh.write("sizes    : %s\n" % ", ".join(map(str, args.sizes)))
        fh.write("crops    : %s, or top/bottom/left/right/centre where there is\n"
                 "           no fold chord, at %s, %.1f logical units, NEAREST\n"
                 % ("/".join(PARTS), ", ".join(map(str, args.crop_sizes)),
                    CROP_UNITS))
        fh.write("bgs      : %s\n" % ", ".join("%s %s" % (b, BGS[b]) for b in args.bgs))
        fh.write("tiles are native renders, never resampled\n")


if __name__ == "__main__":
    main()

"""Rim crispness and evenness, the direction the render is held to.

Two numbers per cursor at 128, 256 and 512, frame 0 composited on white,
in the rim band (0.15-1.6 logical units in from the traced edge):

  X  mean luminance gradient across the edge: how sharp the rim's dark
     hairline and lit line are. Release 1.1.0 is the floor.
  A  wobble along the edge: the band unrolled into arc by depth, each sample
     against the mean of its neighbours at the same depth 2 px and 0.5 LU
     either way. 201694a, the render before the chrome was given back, is
     the ceiling: release 1.1.0 was sharp and wavy, 201694a even and dull,
     the target is both at once (docs/dev/IDEAL.md).

A stage that lowers X without lowering A blurs the chrome and buys nothing.

Read on the unrolled band, not along pixels: a difference taken along a
pixel's own tangent reads a crisp line a degree off the outline, and any
curve, as wobble in proportion to its sharpness, which is what X asks for.

Both are read off the points, where the edge has no one normal, and outside
the owner's complaint: the valley behind the blade (NEXT.md 116-117), found
as the pixels _rim_valley lifts on the release frame itself. That dark line
is the release's sharpest edge and a defect at once. The zone is the
release's, fixed, kept in data/crisp-zone.npz.

    python tools/crisp.py                  # HEAD against the references
    python tools/crisp.py --write DIR      # release reference and zone from
                                           # DIR/r_NAME_SIZE.png
    python tools/crisp.py --even DIR       # evenness reference, same layout
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
from PIL import Image

from cgr import hybrid as H

CURSORS = ("Arrow", "AppStarting", "Wait", "Hand", "Help", "NO", "Handwriting")
SIZES = (128, 256, 512)
BAND = (0.15, 1.6)
X_FLOOR = 0.95    # of release: across-edge sharpness may not fall below
A_CEIL = 1.05     # of 201694a: along-edge wobble may not rise above
DATA = os.path.join(os.path.dirname(__file__), "..", "data")
REF = os.path.join(DATA, "crisp-release.json")
EVEN = os.path.join(DATA, "crisp-even.json")
ZONE = os.path.join(DATA, "crisp-zone.npz")
LIFT = 0.5        # levels _rim_valley lifts a release pixel by to be complaint
POINT = 3.0       # LU round a sharp point left out
ALONG = (None, 0.5)   # neighbours either way: 2 px (dots), 0.5 LU (the wave)
DEPTH_TOL = 0.25  # LU a sample's own depth may sit off its ray's: past it
                  # the ray has crossed the medial ridge


def complaint(rel, name, size):
    """Pixels of the release frame the valley fill lifts: the owner's complaint."""
    a = np.asarray(rel, dtype=np.float64)
    b = np.asarray(H._rim_valley(rel, name, 0, size), dtype=np.float64)
    return np.abs(b[..., :3] - a[..., :3]).max(-1) >= LIFT


def _rays(name, step, d, L):
    """Points every `step` LU along each traced outline, with inward normals."""
    C = H.C
    for poly in C.TRACED[name]["frames"][0]["polys"]:
        pts = np.array([p[:2] for p in C.smooth([tuple(p) for p in poly])],
                       dtype=np.float64)
        if len(pts) < 3:
            continue
        seg = np.roll(pts, -1, 0) - pts
        ln = np.hypot(seg[:, 0], seg[:, 1])
        cum = np.concatenate([[0.0], np.cumsum(ln)])
        s = np.arange(0.0, cum[-1], step)
        i = np.clip(np.searchsorted(cum, s, side="right") - 1, 0, len(pts) - 1)
        p = pts[i] + seg[i] * ((s - cum[i]) / np.maximum(ln[i], 1e-9))[:, None]
        t = seg[i] / np.maximum(ln[i], 1e-9)[:, None]
        # the tangent over a quarter unit, so the normal does not jump at a vertex
        k = max(1, int(round(0.25 / step)))
        tt = t.copy()
        for o in range(1, k + 1):
            tt += np.roll(t, o, 0) + np.roll(t, -o, 0)
        tt /= np.maximum(np.hypot(tt[:, 0], tt[:, 1]), 1e-9)[:, None]
        nrm = np.stack([-tt[:, 1], tt[:, 0]], 1)
        q, r = (p + 0.5 * nrm) * L - 0.5, (p - 0.5 * nrm) * L - 0.5
        if np.median(H._sample1(d, q[:, 0], q[:, 1])
                     - H._sample1(d, r[:, 0], r[:, 1])) < 0:
            nrm = -nrm
        yield p, nrm


def measure(rgba, name, size, skip=None):
    a = np.asarray(rgba, dtype=np.float64)
    al = a[..., 3:] / 255.0
    lum = (a[..., :3] * al + 255.0 * (1.0 - al)) @ [0.2126, 0.7152, 0.0722]
    d = H._edge_distance_at(name, 0, size)
    L = size / 32.0
    corners = H._sharp_corners(name, 0)

    dy, dx = np.gradient(d)
    gn = np.hypot(dx, dy)
    inner = d > BAND[0]
    band = inner & (d < BAND[1]) & (gn > 0.5 * np.median(gn[inner]))
    ys, xs = (np.mgrid[0:size, 0:size] + 0.5) / L
    for cx, cy in corners:
        band &= np.hypot(xs - cx, ys - cy) >= POINT
    if skip is not None:
        band &= ~skip
    nx, ny = dx / np.maximum(gn, 1e-9), dy / np.maximum(gn, 1e-9)
    ly, lx = np.gradient(lum)
    across = np.abs(lx * nx + ly * ny)[band].mean()

    # Smoothed by a pixel's binomial first, so that bilinear lookups across a
    # crisp line do not print their own interpolation error as wobble.
    sm = lum
    for ax in (0, 1):
        sm = 0.5 * sm + 0.25 * (np.roll(sm, 1, ax) + np.roll(sm, -1, ax))
    step = 0.5 / L
    dep = np.arange(BAND[0], BAND[1], step)
    res = {h: [] for h in ALONG}
    for p, nrm in _rays(name, step, d, L):
        X = p[:, None, 0] + nrm[:, None, 0] * dep[None]
        Y = p[:, None, 1] + nrm[:, None, 1] * dep[None]
        sx, sy = X * L - 0.5, Y * L - 0.5
        G = H._sample1(sm, sx, sy)
        ok = np.abs(H._sample1(d, sx, sy) - dep[None]) < DEPTH_TOL
        for cx, cy in corners:
            ok &= np.hypot(X - cx, Y - cy) >= POINT
        if skip is not None:
            ix = np.clip(np.round(sx).astype(int), 0, size - 1)
            iy = np.clip(np.round(sy).astype(int), 0, size - 1)
            ok &= ~skip[iy, ix]
        for h in ALONG:
            k = max(1, int(round((2.0 / L if h is None else h) / step)))
            nb = 0.5 * (np.roll(G, k, 0) + np.roll(G, -k, 0))
            v = ok & np.roll(ok, k, 0) & np.roll(ok, -k, 0)
            res[h].append(np.abs(G - nb)[v])
    along = np.mean([np.concatenate(v).mean() for v in res.values()])
    return float(across), float(along)


def _load_zone():
    zone = {}
    with np.load(ZONE) as z:
        for key in z.files:
            size = int(key.split("@")[1])
            zone[key] = np.unpackbits(z[key])[:size * size].reshape(size, size) > 0
    return zone


def _frames(src):
    for name in CURSORS:
        for size in SIZES:
            if src:
                im = Image.open(os.path.join(src, "r_%s_%d.png" % (name, size)))
                yield name, size, im.convert("RGBA")
            else:
                yield name, size, H.frame_image(name, 0, size)


def _dump(path, got):
    with open(path, "wb") as f:
        f.write((json.dumps(got, indent=1, sort_keys=True) + "\n").encode())
    print("wrote", path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", metavar="DIR")
    ap.add_argument("--even", metavar="DIR")
    args = ap.parse_args()
    if args.write:
        got, zone = {}, {}
        for name, size, im in _frames(args.write):
            key = "%s@%d" % (name, size)
            zone[key] = complaint(im, name, size)
            got[key] = measure(im, name, size, zone[key])
        _dump(REF, got)
        np.savez_compressed(ZONE, **{k: np.packbits(v) for k, v in zone.items()
                                     if v.any()})
        print("wrote", ZONE)
        return 0
    zone = _load_zone()
    got = {}
    for name, size, im in _frames(args.even):
        key = "%s@%d" % (name, size)
        got[key] = measure(im, name, size, zone.get(key))
    if args.even:
        _dump(EVEN, got)
        return 0
    with open(REF, "rb") as f:
        ref = json.loads(f.read().decode())
    with open(EVEN, "rb") as f:
        even = json.loads(f.read().decode())
    bad = 0
    print("%-16s %6s %6s %6s   %6s %6s %6s %6s"
          % ("", "X", "rel", "x/rel", "A", "even", "a/even", "a/rel"))
    for key, (x, a) in got.items():
        rx, ra = ref[key]
        ea = even[key][1]
        flag = []
        if x < X_FLOOR * rx:
            flag.append("blurred")
        if a > A_CEIL * ea:
            flag.append("wobbly")
        bad += bool(flag)
        print("%-16s %6.2f %6.2f %6.2f   %6.2f %6.2f %6.2f %6.2f  %s"
              % (key, x, rx, x / rx, a, ea, a / ea, a / ra, " ".join(flag)))
    print("crisp: %d of %d off target" % (bad, len(got)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

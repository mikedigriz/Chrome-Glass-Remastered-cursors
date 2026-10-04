"""Rim crispness against release 1.1.0, the direction the render is held to.

Two numbers per cursor at 128, 256 and 512, frame 0 composited on white,
in the rim band (0.15-1.6 logical units in from the traced edge):

  X  mean luminance gradient across the edge: how sharp the rim's dark
     hairline and lit line are. Release 1.1.0 is the floor.
  A  mean gradient along the edge: wobble, dots, the wavy line. Release 1.1.0
     had too much; the target is well under it.

A stage that lowers X without lowering A blurs the chrome and buys nothing
(docs/dev/IDEAL.md).

Both are read outside the owner's complaint: the valley behind the blade
(NEXT.md 116-117), found as the pixels _rim_valley lifts on the release frame
itself. That dark line is the release's sharpest edge and a defect at once;
counted, it held X down where the fill is right and hid the wobble left
elsewhere. The zone is the release's, fixed, kept in data/crisp-zone.npz.

    python tools/crisp.py                  # HEAD against data/crisp-release.json
    python tools/crisp.py --write DIR      # reference and zone from
                                           # DIR/r_NAME_SIZE.png
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
A_CEIL = 0.75     # of release: along-edge variation must stay under
REF = os.path.join(os.path.dirname(__file__), "..", "data", "crisp-release.json")
ZONE = os.path.join(os.path.dirname(__file__), "..", "data", "crisp-zone.npz")
LIFT = 0.5        # levels _rim_valley lifts a release pixel by to be complaint
POINT = 3.0       # LU round a sharp point left out: in the narrow wedge the
                  # other side's lines run across this side's "along"


def complaint(rel, name, size):
    """Pixels of the release frame the valley fill lifts: the owner's complaint."""
    a = np.asarray(rel, dtype=np.float64)
    b = np.asarray(H._rim_valley(rel, name, 0, size), dtype=np.float64)
    return np.abs(b[..., :3] - a[..., :3]).max(-1) >= LIFT


def measure(rgba, name, size, skip=None):
    a = np.asarray(rgba, dtype=np.float64)
    al = a[..., 3:] / 255.0
    lum = (a[..., :3] * al + 255.0 * (1.0 - al)) @ [0.2126, 0.7152, 0.0722]
    d = H._edge_distance_at(name, 0, size)
    dy, dx = np.gradient(d)
    gn = np.hypot(dx, dy)
    inner = d > BAND[0]
    # off the medial ridge and the points, where the edge has no one normal
    band = inner & (d < BAND[1]) & (gn > 0.5 * np.median(gn[inner]))
    L = size / 32.0
    ys, xs = (np.mgrid[0:size, 0:size] + 0.5) / L
    for cx, cy in H._sharp_corners(name, 0):
        band &= np.hypot(xs - cx, ys - cy) >= POINT
    if skip is not None:
        band &= ~skip
    nx, ny = dx / np.maximum(gn, 1e-9), dy / np.maximum(gn, 1e-9)
    ly, lx = np.gradient(lum)
    across = np.abs(lx * nx + ly * ny)[band].mean()
    along = np.abs(ly * nx - lx * ny)[band].mean()
    return float(across), float(along)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", metavar="DIR")
    args = ap.parse_args()
    got = {}
    zone = {}
    if not args.write:
        with np.load(ZONE) as z:
            for key in z.files:
                size = int(key.split("@")[1])
                zone[key] = np.unpackbits(z[key])[:size * size].reshape(size, size) > 0
    for name in CURSORS:
        for size in SIZES:
            key = "%s@%d" % (name, size)
            if args.write:
                im = Image.open(os.path.join(args.write, "r_%s_%d.png" % (name, size)))
                im = im.convert("RGBA")
                zone[key] = complaint(im, name, size)
            else:
                im = H.frame_image(name, 0, size)
            got[key] = measure(im, name, size, zone.get(key))
    if args.write:
        with open(REF, "wb") as f:
            f.write((json.dumps(got, indent=1, sort_keys=True) + "\n").encode())
        np.savez_compressed(ZONE, **{k: np.packbits(v) for k, v in zone.items() if v.any()})
        print("wrote", REF, ZONE)
        return 0
    with open(REF, "rb") as f:
        ref = json.loads(f.read().decode())
    bad = 0
    print("%-16s %6s %6s %6s   %6s %6s %6s" % ("", "X", "rel", "x/rel", "A", "rel", "a/rel"))
    for key, (x, a) in got.items():
        rx, ra = ref[key]
        flag = []
        if x < X_FLOOR * rx:
            flag.append("blurred")
        if a > A_CEIL * ra:
            flag.append("wobbly")
        bad += bool(flag)
        print("%-16s %6.2f %6.2f %6.2f   %6.2f %6.2f %6.2f  %s"
              % (key, x, rx, x / rx, a, ra, a / ra, " ".join(flag)))
    print("crisp: %d of %d off target" % (bad, len(got)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

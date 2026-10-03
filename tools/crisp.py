"""Rim crispness against release 1.1.0, the direction the render is held to.

Two numbers per cursor at 128, 256 and 512, frame 0 composited on white,
in the rim band (0.15-1.6 logical units in from the traced edge):

  X  mean luminance gradient across the edge: how sharp the rim's dark
     hairline and lit line are. Release 1.1.0 is the floor.
  A  mean gradient along the edge: wobble, dots, the wavy line. Release 1.1.0
     had too much; the target is well under it.

A stage that lowers X without lowering A blurs the chrome and buys nothing
(docs/dev/IDEAL.md).

    python tools/crisp.py                  # HEAD against data/crisp-release.json
    python tools/crisp.py --write DIR      # reference from DIR/r_NAME_SIZE.png
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


def measure(rgba, name, size):
    a = np.asarray(rgba, dtype=np.float64)
    al = a[..., 3:] / 255.0
    lum = (a[..., :3] * al + 255.0 * (1.0 - al)) @ [0.2126, 0.7152, 0.0722]
    d = H._edge_distance_at(name, 0, size)
    dy, dx = np.gradient(d)
    gn = np.hypot(dx, dy)
    inner = d > BAND[0]
    # off the medial ridge and the points, where the edge has no one normal
    band = inner & (d < BAND[1]) & (gn > 0.5 * np.median(gn[inner]))
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
    for name in CURSORS:
        for size in SIZES:
            if args.write:
                im = Image.open(os.path.join(args.write, "r_%s_%d.png" % (name, size)))
                im = im.convert("RGBA")
            else:
                im = H.frame_image(name, 0, size)
            got["%s@%d" % (name, size)] = measure(im, name, size)
    if args.write:
        with open(REF, "wb") as f:
            f.write((json.dumps(got, indent=1, sort_keys=True) + "\n").encode())
        print("wrote", REF)
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

"""Pin and Person cursors - Windows 10/11 slots the 2006 original never had.

Each is the hybrid glass Arrow with an amber glass glyph (map pin / person)
drawn over the lower-right of the blade, the way the original draws Help's
"?" over the glass.  The palette is sampled from UpArrow, the set's warm
accent, so the new cursors read as part of the family.
"""
import functools, math
import numpy as np
from PIL import Image

import hybrid as H
import vectorlib as V

# amber glass sampled from the original UpArrow (light / dark quantiles)
LIGHT = (246, 233, 180, 235)
DARK = (196, 168, 70, 235)
EDGE = ((122, 100, 38, 210), 0.75)
GLOSS = (255, 255, 255, 130)

NAMES = ["Pin", "Person"]
HOTSPOT = (3, 3)                     # same as Arrow


def _circle(cx, cy, r, a0=0.0, a1=2 * math.pi, n=48):
    return [(cx + r * math.cos(a0 + (a1 - a0) * i / n),
             cy + r * math.sin(a0 + (a1 - a0) * i / n)) for i in range(n + 1)]


def _pin_prims():
    """Map-pin teardrop: circle head, tangent tip, punched hole."""
    cx, cy, r = 23.0, 18.2, 4.4
    tip = (cx, 27.8)
    d = tip[1] - cy
    beta = math.acos(r / d)
    # contact angles either side of the straight-down direction (pi/2)
    a_from = math.pi / 2 - beta
    a_to = math.pi / 2 + beta - 2 * math.pi        # the long way over the top
    body = [tip] + _circle(cx, cy, r, a_from, a_to, 56)
    grad = ((LIGHT, DARK, (0, cy - r, 0, tip[1])))
    prims = [{"poly": body, "grad": grad, "stroke": EDGE}]
    gloss = _circle(cx - 1.1, cy - 1.6, 1.9)
    prims.append({"poly": gloss, "fill": GLOSS, "blur": 0.55})
    hole = [{"poly": _circle(cx, cy, 1.8), "fill": (255, 255, 255, 255)}]
    return prims, hole


def _person_prims():
    """Head over rounded shoulders, with the classic gap between them."""
    hx_, hy_, hr = 23.0, 16.6, 2.75
    bx, by = 23.0, 27.6                            # shoulder dome base centre
    rx, ry = 4.9, 6.2
    head = _circle(hx_, hy_, hr)
    dome = [(bx + rx * math.cos(a), by - ry * math.sin(a))
            for a in [math.pi - math.pi * i / 56 for i in range(57)]]
    grad = ((LIGHT, DARK, (0, hy_ - hr, 0, by)))
    prims = [{"poly": head, "grad": grad, "stroke": EDGE},
             {"poly": dome, "grad": grad, "stroke": EDGE}]
    gloss = _circle(hx_ - 0.8, hy_ - 0.9, 1.1)
    prims.append({"poly": gloss, "fill": GLOSS, "blur": 0.4})
    return prims, None


def _glyph_layer(name, size):
    prims, hole = _pin_prims() if name == "Pin" else _person_prims()
    layer = np.asarray(V.render(prims, size), dtype=np.float64)
    if hole:
        cut = np.asarray(V.render(hole, size), dtype=np.float64)[..., 3]
        layer[..., 3] = layer[..., 3] * (1.0 - cut / 255.0)
    return Image.fromarray(layer.round().astype(np.uint8), "RGBA")


@functools.lru_cache(maxsize=None)
def frame(name, size):
    """Hybrid Arrow + glass glyph, any size."""
    base = H.frame_image("Arrow", 0, size).copy()
    base.alpha_composite(_glyph_layer(name, size))
    return base

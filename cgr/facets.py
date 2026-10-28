"""The glass cursors as surfaces: outline, fold, bevel (GLASS_PLAN.md stage 1a).

An arrow is four straight sides and one fold. Measured on the author's 32 px
alpha, every side of Arrow is a straight line to pixel noise (rms 0.06-0.09
LU, bow under 0.2); traced.json bows the same sides by 0.4-0.5 LU because its
points pull out towards the tips. So the outline here is not traced: each side
is a line fitted to the half-height crossing of the author's alpha along its
normal, and each corner is where two sides meet. The only inputs are the
author's frame and the rough corners H._landmarks already finds.

Height is a roof over the fold: the fold A-J splits the outline into two
triangles, each a plane falling away from the chord, and a bevel of width
`rim` rounds every outer side into it. Each piece is a min of smooth terms,
so the fold is a straight crease and every corner is a mitre that meets on
the bisector - the inner point sits inside the outer one, on its line, by
construction.
"""
import functools

import numpy as np
from PIL import Image

from . import hybrid as H
from . import vectorlib as V

# The fold runs from the point to the notch; the sides go round the outline
# in this order. The arrow family and the darts of the bevel cursors.
ORDER = ("A", "C", "J", "B")
POINTS = ("A", "C", "B")     # the convex corners; J is the concave notch
SURFACE = {
    # rim: bevel width, LU. tilt: plane slope away from the fold, per facet
    # (upper A-C-J, lower A-J-B), height per LU. ridge: fold height at A, J.
    # rim 0.9: the author's bright band is about a pixel of his 32 with its
    # antialiasing; at 1.2 the inner point sat 2.9-3.2 LU back from the outer
    # one and read as stubby, 1.1.0 nests it at 1.6-2.7 (IDEAL.md). 1.3 on
    # the owner's word (2026-10-25): at 0.9 the edges were too narrow to read
    # as chrome and for the light animation to run on. 1.6 (owner, same day):
    # the inner cursor smaller, the outer edges more noticeable; 1.9 heavy
    "Arrow": {"rim": 1.6, "tilt": (0.10, 0.10), "ridge": (1.0, 1.0)},
}
# the family draws Arrow's body in its own colour (GLASS_PLAN.md stage 2)
# Hand's frames are Arrow tilting, each frame its own trace and tone; NO's
# pointer is his frame 0 shrinking toward its point under the growing sign
for _n in ("Arrow_Down", "UpArrow", "Help", "Hand", "NO", "Wait", "AppStarting", "Handwriting"):
    SURFACE[_n] = SURFACE["Arrow"]
SHRINK = ("NO", "Handwriting")

# Handwriting (GLASS_PLAN.md stage 5): his frame 0 shrinks toward its point
# while a pen grows out of it, nib on the point. Fitted to his alpha: the
# arrow's scales (pure scaling through frame 3, 0.6-1.5 of squared error),
# the pen scaled about its nib, its length growing 4 LU a frame. The pen's
# share per frame; the "trace" frames are one shape, the arrow and the pen
# grown together (a cross-fade there stood as a double exposure)
MORPH = {"Handwriting": {
    "scale": (1.0, 0.93, 0.825, 0.725, 0.625, 0.55, 0.50, 0.45, 0.45),
    "pen": (0, 0, 0, 0, 18.0, 21.5, 25.5, 29.5, 34.2),
    "share": (0, 0, 0, 0, 0, 0, 1.0, 1.0, 1.0),
    "trace": (5,)}}
# the pen, fitted to his frame 8: nib point, axis, half width, the nib's
# taper length, and the clip over its upper side: along as shares of the
# length, across its inner and outer edge (LU from the axis), its nose.
# His clip is blunt ahead (his alpha full from its first LU)
PEN = {"point": (3.216, 3.228), "deg": 45.166, "hw": 3.76, "nib": 9.88,
       "clip": (0.52, 0.92, 2.8, 6.0, 1.6)}


def pen_sdf(name, idx, px, py, part=None):
    """Signed distance to the pen of frame idx, LU, + inside: a rod from the
    nib, round at the far end, its nib an ogive, and the clip, a leaf of its
    own laid over the rod's upper flank, pointed toward the nib. part
    "body" or "clip" gives the one alone. His pen grows scaled about the
    nib's point (fitted half widths 3.0, 3.2, 3.7 as the length goes 25,
    29, 34)."""
    pens = MORPH[name]["pen"]
    k = pens[idx] / pens[-1]
    q = np.asarray(PEN["point"])
    body, clip = _pen_sdf(pens[-1], q[0] + (px - q[0]) / k, q[1] + (py - q[1]) / k)
    d = {"body": body, "clip": clip}.get(part, np.maximum(body, clip) if part is None else None)
    return k * d


def _ogive(t, s, nib, hw, end):
    """A rod along t from its point at 0, half width hw, the point an ogive
    nib long (its half width rises on a parabola, into the rod without a
    kink; a straight cone stood off its shoulder as a sharpened pencil),
    round at `end`."""
    tc = np.clip(t, nib, end - hw)
    d = hw - np.hypot(t - tc, s)
    v = np.clip(t / nib, 0, 1)
    w_t = hw * (1 - (1 - v) ** 2)
    slope = 2 * hw / nib * (1 - v)
    d = np.where(t < nib, (w_t - np.abs(s)) / np.sqrt(1 + slope ** 2), d)
    return np.where(t < 0, -np.hypot(t, s), d)


def _pen_sdf(L, px, py):
    q = np.asarray(PEN["point"])
    a = np.radians(PEN["deg"])
    u = np.array([np.cos(a), np.sin(a)])
    t = (px - q[0]) * u[0] + (py - q[1]) * u[1]
    s = -(px - q[0]) * u[1] + (py - q[1]) * u[0]
    body = _ogive(t, s, PEN["nib"], PEN["hw"], L)
    c0, c1, s_in, s_out, c_nib = PEN["clip"]
    c0, c1 = c0 * L, c1 * L
    sc, hc = -(s_in + s_out) / 2, (s_out - s_in) / 2
    return body, _ogive(t - c0, s - sc, c_nib, hc, c1 - c0)

# The bevel cursors are darts, each an arrow: point, two wings, a notch
# between them (GLASS_PLAN.md stage 3). One per traced outline; SizeAll is
# four round a hole, wings meeting at the star's concave corners, notches
# the hole's corners. A
# dart is drawn as an arrow _DART_SCALE times its size on a canvas of its own,
# _DART_SPAN LU of the frame, so every length of Arrow's material holds as it
# is. Its canvas starts on an even LU: at any size divisible by 4 its samples
# then fall on the frame's own, nothing is resampled
DARTS = ("Cross", "IBeam", "SizeNS", "SizeWE", "SizeNESW", "SizeNWSE", "SizeAll")
_STAR = ("SizeAll",)
_DART_SCALE = 2
_DART_SPAN = 16.0
PART = {}            # "Name.i" -> (name, outline index, canvas origin in LU of the frame)


def _polys(name, idx=0):
    return [np.asarray([(q[0], q[1]) for q in poly], dtype=np.float64)
            for poly in H.C.TRACED[name]["frames"][idx]["polys"]]


def parts(name):
    return sorted(k for k, v in PART.items() if v[0] == name)


def _star(name, idx=0):
    """SizeAll's darts as rough outlines: [(point, wing, wing)] round the
    star, the wings the outline's points nearest the middle between points."""
    poly = H.C.TRACED[name]["frames"][idx]["polys"][0]
    pts = np.asarray([(q[0], q[1]) for q in poly], dtype=np.float64)
    tips = [k for k, q in enumerate(poly) if q[2]]
    mid = pts[tips].mean(0)
    m = len(pts)
    wings = []
    for k0, k1 in zip(tips, tips[1:] + tips[:1]):
        run = [(k0 + s) % m for s in range(1, (k1 - k0) % m)]
        wings.append(pts[min(run, key=lambda k: np.hypot(*(pts[k] - mid)))])
    return [(pts[k], wings[i - 1], wings[i]) for i, k in enumerate(tips)], mid


def _rough(name, idx=0):
    """The outlines a frame's darts are cut from, for their canvases and for
    whose of his pixels are whose."""
    if name in _STAR:
        darts, mid = _star(name, idx)
        return [np.asarray([a, w0, mid, w1]) for a, w0, w1 in darts]
    return _polys(name, idx)


for _n in DARTS:
    for _i, _q in enumerate(_rough(_n)):
        _lo, _hi = _q.min(0), _q.max(0)
        _o = np.clip(np.round(((_lo + _hi) / 2 - _DART_SPAN / 2) / 2) * 2, 0, V.LOGICAL - _DART_SPAN)
        if (_lo < _o).any() or (_hi > _o + _DART_SPAN).any():
            raise ValueError("%s outline %d does not fit its canvas at %s" % (_n, _i, _o))
        PART["%s.%d" % (_n, _i)] = (_n, _i, (float(_o[0]), float(_o[1])))
        SURFACE["%s.%d" % (_n, _i)] = SURFACE["Arrow"]

_RAY_BACK = 3.0      # LU inside the side where a crossing ray starts
_RAY_OUT = 2.0       # LU outside it where the ray ends
_RAY_STEP = 0.02
_SIDE_MARGIN = 2.0   # LU kept off each corner: there two sides share pixels
_CORNER_SOFT = 0.35  # of the rim: how far the bevel's facing blends across a mitre


def _alpha(name, idx):
    return np.asarray(original(name, idx))[..., 3].astype(np.float64) / 255.0


def _in_poly(px, py, q):
    inside = np.zeros(px.shape, bool)
    for a, b in zip(q, np.roll(q, -1, 0)):
        if a[1] == b[1]:
            continue
        x = a[0] + (py - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
        inside ^= ((a[1] > py) != (b[1] > py)) & (px < x)
    return inside


@functools.lru_cache(maxsize=None)
def owner(name, idx=0):
    """Which dart each of his 32 px pixels is: the nearest outline's."""
    px, py = grid(32)
    dist = np.stack([np.where(_in_poly(px, py, q), 0.0,
                              np.min([_seg_dist(px, py, a, b) for a, b in zip(q, np.roll(q, -1, 0))], 0))
                     for q in _rough(name, idx)])
    return np.argmin(dist, 0)


@functools.lru_cache(maxsize=None)
def original(name, idx=0):
    """The author's 32 px frame; for a dart, his pixels of that dart on its
    canvas, bilinear in premultiplied light."""
    if name not in PART:
        return H.original(name, idx)
    base, i, (ox, oy) = PART[name]
    im = np.asarray(H.original(base, idx)).astype(np.float64)
    px, py = grid(32)
    a = im[..., 3] / 255.0 * (owner(base, idx) == i)
    pre = V.srgb_to_linear(im[..., :3].astype(np.uint8)) * a[..., None]
    pts = np.stack([ox + px.ravel() / _DART_SCALE, oy + py.ravel() / _DART_SCALE], 1)
    if base in _STAR and i in _star_flip(base, idx):
        mid, u = _star_geom(base, idx)[:2]
        q = pts - mid
        pts = mid + 2 * (q @ u[i])[:, None] * u[i] - q
    al = _bilinear(a, pts).reshape(32, 32)
    rgb = np.stack([_bilinear(pre[..., c], pts).reshape(32, 32) for c in range(3)], -1)
    rgb = V.linear_to_srgb(rgb / np.maximum(al, 1e-9)[..., None])
    return Image.fromarray(np.dstack([rgb, np.round(al * 255).astype(np.uint8)]), "RGBA")


def _cross(a, b):
    """z of the cross product of 2-vectors: numpy 2 refuses them in np.cross."""
    return a[0] * b[1] - a[1] * b[0]


def _dart_corners(name, idx):
    """(A, B, J, C) of a dart on its canvas, as H._landmarks gives them for an
    arrow: the point is the sharp corner the other two face, the wings those
    two, the notch the deepest point of the outline between the wings away
    from the point, measured from the wings' line (his sides are concave too,
    so the deepest point inside the hull can lie on a side)."""
    base, i, o = PART[name]
    if base in _STAR:
        return _star_corners(name, idx)
    poly = H.C.TRACED[base]["frames"][idx]["polys"][i]
    pts = np.asarray([(q[0], q[1]) for q in poly], dtype=np.float64)
    k_sh = [k for k, q in enumerate(poly) if q[2]]
    if len(k_sh) != 3:
        raise ValueError("%s: %d sharp corners, a dart has 3" % (name, len(k_sh)))
    # the point: farthest from the line through the other two
    def off(k):
        u, v = [pts[m] for m in k_sh if m != k]
        e = (v - u) / np.hypot(*(v - u))
        return abs(float(_cross(e, pts[k] - u)))
    k_a = max(k_sh, key=off)
    k_b, k_c = [m for m in k_sh if m != k_a]
    a, wb, wc = pts[k_a], pts[k_b], pts[k_c]
    # the back: the run of the outline from one wing to the other not through the point
    m = len(pts)
    run = [(k_b + s) % m for s in range((k_c - k_b) % m + 1)]
    if k_a in run:
        run = [(k_c + s) % m for s in range((k_b - k_c) % m + 1)]
    e = (wc - wb) / np.hypot(*(wc - wb))
    nrm = np.array([-e[1], e[0]])
    if (a - wb) @ nrm < 0:
        nrm = -nrm
    depth = np.array([(pts[k] - wb) @ nrm for k in run])
    deep = [pts[k] for k, dd in zip(run, depth) if dd > depth.max() - 0.1]
    j = np.mean(deep, axis=0)
    # his darts are symmetric, the traced back is stairs: the notch on the
    # axis from the point to between the wings, at the depth found
    mid = (wb + wc) / 2
    ax = (a - mid) / np.hypot(*(a - mid))
    j = mid + ((j - mid) @ ax) * ax
    d = (j - a) / np.hypot(*(j - a))
    side = [float((q - a) @ np.array([-d[1], d[0]])) for q in (wb, wc)]
    b, c = (wb, wc) if side[0] > side[1] else (wc, wb)
    return tuple(tuple((q - o) * _DART_SCALE) for q in (a, b, j, c))


def _rot(u, deg):
    c, s = np.cos(np.radians(deg)), np.sin(np.radians(deg))
    return np.array([c * u[0] - s * u[1], s * u[0] + c * u[1]])


@functools.lru_cache(maxsize=None)
def _star_geom(name, idx=0):
    """SizeAll as one dart turned four times (owner, 2026-10-26: the inner
    ring perfectly even): the middle, the points' directions a right angle
    apart, and the radii of the points, of the concave corners with their
    angle off the points, and of the hole's corners, each the mean of his
    four. The hole's corner on an axis is where his alpha first reaches
    half of its peak out from the middle."""
    darts, mid = _star(name, idx)
    ang = [np.degrees(np.arctan2(*(a - mid)[::-1])) for a, _w0, _w1 in darts]
    k = np.round((np.asarray(ang) - ang[0]) / 90.0)
    off = np.degrees(np.angle(np.mean(np.exp(1j * np.radians(np.asarray(ang) - 90 * k)))))
    u = [_rot(np.array([1.0, 0.0]), off + 90 * kk) for kk in k]
    big = float(np.mean([np.hypot(*(a - mid)) for a, _w0, _w1 in darts]))
    wings = [w for _a, w0, w1 in darts for w in (w0, w1)]
    rw = float(np.mean([np.hypot(*(w - mid)) for w in wings]))
    phi = float(np.mean([abs(np.degrees(np.arctan2(_cross(uu, w - mid), uu @ (w - mid))))
                         for uu, (_a, w0, w1) in zip(u, darts) for w in (w0, w1)]))
    al = np.asarray(H.original(name, idx))[..., 3] / 255.0
    r = np.arange(0.0, big, 0.02)
    hole = []
    for uu in u:
        v = _bilinear(al, mid + np.outer(r, uu))
        hole.append(r[int(np.argmax(v >= 0.5 * v.max()))])
    return mid, u, big, rw, phi, float(np.mean(hole))


@functools.lru_cache(maxsize=None)
def _star_flip(name, idx=0):
    """SizeAll's darts read mirrored across their axes: his star is lit
    from one corner, so at one joint two lit halves meet, at the opposite
    two dark ones (owner, 2026-10-26). Turned like a pinwheel each dart's lit
    half is on the same side going round, every joint lit against dark: the
    upper dart as he has it, the ones lit the other way round mirrored."""
    mid, u = _star_geom(name, idx)[:2]
    im = np.asarray(H.original(name, idx)).astype(np.float64)
    lum, a = im[..., :3].mean(-1), im[..., 3] / 255.0
    px, py = grid(32)
    x, y = px - mid[0], py - mid[1]
    turn = []
    for uu in u:
        along, across = x * uu[0] + y * uu[1], uu[0] * y - uu[1] * x
        own = (along > np.abs(across)) & (a > 0.3)
        turn.append(np.sign(lum[own & (across > 0.3)].mean() - lum[own & (across < -0.3)].mean()))
    top = int(np.argmin([uu[1] for uu in u]))
    return frozenset(k for k, s in enumerate(turn) if s != turn[top])


_RING_IN = 0.3   # LU the darts' square hole sits inside the round one, so its rims are cut away


def ring(name, idx=0):
    """SizeAll's round hole (owner, 2026-10-26, as 1.1.0): the middle and
    the radius, the area of his square hole."""
    mid, _u, _big, _rw, _phi, r = _star_geom(name, idx)
    return mid, r * np.sqrt(2 / np.pi)


_SEAM_EASE = (0.35, 1.5)   # half-width of the ease across a joint per LU in from the concave corner, LU at most


def sector(name, px, py, idx=0):
    """For one of SizeAll's darts, its weight at samples (in LU of the
    frame): 1 in its quarter of the star, its wings run on past the concave
    corners and there it meets its neighbours on the diagonal. A cut there
    showed as a line from the corner to the ring, each dart's glass its own
    tone (owner, 2026-10-26): the two are eased into each other across it,
    from nothing at the corner, which stays sharp, wider toward the ring."""
    base, i, _o = PART[name]
    mid, u, _R, rw, _phi, _r = _star_geom(base, idx)
    x, y = px - mid[0], py - mid[1]
    d = (x * u[i][0] + y * u[i][1] - np.abs(y * u[i][0] - x * u[i][1])) / np.sqrt(2)
    k, top = _SEAM_EASE
    h = np.clip(k * (rw - np.hypot(x, y)), 1e-6, top)
    w = np.clip((d + h) / (2 * h), 0, 1)
    return w * w * (3 - 2 * w)


def _star_corners(name, idx):
    """(A, B, J, C) of one of SizeAll's darts on its canvas. The notch is the
    hole's corner, the back sides run on to the neighbours' notches, so cut
    to its quarter the hole is a square on its corners, inside the round
    hole that is cut later (glass._ring); the wings are where
    the sides through the concave corners meet the back sides, past the
    diagonal."""
    base, i, o = PART[name]
    mid, u, big, rw, phi, _r = _star_geom(base, idx)
    r = ring(base, idx)[1] - _RING_IN
    a, j = mid + big * u[i], mid + r * u[i]
    wings = []
    for sgn in (1, -1):
        w = mid + rw * _rot(u[i], sgn * phi)
        jn = mid + r * _rot(u[i], sgn * 90)
        wings.append(_meet(a, (w - a) / np.hypot(*(w - a)), j, (jn - j) / np.hypot(*(jn - j))))
    d = (j - a) / np.hypot(*(j - a))
    side = [float((q - a) @ np.array([-d[1], d[0]])) for q in wings]
    b, c = (wings[0], wings[1]) if side[0] > side[1] else (wings[1], wings[0])
    return tuple(tuple((q - o) * _DART_SCALE) for q in (a, b, j, c))


def _bilinear(img, pts):
    """img sampled at points in logical units, pixel centres at k + 0.5."""
    n = img.shape[0]
    x = pts[:, 0] - 0.5
    y = pts[:, 1] - 0.5
    x0 = np.floor(x).astype(int)
    y0 = np.floor(y).astype(int)
    fx, fy = x - x0, y - y0

    def at(yy, xx):
        ok = (yy >= 0) & (yy < n) & (xx >= 0) & (xx < n)
        return np.where(ok, img[np.clip(yy, 0, n - 1), np.clip(xx, 0, n - 1)], 0.0)

    return (at(y0, x0) * (1 - fx) * (1 - fy) + at(y0, x0 + 1) * fx * (1 - fy)
            + at(y0 + 1, x0) * (1 - fx) * fy + at(y0 + 1, x0 + 1) * fx * fy)


def _side(alpha, p, q, centre, pin=None):
    """(point, unit direction) of the side from rough corner p to q.

    Along the normal at every quarter unit, the crossing is where alpha falls
    below half of its peak on that ray: the peak is the rim, so the glass at
    half opacity inside does not count as an edge. A box-filtered hard edge
    crosses half height exactly at the edge."""
    d = (q - p) / np.hypot(*(q - p))
    n = np.array([-d[1], d[0]])
    if (centre - p) @ n > 0:
        n = -n                                   # outward
    length = float(np.hypot(*(q - p)))
    s = np.arange(-_RAY_BACK, _RAY_OUT, _RAY_STEP)
    ts, off = [], []
    for t in np.arange(_SIDE_MARGIN, length - _SIDE_MARGIN, 0.25):
        v = _bilinear(alpha, p + d * t + np.outer(s, n))
        k = int(np.argmax(v))
        below = np.nonzero(v[k:] < 0.5 * v[k])[0]
        if v[k] <= 0 or not len(below):
            continue
        i = k + below[0]
        f = (v[i - 1] - 0.5 * v[k]) / (v[i - 1] - v[i])
        ts.append(t)
        off.append(s[i - 1] + f * _RAY_STEP)
    if len(ts) < 4:
        raise ValueError("side %s-%s: %d crossings, too few to fit" % (p, q, len(ts)))
    if pin is None:
        k, c = np.polyfit(ts, off, 1)
    else:
        # through the rough corner at t = pin: only the slope is fitted
        ts, off = np.asarray(ts) - pin, np.asarray(off)
        k = float(ts @ off / (ts @ ts))
        c = -k * pin
    a = p + n * c
    b = p + d * length + n * (c + k * length)
    return a, (b - a) / np.hypot(*(b - a))


def _meet(p, d, r, e):
    t = np.linalg.solve(np.array([d, -e]).T, r - p)
    return p + t[0] * d


@functools.lru_cache(maxsize=None)
def outline(name, idx=0):
    """{corner: (x, y)} in logical units, corners in ORDER round the outline."""
    if name in SHRINK and idx:
        apex, s = shrink(name, idx)
        return {k: tuple(apex + (np.asarray(v) - apex) * s) for k, v in outline(name, 0).items()}
    lm = _dart_corners(name, idx) if name in PART else H._landmarks(name, idx)
    if lm is None:
        raise ValueError("%s[%d]: no fold chord, not an arrow" % (name, idx))
    rough = dict(zip(("A", "B", "J", "C"), (np.asarray(p, dtype=np.float64) for p in lm)))
    if PART.get(name, ("",))[0] in _STAR:
        return {k: tuple(rough[k]) for k in ORDER}     # built, not fitted: even by construction
    alpha = _alpha(name, idx)
    centre = np.mean(list(rough.values()), axis=0)
    # a dart's sides bow in by 0.3-0.8 LU of its canvas toward the point,
    # so lines fitted along them met 1-3 LU past his point: there they are
    # pinned to his traced point
    def pin(i):
        if name not in PART:
            return None
        if ORDER[i] == "A":
            return 0.0
        if ORDER[(i + 1) % 4] == "A":
            return float(np.hypot(*(rough["A"] - rough[ORDER[i]])))
        return None
    sides = [_side(alpha, rough[ORDER[i]], rough[ORDER[(i + 1) % 4]], centre, pin(i))
             for i in range(4)]
    out = {}
    for i, k in enumerate(ORDER):
        (p, d), (r, e) = sides[i - 1], sides[i]
        out[k] = tuple(_meet(p, d, r, e))
    if name in PART:
        # the bowed sides fitted straight run on past his wings too, met by
        # the back sides 1-1.7 LU beyond them (SizeWE 21.1 against his 20.2):
        # a wing ends where his does along the axis, on its side's line
        a = rough["A"]
        u = (rough["J"] - a) / np.hypot(*(rough["J"] - a))
        for k in ("B", "C"):
            w = np.asarray(out[k]) - a
            f = float((rough[k] - a) @ u) / float(w @ u)
            if f < 1:
                out[k] = tuple(a + w * f)
    return out


@functools.lru_cache(maxsize=None)
def shrink(name, idx):
    """(point, scale) of a SHRINK cursor's frame: his frame 0 scaled about
    its point, the scale whose alpha meets his where the sign is not. From
    frame 4 the sign hides the fold and no trace of the frame finds one; his
    traced wings give the same scales on 1-6 (0.95 ... 0.70)."""
    if name in MORPH:
        poly = H.C.TRACED[name]["frames"][0]["polys"][0]
        apex = np.asarray(min((q[:2] for q in poly if q[2]), key=lambda q: q[0] + q[1]), dtype=np.float64)
        return apex, MORPH[name]["scale"][idx]
    poly = H.C.TRACED[name]["frames"][0]["polys"][0]
    apex = np.asarray(min((q[:2] for q in poly if q[2]), key=lambda q: q[0] + q[1]), dtype=np.float64)
    a0 = _alpha(name, 0)
    im = np.asarray(H.original(name, idx)).astype(np.float64)
    a = im[..., 3] / 255.0
    sign = np.clip((im[..., 0] - im[..., 1:3].max(-1)) / 150.0, 0, 1) * a
    px, py = grid(32)
    ok = sign < 0.05
    if sign.sum() > 0.05:
        cx, cy, r_out = sign_geom(name, idx)
        ok &= np.hypot(px - cx, py - cy) > r_out + 0.7
    best = (np.inf, 1.0)
    for s in np.arange(0.4, 1.0 + 1e-9, 0.005):
        pts = np.stack([apex[0] + (px.ravel() - apex[0]) / s, apex[1] + (py.ravel() - apex[1]) / s], 1)
        e = float((((_bilinear(a0, pts).reshape(32, 32) - a) ** 2)[ok]).sum())
        best = min(best, (e, float(s)))
    return apex, best[1]


_FRONT_RAMP = 2.0   # LU over which his wipe goes from kept to gone: two of his pixels
_WIPE_FROM = 7      # his first wiped frame: before it the pointer only dims to his
                    # level, a front there cut NO's step 6->7 under his


@functools.lru_cache(maxsize=None)
def sign_front(name, idx, hole):
    """(level, front, axis, apex) of the shrunk pointer inside the sign's
    hole (inner over outer radius). From frame 7 he wipes it from the sign
    back to the point: kept nearly whole up to a front across the axis,
    gone two of his pixels past it, the front nearer the point each frame.
    A uniform fade by his mass left a whole ghost pointer in the hole that
    read at 128 and up; a patch at a time, eased over 0.5 LU, read as
    smudges. `level` scales what is kept, ahead of the front."""
    geom = sign_geom(name, idx)
    if geom is None:
        return 1.0, np.inf, (1.0, 0.0), (0.0, 0.0)
    apex, s = shrink(name, idx)
    cx, cy, r_out = geom
    im = np.asarray(H.original(name, idx)).astype(np.float64)
    red = (im[..., 0] - im[..., 1:3].max(-1)) > 60
    px, py = grid(32)
    inside = (np.hypot(px - cx, py - cy) < hole * r_out - 0.7) & ~red
    pts = np.stack([apex[0] + (px.ravel() - apex[0]) / s, apex[1] + (py.ravel() - apex[1]) / s], 1)
    ours = _bilinear(_alpha(name, 0), pts).reshape(32, 32)[inside]
    if ours.sum() < 1:
        return 1.0, np.inf, (1.0, 0.0), apex
    ax = np.array([cx - apex[0], cy - apex[1]])
    ax /= np.linalg.norm(ax)
    t = ((px - apex[0]) * ax[0] + (py - apex[1]) * ax[1])[inside]
    his = im[..., 3][inside] / 255.0
    fronts = np.arange(0.0, 40.0, 0.1)
    ramp = np.clip((fronts[:, None] - t[None, :]) / _FRONT_RAMP + 0.5, 0, 1) * ours[None, :]
    # the level that fits best at each front, least squares, clipped to 0..1
    level = np.clip((ramp * his).sum(1) / np.maximum((ramp * ramp).sum(1), 1e-9), 0, 1)
    err = ((level[:, None] * ramp - his[None, :]) ** 2).sum(1)
    k = int(np.argmin(err))
    # under 2 % is his stray pixels, not the pointer: left in, it kept an
    # invisible pointer whose colour jumped against the frame before
    lv = float(level[k]) if level[k] >= 0.02 else 0.0
    if idx < _WIPE_FROM:
        # dimmed whole to his level, no front: kept at 1, NO[6] read 10 % over
        # his alpha at 32 (build check_metrics)
        return lv, np.inf, (float(ax[0]), float(ax[1])), apex
    return lv, float(fronts[k]), (float(ax[0]), float(ax[1])), apex


_SIGN_MASS = 1.62   # his sign's red mass over its outer radius squared, frames 7-9


@functools.lru_cache(maxsize=None)
def sign_geom(name, idx):
    """(cx, cy, outer radius) of NO's sign, or None: the ring fit where his
    ring is round enough to fit, else from its red mass, the same shape."""
    fit = H._ring_fit(name, idx)
    if fit is not None:
        return fit[0], fit[1], fit[2]
    im = np.asarray(H.original(name, idx)).astype(np.float64)
    red = np.clip((im[..., 0] - im[..., 1:3].max(-1)) / 150.0, 0, 1) * im[..., 3] / 255.0
    if red.sum() < 0.5:
        return None
    px, py = grid(32)
    w = red / red.sum()
    return float((w * px).sum()), float((w * py).sum()), float(np.sqrt(red.sum() / _SIGN_MASS))


def polygon(name, idx=0):
    o = outline(name, idx)
    return [o[k] for k in ORDER]


def _seg_dist(px, py, a, b):
    ab = np.subtract(b, a)
    t = ((px - a[0]) * ab[0] + (py - a[1]) * ab[1]) / float(ab @ ab)
    t = np.clip(t, 0.0, 1.0)
    return np.hypot(px - (a[0] + t * ab[0]), py - (a[1] + t * ab[1]))


def grid(size, ss=1):
    """Sample centres of a size x size frame, ss x ss per pixel, in LU."""
    n = size * ss
    c = (np.arange(n) + 0.5) / n * V.LOGICAL
    return np.meshgrid(c, c)


def coverage(name, size, ss=4, idx=0):
    """Hard-edged inside test at the sample grid, box-averaged per pixel."""
    px, py = grid(size, ss)
    # the notch is concave, but the two triangles of the fold are each
    # convex, so the union of their tests is the outline exactly
    o = outline(name, idx)
    inside = _in_tri(px, py, o["A"], o["C"], o["J"]) | _in_tri(px, py, o["A"], o["J"], o["B"])
    return inside.reshape(size, ss, size, ss).mean(axis=(1, 3))


def _in_tri(px, py, a, b, c):
    def cr(p, q):
        return (q[0] - p[0]) * (py - p[1]) - (q[1] - p[1]) * (px - p[0])
    s1, s2, s3 = cr(a, b), cr(b, c), cr(c, a)
    return ((s1 >= 0) & (s2 >= 0) & (s3 >= 0)) | ((s1 <= 0) & (s2 <= 0) & (s3 <= 0))


def _line_dist(px, py, a, b, inner):
    """Distance to the line a-b, positive on the side of point `inner`."""
    d = np.subtract(b, a) / np.hypot(*np.subtract(b, a))
    n = np.array([-d[1], d[0]])
    if (np.subtract(inner, a) @ n) < 0:
        n = -n
    return (px - a[0]) * n[0] + (py - a[1]) * n[1]


def _bevel(u):
    """Quarter-circle rise, 0 at the edge to 1 at the rim's inner line."""
    u = np.clip(u, 0.0, 1.0)
    return np.sqrt(1.0 - (1.0 - u) ** 2)


def _sides(name, idx):
    """[(start, end, inward normal)] round the outline, with the slab test
    that says which points a side's bevel owns: between the bisectors at its
    two ends. Bisector = sum of the inward normals of the sides meeting
    there, which points into the glass at the convex points and at the
    concave notch alike."""
    o = outline(name, idx)
    pts = [np.asarray(o[k]) for k in ORDER]
    n_side = len(pts)
    out = []
    for i in range(n_side):
        p, q = pts[i], pts[(i + 1) % n_side]
        e = (q - p) / np.hypot(*(q - p))
        n = np.array([-e[1], e[0]])
        mid = (p + q) / 2 + 0.05 * n
        if not coverage_at(name, idx, mid):
            n = -n
        out.append([p, q, n])
    bis = []
    for i in range(n_side):
        b = out[i - 1][2] + out[i][2]
        bis.append(b / np.hypot(*b))
    return out, bis


def coverage_at(name, idx, pt):
    o = outline(name, idx)
    x, y = np.array([pt[0]]), np.array([pt[1]])
    return bool((_in_tri(x, y, o["A"], o["C"], o["J"]) | _in_tri(x, y, o["A"], o["J"], o["B"]))[0])


def surface(name, size, ss=4, idx=0):
    """The surface at the sample grid, as a dict of arrays:

      h       height
      facet   0 outside, 1 upper triangle A-C-J, 2 lower A-J-B
      u       place across the bevel: 0 at the outer edge, 1 at its inner
              line and on the facets beyond it
      nx, ny  outward normal of the bevel, blended between the two sides
              near a corner

    One bevel runs round the whole outline, not one per triangle of the
    fold. Per triangle, the fold cut the rim in two all the way to the
    outer point, so the inner point carried on into the outer one (owner,
    2026-10-25: the inner point ends, it does not continue into the outer).
    Each side owns the points between the bisectors at its ends, so its
    inner line is a straight offset meeting the next one on the bisector:
    the inner point is a mitre, sharp, at the notch as at the points. Across
    that mitre the facing is blended over `_CORNER_SOFT` of the rim, so no
    seam runs from the inner point to the outer one."""
    s = SURFACE[name]
    o = outline(name, idx)
    px, py = grid(size, ss)
    sides, _bis = _sides(name, idx)
    sc = side_coords(name, px, py, idx)
    d, slab, best = sc["d_all"], sc["slab"], np.where(sc["dist"] >= 0, sc["dist"], np.inf)
    tau = _CORNER_SOFT * s["rim"]
    w = (1.0 / (1.0 + np.exp(-slab / tau))) * np.exp(-np.clip(d - best, 0, None) / tau)
    w = np.where(np.isfinite(best), w, 0.0)
    nx = -np.tensordot(np.array([sd[2][0] for sd in sides]), w, 1)
    ny = -np.tensordot(np.array([sd[2][1] for sd in sides]), w, 1)
    nn = np.hypot(nx, ny) + 1e-12

    a, j = np.asarray(o["A"]), np.asarray(o["J"])
    along = np.hypot(*(j - a))
    t = np.clip(((px - a[0]) * (j - a)[0] + (py - a[1]) * (j - a)[1]) / along ** 2, 0, 1)
    ridge = s["ridge"][0] + (s["ridge"][1] - s["ridge"][0]) * t
    facet = np.zeros(px.shape, np.uint8)
    h = np.zeros(px.shape)
    u = np.clip(np.where(np.isfinite(best), best, 0.0) / s["rim"], 0.0, 1.0)
    for k, tri in enumerate((("A", "C", "J"), ("A", "J", "B"))):
        m = _in_tri(px, py, *(o[c] for c in tri)) & (facet == 0)
        plane = ridge - s["tilt"][k] * _line_dist(px, py, o["A"], o["J"], o[tri[1 + k]])
        h[m] = (plane * _bevel(u))[m]
        facet[m] = k + 1
    inside = facet > 0
    return {"h": h, "facet": facet, "u": np.where(inside, u, 1.0),
            "nx": np.where(inside, nx / nn, 0.0), "ny": np.where(inside, ny / nn, 0.0),
            "s": sc["s"]}


def perimeter(name, idx=0):
    """Arc length at the start of each side, and the whole length, in LU."""
    sides, _bis = _sides(name, idx)
    lens = [float(np.hypot(*(q - p))) for p, q, _n in sides]
    return np.concatenate([[0.0], np.cumsum(lens)[:-1]]), float(sum(lens))


def corner_s(name, idx=0):
    """{corner: arc length} - where each corner sits on the outline."""
    starts, _total = perimeter(name, idx)
    return dict(zip(ORDER, starts))


def side_coords(name, px, py, idx=0):
    """Where points sit relative to the outline, inside and out:

      d_all   (sides, ...) signed distance to each side's line, + inside
      slab    (sides, ...) how far inside each side's slab, the region
              between the bisectors at its two ends
      owner   the side whose slab the point is in and whose line is nearest
      dist    signed distance to the owner's line
      s       arc length round the outline from A, of the foot on the owner

    The slab, not the nearest segment, decides the owner: that is what makes
    the bevel's inner line a mitre at every corner."""
    sides, bis = _sides(name, idx)
    starts, _total = perimeter(name, idx)
    n_side = len(sides)
    d = np.empty((n_side,) + px.shape)
    slab = np.empty((n_side,) + px.shape)
    t = np.empty((n_side,) + px.shape)
    for i, (p, q, n) in enumerate(sides):
        d[i] = (px - p[0]) * n[0] + (py - p[1]) * n[1]
        e = (q - p) / np.hypot(*(q - p))
        t[i] = np.clip((px - p[0]) * e[0] + (py - p[1]) * e[1], 0.0, np.hypot(*(q - p)))
        lim = []
        for v, b in ((p, bis[i]), (q, bis[(i + 1) % n_side])):
            m = np.array([-b[1], b[0]])
            if ((p + q) / 2 - v) @ m < 0:
                m = -m
            lim.append((px - v[0]) * m[0] + (py - v[1]) * m[1])
        slab[i] = np.minimum(*lim)
    owner = np.argmin(np.where(slab >= 0, np.abs(d), np.inf), axis=0)
    take = lambda a: np.take_along_axis(a, owner[None], 0)[0]
    return {"d_all": d, "slab": slab, "owner": owner, "dist": take(d),
            "s": np.asarray(starts)[owner] + take(t)}

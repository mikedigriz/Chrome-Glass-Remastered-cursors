"""What every frame stands on: the manifest, the author's frames, the traced
outline and its distance field, and the shared frame and animation entry
points.

The frames themselves are drawn by glass.py (docs/dev/GLASS_PLAN.md). This
file was the old chain - an AI colour master inside a vector edge, some fifty
stages after it - which went in stage 6; what is left is geometry the glass,
the build and the gate read, and the animation pacing.

Animated cursors that the author drew at 50 ms/frame (AppStarting, Hand,
Wait) ship at x3 the frame count - same cycle length, three times smoother:
his nine keys on one still outline, splined between and paced by their own
change. Handwriting and NO already run at 60 fps with a freeze on the last
frame; their frames and rate chunks ship unchanged.
"""
import functools, json, os
import numpy as np
from PIL import Image

from . import gpu as GPU
from . import cursors as C
from . import vectorlib as V
from .paths import ART

ORIG = os.path.join(ART, "orig")

MANIFEST = json.load(open(os.path.join(ART, "manifest.json")))
BY_NAME = {m["name"]: m for m in MANIFEST}

STATIC = [m["name"] for m in MANIFEST if m["kind"] == "cur"]
ANIM = [m["name"] for m in MANIFEST if m["kind"] == "ani"]

# author's 50 ms/frame cursors, resampled x3 to 60 fps (same cycle length):
# his keys on one still outline, splined between and paced by their change
INTERP = {"AppStarting", "Hand", "Wait"}
INTERP_N = 3
# the key whose outline carries the whole cycle: the medoid of the network's
# masters, all three 2 (lightanim.canonical_index before stage 6)
CANONICAL = {"AppStarting": 2, "Hand": 2, "Wait": 2}
_PACE_SOLID = 0.85       # of peak alpha: the glass whose motion sets the pace
_PACE_SAMPLES = 7        # points an interval is sampled at to invert its own pace

_VIS = 0.25              # visible zone: alpha above this fraction of the peak


def hotspot(name):
    f = BY_NAME[name]["frames"][0]
    return f["hx"], f["hy"]


def _key(name, idx=0):
    kind = BY_NAME[name]["kind"]
    return f"{kind}__{name}__{idx}"


@functools.lru_cache(maxsize=None)
def _orig(key):
    return np.asarray(Image.open(os.path.join(ORIG, key + ".png"))
                      .convert("RGBA"), dtype=np.float64)


def _resize(arr, size, filt=Image.LANCZOS):
    """Premultiplied Lanczos resize of an RGBA float array -> (rgb, a), done
    in linear light so translucent edges don't come out dark/soft."""
    if GPU.BACKEND == "gpu":
        from .gpu import stages
        got = stages.resize_rgba(arr, size, filt)
        if got is not None:
            return got
    a = arr[..., 3] / 255.0
    rgb_lin = V.srgb_to_linear(np.clip(arr[..., :3], 0, 255).astype(np.uint8))
    premult = rgb_lin * a[..., None]
    chans = [np.asarray(Image.fromarray(premult[..., c].astype(np.float32), mode="F")
                         .resize((size, size), filt), dtype=np.float64)
              for c in range(3)]
    oa = np.asarray(Image.fromarray(a.astype(np.float32), mode="F")
                     .resize((size, size), filt), dtype=np.float64)
    rgb_lin_out = np.dstack(chans) / np.maximum(oa, 1e-6)[..., None]
    rgb = V.linear_to_srgb(rgb_lin_out).astype(np.float64)
    return rgb, np.clip(oa, 0, 1) * 255.0


@functools.lru_cache(maxsize=None)
def _static_outline(name):
    """True where every frame of a cursor is traced to the same outline.

    Wait, Hand and AppStarting animate colour only - all nine keyframes carry an
    identical polygon, so anything derived from the outline is one answer for
    the whole cycle. Keyed per frame the build rasterised the same silhouette
    and rebuilt the same distance field 27 times per cursor. Verified bit-exact
    on all sixteen before being wired in; Handwriting and NO really do change
    shape and the same test excludes them."""
    fr = C.TRACED[name]["frames"]
    first = fr[0]["polys"]
    return all(f["polys"] == first for f in fr)


def _geom(name, idx):
    """The frame whose outline stands in for this one."""
    return 0 if _static_outline(name) else idx


@functools.lru_cache(maxsize=None)
def _mask_prims(name, idx):
    """The geometry the silhouette is drawn from, as primitives in logical
    units: ("dot", (cx, cy, r)) or ("poly", points).

    One place derives the contour, and everything that needs to know where the
    contour is asks here. It used to be derived twice: _mask_geom rounded the
    small islands and ran C.smooth, while _edge_distance_geom measured to the
    raw traced vertices. Two routes to one contour, and they disagreed - the
    distance field read zero up to a third of a logical unit away from where
    the silhouette actually got drawn, 5 px at 512 and 12 on SizeAll, wandering
    along the outline. Every band keyed off that field - the bevel rim, the
    edge shadow, the hole finder - was laid down beside the edge it was meant
    to sit on."""
    out = []
    for poly in C.TRACED[name]["frames"][idx]["polys"]:
        # A small round island is rendered as the circle it is: nine traced
        # vertices read as a circle at 32px and as an octagon at 512.
        if name in C.HELP_ROUND_ISLANDS and len(poly) <= 12:
            got = C._round_island(poly)
            if got is not None:
                out.append(("dot", got))
                continue
        out.append(("poly", tuple(C.smooth([tuple(p) for p in poly]))))
    return tuple(out)


@functools.lru_cache(maxsize=None)
def _mask_geom(name, idx, size):
    """Crisp silhouette from the traced outline, white on transparent."""
    white = (255, 255, 255, 255)
    prims = [{kind: geom, "fill": white}
             for kind, geom in _mask_prims(name, idx)]
    if GPU.BACKEND == "gpu":
        from .gpu import stages
        a = stages.mask_alpha(prims, size)
        if a is not None:
            return a.astype(np.float64)
    img = V.render(prims, size)
    return np.asarray(img, dtype=np.float64)[..., 3]


def _mask(name, idx, size):
    return _mask_geom(name, _geom(name, idx), size)


def _mean_sat(rgb, a):
    vis = a > _VIS * a.max()
    px = rgb[vis] / 255.0
    mx, mn = px.max(axis=1), px.min(axis=1)
    return float(np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0).mean())


def _sat_match(rgb, a, target, iters=2):
    """Scale chroma about luma so the mean saturation hits the target -
    Reinhard matches per-channel stats but leaves the AI's oversaturation."""
    for _ in range(iters):
        cur = _mean_sat(rgb, a)
        if cur < 1e-4:
            return rgb
        f = np.clip(target / cur, 0.6, 1.4)
        lum = rgb @ np.array([0.299, 0.587, 0.114])
        rgb = np.clip(lum[..., None] + (rgb - lum[..., None]) * f, 0, 255)
    return rgb


def _compose(rgb, alpha):
    out = np.dstack([np.clip(rgb, 0, 255), np.clip(alpha, 0, 255)])
    return Image.fromarray(out.round().astype(np.uint8), "RGBA")


_GHOST_LO = 10.0         # at or below this alpha (4% coverage) a pixel's own colour
_GHOST_HI = 24.0         # cannot be seen at all; it fades back in by here


def _pushpull(values, weight):
    """Fill every zero-weight pixel from the nearest weighted ones.

    Push-pull over an image pyramid: the weighted values are averaged down to a
    single pixel, then each level fills its own gaps from the level above it.
    A gap ends up holding an average of what surrounded it, in a handful of
    passes rather than hundreds of one-pixel steps."""

    def scale(arr, n):
        return np.asarray(Image.fromarray(arr.astype(np.float32), mode="F")
                          .resize((n, n), Image.BOX if n < arr.shape[0] else Image.BILINEAR),
                          dtype=np.float64)

    ch = values.shape[2]
    pyr = [(values * weight[..., None], weight)]
    while pyr[-1][1].shape[0] > 1:                       # push
        n = pyr[-1][1].shape[0] // 2
        p, w = pyr[-1]
        pyr.append((np.dstack([scale(p[..., c], n) for c in range(ch)]), scale(w, n)))
    for lo in range(len(pyr) - 1, 0, -1):                # pull
        p, w = pyr[lo]
        tp, tw = pyr[lo - 1]
        n = tw.shape[0]
        up_p = np.dstack([scale(p[..., c], n) for c in range(ch)])
        up_w = scale(w, n)
        gap = (tw <= 1e-4)[..., None]
        pyr[lo - 1] = (np.where(gap, up_p, tp),
                       np.where(gap[..., 0], np.maximum(up_w, 1e-6), tw))
    p, w = pyr[0]
    return np.nan_to_num(p / np.maximum(w, 1e-9)[..., None])


def _bleed(rgb, alpha):
    """Colour carried outward from the silhouette into the transparent zone."""
    return np.clip(_pushpull(np.clip(rgb, 0, 255),
                             np.clip(alpha, 0, 255) / 255.0), 0, 255)


@functools.lru_cache(maxsize=None)
def _ghost(name, size):
    """One colour field for everything the cursor does not cover, shared by
    every frame of it.

    Nothing composites it - alpha is zero there - but it is not free to be
    anything. _lerp reconstructs colour by dividing premultiplied values by an
    alpha of 1e-6, which turns whatever noise sits outside the silhouette into
    a different arbitrary colour in every interpolated frame: measured on the
    shipped animations, the keyframes and their tweens disagreed by 23..53
    levels out there, while inside they differ by 3.7. Renderers that scale or
    filter a frame before compositing it pull that colour back in as a fringe,
    and it costs a real amount of DIB to store. Freezing it per cursor makes
    those frames agree exactly. Bled out of frame 0's own glass."""
    a = np.asarray(frame_image(name, 0, size), dtype=np.float64)
    return _bleed(a[..., :3], a[..., 3] / 255.0)


def _hide_ghost(im, name, size):
    """Replace the unseeable colour with the cursor's frozen field."""
    a = np.asarray(im, dtype=np.float64)
    w = np.clip((a[..., 3] - _GHOST_LO) / (_GHOST_HI - _GHOST_LO), 0.0, 1.0)[..., None]
    return _compose(a[..., :3] * w + _ghost(name, size) * (1.0 - w), a[..., 3])


_TIP_COS = -0.17         # cos of the widest interior angle (100 deg) still a point
@functools.lru_cache(maxsize=None)
def _sharp_corners(name, idx):
    """Convex points of the traced outline, in logical units.

    Convex and sharp only: a concave notch has no point to converge, and the
    blunt vertices where two edges merely bend are not points either."""
    out = []
    for poly in C.TRACED[name]["frames"][idx]["polys"]:
        pts = np.array([(p[0], p[1]) for p in poly], dtype=np.float64)
        m = len(pts)
        if m < 3:
            continue
        nxt = np.roll(pts, -1, axis=0)
        area = float((pts[:, 0] * nxt[:, 1] - pts[:, 1] * nxt[:, 0]).sum())
        for i, p in enumerate(poly):
            if not p[2]:
                continue
            a, b = pts[(i - 1) % m] - pts[i], pts[(i + 1) % m] - pts[i]
            na, nb = np.hypot(*a), np.hypot(*b)
            if na < 1e-6 or nb < 1e-6:
                continue
            a, b = a / na, b / nb
            if (a[0] * b[1] - a[1] * b[0]) * area > 0 or float(a @ b) < _TIP_COS:
                continue
            out.append((float(p[0]), float(p[1])))
    return tuple(out)


def _sample(rgb, sx, sy):
    """Bilinear lookup of rgb at float coordinates, edge-clamped."""
    n = rgb.shape[0]
    sx = np.clip(sx, 0, n - 1.001)
    sy = np.clip(sy, 0, n - 1.001)
    x0, y0 = sx.astype(np.int32), sy.astype(np.int32)
    fx, fy = (sx - x0)[..., None], (sy - y0)[..., None]
    x1, y1 = np.minimum(x0 + 1, n - 1), np.minimum(y0 + 1, n - 1)
    return ((rgb[y0, x0] * (1 - fx) + rgb[y0, x1] * fx) * (1 - fy)
            + (rgb[y1, x0] * (1 - fx) + rgb[y1, x1] * fx) * fy)


_FOLD_CAP = 1.2          # most it may be moved
_FOLD_MIN_DEPTH = 2.0    # concavity that counts as the tail junction
_FOLD_MIN_SPAN = 8.0     # shortest chord worth straightening
# Help draws Arrow's pointer (trace.borrow_outline) and its "?" covers the
# notch, so the deepest departure from the hull is the hook's junction, 4.0
# units from it. The author's fold runs from the point toward Arrow's notch:
# read along Help's own chord its centre drifted -0.6 -> -3.2 units off the
# line. His Help is Arrow pixel for pixel along Arrow's chord (0-1 levels) up
# to where the hook crosses it, and the fold ends there.
_FOLD_CHORD_OF = {"Help": "Arrow"}
_FOLD_COVER_TOL = 32.0   # levels his frame departs from the donor's under the hook


def _hull(pts):
    pts = sorted(map(tuple, pts))

    def half(ps):
        h = []
        for p in ps:
            while len(h) > 1 and ((h[-1][0] - h[-2][0]) * (p[1] - h[-2][1])
                                  - (h[-1][1] - h[-2][1]) * (p[0] - h[-2][0])) <= 0:
                h.pop()
            h.append(p)
        return h

    return half(pts)[:-1] + half(pts[::-1])[:-1]


@functools.lru_cache(maxsize=None)
def _fold_chord(name, idx):
    """The line the cursor's main fold is supposed to lie on.

    On the author's frames the fold that splits the glass runs dead straight
    from the point to the notch between the tails, and both ends are in the
    traced outline already: the point is a convex corner, the notch is the
    outline's deepest departure from its own convex hull. Nothing is chosen by
    hand, except where the notch is drawn over (_FOLD_CHORD_OF)."""
    if name in _FOLD_CHORD_OF:
        return _covered_chord(name, _FOLD_CHORD_OF[name])
    best = None
    for poly in C.TRACED[name]["frames"][idx]["polys"]:
        pts = np.array([(p[0], p[1]) for p in poly], dtype=np.float64)
        if len(pts) < 8:
            continue
        hull = np.array(_hull(pts))
        if len(hull) < 3:
            continue
        depth, notch = 0.0, None
        for p in pts:
            d = np.inf
            for i in range(len(hull)):
                a, b = hull[i], hull[(i + 1) % len(hull)]
                ab = b - a
                t = np.clip(float((p - a) @ ab) / max(float(ab @ ab), 1e-9), 0.0, 1.0)
                d = min(d, float(np.hypot(*(p - (a + t * ab)))))
            if d > depth:
                depth, notch = d, p
        if notch is None or depth < _FOLD_MIN_DEPTH:
            continue
        tips = _sharp_corners(name, idx)
        if not tips:
            continue
        tip = max(tips, key=lambda q: np.hypot(q[0] - notch[0], q[1] - notch[1]))
        span = float(np.hypot(tip[0] - notch[0], tip[1] - notch[1]))
        if span < _FOLD_MIN_SPAN:
            continue
        if best is None or span > best[0]:
            best = (span, (float(tip[0]), float(tip[1])), (float(notch[0]), float(notch[1])))
    return None if best is None else (best[1], best[2])


def _covered_chord(name, donor):
    """The donor's chord, from its point up to the first of the author's own
    pixels that departs from the donor's frame.

    Without the stop the chord ran on under the hook to Arrow's notch, and
    _fold_restep drew the fold 72 levels deep into the "?" past where it ends
    (selftest `restep stops with the fold`)."""
    ch = _fold_chord(donor, 0)
    if ch is None:
        return None
    (x0, y0), (x1, y1) = ch
    diff = np.abs(np.asarray(original(name, 0), np.float64)
                  - np.asarray(original(donor, 0), np.float64)).max(-1)
    n = int(np.ceil(np.hypot(x1 - x0, y1 - y0) * 16))
    for i in range(1, n + 1):
        x, y = x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n
        py, px = min(int(y), diff.shape[0] - 1), min(int(x), diff.shape[1] - 1)
        if diff[py, px] >= _FOLD_COVER_TOL:
            return (x0, y0), (round(x, 2), round(y, 2))
    return ch


def original(name, idx):
    """The author's original 32px frame, byte for byte - the reference the
    superiority metrics and the 2006-vs-remaster comparison are measured against."""
    return Image.open(os.path.join(ORIG, _key(name, idx) + ".png")).convert("RGBA")


_BEVEL_REF = 512         # size the distance field is measured at, once


def _chamfer(inside):
    """Distance to the outside of `inside`, in pixels.

    Two raster passes with a (1, sqrt2) chamfer. The left-to-right step inside a
    row is a running minimum of d[k] + (x - k), which is (d[k] - k) plus x, so
    numpy's accumulate does it in one call instead of a Python loop; the same
    trick backwards covers right-to-left. A plain minimum filter was tried first
    and steps by exactly one in eight directions, which builds an octagonal,
    staircased field - its gradient then draws a diagonal hatch straight across
    the facets."""
    big = float(inside.shape[0] * 4)
    d = np.where(inside, big, 0.0)
    n = d.shape[1]
    idx = np.arange(n, dtype=np.float64)
    diag = np.sqrt(2.0)

    def scan(rows, step):
        for y in rows:
            ny = y - step
            prev = d[ny] if 0 <= ny < d.shape[0] else None
            if prev is not None:
                cand = prev + 1.0
                cand[1:] = np.minimum(cand[1:], prev[:-1] + diag)
                cand[:-1] = np.minimum(cand[:-1], prev[1:] + diag)
                d[y] = np.minimum(d[y], cand)
            row = d[y]
            row = np.minimum(row, np.minimum.accumulate(row - idx) + idx)
            rev = row[::-1]
            row = np.minimum(row, (np.minimum.accumulate(rev - idx) + idx)[::-1])
            d[y] = row

    scan(range(1, d.shape[0]), 1)
    scan(range(d.shape[0] - 2, -1, -1), -1)
    return d


def _edge_distance(name, idx):
    """Depth inside the silhouette at _BEVEL_REF, zero outside."""
    return np.maximum(_edge_distance_geom(name, _geom(name, idx)), 0.0)


@functools.lru_cache(maxsize=None)
def _edge_distance_at(name, idx, size):
    """The same field at `size`, resampled from the one measured at _BEVEL_REF.

    Resamples the *signed* field and clips afterwards, which is not the order
    the five call sites used to do it in. Depth-with-a-floor is convex at the
    contour - it falls to zero and stays there - so interpolating it between a
    pixel just inside and one just outside averages a positive against a zero
    and returns something positive, and the field's own zero drifts inward by
    about half of whatever the step is. Signed distance is linear straight
    through the contour, so the same interpolation lands on the contour.
    Measured on Arrow at 512: the field's zero sits 0.0097 logical units off
    the drawn edge clipped, 0.0042 signed.

    Cached per size for the same reason _mask_geom is: the build asks for the
    same rung of the same frame from five different stages."""
    d = _edge_distance_geom(name, _geom(name, idx))
    if d.shape[0] != size:
        d = np.asarray(Image.fromarray(d.astype(np.float32), mode="F")
                       .resize((size, size), Image.BILINEAR), dtype=np.float64)
    return np.maximum(d, 0.0)


@functools.lru_cache(maxsize=None)
def _edge_distance_geom(name, idx):
    """Distance from every interior pixel to the silhouette's edge, in logical
    units, measured once at _BEVEL_REF and resampled from there.

    Exact, from the traced segments themselves, when there are any. A chamfer
    on the rasterised mask grows in steps of 1 and sqrt2, so the field carries a
    fine terracing; differentiating it to light the bevel turns that terracing
    into a speckled crest along the medial ridge - the fold came out as a dotted
    line rather than a drawn one. The distance to a line segment is a closed
    form, so there is no reason to approximate it.

    Measured to _mask_prims, the same geometry the silhouette is rasterised
    from. Measuring to the raw traced vertices instead put the zero of this
    field up to a third of a unit off the edge the mask actually draws, and on
    SizeAll three quarters of one.

    Signed: positive inside, negative outside. Callers that want depth take
    _edge_distance or _edge_distance_at, both of which clip - and the clip has
    to happen after any resampling, which is the whole reason the sign is kept
    this far."""
    size = _BEVEL_REF
    inside = _mask(name, idx, size) > 127
    prims = _mask_prims(name, idx) if name in C.TRACED else ()
    if not prims:
        c = _chamfer(inside) / (size / V.LOGICAL)
        return np.where(inside, c, -c)
    if GPU.BACKEND == "gpu":
        from .gpu import stages
        return stages.edge_distance(prims, inside, size, V.LOGICAL)
    L = size / V.LOGICAL
    ys, xs = np.mgrid[0:size, 0:size]
    px, py = (xs + 0.5) / L, (ys + 0.5) / L
    best = np.full((size, size), np.inf)
    for kind, geom in prims:
        if kind == "dot":
            cx, cy, r = geom
            best = np.minimum(best, np.abs(np.hypot(px - cx, py - cy) - r))
            continue
        pts = np.array([(p[0], p[1]) for p in geom], dtype=np.float64)
        for i in range(len(pts)):
            a, b = pts[i], pts[(i + 1) % len(pts)]
            ab = b - a
            den = float(ab @ ab)
            if den < 1e-12:
                continue
            t = np.clip(((px - a[0]) * ab[0] + (py - a[1]) * ab[1]) / den, 0.0, 1.0)
            best = np.minimum(best, np.hypot(px - (a[0] + t * ab[0]),
                                             py - (a[1] + t * ab[1])))
    return np.where(inside, best, -best)


def _box1(a, r, axis):
    """Running mean of width 2r+1 along one axis, edge-clamped, via cumsum."""
    a = np.swapaxes(a, 0, axis)
    pad = np.concatenate([np.repeat(a[:1], r, 0), a, np.repeat(a[-1:], r, 0)], 0)
    c = np.cumsum(pad, 0)
    out = (c[2 * r:] - np.concatenate([np.zeros_like(c[:1]), c[:-2 * r - 1]], 0)) \
        / (2.0 * r + 1.0)
    return np.swapaxes(out, 0, axis)


def _smooth1(a, unit, size):
    """Blur a single-channel float field by `unit` logical units.

    Three box passes each way, which is close enough to a Gaussian and costs
    four cumulative sums. This used to downsample to a small grid with BOX and
    come back up with BILINEAR: cheap, but the result is built out of blocks,
    and lighting a bevel through it turned the fold into a visible staircase -
    asking for more smoothing made the steps bigger rather than the line
    smoother."""
    r = max(0, int(round(unit * size / V.LOGICAL / 3.0)))
    if r < 1:
        return a.astype(np.float64)
    if GPU.BACKEND == "gpu" and a.shape[0] >= _GPU_SMOOTH_MIN:
        from .gpu import ops
        return ops.smooth1(ops.t(a), unit, size).cpu().numpy()
    out = a.astype(np.float64)
    for _ in range(3):
        out = _box1(_box1(out, r, 0), r, 1)
    return out


_GPU_SMOOTH_MIN = 256        # side from which a blur is worth the trip to the device


# --- NO's prohibition sign: a template, not a drawing ---
#
# Measured on the author's own frames 2026-08-22 (NEXT.md 52, 53). His ring is a
# circle to 0.04 logical units rms, centred on (15.93, 16.02) to a thousandth on
# every frame that carries one, and its stroke is one flat colour - Lab 46.8 /
# 85.2 / 38.0, the same on the ring and on the bar across frames 7 to 10. Ours
# is 0.15 short in radius, 18% thin in the stroke, twice as lumpy (the chord
# error of a 24-vertex polygon on a circle of radius 8), and 8.3 units of chroma
# too saturated.
#
# The two defects are not independent and this stage owns both. Fixing either
# alone measurably makes the frame worse: the over-saturated red compensates for
# the under-coverage, because a thin stroke lets the background dilute a colour
# that is too strong. Coverage alone scores 7.749 against 6.413 for doing
# nothing, colour alone 7.653, the pair 5.768. There is deliberately no
# configuration of this renderer that has one without the other.
_NO_RING = {"NO"}
_RING_RMS = 0.10         # circularity his own art has to reach to be redrawn.
                         # His frames 7..10 read 0.035..0.047. Frame 6 reads
                         # 0.256, but that is the pointer under the sign read
                         # as ring: on his red alone it is 0.050. The template
                         # there still scores worse (NEXT.md 94), so it stays off
_RING_BAR = 1.30         # the bar's width in ring widths, on his 45 degrees
                         # through the ring's centre: across his bar at half
                         # height frames 8 and 10 read 1.30 and 1.25. At 1.17
                         # (red area over the chord) frame 8 lost a pixel a row
                         # at 32 and morph_iou fell 0.359 -> 0.311. Left to the
                         # master the bar came through the hole soft, 0.3 LU of
                         # red feather each side and 42.75 degrees, beside a
                         # ring drawn to one device pixel


def _last_true(mask):
    """Per row, the index of the last True and whether there is one."""
    n = mask.shape[1]
    return n - 1 - np.argmax(mask[:, ::-1], axis=1), mask.any(1)


def _ring_levels(a, cx, cy, angs, level, lo, hi, step=0.01):
    """_ring_level for every ray at once: the samples are per point, so each
    row is the numbers the scalar version computed for that ray."""
    r = np.arange(lo, hi, step)
    n = a.shape[0]
    v = _sample1(a, (cx + r[None, :] * np.cos(angs)[:, None]) * n / V.LOGICAL - 0.5,
                 (cy + r[None, :] * np.sin(angs)[:, None]) * n / V.LOGICAL - 0.5)
    i, found = _last_true(v >= level)
    found &= i + 1 < len(r)
    i = np.where(found, i, 0)
    rows = np.arange(len(angs))
    vi, vn = v[rows, i], v[rows, np.minimum(i + 1, len(r) - 1)]
    out = r[i] + step * (vi - level) / np.maximum(1e-9, vi - vn)
    return np.where(found, out, np.nan)


def _ring_kasa(x, y):
    m = np.c_[2 * x, 2 * y, np.ones(len(x))]
    cx, cy, c = np.linalg.lstsq(m, x * x + y * y, rcond=None)[0]
    return float(cx), float(cy), float(np.sqrt(c + cx * cx + cy * cy))


@functools.lru_cache(maxsize=None)
def _ring_fit(name, idx):
    """(cx, cy, R, r) of the prohibition ring, or None if this frame has none.

    Read off the author's 32px alpha, once, the same way tools/fold_tracker
    reads a fold: the half-maximum crossing along a ray is a subpixel edge, and
    360 of them fit a circle to a hundredth of a logical unit even on art this
    small. Rejection is on the residual after a fit rather than on the raw
    radius - the pointer covers forty degrees at twice the ring's radius, and a
    spread test around the median leaves most of it in."""
    if name not in _NO_RING:
        return None
    a = np.asarray(original(name, idx), dtype=np.float64)[..., 3]
    if a.max() < 1.0:
        return None
    lev = 0.5 * float(a.max())
    ys, xs = np.nonzero(a > 0.8 * a.max())
    cx, cy = float(xs.mean()) + 0.5, float(ys.mean()) + 0.5
    ang = np.linspace(0.0, 2.0 * np.pi, 360, endpoint=False)
    keep = rs = None
    for _ in range(12):
        rs = _ring_levels(a, cx, cy, ang, lev, 2.0, 15.0)
        keep = np.isfinite(rs)
        if keep.sum() < 40:
            return None
        for _ in range(8):
            nx, ny, R = _ring_kasa(cx + rs[keep] * np.cos(ang[keep]),
                                   cy + rs[keep] * np.sin(ang[keep]))
            e = np.hypot(cx + rs * np.cos(ang) - nx,
                         cy + rs * np.sin(ang) - ny) - R
            med = np.median(e[keep])
            mad = np.median(np.abs(e[keep] - med)) + 1e-9
            new = np.isfinite(rs) & (np.abs(e - med) < 2.5 * 1.4826 * mad)
            if new.sum() < 20 or (new == keep).all():
                break
            keep = new
        cx, cy = nx, ny
    e = np.hypot(cx + rs[keep] * np.cos(ang[keep]) - cx,
                 cy + rs[keep] * np.sin(ang[keep]) - cy) - R
    if float(e.std()) > _RING_RMS:
        return None
    # inward from the outer edge to where his material stops: the stroke's width
    # arange(0.2, ro, .01) is a prefix of the one to the largest ro: the rays
    # share a grid and each keeps its own length
    tk, rk = ang[keep], rs[keep]
    q = np.arange(0.2, float(rk.max()), 0.01)
    ln = np.array([len(np.arange(0.2, ro, 0.01)) for ro in rk])
    v = _sample1(a, (cx + q[None, :] * np.cos(tk)[:, None]) * a.shape[0] / V.LOGICAL - 0.5,
                 (cy + q[None, :] * np.sin(tk)[:, None]) * a.shape[0] / V.LOGICAL - 0.5)
    below = (v < lev) & (np.arange(len(q))[None, :] < ln[:, None])
    j, found = _last_true(below)
    found &= j + 1 < ln
    j = np.where(found, j, 0)
    rows = np.arange(len(tk))
    vj, vn = v[rows, j], v[rows, np.minimum(j + 1, len(q) - 1)]
    inner = (q[j] + 0.01 * (lev - vj) / np.maximum(1e-9, vn - vj))[found]
    if len(inner) < 20:
        return None
    return (cx, cy, R, float(np.median(inner)))


_HELP_GLYPH_DIP = 25.0     # levels his Help sits below his Arrow on white where
                           # the "?" is cut; their outlines are one drawing
_HELP_GLYPH_MARGIN = 0.4   # LU the sign is grown by, and faded over again


@functools.lru_cache(maxsize=None)
def _help_glyph(name, idx, size):
    """How much of each pixel Help's "?" owns, 0..1; None off Help.

    The right arm of the bowl runs down a unit or two in from the outline, in
    _edge_shadow_declutter's band, and the closing took it for the master's
    second crease and lifted it to the rim's light: the bowl stood open on the
    right, ending in a beak (NEXT.md 157). Read off his own art as where his
    Help is darker than his Arrow."""
    if name != "Help":
        return None

    def lum(n):
        rgb, a = _resize(_orig(_key(n, idx)), V.LOGICAL)
        a = a / 255.0
        return rgb.mean(-1) * a + 255.0 * (1.0 - a)

    m = ((lum("Help") - lum("Arrow")) < -_HELP_GLYPH_DIP).astype(np.float32)
    up = np.asarray(Image.fromarray(m, mode="F").resize((size, size), Image.BILINEAR),
                    dtype=np.float64)
    grown = (_smooth1(up, _HELP_GLYPH_MARGIN, size) > 0.05).astype(np.float64)
    return np.clip(_smooth1(grown, 0.5 * _HELP_GLYPH_MARGIN, size), 0.0, 1.0)


def _sample1(field, x, y):
    """_sample for a single-channel field."""
    return _sample(field[..., None], x, y)[..., 0]


def _median(a):
    """np.median of a short 1-d array, the same number (a sort and the middle
    one or the mean of the middle two) without np.median's call overhead, which
    for the few-dozen-sample arrays of the fits is most of its cost."""
    a = np.asarray(a)
    n = a.size
    if n == 0 or n > 4096 or a.dtype.kind != "f":
        return float(np.median(a))
    s = np.sort(a, axis=None)
    if np.isnan(s[-1]):
        return float("nan")
    h = n >> 1
    return float(s[h]) if n & 1 else float((s[h - 1] + s[h]) / 2.0)


@functools.lru_cache(maxsize=None)
def _landmarks(name, idx):
    """(A, B, J, C) in logical units: the point, the two tails, the notch.

    Not hand-listed. A and J are the ends of the fold chord the tracer already
    finds (_fold_chord); B and C are the other two convex points, sorted by
    which side of that chord they fall on. The structure of an arrow is four
    points and one interior edge, and all four are already in the outline."""
    ch = _fold_chord(name, idx)
    if ch is None:
        return None
    a = np.array(ch[0], dtype=np.float64)
    j = np.array(ch[1], dtype=np.float64)
    d = (j - a) / max(float(np.hypot(*(j - a))), 1e-9)
    nv = np.array([-d[1], d[0]])
    rest = [np.array(p, dtype=np.float64) for p in _sharp_corners(name, idx)
            if float(np.hypot(*(np.array(p) - a))) > 1e-6]
    if len(rest) < 2:
        return None
    side = [float((p - a) @ nv) for p in rest]
    b = rest[int(np.argmax(side))]
    c = rest[int(np.argmin(side))]
    return (tuple(a), tuple(b), tuple(j), tuple(c))


def _disk_frame(kind, name, idx, size, make):
    """One build run's frames shared between its processes. CGR_FRAME_CACHE names
    a directory that cgr.build creates for the run and removes at its end: the
    warm-up workers write the frames, the quality gate's workers read them
    instead of rendering the same ladder again. Unset (everything else), this
    is just make()."""
    d = os.environ.get("CGR_FRAME_CACHE")
    if not d:
        return make()
    path = os.path.join(d, "%s_%s_%d_%d.npy" % (kind, name, idx, size))
    try:
        return Image.fromarray(np.load(path), "RGBA")
    except (OSError, ValueError):
        pass
    im = make()
    tmp = "%s.%d.tmp" % (path, os.getpid())
    try:
        with open(tmp, "wb") as fh:
            np.save(fh, np.asarray(im))
        os.replace(tmp, path)
    except OSError:
        pass
    return im


@functools.lru_cache(maxsize=None)
def frame_image(name, idx, size):
    """Final RGBA frame at any size (glass.frame_image, shared between a
    build's processes through _disk_frame)."""
    from . import glass
    return _disk_frame("f", name, idx, size, lambda: glass.frame_image(name, idx, size))


def _premult(im):
    """RGBA image -> premultiplied linear-light array, the space every temporal
    blend happens in (no dark fringes, no gamma-space midpoint dimming)."""
    a = np.asarray(im, dtype=np.float64)
    al = a[..., 3:4] / 255.0
    lin = V.srgb_to_linear(np.clip(a[..., :3], 0, 255).astype(np.uint8))
    return np.dstack([lin * al, al[..., 0]])


def _unpremult(m):
    al = np.clip(m[..., 3], 0.0, 1.0)
    rgb_lin = np.clip(m[..., :3], 0.0, None) / np.maximum(al, 1e-6)[..., None]
    return _compose(V.linear_to_srgb(rgb_lin).astype(np.float64), al * 255.0)


def _spline(p0, p1, p2, p3, t):
    """Catmull-Rom through four keyframes, in premultiplied linear light.

    A straight cross-fade traces a polyline through image space, and at each
    keyframe that polyline turns a corner: the frame either side of a keyframe
    differs from it more than two frames inside an interval do, which is a
    regular tick three times a cycle. Rounding the corner removes it.

    A cubic was tried once before and reverted, because at uniform t its
    apparent speed oscillates *inside* each interval - which it does. That is
    no longer how the frames are placed: anim_frames measures each interval's
    own pace and inverts it, so the curve is sampled where it moves evenly
    rather than where its parameter says it should."""
    a, b, c, d = (_premult(p) for p in (p0, p1, p2, p3))
    return _unpremult(0.5 * ((2 * b) + (-a + c) * t
                             + (2 * a - 5 * b + 4 * c - d) * t * t
                             + (-a + 3 * b - 3 * c + d) * t * t * t))


def anim_frames(name, size, interp=True):
    """_anim_frames, shared between the processes of one build run through the
    run's frame cache directory (see _disk_frame): the build's own animations
    and the quality gate's measurements ask for the same ones."""
    d = os.environ.get("CGR_FRAME_CACHE")
    if not d:
        return _anim_frames(name, size, interp)
    path = os.path.join(d, "anim_%s_%d_%d.npz" % (name, size, int(bool(interp))))
    try:
        with np.load(path) as z:
            return ([Image.fromarray(a, "RGBA") for a in z["frames"]], [int(r) for r in z["rates"]])
    except (OSError, ValueError, KeyError):
        pass
    frames, rates = _anim_frames(name, size, interp)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    try:
        with open(tmp, "wb") as fh:
            np.savez(fh, frames=np.stack([np.asarray(f) for f in frames]), rates=np.asarray(rates))
        os.replace(tmp, path)
    except OSError:
        pass
    return frames, rates


def _anim_frames(name, size, interp=True):
    """(frames, rates_jiffies) for an animated cursor at the given size.

    AppStarting/Hand/Wait: 27 cross-faded frames at rate 1 (60 fps) when
    interp is True - used for Windows .ani and the preview assets.
    Handwriting/NO: the author's frames and rate chunk verbatim
    (rate 1 with a freeze on the last frame), regardless of interp.

    interp=False returns the author's native ~20 fps cadence uninterpolated
    for AppStarting/Hand/Wait too - Xcursor (GNOME/Mutter) redraws the
    pointer on every frame swap with no compositor-side frame sync, and at
    a true 60 fps cadence that lands the swap out of phase with a 60 Hz
    panel's own refresh often enough to read as a visible flicker on the
    animated cursors; static ones never change so there's nothing to tear.

    The output frames are spaced evenly by how much the picture changes, not by
    keyframe index. The author's sheen does not sweep at a constant rate - the
    widest step of a cycle runs a quarter above its own average - and cutting
    each interval into three equal cross-fades preserves that unevenness
    exactly, so the sweep visibly hurries and dawdles. Placing all 27 frames at
    equal intervals of cumulative change spreads the motion out instead. Frame
    count and cycle length are untouched, so the .ani timing is unchanged."""
    frames, rates, _phases = _anim_paced(name, size, interp)
    return frames, rates


def anim_phases(name, size):
    """Where in the author's cycle each shipped frame sits: his frame j of n
    at j / n, the 27 paced frames between them by their own pacing."""
    return _anim_paced(name, size, True)[2]


# The glass keys move the light along the rim only: the median body pixel
# swung 2 levels a cycle against his 9-16, and in the Pointers preview the
# sweep read as a flicker of the edge (owner, 2026-10-27). His own swing is laid
# over the body, x1 by the owner's pick of x1/x2/x3.
_BODY_PULSE = {"Wait", "AppStarting"}


def _body_pulse(name, keys, size):
    """keys + his frame minus his cycle mean, premultiplied, resized to `size`
    and held inside where every frame of his is solid, so his antialias does
    not touch our edge."""
    his = []
    for i in range(len(keys)):
        o = np.asarray(original(name, i).convert("RGBA"), dtype=np.float64) / 255
        pre = np.dstack([o[..., :3] * o[..., 3:], o[..., 3]])
        his.append(np.dstack([np.asarray(Image.fromarray(np.float32(pre[..., c])).resize(
            (size, size), Image.BICUBIC)) for c in range(4)]))
    mean = np.mean([h[..., :3] for h in his], 0)
    solid = np.clip(np.min([h[..., 3] for h in his], 0), 0, 1)[..., None]
    out = []
    for k, h in zip(keys, his):
        a = np.asarray(k, dtype=np.float64) / 255
        al = a[..., 3:]
        pre = a[..., :3] * al + (h[..., :3] - mean) * solid * al
        # under zero alpha keep _hide_ghost's fill, which the spline reads
        rgb = np.where(al > 0, pre / np.maximum(al, 1e-6), a[..., :3])
        out.append(Image.fromarray((np.dstack([rgb, al]).clip(0, 1) * 255).round().astype(np.uint8), "RGBA"))
    return out


def _anim_paced(name, size, interp):
    """(frames, rates, phases): anim_frames with each frame's place in the
    cycle. Not cached: 27 frames a size held for the run cost a worker
    hundreds of MB."""
    n = len(BY_NAME[name]["frames"])
    if name in INTERP:
        # one outline still, each key his tone of that frame on it; the
        # master's light laid over the glass read as smudges on the rim
        from . import glass
        still = CANONICAL[name]
        base = [_hide_ghost(glass.key_frame_image(name, still, i, size), name, size) for i in range(n)]
        if name in _BODY_PULSE:
            base = _body_pulse(name, base, size)
    else:
        # NO's wipe runs a soft front across the hole each frame, and the
        # colour under its barely covered edge jumped with it (ghost_rgb)
        base = [_hide_ghost(frame_image(name, i, size), name, size) for i in range(n)]
    if name not in INTERP or not interp:
        return base, list(BY_NAME[name]["rates"]), [i / float(n) for i in range(n)]
    arr = [np.asarray(f, dtype=np.float64) for f in base]
    peak = max(float(x[..., 3].max()) for x in arr)

    def moved(a, b):                     # how much the glass itself changed
        m = (a[..., 3] > _PACE_SOLID * peak) & (b[..., 3] > _PACE_SOLID * peak)
        return float(np.abs(a[..., :3][m] - b[..., :3][m]).mean()) if m.sum() else 0.0

    # Distance is measured along each interval too, not just between keyframes:
    # a cross-fade run at equal t does not change the picture at an equal rate,
    # because the blend is linear in premultiplied linear light and the eye (and
    # the metric) reads sRGB. Sampling the interval and inverting its own
    # distance curve is what actually evens the pace out.
    def at(i, t):
        return _spline(base[(i - 1) % n], base[i], base[(i + 1) % n], base[(i + 2) % n], t)

    curves = []
    for i in range(n):
        ts = np.linspace(0.0, 1.0, _PACE_SAMPLES)
        mid = [arr[i]] + [np.asarray(at(i, t), dtype=np.float64)
                          for t in ts[1:-1]] + [arr[(i + 1) % n]]
        d = np.array([moved(mid[k], mid[k + 1]) for k in range(len(mid) - 1)])
        curves.append((ts, np.concatenate([[0.0], np.cumsum(d)])))
    step = np.array([c[1][-1] for c in curves])
    if step.sum() < 1e-9:
        step = np.ones(n)
        curves = [(np.linspace(0, 1, _PACE_SAMPLES), np.linspace(0, 1, _PACE_SAMPLES))
                  for _ in range(n)]
    edge = np.concatenate([[0.0], np.cumsum(step)])      # distance at each keyframe
    total = edge[-1]
    out, phases = [], []
    for k in range(n * INTERP_N):
        want = k * total / (n * INTERP_N)
        i = min(int(np.searchsorted(edge, want, side="right")) - 1, n - 1)
        ts, cum = curves[i]
        t = float(np.interp(want - edge[i], cum, ts))
        out.append(base[i] if t <= 1e-6 else _hide_ghost(at(i, t), name, size))
        phases.append((i + t) / n)
    return out, [1] * len(out), phases

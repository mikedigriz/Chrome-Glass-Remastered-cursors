"""Hybrid frame pipeline: an AI colour master inside a vector-crisp edge.

Per frame:
  colour - a native src/ai512 master from an illustration-tuned Real-ESRGAN
           (anime_6B), Reinhard-anchored to the original 32px frame's
           per-channel stats. Every cursor uses it, grey glass included: the
           anime model keeps flat glass clean instead of speckling it, so there
           is no pale-cursor bypass. Crispness is one deterministic unsharp at
           the anchor, its dark overshoot damped so glass folds soften rather
           than blacken; smaller sizes downsample the sharpened master.
  alpha  - (vector mask / 255) x an AI alpha master (src/aialpha, blended with
           a plain Lanczos): the original's translucency inside a crisp traced
           silhouette, at any size.
  sat    - anchored at the shipped size to the original's level x1.05.

Animated cursors that the author drew at 50 ms/frame (AppStarting, Hand,
Wait) are cross-fade interpolated x3 to 60 fps - same cycle length, three
times smoother.  Handwriting and NO already run at 60 fps with a freeze on
the last frame; their frames and rate chunks ship unchanged.
"""
import functools, json, os
import numpy as np
from PIL import Image, ImageFilter

import cursors as C
import vectorlib as V

HERE = os.path.dirname(os.path.abspath(__file__))
ORIG = os.path.join(HERE, "src", "orig")
AI = os.path.join(HERE, "src", "ai")

MANIFEST = json.load(open(os.path.join(HERE, "src", "manifest.json")))
BY_NAME = {m["name"]: m for m in MANIFEST}

STATIC = [m["name"] for m in MANIFEST if m["kind"] == "cur"]
ANIM = [m["name"] for m in MANIFEST if m["kind"] == "ani"]

# author's 50 ms/frame cursors, cross-faded x3 to 60 fps (same cycle length)
INTERP = {"AppStarting", "Hand", "Wait"}
INTERP_N = 3
_PACE_SOLID = 0.85       # of peak alpha: the glass whose motion sets the pace
_PACE_SAMPLES = 7        # points an interval is sampled at to invert its own pace

_VIS = 0.25              # visible zone: alpha above this fraction of the peak
_BLEND_AI = 0.73         # weight of the AI alpha master vs plain Lanczos (_up_alpha).
                         # Window: the anime alpha runs thinner than the Lanczos on
                         # the pencil, so Handwriting[7] drift falls as this rises,
                         # while NO[10] drifts negative past ~0.75 - 0.73 clears both
                         # at the native 512px anchor too (check_metrics now checks
                         # both 128 and native; 0.72 cleared 128 but missed 512 by
                         # 0.5pt, 0.74+ clears 512 but pushes NO[10]@128 past -8%).


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


@functools.lru_cache(maxsize=None)
def _ai(key):
    return np.asarray(Image.open(os.path.join(AI, key + ".png"))
                      .convert("RGBA"), dtype=np.float64)


def _resize(arr, size):
    """Premultiplied Lanczos resize of an RGBA float array -> (rgb, a), done
    in linear light so translucent edges don't come out dark/soft."""
    a = arr[..., 3] / 255.0
    rgb_lin = V.srgb_to_linear(np.clip(arr[..., :3], 0, 255).astype(np.uint8))
    premult = rgb_lin * a[..., None]
    chans = [np.asarray(Image.fromarray(premult[..., c].astype(np.float32), mode="F")
                         .resize((size, size), Image.LANCZOS), dtype=np.float64)
              for c in range(3)]
    oa = np.asarray(Image.fromarray(a.astype(np.float32), mode="F")
                     .resize((size, size), Image.LANCZOS), dtype=np.float64)
    rgb_lin_out = np.dstack(chans) / np.maximum(oa, 1e-6)[..., None]
    rgb = V.linear_to_srgb(rgb_lin_out).astype(np.float64)
    return rgb, np.clip(oa, 0, 1) * 255.0


@functools.lru_cache(maxsize=None)
def _mask(name, idx, size):
    """Crisp silhouette from the traced outline, white on transparent."""
    fr = C.TRACED[name]["frames"][idx]
    white = (255, 255, 255, 255)
    prims = []
    for poly in fr["polys"]:
        # A small round island is rendered as the circle it is: nine traced
        # vertices read as a circle at 32px and as an octagon at 512.
        if name in C.HELP_ROUND_ISLANDS and len(poly) <= 12:
            got = C._round_island(poly)
            if got is not None:
                prims.append({"dot": got, "fill": white})
                continue
        prims.append({"poly": C.smooth([tuple(p) for p in poly]), "fill": white})
    img = V.render(prims, size)
    return np.asarray(img, dtype=np.float64)[..., 3]


def _stats(rgb, a):
    vis = a > _VIS * a.max()
    px = rgb[vis]
    return px.mean(axis=0), px.std(axis=0) + 1e-6


def _reinhard(rgb, a, ref_rgb, ref_a):
    """Per-channel mean/std transfer over the visible zone."""
    mu, sd = _stats(rgb, a)
    rmu, rsd = _stats(ref_rgb, ref_a)
    return np.clip((rgb - mu) / sd * rsd + rmu, 0, 255)


def _unsharp(rgb, radius=1.6, percent=55, dark=1.0):
    """Sharpen the colour channels only - alpha stays native. radius scales with
    the working resolution so a 512px frame gets the same perceptual crispness a
    128px frame gets at radius 1.6.

    `dark` < 1 attenuates only the darkening half of the overshoot: the bright
    glass highlights keep full crispness while the fold lines soften, instead of
    the symmetric mask deepening the anime edges into harsh black bends."""
    im = Image.fromarray(rgb.astype(np.uint8), "RGB")
    if dark >= 0.999:
        return np.asarray(im.filter(ImageFilter.UnsharpMask(
            radius=radius, percent=percent, threshold=2)), dtype=np.float64)
    blur = np.asarray(im.filter(ImageFilter.GaussianBlur(radius)), dtype=np.float64)
    hp = rgb - blur
    hp = np.where(hp < 0, hp * dark, hp)                    # soften the dark side only
    return np.clip(rgb + (percent / 100.0) * hp, 0, 255)


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


@functools.lru_cache(maxsize=None)
def _base128(name, idx):
    """Processed 128px frame -> (rgb HxWx3, alpha HxW) float arrays.

    The anime_6B master keeps flat glass clean on every cursor (grey included),
    so unlike the photographic model there is no PALE/grey bypass and no
    chroma-gated blend to hide invented hatch noise: the AI colour is used whole,
    Reinhard-anchored to the original's per-channel stats. Sharpening lives in
    _master (once, at the anchor), so this 128 base stays clean and the 512 net
    upscales an unsharpened source instead of compounding two sharpen passes."""
    key = _key(name, idx)
    orig = _orig(key)
    _, up_a = _resize(orig, 128)
    alpha = _mask(name, idx, 128) / 255.0 * up_a
    orig_sat = _mean_sat(orig[..., :3], orig[..., 3])
    ai = _ai(key)
    rgb = _reinhard(ai[..., :3], ai[..., 3], orig[..., :3], orig[..., 3])
    if orig_sat >= 0.05:                                    # anchor the colour cursors
        rgb = _sat_match(rgb, alpha, orig_sat * 1.05)
    return rgb, alpha


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
    those frames agree exactly."""
    idx = 0
    key = _key(name, idx)
    m_rgb, anchor = _master(name, idx)
    _, m_a = _resize(_orig(key), anchor)
    rgb = m_rgb if size == anchor else _resize(np.dstack([m_rgb, m_a]), size)[0]
    return _bleed(rgb, _mask(name, idx, size) / 255.0 * _up_alpha(name, idx, size))


def _hide_ghost(im, name, size):
    """Replace the unseeable colour with the cursor's frozen field."""
    a = np.asarray(im, dtype=np.float64)
    w = np.clip((a[..., 3] - _GHOST_LO) / (_GHOST_HI - _GHOST_LO), 0.0, 1.0)[..., None]
    return _compose(a[..., :3] * w + _ghost(name, size) * (1.0 - w), a[..., 3])


_LUMA = np.array([0.299, 0.587, 0.114])


def _dominant_hue_dir(rgb, a):
    """Unit chroma direction of the frame's own dominant colour, from pixels
    with real saturation (ignores near-grey noise). None for genuinely
    neutral cursors - nothing to anchor a hue correction to."""
    vis = a > _VIS * a.max()
    px = rgb[vis]
    if len(px) == 0:
        return None
    lum = px @ _LUMA
    chroma = px - lum[:, None]
    sat = np.linalg.norm(chroma, axis=1)
    if sat.max() < 8:
        return None
    strong = sat > np.percentile(sat, 70)
    mean_dir = chroma[strong].mean(axis=0)
    n = np.linalg.norm(mean_dir)
    return mean_dir / n if n > 1e-6 else None


def _declutter_hue_outliers(name, idx, rgb):
    """Real-ESRGAN is blind to alpha, and can invent a stray colour cast right
    at a high-contrast silhouette edge - Arrow_Down (blue glass) got a thin
    orange fringe tracing its whole outline, baked into the raw src/ai512
    master itself, where the original crease (and UpArrow's identical fold)
    is neutral grey. Any pixel with real chroma pointing well away from the
    frame's own dominant hue is such an outlier - desaturate it back toward
    its own luminance, feathered so the correction has no hard edge.
    Genuinely neutral cursors have no dominant hue to compare against and are
    left untouched."""
    ref_dir = _dominant_hue_dir(_orig(_key(name, idx))[..., :3], _orig(_key(name, idx))[..., 3])
    if ref_dir is None:
        return rgb
    lum = rgb @ _LUMA
    chroma = rgb - lum[..., None]
    sat = np.linalg.norm(chroma, axis=2)
    cos = np.zeros(sat.shape)
    nz = sat > 1e-6
    cos[nz] = (chroma[nz] @ ref_dir) / sat[nz]
    outlier = np.clip((sat - 10) / 30.0, 0, 1) * np.clip((0.3 - cos) / 0.6, 0, 1)
    # no blur here: outlier is already a smooth per-pixel function of sat/cos,
    # and blurring it would dilute exactly the worst case - a single hallucinated
    # pixel (e.g. AppStarting's tip) - below its own correction strength.
    return lum[..., None] + chroma * (1 - outlier)[..., None]


_ENGRAVED_DETAIL = {"Help"}   # see _declutter_engraved_detail


def _declutter_engraved_detail(name, idx, rgb, size):
    """Some AI colour masters hallucinate a second copy of a glyph that the AI
    alpha master already draws correctly through translucency alone - Help's
    "?" curl is one: the original defines it as a ~1px opacity dip (src/aialpha
    renders it as a clean single stroke), but the anime colour net, fed that
    same thin feature, paints an extra parallel fold beside it. Composited
    together, the two strokes read as one doubled, "melted" line.

    Wherever the alpha master has a strong *interior* gradient (away from the
    outer vector silhouette, a separate hard edge handled elsewhere) the glyph
    is already fully defined by translucency - flatten the colour there
    instead of trusting the net's invented linework, by blending toward a
    heavily blurred copy of the same master."""
    if name not in _ENGRAVED_DETAIL:
        return rgb
    path = os.path.join(HERE, "src", "aialpha", _key(name, idx) + ".png")
    if not os.path.exists(path):
        return rgb
    ai = np.asarray(Image.open(path).convert("L"), dtype=np.float64)
    if ai.shape[0] != size:
        ai = np.asarray(Image.fromarray(ai.astype(np.float32), mode="F")
                        .resize((size, size), Image.LANCZOS), dtype=np.float64)
    interior = _mask(name, idx, size) > 250          # strictly inside the traced edge
    gy, gx = np.gradient(ai)
    grad = np.hypot(gy, gx) * interior
    if grad.max() < 1e-6:
        return rgb
    strength = np.clip(grad / (0.25 * grad.max()), 0, 1)
    strength = np.asarray(Image.fromarray((strength * 255).astype(np.uint8), mode="L")
                          .filter(ImageFilter.GaussianBlur(size / 128.0)), dtype=np.float64) / 255.0
    blurred = np.asarray(Image.fromarray(rgb.astype(np.uint8), "RGB")
                         .filter(ImageFilter.GaussianBlur(size / 32.0)), dtype=np.float64)
    return rgb * (1 - strength)[..., None] + blurred * strength[..., None]


_SHEEN_SMOOTH = (1.0, 2.0, 1.0)   # circular temporal kernel over an animation's colour
_STILL_TIP_R = 1.75               # logical units around a corner whose shading is frozen.
                                  # Was 6.0, widened from 4.0 to cover the neighbourhood
                                  # _tip_pinch read its edge colour from. The pinch is
                                  # gone, and at 6.0 the sweep did not reach the points
                                  # at all: the cycle's own swing inside two units of a
                                  # corner measured 0.07 luma levels against the author's
                                  # 10.65, so the tips were simply dead.
                                  #
                                  # Set by matching the author rather than by eye: at
                                  # 1.75 that swing is 10.62 against his 10.65. What the
                                  # freeze was for - the point appearing to beat as the
                                  # sweep crosses the narrow wedge - is measured too, as
                                  # the frame-to-frame travel of the lit centroid inside
                                  # the same disc, and at this radius it sits at or below
                                  # the author's own on every arrow (apex 0.11 against
                                  # his 0.25).
_STILL_TIP_FEATHER = 2.0          # logical units of blend back into the moving body


@functools.lru_cache(maxsize=None)
def _tip_still(name, idx, size):
    """Weight map, 1 where an animation's shading is held still.

    AppStarting, Hand and Wait animate nothing but the sheen: their silhouette
    is one static arrow (identical 51-point polygon in every frame) and the
    author sweeps a highlight through the glass inside it. Near a tip the wedge
    is only a couple of units wide, so as the sweep passes it the fold line
    crosses the whole width and the point reads as leaning left, then right -
    the tip appears to wobble even though its outline never moves. Freezing the
    shading in a disc around every corner keeps the points dead still and
    leaves the sweep to the body, where it is meant to be seen."""
    pts = [(v[0], v[1]) for poly in C.TRACED[name]["frames"][idx]["polys"]
           for v in poly if v[2]]
    if not pts:
        return None
    s = size / V.LOGICAL
    ys, xs = np.mgrid[0:size, 0:size]
    d = np.full((size, size), np.inf)
    for x, y in pts:
        d = np.minimum(d, np.hypot(xs - x * s, ys - y * s) / s)
    return np.clip((_STILL_TIP_R - d) / _STILL_TIP_FEATHER, 0.0, 1.0)


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


_FOLD_REF = 256          # size the fold's path is measured at, once
_FOLD_BAND = 1.5         # logical units either side of the chord the fold is looked for in
_FOLD_CAP = 1.2          # most it may be moved
_FOLD_DIP = 8.0          # luma a dip must have to be the fold and not flat glass
_FOLD_REACH = 2.5        # logical units over which the correction fades out
_FOLD_MIN_DEPTH = 2.0    # concavity that counts as the tail junction
_FOLD_MIN_SPAN = 8.0     # shortest chord worth straightening


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
    hand."""
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


@functools.lru_cache(maxsize=None)
def _fold_offsets(name, idx):
    """How far the fold actually sits from that line, in logical units.

    Measured at _FOLD_REF and kept in logical units, so every size gets the
    same correction.

    Every keyframe is measured on its own. The sheen animations hold one
    outline and change only their colour, and each keyframe's colour comes from
    its own upscale, which puts the fold somewhere slightly different: half a
    logical unit apart between neighbouring keyframes on all three. Reusing
    frame 0's measurement for the whole cycle - which is what this did - left
    that difference in, and a fold sliding half a unit sideways and back is
    exactly the wobble the eye picks up. Measured per keyframe against the one
    shared chord, every frame lands the fold on the same line.

    An offset is only taken where the cross-section really dips: near the point
    the wedge is narrower than the search band, and the darkest sample there is
    the outer bevel, not the fold. Pulling on that dragged the whole top edge
    into the middle of the glass."""
    ch = _fold_chord(name, idx)
    if ch is None:
        return None
    src = idx
    ch = _fold_chord(name, 0 if name in INTERP else idx) or ch
    size = _FOLD_REF
    s = size / V.LOGICAL
    p0 = np.array(ch[0]) * s
    p1 = np.array(ch[1]) * s
    d = p1 - p0
    nv = np.array([-d[1], d[0]]) / np.hypot(*d)
    rgb, anchor = _master(name, src)
    _, m_a = _resize(_orig(_key(name, src)), anchor)
    rgb = rgb if anchor == size else _resize(np.dstack([rgb, m_a]), size)[0]
    # "inside the glass", which is a question about the outline, not about how
    # opaque the glass is. Thresholding the alpha answered the second question:
    # this glass peaks near 212 and sits at 165 over most of its area, so four
    # fifths of the peak excluded the interior itself, every cross-section came
    # back mostly empty, and the whole correction silently measured zero on
    # every cursor in the set.
    inset = np.asarray(Image.fromarray(_edge_distance(name, src).astype(np.float32),
                                       mode="F").resize((size, size), Image.BILINEAR),
                       dtype=np.float64)
    solid = (_mask(name, src, size) > 250) & (inset > 0.4)
    lum = rgb @ _LUMA
    qs = np.arange(-_FOLD_BAND, _FOLD_BAND + 1e-9, 0.1)
    ts = np.linspace(0.05, 0.95, 25)
    offs = []
    for t in ts:
        c = p0 + d * t
        vals = []
        for q in qs:
            x, y = c + nv * q * s
            xi, yi = int(round(x)), int(round(y))
            vals.append(lum[yi, xi] if (0 <= xi < size and 0 <= yi < size and solid[yi, xi])
                        else np.nan)
        v = np.array(vals)
        if np.isnan(v).mean() > 0.3 or np.nanmax(v) - np.nanmin(v) < _FOLD_DIP:
            offs.append(0.0)
            continue
        k = int(np.nanargmin(v))
        offs.append(0.0 if k in (0, len(v) - 1)
                    else float(np.clip(qs[k], -_FOLD_CAP, _FOLD_CAP)))
    k = np.array([1.0, 2.0, 3.0, 2.0, 1.0])
    k /= k.sum()
    offs = np.convolve(np.pad(np.array(offs), 2, mode="edge"), k, mode="valid")
    offs = offs * np.clip(np.minimum(ts, 1.0 - ts) / 0.15, 0.0, 1.0)   # ends stay put
    return ts, offs, ch


def _straighten_fold(rgb, name, idx, size):
    """Put the main fold back on its own straight line.

    A Real-ESRGAN upscale keeps the fold dark but lets its path wander: on
    Arrow it bows a unit and a half off the line between the point and the
    notch, which reads as the divider sliding sideways and the two halves of
    the glass coming out uneven. The measured offset is undone by displacing
    the colour across the chord, tapering to nothing within a couple of units
    of it, so the fold straightens and the rest of the glass stays where the
    author put it. One sampling, so nothing is superimposed on itself."""
    got = _fold_offsets(name, idx)
    if got is None:
        return rgb
    ts, offs, ch = got
    if not np.any(np.abs(offs) > 0.02):
        return rgb
    s = size / V.LOGICAL
    p0 = np.array(ch[0]) * s
    p1 = np.array(ch[1]) * s
    d = p1 - p0
    span = float(np.hypot(*d))
    u = d / span
    nv = np.array([-u[1], u[0]])
    ys, xs = np.mgrid[0:size, 0:size]
    rel = np.dstack([xs - p0[0], ys - p0[1]])
    t = (rel @ u) / span
    q = (rel @ nv) / s
    off = np.interp(np.clip(t, 0.0, 1.0), ts, offs)
    fall = np.clip(1.0 - np.abs(q) / _FOLD_REACH, 0.0, 1.0) ** 2
    shift = off * fall * s * ((t > 0.0) & (t < 1.0))
    return _sample(rgb, xs + nv[0] * shift, ys + nv[1] * shift)


_ALONG_BAND = 1.5        # logical units either side of the chord that get smoothed
_ALONG_LEN = 0.75        # logical units of travel along the chord averaged over
_ALONG_TAPS = 7          # samples across that travel
_ALONG_KEEP_TIP = 7.5    # logical units around a sharp corner left untouched.
                         # The chord runs into the points, and averaging along it
                         # there smears them: measured, Arrow's apex contrast fell
                         # 0.328 to 0.206 and UpArrow's 0.157 to 0.105 with the
                         # band reaching all the way in. The fold wants averaging
                         # down its length in the body of the glass and nowhere
                         # near a point, where there is no length left to average.


def _smooth_along_fold(rgb, name, idx, size):
    """Average the crease along its own length, and only along it.

    What the removed straightener was actually good for was this: it resampled
    colour down the fold, which averaged the section from row to row and kept it
    the same shape. Taking it out cost that - the row-to-row change of the
    section rose on every cursor that has a fold, by 10 to 60 per cent.

    Smoothing along the line recovers it without any of what the straightener
    also did. It never moves the line, so it cannot blunt a point; it is a
    weighted mean along one fixed direction, so it cannot add anything that was
    not there; and the direction is the chord's, taken from the outline, so it
    is the same in every frame of a cycle and cannot chase a defect.

    That last part is the whole difference from PLAN.md dead end 3, which
    smoothed along a direction estimated from the picture. The estimate followed
    the jitter and smoothed the fold itself. A chord cannot follow anything.

    Not for the engraved cursors. Help's "?" crosses the chord's band and does
    not run along it, so averaging down the chord smears the groove across
    itself: measured, its section got half again as rough (63 -> 95) while every
    other cursor's improved."""
    if name in _ENGRAVED_DETAIL:
        return rgb
    ch = _fold_chord(name, idx)
    if ch is None:
        return rgb
    (x0, y0), (x1, y1) = ch
    dx, dy = x1 - x0, y1 - y0
    n = float(np.hypot(dx, dy))
    if n < 1e-6:
        return rgb
    dx, dy = dx / n, dy / n
    s = size / V.LOGICAL
    ys, xs = np.mgrid[0:size, 0:size].astype(np.float64)
    # Distance from the chord's infinite line, in logical units. The band is
    # cut around the line rather than the segment so the crease keeps its
    # treatment where it runs past the chord's ends.
    d = np.abs((xs / s - x0) * dy - (ys / s - y0) * dx)
    w = np.clip(1.0 - d / _ALONG_BAND, 0.0, 1.0)
    for px, py in _sharp_corners(name, idx):
        w = w * np.clip(np.hypot(xs - px * s, ys - py * s) / s / _ALONG_KEEP_TIP,
                        0.0, 1.0)
    if w.max() <= 0.0:
        return rgb
    offs = np.linspace(-0.5, 0.5, _ALONG_TAPS) * _ALONG_LEN * s
    acc = np.zeros_like(rgb)
    for o in offs:
        acc += _sample(rgb, xs + dx * o, ys + dy * o)
    acc /= len(offs)
    return rgb * (1.0 - w[..., None]) + acc * w[..., None]


_PINCH_R = 4.0           # logical units around a point over which the glass closes
_PINCH_P = 0.7           # how sharply that closing ramps up toward the apex


def _tip_pinch(rgb, name, idx, size):
    """Close the glass at the points the way the outline closes.

    The traced outline runs to a true point, and at that point the two dark
    bevels bounding the wedge must meet - there is no room left between them.
    The colour master does not know that: it carries a bright core down the
    middle of the wedge at a width that never goes to zero, so the two bevels
    arrive at the apex still held apart. That is what reads as the point being
    split on the inside while sharp on the outside.

    The fix is to let the cross-section close: near a point the colour is taken
    to the wedge's own edge colour, weighted to full at the apex. The edge
    colour is not invented - it is the master's own, read from the band just
    inside the silhouette and carried inward. So the bevels meet, the core
    pinches off, and nothing outside _PINCH_R of a point is touched.

    A radial magnification about the apex was tried first (it pulled the fold
    in but also dragged the highlight out past the point, which read as a
    second, offset tip) and so was a local contrast boost (the fold is absent
    there, not faint, so boosting only etched what little was present)."""
    pts = _sharp_corners(name, idx)
    if not pts:
        return rgb
    al = _mask(name, idx, size) / 255.0 * _up_alpha(name, idx, size)
    peak = al.max()
    band = ((al > 0.35 * peak) & (al < 0.85 * peak)).astype(np.float64)
    if band.sum() < 32:
        return rgb
    edge = _pushpull(rgb, band)
    s = size / V.LOGICAL
    ys, xs = np.mgrid[0:size, 0:size]
    out = rgb
    for px, py in pts:
        d = np.hypot(xs - px * s, ys - py * s) / s
        w = np.clip(1.0 - d / _PINCH_R, 0.0, 1.0) ** _PINCH_P
        out = out * (1.0 - w[..., None]) + edge * w[..., None]
    return out


@functools.lru_cache(maxsize=None)
def _master(name, idx):
    """Colour master with the animation's shading damped along time.

    The author's sheen sweeps unevenly: on AppStarting the colour moves 6.6x
    faster at mid-cycle than at its start, so between two keyframes near the
    peak it jumps a long way. At 20 fps that passed unnoticed; interpolated to
    60 fps against a silhouette that now holds a still, sharp tip, the shading
    inside the tip reads as a stutter. Since a cross-fade cannot invent the
    motion between two distant keyframes (and 27 frames at rate 1 is already
    the cycle's 60 fps ceiling - see anim_frames), the pace is evened out at
    the source instead, with a small circular kernel over the neighbouring
    keyframes' colour.

    Around the tips the sweep is frozen outright (see _tip_still), to the
    cycle's own mean so no single frame's look is privileged.

    Colour only, in linear light: alpha stays the vector silhouette exactly,
    and the static cursors plus the two non-looping animations (Handwriting,
    NO, whose content appears and freezes rather than cycling) are untouched -
    averaging a frame with a neighbour that holds different content would
    ghost it."""
    rgb, anchor = _master_raw(name, idx)
    if name not in INTERP:
        return rgb, anchor
    n = len(BY_NAME[name]["frames"])
    w = _SHEEN_SMOOTH
    out = sum(_lin_master(name, (idx + d) % n) * wt
              for d, wt in zip((-1, 0, 1), w)) / sum(w)
    mean = _cycle_mean(name)
    still = _tip_still(name, idx, anchor)
    if still is not None:
        out = mean * still[..., None] + out * (1.0 - still[..., None])
    return V.linear_to_srgb(np.clip(out, 0.0, None)).astype(np.float64), anchor


@functools.lru_cache(maxsize=None)
def _lin_master(name, idx):
    return V.srgb_to_linear(np.clip(_master_raw(name, idx)[0], 0, 255).astype(np.uint8))


@functools.lru_cache(maxsize=None)
def _cycle_mean(name):
    """Mean colour over the whole cycle, in linear light.

    Cached per cursor, not recomputed per frame: _master used to rebuild this
    inside every frame it rendered, so a 9-frame cycle ran the 512px
    srgb_to_linear 81 times where 9 would do. Same summation order, so the
    result is bit-for-bit what the inline version produced."""
    n = len(BY_NAME[name]["frames"])
    return sum(_lin_master(name, i) for i in range(n)) / n


@functools.lru_cache(maxsize=None)
def _master_raw(name, idx):
    """Colour master -> (rgb HxWx3 float, anchor px), sharpened once at the anchor.

    Every cursor now anchors on the native anime src/ai512 (grey/pale included -
    the anime_6B model invents no colour on flat glass, so the old honest-Lanczos
    bypass is gone and the pale Size*/IBeam/Cross cursors finally carry real
    network detail).

    There used to be a src/ai256 level and a plain-Lanczos level under this one.
    Neither could ever fire: src/ai512 is committed and complete, so the fallback
    chain only cost 3.9 MB of unreachable masters in the repository. A missing
    master is now a hard error instead of a silent quality drop nobody would
    notice until the cursors shipped soft.

    Crispness is a single deterministic unsharp at the anchor rather than a
    sharper (noisier) network: on this clean source it sharpens the luminance
    edges without inventing texture, and downsampling the already-sharpened
    master keeps every smaller size crisp too. Saturation is anchored later, in
    frame_image, at the shipped size (see there)."""
    key = _key(name, idx)
    anchor = 512
    path = os.path.join(HERE, "src", f"ai{anchor}", key + ".png")
    if not os.path.exists(path):
        raise SystemExit("missing colour master %s - regenerate with "
                         "tools/upscale512.py" % path)
    rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.float64)
    rgb = _unsharp(rgb, radius=2.2 * anchor / 512.0, percent=90, dark=0.45)
    rgb = _declutter_hue_outliers(name, idx, rgb)
    rgb = _declutter_engraved_detail(name, idx, rgb, anchor)
    return rgb, anchor


def _ai_scale(ref, ai):
    """Factor putting the AI alpha master's visible-zone median on the plain
    Lanczos reference's, so the two are comparable level for level."""
    rv, av = ref[ref > 32], ai[ai > 32]
    if not av.size or not rv.size:
        return 1.0
    return float(np.median(rv)) / max(float(np.median(av)), 1e-6)


_TONE_LO = 0.08          # mid-tone fraction of a master that kept no translucency
_TONE_HI = 0.20          # ...and of one that did (measured: NO[8..10] 0.02..0.07,
                         # every other master 0.29..0.99, so nothing sits between)
_TONE_FLOOR = 0.90       # how far a master without mid-tones is still trusted


@functools.lru_cache(maxsize=None)
def _ai_tonality(key):
    """How much of the AI alpha master's body carries mid-tones - 1 for a real
    translucency map, near 0 for one the net collapsed to two levels.

    Real-ESRGAN is run on the alpha channel alone, and on a frame whose
    translucency spans a narrow band it can binarise it instead of upscaling
    it: NO's last frames come back as a hard stencil, everything above ~170
    kept and the rest zeroed. Such a master carries no gradient to contribute -
    only a crisper outline - and its own median-matched level is a poor
    estimate of the glass, so it is leaned back toward the Lanczos and its
    dropouts are repaired (see _ai_dropout)."""
    a = np.asarray(Image.open(os.path.join(HERE, "src", "aialpha", key + ".png"))
                   .convert("L"), dtype=np.float64)
    body = (a > 10).sum()
    if not body:
        return 1.0
    mid = ((a > 0.15 * a.max()) & (a < 0.85 * a.max())).sum()
    return float(np.clip((mid / body - _TONE_LO) / (_TONE_HI - _TONE_LO), 0, 1))


_CRACK_UNIT = 32.0       # closing kernel: one logical unit wide at native scale
_CRACK_LO = 40.0         # alpha the closing must recover before it counts
_CRACK_HI = 120.0        # ...and where the crack scores in full
_CRACK_REF_LO = 64.0     # below this the Lanczos reference is edge or background
_CRACK_REF_HI = 128.0    # at and above it the reference says solid glass


@functools.lru_cache(maxsize=None)
def _ai_dropout(key, size):
    """Per-pixel weight, 1 where the AI alpha master deleted interior coverage.

    The masters are Real-ESRGAN run on the alpha channel alone, and on a frame
    whose translucency spans a narrow band the net can binarise it instead of
    upscaling it: NO's alpha master keeps everything above ~170 and zeroes the
    rest, so the arrow's own glass (137..190 in the 2006 frame) is cut in half
    by a hard hole. Blended in at _BLEND_AI that hole survives as a black
    V-notch straight through the arrow, which at 512px reads as two forked
    spikes instead of one wedge sliding behind the ring.

    What separates such a deletion from an edge the net legitimately sharpened
    is its width, not its depth: a dropout is a thin crack with the master's
    own content on both sides, while a real edge borders open space. A
    morphological closing one logical unit wide fills the first and leaves the
    second alone, so the alpha the closing recovers - where the reference still
    reads as solid glass - is exactly the deleted part, and it is handed back
    to the Lanczos.

    The reference is measured the same way and subtracted: a thin gap the 2006
    author actually drew shows up as a crack in both, and only what the master
    invented on top of it is corrected. The whole test is scaled by how far the
    master lost its mid-tones (_ai_tonality): a faithful upscale sharpens the
    author's own thin dark seams - Handwriting's pencil folds are exactly that -
    and must keep them, so only a binarised master is repaired here.

    Measured once at the master's native resolution and resampled, because the
    crack is a native-resolution artifact: detecting it after a downsample
    would reinstate it at full strength on a size that cannot resolve it
    anyway, where the right answer is the blurred fraction this resample
    gives."""
    ai = np.asarray(Image.open(os.path.join(HERE, "src", "aialpha", key + ".png"))
                    .convert("L"), dtype=np.float64)
    native = ai.shape[0]
    _, ref = _resize(_orig(key), native)
    ai = ai * _ai_scale(ref, ai)
    k = max(3, int(native / _CRACK_UNIT) | 1)

    def crack(a):
        a = np.clip(a, 0, 255)
        im = Image.fromarray(a.astype(np.uint8), "L")
        closed = np.asarray(im.filter(ImageFilter.MaxFilter(k)).filter(ImageFilter.MinFilter(k)),
                            dtype=np.float64)
        return np.clip((closed - a - _CRACK_LO) / (_CRACK_HI - _CRACK_LO), 0, 1)

    solid = np.clip((ref - _CRACK_REF_LO) / (_CRACK_REF_HI - _CRACK_REF_LO), 0, 1)
    d = np.clip(crack(ai) - crack(ref), 0, 1) * solid * (1.0 - _ai_tonality(key))
    if native != size:
        d = np.asarray(Image.fromarray(d.astype(np.float32), mode="F")
                       .resize((size, size), Image.LANCZOS), dtype=np.float64)
    return np.clip(d, 0, 1)


@functools.lru_cache(maxsize=None)
def _up_alpha_native(key):
    """The Lanczos/AI alpha blend, built once at the master's own resolution.

    It used to be rebuilt from scratch at every requested size, and the two
    ingredients do not survive resampling the same way: the Lanczos reference
    is a 32px frame stretched to `size`, the AI master is a 512px frame
    squeezed to it, so their ratio - and with it the blend's level and the
    logical width of its falloff - came out different on every rung of the
    ladder. Measured on the shipped frames that cost 8..19% of the glass's
    opacity between 32 and 384 (the cursor visibly thinned out as it got
    bigger) and 0.22..0.45 logical units of coverage, i.e. the silhouette's own
    size drifted with the size it was drawn at.

    Building it once and resampling the result keeps one alpha for the cursor,
    scaled rather than re-derived.

    Flattening this map's own edge falloff was tried too, so that the vector
    mask would be the only thing drawing the edge - it does take the residual
    drift to nothing, and it ruins the artwork: the colour the master keeps at
    the rim is the author's thin dark outline, and standing it up at full
    opacity draws a second bright ridge parallel to the whole contour. That is
    a facet the cursor never had. Reverted; the drift left over without it is
    a twentieth of a logical unit and invisible."""
    path = os.path.join(HERE, "src", "aialpha", key + ".png")
    ai = np.asarray(Image.open(path).convert("L"), dtype=np.float64)
    native = ai.shape[0]
    _, ref = _resize(_orig(key), native)
    ai = ai * _ai_scale(ref, ai)
    t = _ai_tonality(key)
    w = (_BLEND_AI * (t + (1.0 - t) * _TONE_FLOOR)) * (1.0 - _ai_dropout(key, native))
    a = np.clip((1.0 - w) * ref + w * ai, 0, 255)
    # Level held to the author's own median, once, at native resolution: a
    # scalar applied before any resampling cannot bring per-size drift back
    # with it. Measured through the vector mask, the way the shipped frame is -
    # on the thin frames (Handwriting's pencil) the mask trims a different share
    # of the map than of the plain Lanczos, and matching the two maps bare left
    # that frame 9% out while every other one landed.
    _, name, idx = key.split("__")
    o = _orig(key)[..., 3]
    target = np.median(o[o > _VIS * o.max()])
    m = _mask(name, int(idx), _LEVEL_REF) / 255.0
    for _ in range(3):                   # the clip at 255 eats part of each pass
        cur = _resample(a, _LEVEL_REF) * m
        vis = cur > _VIS * cur.max()
        lvl = float(np.median(cur[vis])) if vis.sum() > 32 else 0.0
        if lvl < 1e-6 or abs(lvl - target) < 0.05:
            break
        a = np.clip(a * target / lvl, 0, 255)
    return a


_LEVEL_REF = 128         # size the glass level is matched at


def _resample(a, size):
    if a.shape[0] == size:
        return a
    return np.clip(np.asarray(Image.fromarray(a.astype(np.float32), mode="F")
                              .resize((size, size), Image.LANCZOS), dtype=np.float64), 0, 255)


def _up_alpha_raw(key, size):
    """The native blend at `size`, resampled. Lanczos both ways: a box
    downsample was tried for being the physically right average of a coverage
    map and is measurably worse here (the ladder's interior spread went
    2.5..3.9% -> 3.4..6.3%), because the rim this map carries is flat by
    construction and what the average would protect is already gone."""
    a = _up_alpha_native(key)
    if a.shape[0] == size:
        return a
    return np.clip(np.asarray(Image.fromarray(a.astype(np.float32), mode="F")
                              .resize((size, size), Image.LANCZOS), dtype=np.float64), 0, 255)


@functools.lru_cache(maxsize=None)
def _up_alpha(name, idx, size):
    """Silhouette translucency at `size`. The vector mask already gives a crisp
    edge; this is the glass *inside* it. A plain Lanczos of the 32px original
    alpha goes soft when stretched, so the inner sheen turns to mush at large
    sizes - the committed Real-ESRGAN alpha master (src/aialpha, native 512,
    tools/upscale_alpha.py) keeps that gradient crisp instead.

    The AI alpha is rescaled so its visible-zone median matches the plain
    Lanczos, then blended _BLEND_AI toward it from the Lanczos. The blend keeps
    the drift metric in tolerance (the full-strength AI shifts the visible-zone
    median -8..-11% on the thin NO/Handwriting frames once the vector mask
    multiplies in) without the faint horizontal banding a rank-for-rank
    histogram match leaves in the flat glass.

    A master that binarised the frame instead of upscaling it (_ai_tonality)
    is trusted a shade less, since a two-level stencil has no gradient to
    contribute and its median-matched level is a guess, and the coverage it
    deleted outright is put back (_ai_dropout). Trusting such a master at zero
    was tried and is worse than the artefact it removes: the AI alpha is what
    holds the glass opaque up to the traced edge, and without it every one of
    those frames goes soft all round. Falls back to the plain Lanczos when no
    master is present, so a torch-free build is identical to before.

    The blend is made once at the master's own resolution (_up_alpha_native,
    rim flattened) and only resampled here, so every size gets one and the same
    alpha scaled rather than a fresh one derived from differently-resampled
    ingredients. Rescaling the level per size on top of that was tried and is
    not needed once the rim is flat - a uniform scalar cannot fix a
    distribution, and it traded 0.03 -> 0.15 logical units of coverage drift
    for the 2..4% of interior level it recovered."""
    key = _key(name, idx)
    if not os.path.exists(os.path.join(HERE, "src", "aialpha", key + ".png")):
        return _resize(_orig(key), size)[1]
    a = _up_alpha_raw(key, size)
    if size == _LEVEL_REF:
        return a
    # Held to the reference size's own level. The map is one and the same at
    # every size, but the mask it gets multiplied by is not: that mask's edge is
    # one device pixel wide, a whole logical unit of the cursor at 32px and a
    # sixteenth of one at 512, so the product still drifts - 0.15 logical units
    # of coverage, the cursor quietly changing size with the size it is drawn
    # at. A scalar fixes that and cannot do any harm to the edge, which is what
    # flattening the map's own falloff did (see _up_alpha_native).
    m = _mask(name, idx, size)
    ms = m.sum()
    if ms < 1e-6:
        return a
    target = _up_alpha_level(name, idx)
    for _ in range(2):                   # the clip at 255 eats part of the first
        cur = float((m * a).sum() / ms)
        if cur < 1e-6:
            break
        a = np.clip(a * (target / cur), 0, 255)
    return a


@functools.lru_cache(maxsize=None)
def _up_alpha_level(name, idx):
    """Mask-weighted mean of the translucency map at the reference size."""
    m = _mask(name, idx, _LEVEL_REF)
    return float((m * _up_alpha_raw(_key(name, idx), _LEVEL_REF)).sum()
                 / max(m.sum(), 1e-6))


def original(name, idx):
    """The author's original 32px frame, byte for byte - the reference the
    superiority metrics and the 2006-vs-remaster comparison are measured against."""
    return Image.open(os.path.join(ORIG, _key(name, idx) + ".png")).convert("RGBA")


@functools.lru_cache(maxsize=None)
def _sat_anchor(name, idx):
    """Saturation level to match, read off the author's own frames.

    Per frame for everything except the sheen-only animations: there the level
    drifts a little from frame to frame (AppStarting 0.664..0.674) and the
    per-frame chroma rescale would put that drift back into every pixel,
    including the tips whose shading is deliberately frozen. One level for the
    whole cycle keeps them frozen; the spread is 1.6%, far inside tolerance."""
    idxs = range(len(BY_NAME[name]["frames"])) if name in INTERP else (idx,)
    return float(np.mean([_mean_sat(_orig(_key(name, i))[..., :3],
                                    _orig(_key(name, i))[..., 3]) for i in idxs]))


_BEAD_FEATHER = 0.25     # logical units the bead blends back into the glass


def _bead(rgb, name, idx, size):
    """Shade Help's dot as a bead of the same glass, not as a chip of the master.

    Two logical units across is below anything the colour master can resolve: it
    fills the dot with a hard dark wedge and a bright crescent, which at 512
    reads as a stone chipped out of the cursor. The dot's outline is analytic
    here already (see cursors._round_island), so its shading can be too - the
    same bevel lighting the geometric cursors use, over the colour of the glass
    immediately around it."""
    if name not in C.HELP_ROUND_ISLANDS:
        return rgb
    beads = [C._round_island(poly) for poly in C.TRACED[name]["frames"][idx]["polys"]
             if len(poly) <= 12]
    beads = [b for b in beads if b is not None]
    if not beads:
        return rgb
    s = size / V.LOGICAL
    ys, xs = np.mgrid[0:size, 0:size]
    out = rgb
    for cx, cy, r in beads:
        dist = np.hypot(xs - cx * s, ys - cy * s) / s
        inside = dist < r + _BEAD_FEATHER
        if not inside.any():
            continue
        # The dot floats free of the arrow, so there is no glass around it to
        # borrow a tone from - a push-pull fill here reads the transparent
        # background and washes the bead out. The author's own three pixels do
        # carry the right tone even though they carry no shape, so the bead is
        # levelled onto their mean and gets its form from the shading alone.
        base, oa = _resize(_orig(_key(name, idx)), size)
        w0 = inside.astype(np.float64) * (oa.astype(np.float64) / 255.0)
        if w0.sum() < 1.0:
            continue
        tone = (base.astype(np.float64) * w0[..., None]).sum((0, 1)) / w0.sum()
        around = np.broadcast_to(tone, rgb.shape)
        # A sphere, not a cone: the height r - dist has a crease running out of
        # the centre because its normal turns over discontinuously there, and
        # the bead came out with a seam across it.
        d = np.sqrt(np.clip(r * r - dist * dist, 0.0, None))
        gy, gx = np.gradient(d)
        gx, gy = gx * s, gy * s
        inv = 1.0 / np.sqrt(gx * gx + gy * gy + 1.0 / (_BEVEL_SLOPE ** 2))
        nx, ny, nz = -gx * inv, -gy * inv, inv / _BEVEL_SLOPE
        lx, ly, lz = _BEVEL_LIGHT
        ln = np.sqrt(lx * lx + ly * ly + lz * lz)
        dot = np.clip((nx * lx + ny * ly + nz * lz) / ln, -1.0, 1.0)
        shade = _BEVEL_DIFF * dot
        w = inside.astype(np.float64)
        shade = shade - float((shade * w).sum() / max(w.sum(), 1e-6))
        blend = np.clip((r + _BEAD_FEATHER - dist) / _BEAD_FEATHER, 0.0, 1.0)[..., None]
        out = out * (1.0 - blend) + np.clip(around + shade[..., None], 0, 255) * blend
    return out


_ENGRAVE_DROP = 70.0     # levels a pixel may fall below the glass around it
_ENGRAVE_UNIT = 2.0      # logical units that "around it" spans


def _engrave(rgb, name, size):
    """Keep Help's question mark a groove in the glass instead of ink on it.

    The author cut the mark into the surface: a shallow depression, a highlight
    on one side of it, and nothing anywhere near black. The master reads those
    few dark 32px pixels as a stroke and sharpens them into a solid black
    crescent with a hard edge - it stops looking like glass and starts looking
    like a sticker. Measured against the author's own frame, our darkest glass
    reaches 0 where his floor is 35, and a full percent of the visible cursor
    is pure black where he has nothing below 100.

    Limiting how far a pixel may fall below its own surroundings restores the
    groove and leaves everything else alone, because a groove is a local dip
    while the cursor's own dark rim is a step at the silhouette's edge, where
    there is nothing brighter beside it to be measured against.

    Only Help. Tried on the arrows the same limit takes the crease off the top
    edge and the glass goes flat - those darks are the drawing, not invention."""
    lum = rgb.mean(-1)
    small = max(2, int(round(V.LOGICAL / _ENGRAVE_UNIT)))
    im = Image.fromarray(lum.astype(np.float32), mode="F")
    around = np.asarray(im.resize((small, small), Image.BOX)
                          .resize((size, size), Image.BILINEAR), dtype=np.float64)
    lift = np.clip(around - _ENGRAVE_DROP - lum, 0.0, None)
    return np.clip(rgb + lift[..., None], 0, 255)


# Cursors whose colour master is not a rendering of the author's drawing but an
# invention. Real-ESRGAN, handed a 32px wedge with one straight fold in it,
# returns a wedge with an S-shaped hook and a swelling - the shapes read as
# melted rather than faceted, and it does it on every one of the plain
# geometric cursors. No measurement separates those frames from good ones
# (structure correlation, contrast ratio and edge density were all tried), and
# the author's own colour, scaled up, is coherent but has no fold left in it at
# all past ~128px.
#
# For these the shading is built from the outline instead. A wedge is a bevel:
# the distance to its own edge rises to a ridge along the medial axis, which for
# a triangle runs dead straight from the apex - the very fold the author drew.
# Lighting that surface gives two clean facets meeting on it. This is a
# deliberate departure from the 2006 pixels, taken because reproducing them
# through the net produces something worse than either.
_SYNTH_BEVEL = {"Cross", "SizeAll", "SizeNS", "SizeWE", "SizeNESW", "SizeNWSE", "IBeam"}

_BEVEL_REF = 512         # size the distance field is measured at, once
_BEVEL_LIGHT = (-0.6, -0.8, 0.55)   # from the upper left, as the author lit them
_BEVEL_SLOPE = 1.6       # how steeply the glass rises from its edge
_BEVEL_DIFF = 52.0       # luma swing between the facets
_BEVEL_RIM = 26.0        # how much the outline's own dark edge darkens
_BEVEL_RIM_W = 0.9       # logical units that edge is wide


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


@functools.lru_cache(maxsize=None)
def _edge_distance(name, idx):
    """Distance from every interior pixel to the silhouette's edge, in logical
    units, measured once at _BEVEL_REF and resampled from there.

    Exact, from the traced segments themselves, when there are any. A chamfer
    on the rasterised mask grows in steps of 1 and sqrt2, so the field carries a
    fine terracing; differentiating it to light the bevel turns that terracing
    into a speckled crest along the medial ridge - the fold came out as a dotted
    line rather than a drawn one. The distance to a line segment is a closed
    form, so there is no reason to approximate it."""
    size = _BEVEL_REF
    inside = _mask(name, idx, size) > 127
    polys = C.TRACED[name]["frames"][idx].get("polys") if name in C.TRACED else None
    if not polys:
        return _chamfer(inside) / (size / V.LOGICAL)
    L = size / V.LOGICAL
    ys, xs = np.mgrid[0:size, 0:size]
    px, py = (xs + 0.5) / L, (ys + 0.5) / L
    best = np.full((size, size), np.inf)
    for poly in polys:
        pts = np.array([(p[0], p[1]) for p in poly], dtype=np.float64)
        for i in range(len(pts)):
            a, b = pts[i], pts[(i + 1) % len(pts)]
            ab = b - a
            den = float(ab @ ab)
            if den < 1e-12:
                continue
            t = np.clip(((px - a[0]) * ab[0] + (py - a[1]) * ab[1]) / den, 0.0, 1.0)
            best = np.minimum(best, np.hypot(px - (a[0] + t * ab[0]),
                                             py - (a[1] + t * ab[1])))
    return np.where(inside, best, 0.0)


_BEVEL_SMOOTH = 0.3     # logical units the field is smoothed by before differencing


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
    out = a.astype(np.float64)
    for _ in range(3):
        out = _box1(_box1(out, r, 0), r, 1)
    return out


_ROUND_HOLES = {"SizeAll"}   # cursors whose interior hole the author drew round
_HOLE_FEATHER = 0.08         # logical units the analytic hole's edge spans


@functools.lru_cache(maxsize=None)
def _hole_circle(name, idx):
    """Centre and radius of the interior hole the alpha master draws, or None.

    Only the outline of SizeAll is traced; its centre hole lives in the alpha
    master alone, and the master renders it as a rounded octagon - the facets
    are obvious by 512 against an outline that is otherwise analytic. It is a
    circle to within a fifth of a logical unit (equal-area radius 4.33, largest
    radius 4.52), so measuring it once and redrawing it as one is a correction,
    not a redesign."""
    size = 512
    a = _up_alpha(name, idx, size)
    m = _mask(name, idx, size)
    inner = (m > 250) & (_edge_distance(name, idx) > 0.6)
    if not inner.any():
        return None
    dark = ((m > 250) & (a < 0.5 * np.median(a[inner]))).astype(np.uint8) * 255
    # grow out of the centre rather than label the image: everything else that
    # is dark inside the mask is where the two silhouettes disagree at the rim,
    # and only the component holding the middle is the hole
    seed = np.zeros((size, size), np.uint8)
    c = size // 2
    seed[c - 2:c + 3, c - 2:c + 3] = 255
    for _ in range(size):
        grown = np.minimum(np.asarray(Image.fromarray(seed)
                                      .filter(ImageFilter.MaxFilter(3))), dark)
        if (grown == seed).all():
            break
        seed = grown
    comp = seed > 0
    if comp.sum() < 64:
        return None
    ys, xs = np.nonzero(comp)
    L = size / V.LOGICAL
    return (xs.mean() / L, ys.mean() / L, (comp.sum() / np.pi) ** 0.5 / L)


def _round_hole(alpha, name, idx, size):
    """Cut the measured hole back out as a true circle."""
    if name not in _ROUND_HOLES:
        return alpha
    fit = _hole_circle(name, idx)
    if fit is None:
        return alpha
    cx, cy, r = fit
    L = size / V.LOGICAL
    ys, xs = np.mgrid[0:size, 0:size]
    dist = np.hypot(xs - cx * L, ys - cy * L) / L
    keep = np.clip((dist - r) / _HOLE_FEATHER, 0.0, 1.0)
    near = dist < r + 1.0            # leave the rest of the frame untouched
    return np.where(near, alpha * keep, alpha)


_DEBURR_LOGICAL = 0.14   # widest feature a burr may be, in logical units


def _deburr(alpha, size):
    """Close hairline nicks where the two silhouettes disagree.

    The alpha is the vector mask times the AI alpha master, and the two do not
    trace exactly the same outline. Almost everywhere the difference is under a
    pixel and invisible; where the outline turns through a deep concave corner -
    SizeAll's waist, between an arm and the centre hole - the master's edge
    crosses the vector one and a thin transparent spike is left sticking into
    the glass, plain at 512.

    A grey closing at a fraction of a logical unit fills a spike that thin and
    is too small to touch anything drawn on purpose: the hole is twenty times
    wider, Help's engraved groove ten."""
    r = max(1, int(round(_DEBURR_LOGICAL * size / V.LOGICAL)))
    k = 2 * r + 1
    im = Image.fromarray(np.clip(alpha, 0, 255).astype(np.uint8), "L")
    closed = im.filter(ImageFilter.MaxFilter(k)).filter(ImageFilter.MinFilter(k))
    return np.maximum(alpha, np.asarray(closed, dtype=np.float64))


def _bevel_shading(name, idx, size):
    """Luma to add so a flat wedge reads as bevelled glass."""
    d = _edge_distance(name, idx)
    if d.shape[0] != size:
        d = np.asarray(Image.fromarray(d.astype(np.float32), mode="F")
                       .resize((size, size), Image.BILINEAR), dtype=np.float64)
    L = size / V.LOGICAL
    # The field is grown a whole pixel at a time, so it climbs in steps; its
    # gradient turns those steps into a diagonal hatch across the facets, plain
    # to see by 384. Smoothing it first costs nothing - the ridge stays where it
    # is, and only the staircase goes.
    gy, gx = np.gradient(_smooth1(d, _BEVEL_SMOOTH, size))
    gx, gy = gx * L, gy * L                      # per logical unit
    inv = 1.0 / np.sqrt(gx * gx + gy * gy + 1.0 / (_BEVEL_SLOPE ** 2))
    nx, ny, nz = -gx * inv, -gy * inv, inv / _BEVEL_SLOPE
    lx, ly, lz = _BEVEL_LIGHT
    ln = np.sqrt(lx * lx + ly * ly + lz * lz)
    dot = np.clip((nx * lx + ny * ly + nz * lz) / ln, -1.0, 1.0)
    rim = np.clip(1.0 - d / _BEVEL_RIM_W, 0.0, 1.0) ** 1.5
    shade = _BEVEL_DIFF * dot - _BEVEL_RIM * rim
    # Mean removed: a light from one side lands more of the cone facing it than
    # away, so the raw term brightens the glass by a dozen levels as well as
    # shaping it, and the wedges came out paler than the author drew them.
    w = _mask(name, idx, size)
    if w.sum() > 1e-6:
        shade = shade - float((shade * w).sum() / w.sum())
    return shade


# Frames whose colour master is not usable. Real-ESRGAN, given a frame that is
# nearly transparent to begin with, does not upscale it - it invents a sheet of
# glass plates with hard cracks between them, and Handwriting's middle three are
# where it does that. Nothing separates them from the good frames by measurement:
# structure correlation, local-contrast ratio and edge density were all tried and
# all rank ordinary frames above these. So they are named, which is what a hand
# correction is.
#
# What replaces them is the author's own colour, Lanczos-scaled: blurred, because
# it comes from 32px, but whole. At the shipped sizes the difference does not
# show; past 256 these three read softer than their neighbours, which is the
# price of not having them read as broken glass.
_BROKEN_COLOUR = {("Handwriting", 3), ("Handwriting", 4), ("Handwriting", 5)}

_FREEZE_UNIT = 0.6       # logical units below which detail counts as a line


@functools.lru_cache(maxsize=None)
def _master_rgb(name, idx, size):
    """The sharpened master's colour at `size`, before any correction."""
    m_rgb, anchor = _master(name, idx)
    if size == anchor:
        return m_rgb
    _, m_a = _resize(_orig(_key(name, idx)), anchor)
    rgb, _ = _resize(np.dstack([m_rgb, m_a]), size)
    if size > anchor:                                  # only when past native detail
        rgb = _unsharp(rgb, radius=1.6 * size / 128.0, percent=40)
    return rgb


def _smooth3(rgb, unit, size):
    """Blur an RGB float array by `unit` logical units."""
    return np.dstack([_smooth1(rgb[..., c], unit, size) for c in range(3)])


def _freeze_lines(rgb, name, idx, size):
    """Hold every interior line still across a sheen animation's cycle.

    Hand, Wait and AppStarting hold one outline for the whole loop and change
    only their colour - the alpha is bit-identical from frame to frame. Each
    keyframe's colour, though, is its own upscale, and the net puts the creases
    in slightly different places each time: measured against the author's own
    frames the average swing over the cycle matches him well, but along two
    hairlines - the crease under the top edge and the fold where it meets the
    tail junction - ours swings two and a half times as far as anything he
    drew. A line a pixel wide moving a pixel is what the eye calls jitter, and
    no amount of straightening a single fold reaches it, because it is every
    line at once.

    So the cycle keeps one keyframe's lines and every keyframe's light: detail
    finer than _FREEZE_UNIT comes from the reference frame, everything coarser
    - which is the whole of the sheen, it sweeps over a third of the cursor -
    stays the frame's own.

    An earlier attempt took the high frequencies from the cycle's mean instead
    of from one frame. The mean of a moving line is a smear, and substituting
    it softened every crease it touched. One frame's are as sharp as they were
    drawn, which is why this does not soften anything."""
    if name not in INTERP or idx == 0:
        return rgb
    ref = _master_rgb(name, 0, size)
    return np.clip(_smooth3(rgb, _FREEZE_UNIT, size)
                   + (ref - _smooth3(ref, _FREEZE_UNIT, size)), 0, 255)


@functools.lru_cache(maxsize=None)
def frame_image(name, idx, size):
    """Final RGBA frame at any size. Every size, 32px included, draws its colour
    from the sharpened AI master (_master, native up to 512px) inside a
    vector-crisp silhouette; smaller sizes downsample the already-sharpened
    master, so the crispness carries down without a second sharpen pass."""
    orig = _orig(_key(name, idx))
    rgb = _freeze_lines(_master_rgb(name, idx, size), name, idx, size)
    if (name, idx) in _BROKEN_COLOUR:
        rgb = _resize(orig, size)[0]
    if name == "Help":
        rgb = _engrave(rgb, name, size)
        rgb = _bead(rgb, name, idx, size)
    if name in _SYNTH_BEVEL:
        rgb = np.clip(_resize(orig, size)[0] + _bevel_shading(name, idx, size)[..., None],
                      0, 255)
    # _straighten_fold and _tip_pinch used to run here. Both are out, and both
    # were measured on the way out rather than argued about.
    #
    # _tip_pinch took the colour near every sharp corner to a flat edge colour.
    # It closed the cross-section onto nothing: the seam beside Arrow's tail
    # corners lifted from black to 69 and the lit core fell from 255 to 229,
    # both sliding toward the same flat value. The two tail corners lost a third
    # of their contrast on a background (0.325 -> 0.207, 0.347 -> 0.267) and the
    # point it was added for did not move at all. It is PLAN.md dead end 10,
    # shipped.
    #
    # _straighten_fold cost the point itself: with it out, contrast at Arrow's
    # apex goes 0.266 -> 0.367, past every value in this repo's history. It also
    # turns out to have been a source of the jitter it was aimed at - it fits
    # its chord per frame, so the correction itself moved from frame to frame.
    # Removing it drops fold smoothness on every interpolated cursor at once
    # (Hand 1.141 -> 0.962, Wait 1.215 -> 1.047, AppStarting 1.241 -> 1.091) and
    # brings every fold two logical units closer to its point. That is dead end
    # 3's mechanism, wired into the pipeline instead of tried and rejected.
    #
    # The functions are left in place, unused, until the geometric shading of
    # stage 2 either needs them or replaces them.
    #
    # _smooth_along_fold is written and measured but not wired in. It recovers
    # the one thing the straightener was good for - the section's roughness
    # falls below where it was before any of this (Arrow 98.8 -> 41.7, UpArrow
    # 71.9 -> 64.4, Wait 70.7 -> 58.7) - and it costs, every time, a few per
    # cent of the two things that were actually asked for: Arrow_Down's point
    # contrast 0.208 -> 0.199, UpArrow's 0.157 -> 0.149, and Wait's sheen
    # smoothness 1.047 -> 1.165. Widening the corner exclusion to 7.5 units
    # bought back all of Arrow's and none of theirs.
    #
    # A rough section is a defect. It is not the defect that was reported, and
    # it is not worth paying for in points and in sheen. Left here, off, with
    # its numbers, so the trade is a decision rather than a discovery.
    up_a = _up_alpha(name, idx, size)
    alpha = _round_hole(_deburr(_mask(name, idx, size) / 255.0 * up_a, size),
                        name, idx, size)
    # anchor saturation at the shipped size, where the superiority metric reads
    # it: the premultiplied linear-light downsample shifts a vivid ring's chroma
    # (the 512-anchored match drifted +12% by 128), so matching here to the 32px
    # original's level lands every size on target. Grey glass (sat below the
    # floor) is left alone - scaling its near-zero chroma only invents colour.
    orig_sat = _sat_anchor(name, idx)
    if orig_sat >= 0.035:
        rgb = _sat_match(rgb, alpha, orig_sat * 1.05)
    return _hide_ghost(_compose(rgb, alpha), name, size)


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


def _lerp(im_a, im_b, t):
    """Cross-fade in premultiplied linear-light space - no dark fringes and no
    gamma-space midpoint dimming."""
    pa, pb = _premult(im_a), _premult(im_b)
    return _unpremult(pa + (pb - pa) * t)


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
    n = len(BY_NAME[name]["frames"])
    base = [frame_image(name, i, size) for i in range(n)]
    if name not in INTERP or not interp:
        return base, list(BY_NAME[name]["rates"])
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
    out = []
    for k in range(n * INTERP_N):
        want = k * total / (n * INTERP_N)
        i = min(int(np.searchsorted(edge, want, side="right")) - 1, n - 1)
        ts, cum = curves[i]
        t = float(np.interp(want - edge[i], cum, ts))
        out.append(base[i] if t <= 1e-6 else _hide_ghost(at(i, t), name, size))
    return out, [1] * len(out)

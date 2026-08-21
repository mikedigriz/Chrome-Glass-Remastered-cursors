"""Hybrid frame pipeline: an AI colour master inside a vector-crisp edge.

Per frame:
  colour - a native art/ai512 master from an illustration-tuned Real-ESRGAN
           (anime_6B), Reinhard-anchored to the original 32px frame's
           per-channel stats. Every cursor uses it, grey glass included: the
           anime model keeps flat glass clean instead of speckling it, so there
           is no pale-cursor bypass. Crispness is one deterministic unsharp at
           the anchor, its dark overshoot damped so glass folds soften rather
           than blacken; smaller sizes downsample the sharpened master.
  alpha  - (vector mask / 255) x an AI alpha master (art/aialpha, blended with
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

from . import cursors as C
from . import vectorlib as V
from .paths import ART

ORIG = os.path.join(ART, "orig")
AI = os.path.join(ART, "ai")

MANIFEST = json.load(open(os.path.join(ART, "manifest.json")))
BY_NAME = {m["name"]: m for m in MANIFEST}

STATIC = [m["name"] for m in MANIFEST if m["kind"] == "cur"]
ANIM = [m["name"] for m in MANIFEST if m["kind"] == "ani"]

# author's 50 ms/frame cursors, cross-faded x3 to 60 fps (same cycle length)
INTERP = {"AppStarting", "Hand", "Wait"}
INTERP_N = 3
LIGHT_ANIM = True        # these three are lit, not redrawn: one canonical render
                         # carries the geometry for the whole cycle and only the
                         # light moves over it (lightanim.py, NEXT.md 29). Set
                         # False to fall back on cross-fading full RGBA keyframes,
                         # which is what redrew the fold in a different place on
                         # every frame
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
    img = V.render(prims, size)
    return np.asarray(img, dtype=np.float64)[..., 3]


def _mask(name, idx, size):
    return _mask_geom(name, _geom(name, idx), size)


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


def _hue_outlier_weight(name, idx, rgb, sat_floor, sat_span, cos_thresh, cos_span):
    """0..1 per pixel: how far its chroma has swung from the frame's own hue.

    Shared by _declutter_hue_outliers and the ringing guard in _master_rgb -
    the same test, tuned to how far a defect has to swing before it is worth
    desaturating over."""
    ref_dir = _dominant_hue_dir(_orig(_key(name, idx))[..., :3], _orig(_key(name, idx))[..., 3])
    if ref_dir is None:
        return None
    lum = rgb @ _LUMA
    chroma = rgb - lum[..., None]
    sat = np.linalg.norm(chroma, axis=2)
    cos = np.zeros(sat.shape)
    nz = sat > 1e-6
    cos[nz] = (chroma[nz] @ ref_dir) / sat[nz]
    outlier = (np.clip((sat - sat_floor) / sat_span, 0, 1)
              * np.clip((cos_thresh - cos) / cos_span, 0, 1))
    return lum, chroma, outlier


def _declutter_hue_outliers(name, idx, rgb):
    """Real-ESRGAN is blind to alpha, and can invent a stray colour cast right
    at a high-contrast silhouette edge - Arrow_Down (blue glass) got a thin
    orange fringe tracing its whole outline, baked into the raw art/ai512
    master itself, where the original crease (and UpArrow's identical fold)
    is neutral grey. Any pixel with real chroma pointing well away from the
    frame's own dominant hue is such an outlier - desaturate it back toward
    its own luminance, feathered so the correction has no hard edge.
    Genuinely neutral cursors have no dominant hue to compare against and are
    left untouched."""
    got = _hue_outlier_weight(name, idx, rgb, 10.0, 30.0, 0.3, 0.6)
    if got is None:
        return rgb
    lum, chroma, outlier = got
    # no blur here: outlier is already a smooth per-pixel function of sat/cos,
    # and blurring it would dilute exactly the worst case - a single hallucinated
    # pixel (e.g. AppStarting's tip) - below its own correction strength.
    return lum[..., None] + chroma * (1 - outlier)[..., None]


_ENGRAVED_DETAIL = {"Help"}   # see _declutter_engraved_detail


def _declutter_engraved_detail(name, idx, rgb, size):
    """Some AI colour masters hallucinate a second copy of a glyph that the AI
    alpha master already draws correctly through translucency alone - Help's
    "?" curl is one: the original defines it as a ~1px opacity dip (art/aialpha
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
    path = os.path.join(ART, "aialpha", _key(name, idx) + ".png")
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
    inset = _edge_distance_at(name, src, size)
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
    """Colour master for one frame, as the network drew it.

    Two temporal correctors used to live here and are gone. `_SHEEN_SMOOTH`
    averaged each animation frame with its two neighbours and `_tip_still`
    froze the shading in a disc around every point to the cycle's mean; both
    existed because the animation was a cross-fade between per-frame masters
    that disagreed with each other, and the disagreement showed at the tips.
    The three looping animations are lit from one canonical render now
    (LIGHT_ANIM), so those masters are not cross-faded and not shipped - the
    correctors were left applying to nothing but the measurements and the
    preview tile. Removing them leaves the shipped frames bit-for-bit identical
    and moves the readings towards the author: delta_e 4.57 -> 4.24, 2.89 ->
    2.79, 3.78 -> 3.52, and Hand's point contrast 0.062 -> 0.178 against his
    own 0.084, which was a debt line describing a frame nobody ever saw."""
    rgb, anchor = _master_raw(name, idx)
    if name in _APEX_DONOR:
        rgb = _apex_borrow(rgb, name, idx)
    return rgb, anchor


_APEX_DONOR = {"UpArrow": "Arrow_Down"}   # blunt point -> whose shading it borrows
_APEX_R0 = 2.0           # logical units from the point the borrow is whole out to
_APEX_R1 = 3.5           # and where it has faded to nothing
_APEX_LEVEL = 1.0        # logical units the broad level is read over


def _gauss(a, sigma_px):
    """Separable gaussian, in float. PIL's own runs on bytes, and what this
    carries is a ratio of two blurs, where one level of quantisation is a
    percent of the answer."""
    r = int(max(1, round(3 * sigma_px)))
    x = np.arange(-r, r + 1, dtype=np.float64)
    k = np.exp(-0.5 * (x / sigma_px) ** 2)
    k /= k.sum()
    out = np.asarray(a, dtype=np.float64)
    for axis in (0, 1):
        pad = [(0, 0)] * out.ndim
        pad[axis] = (r, r)
        q = np.pad(out, pad, mode="edge")
        acc = np.zeros_like(out)
        for i, w in enumerate(k):
            sl = [slice(None)] * out.ndim
            sl[axis] = slice(i, i + out.shape[axis])
            acc += w * q[tuple(sl)]
        out = acc
    return out


def _apex_borrow(rgb, name, idx):
    """Lend a blunt point the shading of a cursor drawn on the same outline.

    Only the luminance travels, and only near the point:

    - the donor's own broad level is divided out and UpArrow's put back, so the
      zone cannot come out lighter or darker than it was - what is borrowed is
      the shape of the shading, not its exposure;
    - colour comes from UpArrow's own chroma direction, read over _APEX_LEVEL so
      it carries no structure of its own. Scaling each pixel by the ratio it
      would need instead clips two channels before the third where UpArrow has
      its crease and the donor has its facet, and lands as a magenta line down
      the fold - the first thing this stage got wrong;
    - the weight is 1 inside _APEX_R0 of the traced point and smoothsteps to 0
      by _APEX_R1, measured in logical units, so nothing steps at the boundary.

    Measured on UpArrow, the only cursor this is wired for: point contrast
    0.048 -> 0.071 against the author's own 0.085, the fold reaches 2.00 logical
    units from the apex instead of 2.10, delta_e 3.769 -> 3.784, fold curvature
    0.012 -> 0.013. A wider zone (2.5/4.0) buys 0.001 of contrast and costs the
    curvature 0.016; Arrow as donor doubles the contrast to 0.150 and pushes the
    fold's own start out to 5.00 units, which is the defect this exists to fix
    arriving from the other side."""
    donor = _APEX_DONOR.get(name)
    lm = _landmarks(name, idx)
    if donor is None or lm is None:
        return rgb
    size = rgb.shape[0]
    L = size / 32.0
    A = np.asarray(lm[0], dtype=np.float64)
    sigma = _APEX_LEVEL * L
    pad = int(round(3 * sigma))
    reach = int(round(_APEX_R1 * L)) + pad
    x0, x1 = max(0, int(A[0] * L) - reach), min(size, int(A[0] * L) + reach + 1)
    y0, y1 = max(0, int(A[1] * L) - reach), min(size, int(A[1] * L) + reach + 1)

    m = _mask(name, idx, size)[y0:y1, x0:x1] / 255.0
    dm = _mask(donor, idx, size)[y0:y1, x0:x1] / 255.0
    if abs(float(m.sum() - dm.sum())) > 0.01 * max(float(m.sum()), 1.0):
        raise ValueError("%s cannot borrow from %s: different silhouettes" % (name, donor))

    u = rgb[y0:y1, x0:x1]
    d = _master_raw(donor, idx)[0][y0:y1, x0:x1]
    lu, ld = u.mean(-1), d.mean(-1)
    bu, bd = _mblur(lu, m, sigma), _mblur(ld, m, sigma)
    lit = ld * np.where(bd > 1e-3, bu / np.maximum(bd, 1e-3), 1.0)
    dirn = _mblur(u, m[..., None], sigma) / np.maximum(bu, 1e-3)[..., None]

    ys, xs = np.mgrid[y0:y1, x0:x1]
    dist = np.hypot(xs / L - A[0], ys / L - A[1])
    w = (1.0 - _smoothstep(np.clip((dist - _APEX_R0) / max(_APEX_R1 - _APEX_R0, 1e-6), 0, 1)))[..., None]

    out = rgb.copy()
    out[y0:y1, x0:x1] = np.clip(u * (1.0 - w) + lit[..., None] * dirn * w, 0, 255)
    return out


def _mblur(a, m, sigma_px):
    """Blur over the covered part only, so the background outside the outline
    does not average into the level this reads."""
    if a.ndim == 3:
        return np.dstack([_mblur(a[..., i], m[..., 0], sigma_px) for i in range(a.shape[2])])
    den = _gauss(m, sigma_px)
    return np.where(den > 1e-3, _gauss(a * m, sigma_px) / np.maximum(den, 1e-3), a)


# UpArrow's apex is measured, and no stage here moves it. Kept as a note so the
# next reader does not re-derive it (full working in NEXT.md 23.6, rejected
# levers in DEAD_ENDS.md).
#
# Brightest sample per cross-section, walking down the fold chord from the
# point, stations 0.25 .. 2.5 logical units, finished 512 render. The healthy
# wedges ramp into their lit facet; UpArrow holds one flat value for two units
# and then steps sixty levels in a single station:
#
#     Arrow       134 137 140 150 159 190 210 213 211
#     Arrow_Down  123 125 127 130 133 142 178 182 195
#     UpArrow     142 143 145 145 146 145 144 203 204
#
# The ramp is in what the network was fed (`_base128`: UpArrow `115 116 120 136
# 125 149 160 229`, Arrow_Down `110 111 113 116 114 150 153 210`) and only
# UpArrow's is gone from what came back. Same net, same input shape, only the
# hue differs - and three different fills of the transparent zone reproduce the
# flat slab to within two levels, so it is not the margin either.
#
# Moving it from this side does not work. Scaling the master about the traced
# point (the wedge is a cone, so the flanks map onto themselves and only the
# misplaced facet travels) does put the step at 1.67 units, and it drags the
# master's own dark rim into the apex with it: the rim compresses tangentially
# by the same factor and arrives as a hard shadow hugging the lit facet on both
# flanks, where before there was none. Owner saw it immediately. Blending the
# 128 base back in instead recovers the ramp and smears the point into a glow.
#
# What does work is not moving anything: borrowing it. Across the wedge two
# units from the point UpArrow reads 115 95 104 97 82 and Arrow_Down reads
# 123 88 72 96 225 - the crease is there in both, the lit facet only in one, so
# the facet is missing rather than dim and no gain applied to UpArrow can put it
# back. Arrow_Down is drawn on the same traced outline, which makes its shading
# transplantable without any registration at all. See _apex_borrow.


# Handwriting 3-6: the master is torn paper, and no render stage reaches it.
#
# The author's own frames 3-5 are a cross-dissolve - two silhouettes at partial
# opacity, the arrow going and the pen arriving - so the colour handed to
# Real-ESRGAN there has no crisp structure to enlarge, and what came back is a
# scene of shards over a grey gradient (look at art/ai512 for those keys). The
# alpha is not the problem: on a common interior set at 32 our alpha and
# luminance sit within 2-4 levels of the author's on every one of the nine
# frames. Only the colour is invented, and only from 128 px up does the
# invention read - at 32 the shards average away.
#
# So the colour for those frames is borrowed from the two frames whose masters
# the net did get right (2, the arrow; 8, the pen) and registered onto the
# frame's own traced mask. Registration is by second moments rather than by
# landmarks: _landmarks resolves for 0-3 only, and the pen frames have no fold
# chord for it to stand on.
#
# Read the value as a basis frame, not as a better copy of this frame. What is
# taken from it is material - the high frequencies of glass, its facets and its
# rim - and nothing about when in the cycle it sits. Two consequences worth
# holding on to: improving frame 2 or 8 changes four other frames with it, and
# a frame listed here has no colour of its own past _MATERIAL_SPLIT, so any
# complaint about its structure is a complaint about the basis.
_MATERIAL_BASIS = {("Handwriting", 3): 2, ("Handwriting", 4): 2,
                   ("Handwriting", 5): 8, ("Handwriting", 6): 8}


def _moment_map(tm, dm):
    """Affine taking a target pixel to the donor pixel with the same place in
    the shape: centroid to centroid, principal axes to principal axes.

    Second moments fix the axes but not their sign, so all four sign pairs are
    tried and the one whose warped donor mask overlaps the target best wins.
    Nothing here looks at colour."""
    ys, xs = np.mgrid[0:tm.shape[0], 0:tm.shape[1]].astype(np.float64)

    def mom(m):
        w = m / max(m.sum(), 1e-9)
        c = np.array([(w * xs).sum(), (w * ys).sum()])
        dx, dy = xs - c[0], ys - c[1]
        cov = np.array([[(w * dx * dx).sum(), (w * dx * dy).sum()],
                        [(w * dx * dy).sum(), (w * dy * dy).sum()]])
        return c, cov

    ct, cov_t = mom(tm)
    cd, cov_d = mom(dm)
    wt, vt = np.linalg.eigh(cov_t)
    wd, vd = np.linalg.eigh(cov_d)
    wt = np.maximum(wt, 1e-9)
    wd = np.maximum(wd, 1e-9)
    whiten = (vt * (1.0 / np.sqrt(wt))).T          # target -> unit circle
    best = None
    for s0 in (1.0, -1.0):
        for s1 in (1.0, -1.0):
            m = (vd * np.array([s0, s1]) * np.sqrt(wd)) @ whiten
            qx = cd[0] + m[0, 0] * (xs - ct[0]) + m[0, 1] * (ys - ct[1])
            qy = cd[1] + m[1, 0] * (xs - ct[0]) + m[1, 1] * (ys - ct[1])
            warped = _sample(dm[..., None], qx, qy)[..., 0]
            iou = np.minimum(warped, tm).sum() / max(np.maximum(warped, tm).sum(), 1e-9)
            if best is None or iou > best[0]:
                best = (iou, qx, qy)
    return best


_MATERIAL_GAIN = 1.2        # weight of the borrowed detail. Costs the frame's
                         # colour fidelity and buys the glass back: delta_e on
                         # Handwriting[4] reads 4.05 at 1.0, 4.49 here, 5.40 at
                         # 1.6 - past the 5.0 the gate allows. Ceiling is that
                         # number, not taste.
_MATERIAL_FOLD_KEEP = 2.0   # logical units either side of this frame's own fold
                         # chord that take no borrowed detail at all. The donor
                         # brings its own crease and no fit puts the two on top
                         # of each other, so inside the band the fold stays the
                         # frame's. Measured on Handwriting[3]: without the
                         # band, fold_gap 1.50 and fold_luma_step 18.10 against
                         # a baseline 0.50 and 3.33; at 1.2 units, 1.44 and
                         # 3.33; at 2.0, both back on the baseline. Wider buys
                         # nothing.
_MATERIAL_FOLD_FADE = 0.8   # units the keep-out fades back in over
_MATERIAL_DARK = 1.0        # how much of the donor's darkening the frame takes.
                         # Held at 1: keeping the band above and letting only
                         # the bright half through it puts fold_wander at 0.93
                         # against 0.20, so the two are not interchangeable -
                         # a bright facet beside the crease moves the ridge the
                         # tracker follows as surely as a dark one.
_MATERIAL_SPLIT = 1.0       # logical units: coarser than this the colour is the
                         # author's own, finer than this it is the donor's.
                         # Whole-donor substitution reads better than anything
                         # before it and costs the frame its identity - the
                         # donor brings its own fold and its own level, so on
                         # Handwriting[3] delta_e went 3.55 -> 8.80, fold_gap
                         # 0.50 -> 4.38 and fold_luma_step 3.3 -> 32.1. The
                         # split keeps what the donor is for (facets, rim, the
                         # crispness of glass) and leaves where the fold runs
                         # and how bright the sheet is to the frame itself.


def _material_layer(name, idx, donor, size):
    """Colour for a frame whose own master the net tore up: high frequencies
    borrowed from `donor` and registered onto this frame's silhouette by
    _moment_map, low frequencies kept from the frame's own author art.

    The author's frame is 32px, so on its own it can only be soft - that is the
    _BROKEN_COLOUR substitution this grew out of. It is, however, right about
    everything coarse: where the fold runs, how the sheet is lit, what the frame
    weighs. The donor is right about everything fine and knows nothing about
    this frame. Splitting them at _MATERIAL_SPLIT gives each the half it is right
    about.

    Built at the shipped size rather than at the master's anchor, and for the
    same reason the substitution it replaces was: laid at 512 and carried down
    the chain instead, Handwriting[3]'s `fold_wander` reads 0.33 against 0.20
    with no donor detail in it at all. That is the stages between, not the
    borrow.

    What crosses is luminance only. Measured three ways on this cursor - the
    donor's detail in all three channels, its detail collapsed to luminance,
    and luminance plus the donor's own low-passed chroma - the fold readings
    are identical to the hundredth (gap 0.50, step 3.33, wander 0.20, jag 43.3)
    and only delta_e separates them: 4.49, 4.46, 4.62. So chroma is not a
    degree of freedom here, and the one variant that does move it moves it the
    wrong way - the donor's cast lands as a blue wash across the sheet, plain
    in the residual. Colour stays the author's by construction rather than by
    luck."""
    own = _resize(_orig(_key(name, idx)), size)[0]
    tm = _mask(name, idx, size) / 255.0
    dm = _mask(name, donor, size) / 255.0
    _iou, qx, qy = _moment_map(tm, dm)
    warped = _sample(_master_rgb(name, donor, size), qx, qy)
    detail = warped - _gauss(warped, _MATERIAL_SPLIT * size / V.LOGICAL)
    detail = detail.mean(2)[..., None]                 # material, not colour
    detail = np.where(detail < 0, detail * _MATERIAL_DARK, detail)
    detail = detail * (_MATERIAL_GAIN * _material_keepout(name, idx, size)[..., None])
    return np.clip(own + detail, 0, 255)


def _material_keepout(name, idx, size):
    """1 everywhere the borrowed detail may land, fading to 0 over the frame's
    own fold. Flat 1 when this frame has no chord to keep away from.

    Not to be confused with _fold_keepout further down, which holds a different
    stage off the same chord."""
    ch = _fold_chord(name, idx)
    if ch is None or _MATERIAL_FOLD_KEEP <= 0:
        return np.ones((size, size))
    s = size / V.LOGICAL
    a = np.array(ch[0], dtype=np.float64) * s
    b = np.array(ch[1], dtype=np.float64) * s
    d = b - a
    n = np.array([-d[1], d[0]]) / max(float(np.hypot(*d)), 1e-9)
    ys, xs = np.mgrid[0:size, 0:size].astype(np.float64)
    dist = np.abs((xs - a[0]) * n[0] + (ys - a[1]) * n[1]) / s
    keep = (dist - _MATERIAL_FOLD_KEEP) / max(_MATERIAL_FOLD_FADE, 1e-6)
    return np.clip(keep, 0.0, 1.0)


@functools.lru_cache(maxsize=None)
def _master_raw(name, idx):
    """Colour master -> (rgb HxWx3 float, anchor px), sharpened once at the anchor.

    Every cursor now anchors on the native anime art/ai512 (grey/pale included -
    the anime_6B model invents no colour on flat glass, so the old honest-Lanczos
    bypass is gone and the pale Size*/IBeam/Cross cursors finally carry real
    network detail).

    There used to be an art/ai256 level and a plain-Lanczos level under this one.
    Neither could ever fire: art/ai512 is committed and complete, so the fallback
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
    path = os.path.join(ART, f"ai{anchor}", key + ".png")
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
_THIN_LEAN = 1.0         # how far to hand a pixel back to the Lanczos when the
                         # alpha master runs thinner than it there. 1.0 = fully,
                         # at the limit where the master has deleted the pixel
                         # outright; the term is proportional, so a master that
                         # is only a little thin is only nudged. See
                         # _up_alpha_native for the failure this catches.


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
    a = np.asarray(Image.open(os.path.join(ART, "aialpha", key + ".png"))
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
    ai = np.asarray(Image.open(os.path.join(ART, "aialpha", key + ".png"))
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
    path = os.path.join(ART, "aialpha", key + ".png")
    ai = np.asarray(Image.open(path).convert("L"), dtype=np.float64)
    native = ai.shape[0]
    _, ref = _resize(_orig(key), native)
    ai = ai * _ai_scale(ref, ai)
    t = _ai_tonality(key)
    w = (_BLEND_AI * (t + (1.0 - t) * _TONE_FLOOR)) * (1.0 - _ai_dropout(key, native))
    # Lean back toward the Lanczos wherever the master runs thinner than it,
    # in proportion to how much thinner. _ai_dropout already does this for a
    # master that binarised the frame - a hard crack with content either side
    # of it - but the same net fails a second, softer way that no test here
    # caught: it keeps the mid-tones (so _ai_tonality scores 1.00 and the
    # median lands on the author's) while thinning the faint tail everywhere
    # at once. Measured inside the traced mask at the author's own 32px, NO[7]
    # came out at 115.7 against his 141.9 and Handwriting[6] at 134.9 against
    # 161.0 - a sixth of his glass gone, on the two frames that carried the
    # worst colour error in the set.
    #
    # This is a shape correction and has to be: the level matching below is a
    # scalar, and a scalar cannot put back a crushed tail. Matching the
    # author's mask-weighted mean does land the total light, and lands it by
    # inflating the middle of the glass - the level policy below matches a mean
    # now, on a like-for-like reading, and still needs this stage under it for
    # exactly that reason.
    thin = np.clip((ref - ai) / np.maximum(ref, 1.0), 0.0, 1.0)
    w = w * (1.0 - _THIN_LEAN * thin)
    a = np.clip((1.0 - w) * ref + w * ai, 0, 255)
    # Level held to the author's own glass, once, at native resolution: a
    # scalar applied before any resampling cannot bring per-size drift back
    # with it. Measured through the vector mask, the way the shipped frame is -
    # on the thin frames (Handwriting's pencil) the mask trims a different share
    # of the map than of the plain Lanczos, and matching the two maps bare left
    # that frame 9% out while every other one landed.
    #
    # Both sides are read at the author's own resolution, and that is the whole
    # point of this stage. It used to compare our median on the _LEVEL_REF grid
    # against his on 32, which is not the same quantity: on a thin cursor every
    # pixel of his visible zone is antialiased edge - Cross 148 of 148, IBeam
    # 88 of 88, against a tenth solid on Help - so the pairing held our glass
    # to his antialiasing. It held it perfectly (Cross 0.541 against his 0.543)
    # and the cursor paid in density: read at his own 32px, all 58 shipped
    # frames sat under him, 1.4% on NO[8] to 10.7% on IBeam, worst on the grey
    # family that reads thinnest on screen. Reading our 32 against his 32
    # lifts the glass 2..16% and centres that on zero.
    #
    # A mean rather than a median, because once the two sides line up the mean
    # is the honest statistic: a median over an all-edge zone is a median of
    # antialiasing. Matching a mean was tried before and reverted on a drift
    # reading of 10.3% against build.check_metrics' 8% limit - that reading came
    # from the same mismatched pairing, which check_metrics made too and no
    # longer does, so it is not evidence against this.
    #
    # The deficit it corrects is not perfectly flat: binned by depth from the
    # traced edge, the grey family runs 0.82..0.88 of the author in the outer
    # half unit against 0.87..0.97 deeper, so a scalar leaves the rim a few
    # percent short. Per rule 7 in NEXT.md that residue wants a per-pixel
    # correction in the manner of `thin` above, not a fourth anchor.
    _, name, idx = key.split("__")
    idx = int(idx)
    o = _orig(key)[..., 3]
    n = o.shape[0]
    vis = o > _VIS * o.max()
    w = _mask(name, idx, a.shape[0]) / 255.0
    m = _mask(name, idx, n) / 255.0
    # Read only where the silhouette actually carries glass. Where the trace
    # runs inside his faint edge the frame cannot reach him at any opacity, and
    # a mean over those pixels bills the difference to the level: Handwriting's
    # pencil has fifteen of its hundred and eighty-four visible pixels sitting
    # under a fifth of a unit of coverage against half a unit of his alpha, and
    # paying for them put that frame's body 8.1% over his own median - through
    # build.check_metrics, on the corrected reading. Missing reach is a tracing
    # defect and belongs to the trace.
    #
    # The region is picked once, on his grid, so this is not the size-dependent
    # anchor DEAD_ENDS.md records: nothing here is re-thresholded per rung, and
    # the scalar it produces is applied before any resampling.
    reach = vis & (m >= _LEVEL_REACH)
    if reach.sum() < 16:
        reach = vis
    target = float(o[reach].mean())
    for _ in range(3):                   # the clip at 255 eats part of each pass
        lvl = float((_shrink_in_mask(a, w, n) * m)[reach].mean())
        if lvl < 1e-6 or abs(lvl - target) < 0.05:
            break
        a = np.clip(a * (target / lvl), 0, 255)
    kind, cname, cidx = key.split("__")
    return _thin_lift_glass(a, cname, int(cidx), a.shape[0])


_LEVEL_REACH = 0.5       # least mask coverage a pixel needs to speak for the level


_LEVEL_REF = 128         # size the glass level is matched at


def _resample_cover(a, size, clip=True):
    """Resize a coverage map: area average down, Lanczos up.

    Box on the way down was tried once on its own and measured worse (the
    ladder's interior spread went 2.5..3.9% -> 3.4..6.3%), which is why this
    file was Lanczos both ways. That reading was taken against the whole-mask
    anchor below, which counted the ladder's own rim as glass; against an
    interior anchor the order reverses, and Lanczos' ring across a bar six
    units wide (SizeNS, SizeWE - all rim, no interior) is what no anchor could
    reach."""
    if a.shape[0] == size:
        return a
    f = Image.BOX if size < a.shape[0] else Image.LANCZOS
    out = np.asarray(Image.fromarray(a.astype(np.float32), mode="F")
                     .resize((size, size), f), dtype=np.float64)
    return np.clip(out, 0, 255) if clip else out


def _up_alpha_raw(key, size):
    """The native blend at `size`, resampled - averaged over the silhouette
    only, never across its edge.

    A plain box average of the map pulls in what lies outside the shape, so at
    32px the map's own edge pixels come out coverage-weighted - and then the
    vector mask, which is coverage-weighted by construction, multiplies that in
    a second time. The rim ends up carrying cov^2 where it should carry cov,
    and the cursor loses a few percent of its mass at every step down the
    ladder. Weighting the average by the mask removes the double count: the map
    keeps its level right up to the edge and the mask alone says how much of
    each pixel is covered."""
    a = _up_alpha_native(key)
    if a.shape[0] == size:
        return a
    if size > a.shape[0]:
        return _resample_cover(a, size)
    _, name, idx = key.split("__")
    return _shrink_in_mask(a, _mask(name, int(idx), a.shape[0]) / 255.0, size)


def _shrink_in_mask(a, w, size):
    """Box-average a coverage map down to `size` over the silhouette only.

    Shared with the level anchor in _up_alpha_native, which has to read the map
    the way the shipped frame is built or it would measure a level nothing
    renders."""
    num = _resample_cover(a * w, size, clip=False)
    den = _resample_cover(w, size, clip=False)
    flat = _resample_cover(a, size)
    return np.clip(np.where(den > 1e-3, num / np.maximum(den, 1e-3), flat), 0, 255)


@functools.lru_cache(maxsize=None)
def _up_alpha(name, idx, size):
    """Silhouette translucency at `size`. The vector mask already gives a crisp
    edge; this is the glass *inside* it. A plain Lanczos of the 32px original
    alpha goes soft when stretched, so the inner sheen turns to mush at large
    sizes - the committed Real-ESRGAN alpha master (art/aialpha, native 512,
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
    if not os.path.exists(os.path.join(ART, "aialpha", key + ".png")):
        return _resize(_orig(key), size)[1]
    a = _up_alpha_raw(key, size)
    if size == _LEVEL_REF:
        return a                         # note: anything added below skips 128
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
        cur = _interior_level(a, name, idx)
        if cur is None:
            cur = float((m * a).sum() / ms)
        if cur < 1e-6:
            break
        a = np.clip(a * (target / cur), 0, 255)
    return _hold_coverage(a, name, idx, size)


_DENSITY_DEPTH = 1.0     # logical units below the edge where the glass starts


@functools.lru_cache(maxsize=None)
def _level_region(name, idx):
    """Where the glass level is read: everything deeper than _DENSITY_DEPTH.

    Chosen once at _LEVEL_REF and never re-thresholded per size, so every rung
    is measured over one and the same piece of the cursor."""
    return _edge_distance_at(name, idx, _LEVEL_REF) > _DENSITY_DEPTH


def _interior_level(a, name, idx):
    """Mean of that region, read on the reference grid. None if there is no
    interior at all - a frame thinner than two logical units everywhere."""
    reg = _level_region(name, idx)
    if not reg.any():
        return None
    return float(_resample_cover(a, _LEVEL_REF)[reg].mean())


@functools.lru_cache(maxsize=None)
def _up_alpha_level(name, idx):
    """The glass level every other size is held to.

    Was the mask-weighted mean over the whole silhouette, which is not a
    property of the glass: the mask's edge is one device pixel wide, so
    half-covered pixels are 41% of the coverage at 32px against 4% at 512, and
    an average over all of them reads the ladder's own rim as the cursor
    getting denser. That is where density's 2.4..6.8% came from."""
    a = _up_alpha_raw(_key(name, idx), _LEVEL_REF)
    lvl = _interior_level(a, name, idx)
    if lvl is not None:
        return lvl
    m = _mask(name, idx, _LEVEL_REF)
    return float((m * a).sum() / max(m.sum(), 1e-6))


@functools.lru_cache(maxsize=None)
def _cover_ref(name, idx):
    """Coverage the frame carries per unit area at the reference size."""
    m = _mask(name, idx, _LEVEL_REF) / 255.0
    a = _up_alpha_raw(_key(name, idx), _LEVEL_REF) / 255.0
    return float((m * a).sum()) / float(_LEVEL_REF ** 2)


def _hold_coverage(a, name, idx, size):
    """Put back the coverage the interior anchor no longer carries.

    One scalar cannot hold two quantities. The level belongs to the glass and
    is now read where the glass is; how much of the cursor is covered belongs
    to the edge, and the pixels carrying it are exactly the ones the mask
    antialiases. Correcting only those leaves the interior at its anchored
    level and keeps scale_drift where it was."""
    m = _mask(name, idx, size) / 255.0
    rim = (m > 0.0) & (m < 1.0)
    if not rim.any():
        return a
    want = _cover_ref(name, idx) * float(size * size)
    for _ in range(2):                   # the clip at 255 eats part of the first
        p = m * (a / 255.0)
        have_rim = float(p[rim].sum())
        if have_rim < 1e-6:
            break
        c = (want - (float(p.sum()) - have_rim)) / have_rim
        if not 0.0 < c < 4.0 or abs(c - 1.0) < 1e-4:
            break
        a = a.copy()
        a[rim] = np.clip(a[rim] * c, 0.0, 255.0)
    return a


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
_BEVEL_DIFF = 31.0       # luma swing between the facets
_BEVEL_RIM = 15.5        # how much the outline's own dark edge darkens
# Both were 52.0/26.0, i.e. 1.67x these, and at that strength the synthetic
# lighting was painting contrast the author never drew. Measured at 128px
# against his own frames: our luma span across these seven ran 174..202 levels
# where his is 101..130, 8.8% of the visible cursor came out darker than his
# own darkest pixel (SizeWE 22.0%, and his floor there is 125 while ours
# reached 81), and 3.3% of it clipped flat at 255 where he tops out at 226.
# Inventing darkness below his floor and destroying highlight detail at the
# ceiling are both defects however deliberate the departure from his pixels
# is elsewhere - see the _SYNTH_BEVEL note above for why there is a departure
# at all. At 0.6x the clipping is gone (0.4%), the sub-floor share is down to
# 3.6%, and delta_e over the seven falls 5.51 -> 4.46 mean. Lower still keeps
# improving delta_e - it would, since the limit is his own blurred frame - so
# the stopping point is not that metric but the two invariants above, which
# are met by 0.6 and only marginally better below it; the facets have to stay
# facets.
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


_THIN_REF = 256          # grid the width field is measured on, once
_THIN_FULL = 1.6         # logical units of feature width repaired in full
_THIN_NONE = 3.2         # ...and where the repair has faded out
_THIN_LIFT = 0.30        # how far toward opaque the glass is taken there


@functools.lru_cache(maxsize=None)
def _thin_weight(name, idx, size):
    """1 on a thin feature, 0 on a broad one, smooth between.

    Width, not depth: a pixel in the middle of IBeam's stem is 0.8 units from
    the edge because the stem is 1.6 units across, and a pixel 0.8 units inside
    Arrow's blade is in the middle of nothing. So the field is the deepest
    point within a unit's reach, doubled - the width of the feature the pixel
    belongs to.
    Measured once at _THIN_REF and resampled, never derived at the shipped size:
    at 32 a logical unit is one pixel, the reach becomes a single step and half
    the cursor reads as thin. Derived per rung, the lift put IBeam at 0.948 of
    the author's mass at 32 against 0.928 at 256 and pushed Cross past the
    author outright (1.023 at 32) - the cursor changing weight with the size it
    is drawn at, which is the defect this stage exists to remove."""
    d = _edge_distance_at(name, idx, _THIN_REF)
    r = max(1, int(round(_THIN_REF / 32.0)))
    m = d
    for axis in (0, 1):                       # separable max, r rolls per axis
        acc = m
        for k in range(1, r + 1):
            acc = np.maximum(acc, np.maximum(np.roll(m, k, axis),
                                             np.roll(m, -k, axis)))
        m = acc
    t = 2.0 * m
    w = np.clip((_THIN_NONE - t) / (_THIN_NONE - _THIN_FULL), 0.0, 1.0)
    w = w * w * (3.0 - 2.0 * w)
    if size != _THIN_REF:
        w = np.asarray(Image.fromarray(w.astype(np.float32), mode="F")
                       .resize((size, size), Image.BILINEAR), dtype=np.float64)
    return w


def _thin_lift_glass(up_a, name, idx, size):
    """Hold a thin strip of glass off transparency.

    The grey family carries less alpha than the author's own art, and the
    shortfall is not made at any rung: normalised to the author's own 32px
    frame, IBeam reads 0.901 at 32 and 0.902 at 256, flat to the third decimal
    (tools/visual_audit.py --coverage). A resize loss would vary with size;
    this one is in the shape, and it hurts in proportion to how much boundary a
    cursor has for its area - IBeam has 62 pixel edges around 57 pixels of
    body, Arrow 160 around 190, and Arrow shows no deficit at all.

    Two repairs were measured, both alpha-only, neither moving a vertex: this
    one, which raises the glass's translucency on thin features, and lifting
    the mask's own partial coverage there instead. At the same strength the
    coverage lift buys almost nothing (IBeam mass +0.007 against +0.026 here),
    because the mask is already near one across a stem - what is thin there is
    the glass. Widening the traced contour instead is a dead end with numbers
    against it (DEAD_ENDS, uniform outward offset).

    Gated on width so it cannot touch a broad cursor: at _THIN_LIFT 0.30, Arrow
    moves 1.003 -> 1.007 and Help 0.999 -> 1.005, while Cross goes 0.955 ->
    0.991 and SizeWE 0.970 -> 0.998."""
    if _THIN_LIFT <= 0:
        return up_a
    w = _thin_weight(name, idx, size)
    return up_a + _THIN_LIFT * (255.0 - up_a) * w


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
    # No floor at one pixel. A pixel is not a fixed amount of cursor: at 32px it
    # is a whole logical unit, seven times the burr this is allowed to close, and
    # the closing fattened the silhouette by that much - the single largest
    # source of `scale_drift` in the set. Measured with the floor in place, the
    # mask times the alpha master drifts 0.016..0.075 across the ladder and
    # `_deburr` takes that to 0.141 (Arrow) and 0.545 (Help); without it, 0.011
    # and 0.037. Below ~114px the radius rounds to zero, and a burr thinner than
    # one device pixel is not there to close.
    r = int(round(_DEBURR_LOGICAL * size / V.LOGICAL))
    if r < 1:
        return alpha
    k = 2 * r + 1
    im = Image.fromarray(np.clip(alpha, 0, 255).astype(np.uint8), "L")
    closed = im.filter(ImageFilter.MaxFilter(k)).filter(ImageFilter.MinFilter(k))
    return np.maximum(alpha, np.asarray(closed, dtype=np.float64))


def _bevel_shading(name, idx, size):
    """Luma to add so a flat wedge reads as bevelled glass."""
    d = _edge_distance_at(name, idx, size)
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


# The paper-plane cursors: a straight fold from the point to the tail notch,
# on a silhouette the master's own upscale mis-lights right at the point (see
# DEAD_ENDS.md, "The red tip"). Owner's call, 2026-08-08: relight the point
# analytically rather than keep fighting the master's own colour there, the
# same trade _SYNTH_BEVEL already made for the seven flat cursors - narrower
# in reach, so the rest of the glass keeps the AI sheen.
#
# Handwriting and NO are not here, and were tried here 2026-08-13. Their
# opening frames are this same wedge - frame 0 of each is Hand's author art
# pixel for pixel, `_fold_chord` resolves on Handwriting 0-3 and 5 and on NO
# 0-3 - and with the full treatment their fold does read as a line to the point
# instead of dissolving a third of the way down, plainest on Handwriting frame
# 2. It costs the point: `tip_contrast` 0.242 -> 0.145 and 0.244 -> 0.155,
# against Hand's own treated 0.062. The reason this set exists is a master that
# mis-lights the point; these two do not have that master, so the relight is
# fighting paint that was already right, and 40 per cent of the point's
# contrast is what that costs. Left out. The knob to try next is
# `_TEMPER_PER_CURSOR` on "relight" rather than the whole stage at full
# strength - see NEXT.md 23.9.
_WEDGE_TIPS = {"Arrow", "Arrow_Down", "Hand", "UpArrow", "Wait", "AppStarting"}

_TIP_RELIGHT_DIFF = 34.0     # luma swing between the two facets the relight paints
_TIP_RELIGHT_RIDGE_W = 0.35  # logical units the transition spans, away from the point
_TIP_RELIGHT_TAPER = 1.2     # logical units back from the point the ridge takes to
                             # open to its full width - narrower nearer the point,
                             # the way the author's own rim does
_TIP_RELIGHT_BIAS = 0.0      # logical units the ridge sits off the tip-notch chord,
                             # toward the rim. Was 1.0: narrowed the lit core toward
                             # the author's thin rim strip, but the ridge no longer
                             # converged on the traced apex, and the owner read that
                             # as the opaque fill's own point pulling off the visible
                             # silhouette corner. On the chord it converges cleanly;
                             # the lit-core width is owner-rejected as a fix for this.
_TIP_RELIGHT_LATERAL = 2.6   # logical units either side of the chord the
                             # relight replaces at full weight (see `lateral`
                             # below - a plateau, not a ramp from the centre).
                             # Covers the AI master's own second invented dark
                             # line on Arrow/Hand, measured 2026-08-09 at
                             # |s|~2.0-2.5.
_TIP_RELIGHT_LATERAL_FALLOFF = 1.2  # logical units past _TIP_RELIGHT_LATERAL
                             # the blend weight takes to reach zero
_TIP_RELIGHT_ALONG_FLAT = 0.25  # share of the chord replaced at full weight
                             # before along starts fading - was a straight
                             # ramp from t=0, so by t=0.24 (about where the
                             # owner's close-up crops end) the master was
                             # already back to 59% strength, and its own
                             # bright rim bled through right where the eye
                             # was looking, reading as a second point forking
                             # off the first (measured 2026-08-09).
_TIP_RELIGHT_ALONG = 0.6     # share of the tip-to-notch chord the relight
                             # reaches down in total (flat part plus fade),
                             # before it fades back to the AI master

# Per-cursor fold shape near the point.
#
# Two different shapes live here, because the author drew two different
# things. Measured off his own 32px art on 2026-08-XX, cross-sections taken
# perpendicular to the tip-notch chord (t = 0.15..0.75 on Arrow):
#
#     t=0.15  103 103 103 | 164 164 164 | 132 132 | 106 113 113
#     t=0.35  173 195 195 | 210 202 177 | 154 154 | 151 146 146
#     t=0.55  214 214 206 | 206 199 176 | 176 153 | 150 150 150
#
# That is a STEP - one lit facet around 205-214, one shaded facet around
# 150-154, and a single transition sample (~176) between them. Not one value
# in it dips below the glass on either side. Arrow/Hand/Arrow_Down get that
# step, as `diff` (the luma swing across it) and `edge` (how wide the
# transition is, in logical units, away from the point).
#
# `edge` 0.5 -> 0.12: at 0.5 the transition spanned 0.92 logical units, which
# at 512px is seven device pixels of smooth ramp, and a ramp that wide between
# two large flat facets reads as shading rather than as a drawn line - the
# fold "practically invisible on the grey cursor" (owner, 2026-08-XX). Below
# ~0.125 the `width` floor takes over anyway (it holds the step to two device
# pixels at whatever size is being drawn, for anti-aliasing), so 0.12 is
# simply "let the floor decide" - one crisp line, the same couple of pixels
# wide at every size. Measured: the transition now resolves 1.8 device pixels
# from where the silhouette itself begins at 512, i.e. the fold converges on
# the traced apex as tightly as antialiasing permits, which is the other half
# of the same report ("внутренние кончики должны быть сведены с внешним").
#
# `diff` 58 -> 85 is a deliberate departure from the author, asked for
# directly ("есть смысл немного дорисовать эту складку"). 58 is his own swing,
# and reproducing it exactly is not enough here: the mean-anchoring sets our
# band to the AI master's level, which sits some 25 levels below his in this
# region (our facets read 185/127 against his 210/152), so the same step
# lands on a darker, muddier pair of facets and carries less apparent
# contrast against the bright glass around it. 85 restores the fold to
# something that reads at a glance; 110 was tried and makes the lit facet
# look heavy. The cost is small and was measured: delta_e 3.07 -> 3.20 on
# Arrow, 3.25 -> 3.45 on Hand, 3.81 -> 3.88 on Arrow_Down, against a
# tolerance of 5.0.
#
# The trough model this replaced (hw0/hw_grow/depth: a dark valley with
# brighter glass on *both* sides) was a misreading of the same art, and it is
# what the whole 2026-08-XX run of reports was chasing. A valley painted
# where the author drew a step cannot be tuned into looking right: shallow it
# vanishes, deep it reads as a hard dark band laid on top of the glass, and
# every value in between reads as a soft smudge - which is exactly the
# sequence of owner reports it produced ("нет кончика внутреннего", then
# "мега резкая тень", then "линия была линией, а не тенью непонятной"). The
# depth/hw0 tuning that answered each of those was moving along the wrong
# axis; none of it survives here.
#
# UpArrow/Wait/AppStarting keep the trough parameters, and for them it is not
# a misreading: their own art carries no fold at all this close to the point
# (it only exists past t~0.8, near the tail notch - off this band and off the
# straight chord besides; `_fold_offsets` tracks the real departure there and
# would be the way to reach it, not attempted here). What their entries do is
# replace the band with a flattened, mean-anchored version of itself, which
# is what a shallow trough degenerates to, and that matters: the AI master
# invents a fold of its own here that the author never drew (confirmed on
# Wait - see NEXT.md item 7, the render splits into two lobes even with every
# stage in this file that touches the point switched off, so it is baked into
# `art/ai512`). Flattening the band erases that invented split instead of
# adding a second one on top of it.
#
# `taper` is shared by both shapes: it is how far back from the point the
# transition (or the groove's half-width) takes to open to full size, so the
# fold converges to a true line at the traced apex instead of arriving there
# already at full width - the original two/three-tips defect.
_TROUGH_PARAMS = {
    "Arrow":       dict(diff=85.0, edge=0.12, taper=5.0),
    "Hand":        dict(diff=85.0, edge=0.12, taper=5.0),
    "Arrow_Down":  dict(diff=85.0, edge=0.12, taper=5.0),
    # Switched UpArrow/Wait/AppStarting from the trough shape to the same
    # step as Arrow/Hand/Arrow_Down (2026-08-XX), reversing the "not a
    # misreading" call made 2026-08-09 (see the long comment above this
    # dict). That call was about fidelity to the author's own 32px art -
    # correct on its own terms, his drawing really has no crease here - but
    # the trough this fidelity produced reads as a shadowy dent, not a fold
    # in glass: a valley with lit glass on *both* sides has no bright facet
    # to carry a highlight, so the point looks punched-in rather than
    # faceted. Owner's report, 2026-08-XX ("кончик стал просто теневым
    # внутренним провалом без текстуры стекла"), on the same render this
    # comment used to defend. Direct side-by-side (Wait as trough vs Wait
    # with Hand's exact step params) settles it visually: the step reads as
    # a clean fold with a real highlight streak, the trough as a dent,
    # regardless of which one matches his reference more closely. Owner
    # priority (`NEXT.md`, this session): look over literal fidelity to a
    # 32px source that was never meant to be read as an accuracy target for
    # shading a feature sixteen times larger than the pixels it was drawn
    # with.
    #
    # This also resolves the delamination crack (item 2 this session) as a
    # side effect for free: the step model replaces its band as a flat
    # two-facet field with no per-pixel structure of its own to split into
    # lobes, where the trough's shade outside its own groove fell back to
    # `_band_level`'s blurred field - close to the master's texture, close
    # enough to still carry a faint trace of it.
    # diff 85 -> 18: Arrow/Hand/Arrow_Down's 85 answers a direct request to
    # draw up a crease that is faintly but genuinely there in the author's
    # 32px art (see the `diff` history above). UpArrow/Wait/AppStarting have
    # no crease there at all - not faint, absent (measured cross-sections,
    # `_TROUGH_PARAMS` comment above) - so 85 was inventing contrast with
    # nothing behind it, and it showed: compared directly against
    # `f1769ec` (pre-`_tip_relight`, raw AI master, no fold drawn), these
    # three apexes are close to a flat wash of light, not two facets - at
    # diff=85 the shaded half read as a shadow the reference never had.
    # 18 keeps just enough split to converge as a line rather than a flat
    # disc (still needed for the point itself to read as faceted glass, not
    # a blob) while staying visibly closer to the reference's brightness.
    "UpArrow":     dict(diff=18.0, edge=0.12, taper=5.0),
    "Wait":        dict(diff=18.0, edge=0.12, taper=5.0),
    "AppStarting": dict(diff=18.0, edge=0.12, taper=5.0),
}


# The master's own fold does not sit on the chord - it runs parallel to it,
# offset sideways (measured 2026-08-13, cross-sections at t=0.35/0.45/0.55,
# darkest-gradient crossing per row): Arrow 0.25-0.30, Hand 0.25, Wait
# 0.20-0.25, Arrow_Down 0.10-0.20, UpArrow/AppStarting under 0.1. That offset,
# not a shortfall of `_tip_relight`'s own blend strength, is what read as a
# second line merging into the outline near the point: at partial temper
# strength the master's real (but sideways) fold shows through next to the
# synthetic one on the chord, and full strength only hides the seam by
# discarding the master's own facet along with it (see `_TEMPER_PER_CURSOR`
# above - flattens instead of merging). Sliding the master's pixels sideways
# by the measured amount before either stage runs puts its facet back on the
# chord, so the two agree instead of competing, at every temper strength.
_TIP_REALIGN = {
    "Arrow": 0.27, "Hand": 0.25, "Wait": 0.23, "Arrow_Down": 0.15,
    "UpArrow": 0.05, "AppStarting": 0.05,
    # Handwriting and NO are not in this table because they are not in
    # `_WEDGE_TIPS` (see the note there). Their offsets are measured, for
    # whoever picks that up: same reading, on the frames that have a chord,
    # Handwriting +0.15 / +0.21 (frames 0/1), NO +0.21 / +0.31 / +0.29
    # (frames 0/1/2). The later morph frames throw single stations of two
    # units either way - the tracker losing a line that is being redrawn.
}
_TIP_REALIGN_START = 0.2   # share of the chord the shift starts ramping in
                            # from - the measurement (t=0.35/0.45/0.55) says
                            # nothing about closer to the point, and starting
                            # the ramp at 0 reached into `tip_contrast`'s own
                            # disc (1.5 logical units, close to the apex on a
                            # short chord) and softened its one sharp pixel
_TIP_REALIGN_FLAT = 0.35   # share of the chord shifted at full weight
_TIP_REALIGN_END = 0.6     # share of the chord the shift reaches by, fading
                            # in over START..FLAT and out over FLAT..END -
                            # same reach as `_tip_relight`'s own band, since
                            # past it nothing here is being prepared for


def _tip_realign(rgb, name, idx, size):
    """Slide the master sideways near the point so its own fold sits on the
    chord instead of beside it (see `_TIP_REALIGN` for the measurement)."""
    shift = _TIP_REALIGN.get(name, 0.0)
    if shift < 1e-6:
        return rgb
    ch = _fold_chord(name, idx)
    if ch is None:
        return rgb
    (tx, ty), (nx_, ny_) = ch
    L = size / V.LOGICAL
    dx, dy = nx_ - tx, ny_ - ty
    seg_len = float(np.hypot(dx, dy))
    if seg_len < 1e-6:
        return rgb
    ux, uy = dx / seg_len, dy / seg_len
    ys, xs = np.mgrid[0:size, 0:size]
    px, py = (xs + 0.5) / L, (ys + 0.5) / L
    relx, rely = px - tx, py - ty
    t = (relx * ux + rely * uy) / seg_len
    tc = np.clip(t, 0.0, 1.0)
    w = np.clip((tc - _TIP_REALIGN_START) / (_TIP_REALIGN_FLAT - _TIP_REALIGN_START), 0.0, 1.0) * \
        np.clip(1.0 - (tc - _TIP_REALIGN_FLAT) / (_TIP_REALIGN_END - _TIP_REALIGN_FLAT), 0.0, 1.0)
    # Sample from `+shift*w` along the chord's own left normal: the seam
    # measured to the right of the chord (positive `s`), so each output pixel
    # takes the colour that currently sits `shift` further right of it,
    # pulling that content onto the chord instead of moving the chord to it.
    sx = xs + shift * w * (-uy) * L
    sy = ys + shift * w * ux * L
    return _sample(rgb, sx, sy)


def _tip_relight(rgb, name, idx, size):
    """Repaint the wedge point analytically, in a band along its own fold chord.

    Luma only - chroma stays the AI master's, so the colour family does not
    jump at the seam. The groove is a smooth flat-bottomed valley across the
    band (`_TROUGH_PARAMS`, one shape per cursor), narrow near the point and
    opening out down the chord, which is what keeps it converging cleanly to a
    single point rather than blooming (dead end: `_draw_tip`, see
    DEAD_ENDS.md) - there is no hard edge for the pixel grid to alias against,
    and no second edge for the eye to read as a second point.

    The whole band is replaced, not shaded on top of what the master painted -
    luma and chroma both, anchored to the AI master's own weighted-mean over
    the band so it sits at the band's general level and colour rather than
    introducing one of its own, but the per-pixel pattern underneath is
    discarded entirely. That is the only way to guarantee one feature - adding
    a groove on top of whatever the master already drew there cannot undo a
    split the master invented (see `_TROUGH_PARAMS` and NEXT.md item 7);
    replacing it can, and it takes both channels: the master carries its
    second point as a colour streak as much as a brightness one. Same reason
    _bevel_shading mean-subtracts over the whole mask - this is that idea
    applied to a strip instead of the whole cursor, because unlike the seven
    _SYNTH_BEVEL shapes these silhouettes are traced from raster art with far
    more vertices, and lighting the true distance-to-outline field on them
    facets visibly (see DEAD_ENDS.md for the render this produced): the chord
    is two points and carries none of that."""
    if name not in _TROUGH_PARAMS:
        return rgb
    p = _TROUGH_PARAMS[name]
    ch = _fold_chord(name, idx)
    if ch is None:
        return rgb
    (tx, ty), (nx_, ny_) = ch
    L = size / V.LOGICAL
    ys, xs = np.mgrid[0:size, 0:size]
    px, py = (xs + 0.5) / L, (ys + 0.5) / L
    dx, dy = nx_ - tx, ny_ - ty
    seg_len = float(np.hypot(dx, dy))
    if seg_len < 1e-6:
        return rgb
    ux, uy = dx / seg_len, dy / seg_len
    relx, rely = px - tx, py - ty
    s = relx * (-uy) + rely * ux           # signed distance to the chord line
    t = (relx * ux + rely * uy) / seg_len  # 0 at the point, 1 at the notch

    # `along` first, so the bend below can be weighted by how much of this
    # pixel's colour is even coming from the master to bend toward.
    #
    # Coverage is the silhouette itself, not a lateral distance from the
    # chord: replacing every pixel actually inside the wedge near the point,
    # instead of a band of some width around a line, leaves nothing of the
    # master's own competing structure to bleed through at all - there is no
    # pixel left unreplaced for a second line to be made of. `along` alone
    # still limits how far down the chord this reaches and fades it back to
    # the AI master past that.
    along_flat = p.get("along_flat", _TIP_RELIGHT_ALONG_FLAT)
    along_end = p.get("along", _TIP_RELIGHT_ALONG)
    tc = np.clip(t, 0.0, 1.0)
    along = np.clip(1.0 - (tc - along_flat) / (along_end - along_flat), 0.0, 1.0)

    # The chord is straight; the fold the master actually drew is not - it
    # bends away from the chord the same way `_fold_offsets` measures for the
    # divider-line straightening elsewhere. Past `along`'s own reach the band
    # fades back to the master's own pixels, and bending our centreline to
    # meet it there keeps the two paths coincident at the seam instead of
    # forking (owner report 2026-08-09, first fix).
    #
    # Full strength - `along` at 1, deep inside the fully-replaced core - the
    # bend has to stay off: at full coverage there is no master pixel left to
    # meet, so bending there only imports the master's own measurement noise.
    # `_fold_offsets` is sampled from a couple of pixels either side of a
    # cross-section that is barely a unit wide this close to the apex, and it
    # swung -0.7 units over three consecutive samples (t=0.09..0.16) - not a
    # real bend, a measurement wobble. Painted at full strength, that wobble
    # became a visible S-kink in the line converging on the apex itself,
    # right where the point is meant to read as one clean line (owner report
    # 2026-08-XX, "хорда идёт юзом" - the second fix, after the first left
    # this in at every t). Scaling the bend by `1 - along` keeps it at zero
    # through the flat core and fades it in only over the same stretch the
    # band itself is already fading out, so the wobble never reaches the part
    # of the line the eye is looking at.
    fo = _fold_offsets(name, idx)
    if fo is not None:
        ts_, offs_, _ = fo
        s = s - np.interp(t, ts_, offs_, left=0.0, right=0.0) * (1.0 - along)

    # Lateral reach: `_TIP_RELIGHT_LATERAL`/`_FALLOFF` were named and
    # documented as this limiter above but never wired in - `band` used the
    # whole mask, so at any t past the very apex, where the wedge is wider
    # than the fold band, the replacement covered the outer rim too, not
    # just the crease. That rim already carries its own highlight from the
    # AI master (or, for Arrow/Hand's `diff`-step shape, is meant to keep
    # it) - overwriting it with the flat analytic facet is what the owner
    # saw as an extra strip running the length of the edge, absent from the
    # pre-`_tip_relight` reference (`f1769ec`) and present since. Wired in
    # now: a lateral plateau to `_TIP_RELIGHT_LATERAL`, ramp to zero over
    # `_FALLOFF`. Measured on Wait: the wedge is 3.45 units wide at
    # `t=0.14` (the widest the crack fix reaches at full strength) against
    # a 3.8-unit total lateral reach, so this does not reopen the crack;
    # by `t=0.30` the wedge is 6.5 units wide and the outer half on each
    # side falls outside the reach, back to the master's own rim.
    lateral = np.clip((_TIP_RELIGHT_LATERAL + _TIP_RELIGHT_LATERAL_FALLOFF
                       - np.abs(s)) / _TIP_RELIGHT_LATERAL_FALLOFF, 0.0, 1.0)
    band = along * lateral * (_mask(name, idx, size) / 255.0)
    if band.max() < 1e-6:
        return rgb

    taper_dist = p.get("taper", _TIP_RELIGHT_TAPER)
    taper_frac = np.clip(t * seg_len / taper_dist, 0.0, 1.0)
                                            # true 0 at the point itself, not
                                            # floored at 0.05 - that floor used
                                            # to hold the groove's own half-width
                                            # open a few pixels wide right at the
                                            # apex, which is what read as a blunt,
                                            # offset "second point" instead of a
                                            # convergence to the traced corner
                                            # (owner report 2026-08-09). `width`
                                            # keeps its own floor below, which is
                                            # a separate anti-alias concern, not
                                            # a substitute for hw reaching zero.
    lum = rgb.mean(-1)
    if "diff" in p:
        # A step: one lit facet, one shaded facet, meeting on the chord - the
        # shape the author actually drew (see _TROUGH_PARAMS). `edge` is how
        # wide the transition is away from the point; `taper_frac` closes it
        # toward zero at the apex so the two facets converge to a line there
        # rather than arriving already separated. Floored at a couple of
        # device pixels: sub-pixel-wide it is a knife edge on the sampling
        # grid and reads as speckle rather than as a drawn line.
        width = np.maximum(p["edge"] * taper_frac, 2.0 / L)
        # `width` closes to its device-pixel floor at the apex, but the wedge
        # itself is already wider than that floor almost immediately off the
        # point (0.6 logical units of half-width at t=0.05), so without also
        # tapering `diff` the two facets hit full +-42.5 contrast the instant
        # the transition narrows - a hard 50/50 split with no point left to
        # read as lit. Owner report: apex reads as shadowed against the
        # `f1769ec` reference, which has no such stage at all. Ramping diff
        # by the same `taper_frac` lets the split itself, not just its
        # transition width, converge smoothly to the anchor level at t=0.
        shade = -0.5 * p["diff"] * taper_frac * np.clip(s / width, -1.0, 1.0)
    else:
        # A trough - see _TROUGH_PARAMS for why the three sheen cursors keep
        # this shape (they carry no fold here at all; a shallow one degenerates
        # to flattening the band, which is the point).
        width = np.maximum(_TIP_RELIGHT_RIDGE_W * taper_frac, 2.0 / L)
        hw = p["hw0"] + p["hw_grow"] * taper_frac
        d = np.abs(s - _TIP_RELIGHT_BIAS)
        shade = -p["depth"] * np.clip(1.0 - (d - hw) / width, 0.0, 1.0)
    band_sum = band.sum()
    # Anchored to the band's own level, but to that level as a slowly varying
    # field rather than as one number over the whole band. A scalar anchor
    # makes the patch a pair of flat facets whose only per-frame freedom is
    # their common brightness, and on a sheen animation that is what killed the
    # point: measured on the cycle, the apex disc swung 4.6 luma levels against
    # the author's 13.8 on Hand, while the two tails - which this stage never
    # touches - swung more than his. Smoothing over _TIP_ANCHOR_SMOOTH keeps
    # every frequency the artefact lived at replaced (the invented second line
    # is a hairline; see the chroma note below) and lets the sweep through.
    #
    # Only on the three that animate. A still cursor has no sweep to let
    # through and pays for the field anyway: on Arrow the local level near the
    # point is lower than the band's, so the patch lands darker and the point's
    # contrast against a background falls (0.215 -> 0.157 measured, and 3.5 is
    # the best of the widths tried - 5.0 gave 0.132). There is nothing to buy
    # with that on a frame that never changes.
    lvl = _band_level(lum, band, size) if name in INTERP else \
        float((lum * band).sum() / band_sum)
    shade = shade - float((shade * band).sum() / band_sum) + lvl
    new_lum = lum * (1.0 - band) + shade * band

    # Chroma flattened the same way luma is, not carried over raw: the master
    # carries its own colour streak here as well as its own brightness one -
    # a saturation/hue line independent of luma, invisible to every check
    # above because they only ever looked at luma. Preserving chroma read as
    # "the colour family does not jump at the seam" when the band was narrow,
    # but now that the band covers the whole cross-section, raw chroma means
    # carrying the master's second line through untouched in colour even
    # after luma stopped having one - which is exactly the second point the
    # owner kept seeing (measured 2026-08-09: a 0.4-14 magnitude chroma
    # streak tracking the same path as the luma artefact, band-anchored luma
    # alone cannot touch it). Anchored to the band's own weighted-mean chroma,
    # same as luma, so the seam still sits at the band's general colour.
    chroma = rgb - lum[..., None]
    band_w = band[..., None]
    if name in INTERP:
        lvl_chroma = np.dstack([_band_level(chroma[..., c], band, size)
                                for c in range(3)])
    else:
        lvl_chroma = (chroma * band_w).sum((0, 1)) / max(float(band_w.sum()), 1e-6)
    new_chroma = chroma * (1.0 - band_w) + lvl_chroma * band_w
    return np.clip(new_lum[..., None] + new_chroma, 0, 255)


_EDGE_SHADOW_CURSORS = _WEDGE_TIPS | {"Help"} | {"Handwriting", "NO"}
# Handwriting and NO were dropped from this set after the first gate run, on
# two readings: Handwriting's morph_iou_min fell below its ratchet (0.437 ->
# 0.385) and NO's fold_luma_step nearly doubled (68 -> 90). Added back
# 2026-08-13, on the look and on a re-measurement.
#
# The look first. Their arrow frames carry the defect this stage exists for at
# full strength - a black hairline the length of the top edge and down the
# left, reading as a crack in the glass rather than a bevel - and they are the
# only cursors that still do, so next to Hand, whose author frame 0 is the
# same drawing pixel for pixel, they look broken. With the stage on the crack
# is gone and the two match Hand.
#
# The morph reading no longer reproduces: iou_min is 0.448 with the stage on
# and 0.448 with it off, unchanged to three decimals on every frame pair. That
# regression belonged to the code as it stood then, not to this stage.
#
# The fold reading does reproduce, and it is the tracker reading the defect.
# `_fold_track` takes the darkest interior pixel per row, the spurious line is
# the darkest thing in its window, and `_fold_keepout` only protects a strip
# 0.8 units either side of the chord. Measured at 256, the surviving track on
# Handwriting frame 2 sits +0.95..+1.58 units off the chord - out in the
# filter's own band, nowhere near the crease - and that frame is the whole
# regression (fold_luma_step 0.0 -> 15.5, and the set worst 2.100 -> 15.500;
# frames 0/1/5 move by tenths). Frame 0 on both cursors trades jag 15 -> 42
# and 14 -> 41, which is where Arrow already sits (34) with the stage on.
# Carried in metrics-baseline.json rather than defended: a hairline crack the
# eye sees on every frame is not worth a number measured on that crack.
_EDGE_SHADOW_D_LO = 0.45   # logical units from the traced edge the band starts.
                           # Was 0.7, which left the master's dark band sitting
                           # at d~0.68 just outside the reach of the very stage
                           # written to clear it - the owner reported it twice,
                           # as an outline along the edge and as the inner facet
                           # being pushed back from the point. Judged on rendered
                           # crops at 512 on grey: at 0.45 the dark band between
                           # the outline and the lit inner facet is visibly
                           # narrower on Arrow, UpArrow and Wait and the facet
                           # reaches closer to the point, while the inner tip
                           # keeps its own point and its separating line. 0.25
                           # goes further and is too far: Hand's interior flattens
                           # and its crease weakens, plainly, and the numbers
                           # agree (fold_wander 0.015 -> 0.478). Cost at 0.45 is
                           # one gate regression, both of them fold cross-section
                           # readings on cursors whose folds still read correctly
                           # by eye: Arrow fold_luma_step back to 1.333 and
                           # AppStarting 6.633 -> 8.433.
_EDGE_SHADOW_D_HI = 1.9    # ...and ends - measured on Arrow and Arrow_Down
                           # (row scan away from apex/tail, background composited
                           # out): the master's dip sits at d~1.19-1.37, between
                           # the chrome rim highlight (peaks ~d 1.0-1.15) and the
                           # facet proper (flat ~153-160 past d 1.6). The band is
                           # measured wide enough to hold the dip on every one of
                           # the nine affected cursors without needing the exact
                           # centre fitted per cursor.
_EDGE_SHADOW_REACH = 0.35  # logical units the max-filter looks sideways for a
                           # brighter neighbour - wide enough to clear the
                           # dip's own ~0.2-unit width from either side.
                           #
                           # A max filter's smallest radius is one pixel, and
                           # below 96px one pixel is wider than this reach: at
                           # 32 it is 1.0 logical units, three times what was
                           # measured, on a cursor whose entire dark outline is
                           # one pixel. The stage used to floor the radius at
                           # one and run anyway, and it ate the outline - that
                           # is where the small sizes lost their weight against
                           # a light desktop (p99 |luma-240| over the mask,
                           # composited on 240, before the stage and after:
                           # UpArrow 91 -> 75, AppStarting 165 -> 123, Arrow
                           # 90 -> 81, against the author's own 32px art at
                           # 102, 162 and 101). Every route that keeps the
                           # stage's reach honest scored 92-97 on the same
                           # three, so the reach was the whole of it - the
                           # linear-light downsample was suspected first and
                           # measured innocent (gamma-space averaging is worth
                           # 2-4 levels, not 16).
                           #
                           # So it now declines below 96 rather than running
                           # with a reach it was never measured with. Judged on
                           # rendered crops at 32, 48, 64, 96 and 128 on both
                           # grounds against the author's art: through 64 the
                           # band it clears is sub-pixel and there is nothing
                           # to see, the stage only lightens the true rim and
                           # the author's is darker than either version. At 96
                           # the second line is plainly there with the stage
                           # off - a doubled outline inside the top-right edge
                           # of Arrow, UpArrow, AppStarting, Hand and Help -
                           # and the stage clears it. 96 is also exactly where
                           # one pixel first fits inside the reach.
_EDGE_SHADOW_DIP_CAP = 3.0 # luma levels a pixel may sit below the brightest
                           # pixel within _EDGE_SHADOW_REACH before it is lifted
                           # to that brightest value. Small: flat glass either
                           # side of the dip varies by only a couple of levels,
                           # so little margin is needed to leave real shading
                           # alone while still catching the artefact, which is
                           # 50-150 levels deep.


_FOLD_KEEPOUT = 0.8      # logical units either side of the chord the edge-shadow
_FOLD_KEEPOUT_RAMP = 0.3 # filter is held off, and the units it ramps back in over


def _fold_keepout(name, idx, size):
    """Weight that holds `_edge_shadow_declutter` off the fold itself.

    The band it clears runs 0.7..1.9 units in from the silhouette, and where the
    fold comes that close to the edge - the tail cutout on Wait, the notch on
    Arrow - the max filter lifts the crease along with the master's spurious
    line, because a max filter cannot tell one dark thing from another. The
    fold's own dip is what every fold metric reads, so this showed up as the
    line breaking (Wait `fold_gap` 0.875 -> 1.375) and its cross-section
    flattening (Arrow `fold_luma_step` 1.083 -> 1.333, Arrow_Down 9.650 ->
    9.850, AppStarting `fold_wander` 0.207 -> 0.210) - four gate regressions,
    all of them exactly the pre-band readings once the crease is held out.

    The spurious line the stage exists for runs parallel to the outline, not
    along the chord, so keeping a strip around the chord out of the filter costs
    it almost nothing: measured at 512 on grey, the share of the cursor below 70
    luma moves 0.50% -> 0.56% on Arrow, 7.79% -> 7.82% on Wait, and not at all on
    Hand. Cursors with no chord get a weight of one and are untouched."""
    ch = _fold_chord(name, idx)
    if ch is None:
        return 1.0
    (x0, y0), (x1, y1) = ch[0], ch[1]
    L = size / V.LOGICAL
    dx, dy = (x1 - x0) * L, (y1 - y0) * L
    n = float(np.hypot(dx, dy))
    if n < 1e-6:
        return 1.0
    ux, uy = dx / n, dy / n
    ys, xs = np.mgrid[0:size, 0:size]
    s = ((xs - x0 * L) * (-uy) + (ys - y0 * L) * ux) / L      # logical units
    return np.clip((np.abs(s) - _FOLD_KEEPOUT) / _FOLD_KEEPOUT_RAMP, 0.0, 1.0)


def _edge_shadow_declutter(rgb, name, idx, size):
    """Cap the AI master's second, spurious crease line that runs parallel to
    the outer silhouette edge on every wedge-shaped cursor.

    Baked into art/ai512 before any stage in this file runs (present with
    _tip_relight, _match_author_level and _notch_declutter all off): a thin
    dark band sits a little over a logical unit in from the traced edge,
    between the chrome rim highlight and the facet - the network's own
    reading of a second bevel that the author's 32px art never drew (one
    soft falloff, not two facets meeting at a hairline). It reads as a
    second, floating outline sitting just inside the true one.

    A smoothed-neighbourhood floor (`_notch_declutter`'s approach, immediately
    below) was tried first and undershoots here: the averaging window that
    builds the "local level" pulls in the dip itself, so the floor sags along
    with the defect it is meant to correct, and a thin dark line survives at
    reduced but still visible contrast. A max filter has the opposite bias -
    it can only replace a pixel with the brightest one nearby, so the dip
    cannot drag its own reference down - and reaches the same conclusion the
    author's single soft falloff implies: nothing but the network's own
    invention sits between the rim and the facet, so the brightest nearby
    reading is the correct one."""
    if name not in _EDGE_SHADOW_CURSORS:
        return rgb
    if _EDGE_SHADOW_REACH * size / V.LOGICAL < 1.0:
        return rgb
    d = _edge_distance_at(name, idx, size)
    band = np.clip(np.minimum(d - _EDGE_SHADOW_D_LO,
                              _EDGE_SHADOW_D_HI - d) / 0.2, 0.0, 1.0)
    mask = _mask(name, idx, size) / 255.0
    w = band * mask * _fold_keepout(name, idx, size)
    if w.max() < 1e-6:
        return rgb
    r = int(round(_EDGE_SHADOW_REACH * size / V.LOGICAL))
    k = 2 * r + 1

    def _closed(chan):
        im = Image.fromarray(np.clip(chan, 0, 255).astype(np.uint8))
        return np.asarray(im.filter(ImageFilter.MaxFilter(k))
                          .filter(ImageFilter.MinFilter(k)), dtype=np.float64)

    lit = np.stack([_closed(rgb[..., c]) for c in range(3)], axis=-1)
    lum, lit_lum = rgb.mean(-1), lit.mean(-1)
    dip = np.clip((lit_lum - lum - _EDGE_SHADOW_DIP_CAP) / 20.0, 0.0, 1.0)
    lift = _smooth1(dip * w, 0.2, size)
    return rgb * (1.0 - lift[..., None]) + lit * lift[..., None]


_EDGE_COMB_CURSORS = _EDGE_SHADOW_CURSORS
_EDGE_COMB_REACH = 0.5    # logical units either way along the edge that are
                          # averaged. 0.75 cleans a little further and starts
                          # costing fold cross-sections near the tail (NO's jag
                          # 8.0 -> 21.8); 0.5 leaves those alone.
_EDGE_COMB_DEPTH = 0.7    # how far in from the traced edge the smoothing runs
_EDGE_COMB_FADE = 0.4     # and the units it fades out over
_EDGE_COMB_KEEP = 2.0     # radius round each traced corner it is held off in,
_EDGE_COMB_RAMP = 1.5     # and the units it ramps back in over


def _edge_comb(rgb, name, idx, size):
    """Smooth the edge band *along* the outline, never across it.

    The author's shaded side is one soft dark line the whole length of the
    wedge. Ours is that line broken into flecks - dark brown, near black, grey,
    a red pixel - one per pixel, because the master's texture survives in a
    feature about a pixel wide and every pixel takes a different sample of it.
    Composited and magnified at 32 and 64, where that line *is* the edge, it
    reads as dirt rather than as glass (owner report, 2026-08-13).

    It is not a level error and no author-anchored correction touches it: the
    line's own darkness is close to his (measured across the side at 128 on
    Wait, station 0.5 in from the edge, on grey: 84 against his 93). What is
    wrong is that it is not the same colour twice running.

    Smoothing across the edge would soften the silhouette, which is the one
    thing the vector trace exists to keep sharp. Along it costs nothing: the
    tangent is perpendicular to grad(`_edge_distance`), so every sample stays
    at the same depth and the profile across the edge comes out unchanged.

    Held off the traced corners, where two edges meet and "the" tangent means
    nothing - smoothing along it there runs straight across the point, and the
    points lose most of their contrast (Arrow 0.129 -> 0.038, Hand 0.062 ->
    0.038, Arrow_Down 0.092 -> 0.036)."""
    if name not in _EDGE_COMB_CURSORS:
        return rgb
    d = _edge_distance_at(name, idx, size)
    L = size / V.LOGICAL
    # `_fold_keepout` for the same reason `_edge_shadow_declutter` takes it:
    # where the fold runs close to the outline - the tail cutout - averaging
    # along the edge averages along the crease too. Without it UpArrow's
    # fold_gap goes 1.250 -> 2.250.
    w = np.clip((_EDGE_COMB_DEPTH - d) / _EDGE_COMB_FADE, 0.0, 1.0) * \
        (_mask(name, idx, size) / 255.0) * _fold_keepout(name, idx, size)
    ys, xs = np.mgrid[0:size, 0:size]
    px, py = (xs + 0.5) / L, (ys + 0.5) / L
    for cx, cy in _sharp_corners(name, idx):
        w *= np.clip((np.hypot(px - cx, py - cy) - _EDGE_COMB_KEEP)
                     / _EDGE_COMB_RAMP, 0.0, 1.0)
    if w.max() < 1e-6:
        return rgb
    gy, gx = np.gradient(d)
    n = np.hypot(gx, gy)
    ok = n > 1e-6
    tx = np.where(ok, -gy / np.maximum(n, 1e-6), 0.0)
    ty = np.where(ok, gx / np.maximum(n, 1e-6), 0.0)
    steps = np.arange(-_EDGE_COMB_REACH, _EDGE_COMB_REACH + 1e-9, 0.25)
    acc = np.zeros_like(rgb)
    for k in steps:
        acc += _sample(rgb, xs + tx * k * L, ys + ty * k * L)
    acc /= len(steps)
    return rgb + (acc - rgb) * w[..., None]


_NOTCH_RADIUS = 3.2    # logical units from the tail notch the correction reaches
_NOTCH_FALLOFF = 0.6   # exponent on the radial weight - below 1 so the weight
                       # stays high most of the way to _NOTCH_RADIUS instead of
                       # tapering from the centre, because the defect itself
                       # does not taper: it is close to full strength across
                       # the whole disc and only stops at the edge.
_NOTCH_DIP_CAP = 42.0  # luma levels the local facet colour may sit above a
                       # pixel before the excess counts as the defect, not the
                       # genuine crease. The author's own notch dips 20-30
                       # levels away from t~0.6-0.9 and up to 55-90 right at
                       # the notch (measured along _fold_chord, composited on
                       # both a light and a dark background); 42 sits inside
                       # that native range so a real crease survives and only
                       # the overshoot past it is pulled back.
_NOTCH_BLUR = 1.4      # logical units the local facet baseline is averaged
                       # over - wide enough to bridge the crack itself (a unit
                       # or less across) without reaching past the notch into
                       # the other tail's own facet
_NOTCH_T0 = 0.985      # share of the tip-to-notch chord the correction is held
                       # off until. `tools/selftest.py`'s fold-jag probe plants
                       # its defect on every row `_fold_track` resolves, which
                       # on Arrow at 256px reaches t=0.959 - a disc keyed on
                       # distance from the notch vertex alone reached back into
                       # that band and absorbed the probe (selftest failed:
                       # jag no longer moved on its own defect). Gating on t
                       # as well keeps the correction out of ground the
                       # tracker is already answering for.


def _notch_declutter(rgb, name, idx, size):
    """Cap how dark the tail notch is allowed to read, relative to its own
    neighbourhood.

    All six wedge cursors share one silhouette, and at the concave notch where
    the two tails meet, the AI master exaggerates the fold into a near-black
    wedge that runs several times deeper than the author's own art: measured
    along `_fold_chord` near its notch end (t=0.99, composited on a light
    background), the master's dip reaches 124-188 luma levels on Arrow, Hand
    and Arrow_Down against the author's 22-30 there. It is baked into
    `art/ai` before any stage in this file runs - present with `_tip_relight`
    and `_match_author_level` both switched off - so it is corrected here the
    same way `_tip_relight` corrects the master's invented second point: by
    replacing, not shading on top.

    Unlike `_tip_relight`, the region is not a band along a chord - the defect
    sits off-axis from the tip-notch chord by up to a full logical unit
    (measured on Arrow: the darkest pixels near the notch land at |s|~0.9-1.0,
    not on the chord itself), which is the departure `_fold_offsets` already
    tracks for the divider line elsewhere. A disc centred on the notch vertex
    reaches the defect without needing that offset fitted a second time here;
    `_NOTCH_T0` then trims the disc back on the apex-facing side so it starts
    only past where the fold tracker's own band ends.

    The correction is a floor, not a flat replacement: `_band_level` in
    `_tip_relight` replaces its whole band outright because that band is
    narrow enough that "the local level" and "the target" are the same
    question. Here they are not - the notch spans a real light/dark facet
    junction, and flattening it the same way would erase the genuine crease
    along with the exaggeration. So only the excess past `_NOTCH_DIP_CAP`
    below the pixel's own smoothed neighbourhood is pulled back; a pixel that
    is merely darker than its neighbour, not darker than any pixel in this
    drawing has a right to be, is left alone."""
    # Handwriting and NO were let in here 2026-08-13 and taken straight back
    # out. Their notch bar is thicker than this stage's own reference can
    # survive: `_NOTCH_BLUR` is 1.4 units and the bar is about 1, so the
    # smoothed neighbourhood sags into it and the floor comes down with the
    # defect - the failure the docstring above credits to the smoothed-baseline
    # approach in general. Measured, the crop does not move. `_notch_from_author`
    # is the stage that does not sag, and it has them.
    if name not in _WEDGE_TIPS:
        return rgb
    ch = _fold_chord(name, idx)
    if ch is None:
        return rgb
    (tx, ty), (nx_, ny_) = ch
    L = size / V.LOGICAL
    ys, xs = np.mgrid[0:size, 0:size]
    px, py = (xs + 0.5) / L, (ys + 0.5) / L
    r = np.hypot(px - nx_, py - ny_)
    dx, dy = nx_ - tx, ny_ - ty
    seg = float(np.hypot(dx, dy))
    if seg < 1e-6:
        return rgb
    ux, uy = dx / seg, dy / seg
    t = ((px - tx) * ux + (py - ty) * uy) / seg
    t_gate = np.clip((t - _NOTCH_T0) / (1.0 - _NOTCH_T0), 0.0, 1.0)
    mask = _mask(name, idx, size) / 255.0
    w = np.clip(1.0 - r / _NOTCH_RADIUS, 0.0, 1.0) ** _NOTCH_FALLOFF * t_gate * mask
    if w.max() < 1e-6:
        return rgb
    lum = rgb.mean(-1)
    weighted = lum * mask
    base = _smooth1(weighted, _NOTCH_BLUR, size)
    den = _smooth1(mask, _NOTCH_BLUR, size)
    base = np.where(den > 1e-4, base / np.maximum(den, 1e-4), lum)
    floor = base - _NOTCH_DIP_CAP
    lift = np.clip(floor - lum, 0.0, None) * w
    return np.clip(rgb + lift[..., None], 0, 255)


# Only the three the measurement puts far from the author. Hook at t=0.98,
# render against the same track on his own 32px frame resampled to 512: Hand
# -1.10 against -1.00, Arrow_Down 0.72 against -0.74, Arrow 1.44 against -1.00
# (the sign flips where the tracker takes the far side of the notch; the
# magnitude is the reading). Those three already end their fold where he does.
# Wait -1.44 against -0.22, AppStarting -1.62 against -0.22, UpArrow -1.62
# against -0.74 - six to seven times his own departure, and the same three
# cursors the upscale mangles at the apex. Run on all six, the cap washes out
# Arrow's notch crease, which is his drawing, not the network's.
#
# Handwriting and NO added the same day, on the crop rather than that table:
# neither is in `_WEDGE_TIPS`, so neither gets `_notch_declutter` either, and
# their notch carries a solid dark bar about a unit thick and four long where
# the author has soft grey - worse than any of the six ever were.
_NOTCH_AUTHOR_CURSORS = {"Wait", "AppStarting", "UpArrow", "Handwriting", "NO"}
_NOTCH_AUTHOR_FULL = 2.0   # logical units from the notch vertex the author's own
                           # paint is used outright
_NOTCH_AUTHOR_FADE = 4.0   # and where it has faded back to the master entirely
_NOTCH_AUTHOR_CAP = 25.0   # levels the master may sit away from the author's own
                           # paint inside that disc before the excess is pulled
                           # back. His own art swings 40 levels between
                           # neighbouring pixels here, so a cap under that
                           # leaves his drawing intact and catches only the
                           # network's overshoot (measured 70-80 levels)


def _notch_from_author(rgb, name, idx, size):
    """Hand the tail notch back to the author's own frame, upsampled.

    Every level tool in this file measures itself against his 32px art after
    downsampling ours onto his grid, and at the notch that comparison comes
    back clean - the two agree. The whole defect is how the network
    redistributed light *inside* one of his pixels: measured across the chord
    at t=0.97 on Wait, his own art interpolates as one smooth valley
    (143 131 124 118 109 93 75 62 40 18 3 16 34 50 61 67 74) where the master
    paints a plateau, a cliff and a black floor that never recovers
    (181 183 190 190 91 11 17 20 22 23 25 27 26 27 27 30 59). It is the same
    disease as the apex - a ramp flattened into a step - and it reads as the
    fold turning off its own chord and running along the tail spike (owner
    report 23.3; measured hook at t=0.98 is 1.4-1.6 units against the author's
    0.2 on Wait/AppStarting/UpArrow).

    So there is no reference finer than his pixels, and every author-anchored
    correction here is blind by construction: `_match_author_level` sees a
    12-level cap on an error that vanishes at 32px, `_edge_shadow_declutter`'s
    closing filter cannot bridge a dark region four units wide, and
    `_notch_declutter`'s local baseline sags into the same dark it is meant to
    lift. Tried, measured, none of them moves it (DEAD_ENDS.md).

    What is left is his own paint, resampled - not as a replacement but as a
    ceiling on how far the master may depart from it. Replacing the disc
    outright does land on his numbers exactly, and it hands the notch his 32px
    blur: a soft smudge sitting in otherwise crisp glass, plain to see at 128
    and 256. A cap leaves every pixel that already agrees with him alone, so
    the texture stays, and pulls back only the excursions - which here are the
    whole defect.

    Pulled back by blending toward his paint entire, not by a luma offset:
    moving luma and keeping the master's chroma left a green-yellow streak
    along the boundary, and scaling both blew the near-black into a red one.
    His paint carries its own colour, so a step toward it invents no hue.

    What it costs, so the trade is on the record. The fold tracker reads the
    darkest interior pixel per row, and the hook is dark, so some of what it
    was tracking was the defect: measured at 256, Wait resolved t=0.618..0.969
    before and t=0.618..0.844 after (fold_gap 0.875 -> 1.875), and
    AppStarting, whose entire six-row reading sat at t=0.852..0.969, resolves
    nothing at any size afterwards (`fold_unmeasured`, carried in
    metrics-known-issues.json). Against that, Wait's two standing failures
    clear - fold_luma_step 4.667 -> 2.333, fold_jag 44.0 -> 8.8 - and UpArrow
    goes 30.3 -> 1.0 and 98.5 -> 12.8. The author's own frames score no better
    than unmeasurable here either: `fold_profile` on `orig_frame` returns None
    for all six wedges at every size, so a fold this soft has never had a
    number behind it.

    Three narrower shapes were tried first and none of them works. A keep-out
    strip along the chord (correct only where the crease has already left it)
    keeps every tracker row and leaves the hook plainly visible, because the
    hook starts inside the strip. Capping only the positive deviation - the
    bright rim along the tail spike, which is what the eye first picks out -
    moves nothing: the rim is within 25 levels of his own paint. Adding back
    the difference blurred at 0.7-1.0 units, which would move the crease
    without softening it, cancels the dipole a displaced edge makes and leaves
    the hook where it was.
    """
    if name not in _NOTCH_AUTHOR_CURSORS:
        return rgb
    ch = _fold_chord(name, idx)
    if ch is None:
        return rgb
    (_, _), (nx_, ny_) = ch
    L = size / V.LOGICAL
    ys, xs = np.mgrid[0:size, 0:size]
    r = np.hypot((xs + 0.5) / L - nx_, (ys + 0.5) / L - ny_)
    w = np.clip((_NOTCH_AUTHOR_FADE - r) / (_NOTCH_AUTHOR_FADE - _NOTCH_AUTHOR_FULL),
                0.0, 1.0) * (_mask(name, idx, size) / 255.0)
    if w.max() < 1e-6:
        return rgb
    ref, _ = _resize(_orig(_key(name, idx)), size)
    dev = rgb.mean(-1) - ref.mean(-1)
    pull = np.clip(1.0 - _NOTCH_AUTHOR_CAP / np.maximum(np.abs(dev), 1e-6), 0.0, 1.0)
    return np.clip(rgb + (ref - rgb) * (pull * w)[..., None], 0, 255)


# The edge's shape, transferred from the analytic surface (NEXT.md, "Перенос
# формы кромки"). The master's cross-section from the contour inward carries an
# interior dip on 97% of stations where the author's own art carries none and
# the analytic bevel carries none; what is wrong is not the level or the colour
# but the way the glass rises off its edge. So only that shape is rewritten:
# per station corr(u) = (b(u) - b(e)) - (m(u) - m(e)), with `e` the far end of
# the ray inside the glass, which leaves the master's level, hue and every
# frequency along the arc untouched.
#
# Read and corrected in composite luma over _RIM_XFER_BG, not in raw RGB: the
# glass runs 0.35 alpha at the contour and 0.80 a unit in, so a correction
# sized in raw levels arrives at the eye scaled by whatever the alpha happens
# to be, and the dip the metric reads is the composited one.
_RIM_XFER = {"Arrow", "Help", "NO", "AppStarting"}   # cursors it runs on
_RIM_XFER_DEPTH = 1.0      # logical units inward a section is read over. Wider
                           # windows reach past the rim into the body and bring
                           # the fold's neighbourhood back with them - at 2.5
                           # Arrow's fold_jag went 53.9 -> 55.6 for a rim gain
                           # this window gets anyway.
_RIM_XFER_STEP = 0.125     # ...and the spacing of its samples
_RIM_XFER_STATION = 0.25   # logical units of arc between sections
_RIM_XFER_ARC = 1.0        # half-width of the mean that runs along the arc.
                           # Without it each ray prints its own correction and
                           # the edge comes out as a comb of them, plain to see
                           # along Arrow's top edge.
_RIM_XFER_ALPHA_LO = 0.35  # alpha the correction is held off below, and the
_RIM_XFER_ALPHA_HI = 0.60  # alpha it is in full at - also the divide's floor
_RIM_XFER_CORNER = 1.5     # logical units round a traced point the transfer
_RIM_XFER_CORNER_RAMP = 1.0  # is held off, and the units it ramps back in over
_RIM_XFER_BLEND = 0.35     # logical units of arc the sections are blended
                           # over when the correction is read back as a field
_RIM_XFER_CAP = 60.0       # levels of composite luma the correction may carry
_RIM_XFER_BG = 128.0       # the ground the section is composited on, the same
                           # one analyze.rim_layers reads over


@functools.lru_cache(maxsize=None)
def _rim_stations(name, idx):
    """Points and inward normals along the outline, every _RIM_XFER_STATION
    logical units of arc. Walks C.smooth's output - the polygon _mask_geom
    rasterises - so a station sits where the contour actually is."""
    out = []
    for poly in C.TRACED.get(name, {}).get("frames", [])[idx]["polys"]:
        pts = [np.array(p[:2], dtype=np.float64)
               for p in C.smooth([tuple(p) for p in poly])]
        n = len(pts)
        if n < 3:
            continue
        arr = np.array(pts)
        nxt = np.roll(arr, -1, axis=0)
        area = float((arr[:, 0] * nxt[:, 1] - arr[:, 1] * nxt[:, 0]).sum())
        sgn = -1.0 if area > 0 else 1.0          # inward, whichever way it winds
        acc = 0.0
        for i in range(n):
            a, b = pts[i], pts[(i + 1) % n]
            seg = float(np.hypot(*(b - a)))
            if seg < 1e-9:
                continue
            t = (b - a) / seg
            nrm = np.array([-t[1], t[0]]) * sgn
            s = _RIM_XFER_STATION - acc
            while s < seg:
                out.append((a + t * s, nrm))
                s += _RIM_XFER_STATION
            acc = (acc + seg) % _RIM_XFER_STATION
    if not out:
        return None
    return (np.array([p for p, _ in out]), np.array([n for _, n in out]))


def _sample1(field, x, y):
    """_sample for a single-channel field."""
    return _sample(field[..., None], x, y)[..., 0]


def _rim_transfer(rgb, name, idx, size):
    """Rewrite how the glass rises off its edge, keeping everything else."""
    if name not in _RIM_XFER:
        return rgb
    got = _rim_stations(name, idx)
    if got is None:
        return rgb
    pts, nrm = got
    L = size / V.LOGICAL
    us = np.arange(0.0, _RIM_XFER_DEPTH + 1e-9, _RIM_XFER_STEP)
    mask = _mask(name, idx, size).astype(np.float64)
    # Which way is inward is settled per station by probing half a unit each
    # way, not by the polygon's winding: the traced polys wind both ways and a
    # hole winds against its own outline.
    probe = np.stack([_sample1(mask, (pts[:, 0] + s_ * nrm[:, 0] * 0.5) * L - 0.5,
                               (pts[:, 1] + s_ * nrm[:, 1] * 0.5) * L - 0.5)
                      for s_ in (1.0, -1.0)])
    flip = np.where(probe[0] >= probe[1], 1.0, -1.0)[:, None]
    xs = (pts[:, 0:1] + nrm[:, 0:1] * flip * us) * L - 0.5
    ys = (pts[:, 1:2] + nrm[:, 1:2] * flip * us) * L - 0.5
    a = np.clip(_up_alpha(name, idx, size) * mask / 255.0, 0.0, 1.0)
    comp = rgb.mean(-1) * a + _RIM_XFER_BG * (1.0 - a)

    m = _sample1(comp, xs, ys)
    b = _sample1(_bevel_shading(name, idx, size), xs, ys)
    # A station whose ray leaves the silhouette has no section to read; the
    # first ramp of samples is the contour's own falloff and is skipped.
    ramp = int(np.ceil(0.5 / _RIM_XFER_STEP))
    keep = _sample1(mask, xs, ys)[:, ramp:].min(1) >= 250.0
    if keep.sum() < 8:
        return rgb

    # The section ends where the analytic surface stops climbing. On a thin
    # limb the medial ridge falls inside the window, and past it the analytic
    # profile descends again - transferring that descent prints the ridge into
    # the rim band as a layer of its own, which is what it did to Arrow_Down
    # and Handwriting (0.745 -> 0.78, 0.733 -> 0.79) while the wide cursors
    # gained. Anchoring at the crest instead ends every section on the same
    # feature it started from.
    e = np.maximum(np.argmax(b, axis=1), 2)[:, None]
    idxs = np.arange(b.shape[1])[None, :]
    inside = idxs <= e
    ba = np.take_along_axis(b, e, 1)
    ma = np.take_along_axis(m, e, 1)
    br = (b - ba) * inside
    mr = (m - ma) * inside
    # The analytic surface says how the glass should rise, not how far: its
    # swing is _BEVEL_DIFF, a number about the wedges, and printing that swing
    # on a master that rises by a different amount buys a new step where the
    # two disagree. Scaled per station to the master's own rise, the correction
    # is a change of path with the same endpoints - which is also why the
    # contour sample is not pinned to zero afterwards: pinning re-introduces
    # the step the scaling exists to avoid, and cost Arrow_Down 0.745 -> 0.79.
    k = np.divide(br[:, 0], mr[:, 0], out=np.ones(len(br)),
                  where=np.abs(mr[:, 0]) > 1e-6)
    br = br / np.clip(np.abs(k), 0.2, 5.0)[:, None]
    corr = br - mr
    corr[~keep] = 0.0
    w = max(1, int(round(_RIM_XFER_ARC / _RIM_XFER_STATION)))
    pad = np.concatenate([corr[-w:], corr, corr[:w]], 0)          # the arc closes
    kern = np.ones(2 * w + 1) / (2.0 * w + 1.0)
    corr = np.apply_along_axis(lambda c: np.convolve(c, kern, mode="valid"), 0, pad)
    corr = np.clip(corr, -_RIM_XFER_CAP, _RIM_XFER_CAP)
    corr[~keep] = 0.0

    # Composite levels back to the master's own, then read off as a field: the
    # depth the pixel sits at, against the sections blended round it.
    # Scattering the samples back along their own rays and normalising by their
    # weight was tried first and is worse in both orders - the rays leave whole
    # pixels untouched between them, and blurring the sums to fill those smears
    # the correction across depth, which is the one axis it is about (Arrow
    # 0.65 -> 0.80).
    #
    # Where the glass is barely there the divide would print the correction as
    # an outline - a bright thread right on the contour - and it buys nothing:
    # that ramp is the falloff itself and rim_layers skips it. So the
    # correction fades out with the alpha it is divided by.
    a_ray = _sample1(a, xs, ys)
    corr = corr / np.maximum(a_ray, _RIM_XFER_ALPHA_HI)
    corr = corr * np.clip((a_ray - _RIM_XFER_ALPHA_LO)
                          / (_RIM_XFER_ALPHA_HI - _RIM_XFER_ALPHA_LO), 0.0, 1.0)
    d = _edge_distance_at(name, idx, size)
    ys_i, xs_i = np.mgrid[0:size, 0:size]
    px = (xs_i + 0.5) / L
    py = (ys_i + 0.5) / L
    ui = np.clip(d / _RIM_XFER_STEP, 0.0, len(us) - 1.001)
    k0 = ui.astype(np.int32)
    k1 = np.minimum(k0 + 1, len(us) - 1)
    fu = ui - k0
    # Blended over the stations near the pixel, not taken from the nearest one.
    # A nearest-station lookup partitions the glass into Voronoi cells and each
    # cell prints its own section, so the correction lands as flat facets with
    # straight seams between them - plain to see at the point, where the cells
    # fan out (looked at on Help at 512, 4x). The weight is on the arc offset
    # alone: the pixel's own depth is already the axis being interpolated, and
    # leaving it in the distance would flatten the weights the deeper it sits.
    delta = np.zeros((size, size))
    var = 2.0 * _RIM_XFER_BLEND ** 2
    for r0 in range(0, size, 32):
        sl = slice(r0, r0 + 32)
        dx = px[sl, :, None] - pts[None, None, :, 0]
        dy = py[sl, :, None] - pts[None, None, :, 1]
        arc2 = np.maximum(dx * dx + dy * dy - (d[sl] ** 2)[..., None], 0.0)
        w = np.exp(-arc2 / var)
        c = (corr[:, k0[sl]] * (1.0 - fu[sl]) + corr[:, k1[sl]] * fu[sl])
        delta[sl] = np.einsum("yxs,syx->yx", w, c) / np.maximum(w.sum(2), 1e-9)
    # Held off around the traced points. A section is a reading along one
    # normal, and at a point there is no one normal: the rays of the stations
    # either side of it cross, their sections disagree, and the blend of two
    # disagreeing sections prints a dark wedge in the point itself - looked at
    # on Help at 128 and 256, 10x. Where the geometry cannot define the
    # correction it is not applied.
    for cx_, cy_ in _sharp_corners(name, idx):
        r_ = np.hypot(px - cx_, py - cy_)
        delta = delta * np.clip((r_ - _RIM_XFER_CORNER) / _RIM_XFER_CORNER_RAMP,
                                0.0, 1.0)
    delta = delta * (mask / 255.0) * (d <= _RIM_XFER_DEPTH)
    return np.clip(rgb + delta[..., None], 0, 255)


# The fold's own shape, transferred the same way, along its length instead of
# across the edge (NEXT.md, fork item 1: fix the fold with the method rather
# than protect it from it). The rim transfer above rewrites how the glass rises
# off its edge, and on a thin wedge the fold's neighbourhood is the same band of
# pixels, so it arrives at the fold too - keep-outs by chord, by tracked path
# and by ceiling were all tried and each either broke the crease or ate the
# gain. Here the crease is part of the target: its brightness along its own
# length is made to follow the analytic surface's, which varies smoothly, while
# its depth across the crease - the dark line itself - is left alone.
_FOLD_XFER = set()         # cursors the fold transfer runs on
_FOLD_XFER_BAND = 1.2      # logical units either side of the crease it reaches
_FOLD_XFER_STEP = 0.125    # sample spacing across the crease
_FOLD_XFER_TS = 0.02       # spacing along the crease, as a share of the chord
_FOLD_XFER_SMOOTH = 5      # samples along the crease the correction is averaged
                           # over, so a single dark pixel cannot set the target
_FOLD_XFER_TREND = 0.15    # share of the chord the slow gradient is kept over
_FOLD_XFER_CAP = 6.0       # levels of composite luma the correction may carry
_FOLD_XFER_ENDS = 0.15     # share of the chord at each end the correction fades
                           # over: the point and the tail notch are drawn
                           # features, not fold, and both are already owned by
                           # _tip_relight and _notch_from_author


def _fold_transfer(rgb, name, idx, size):
    """Make the crease's brightness along its length follow the analytic one."""
    if name not in _FOLD_XFER:
        return rgb
    got = _fold_offsets(name, idx)
    if got is None:
        return rgb
    tso, offs, ch = got
    L = size / V.LOGICAL
    p0 = np.array(ch[0], dtype=np.float64)
    p1 = np.array(ch[1], dtype=np.float64)
    dvec = p1 - p0
    span = float(np.hypot(*dvec))
    if span < _FOLD_MIN_SPAN:
        return rgb
    u = dvec / span
    nv = np.array([-u[1], u[0]])
    ts = np.arange(0.0, 1.0 + 1e-9, _FOLD_XFER_TS)
    qs = np.arange(-_FOLD_XFER_BAND, _FOLD_XFER_BAND + 1e-9, _FOLD_XFER_STEP)
    # centred on where the crease actually runs, not on the chord: the master
    # puts it up to _FOLD_CAP off the line, and a template read off the chord
    # would be reading half glass and half crease.
    off = np.interp(ts, tso, offs)
    cx = p0[0] + dvec[0] * ts + nv[0] * off
    cy = p0[1] + dvec[1] * ts + nv[1] * off
    xs = (cx[:, None] + nv[0] * qs[None, :]) * L - 0.5
    ys = (cy[:, None] + nv[1] * qs[None, :]) * L - 0.5

    mask = _mask(name, idx, size).astype(np.float64)
    a = np.clip(_up_alpha(name, idx, size) * mask / 255.0, 0.0, 1.0)
    comp = rgb.mean(-1) * a + _RIM_XFER_BG * (1.0 - a)
    m = _sample1(comp, xs, ys)
    b = _sample1(_bevel_shading(name, idx, size), xs, ys)
    solid = _sample1(mask, xs, ys) >= 250.0
    keep = solid.all(1)
    if keep.sum() < 8:
        return rgb

    # Along the crease, not across it: each column of the band is compared with
    # its own mean, so the crease keeps its depth and only its variation down
    # the line is rewritten.
    def demean(v):
        # High-passed, not de-meaned against the whole chord: a crease is
        # legitimately brighter at one end than the other (fold_profile grades
        # the step between neighbouring rows for exactly that reason), so only
        # the variation faster than _FOLD_XFER_TREND is the render's to fix.
        w = int(round(_FOLD_XFER_TREND / _FOLD_XFER_TS)) | 1
        pad = np.pad(v, ((w // 2, w // 2), (0, 0)), mode="edge")
        k = np.ones(w) / w
        trend = np.apply_along_axis(lambda c: np.convolve(c, k, mode="valid"), 0, pad)
        return np.where(keep[:, None], v - trend, 0.0)

    corr = demean(b) - demean(m)
    k = np.ones(_FOLD_XFER_SMOOTH) / _FOLD_XFER_SMOOTH
    corr = np.apply_along_axis(
        lambda c: np.convolve(np.pad(c, _FOLD_XFER_SMOOTH // 2, mode="edge"), k,
                              mode="valid"), 0, corr)
    corr = np.clip(corr, -_FOLD_XFER_CAP, _FOLD_XFER_CAP)
    corr *= np.clip(np.minimum(ts, 1.0 - ts) / _FOLD_XFER_ENDS, 0.0, 1.0)[:, None]
    corr *= (1.0 - np.abs(qs) / _FOLD_XFER_BAND)[None, :] ** 2
    corr = corr / np.maximum(_sample1(a, xs, ys), 0.25)
    corr[~keep] = 0.0

    acc = np.zeros((size, size))
    wgt = np.zeros((size, size))
    sx = np.clip(xs, 0, size - 1.001)
    sy = np.clip(ys, 0, size - 1.001)
    x0, y0 = sx.astype(np.int32), sy.astype(np.int32)
    fx, fy = sx - x0, sy - y0
    for dx, dy, f in ((0, 0, (1 - fx) * (1 - fy)), (1, 0, fx * (1 - fy)),
                      (0, 1, (1 - fx) * fy), (1, 1, fx * fy)):
        xi = np.minimum(x0 + dx, size - 1)
        yi = np.minimum(y0 + dy, size - 1)
        np.add.at(acc, (yi, xi), corr * f)
        np.add.at(wgt, (yi, xi), f)
    delta = np.where(wgt > 1e-6, acc / np.maximum(wgt, 1e-6), 0.0) * (mask / 255.0)
    return np.clip(rgb + delta[..., None], 0, 255)


_TIP_ANCHOR_SMOOTH = 3.5   # logical units the band's anchor level is smoothed
                           # over. Wide enough that nothing structural survives
                           # it - the fold this stage replaces is a hairline and
                           # the master's invented second point beside it is
                           # about a unit across - narrow enough that the sheen,
                           # which sweeps over a third of the cursor, does.


def _band_level(field, band, size):
    """The band's own level as a smooth field: a band-weighted blur of `field`.

    Written as a weighted blur rather than a plain one so the level does not
    drift toward whatever the master painted outside the band - near the point
    the band is a couple of units across and a plain blur of that radius is
    mostly background inpainting."""
    num = _smooth1(field * band, _TIP_ANCHOR_SMOOTH, size)
    den = _smooth1(band, _TIP_ANCHOR_SMOOTH, size)
    flat = float((field * band).sum() / max(float(band.sum()), 1e-6))
    return np.where(den > 1e-4, num / np.maximum(den, 1e-4), flat)


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
#
# Adding `_bevel_shading` on top of that colour - the same trade `_SYNTH_BEVEL`
# makes for the seven flat cursors, and it is keyed per frame so it drops
# straight in - was tried 2026-08-13 and is out. At 256 it does put a ridge and
# two facets back into frames 3 and 4, which is a fair reading of the glass
# beside them. At 512 the interior fills with straight creases meeting at
# angles: these outlines are traced from raster art and carry far more vertices
# than a `_SYNTH_BEVEL` shape, so the distance field ridges at every one of
# them. That is the facet dead end recorded against `_tip_relight`, reached
# from the other side, and crumpled paper is worse than soft glass.
#
# Superseded 2026-08-21 and left empty rather than deleted, because the two
# dead ends above are still the reason the third way is shaped as it is. The
# author's own colour is whole but it comes from 32px, and past 128 it reads as
# the grey smudge NEXT.md 23.8 complains about - "серые мутные пятна без единой
# грани", which is this substitution seen at size. What replaces it is neither
# the net's output for these frames nor a field computed from the outline: it
# is the colour of the frames either side, registered onto this frame's own
# silhouette. See _MATERIAL_BASIS.
# Kept as a name because tools/loop.py's diagnosis tree asks about it, and
# because the two dead ends above are still why the third way is shaped the way
# it is. The substitution itself now runs through _MATERIAL_BASIS, at the same
# point in frame_image this set used to be read at.
_BROKEN_COLOUR = set()

_FREEZE_UNIT = 2.0       # logical units below which detail counts as a line.
                         # Was 0.6, which froze hairlines and let every coarser
                         # interior structure move. Mapped the same way the note
                         # below describes - per-frame deviation from the cycle
                         # mean - the author's motion is a ribbon on the outline
                         # with flares at the points and a dark, still interior;
                         # ours carried a web of moving lines right across the
                         # body. That web is the "inner elements wobbling" the
                         # owner reported. At 2.0 it goes and the ribbon stays:
                         # the rendered frames still read alive side by side,
                         # and the sweep keeps 0.80 of the author's own on Hand
                         # (10.91 against 13.60), 0.86 on Wait, 0.89 on
                         # AppStarting, all over the 0.75 the gate asks. Hand's
                         # `temporal_fold` comes down 1.022 -> 1.005 with it.
_FREEZE_RIM = 1.5        # logical units in from the silhouette's own edge that
                         # stay live - the author's sheen is a thin bright band
                         # travelling along the rim and over the points (mapped
                         # 2026-08-XX: per-frame deviation from the cycle mean,
                         # his is a hairline on the outline, ours was a broad
                         # smear over the body), which is detail finer than
                         # _FREEZE_UNIT and so was exactly what the freeze held
                         # still. Owner's call: the rim may jitter, the interior
                         # may not.
_FREEZE_RIM_FADE = 1.2   # logical units the release fades out over, so there is
                         # no seam between the live rim and the frozen interior
_FREEZE_FOLD = 1.2       # logical units either side of the fold chord that stay
                         # frozen whatever the edge distance says - see
                         # _freeze_weight


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
    else:
        # _resize's Lanczos has negative side-lobes, and premultiplying does
        # not cancel them: each channel rings by its own amount, set by how
        # much that channel swings across the edge being resized. At a sharp
        # point three edges meet in a handful of pixels (rim, lit core,
        # transparency) and every channel swings hard, so at 512 -> 32 the R
        # channel of this glass - always the largest swing, rim to core - can
        # ring negative and clip to zero while B, which barely moves in the
        # true image, keeps a small positive remainder. Divided back through
        # alpha that remainder survives as a blue fleck on an otherwise warm
        # rim: measured on Wait's own point, (0, 0, 22) at 44% alpha where the
        # source either side is a warm near-black. Only visible at 32px, where
        # the point is a couple of pixels wide and every channel is ringing at
        # once; not worth guarding every resize against for that.
        # _declutter_hue_outliers already exists for a stray hue the master
        # invents (see there) and needs nothing new to catch this one too - a
        # channel clipped by ringing is exactly a pixel whose chroma has
        # swung away from the frame's own colour. Tuned stronger than the
        # 512-anchor pass: that one runs on a frame where the worst it is
        # guarding against is a thin hallucinated fringe several pixels wide,
        # here the whole defect is one or two pixels at a silhouette point,
        # already at the size it ships at - there is no second pass downstream
        # to catch what this one leaves. Measured on Wait's own point at 32px,
        # (0, 0, 22) at 44% alpha: the default threshold only pulls it to
        # (1, 1, 16), still visibly blue; this one reaches (2, 2, 7).
        got = _hue_outlier_weight(name, idx, rgb, 4.0, 15.0, 0.5, 1.0)
        if got is not None:
            lum, chroma, outlier = got
            rgb = lum[..., None] + chroma * (1 - outlier)[..., None]
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
    hold = _freeze_weight(name, idx, size)[..., None]
    fine_ref = ref - _smooth3(ref, _FREEZE_UNIT, size)
    fine_own = rgb - _smooth3(rgb, _FREEZE_UNIT, size)
    return np.clip(rgb + hold * (fine_ref - fine_own), 0, 255)


@functools.lru_cache(maxsize=None)
def _freeze_weight(name, idx, size):
    """How much of each pixel's fine detail is held to the reference frame.

    One inside the glass, zero along the rim. The freeze was written against
    line jitter in the interior and it works, but it is indiscriminate: it also
    holds the one thing the animation is made of. The author's sheen, measured
    as each frame's deviation from the cycle's own mean, is a hairline running
    along the outline and flaring at the points - finer than _FREEZE_UNIT
    everywhere, so all of it was being replaced by frame 0's. Ours came out at
    a third of his swing on Hand and about three quarters on Wait and
    AppStarting, and read dead at exactly the places the eye follows.

    Releasing the rim and nothing else is the owner's own rule for this
    ("внешние дрожания - ничего страшного, главное чтобы слои не дёргались
    внутренние"): the fold, the lit facet and the points' inner fill are all
    further in than _FREEZE_RIM and stay frozen."""
    d = _edge_distance_at(name, idx, size)
    hold = np.clip((d - _FREEZE_RIM) / _FREEZE_RIM_FADE, 0.0, 1.0)
    # The fold is the one interior line that runs out to where the glass is
    # thinner than _FREEZE_RIM - it ends in the tail notch - so a release keyed
    # on edge distance alone lets go of its last stretch, and that is the line
    # the whole freeze was written for. Measured: releasing it took Hand's
    # fold_wander 0.015 -> 0.033 and temporal_fold 1.001 -> 1.043, Wait's
    # fold_jag 44.4 -> 51.3. Held explicitly, by distance to its own chord.
    ch = _fold_chord(name, idx)
    if ch is not None:
        (ax, ay), (bx, by) = ch
        L = size / V.LOGICAL
        ys, xs = np.mgrid[0:size, 0:size]
        px, py = (xs + 0.5) / L, (ys + 0.5) / L
        vx, vy = bx - ax, by - ay
        den = vx * vx + vy * vy
        t = np.clip(((px - ax) * vx + (py - ay) * vy) / max(den, 1e-9), 0.0, 1.0)
        dist = np.hypot(px - (ax + t * vx), py - (ay + t * vy))
        near = np.clip((_FREEZE_FOLD + _FREEZE_RIM_FADE - dist) / _FREEZE_RIM_FADE,
                       0.0, 1.0)
        hold = np.maximum(hold, near)
    return hold


_LEGACY_TEMPER = 0.5    # how much of _match_author_level/_tip_relight/_sat_match
                         # survives. Isolated 2026-08-XX against `58a28b72`
                         # (the render the owner asked to get back toward):
                         # six post-master corrections were tried as suspects
                         # for a softer tail-corner highlight the owner
                         # reported (_match_author_level, _tip_relight,
                         # _sat_match, _hide_ghost, _declutter_hue_outliers,
                         # _declutter_engraved_detail). At full strength the
                         # tail corner averages 12.2 levels away from that
                         # render at the crop the owner pointed at; with all
                         # six off, 0.1. No single stage moved the number much
                         # alone (disabling any one dropped it only to ~11) -
                         # the softening is the six compounding, not one bug.
                         #
                         # Tempering only these three reaches 5.8 of the same
                         # 12.2, essentially the whole effect on its own
                         # (checked: adding the other three at 0.5 too only
                         # reached 6.1) - the other three barely touch this
                         # corner (Arrow never reaches `_hide_ghost`'s
                         # near-transparent band or Help's engraved detail).
                         # They were tried at 0.5 regardless and reverted:
                         # `_declutter_hue_outliers`/`_declutter_engraved_detail`
                         # run inside `_master_raw` for every cursor, not just
                         # the six wedge tips, and halving them let their own
                         # defects back in where they had nothing to do with
                         # this report - Help's fold_gap 0.125 -> 0.5 (the
                         # engraved question mark softening), SizeAll's
                         # fold_jag 53.7 -> 119.8. `_hide_ghost` at 0.5 failed
                         # the gate outright: `ghost_rgb` up to 14..38 levels
                         # against a 0.5 tolerance - the interpolated-frame
                         # colour disagreement it exists to prevent (see its
                         # own docstring), reintroduced.


_TEMPER_K = {"level": 1.0,
             "relight": _LEGACY_TEMPER,
             "sat": _LEGACY_TEMPER}
# Per-stage strength, split out of the single `_LEGACY_TEMPER` knob so the three
# stages can be isolated: they were tempered together because they were measured
# together, not because they cost the same. `CGR_TEMPER=level:1,relight:0.5`
# overrides for a measurement run without editing the file.
#
# `level` is back at full strength, isolated 2026-08-12. `_match_author_level`
# is what straightens the fold, and halving it was the whole of the fold debt
# the temper commit added: at 1.0 `fold_jag` leaves Arrow/Hand/Arrow_Down
# outright and AppStarting's `fold_luma_step` drops 9.03 -> 6.63, sixteen wedge
# failures down to fourteen. It was never what softened the tail corner the
# owner reported - measured on the same crop the isolation used, going 0.5 -> 1.0
# moves the two tail corners by 0.06 and 0.07 levels on average (2.0 at the
# single worst pixel), against the 6.15 levels tempering all three bought back.
# So this stage was paying the fold's bill for a corner it does not touch.
#
# `relight` went back to full for the same reason, isolated the same way: at 1.0
# it costs 0.00 levels at both of Arrow's tail corners - the crop the owner's
# report was about - while clearing UpArrow's `tip_contrast` outright and taking
# Hand's `temporal_fold` 1.022 -> 1.005 and Wait's `fold_jag` off the list. Its
# whole cost is at the apex (4.6 levels on average there, and Arrow_Down's point
# contrast 0.090 -> 0.069), which is the axis already under review in NEXT.md
# item 15. Ten gate regressions down to eight.
#
# `sat` is the one that earns its temper and keeps it. It costs nothing at any
# of Arrow's corners - `_sat_match` only runs on saturated cursors, so it never
# reaches that render at all - but at full strength it puts two fold failures
# back, Arrow_Down `fold_jag` 84.4 -> 89.1 and Wait 44.4 -> 44.8.
if os.environ.get("CGR_TEMPER"):
    for _part in os.environ["CGR_TEMPER"].split(","):
        _s, _, _v = _part.partition(":")
        _TEMPER_K[_s.strip()] = float(_v)


_TEMPER_PER_CURSOR = {}
# Empty, and the entry that was here is worth keeping as a warning. `relight`
# was put to full strength on the numbers - it read closer to the author's apex
# on three wedges of four and took two other failures off the gate - and
# Arrow_Down, the one cursor the numbers said lost by it, got a half-strength
# exception here. Both were wrong. At full strength the stage dissolves the
# inner tip: the lit inner facet that carries its own sharp point, and the dark
# line separating it from the outer silhouette, wash into one flat field. The
# owner saw it on sight; no metric in tools/analyze.py did. `tip_contrast` rose
# (UpArrow 0.049 -> 0.074), and the obvious sharpness proxy - mean luma-gradient
# magnitude in the apex disc - rose too (UpArrow 0.32 -> 0.43). Both were
# measuring a flat wash as an improvement. See NEXT.md item 22.


def _temper(before, after, name, stage):
    """Blend a correction's output back toward its input by `_TEMPER_K[stage]`,
    but only for the six wedge tips the isolation above was measured against -
    every other cursor (NO, Help, SizeAll, ...) keeps the full correction, it
    was never part of the `58a28b72` comparison and regressed when included.
    """
    if name not in _WEDGE_TIPS:
        return after
    k = _TEMPER_PER_CURSOR.get((name, stage), _TEMPER_K[stage])
    return before * (1.0 - k) + after * k


_LEVEL_CAP = 12.0        # levels the whole-glass author-level correction may
                         # move a pixel, before smoothing - a cap, not a target,
                         # so it corrects where the master is genuinely off
                         # without inventing contrast finer than his own pixels
_LEVEL_SMOOTH = 4.5      # logical units the correction is blurred by on the
                         # way back up from his 32px grid - narrower and it
                         # reads as a stencil of his pixels and shows up as
                         # fold-curvature noise where the tracker follows it.
                         # Measured on UpArrow, the worst-hit cursor: fold_gap
                         # regressed to 2.25 at smooth=3.0 (from 1.69 with the
                         # correction off) and is back to 1.69 at 4.5, and
                         # fold_wander drops from 0.236 to 0.198. 6.0 buys
                         # little more wander (0.176) for worse colour
                         # (delta_e 3.62 -> 3.70) - diminishing returns past 4.5.
_LEVEL_CAP_NATIVE = 40.0 # ...and the cap on his own grid, where neither guard
                         # above has anything to guard against. Both of them
                         # exist for one reason - the correction is measured on
                         # his 32px pixels and then stretched over ours, so a
                         # loose cap or a sharp edge stamps his grid onto a
                         # render several times finer. At 32 there is no stretch:
                         # his pixel is our pixel, "finer than his own pixels"
                         # is not a thing that can happen, and there is no
                         # stencil to blur out.
                         #
                         # What the two guards were costing there is the dark
                         # outline. His 32px art carries a full logical unit of
                         # near-black around the silhouette; ours inherits a
                         # fifth of a unit from art/ai512 and averages it away
                         # on the trip down, so the darkest pixel over the mask
                         # composited on 240 came out 145 against his 106 and
                         # the cursor read washed out on a light desktop. 12
                         # levels cannot cross a 40-level gap and a 4.5-unit
                         # blur cannot rebuild a 1-unit rim.
                         #
                         # So both relax toward his grid, on the same ramp:
                         # nothing changes at 64 and above, 48 gets half, and 32
                         # is corrected at his own resolution. Judged at 32 on
                         # both grounds beside his art, eight wedge cursors: the
                         # rim arrives where his is and nowhere else, and no
                         # cursor picks up a stencil. p99 |luma-240| over the
                         # mask, shipped -> corrected against his own: Arrow
                         # 89.8 -> 98.9 (101.3), UpArrow 90.6 -> 100.3 (102.4),
                         # Hand 87.7 -> 101.5 (101.3), Wait 159.0 -> 166.5
                         # (167.1). 60 levels buys another point on Arrow and
                         # overshoots Wait past him, 20 gets half the rim.


def _resample_signed(a, size):
    """Plain float Lanczos resize, no clamp - for a signed correction field,
    not a colour channel."""
    if a.shape[0] == size:
        return a
    return np.asarray(Image.fromarray(a.astype(np.float32), mode="F")
                       .resize((size, size), Image.LANCZOS), dtype=np.float64)


def _match_author_level(rgb, name, idx, size):
    """Restore the author's own light level across the whole glass, not just
    at the points: his 32px frame minus ours downsampled to it, capped at
    _LEVEL_CAP levels, smoothed by _LEVEL_SMOOTH logical units on the way back
    up, frozen per cycle (one keyframe's correction for the whole sheen loop,
    the same idiom as _freeze_lines) so a sheen-only animation cannot pick up
    a per-frame wobble from it.

    This is what straightens the lit sheet's boundary - DEAD_ENDS.md, "The
    line that slides right": the master crowds it against the rim near the
    point and only opens out further down, which is what item 3 in NEXT.md
    reads as the dividing chord failing to bisect the cursor. `_tip_relight`
    already owns the point itself; this stays out of its band by running
    first and letting the point's own weighted-mean anchor absorb whatever
    shift landed there.

    Two jobs, two guards. Straightening the boundary is a wedge-tip job and runs
    at every size on `_WEDGE_TIPS`, as it always has. Restoring his dark rim is a
    small-size job (see `_LEVEL_CAP_NATIVE`) and belongs to any wedge-bodied
    cursor whose master washes out on the way down, so the other three get it
    only where the correction is still near his own grid. Letting them have it
    everywhere was tried and costs six fold readings and buys nothing: Help
    `fold_luma_step` 20.500 -> 22.867 and `fold_wander` 0.274 -> 0.275,
    Handwriting `fold_wander` 0.225 -> 0.287, NO 0.014 -> 0.020 and
    `fold_luma_step` 1.433 -> 1.667. That is the stencil the blur exists to
    prevent, on three cursors it was never tuned for."""
    # how far above his grid this size is: 0 on it, 1 at twice it and beyond
    up = min(max((size - 32) / 32.0, 0.0), 1.0)
    if name not in (_WEDGE_TIPS if up >= 1.0 else _EDGE_SHADOW_CURSORS):
        return rgb
    src = 0 if name in INTERP else idx
    key = _key(name, src)
    m32 = _mask(name, src, 32) / 255.0
    ours32, _ = _resize(np.dstack([_master_rgb(name, src, size), _mask(name, src, size)]), 32)
    orig32 = np.asarray(original(name, src), dtype=np.float64)[..., :3]
    cap = _LEVEL_CAP_NATIVE + (_LEVEL_CAP - _LEVEL_CAP_NATIVE) * up
    diff32 = np.clip(orig32 - ours32, -cap, cap) * m32[..., None]
    diff = np.dstack([_resample_signed(diff32[..., c], size) for c in range(3)])
    diff = _smooth3(diff, _LEVEL_SMOOTH * up, size)
    m = _mask(name, src, size) / 255.0
    return np.clip(rgb + diff * m[..., None], 0, 255)


_FACET_CURSORS = {"Arrow"}     # the two glass surfaces are built from the
                               # traced landmarks instead of being taken on
                               # trust from the master (NEXT.md 30). Arrow only:
                               # on Arrow_Down and UpArrow the same stage buys
                               # less facet contrast at the point than it spends
                               # in point contrast against the desktop, measured
                               # over three percentiles and three rim widths
                               # (NEXT.md 30.3)
_FACET_FEATHER = 0.40          # logical units the two facets blend over out in
                               # the body, where the wedge is wide
_FACET_RAMP = 3.0              # logical units from the point over which that
                               # blend opens up from nothing. At the point
                               # itself the two surfaces meet along a line: a
                               # blend of constant width is wider than the glass
                               # there, and two surfaces blended across the
                               # whole width of a wedge are one surface
_FACET_GAIN_CAP = 4.0          # widest facet ratio that may be imposed
_FACET_REF = 512               # size the two ratios are read at, once
_FACET_BODY_BAND = (8.0, 20.0) # logical units from the point the ratio between
                               # the two surfaces is read over: the body, where
                               # the master is trustworthy and reads 2.00-2.10
                               # against the author's 1.91-2.07
_FACET_BIN = 0.25              # logical units per station of the along-chord
                               # brightness profile the tip zone keeps
_FACET_MIX = 1.0               # how much of the rebuilt point is used against
                               # the master's own. Full is the most faithful to
                               # the author on both readings that matter here
                               # and costs raw point contrast, which the ratchet
                               # counts upward-only (NEXT.md 30)
_FACET_PCT = 20                # percentile of each section that counts as its
                               # dark surface, and its mirror as the lit one.
                               # Medians of the whole section were tried and
                               # flatten the ramp: the brightening towards the
                               # point lives in the lit facet alone, and a
                               # statistic that mixes both surfaces cannot see it.
                               # The quartile is the principled reading and lands
                               # the point exactly on the body's own facet ratio
                               # (1.96 against 1.98) - and on the author's own
                               # point contrast, a per cent under it. This one is
                               # a fifth: ratio 2.12, and the point still reads
                               # half again as strongly as his (NEXT.md 30.3)
_FACET_TIP_ZONE = 2.5          # units of point the correction is full over, and
_FACET_TIP_FADE = 2.0          # units it fades out over past that
_FACET_KEEP_RIM = 0.25         # logical units of edge the master's own rim
                               # keeps, blending to the rebuilt facets over the
                               # same width again. The rim is what carries the
                               # point against the desktop, and it is a different
                               # structure from the two surfaces inside it
_TIP_GLASS = 1.5               # logical units of point whose translucency is
                               # carried out from deeper inside the glass
_FACET_MEASURING = set()       # guard: the gain is read off the finished frame,
                               # and reading it must not apply itself


def _smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


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


def _facet_frame(name, idx, size):
    """Signed distance to the A-J chord and distance along it, logical units."""
    lm = _landmarks(name, idx)
    a = np.array(lm[0]); j = np.array(lm[2])
    d = (j - a) / max(float(np.hypot(*(j - a))), 1e-9)
    nv = np.array([-d[1], d[0]])
    s = size / V.LOGICAL
    ys, xs = np.mgrid[0:size, 0:size]
    px = xs / s - a[0]
    py = ys / s - a[1]
    return px * nv[0] + py * nv[1], px * d[0] + py * d[1]


@functools.lru_cache(maxsize=None)
def _facet_gain(name, idx):
    """How much of its own facet contrast the point has lost.

    Median linear luminance either side of the chord, in a band at the point
    and in a band out in the body, both on the finished frame at _FACET_REF.
    The body is the target and it is not a guess: measured this way Arrow's
    body separates its two surfaces by 2.00-2.10 and the author separates his
    by 1.91-2.07 - the same glass. Inside two units of the apex ours falls to
    1.06, which is what "the point stops reading as two surfaces" is, in a
    number. Nothing is chosen by hand; the cursor is compared with itself."""
    if _landmarks(name, idx) is None:
        return 1.0
    size = _FACET_REF
    sd, t = _facet_frame(name, idx, size)
    ed = _edge_distance_at(name, idx, size)
    inside = (_mask(name, idx, size) > 250) & (ed > 0.35)
    _FACET_MEASURING.add(name)
    try:
        rgb = np.asarray(frame_image.__wrapped__(name, idx, size), dtype=np.float64)[..., :3]
    finally:
        _FACET_MEASURING.discard(name)
    y = V.srgb_to_linear(np.clip(rgb, 0, 255).astype(np.uint8)) @ _LUMA

    def ratio(band):
        m = inside & (t >= band[0]) & (t < band[1])
        u, l = m & (sd > 0), m & (sd < 0)
        if u.sum() < 20 or l.sum() < 20:
            return None
        return float(np.median(y[l])) / max(float(np.median(y[u])), 1e-9)

    body = ratio(_FACET_BODY_BAND)
    if not body or body <= 0:
        return 1.0
    return float(np.clip(body, 1.0 / _FACET_GAIN_CAP, _FACET_GAIN_CAP))


_TIP_LEVEL_CURSORS = {"Arrow", "Arrow_Down", "Hand", "UpArrow"}
                         # the wedges whose point is relit. AppStarting and Wait
                         # are wedges too and are deliberately out: their level
                         # near the apex is part of the travelling highlight and
                         # belongs to lightanim. Measured, not assumed - with
                         # them in, AppStarting `tip_extreme_contrast` goes
                         # 0.138 -> 0.066 against the author's own 0.069, a new
                         # failure, and Wait 0.130 -> 0.083.
_TIP_LEVEL_BAND = 3.0    # logical units down the fold chord the correction holds
_TIP_LEVEL_FADE = 1.5    # ...and the units it fades out over past that


def _tip_level(rgb, name, idx, size):
    """Bring the point's own luma to the author's. One number, not a field.

    The wedge points ship 18-30 levels lighter than the author draws them, at
    every rung: the tip zone reads 115-129 against his 99-102, which on a grey
    desktop is the cursor's own point sitting at the background's value and
    disappearing into it. Alpha is not the problem and never was - at 32 ours
    is 0.55-0.57 against his 0.54-0.55 - and neither is the silhouette or the
    width of the rim. Only the level. So only the level moves here: luma over a
    band along the fold chord, chroma and alpha and geometry untouched.

    Deliberately one constant over the band, and the two better-looking
    alternatives were built and measured before this was settled (NEXT.md 45):

    Solving the mask's own attenuation out - the band is weighted, so a shift
    of d delivers d * sum(w*w)/sum(w) and lands short - does bring the mean
    error to zero (+4.4/+6.6/+4.1/+3.5 -> +0.8/+1.8/+1.0/+0.2) and buys it with
    local overshoot: Arrow's profile then reads -8 at the point, +3 in the
    middle, +10 further down, where this one never crosses -2.5.

    Fitting a correction that varies along the chord flattens the profile
    outright (mean under 1 level, span +/-7 instead of +/-35) and breaks the
    fold: UpArrow `fold_gap` 0.125 -> 0.750, Hand `fold_wander` 0.207 -> 0.568,
    Arrow_Down `fold_jag` 55.8 -> 89.4. Smoothing it does not help - sigma 1.5,
    4.0 and 8.0 along t give fold numbers identical to the digit. The crease
    runs along the same axis the correction would vary on, so any tilt of the
    level along it is read by the tracker as the crease moving. A constant
    cannot do that, and this one leaves every fold reading where it found it.

    What is left is +2.7..+8.1 levels of the author's own falloff, and that is
    the price of not touching the fold. Closing it needs the correction to live
    where the fold lives, in `_tip_relight`'s own trough model, so that one
    object owns both - not a second luma stage arguing with the first.

    Which makes this stage provisional by design. It is one number because one
    number is all that can be added here without a fight; the moment
    `_tip_relight` owns the longitudinal level as well, this comes out. Do not
    layer a second mechanism on top of it - see STATUS.md, the fold-relight
    branch."""
    if name not in _TIP_LEVEL_CURSORS:
        return rgb
    ch = _fold_chord(name, idx)
    if ch is None:
        return rgb
    (tx, ty), (nx_, ny_) = ch
    dx, dy = nx_ - tx, ny_ - ty
    seg = float(np.hypot(dx, dy))
    if seg < 1e-6:
        return rgb
    ux, uy = dx / seg, dy / seg
    L = size / V.LOGICAL
    ys, xs = np.mgrid[0:size, 0:size]
    t = ((xs + 0.5) / L - tx) * ux + ((ys + 0.5) / L - ty) * uy
    w = np.clip((_TIP_LEVEL_BAND + _TIP_LEVEL_FADE - t) / _TIP_LEVEL_FADE, 0.0, 1.0)
    w = np.where(t < -0.5, 0.0, w)
    w = w * w * (3 - 2 * w)
    # weighted by what will actually be visible, not by the silhouette: a band
    # pixel under a tenth of glass should not get a tenth of a vote in the level
    ours_w = w * (_mask(name, idx, size) / 255.0) * (_up_alpha(name, idx, size) / 255.0)
    if ours_w.sum() < 1e-6:
        return rgb
    au = np.asarray(original(name, idx).convert("RGBA")
                    .resize((size, size), Image.LANCZOS), dtype=np.float64)
    au_w = w * (au[..., 3] / 255.0)
    if au_w.sum() < 1e-6:
        return rgb
    ours = float((rgb.mean(2) * ours_w).sum() / ours_w.sum())
    theirs = float((au[..., :3].mean(2) * au_w).sum() / au_w.sum())
    return np.clip(rgb + (theirs - ours) * w[..., None], 0, 255)


def _facet_split(rgb, name, idx, size):
    """Rebuild the point out of two surfaces that meet at it.

    The outer silhouette is geometry - the tracer even reconstructs the apex
    from the two sides that form it. The interior edge between the lit sheet
    and the grey underside is not: it arrives as pixels in the master, drawn
    wherever the network put it. Measured against the chord it is 0.44-0.70
    logical units off within two units of the point, and measured across it the
    two surfaces there differ by 1.06 where the body differs by 2.00 and the
    author by 1.91-2.07. That is the point not reading as two surfaces.

    The correction is across the chord only. Along it the master is right and
    says something the author says too: the glass brightens towards the point
    (Arrow 133 -> 238 over the first 2.5 units). An earlier version replaced the
    tip with a straight fit of each surface's colour and flattened that ramp to
    a plateau - which is UpArrow's own defect, drawn brighter. So the along-chord
    profile is kept exactly as the master has it, taken as the median across each
    section, and only the shape across the section is replaced: the two sides of
    the chord are set to that level times and divided by the square root of the
    ratio the body already carries.

    This does not draw a line between them. A line has a width of its own and
    would split the point in two; what is wanted is one edge whose width goes to
    zero exactly at A, so both surfaces arrive at the same vertex. Out past
    _FACET_TIP_ZONE the master's own fold takes over again."""
    if (name not in _FACET_CURSORS or name in _FACET_MEASURING
            or _landmarks(name, idx) is None):
        return rgb
    r = _facet_gain(name, idx)
    if abs(r - 1.0) < 1e-3:
        return rgb
    sd, t = _facet_frame(name, idx, size)
    near = 1.0 - _smoothstep((t - _FACET_TIP_ZONE) / _FACET_TIP_FADE)
    if near.max() <= 0.0:
        return rgb
    ed = _edge_distance_at(name, idx, size)
    inside = (_mask(name, idx, size) > 250) & (ed > 0.35)
    lum = rgb @ _LUMA
    span = _FACET_TIP_ZONE + _FACET_TIP_FADE
    edges = np.arange(0.0, span + _FACET_BIN, _FACET_BIN)
    at, hi, lo = [], [], []
    for e0 in edges[:-1]:
        m = inside & (t >= e0) & (t < e0 + _FACET_BIN)
        if m.sum() < 12:
            continue
        y = lum[m]
        cut_hi = np.percentile(y, 100 - _FACET_PCT)
        cut_lo = np.percentile(y, _FACET_PCT)
        at.append(e0 + _FACET_BIN / 2.0)
        hi.append(np.median(rgb[m][y >= cut_hi], axis=0))
        lo.append(np.median(rgb[m][y <= cut_lo], axis=0))
    if len(at) < 4:
        return rgb
    at = np.array(at); hi = np.array(hi); lo = np.array(lo)
    bright = np.dstack([np.interp(t, at, hi[:, c]) for c in range(3)])
    dark = np.dstack([np.interp(t, at, lo[:, c]) for c in range(3)])
    w = _FACET_FEATHER * _smoothstep(t / _FACET_RAMP)
    upper = np.where(w < 1e-6, (sd > 0).astype(np.float64),
                     np.clip(0.5 + sd / (2.0 * np.maximum(w, 1e-6)), 0.0, 1.0))
    lit = upper if r < 1.0 else 1.0 - upper        # r is lower-over-upper
    recon = bright * lit[..., None] + dark * (1.0 - lit)[..., None]
    if _FACET_KEEP_RIM > 0.0:
        # The two facets are interior surfaces. The dark rim that runs around
        # the outside is a different structure, and it is what carries the
        # point's contrast against the desktop - overwriting it with interior
        # glass is what cost tip_contrast on all three arrows (NEXT.md 30.3).
        near = near * _smoothstep(ed / _FACET_KEEP_RIM - 1.0)
    k = (near * _FACET_MIX)[..., None]
    return np.clip(rgb * (1.0 - k) + recon * k, 0, 255)


def _tip_glass(up_a, name, idx, size):
    """Carry the glass out to the point.

    The silhouette is a sharp vector polygon and the translucency inside it is
    not: at Arrow's apex the two multiply out to alpha 9, and the glass only
    reaches its own level half a unit further in. The polygon is therefore
    sharper than anything the eye ever sees. Sample the translucency
    _TIP_GLASS units inside, along the fold chord where both surfaces meet, and
    carry that value out to A. The vector mask still draws the edge, so the
    point stays as sharp as it is traced - it just has glass in it."""
    if name not in _FACET_CURSORS or _landmarks(name, idx) is None:
        return up_a
    lm = _landmarks(name, idx)
    a = np.array(lm[0]); j = np.array(lm[2])
    d = (j - a) / max(float(np.hypot(*(j - a))), 1e-9)
    s = size / V.LOGICAL
    p = (a + d * _TIP_GLASS) * s
    ref = float(_sample1(up_a, p[0], p[1]))
    _, t = _facet_frame(name, idx, size)
    return np.maximum(up_a, ref * _smoothstep(1.0 - t / _TIP_GLASS))


_SAT_LIFT_DEFAULT = 1.05     # of the author's own level. Glass reads flatter
                             # than the art it came from once it is composited,
                             # and the lift is what puts the colour back.
_SAT_LIFT = {"NO": 1.00}     # named, because NO's red ring is not a sheet of
                             # glass - it is a small, highly saturated UI mark
                             # laid over one, and the same lift that flatters a
                             # sheet oversaturates a mark. Measured: on the
                             # grey background the interior of frames 5-10
                             # departs from the author's almost purely in
                             # chroma (dC +3.69..+6.71 against dL +0.48..+1.35
                             # and dH 1.64..2.38), and delta_e[7] reads 6.56 at
                             # 1.05, 6.14 at 1.02, 5.93 at 1.00. The rest of
                             # that frame's error is the ring's own coverage,
                             # not its colour, and no lift reaches it.


@functools.lru_cache(maxsize=None)
def frame_image(name, idx, size):
    """Final RGBA frame at any size. Every size, 32px included, draws its colour
    from the sharpened AI master (_master, native up to 512px) inside a
    vector-crisp silhouette; smaller sizes downsample the already-sharpened
    master, so the crispness carries down without a second sharpen pass."""
    orig = _orig(_key(name, idx))
    rgb = _freeze_lines(_master_rgb(name, idx, size), name, idx, size)
    if (name, idx) in _MATERIAL_BASIS:
        rgb = _material_layer(name, idx, _MATERIAL_BASIS[(name, idx)], size)
    if name == "Help":
        rgb = _engrave(rgb, name, size)
        rgb = _bead(rgb, name, idx, size)
    if name in _SYNTH_BEVEL:
        rgb = np.clip(_resize(orig, size)[0] + _bevel_shading(name, idx, size)[..., None],
                      0, 255)
    rgb = _temper(rgb, _match_author_level(rgb, name, idx, size), name, "level")
    rgb = _tip_realign(rgb, name, idx, size)
    rgb = _temper(rgb, _tip_relight(rgb, name, idx, size), name, "relight")
    rgb = _edge_shadow_declutter(rgb, name, idx, size)
    rgb = _edge_comb(rgb, name, idx, size)
    rgb = _notch_declutter(rgb, name, idx, size)
    rgb = _notch_from_author(rgb, name, idx, size)
    rgb = _rim_transfer(rgb, name, idx, size)
    rgb = _fold_transfer(rgb, name, idx, size)
    rgb = _facet_split(rgb, name, idx, size)
    rgb = _tip_level(rgb, name, idx, size)
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
    up_a = _tip_glass(_up_alpha(name, idx, size), name, idx, size)
    alpha = _round_hole(_deburr(_mask(name, idx, size) / 255.0 * up_a, size),
                        name, idx, size)
    # anchor saturation at the shipped size, where the superiority metric reads
    # it: the premultiplied linear-light downsample shifts a vivid ring's chroma
    # (the 512-anchored match drifted +12% by 128), so matching here to the 32px
    # original's level lands every size on target. Grey glass (sat below the
    # floor) is left alone - scaling its near-zero chroma only invents colour.
    orig_sat = _sat_anchor(name, idx)
    if orig_sat >= 0.035:
        lift = _SAT_LIFT.get(name, _SAT_LIFT_DEFAULT)
        rgb = _temper(rgb, _sat_match(rgb, alpha, orig_sat * lift), name, "sat")
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
    if name in INTERP and LIGHT_ANIM:
        from . import lightanim          # imports this module: has to stay lazy
        out_n = n * INTERP_N if interp else n
        frames, _ = lightanim.anim_frames_lighting(name, size, out_n=out_n)
        return frames, ([1] * out_n if interp else list(BY_NAME[name]["rates"]))
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

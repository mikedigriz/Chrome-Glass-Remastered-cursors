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
    prims = [{"poly": C.smooth([tuple(p) for p in poly]),
              "fill": (255, 255, 255, 255)} for poly in fr["polys"]]
    if name == "Help":
        prims += C.HELP_EXTRA
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


def _declutter_hue_outliers(name, idx, rgb, size):
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


@functools.lru_cache(maxsize=None)
def _master(name, idx):
    """Colour master -> (rgb HxWx3 float, anchor px), sharpened once at the anchor.

    Every cursor now anchors on the native anime src/ai512 (grey/pale included -
    the anime_6B model invents no colour on flat glass, so the old honest-Lanczos
    bypass is gone and the pale Size*/IBeam/Cross cursors finally carry real
    network detail). Falls back to src/ai256, then a Lanczos of the 128 base.

    Crispness is a single deterministic unsharp at the anchor rather than a
    sharper (noisier) network: on this clean source it sharpens the luminance
    edges without inventing texture, and downsampling the already-sharpened
    master keeps every smaller size crisp too. Saturation is anchored later, in
    frame_image, at the shipped size (see there)."""
    key = _key(name, idx)
    rgb, anchor = None, 256
    for a in (512, 256):
        path = os.path.join(HERE, "src", f"ai{a}", key + ".png")
        if os.path.exists(path):
            rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.float64)
            anchor = a
            break
    if rgb is None:
        rgb128, a128 = _base128(name, idx)
        rgb, _ = _resize(np.dstack([rgb128, a128]), 256)
        anchor = 256
    rgb = _unsharp(rgb, radius=2.2 * anchor / 512.0, percent=90, dark=0.45)
    rgb = _declutter_hue_outliers(name, idx, rgb, anchor)
    rgb = _declutter_engraved_detail(name, idx, rgb, anchor)
    return rgb, anchor


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
    histogram match leaves in the flat glass. Falls back to the plain Lanczos
    when no master is present, so a torch-free build is identical to before."""
    key = _key(name, idx)
    _, ref = _resize(_orig(key), size)
    path = os.path.join(HERE, "src", "aialpha", key + ".png")
    if not os.path.exists(path):
        return ref
    ai = np.asarray(Image.open(path).convert("L"), dtype=np.float64)
    if ai.shape[0] != size:
        ai = np.asarray(Image.fromarray(ai.astype(np.float32), mode="F")
                        .resize((size, size), Image.LANCZOS), dtype=np.float64)
    rv, av = ref[ref > 32], ai[ai > 32]
    if av.size and rv.size:
        ai = ai * (np.median(rv) / max(np.median(av), 1e-6))
    return np.clip((1.0 - _BLEND_AI) * ref + _BLEND_AI * ai, 0, 255)


def original(name, idx):
    """The author's original 32px frame, byte for byte - the reference the
    superiority metrics and the 2006-vs-remaster comparison are measured against."""
    return Image.open(os.path.join(ORIG, _key(name, idx) + ".png")).convert("RGBA")


@functools.lru_cache(maxsize=None)
def frame_image(name, idx, size):
    """Final RGBA frame at any size. Every size, 32px included, draws its colour
    from the sharpened AI master (_master, native up to 512px) inside a
    vector-crisp silhouette; smaller sizes downsample the already-sharpened
    master, so the crispness carries down without a second sharpen pass."""
    key = _key(name, idx)
    orig = _orig(key)
    m_rgb, anchor = _master(name, idx)
    _, m_a = _resize(orig, anchor)
    if size == anchor:
        rgb = m_rgb
    else:
        rgb, _ = _resize(np.dstack([m_rgb, m_a]), size)
        if size > anchor:                                  # only when past native detail
            rgb = _unsharp(rgb, radius=1.6 * size / 128.0, percent=40)
    up_a = _up_alpha(name, idx, size)
    alpha = _mask(name, idx, size) / 255.0 * up_a
    # anchor saturation at the shipped size, where the superiority metric reads
    # it: the premultiplied linear-light downsample shifts a vivid ring's chroma
    # (the 512-anchored match drifted +12% by 128), so matching here to the 32px
    # original's level lands every size on target. Grey glass (sat below the
    # floor) is left alone - scaling its near-zero chroma only invents colour.
    orig_sat = _mean_sat(orig[..., :3], orig[..., 3])
    if orig_sat >= 0.035:
        rgb = _sat_match(rgb, alpha, orig_sat * 1.05)
    return _compose(rgb, alpha)


def _lerp(im_a, im_b, t):
    """Cross-fade in premultiplied linear-light space - no dark fringes and no
    gamma-space midpoint dimming."""
    a = np.asarray(im_a, dtype=np.float64)
    b = np.asarray(im_b, dtype=np.float64)
    aa, ba = a[..., 3:4] / 255.0, b[..., 3:4] / 255.0
    a_lin = V.srgb_to_linear(np.clip(a[..., :3], 0, 255).astype(np.uint8))
    b_lin = V.srgb_to_linear(np.clip(b[..., :3], 0, 255).astype(np.uint8))
    pa = np.dstack([a_lin * aa, aa[..., 0]])
    pb = np.dstack([b_lin * ba, ba[..., 0]])
    m = pa + (pb - pa) * t
    al = m[..., 3]
    rgb_lin = m[..., :3] / np.maximum(al, 1e-6)[..., None]
    rgb = V.linear_to_srgb(rgb_lin).astype(np.float64)
    return _compose(rgb, al * 255.0)


def anim_frames(name, size):
    """(frames, rates_jiffies) for an animated cursor at the given size.

    AppStarting/Hand/Wait: 27 cross-faded frames at rate 1 (60 fps).
    Handwriting/NO: the author's frames and rate chunk verbatim
    (rate 1 with a freeze on the last frame)."""
    n = len(BY_NAME[name]["frames"])
    base = [frame_image(name, i, size) for i in range(n)]
    if name not in INTERP:
        return base, list(BY_NAME[name]["rates"])
    out = []
    for i in range(n):
        nxt = base[(i + 1) % n]
        out.append(base[i])
        for k in range(1, INTERP_N):
            out.append(_lerp(base[i], nxt, k / INTERP_N))
    return out, [1] * len(out)

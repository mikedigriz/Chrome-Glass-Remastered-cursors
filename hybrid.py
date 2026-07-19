"""Hybrid frame pipeline: the original's pixels + a vector-crisp edge.

Per frame:
  colour - the AI-upscaled 128px frame keeps every hand-painted inner sheen;
           Reinhard colour transfer (per-channel mean/std over the visible
           zone) from the original 32px frame restores the true saturation.
           Pale glass cursors (IBeam, Cross, Size*) skip the AI pass - their
           RGB is a premultiplied Lanczos of the original (the AI is noisy
           on near-transparent glass).
  alpha  - (vector mask / 255) x Lanczos(original alpha): the original's own
           translucency inside a crisp traced silhouette, at any size.
  32px   - the original frame, byte for byte.
  256px  - RGB Lanczos-up from the processed 128; the vector mask stays
           infinitely sharp at any size.

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

# AI RGB is noisy on these near-transparent glass shapes - original RGB only
PALE = {"IBeam", "Cross", "SizeAll", "SizeNESW", "SizeNS", "SizeNWSE", "SizeWE"}

# author's 50 ms/frame cursors, cross-faded x3 to 60 fps (same cycle length)
INTERP = {"AppStarting", "Hand", "Wait"}
INTERP_N = 3

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


def _unsharp(rgb, radius=1.6, percent=55):
    """Light sharpening of the colour channels only - alpha stays native.
    radius scales with the working resolution so a 512px frame gets the same
    perceptual crispness a 128px frame gets at radius 1.6."""
    im = Image.fromarray(rgb.astype(np.uint8), "RGB")
    im = im.filter(ImageFilter.UnsharpMask(radius=radius, percent=percent, threshold=2))
    return np.asarray(im, dtype=np.float64)


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
    """Processed 128px frame -> (rgb HxWx3, alpha HxW) float arrays."""
    key = _key(name, idx)
    orig = _orig(key)
    up_rgb, up_a = _resize(orig, 128)
    alpha = _mask(name, idx, 128) / 255.0 * up_a
    orig_sat = _mean_sat(orig[..., :3], orig[..., 3])
    if name in PALE or orig_sat < 0.05:
        # near-grey glass: the AI pass invents cross-hatch noise there,
        # the premultiplied Lanczos of the original is the honest source
        rgb = _unsharp(up_rgb)
    else:
        ai = _ai(key)
        tr = _reinhard(ai[..., :3], ai[..., 3], orig[..., :3], orig[..., 3])
        # keep the AI only where it painted colour (Wait's red, NO's ring);
        # its grey zones carry the same hatch noise, use the original there
        px = tr / 255.0
        chroma = (px.max(axis=2) - px.min(axis=2)) / np.maximum(px.max(axis=2), 1e-6)
        w = np.clip((chroma - 0.04) / 0.08, 0, 1)[..., None]
        rgb = up_rgb + w * (tr - up_rgb)
        rgb = _unsharp(rgb)
        # match against the final alpha so the correction is judged on
        # the same zone the shipped frame is measured by
        rgb = _sat_match(rgb, alpha, orig_sat * 1.05)
    return rgb, alpha


def _compose(rgb, alpha):
    out = np.dstack([np.clip(rgb, 0, 255), np.clip(alpha, 0, 255)])
    return Image.fromarray(out.round().astype(np.uint8), "RGBA")


@functools.lru_cache(maxsize=None)
def _master(name, idx):
    """Native 256px colour master -> rgb HxWx3 float. This anchors the whole
    set at 256px instead of 128: 128/96/64/48 are supersampled down from it,
    384/512 up from it.

    For coloured cursors the committed Real-ESRGAN pass (src/ai256,
    tools/upscale256.py) supplies native 256px detail, with its saturation
    pulled back to the original's (Real-ESRGAN oversaturates). Pale/near-grey
    glass keeps the honest Lanczos of the 128 base - the AI invents colour
    noise there, exactly what the 128 pipeline already rejects."""
    key = _key(name, idx)
    orig = _orig(key)
    orig_sat = _mean_sat(orig[..., :3], orig[..., 3])
    rgb128, a128 = _base128(name, idx)
    ai256 = os.path.join(HERE, "src", "ai256", key + ".png")
    if name in PALE or orig_sat < 0.05 or not os.path.exists(ai256):
        rgb, _ = _resize(np.dstack([rgb128, a128]), 256)
        return rgb
    rgb = np.asarray(Image.open(ai256).convert("RGB"), dtype=np.float64)
    _, up_a = _resize(orig, 256)
    alpha = _mask(name, idx, 256) / 255.0 * up_a
    return _sat_match(rgb, alpha, orig_sat * 1.05)


def original(name, idx):
    """The author's original 32px frame, byte for byte - the reference the
    superiority metrics and the 2006-vs-remaster comparison are measured against."""
    return Image.open(os.path.join(ORIG, _key(name, idx) + ".png")).convert("RGBA")


@functools.lru_cache(maxsize=None)
def frame_image(name, idx, size):
    """Final RGBA frame at any size. Every size, 32px included, draws its colour
    from the 256px master (_master) inside a vector-crisp silhouette."""
    key = _key(name, idx)
    m_rgb = _master(name, idx)
    _, m_a = _resize(_orig(key), 256)
    if size == 256:
        rgb = m_rgb
    else:
        rgb, _ = _resize(np.dstack([m_rgb, m_a]), size)
        if size > 256:
            # upscaling past the master softens it; restore crispness at a
            # radius proportional to the new resolution (gentle percent to
            # avoid ringing on glass edges)
            rgb = _unsharp(rgb, radius=1.6 * size / 128.0, percent=40)
    _, up_a = _resize(_orig(key), size)
    alpha = _mask(name, idx, size) / 255.0 * up_a
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

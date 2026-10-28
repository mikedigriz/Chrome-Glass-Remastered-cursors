"""GPU ports of hybrid.py stages. Each takes and returns numpy so the callers in
hybrid.py stay unchanged; the arithmetic is float64 to match the CPU path."""
import numpy as np
import torch

from . import rows_for

_DEV = torch.device("cuda")


def _t(a, dtype=torch.float64):
    return torch.as_tensor(np.ascontiguousarray(a), device=_DEV).to(dtype)


_PLAIN_KEYS = {"poly", "dot", "fill"}


def mask_alpha(prims, size, ss=None):
    """vectorlib.render(prims, size) alpha channel for a list of opaque white
    filled polygons/dots, or None when the primitives need the general path.

    Compositing opaque white in linear light is a union of binary masks, so the
    alpha is round(255 * Lanczos(union)) - the same float32 Lanczos _resize_linear
    runs, on one channel instead of four, and no per-primitive composite."""
    from PIL import Image, ImageDraw
    from . import resample as R
    from .. import vectorlib as V
    for p in prims:
        if set(p) - _PLAIN_KEYS or p.get("fill") != (255, 255, 255, 255):
            return None
    if ss is None:
        ss = max(6, -(-1536 // size))
    S = size * ss
    scale = S / V.LOGICAL
    img = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(img)
    for p in prims:
        if "dot" in p:
            cx, cy, rad = (v * scale for v in p["dot"])
            d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=255)
        if "poly" in p:
            pts = V._poly_px(p["poly"], scale)
            if pts:
                d.polygon(pts, fill=255)
    a = torch.from_numpy(np.array(img)).to(_DEV) // 255
    r = R.resize_f(a.to(torch.float32), (size, size), "lanczos")
    return torch.clamp(torch.round(r * 255.0), 0, 255).to(torch.uint8).cpu().numpy()


def edge_distance(prims, inside, size, logical=32.0):
    """hybrid._edge_distance_geom's exact distance to the traced segments, all
    edges of a chunk at once. Signed by `inside`."""
    from . import ops
    L = size / logical
    py, px = ops.grid(size)
    px, py = (px + 0.5) / L, (py + 0.5) / L
    best = torch.full((size, size), float("inf"), dtype=torch.float64, device=ops.DEV)
    segs = []
    for kind, geom in prims:
        if kind == "dot":
            cx, cy, r = geom
            best = torch.minimum(best, torch.abs(torch.hypot(px - cx, py - cy) - r))
            continue
        pts = np.array([(p[0], p[1]) for p in geom], dtype=np.float64)
        a, b = pts, np.roll(pts, -1, axis=0)
        ab = b - a
        den = (ab * ab).sum(1)
        keep = den >= 1e-12
        segs.append(np.concatenate([a, ab, den[:, None]], 1)[keep])
    if segs:
        s = ops.t(np.concatenate(segs))
        chunk = rows_for(size * size * 4)           # edges per step: t, hypot and two offsets
        for i in range(0, len(s), chunk):
            c = s[i:i + chunk]
            ax, ay, abx, aby, den = (c[:, k, None, None] for k in range(5))
            t = torch.clamp(((px - ax) * abx + (py - ay) * aby) / den, 0.0, 1.0)
            dd = torch.hypot(px - (ax + t * abx), py - (ay + t * aby))
            best = torch.minimum(best, dd.amin(0))
    ins = ops.t(inside, torch.bool)
    return torch.where(ins, best, -best).cpu().numpy()


_FILTERS = {1: "lanczos", 2: "bilinear", 4: "box"}       # PIL Image.LANCZOS / BILINEAR / BOX
_LUT = None


def _srgb_lut():
    global _LUT
    if _LUT is None:
        from .. import vectorlib as V
        _LUT = torch.as_tensor(V._SRGB_LUT, device=_DEV)        # float32, 256 entries
    return _LUT


def linear_to_srgb(lin):
    """vectorlib.linear_to_srgb on a tensor: uint8 sRGB."""
    c = torch.clamp(lin, 0.0, 1.0)
    c = torch.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)
    return torch.clamp(torch.round(c * 255.0), 0, 255).to(torch.uint8)


def resize_rgba(arr, size, filt):
    """hybrid._resize: premultiplied linear-light resize of an RGBA float array.
    Returns (rgb float64 (size, size, 3), alpha float64 0..255), or None for a
    filter the port does not know."""
    from . import resample as R
    kind = _FILTERS.get(int(filt))
    if kind is None:
        return None
    a_in = _t(arr)
    a = a_in[..., 3] / 255.0
    u8 = torch.clamp(a_in[..., :3], 0, 255).to(torch.uint8)
    premult = _srgb_lut()[u8.long()] * a[..., None]                 # float32 * float64 -> float64
    planes = torch.cat([premult.permute(2, 0, 1), a[None]], 0)       # (4, H, W)
    out = R.resize_f(planes, (size, size), kind).to(torch.float64)
    oa = out[3]
    rgb_lin = out[:3].permute(1, 2, 0) / torch.clamp(oa, min=1e-6)[..., None]
    rgb = linear_to_srgb(rgb_lin).to(torch.float64)
    return rgb.cpu().numpy(), (torch.clamp(oa, 0, 1) * 255.0).cpu().numpy()



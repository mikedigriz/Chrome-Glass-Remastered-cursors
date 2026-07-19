"""Tiny declarative vector engine for the cursor set.

A cursor mask or glyph is a list of primitives in a 32x32 logical space,
rendered to a crisp anti-aliased RGBA bitmap (PIL, supersampled) at any size.

Primitive dict keys:
  poly   : [(x,y), ...]           polygon points (logical units, 0..32)
  path   : "M .. L .. Z"          raw SVG path (alternative to poly)
  grad   : (c1, c2, (x1,y1,x2,y2)) linear gradient in logical coords
  fill   : (r,g,b,a)              solid fill (if no grad)
  stroke : ((r,g,b,a), width)     outline
  blur   : float                  gaussian blur radius (logical units)
  offset : (dx, dy)               translate (for shadows)
  opacity: float                  0..1 layer opacity
"""
import struct, math
from PIL import Image, ImageDraw, ImageFilter
try:
    import numpy as _np
except ImportError:
    _np = None

LOGICAL = 32

_SRGB_THRESH = 0.0031308


def srgb_to_linear(u8):
    """uint8 sRGB array -> float32 linear-light array, 0..1 range."""
    c = u8.astype(_np.float32) / 255.0
    return _np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(lin):
    """float linear-light array (0..1) -> uint8 sRGB array."""
    c = _np.clip(lin, 0.0, 1.0)
    c = _np.where(c <= _SRGB_THRESH, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)
    return _np.clip(_np.round(c * 255.0), 0, 255).astype(_np.uint8)


def _grad_image(size, c1, c2, vec):
    """Linear gradient RGBA image of given pixel size; vec in pixel coords."""
    x1, y1, x2, y2 = vec
    dx, dy = x2 - x1, y2 - y1
    denom = dx * dx + dy * dy or 1.0
    if _np is not None:
        ys, xs = _np.mgrid[0:size, 0:size]
        t = _np.clip(((xs - x1) * dx + (ys - y1) * dy) / denom, 0.0, 1.0)
        a = _np.array(c1, dtype=_np.float32)
        b = _np.array(c2, dtype=_np.float32)
        arr = (a + (b - a) * t[..., None]).round().astype(_np.uint8)
        return Image.fromarray(arr, "RGBA")
    img = Image.new("RGBA", (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            t = ((x - x1) * dx + (y - y1) * dy) / denom
            t = 0.0 if t < 0 else 1.0 if t > 1 else t
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(c1, c2))
    return img


def _poly_px(points, scale):
    return [(x * scale, y * scale) for x, y in points]


def _composite_linear(base, layer):
    """Alpha-composite layer over base in linear light instead of sRGB-encoded
    space - blending translucent edges in gamma space makes them read dark/
    soft/faceted instead of a true anti-aliased line."""
    b = _np.asarray(base, dtype=_np.float32)
    l = _np.asarray(layer, dtype=_np.float32)
    ba, la = b[..., 3:4] / 255.0, l[..., 3:4] / 255.0
    brgb = srgb_to_linear(b[..., :3].astype(_np.uint8))
    lrgb = srgb_to_linear(l[..., :3].astype(_np.uint8))
    out_a = la + ba * (1.0 - la)
    out_rgb = (lrgb * la + brgb * ba * (1.0 - la)) / _np.maximum(out_a, 1e-6)
    rgb_u8 = linear_to_srgb(out_rgb)
    a_u8 = _np.clip(_np.round(out_a * 255.0), 0, 255).astype(_np.uint8)
    return Image.fromarray(_np.dstack([rgb_u8, a_u8]), "RGBA")


def _resize_linear(img, size):
    """Downsample premultiplied linear-light RGBA with Lanczos, then encode
    back to sRGB - keeps edge pixels gamma-correct instead of gamma-averaged."""
    arr = _np.asarray(img, dtype=_np.float32)
    a = arr[..., 3] / 255.0
    rgb_lin = srgb_to_linear(arr[..., :3].astype(_np.uint8))
    premult = rgb_lin * a[..., None]
    chans = [_np.asarray(Image.fromarray(premult[..., c], mode="F")
                          .resize((size, size), Image.LANCZOS), dtype=_np.float32)
              for c in range(3)]
    a_r = _np.asarray(Image.fromarray(a, mode="F")
                       .resize((size, size), Image.LANCZOS), dtype=_np.float32)
    rgb_r = _np.dstack(chans) / _np.maximum(a_r[..., None], 1e-6)
    rgb_u8 = linear_to_srgb(rgb_r)
    a_u8 = _np.clip(_np.round(a_r * 255.0), 0, 255).astype(_np.uint8)
    return Image.fromarray(_np.dstack([rgb_u8, a_u8]), "RGBA")


def render(primitives, size=256, ss=None):
    """Render primitives to an RGBA image of (size x size) pixels.

    ss is the supersampling factor. When left at None it adapts so the internal
    canvas never drops below ~1536px: small sizes get the same crisp diagonal
    edge as the large ones (32px went to a 192px canvas at the old fixed ss=6),
    while 256px and above stay at 6x."""
    if ss is None:
        ss = max(6, -(-1536 // size))       # ceil(1536 / size), floor 6
    S = size * ss
    scale = S / LOGICAL
    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    for p in primitives:
        layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        if "line" in p:                                 # open stroked polyline
            lp = _poly_px(p["line"], scale)
            col, w = p["stroke"]
            wp = max(1, round(w * scale))
            d.line(lp, fill=col, width=wp, joint="curve")
            r = wp / 2.0
            for (px_, py_) in (lp[0], lp[-1]):           # round caps
                d.ellipse([px_ - r, py_ - r, px_ + r, py_ + r], fill=col)
        if "dot" in p:                                   # filled circle
            cx, cy, rad = p["dot"]
            cx, cy, rad = cx * scale, cy * scale, rad * scale
            d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=p["fill"])
        pts = _poly_px(p["poly"], scale) if "poly" in p else None
        if pts:
            if "grad" in p:
                c1, c2, vec = p["grad"]
                g = _grad_image(S, c1, c2, [v * scale for v in vec])
                mask = Image.new("L", (S, S), 0)
                ImageDraw.Draw(mask).polygon(pts, fill=255)
                layer.paste(g, (0, 0), mask)
            elif "fill" in p:
                d.polygon(pts, fill=p["fill"])
            if "stroke" in p:
                col, w = p["stroke"]
                d.line(pts + [pts[0]], fill=col, width=max(1, round(w * scale)), joint="curve")
                r = max(1, round(w * scale)) / 2.0
                for (px_, py_) in pts:                      # round the joints
                    d.ellipse([px_ - r, py_ - r, px_ + r, py_ + r], fill=col)
        if p.get("blur"):
            layer = layer.filter(ImageFilter.GaussianBlur(p["blur"] * scale))
        if p.get("offset"):
            dx, dy = p["offset"]
            layer = layer.transform(layer.size, Image.AFFINE,
                                    (1, 0, -dx * scale, 0, 1, -dy * scale))
        if p.get("opacity", 1) < 1:
            alpha = layer.split()[3].point(lambda a: round(a * p["opacity"]))
            layer.putalpha(alpha)
        out = _composite_linear(out, layer)
    return _resize_linear(out, size)

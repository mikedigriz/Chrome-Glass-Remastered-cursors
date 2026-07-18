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


def render(primitives, size=256, ss=6):
    """Render primitives to an RGBA image of (size x size) pixels."""
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
        out = Image.alpha_composite(out, layer)
    return out.resize((size, size), Image.LANCZOS)

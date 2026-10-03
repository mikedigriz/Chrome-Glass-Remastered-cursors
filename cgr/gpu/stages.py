"""GPU ports of hybrid.py stages. Each takes and returns numpy so the callers in
hybrid.py stay unchanged; the arithmetic is float64 to match the CPU path."""
import numpy as np
import torch

from . import rows_for

_DEV = torch.device("cuda")


def _t(a, dtype=torch.float64):
    return torch.as_tensor(np.ascontiguousarray(a), device=_DEV).to(dtype)


def rim_blend(px, py, pts, d, corr, k0, k1, fu, var):
    """_rim_native's blend: per pixel, the sections of the stations round it,
    weighted by arc offset alone. Same maths as the CPU loop in hybrid._rim_blend."""
    size = px.shape[0]
    pxt, pyt, dt = _t(px), _t(py), _t(d)
    sx, sy = _t(pts[:, 0]), _t(pts[:, 1])
    corr_t = _t(corr)                                   # (S, depth)
    k0t, k1t, fut = _t(k0, torch.int64), _t(k1, torch.int64), _t(fu)
    out = torch.empty((size, size), dtype=torch.float64, device=_DEV)
    rows = rows_for(size * len(sx) * 3)             # w, dx/dy and c live together
    for r0 in range(0, size, rows):
        sl = slice(r0, r0 + rows)
        dx = pxt[sl, :, None] - sx
        dy = pyt[sl, :, None] - sy
        w = torch.exp(-torch.clamp(dx * dx + dy * dy - (dt[sl] ** 2)[..., None], min=0.0) / var)
        c = corr_t[:, k0t[sl]] * (1.0 - fut[sl]) + corr_t[:, k1t[sl]] * fut[sl]   # (S, r, x)
        out[sl] = torch.einsum("yxs,syx->yx", w, c) / torch.clamp(w.sum(2), min=1e-9)
    return out.cpu().numpy()


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


def point_along_core(a, nx, ny, w, taps, agree, back_passes, back_gain):
    """hybrid._point_along from the taps on: the edge-wise mean colour, put back
    and blended by w. Returns rgb (float64, unclipped)."""
    from . import ops
    a, nx, ny, w = ops.t(a), ops.t(nx), ops.t(ny), ops.t(w)
    size = a.shape[0]
    al = a[..., 3] / 255.0
    nrm = torch.stack([nx, ny], -1)
    py, px = ops.grid(size)
    lo, hi = agree
    tp = []
    for k, wt in taps:
        if k == 0:
            tp.append((None, None, wt))
            continue
        sx, sy = px - ny * k, py + nx * k
        s_n = ops.sample(nrm, sx, sy)
        ok = wt * torch.clamp((s_n[..., 0] * nx + s_n[..., 1] * ny - lo) / (hi - lo), 0.0, 1.0)
        tp.append((sx, sy, ok))

    def mean_along(c):
        pre = c * al[..., None]
        acc = torch.zeros_like(pre)
        wsum = torch.zeros((size, size), dtype=torch.float64, device=ops.DEV)
        for sx, sy, ok in tp:
            if sx is None:
                acc += pre * ok
                wsum += al * ok
            else:
                acc += ops.sample(pre, sx, sy) * ok[..., None]
                wsum += ops.sample(al[..., None], sx, sy)[..., 0] * ok
        return acc / torch.clamp(wsum, min=1e-6)[..., None], wsum

    c, wsum = mean_along(a[..., :3])
    back = c - mean_along(c)[0]
    for _ in range(back_passes):
        back = mean_along(back)[0]
    c = c + back_gain * back
    w = w * (wsum > 1e-3)
    rgb = a[..., :3] + (c - a[..., :3]) * w[..., None]
    return rgb.cpu().numpy()


def rim_valley_core(a, d, nx, ny, w, P):
    """hybrid._rim_valley from the luminance on. P carries the _VALLEY_* constants.
    Returns delta (float64) to add to rgb."""
    from . import ops
    a, d, nx, ny, w = ops.t(a), ops.t(d), ops.t(nx), ops.t(ny), ops.t(w)
    size = a.shape[0]
    L = size / 32.0
    lum = a[..., :3].mean(-1)
    al = a[..., 3]
    level = torch.where(al >= P["alpha"] * al.max(), lum, torch.full_like(lum, -1.0))
    py, px = ops.grid(size)
    out = torch.full((size, size), -1.0, dtype=torch.float64, device=ops.DEV)
    for tt in np.arange(P["step"], P["out"] + 1e-9, P["step"]):
        o = tt * L
        got = ops.sample1(level, px - nx * o, py - ny * o)
        out = torch.where(d >= tt, torch.maximum(out, got), out)
    inn = torch.full((size, size), -1.0, dtype=torch.float64, device=ops.DEV)
    climbing = torch.ones((size, size), dtype=torch.bool, device=ops.DEV)
    below = d
    for tt in np.arange(P["step"], P["in"] + 1e-9, P["step"]):
        o = tt * L
        here = ops.sample1(d, px + nx * o, py + ny * o)
        climbing &= here >= below + P["climb"] * P["step"]
        below = here
        inn = torch.where(climbing, torch.maximum(inn, ops.sample1(level, px + nx * o, py + ny * o)), inn)
    target = torch.minimum(out, inn)
    m = (target > 0).to(torch.float64)
    smooth = (ops.smooth1(target * m, P["smooth"], size)
              / torch.clamp(ops.smooth1(m, P["smooth"], size), min=1e-9))
    target = torch.where(m > 0, smooth, target)
    gap = torch.clamp(target - lum, min=0.0)
    lift = torch.clamp((gap - P["cap"]) / P["ramp"], 0.0, 1.0) * w * (target > 0)
    ga = al / 255.0
    seen = gap * lift * ga
    along = sum(wt * (seen if k == 0 else ops.sample1(seen, px - ny * k, py + nx * k))
                for k, wt in P["along"]) / sum(wt for _k, wt in P["along"])
    delta = torch.where(al >= 2, along / torch.clamp(ga, min=1e-3), torch.zeros_like(al))
    return delta.cpu().numpy()


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


def nearest_station(px, py, x, y):
    """Index of the nearest station per point (first one on ties), as hybrid._even_band's loop."""
    from . import ops
    pxt, pyt, xt, yt = ops.t(px), ops.t(py), ops.t(x), ops.t(y)
    out = torch.empty(len(px), dtype=torch.int64, device=ops.DEV)
    rows = rows_for(len(x) * 3)
    for r0 in range(0, len(px), rows):
        sl = slice(r0, r0 + rows)
        dd = (pxt[sl, None] - xt[None, :]) ** 2 + (pyt[sl, None] - yt[None, :]) ** 2
        out[sl] = torch.argmin(dd, 1)
    return out.cpu().numpy()



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


def along_edge_walk(col, m, tx, ty, xs, ys, h, L, along, nsteps):
    """The walk of hybrid._along_edge along the level sets, both ways, for the
    pixels (xs, ys): returns acc / wsum per pixel (N, C)."""
    from . import ops
    col_t, m_t, tx_t, ty_t = ops.t(col), ops.t(m), ops.t(tx), ops.t(ty)
    xi, yi = torch.as_tensor(xs, device=ops.DEV), torch.as_tensor(ys, device=ops.DEV)
    acc = col_t[yi, xi].clone()
    wsum = torch.ones(len(xs), dtype=torch.float64, device=ops.DEV)
    for sgn in (1.0, -1.0):
        px, py = xi.to(torch.float64), yi.to(torch.float64)
        dx, dy = tx_t[yi, xi] * sgn, ty_t[yi, xi] * sgn
        alive = torch.ones(len(xs), dtype=torch.bool, device=ops.DEV)
        for k in range(1, nsteps + 1):
            px, py = px + h * dx, py + h * dy
            ntx, nty = ops.band_bilinear(tx_t, px, py), ops.band_bilinear(ty_t, px, py)
            flip = (ntx * dx + nty * dy) < 0
            ntx, nty = torch.where(flip, -ntx, ntx), torch.where(flip, -nty, nty)
            nn = torch.hypot(ntx, nty) + 1e-12
            dx, dy = ntx / nn, nty / nn
            alive &= ops.band_bilinear(m_t, px, py) > 0.5
            w = torch.exp(torch.tensor(-0.5 * (k * h / L / along) ** 2, dtype=torch.float64,
                                       device=ops.DEV)) * alive
            acc += ops.band_bilinear(col_t, px, py) * w[:, None]
            wsum += w
            if k % 8 == 0 and not bool(alive.any()):
                break               # later steps add exactly 0, so checking rarely changes nothing
    return (acc / wsum[:, None]).cpu().numpy()


def comb_mean(rgb, xs, ys, tx, ty, L, steps):
    """hybrid._edge_comb's mean of _sample along the tangent over `steps`."""
    from . import ops
    f, txt, tyt = ops.t(rgb), ops.t(tx), ops.t(ty)
    px, py = ops.t(xs), ops.t(ys)
    acc = torch.zeros_like(f)
    for k in steps:
        acc += ops.sample(f, px + txt * k * L, py + tyt * k * L)
    acc /= len(steps)
    return acc.cpu().numpy()


def band_smooth(v, sides, ker, r):
    """hybrid._band_smooth for a stack of rows: every side padded with zeros to
    the longest, one convolution for the lot. Rows are (..., NS); `sides` is the
    list of station indices per side. Not bit-identical to np.convolve (another
    summation order), the same to ~1e-13."""
    lead = v.shape[:-1]
    rows = int(np.prod(lead)) if lead else 1
    flat = np.ascontiguousarray(v).reshape(rows, v.shape[-1])
    L = max(len(i) for i in sides)
    buf = np.zeros((len(sides), rows + 1, L + 2 * r))
    for k, idx in enumerate(sides):
        buf[k, :rows, r:r + len(idx)] = flat[:, idx]
        buf[k, rows, r:r + len(idx)] = 1.0                    # the weight row
    from . import ops
    x = ops.t(buf).reshape(-1, 1, L + 2 * r)
    w = ops.t(ker).reshape(1, 1, -1)
    y = torch.nn.functional.conv1d(x, w).reshape(len(sides), rows + 1, L).cpu().numpy()
    out = np.empty_like(flat)
    for k, idx in enumerate(sides):
        out[:, idx] = y[k, :rows, :len(idx)] / y[k, rows, :len(idx)]
    return out.reshape(v.shape)


def point_converge(rgb, corners, L, read, reach, taps):
    """hybrid._point_converge's disc reads. The coordinates are numpy's own (a
    1 ulp difference in a cosine moved one pixel of Handwriting by three
    levels); only the lookups, the part that costs, run on the device."""
    from . import ops
    n = rgb.shape[0]
    out = np.array(rgb, dtype=np.float64)
    ys, xs = np.mgrid[0:n, 0:n] + 0.5
    px, py = xs / L, ys / L
    for cx, cy in corners:
        src = ops.t(out)
        dx, dy = px - cx, py - cy
        r = np.hypot(dx, dy)
        m = r < reach
        rm = r[m]
        rho = rm + read * (1.0 - rm / reach) ** 2
        th = np.arctan2(dy[m], dx[m])
        span = np.maximum(1.0 / np.maximum(rm, 1.0 / L) - 1.0 / rho, 0.0) / L
        acc = 0.0
        for j in range(taps):
            a = th + ((j + 0.5) / taps - 0.5) * span
            acc = acc + ops.sample(src, ops.t((cx + rho * np.cos(a)) * L - 0.5),
                                   ops.t((cy + rho * np.sin(a)) * L - 0.5))
        out[m] = (acc / taps).cpu().numpy()
    return out

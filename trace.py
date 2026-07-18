"""Trace vector silhouettes and glass shading straight from the original
Chrome Glass frames, so the vector edition keeps the authentic shapes.

Outputs, per cursor frame: a simplified polygon (32-logical coords), a fitted
linear RGBA gradient, and a highlight polygon derived from the residual bright
region. Used by cursors.py at build time (results are cached to traced.json).
"""
import json, os, sys
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("LG_FRAMES", os.path.join(HERE, "src", "ai"))


def _erode(m):
    e = m.copy()
    e[1:, :] &= m[:-1, :]; e[:-1, :] &= m[1:, :]
    e[:, 1:] &= m[:, :-1]; e[:, :-1] &= m[:, 1:]
    return e


def boundary_chain(mask):
    edge = mask & ~_erode(mask)
    ys, xs = np.nonzero(edge)
    pts = list(zip(xs.tolist(), ys.tolist()))
    if not pts:
        return []
    start = min(pts, key=lambda p: (p[1], p[0]))
    pts.remove(start)
    chain = [start]
    while pts:
        cx, cy = chain[-1]
        j = min(range(len(pts)), key=lambda i: (pts[i][0] - cx) ** 2 + (pts[i][1] - cy) ** 2)
        if (pts[j][0] - cx) ** 2 + (pts[j][1] - cy) ** 2 > 36:
            break
        chain.append(pts.pop(j))
    return chain


def simplify(points, eps):
    if len(points) < 3:
        return points
    (x1, y1), (x2, y2) = points[0], points[-1]
    den = ((y2 - y1) ** 2 + (x2 - x1) ** 2) ** .5 or 1e-9
    dmax, idx = 0.0, 0
    for i in range(1, len(points) - 1):
        x0, y0 = points[i]
        dist = abs((y2 - y1) * x0 - (x2 - x1) * y0 + x2 * y1 - y2 * x1) / den
        if dist > dmax:
            dmax, idx = dist, i
    if dmax > eps:
        l = simplify(points[:idx + 1], eps)
        r = simplify(points[idx:], eps)
        return l[:-1] + r
    return [points[0], points[-1]]


def _components(mask, min_px=60):
    """Label 4-connected components, return list of sub-masks, largest first."""
    lab = np.zeros(mask.shape, dtype=np.int32)
    cur = 0
    H, W = mask.shape
    for sy in range(H):
        for sx in range(W):
            if mask[sy, sx] and not lab[sy, sx]:
                cur += 1
                stack = [(sy, sx)]
                lab[sy, sx] = cur
                while stack:
                    y, x = stack.pop()
                    for ny, nx in ((y-1, x), (y+1, x), (y, x-1), (y, x+1)):
                        if 0 <= ny < H and 0 <= nx < W and mask[ny, nx] and not lab[ny, nx]:
                            lab[ny, nx] = cur
                            stack.append((ny, nx))
    out = []
    for i in range(1, cur + 1):
        m = lab == i
        if m.sum() >= min_px:
            out.append(m)
    out.sort(key=lambda m: -m.sum())
    return out


def trace_frame(key, thresh=60, eps=1.3):
    """key like 'cur__Arrow__0' -> dict with polys / gradient / highlight."""
    im = Image.open(os.path.join(SRC, key + ".png")).convert("RGBA")
    arr = np.array(im, dtype=np.float64)
    a = arr[:, :, 3]
    # perceptual silhouette: threshold relative to this cursor's own peak alpha,
    # so faint glass cursors keep their shape and blur halo is not swallowed
    thresh = max(30.0, min(0.45 * a.max(), 55.0))
    mask = a > thresh

    polys = []
    for comp in _components(mask, min_px=25):
        chain = boundary_chain(comp)
        poly = [(x / 4.0, y / 4.0) for x, y in chain]      # 128 -> 32 logical
        poly = simplify(poly, eps / 4.0)
        if len(poly) > 2 and poly[0] == poly[-1]:
            poly = poly[:-1]
        if len(poly) >= 3:
            polys.append(poly)

    # gradient: least-squares for the DIRECTION, percentile colours for the
    # ENDPOINTS (linear endpoints average away the glass saturation)
    ys, xs = np.nonzero(a > thresh)
    A = np.c_[xs / 4.0, ys / 4.0, np.ones(len(xs))]
    sol, *_ = np.linalg.lstsq(A, arr[ys, xs, :], rcond=None)
    gx, gy, c0 = sol[0], sol[1], sol[2]
    dirv = np.array([gx[:3].mean(), gy[:3].mean()])
    n = np.linalg.norm(dirv) or 1e-9
    u = dirv / n
    t = (xs / 4.0) * u[0] + (ys / 4.0) * u[1]
    t0, t1 = t.min(), t.max()
    p0 = (u[0] * t0, u[1] * t0)
    p1 = (u[0] * t1, u[1] * t1)
    lo = t <= np.quantile(t, 0.15)
    hi = t >= np.quantile(t, 0.85)
    cols = arr[ys, xs, :]

    def avg_col(sel):
        return [int(min(255, max(0, round(c)))) for c in cols[sel].mean(axis=0)]

    col_p0, col_p1 = avg_col(lo), avg_col(hi)

    def col_at(x, y):        # kept for highlight residual prediction below
        v = c0 + gx * x + gy * y
        return [int(min(255, max(0, round(c)))) for c in v]

    # highlight: pixels notably brighter than the gradient prediction
    pred = c0[None, :] + np.outer(xs / 4.0, gx) + np.outer(ys / 4.0, gy)
    lum = arr[ys, xs, :3].mean(axis=1)
    plum = pred[:, :3].mean(axis=1)
    bright = lum - plum > 18
    hl = None
    if bright.sum() > 30:
        hxs, hys = xs[bright], ys[bright]
        hmask = np.zeros_like(mask)
        hmask[hys, hxs] = True
        hchain = boundary_chain(hmask)
        if len(hchain) > 8:
            hp = [(x / 4.0, y / 4.0) for x, y in hchain]
            hp = simplify(hp, 0.5)
            if len(hp) >= 3:
                hl = [[round(x, 2), round(y, 2)] for x, y in hp]

    return {
        "polys": [[[round(x, 2), round(y, 2)] for x, y in poly] for poly in polys],
        "grad": [col_p0, col_p1,
                 [round(p0[0], 2), round(p0[1], 2), round(p1[0], 2), round(p1[1], 2)]],
        "highlight": hl,
    }


STATIC = ["Arrow", "Arrow_Down", "Cross", "Help", "IBeam", "SizeAll",
          "SizeNESW", "SizeNS", "SizeNWSE", "SizeWE", "UpArrow"]
ANI = {"AppStarting": 9, "Hand": 9, "Handwriting": 9, "NO": 11, "Wait": 9}


def main():
    out = {}
    for name in STATIC:
        out[name] = {"frames": [trace_frame(f"cur__{name}__0")]}
        fr = out[name]["frames"][0]
        print("traced", name, len(fr["polys"]), "components,",
              sum(len(p) for p in fr["polys"]), "pts")
    for name, n in ANI.items():
        out[name] = {"frames": [trace_frame(f"ani__{name}__{i}") for i in range(n)]}
        print("traced", name, "x", n)
    json.dump(out, open(os.path.join(HERE, "traced.json"), "w"))
    print("wrote traced.json")


if __name__ == "__main__":
    main()

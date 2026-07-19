"""Trace vector silhouettes and glass shading straight from the original
Chrome Glass frames, so the vector edition keeps the authentic shapes.

Outputs, per cursor frame: a simplified polygon (32-logical coords), a fitted
linear RGBA gradient, and a highlight polygon derived from the residual bright
region. Used by cursors.py at build time (results are cached to traced.json).
"""
import json, math, os, sys
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


CORNER_WINDOW = 6        # raw boundary pixels on each side of a point
CORNER_KEEP_DEG = 55     # windowed turn angle above this = genuine corner


def corner_curvature(raw_chain):
    """Windowed turning-angle curvature over the dense (pre-simplify) boundary
    chain. A single-pixel-jitter-resistant alternative to a 3-point angle:
    for each point, fit the average direction of the CORNER_WINDOW points
    before it and after it, and measure the turn between those two directions."""
    n = len(raw_chain)
    if n < 2 * CORNER_WINDOW + 1:
        return [False] * n
    flags = []
    for i in range(n):
        p = raw_chain[i]
        before = raw_chain[(i - CORNER_WINDOW) % n]
        after = raw_chain[(i + CORNER_WINDOW) % n]
        a1 = math.atan2(p[1] - before[1], p[0] - before[0])
        a2 = math.atan2(after[1] - p[1], after[0] - p[0])
        turn = abs((a2 - a1 + math.pi) % (2 * math.pi) - math.pi)
        flags.append(turn > math.radians(CORNER_KEEP_DEG))
    return flags


def nearest_raw_flag(pt, raw_chain, raw_flags):
    """Is the raw boundary point closest to pt (a simplified/logical-scale
    vertex) flagged as a genuine corner?"""
    bx, by = pt[0] * 4.0, pt[1] * 4.0
    best_i, best_d = 0, float("inf")
    for i, (x, y) in enumerate(raw_chain):
        d = (x - bx) ** 2 + (y - by) ** 2
        if d < best_d:
            best_d, best_i = d, i
    return raw_flags[best_i]


def merge_corner_clusters(poly, flags):
    """A genuine tip is ONE vertex, but curvature detection can flag 2-3
    consecutive simplified vertices near an apex as corners (each sees a
    sharp turn within its window) - smooth() then leaves all of them crisp,
    which draws a tiny flat facet across the run instead of a point. Collapse
    each run of consecutive corner flags down to its single most extreme
    vertex (the one farthest from the chord joining its non-corner
    neighbours), so the tip stays one true point."""
    n = len(poly)
    if n < 3 or not any(flags):
        return poly, flags
    if all(flags):
        # every vertex flagged (degenerate) - nothing to anchor a run to
        return poly, flags
    # start scanning from a non-corner vertex so a run that wraps around the
    # array boundary (e.g. the tail corner sitting at index 0/n-1) is walked
    # as a single contiguous run instead of being split by the array seam
    start = next(k for k in range(n) if not flags[k])
    order = [(start + k) % n for k in range(n)]
    runs = []
    i = 0
    visited = [False] * n
    while i < n:
        idx = order[i]
        if flags[idx] and not visited[idx]:
            run = [idx]
            visited[idx] = True
            jj = i + 1
            while jj < n and flags[order[jj]] and not visited[order[jj]]:
                run.append(order[jj])
                visited[order[jj]] = True
                jj += 1
            runs.append(run)
            i = jj
        else:
            i += 1
    if all(len(r) <= 1 for r in runs):
        return poly, flags
    drop = set()
    replace = {}
    for run in runs:
        if len(run) <= 1:
            continue
        before = poly[(run[0] - 1) % n]
        after = poly[(run[-1] + 1) % n]
        dx, dy = after[0] - before[0], after[1] - before[1]
        norm = (dx * dx + dy * dy) ** 0.5 or 1e-9
        best_idx, best_dist = run[0], -1.0
        for idx in run:
            x, y = poly[idx]
            dist = abs((y - before[1]) * dx - (x - before[0]) * dy) / norm
            if dist > best_dist:
                best_dist, best_idx = dist, idx
        for idx in run:
            if idx != best_idx:
                drop.add(idx)
        replace[best_idx] = True
    out_poly = [p for i, p in enumerate(poly) if i not in drop]
    out_flags = [replace.get(i, flags[i]) for i in range(n) if i not in drop]
    return out_poly, out_flags


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


def trace_frame(key, thresh=60, eps=0.7):
    """key like 'cur__Arrow__0' -> dict with polys / gradient / highlight."""
    im = Image.open(os.path.join(SRC, key + ".png")).convert("RGBA")
    arr = np.array(im, dtype=np.float64)
    a = arr[:, :, 3]
    # perceptual silhouette: threshold relative to this cursor's own peak alpha,
    # so faint glass cursors keep their shape and blur halo is not swallowed
    thresh = max(30.0, min(0.45 * a.max(), 55.0))
    mask = a > thresh

    polys = []
    corner_flags = []
    for comp in _components(mask, min_px=25):
        chain = boundary_chain(comp)
        # corner classification on the dense raw chain, before any
        # simplification collapses a genuine tip into a misleading angle
        raw_flags = corner_curvature(chain)
        poly = [(x / 4.0, y / 4.0) for x, y in chain]      # 128 -> 32 logical
        poly = simplify(poly, eps / 4.0)
        if len(poly) > 2 and poly[0] == poly[-1]:
            poly = poly[:-1]
        if len(poly) >= 3:
            flags = [nearest_raw_flag(p, chain, raw_flags) for p in poly]
            poly, flags = merge_corner_clusters(poly, flags)
            polys.append(poly)
            corner_flags.append(flags)

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
        "polys": [[[round(x, 2), round(y, 2), bool(c)] for (x, y), c in zip(poly, flags)]
                  for poly, flags in zip(polys, corner_flags)],
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

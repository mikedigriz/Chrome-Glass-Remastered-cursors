"""Trace vector silhouettes straight from the original Chrome Glass frames, so
the vector edition keeps the authentic shapes.

Output, per cursor frame: a simplified polygon in 32-logical coordinates, with
a per-vertex corner flag. Cached to traced.json and read by hybrid._mask at
build time. (Earlier revisions also fitted a linear gradient and a highlight
polygon here; nothing ever consumed them, so both are gone.)
"""
import json, math, os, statistics
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
# Every logical<->raw conversion below hardcodes the 4x of a 128px source
# (128 / 32 logical). Pointing this at another level silently scales the whole
# geometry, so the size is asserted per frame in trace_frame.
SRC = os.environ.get("LG_FRAMES", os.path.join(HERE, "src", "ai"))
SRC_PX = 128


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
        left = simplify(points[:idx + 1], eps)
        right = simplify(points[idx:], eps)
        return left[:-1] + right
    return [points[0], points[-1]]


CORNER_WINDOW = 6        # raw boundary pixels on each side of a point
CORNER_KEEP_DEG = 55     # windowed turn angle above this = genuine corner

CORNER_GAP = 2           # raw px skipped either side of a corner run before fitting
FLANK_WIN = 14           # raw px per flank fit window (3.5 logical of arc)
FLANK_MIN = 8            # fewer usable raw px than this -> reject the reconstruction
FLANK_RES_MAX = 1.0      # max RMS residual (raw px) of a flank line fit
APEX_ANG_MIN = 20.0      # degrees between the two flanks at the reconstructed apex
APEX_ANG_MAX = 150.0
TIP_MAX_EXT = 0.75       # logical: max protrusion of the apex past the run chord
TIP_LOCK = 1.25          # logical: no vertex is reinserted this close to an apex
TIP_REINSERT = 0.5       # logical: only gross excursions come back near an apex
SNAP_R = 0.5             # logical: cross-frame corner match/snap radius


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


def nearest_raw_index(pt, raw_chain):
    """Index of the raw boundary point closest to pt (a simplified vertex in
    logical scale) - the link between the two representations."""
    bx, by = pt[0] * 4.0, pt[1] * 4.0
    best_i, best_d = 0, float("inf")
    for i, (x, y) in enumerate(raw_chain):
        d = (x - bx) ** 2 + (y - by) ** 2
        if d < best_d:
            best_d, best_i = d, i
    return best_i


def runs_cyclic(flags):
    """Maximal runs of consecutive True, walked from a False so a run sitting
    across the array seam comes back as one contiguous run. Empty when nothing
    or everything is flagged (nothing to anchor a run to)."""
    n = len(flags)
    if n == 0 or not any(flags) or all(flags):
        return []
    start = next(k for k in range(n) if not flags[k])
    runs, run = [], None
    for k in range(n):
        i = (start + k) % n
        if flags[i]:
            run = [i] if run is None else run + [i]
        elif run is not None:
            runs.append(run)
            run = None
    if run is not None:
        runs.append(run)
    return runs


def _in_arc(x, lo, hi, n):
    """Is index x inside the cyclic interval [lo, hi] of a length-n ring?"""
    return lo <= x <= hi if lo <= hi else (x >= lo or x <= hi)


def _fit_line(pts):
    """Total-least-squares line through raw boundary points -> (centre, unit
    direction, RMS residual). Fitting the dense 128px chain rather than the
    already-simplified vertices is what makes the flank direction stable."""
    p = np.asarray(pts, dtype=np.float64)
    c = p.mean(axis=0)
    d = np.linalg.svd(p - c, full_matrices=False)[2][0]
    off = p - c
    res = off - np.outer(off @ d, d)
    return c, d, float(np.sqrt((res ** 2).sum(axis=1).mean()))


def _flank(chain, flags, start, step):
    """Up to FLANK_WIN raw points walking away from a corner run, stopping
    before a neighbouring corner so one fit never spans two corners."""
    n = len(chain)
    out, i = [], start % n
    for _ in range(FLANK_WIN):
        if flags[i]:
            break
        out.append(chain[i])
        i = (i + step) % n
    return out


def _outward(chain, run, centroid):
    """(anchor point, outward unit normal) of a corner run's chord."""
    n = len(chain)
    p0 = np.asarray(chain[run[0]], dtype=np.float64)
    p1 = np.asarray(chain[run[-1]], dtype=np.float64)
    mid = (p0 + p1) / 2.0
    ch = p1 - p0
    length = float(np.hypot(*ch))
    if length < 1e-6:                       # single-point run: no chord to use
        away = mid - centroid
        nrm = away / (float(np.hypot(*away)) or 1e-9)
        return mid, nrm
    nrm = np.array([-ch[1], ch[0]]) / length
    if nrm @ (mid - centroid) < 0:
        nrm = -nrm
    return p0, nrm


def reconstruct_apex(chain, flags, run, centroid):
    """The sharp point where a corner's two straight flanks meet.

    The source frames round every tip off over about a pixel, so the traced
    boundary holds a small blunt nose, not a point. Fit a line to each flank
    (away from that nose, where the threshold noise lives), intersect the two,
    and that is the point the artwork implies. The intersection is clamped to
    TIP_MAX_EXT past the nose's own chord: unclamped it would extrapolate the
    slightly convex flanks well outside the 2006 silhouette. Returns a logical
    (x, y) or None when the geometry does not support a reconstruction."""
    i0, i1 = run[0], run[-1]
    a = _flank(chain, flags, i0 - CORNER_GAP, -1)
    b = _flank(chain, flags, i1 + CORNER_GAP, +1)
    if len(a) < FLANK_MIN or len(b) < FLANK_MIN:
        return None
    ca, da, ra = _fit_line(a)
    cb, db, rb = _fit_line(b)
    if max(ra, rb) > FLANK_RES_MAX:
        return None
    m = np.array([[da[0], -db[0]], [da[1], -db[1]]])
    if abs(np.linalg.det(m)) < 1e-6:                    # flanks parallel
        return None
    t = np.linalg.solve(m, cb - ca)
    p = ca + t[0] * da
    anchor, nrm = _outward(chain, run, centroid)
    prot = float((p - anchor) @ nrm)
    if prot < 0:                                        # intersection fell inside
        return None
    if prot > TIP_MAX_EXT * 4.0:
        p = p - (prot - TIP_MAX_EXT * 4.0) * nrm
    ray_a = np.asarray(a[min(len(a) - 1, FLANK_MIN - 1)], dtype=np.float64) - p
    ray_b = np.asarray(b[min(len(b) - 1, FLANK_MIN - 1)], dtype=np.float64) - p
    na, nb = float(np.hypot(*ray_a)), float(np.hypot(*ray_b))
    if na < 1e-6 or nb < 1e-6:
        return None
    ang = math.degrees(math.acos(max(-1.0, min(1.0, (ray_a @ ray_b) / (na * nb)))))
    if not APEX_ANG_MIN <= ang <= APEX_ANG_MAX:
        return None
    return (p[0] / 4.0, p[1] / 4.0)


def _seg_dist(pt, a, b):
    """Distance from pt to segment ab."""
    ax, ay = a; bx, by = b; px, py = pt
    dx, dy = bx - ax, by - ay
    den = dx * dx + dy * dy
    t = 0.0 if den < 1e-12 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / den))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _extreme(run_pts, before, after):
    """Index within run_pts of the vertex farthest from the before-after chord."""
    dx, dy = after[0] - before[0], after[1] - before[1]
    norm = (dx * dx + dy * dy) ** 0.5 or 1e-9
    best, best_d = 0, -1.0
    for k, (x, y) in enumerate(run_pts):
        d = abs((y - before[1]) * dx - (x - before[0]) * dy) / norm
        if d > best_d:
            best_d, best = d, k
    return best


def sharpen_corners(poly, chain, flags, eps):
    """Rebuild a simplified polygon with one sharp vertex per genuine corner.

    Corner runs are taken from the dense raw chain, so a flank vertex that the
    windowed curvature happened to flag near a tip is no longer mistaken for
    part of the corner and deleted - the old collapse did exactly that, which
    left the arrow's left edge as a vertical wall and its point as a facet.

    Each run becomes its reconstructed apex (see reconstruct_apex), flagged as
    a corner; the vertices it replaced come back only when they sit well off
    the two new edges and far enough from the apex, so a real feature survives
    but the nose does not re-blunt the point. Runs whose reconstruction is
    rejected fall back to their most extreme vertex, with the same reinsertion
    test at the plain simplification tolerance.

    Returns (poly, flags, apexes) where poly holds (x, y) tuples and apexes is
    the list of output indices carrying a reconstructed apex."""
    n, m = len(poly), len(chain)
    runs = runs_cyclic(flags)
    if n < 3 or not runs:
        return poly, [False] * n, []
    rmap = [nearest_raw_index(p, chain) for p in poly]
    centroid = np.asarray(chain, dtype=np.float64).mean(axis=0)

    owners = [None] * n
    for ri, run in enumerate(runs):
        lo, hi = (run[0] - CORNER_GAP) % m, (run[-1] + CORNER_GAP) % m
        for i in range(n):
            if owners[i] is None and _in_arc(rmap[i], lo, hi, m):
                owners[i] = ri

    # walk from a vertex no run owns, so an owned stretch across the seam stays
    # contiguous; the polygon is cyclic, its start vertex carries no meaning
    free = [i for i in range(n) if owners[i] is None]
    if not free:
        return poly, [False] * n, []
    start = free[0]
    order = [(start + k) % n for k in range(n)]

    out, out_flags, apexes = [], [], []
    placed = set()
    k = 0
    while k < n:
        i = order[k]
        ri = owners[i]
        if ri is None:
            out.append(poly[i])
            out_flags.append(False)
            k += 1
            continue
        group = []
        while k < n and owners[order[k]] == ri:
            group.append(order[k])
            k += 1
        placed.add(ri)
        before, after = out[-1], poly[order[k % n]]
        run_pts = [poly[i] for i in group]
        apex = reconstruct_apex(chain, flags, runs[ri], centroid)
        if apex is None:
            slot = _extreme(run_pts, before, after)
            apex, tol, lock, is_apex = run_pts[slot], eps, 0.0, False
        else:
            slot = _extreme(run_pts, before, after)
            tol, lock, is_apex = TIP_REINSERT, TIP_LOCK, True
        for k2, v in enumerate(run_pts):
            if k2 == slot:
                if is_apex:
                    apexes.append(len(out))
                out.append(apex)
                out_flags.append(True)
                continue
            keep = (min(_seg_dist(v, before, apex), _seg_dist(v, apex, after)) > tol
                    and math.dist(v, apex) > lock)
            if keep:
                out.append(v)
                out_flags.append(False)
    # a corner is always one vertex: never leave two flagged neighbours
    for i in range(len(out)):
        if out_flags[i] and out_flags[(i + 1) % len(out)]:
            out_flags[(i + 1) % len(out)] = False
    apexes = [i for i in apexes if out_flags[i]]
    return out, out_flags, apexes


def _components(mask, min_px):
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


def trace_frame(key, eps=0.7):
    """key like 'cur__Arrow__0' -> {"polys": [...], "_apex": [...]}."""
    im = Image.open(os.path.join(SRC, key + ".png")).convert("RGBA")
    if im.size != (SRC_PX, SRC_PX):
        raise SystemExit("%s is %dx%d, expected %dx%d - the logical scale below "
                         "is hardcoded to that size" % ((key,) + im.size + (SRC_PX, SRC_PX)))
    arr = np.array(im, dtype=np.float64)
    a = arr[:, :, 3]
    # perceptual silhouette: threshold relative to this cursor's own peak alpha,
    # so faint glass cursors keep their shape and blur halo is not swallowed
    thresh = max(30.0, min(0.45 * a.max(), 55.0))
    mask = a > thresh

    polys = []
    corner_flags = []
    apex_idx = []
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
            poly, flags, apexes = sharpen_corners(poly, chain, raw_flags, eps / 4.0)
            polys.append(poly)
            corner_flags.append(flags)
            apex_idx.append(apexes)

    return {
        "polys": [[[round(x, 2), round(y, 2), bool(c)] for (x, y), c in zip(poly, flags)]
                  for poly, flags in zip(polys, corner_flags)],
        "_apex": apex_idx,          # per component: output indices of reconstructed
                                    # apexes; consumed by snap_corners, never written
    }


STATIC = ["Arrow", "Arrow_Down", "Cross", "Help", "IBeam", "SizeAll",
          "SizeNESW", "SizeNS", "SizeNWSE", "SizeWE", "UpArrow"]
ANI = {"AppStarting": 9, "Hand": 9, "Handwriting": 9, "NO": 11, "Wait": 9}


def snap_corners(frames):
    """Give a corner that stands still across an animation one shared position.

    Every frame is traced on its own, so a reconstructed apex can land a
    fraction of a unit apart from frame to frame - on a 60 fps pointer that
    reads as a tip that wobbles while the rest of the cursor animates. Match
    apexes across frames within SNAP_R and, when a match exists in every frame
    and the whole group fits inside that radius, write the median to all of
    them. A genuinely moving corner (spread beyond SNAP_R) is left alone.

    Consumes the "_apex" key. Iteration order is fixed so the JSON stays
    byte-identical run to run - CI diffs traced.json."""
    apex = [f.pop("_apex") for f in frames]
    if len(frames) < 2:
        return
    for ci in range(min(len(a) for a in apex)):
        taken = [set() for _ in frames]
        for vi in apex[0][ci]:
            x, y = frames[0]["polys"][ci][vi][:2]
            group = [(0, vi, x, y)]
            for fi in range(1, len(frames)):
                cand = []
                for vj in apex[fi][ci]:
                    if vj in taken[fi]:
                        continue
                    xj, yj = frames[fi]["polys"][ci][vj][:2]
                    if math.dist((x, y), (xj, yj)) <= SNAP_R:
                        cand.append((math.dist((x, y), (xj, yj)), vj, xj, yj))
                if not cand:
                    break
                _, vj, xj, yj = min(cand)
                group.append((fi, vj, xj, yj))
            if len(group) < len(frames):
                continue
            mx = round(statistics.median([g[2] for g in group]), 2)
            my = round(statistics.median([g[3] for g in group]), 2)
            if max(math.dist((g[2], g[3]), (mx, my)) for g in group) > SNAP_R:
                continue
            for fi, vj, _, _ in group:
                frames[fi]["polys"][ci][vj][0] = mx
                frames[fi]["polys"][ci][vj][1] = my
                taken[fi].add(vj)


def main():
    out = {}
    for name in STATIC:
        out[name] = {"frames": [trace_frame(f"cur__{name}__0")]}
        snap_corners(out[name]["frames"])
        fr = out[name]["frames"][0]
        print("traced", name, len(fr["polys"]), "components,",
              sum(len(p) for p in fr["polys"]), "pts")
    for name, n in ANI.items():
        out[name] = {"frames": [trace_frame(f"ani__{name}__{i}") for i in range(n)]}
        snap_corners(out[name]["frames"])
        print("traced", name, "x", n)
    with open(os.path.join(HERE, "traced.json"), "w", encoding="utf-8") as f:
        json.dump(out, f)
    print("wrote traced.json")


if __name__ == "__main__":
    main()

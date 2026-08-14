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


STRAIGHT_TOL = 2.5       # multiples of the simplifier's own eps a run may bow.
                         #
                         # Derived, not tuned. The run test measures each vertex
                         # against the chord between the run's two endpoints, and
                         # all three are samples of the same sawtooth: the
                         # interior may sit eps off the true line, and so may
                         # each endpoint, which tilts the chord as well. A
                         # genuinely straight edge therefore reads up to about
                         # 2 eps off its own chord before sharpen_corners has
                         # nudged anything, so anything under that must still be
                         # admitted as straight.
                         #
                         # The ceiling is measured, from a source the render
                         # never touches: the distance from each polygon vertex
                         # to the dense 128px boundary chain, which is what the
                         # master actually draws. Straightening moves the mean of
                         # that distance up to the staircase's own half-pixel
                         # scale and no further, which is simply what a straight
                         # line through a staircase costs; the number that says
                         # whether a span swallowed a bend is the per-cursor
                         # maximum. Through 2.5 eps not one of those maxima moves
                         # at all, on any cursor. At 3 they start (IBeam 0.266 ->
                         # 0.304, Cross -> 0.366 at 3.4) and edge_straight's own
                         # worst window goes backwards on three cursors, both
                         # symptoms of a span being called straight over a bend.
                         # 2.5 is the last value that is free: it takes Cross's
                         # wander at 512 from 0.147 rms to 0.033 and costs
                         # nothing measurable anywhere.
STRAIGHT_MIN = 4         # vertices a run needs before it is worth fitting


def _chord_off(pts, i, j):
    """Largest perpendicular distance from pts[i..j] to the chord i->j."""
    a, b = pts[i], pts[j]
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy)
    if n < 1e-9:
        return float("inf")
    ux, uy = dx / n, dy / n
    return max(abs((p[0] - a[0]) * (-uy) + (p[1] - a[1]) * ux)
               for p in pts[i:j + 1])


STRAIGHT_BALANCE = 0.4   # how evenly a run's vertices must straddle their own
                         # chord, as the lighter side's share of the heavier one.
                         #
                         # This is the defect's own definition used as the test
                         # for it. The sawtooth is vertices alternating either
                         # side of the line they belong on, so it puts the same
                         # mass on both sides of the chord and this reads near 1.
                         # A genuine arc has every vertex on one side and reads
                         # near 0 - and straightening one does not tidy an edge,
                         # it bridges the curve and puts outline where the art
                         # has none.
                         #
                         # Which is not hypothetical. Without this, Cross and
                         # IBeam lost 0.017 and 0.015 of silhouette IoU against
                         # the author's own 32px art, because their arms are
                         # drawn slightly concave and a straight line across a
                         # concave arm sits outside every pixel of it. Nothing
                         # else in the pass could see that: the chord test only
                         # asks how far, never which side, and Douglas-Peucker
                         # splitting an arc in two just gives two chords that
                         # each bridge half of it.
STRAIGHT_MAX_SEG = 2     # straight pieces a span between two corners may hold.
                         # Two is an edge with one bend in it, which this art has
                         # plenty of. More than two and the span is a curve, and
                         # cutting a curve into straight pieces is how you
                         # polygonise it.
STRAIGHT_TIP_DEG = 100.0  # interior angle above which a corner is a joint rather
                          # than a point. Straightening never moves a corner, but
                          # it moves both of its neighbours, and this angle is
                          # what decides which of the two the corner is: the
                          # first version tightened a Handwriting joint from 110
                          # to 97 degrees and the cursor grew a third tip, which
                          # the topology check caught. So a span is put back
                          # whenever straightening it would carry either end
                          # across this line. Guarding the size of the change
                          # instead was tried and is the wrong shape - a few
                          # degrees is normal and harmless everywhere except at
                          # this one boundary, so a threshold on it either reverts
                          # everything or protects nothing.


def _dp_breaks(pts, a, b, tol):
    """Douglas-Peucker breakpoints of pts[a..b], the ends included.

    Same rule the simplifier upstream runs on, for the same reason: the vertex
    that departs furthest from the chord is where the edge actually bends, so a
    seam put there lands on a feature instead of on an arbitrary vertex of a
    slow curve."""
    if b - a < 2 or _chord_off(pts, a, b) <= tol:
        return [a, b]
    p, q = pts[a], pts[b]
    dx, dy = q[0] - p[0], q[1] - p[1]
    n = math.hypot(dx, dy) or 1e-9
    ux, uy = dx / n, dy / n
    k = max(range(a + 1, b),
            key=lambda i: abs((pts[i][0] - p[0]) * (-uy)
                              + (pts[i][1] - p[1]) * ux))
    return _dp_breaks(pts, a, k, tol)[:-1] + _dp_breaks(pts, k, b, tol)


def _angle_at(pts, i, n):
    """Interior angle at vertex i of a closed ring, in degrees."""
    v, p, q = pts[i % n], pts[(i - 1) % n], pts[(i + 1) % n]
    a1 = math.atan2(p[1] - v[1], p[0] - v[0])
    a2 = math.atan2(q[1] - v[1], q[0] - v[0])
    return abs(math.degrees((a2 - a1 + math.pi) % (2 * math.pi) - math.pi))


def _balance(pts, i, j):
    """How evenly pts[i..j] straddles its own chord: 0 all one side, 1 even.

    Measured against the chord and not against the fitted line, which was the
    first attempt and reads 1 for everything - total least squares centres its
    own residuals by construction, so an arc balances about its fit as neatly as
    a sawtooth does. The chord has no such property: an arc bows entirely to one
    side of it, which is what an arc is."""
    a, b = pts[i], pts[j]
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy)
    if n < 1e-9:
        return 0.0
    ux, uy = dx / n, dy / n
    pos = neg = 0.0
    for p in pts[i + 1:j]:
        s = (p[0] - a[0]) * (-uy) + (p[1] - a[1]) * ux
        if s > 0:
            pos += s
        else:
            neg -= s
    hi = max(pos, neg)
    return min(pos, neg) / hi if hi > 1e-9 else 0.0


def _tls_line(run):
    """Centroid and direction of the total-least-squares line through run.

    Orthogonal, not y on x: these edges run in every direction, vertical ones
    included, and a fit of y on x has no answer for those."""
    cx = sum(p[0] for p in run) / len(run)
    cy = sum(p[1] for p in run) / len(run)
    sxx = sum((p[0] - cx) ** 2 for p in run)
    syy = sum((p[1] - cy) ** 2 for p in run)
    sxy = sum((p[0] - cx) * (p[1] - cy) for p in run)
    ang = 0.5 * math.atan2(2.0 * sxy, sxx - syy)
    return cx, cy, math.cos(ang), math.sin(ang)


def straighten_runs(poly, flags, eps, tol=STRAIGHT_TOL, minlen=STRAIGHT_MIN):
    """Sit the interior vertices of a straight run on the line they are meant to
    be on.

    Douglas-Peucker keeps every vertex within `eps` of the chain it is
    simplifying, and does so vertex by vertex, so a straight edge comes back as
    a run of vertices alternating either side of the line the author drew - each
    one legal, the run as a whole a sawtooth. `C.smooth` in the renderer then
    turns that sawtooth into a slower S-curve rather than removing it, which is
    why the wander grows with the size the cursor is drawn at instead of
    averaging out. Measured with edge_straight in tools/analyze.py: up to 0.624
    logical units on SizeAll, 0.467 on IBeam, 0.444 on Help, which at 512 is ten
    pixels of visible waviness on edges that should be dead straight.

    This is not smoothing. Every vertex moves *along* its own run's fitted line
    and nowhere else, so nothing is rounded off and no detail is averaged away.
    The fit is orthogonal (total least squares) rather than y-on-x, because
    these edges run in every direction including vertical.

    Two things are never touched. A vertex carrying the corner flag is an
    anchor: it does not move, so a tip stays exactly where corner_curvature and
    sharpen_corners put it. And a polygon with no flagged corner at all is left
    alone entirely - that is a drawn circle, Help's dot or SizeAll's hole, and it
    has no straight edge to assert.

    The one way a pass that only moves points along a line can still invent a
    feature is at the seam between two of those lines, and the first version did
    exactly that: it walked runs greedily and stopped wherever the chord test
    failed, so one stretch of a slow curve got fitted to a line while its
    neighbour stayed curved, and the smooth bend between them came out a corner.
    Not theoretical - it grew Handwriting frame 6 a third tip, and the topology
    check caught it.

    So the work is done span by span, between one flagged corner and the next,
    and a span is cut only at its own Douglas-Peucker breakpoints - the vertices
    that depart furthest from their chord, which is where the edge bends. A span
    that needs more than STRAIGHT_MAX_SEG pieces is a curve and is left alone
    entirely.

    Then each piece has to look like the defect before it is treated as the
    defect: its vertices must straddle the fitted line, per STRAIGHT_BALANCE.
    An arc's vertices all sit on one side, and a line drawn across an arc puts
    outline where the artwork has none.

    The other half of the story is the corner itself. It never moves, but both
    its neighbours do, and the angle between them is what decides whether the
    corner is a point - so the whole span is put back if straightening it would
    carry either end across STRAIGHT_TIP_DEG.

    A greedy walk that stopped wherever the chord test failed was tried first
    and is wrong: it fitted one stretch of a slow curve to a line, left its
    neighbour curved, and the smooth bend between them came out a corner."""
    n = len(poly)
    if n < minlen + 2 or not any(flags):
        return poly
    tol = tol * eps
    pts = [(float(x), float(y)) for x, y in poly]
    # Start the walk on a corner so no span has to wrap the seam.
    s = flags.index(True)
    order = [(s + k) % n for k in range(n)]
    seq = [pts[i] for i in order]
    fl = [flags[i] for i in order]
    out = list(seq)
    seq.append(seq[0])                      # close the ring: index n is anchor 0
    fl.append(True)
    bounds = [k for k in range(n + 1) if fl[k]]
    for a, b in zip(bounds, bounds[1:]):
        if b - a + 1 < minlen:
            continue
        cuts = _dp_breaks(seq, a, b, tol)
        if len(cuts) - 1 > STRAIGHT_MAX_SEG:
            continue                        # a curve, not an edge with a bend
        span = list(range(a, min(b + 1, n)))
        was = [_angle_at(out, k, n) for k in (a, b)]
        keep = [out[k] for k in span]
        for u, v in zip(cuts, cuts[1:]):
            if v - u + 1 < minlen:
                continue
            if _balance(seq, u, v) < STRAIGHT_BALANCE:
                continue                    # an arc, and flattening one inflates
            cx, cy, ux, uy = _tls_line(seq[u:v + 1])
            for k in range(u + 1, min(v, n)):   # breakpoints stay put
                t = (seq[k][0] - cx) * ux + (seq[k][1] - cy) * uy
                out[k] = (cx + t * ux, cy + t * uy)
        now = [_angle_at(out, k, n) for k in (a, b)]
        if any((w > STRAIGHT_TIP_DEG) != (m > STRAIGHT_TIP_DEG)
               for w, m in zip(was, now)):
            for k, p in zip(span, keep):        # the corner would stop reading
                out[k] = p                      # as the corner it is
    back = [None] * n
    for k, idx in enumerate(order):
        back[idx] = out[k]
    return back


# Axes the author drew these cursors symmetric about. Kept here rather than
# imported because trace.py is upstream of tools/ and must run on its own.
#
# A subset of analyze.SYMMETRY, which measures two more. SizeNS and SizeWE are
# measured but not corrected: averaging their outlines works on the silhouette
# and lands both on the author's own asymmetry, but it costs the tip. SizeNS
# reads 0.037 -> 0.021 of tip_contrast at full pull and 0.030 at a third of it,
# and the loss is entirely in the shading - alpha, silhouette width across the
# bisector at 0.25/0.5/1.0/2.0 and the tip angle all hold, while the luma under
# the point goes 112.7 -> 119.3 against a ground of 128. The tip is where the
# master's dark core is, and moving the outline off it lightens the point
# without blunting it. That is a render-side coupling, not something the vector
# can settle.
SYMMETRY = {"Cross": ("lr", "ud", "t"), "SizeAll": ("lr", "ud", "t"),
            "IBeam": ("lr", "ud")}
SYM_PULL = 1.0           # share of the way to the symmetric mean a vertex moves
SYM_MAX = 1.0            # logical: a vertex further than this from its mirror
                         # image is not the same feature, and the whole cursor is
                         # left alone rather than half-averaged into a chimera.
                         #
                         # It has to be well clear of the asymmetry itself or it
                         # refuses exactly the cursors that need the work. The
                         # mismatch these outlines actually carry is a median of
                         # 0.07 to 0.50 and a maximum of 0.84, all of it the
                         # defect; features, meanwhile, sit whole logical units
                         # apart. At 0.6 this rejected Cross, SizeNS and SizeWE
                         # outright.


def _sym_ops(axes, cx=16.0, cy=16.0):
    """Close the axes into the group they generate, as (a,b,c,d,e,f) maps.

    The default centre is the frame's, logical 16.0, and that is measured rather
    than assumed. Sub-pixel search for the offset that minimises the author's own
    |alpha - mirrored alpha| on his 32px art puts every axis of every cursor in
    SYMMETRY between 15.40 and 15.60 in pixel coordinates, against a frame centre
    of 15.50 - within a tenth of a pixel, on ten independent readings.

    Deriving the centre from our own outline instead was tried and is wrong in a
    way worth recording: the polygon's asymmetry *is* the defect, so its centroid
    is displaced by roughly half of it, and the area centroid landed 0.13 to 0.34
    logical units off the author's axis. Symmetrising about that squares the
    shape up around the wrong line. The mean of the vertices is worse still -
    vertices crowd where the outline has detail, and it missed by up to 0.9."""
    gen = {"lr": (-1, 0, 2.0 * cx, 0, 1, 0.0),
           "ud": (1, 0, 0.0, 0, -1, 2.0 * cy),
           "t": (0, 1, cx - cy, 1, 0, cy - cx)}
    ops = {(1, 0, 0.0, 0, 1, 0.0)}
    frontier = [g for k, g in gen.items() if k in axes]
    ops.update(frontier)
    for _ in range(3):                          # D4 closes well inside three
        grown = set()
        for a in ops:
            for b in frontier:
                grown.add((a[0] * b[0] + a[1] * b[3], a[0] * b[1] + a[1] * b[4],
                           a[0] * b[2] + a[1] * b[5] + a[2],
                           a[3] * b[0] + a[4] * b[3], a[3] * b[1] + a[4] * b[4],
                           a[3] * b[2] + a[4] * b[5] + a[5]))
        if grown <= ops:
            break
        ops |= grown
    return sorted(ops)


def _apply(op, p):
    a, b, c, d, e, f = op
    return (a * p[0] + b * p[1] + c, d * p[0] + e * p[1] + f)


def _near_seg(p, q0, q1):
    """Closest point to p on the segment q0-q1."""
    dx, dy = q1[0] - q0[0], q1[1] - q0[1]
    n = dx * dx + dy * dy
    if n < 1e-12:
        return q0
    t = max(0.0, min(1.0, ((p[0] - q0[0]) * dx + (p[1] - q0[1]) * dy) / n))
    return (q0[0] + t * dx, q0[1] + t * dy)


def _image_of(p, corner, rings):
    """Where p lands on the nearest of rings.

    A flagged corner is matched to the nearest flagged corner, everything else
    to the nearest point on the outline. That distinction is the whole reason
    this is not just a nearest-point projection: SizeAll's four tips differ by
    11.5 degrees, and a tip pulled onto the flank of its mirror image instead of
    onto the mirror tip would average the spread into a smear rather than out of
    existence."""
    best, bd = None, float("inf")
    for pts, fl in rings:
        if corner:
            for q, f in zip(pts, fl):
                if not f:
                    continue
                d = (q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2
                if d < bd:
                    best, bd = q, d
        else:
            m = len(pts)
            for i in range(m):
                q = _near_seg(p, pts[i], pts[(i + 1) % m])
                d = (q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2
                if d < bd:
                    best, bd = q, d
    if best is None:
        return None, float("inf")
    return best, math.sqrt(bd)


def symmetrize(polys, flags, axes):
    """Average a cursor's outline with its own reflections.

    The asymmetry this removes is in the vector, not the render: measured with
    mirror_asym, ours runs about twice the author's own and grows with the size
    it is drawn at, because rasterising a lopsided outline more finely
    reproduces the lopsidedness rather than averaging it away. Cross reads 32.6
    against his 16.1 at 512, IBeam 42.5 against 21.6.

    Unlike straightening, this cannot invent a shape or bridge a curve: every
    vertex moves toward the mean of where it and its mirror images already are,
    so a feature the author drew stays, and only the disagreement between its
    copies goes. Corners are matched corner-to-corner rather than to the nearest
    point on the outline, so tips are averaged with tips.

    Refuses the whole cursor when any vertex sits further than SYM_MAX from its
    image. That means the reflection found no counterpart - a genuinely
    asymmetric detail, or an axis that does not hold - and averaging across it
    would build a shape the author never drew."""
    rings = [([(float(x), float(y)) for x, y in p], f)
             for p, f in zip(polys, flags)]
    ident = (1, 0, 0.0, 0, 1, 0.0)
    ops = [o for o in _sym_ops(axes) if o != ident]
    if not ops:
        return polys
    acc = [[[p[0], p[1], 1] for p in pts] for pts, _ in rings]
    for op in ops:
        moved = [([_apply(op, q) for q in pts], f) for pts, f in rings]
        for pi, (pts, fl) in enumerate(rings):
            for vi, (p, corner) in enumerate(zip(pts, fl)):
                img, d = _image_of(p, corner, moved)
                if img is None or d > SYM_MAX:
                    return polys                # not the same drawing, hands off
                acc[pi][vi][0] += img[0]
                acc[pi][vi][1] += img[1]
                acc[pi][vi][2] += 1
    out = []
    for pi, (pts, _) in enumerate(rings):
        ring = []
        for vi, p in enumerate(pts):
            sx, sy, k = acc[pi][vi]
            ring.append((p[0] + SYM_PULL * (sx / k - p[0]),
                         p[1] + SYM_PULL * (sy / k - p[1])))
        out.append(ring)
    return out


def trace_frame(key, eps=0.7, name=None):
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
            anchors = list(flags)
            for a in apexes:                # a reconstructed apex is an anchor too
                if 0 <= a < len(anchors):
                    anchors[a] = True
            poly = straighten_runs(poly, anchors, eps / 4.0)
            polys.append(poly)
            corner_flags.append(flags)
            apex_idx.append(apexes)

    # after every component is in hand: the axes of Cross and SizeAll carry one
    # arm onto another, so the reflection has to see the whole frame at once
    if name in SYMMETRY and polys:
        polys = symmetrize(polys, corner_flags, SYMMETRY[name])

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
        out[name] = {"frames": [trace_frame(f"cur__{name}__0", name=name)]}
        snap_corners(out[name]["frames"])
        fr = out[name]["frames"][0]
        print("traced", name, len(fr["polys"]), "components,",
              sum(len(p) for p in fr["polys"]), "pts")
    for name, n in ANI.items():
        out[name] = {"frames": [trace_frame(f"ani__{name}__{i}", name=name)
                                for i in range(n)]}
        snap_corners(out[name]["frames"])
        print("traced", name, "x", n)
    with open(os.path.join(HERE, "traced.json"), "w", encoding="utf-8") as f:
        json.dump(out, f)
    print("wrote traced.json")


if __name__ == "__main__":
    main()

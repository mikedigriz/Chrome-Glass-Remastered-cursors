"""Fitting one fold cross-section as a step between two facets.

The measurement itself, with no opinion about what a good number is. `analyze`
gates on it and `fold_tracker` prints it; both call the same code so that the
CLI a human reads and the gate a commit has to pass cannot drift apart.

Why a step and not a pit: the tracker `analyze` used before this took the
darkest interior pixel of each row and required a prominence around it. That
finds a dark line drawn on flat glass. The author did not draw one - his
cross-section is a transition between two facet levels, with a shallow notch
sitting on the transition, and both facets sloped. Measured with a pit-finder
his own frames read as no fold at all, at every size, on every wedge, which is
how "the reference scores no better than we do" got believed for a while.

Per station along the chord:

    sample along the chord's normal, in logical units
    exclude the rim by distance to the outline, never by alpha
    find the steepest fall - a prior for where the transition is
    fit each facet on its own, robustly, with the transition zone held out
    take the two slopes off, which leaves the step intact and the facets level
    fit the step on what remains, then read the notch against it

reported per station as:

    k_lo, k_hi     facet slopes, levels per logical unit (diagnostic)
    bend_lo/_hi    residual of each facet's straight line - how domed it is
    c              transition centre, signed from the structural chord
    s              transition width; a tanh spans about 2.2*s at 10..90 percent
    b_lo, b_hi     facet levels extrapolated to the transition
    d, w           notch depth below the fitted step, and its width
    rms            what the model failed to explain

`s` carries a resolution verdict rather than a bare number: under one hardware
pixel of transition there is nothing to measure, and the lowest rung of the
search grid is then a floor, not a reading.

`bend` is a confidence figure, not a defect: small means the straight facet is a
fair description and the slope can be trusted, large means it is not. On the
author it runs 1.3 to 3.1 everywhere except Wait, whose left facet is genuinely
curved and reads 11.6.

What this cannot see, and it matters: these numbers describe the shape of one
cross-section and nothing else. They say nothing about whether the features
either side of the fold survived. A change that flattens the lit inner facet
into the fold improves width, notch and residual at once, because a flat field
has nothing left to disagree with itself - which is exactly what happened on
2026-08-21 to a render whose inner tip had visibly been destroyed (DEAD_ENDS.md,
"Зонный temper"). `inner_tip` below is the companion for that blind spot, and
the two are separate acceptance classes on purpose.

Alpha is used only as a floor for "there is a signal here at all". Admission is
geometric. Any station count of zero is a fault in this file until proven
otherwise.
"""
import numpy as np

from cgr import hybrid as H
from cgr import vectorlib as V

RIM_INSET = 0.75        # logical units of glass between the search and the rim
REACH = 6.0             # how far along the normal the section is sampled
STEP = 0.05             # sampling pitch along the normal, logical units
ALPHA_FLOOR = 24.0      # 8-bit alpha under which there is no signal to read
LAMBDA = 1.5            # levels of penalty per logical unit away from the chord
S_GRID = (0.02, 0.03, 0.05, 0.08, 0.11, 0.15, 0.25, 0.4, 0.6, 0.9, 1.3, 1.8, 2.5)
MIN_SIDE = 6            # samples each side of c a fit needs
GUARD = 1.0             # logical units around the transition kept out of the
                        # facet fits - the author's transition is that wide
SMOOTH = 0.15           # logical units the profile is averaged over before its
                        # gradient is read, so single-sample noise cannot win
C_WINDOW = 2.0          # how far the fitted centre may sit from the prior

# Stations, as a fraction along the chord. Fixed here rather than passed in, so
# that a curvature read at one size is the same set of points as at another.
T_LO, T_HI = 0.08, 0.92
STATIONS = 24


def _robust_line(n, y, pivot):
    """a, k of y = a + k*(n - pivot), with outliers thrown out twice.

    Plain least squares is not usable here: the notch is a large one-sided
    excursion and the samples nearest the rim carry spikes of 20-40 levels, and
    either would set the slope of a facet that is otherwise straight.
    """
    x = n - pivot
    keep = np.ones(len(x), bool)
    k = a = 0.0
    for _ in range(3):
        if keep.sum() < 4:
            break
        k, a = np.polyfit(x[keep], y[keep], 1)
        r = y - (a + k * x)
        med = float(np.median(r[keep]))
        mad = float(np.median(np.abs(r[keep] - med)))
        if mad < 1e-9:
            break
        new = np.abs(r - med) < 3.0 * 1.4826 * mad
        if new.sum() < 4 or (new == keep).all():
            break
        keep = new
    r = y - (a + k * (n - pivot))
    return float(a), float(k), float(np.sqrt((r[keep] ** 2).mean()))


def _smoothed(y):
    k = max(3, int(round(SMOOTH / STEP)) | 1)
    return np.convolve(np.pad(y, k // 2, mode="edge"), np.ones(k) / k, "valid")


def _steepest(n, y):
    """Where the profile falls fastest - the prior for the transition.

    Searched only where a transition could still be fitted: GUARD plus MIN_SIDE
    samples must fit between it and either end. Without that bound the winner is
    often the spike two samples inside the rim, and then one facet comes out
    empty and the station is lost - which is how the first version of this
    dropped Arrow from 20 stations to 8.
    """
    g = np.gradient(_smoothed(y), n)
    room = GUARD + MIN_SIDE * STEP
    inner = (n >= n.min() + room) & (n <= n.max() - room)
    if inner.sum() < 3:
        return None, 0.0
    i = int(np.argmax(np.where(inner, np.abs(g), 0.0)))
    return float(n[i]), float(g[i])


def _solve(u, v, y, w):
    """Least squares over the two columns `u`, `v`, one fit per candidate row.

    Written out as the two-by-two normal equations rather than a least-squares
    call per candidate: the basis has two columns, so the solve is a
    determinant, and doing every candidate as one array is what makes this
    affordable inside the gate - eighty times faster than the loop it replaces,
    and the same answer to twelve digits.
    """
    uu, vv, uv = (u * u), (v * v), (u * v)
    uy, vy = u * y, v * y
    if w is not None:
        uu, vv, uv, uy, vy = uu * w, vv * w, uv * w, uy * w, vy * w
    Suu, Svv, Suv = uu.sum(1), vv.sum(1), uv.sum(1)
    Suy, Svy = uy.sum(1), vy.sum(1)
    det = Suu * Svv - Suv * Suv
    ok = np.abs(det) > 1e-12
    det = np.where(ok, det, 1.0)
    a = (Svv * Suy - Suv * Svy) / det
    b = (Suu * Svy - Suv * Suy) / det
    res = y[None, :] - (a[:, None] * u + b[:, None] * v)
    return a, b, res, ok


def section(name, idx, size, get, t, inset=RIM_INSET):
    """One cross-section at fraction `t` along the chord, or None."""
    ch = H._fold_chord(name, idx)
    if ch is None:
        return None
    (x0, y0), (x1, y1) = ch
    px, py = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
    dx, dy = x1 - x0, y1 - y0
    ln = float(np.hypot(dx, dy))
    if ln < 1e-6:
        return None
    nx, ny = -dy / ln, dx / ln              # unit normal, logical units
    L = size / V.LOGICAL
    n = np.arange(-REACH, REACH + STEP, STEP)
    sx, sy = (px + n * nx) * L - 0.5, (py + n * ny) * L - 0.5
    a = get(name, idx, size)
    lum = H._sample1(np.ascontiguousarray(a[..., :3].mean(-1)), sx, sy)
    alpha = H._sample1(np.ascontiguousarray(a[..., 3].astype(np.float64)), sx, sy)
    # already in logical units - analyze compares it against _FOLD_INSET raw
    dist = H._sample1(H._edge_distance_at(name, idx, size), sx, sy)
    ok = (dist >= inset) & (alpha >= ALPHA_FLOOR) & np.isfinite(lum)
    if ok.sum() < 2 * MIN_SIDE + 3:
        return None
    # one run only: a normal that leaves and re-enters the shape must not be
    # stitched into a single section
    idxs = np.nonzero(ok)[0]
    runs = np.split(idxs, np.nonzero(np.diff(idxs) > 1)[0] + 1)
    run = max(runs, key=len)
    if len(run) < 2 * MIN_SIDE + 3:
        return None
    return n[run], lum[run]


def chord_length(name, idx):
    """The chord's own length in logical units, or None."""
    ch = H._fold_chord(name, idx)
    if ch is None:
        return None
    (x0, y0), (x1, y1) = ch
    return float(np.hypot(x1 - x0, y1 - y0))


def measure(name, idx, size, get, t):
    """Fit one station, or None if the section cannot carry a fit."""
    got = section(name, idx, size, get, t)
    if got is None:
        return None
    n, raw = got
    c0, _grad = _steepest(n, raw)
    if c0 is None:
        return None
    left, right = n < c0 - GUARD, n > c0 + GUARD
    if left.sum() < MIN_SIDE or right.sum() < MIN_SIDE:
        return None
    _aL, k_lo, bend_lo = _robust_line(n[left], raw[left], c0)
    _aR, k_hi, bend_hi = _robust_line(n[right], raw[right], c0)
    # continuous at c0, so the step itself survives detrending untouched
    y = raw - np.where(n < c0, k_lo * (n - c0), k_hi * (n - c0))

    inner = n[MIN_SIDE:-MIN_SIDE]
    cs = inner[np.abs(inner - c0) <= C_WINDOW]
    if len(cs) == 0:
        return None
    best = None
    for s in S_GRID:
        phi = 0.5 * (1.0 + np.tanh((n[None, :] - cs[:, None]) / s))
        u = 1.0 - phi
        a, b, res, ok = _solve(u, phi, y, None)
        # two passes: the notch is a big one-sided residual and would drag the
        # transition onto itself if it were left in the fit
        keep = res > -2.0 * np.maximum(res.std(1, keepdims=True), 1e-6)
        enough = keep.sum(1) > 2 * MIN_SIDE
        if enough.any():
            a2, b2, res2, ok2 = _solve(u[enough], phi[enough], y,
                                       keep[enough].astype(float))
            a[enough] = np.where(ok2, a2, a[enough])
            b[enough] = np.where(ok2, b2, b[enough])
            res[enough] = np.where(ok2[:, None], res2, res[enough])
        score = np.sqrt((res ** 2).mean(1)) + LAMBDA * np.abs(cs)
        score = np.where(ok, score, np.inf)
        i = int(np.argmin(score))
        if np.isfinite(score[i]) and (best is None or score[i] < best[0]):
            best = (float(score[i]), float(cs[i]), s,
                    (float(a[i]), float(b[i])), res[i].copy())
    if best is None:
        return None
    _score, c, s, (b_lo, b_hi), res = best

    near = np.abs(n - c) <= 1.5
    d = float(-res[near].min()) if near.any() else 0.0
    w = float("nan")
    if d > 0:
        below = near & (res <= -0.5 * d)
        w = float(below.sum() * STEP) if below.any() else float("nan")
    # A tanh of width s spans about 2.2*s between its 10 and 90 percent points.
    # Under one hardware pixel of that there is nothing left to measure, and the
    # grid's lowest rung is then a floor, not a reading. Say so instead of
    # quietly storing the number.
    return dict(t=float(t), c=float(c), s=float(s), c0=c0,
                s_resolved=bool(2.2 * s > V.LOGICAL / float(size)),
                b_lo=float(b_lo), b_hi=float(b_hi), step=float(b_hi - b_lo),
                k_lo=k_lo, k_hi=k_hi, bend_lo=bend_lo, bend_hi=bend_hi,
                d=d, w=w, rms=float(np.sqrt((res ** 2).mean())),
                n=n, y=y, raw=raw, res=res)


INNER_T = (0.10, 0.45)  # the stretch of chord the inner tip lives on
INNER_INSET = 0.15      # the separator sits within a unit of the rim, so the
                        # section has to reach nearly to it - RIM_INSET cuts it
INNER_DIP = 5.0         # levels the separator must fall below the rim's own
                        # brightness before it counts as a separator
INNER_RIDGE = 12.0      # levels the inner facet must rise above the separator
INNER_STATIONS = 12


def inner_tip(name, idx, size, get, count=INNER_STATIONS):
    """Is the inner tip still a separate thing, or has it washed into the fold?

    This is the companion the fold profile needs and cannot be. `s`, `d` and
    `rms` describe the shape of one cross-section; they say nothing about
    whether the lit inner facet still exists as its own feature. On 2026-08-21 a
    render whose inner tip had visibly been destroyed scored better on all three
    at once, because a flat field has nothing left to disagree with itself
    (DEAD_ENDS.md, "Зонный temper").

    What is looked for is a topology, not a contrast: walking inward from the
    rim, the profile must fall into a separator and then climb onto the inner
    facet's own ridge. Two turning points, in that order. A wash has neither -
    it leaves one monotone slope from the rim to the fold, however bright.

    Not a fidelity check: the author's own frame is 32px art, upscaled, and
    carries no such structure to compare against. This measures that our render
    has kept a feature its owner asked for, which is a different question.
    """
    out = []
    for t in np.linspace(INNER_T[0], INNER_T[1], count):
        got = section(name, idx, size, get, t, inset=INNER_INSET)
        if got is None:
            continue
        n, y = got
        sm = _smoothed(y)
        # Only the stretch between the rim and the fold. Taking the first
        # turning point instead of the strongest one was the first version's
        # mistake: on a plateau the ripple supplies a local minimum two samples
        # in, and UpArrow then scored 4 stations of 12 on a render whose inner
        # tip is plainly there.
        c0, _g = _steepest(n, y)
        lim = int(np.searchsorted(n, c0)) if c0 is not None else int(0.6 * len(n))
        lim = max(lim, 5)
        hi = int(np.argmax(sm[:lim]))               # the inner facet's ridge
        # The separator is a local minimum, not the darkest sample before the
        # ridge: on Arrow the section begins at the rim already darker than the
        # separator (159 against 184 at t=0.20), and the plain argmin lands on
        # the first sample and reports no structure at all. Prominence, so a
        # ripple on a plateau cannot pass for a drawn line either.
        d = np.diff(sm[:hi + 1])
        lo, dip = 0, 0.0
        for i in range(len(d) - 1):
            if d[i] < 0 <= d[i + 1]:
                j = i + 1
                prom = min(float(sm[:j].max()), float(sm[j:hi + 1].max())) - sm[j]
                if prom > dip:
                    lo, dip = j, float(prom)
        ridge = float(sm[hi] - sm[lo]) if lo else 0.0
        out.append(dict(t=float(t), dip=dip, ridge=ridge, n_lo=float(n[lo]),
                        n_hi=float(n[hi]),
                        ok=bool(lo > 0 and hi > lo and dip >= INNER_DIP
                                and ridge >= INNER_RIDGE)))
    return out


def track(name, idx, size, get, count=STATIONS):
    """Every station that resolves, from t=0.08 to t=0.92 along the chord."""
    out = []
    for t in np.linspace(T_LO, T_HI, count):
        m = measure(name, idx, size, get, t)
        if m is not None:
            out.append(m)
    return out


def track_slots(name, idx, size, get, count=STATIONS):
    """The same, but keeping the empty slots, so a curvature can tell a
    neighbour from a station three places away."""
    return [measure(name, idx, size, get, t)
            for t in np.linspace(T_LO, T_HI, count)]

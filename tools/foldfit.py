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

`s` carries two verdicts rather than a bare number. Under one hardware pixel of
transition there is nothing to resolve. Independently, a flat profile over
materially different widths contains no identified width even at high
resolution. The first state is `s_resolved=False`, the second
`s_identified=False`; neither is allowed to masquerade as a good narrow fit.

Every width candidate is fitted on the same samples with one scale estimated
before the search and continuous soft-L1 influence. The previous candidate-
specific hard outlier mask could make one pixel disappear for one width and
reappear for its neighbour, producing a discontinuous ranking unrelated to the
picture. See docs/dev/NEXT.md 72 for the calibration and external basis.

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
import functools

import numpy as np
from PIL import Image

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
SOFT_L1_FLOOR = 1.0     # luma levels. The robust scale is estimated once from
                        # the two facets; this is only its quantisation floor.
SOFT_L1_PASSES = 3      # IRLS passes after the ordinary least-squares seed
PROFILE_SIGMA = 1.0     # one standard error of the per-sample robust loss
PROFILE_SPAN = 2.0      # a wider near-optimal interval cannot identify `s`

# Stations, as a fraction along the chord. Fixed here rather than passed in, so
# that a curvature read at one size is the same set of points as at another.
T_LO, T_HI = 0.08, 0.92
STATIONS = 24

# The shape the author draws on the transition, measured 2026-09-06 from his
# own art at 128, 256 and 512 (NEXT.md 81, 82).
#
# Not a notch: his residual against a fitted tanh step is a dipole - brighter
# than the step just past its centre, darker again around +1.15, with a mild
# dark shoulder to the left. One shared shape, rank 1. Rank is not taste: a
# second component only reduces a residual already under the fit's own
# robust_scale, and a per-station table would store 70-90% noise, since one
# fixed shape explains 0.10..0.30 of a station's residual energy while a
# split-half says the shape itself is real. Stable across the three rungs
# (r 0.88..1.00), and the pooled shape beats each cursor's own on held-out
# stations for five of seven.
#
# Why the instrument carries it: the positive lobe sits on the transition and
# competes with the tanh for the width, so a picture that has the shape the
# author drew reads as less width-identifiable than one that does not. That is
# a property of a two-column model, not of the drawing. `A` is therefore a
# nuisance parameter here - minimised out at every (c, s) exactly as the facet
# levels already are - and `s` is judged on what is left. Measured on his own
# corpus this is neutral to better: 2391 stations, unident 0.349 -> 0.332.
#
# Unit norm, so `A` carries the levels. Sampled every DIPOLE_PITCH from
# DIPOLE_X0.
DIPOLE_X0 = -2.45
DIPOLE_PITCH = 0.05
DIPOLE = np.array([
    +0.01075, +0.00302, -0.00729, -0.01905, -0.03002, -0.03921, -0.04653, -0.05544,
    -0.06151, -0.06904, -0.07947, -0.08922, -0.09631, -0.09818, -0.09822, -0.09696,
    -0.09594, -0.09435, -0.09030, -0.08507, -0.07898, -0.07276, -0.06489, -0.05534,
    -0.04409, -0.03565, -0.02739, -0.01690, -0.00621, +0.00275, +0.00984, +0.01700,
    +0.02270, +0.02685, +0.03075, +0.03330, +0.03365, +0.03734, +0.04209, +0.04569,
    +0.04624, +0.04813, +0.05311, +0.06375, +0.07866, +0.09532, +0.11422, +0.13316,
    +0.15208, +0.17218, +0.18765, +0.19822, +0.20196, +0.19961, +0.19118, +0.17799,
    +0.15816, +0.13208, +0.10335, +0.07311, +0.03793, +0.00318, -0.03093, -0.05865,
    -0.08473, -0.11120, -0.13147, -0.14843, -0.16496, -0.17725, -0.18493, -0.18985,
    -0.19057, -0.18659, -0.18029, -0.17168, -0.15906, -0.14634, -0.13435, -0.12060,
    -0.10770, -0.09524, -0.08327, -0.06842, -0.05083, -0.03367, -0.01686, -0.00338,
    +0.00761, +0.01736, +0.02613, +0.03415, +0.04191, +0.04621, +0.05065, +0.05512,
    +0.06002, +0.06509, +0.07026, +0.07434,
])
DIPOLE_SPAN = 0.5       # logical units of section a station needs beyond the
                        # template before its residual may be projected on it.
                        # At the very edge the residual ramps, and the ramp
                        # flips the projection's sign


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


def _mad_scale(r):
    """One robust luma scale, shared by every centre/width candidate.

    The old second pass recomputed a hard inlier mask for each candidate. A
    sample could therefore disappear for one width and reappear for the next,
    making an otherwise continuous profile jump between adjacent `S_GRID`
    ranks. Here the data set never changes. The scale is measured before the
    width search, from the two facet residuals, so it cannot favour a candidate.
    """
    r = np.asarray(r, dtype=np.float64)
    if not len(r):
        return SOFT_L1_FLOOR
    med = float(np.median(r))
    mad = float(np.median(np.abs(r - med)))
    return max(SOFT_L1_FLOOR, 1.4826 * mad)


def _soft_l1_fit(u, v, y, scale):
    """Fit the two facet levels with continuous soft-L1 influence.

    This is iteratively reweighted least squares for
    ``rho(z) = 2 * (sqrt(1 + z) - 1)``. Every sample keeps a positive weight;
    unlike the former ``res > cutoff`` pass, no candidate owns a different
    set of pixels. The returned score has luma units and approaches RMS for
    residuals small compared with ``scale``.
    """
    a, b, res, ok = _solve(u, v, y, None)
    for _ in range(SOFT_L1_PASSES):
        z = res / scale
        weights = 1.0 / np.sqrt(1.0 + z * z)
        a2, b2, res2, ok2 = _solve(u, v, y, weights)
        use = ok & ok2
        a = np.where(use, a2, a)
        b = np.where(use, b2, b)
        res = np.where(use[:, None], res2, res)
        ok &= ok2
    z2 = (res / scale) ** 2
    rho = 2.0 * (np.sqrt(1.0 + z2) - 1.0)
    score = scale * np.sqrt(rho.mean(1))
    return a, b, res, ok, score


def _profile_verdict(profile, scale, samples):
    """Return the best width and its near-optimal profile interval.

    Width is a profiled nonlinear parameter: for each `s`, centre and facet
    levels have already been minimised out. A flat profile does not contain a
    defensible width. We call all grid rungs within one estimated standard
    error of the best score near-optimal; if that interval spans more than a
    factor of two, `s` is explicitly unidentified instead of inheriting the
    arbitrary rank that won by a few ten-thousandths of a luma level.
    """
    scores = np.array([row[0] for row in profile], dtype=np.float64)
    j = int(np.argmin(scores))
    tol = PROFILE_SIGMA * scale / np.sqrt(max(int(samples), 1))
    near = scores <= scores[j] + tol
    widths = np.array([row[1] for row in profile], dtype=np.float64)
    lo, hi = float(widths[near].min()), float(widths[near].max())
    return j, lo, hi, float(tol), bool(hi / lo <= PROFILE_SPAN)


def _solve3(u, v, w, y, weights):
    """Least squares over three columns, one fit per candidate row.

    `_solve` one column wider. The 3x3 normal equations are solved as a batch
    so that adding the dipole keeps every candidate centre a single array
    operation, the property that makes the width search affordable at all.
    """
    cols = (u, v, w)
    G = np.empty((3, 3, u.shape[0]))
    for i in range(3):
        for j in range(i, 3):
            p = cols[i] * cols[j]
            G[i, j] = G[j, i] = (p * weights).sum(1) if weights is not None                 else p.sum(1)
    b = np.empty((3, u.shape[0]))
    for i in range(3):
        p = cols[i] * y
        b[i] = (p * weights).sum(1) if weights is not None else p.sum(1)
    M = np.moveaxis(G, (0, 1), (-2, -1))
    det = np.linalg.det(M)
    ok = np.abs(det) > 1e-12
    M = np.where(ok[:, None, None], M, np.eye(3))
    # numpy reads a 2-D right-hand side as one matrix, not a stack of vectors
    sol = np.linalg.solve(M, np.moveaxis(b, 0, -1)[..., None])[..., 0]
    res = y[None, :] - (sol[:, 0:1] * u + sol[:, 1:2] * v + sol[:, 2:3] * w)
    return sol[:, 0], sol[:, 1], sol[:, 2], res, ok


def _soft_l1_joint(u, v, w, y, scale):
    """`_soft_l1_fit` with the dipole as a third column and `A >= 0`.

    One inequality on one coefficient: where the unconstrained optimum wants
    A < 0 the constrained optimum sits at A = 0, so those rows keep the
    two-column fit. Exact for least squares, and exact per iteration for the
    reweighted problem - the standing the two-column IRLS already has.

    Non-negative because the shape has a direction. A free sign would let the
    column install the author's dipole upside down wherever that happened to
    fit better, which is not a reading of anything he drew.
    """
    a2, b2, res2, ok2 = _solve(u, v, y, None)
    a3, b3, A3, res3, ok3 = _solve3(u, v, w, y, None)
    for _ in range(SOFT_L1_PASSES):
        z = res2 / scale
        n2, m2, r2, k2 = _solve(u, v, y, 1.0 / np.sqrt(1.0 + z * z))
        use = ok2 & k2
        a2 = np.where(use, n2, a2)
        b2 = np.where(use, m2, b2)
        res2 = np.where(use[:, None], r2, res2)
        ok2 = use
        z = res3 / scale
        n3, m3, q3, r3, k3 = _solve3(u, v, w, y, 1.0 / np.sqrt(1.0 + z * z))
        use = ok3 & k3
        a3 = np.where(use, n3, a3)
        b3 = np.where(use, m3, b3)
        A3 = np.where(use, q3, A3)
        res3 = np.where(use[:, None], r3, res3)
        ok3 = use
    take3 = ok3 & (A3 > 0.0)
    a = np.where(take3, a3, a2)
    b = np.where(take3, b3, b2)
    A = np.where(take3, A3, 0.0)
    res = np.where(take3[:, None], res3, res2)
    ok = np.where(take3, ok3, ok2)
    rho = 2.0 * (np.sqrt(1.0 + (res / scale) ** 2) - 1.0)
    return a, b, A, res, ok, scale * np.sqrt(rho.mean(1))


def _author_at(name, idx, size):
    """The author's own frame at `size`. His art, never our render."""
    im = H.original(name, idx)
    if size != im.size[0]:
        im = im.resize((size, size), Image.LANCZOS)
    return np.asarray(im, dtype=np.float64)


def _dipole_of(m):
    """A station's residual projected on the shared shape, or None.

    None where the section does not clear the template's span with
    `DIPOLE_SPAN` to spare: at the very edge the residual ramps, and the ramp
    decides the sign of the projection rather than the drawing does.
    """
    x0 = DIPOLE_X0
    x1 = x0 + DIPOLE_PITCH * (len(DIPOLE) - 1)
    if x0 < m["n"].min() - m["c"] + DIPOLE_SPAN             or x1 > m["n"].max() - m["c"] - DIPOLE_SPAN:
        return None
    grid = np.arange(len(DIPOLE)) * DIPOLE_PITCH + x0 + m["c"]
    return np.interp(grid, m["n"], m["res"])


@functools.lru_cache(maxsize=None)
def dipole_eligible(name):
    """Does this cursor's fold carry the shared dipole at all?

    Decided on his art alone and by sign only, so there is nothing to tune and
    no list of names to keep in step with the drawing. A cursor whose own mean
    residual leans against the shared shape would have it fitted upside down;
    it gets no third column, and reads exactly as it did before this existed.

    Per frame rather than pooled, because a cursor that cannot make up its mind
    frame to frame is the one that does not belong: AppStarting votes 12 frames
    for and 15 against, Help none for, while every other cursor is unanimous.
    Measured with the two-column fit, so this cannot recurse.
    """
    votes = 0
    for idx in range(len(H.BY_NAME[name]["frames"])):
        rows = []
        for t in np.linspace(T_LO, T_HI, STATIONS):
            m = measure(name, idx, DIPOLE_SIZE, _author_at, t, joint=False)
            if m is None:
                continue
            g = _dipole_of(m)
            if g is not None:
                rows.append(g)
        if len(rows) < 6:
            continue
        votes += 1 if float(np.corrcoef(np.mean(rows, axis=0),
                                        DIPOLE)[0, 1]) > 0 else -1
    return votes > 0


DIPOLE_SIZE = 256       # the rung eligibility is decided on. The sign of the
                        # correlation is the same at 128 and 512 for every
                        # cursor, so one rung is read rather than three


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


def measure(name, idx, size, get, t, joint=None):
    """Fit one station, or None if the section cannot carry a fit.

    `joint` overrides the eligibility decision, and exists so that the decision
    itself can be taken with the two-column fit without recursing. Callers
    leave it alone.
    """
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
    aL, k_lo, bend_lo = _robust_line(n[left], raw[left], c0)
    aR, k_hi, bend_hi = _robust_line(n[right], raw[right], c0)
    # continuous at c0, so the step itself survives detrending untouched
    y = raw - np.where(n < c0, k_lo * (n - c0), k_hi * (n - c0))

    # One noise/model-mismatch scale for the whole width profile. It is read
    # from the held-out facets, before any candidate transition is built.
    facet_res = np.r_[raw[left] - (aL + k_lo * (n[left] - c0)),
                      raw[right] - (aR + k_hi * (n[right] - c0))]
    robust_scale = _mad_scale(facet_res)

    inner = n[MIN_SIDE:-MIN_SIDE]
    cs = inner[np.abs(inner - c0) <= C_WINDOW]
    if len(cs) == 0:
        return None
    use_dipole = dipole_eligible(name) if joint is None else joint
    profile = []
    for s in S_GRID:
        phi = 0.5 * (1.0 + np.tanh((n[None, :] - cs[:, None]) / s))
        u = 1.0 - phi
        if use_dipole:
            # anchored on the candidate centre - the frame the shape was
            # measured in. Neither its shift nor its width is fitted.
            col = np.interp((n[None, :] - cs[:, None]).ravel(),
                            np.arange(len(DIPOLE)) * DIPOLE_PITCH + DIPOLE_X0,
                            DIPOLE, left=0.0, right=0.0).reshape(phi.shape)
            a, b, A, res, ok, robust_score = _soft_l1_joint(u, phi, col, y,
                                                            robust_scale)
        else:
            a, b, res, ok, robust_score = _soft_l1_fit(u, phi, y, robust_scale)
            A = np.zeros(len(cs))
        score = robust_score + LAMBDA * np.abs(cs)
        score = np.where(ok, score, np.inf)
        i = int(np.argmin(score))
        if np.isfinite(score[i]):
            profile.append((float(score[i]), float(s), float(cs[i]),
                            float(a[i]), float(b[i]), res[i].copy(),
                            float(A[i])))
    if not profile:
        return None
    j, s_lo, s_hi, profile_tol, s_identified = _profile_verdict(
        profile, robust_scale, len(n))
    score, s, c, b_lo, b_hi, joint_res, A = profile[j]

    # `d`, `w` and `rms` are read against the STEP ALONE, never against the
    # joint residual. The dipole is in the model to keep it out of the width
    # verdict; letting it also absorb the notch would silently redefine
    # `fold_notch` and `fold_rms`, and every number recorded against those two
    # would stop being comparable.
    phi = 0.5 * (1.0 + np.tanh((n - c) / s))
    res = y - (b_lo * (1.0 - phi) + b_hi * phi)
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
    return dict(t=float(t), c=float(c), s=float(s), c0=c0, A=float(A),
                joint_res=joint_res,
                joint_rms=float(np.sqrt((joint_res ** 2).mean())),
                s_identified=s_identified, s_lo=s_lo, s_hi=s_hi,
                profile_tol=profile_tol, profile_score=score,
                robust_scale=robust_scale,
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

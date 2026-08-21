#!/usr/bin/env python3
# Experimental measurement tool.
# Not yet part of the quality gate.
"""Measures the fold as a step between two facets, not as a pit in a flat field.

Written 2026-08-21 because the tracker in analyze.py cannot read the author at
all. That one takes the darkest interior pixel per row inside +-_JAG_BAND of the
chord, and admits a row by counting pixels over `_SOLID_FRAC * al.max()`. The
author's peak alpha is his opaque outline, so on Arrow at 256 the test throws
away 232 rows of 256 before anything is measured, and the resulting silence was
being read as "the reference scores no better than we do". It does not: it was
never reached. What the sections actually show is not a pit either - it is a
transition between two facet levels, with a dark notch sitting on the
transition, and on the author both facets are sloped and the left one is domed.

So, per station along the chord:

    sample along the chord's normal, in logical units
    exclude the rim by distance to the outline, never by alpha
    find the steepest fall - a prior for where the transition is
    fit each facet on its own, robustly, with the transition zone held out
    take the two slopes off, which leaves the step intact and the facets level
    fit the step on what remains, then read the notch against it

reported as:

    k_lo, k_hi     facet slopes, levels per logical unit (diagnostic)
    bend_lo/_hi    residual of each facet's straight line - how domed it is
    c              transition centre, signed from the structural chord
    s              transition width; a tanh spans about 2.2*s at 10..90 percent
    b_lo, b_hi     facet levels extrapolated to the transition
    d, w           notch depth below the fitted step, and its width
    rms            what the model failed to explain

`s` gets a resolution verdict rather than a bare number: under one hardware
pixel of transition there is nothing to measure, and the lowest rung of the
search grid is a floor, not a reading. The author holds s = 0.60 LU at 128, 256
and 512 alike; our render's s follows the pixel pitch down at every doubling,
which is the quantitative form of "we draw the fold as a discontinuity".

`bend` is a confidence figure, not a defect: small means the straight facet is a
fair description and the slope can be trusted, large means it is not. On the
author it runs 1.3 to 3.1 everywhere except Wait, where the left facet is
genuinely curved and reads 11.6 - so Wait's slopes are a control, not a source
of parameters, and a quadratic facet model would be a measuring option to add
later rather than a rewrite of the base fit.

Alpha is used only as a floor for "there is a signal here at all". Admission is
geometric. Any station count of zero is a fault in this file until proven
otherwise.

Usage:
    python tools/fold_tracker.py --cursor Arrow --size 256
    python tools/fold_tracker.py --cursor Arrow --size 256 --debug
    python tools/fold_tracker.py --sizes 128,256,512      # is s a real width?
"""
import argparse
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))

import analyze as A
from cgr import hybrid as H
from cgr import vectorlib as V

# The five cursors whose silhouette carries a fold along a chord. Three of them
# are independent references: Arrow, Arrow_Down, UpArrow. Wait is a control, its
# facets being curved (see `bend` above), and Hand is not a sample at all at
# frame 0 - the author's ani__Hand__0 is his cur__Arrow__0 pixel for pixel, so
# counting it makes one bitmap look like two cursors agreeing. Read Hand at a
# frame where the light has actually moved, or leave it for checking the
# animation once the static wedges are explained.
WEDGES = ("Arrow", "Arrow_Down", "Hand", "UpArrow", "Wait")
INDEPENDENT = ("Arrow", "Arrow_Down", "UpArrow")

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


def _fit_step(n, y, c, s):
    """Least squares b_lo, b_hi for a fixed transition, and the residual."""
    phi = 0.5 * (1.0 + np.tanh((n - c) / s))
    M = np.stack([1.0 - phi, phi], 1)
    sol, *_ = np.linalg.lstsq(M, y, rcond=None)
    return sol, y - M @ sol


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


def _steepest(n, y):
    """Where the profile falls fastest - the prior for the transition.

    Searched only where a transition could still be fitted: GUARD plus MIN_SIDE
    samples must fit between it and either end. Without that bound the winner is
    often the spike two samples inside the rim, and then one facet comes out
    empty and the station is lost - which is how the first version of this
    dropped Arrow from 20 stations to 8.
    """
    k = max(3, int(round(SMOOTH / STEP)) | 1)
    pad = k // 2
    sm = np.convolve(np.pad(y, pad, mode="edge"), np.ones(k) / k, mode="valid")
    g = np.gradient(sm, n)
    room = GUARD + MIN_SIDE * STEP
    inner = (n >= n.min() + room) & (n <= n.max() - room)
    if inner.sum() < 3:
        return None, 0.0
    i = int(np.argmax(np.where(inner, np.abs(g), 0.0)))
    return float(n[i]), float(g[i])


def section(name, idx, size, get, t):
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
    ok = (dist >= RIM_INSET) & (alpha >= ALPHA_FLOOR) & np.isfinite(lum)
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

    best = None
    inner = n[MIN_SIDE:-MIN_SIDE]
    for s in S_GRID:
        for c in inner[np.abs(inner - c0) <= C_WINDOW]:
            sol, res = _fit_step(n, y, c, s)
            # two passes: the notch is a big one-sided residual and would drag
            # the transition onto itself if it were left in the fit
            keep = res > -2.0 * max(res.std(), 1e-6)
            if keep.sum() > 2 * MIN_SIDE:
                sol, _ = _fit_step(n[keep], y[keep], c, s)
                phi = 0.5 * (1 + np.tanh((n - c) / s))
                res = y - np.stack([1.0 - phi, phi], 1) @ sol
            score = float(np.sqrt((res ** 2).mean())) + LAMBDA * abs(c)
            if best is None or score < best[0]:
                best = (score, c, s, sol, res)
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


def track(name, idx, size, get, count=24):
    """Every station that resolves, from t=0.08 to t=0.92 along the chord."""
    out = []
    for t in np.linspace(0.08, 0.92, count):
        m = measure(name, idx, size, get, t)
        if m is not None:
            out.append(m)
    return out


def _summary(tr, count):
    a = {k: np.array([m[k] for m in tr]) for k in
         ("c", "s", "b_lo", "b_hi", "step", "d", "rms",
          "k_lo", "k_hi", "bend_lo", "bend_hi")}
    unresolved = sum(1 for m in tr if not m["s_resolved"])
    return dict(stations="%d/%d" % (len(tr), count), unresolved=unresolved,
                **{k: float(np.median(v)) for k, v in a.items()},
                c_p10=float(np.percentile(a["c"], 10)),
                c_p90=float(np.percentile(a["c"], 90)),
                s_p10=float(np.percentile(a["s"], 10)),
                s_p90=float(np.percentile(a["s"], 90)))


_ASIDE = {"Hand": "author frame 0 is Arrow's - not an independent reference",
          "Wait": "curved facets, control only - slopes not a source of numbers"}


def _report(name, size, count):
    print("\n=== %s @ %d ===%s"
          % (name, size, "  [%s]" % _ASIDE[name] if name in _ASIDE else ""))
    print("%-8s%9s%8s%8s%8s%8s%8s%8s%8s%8s%7s%7s" %
          ("who", "stations", "c", "s", "unres", "b_lo", "b_hi",
           "k_lo", "k_hi", "bend", "notch", "rms"))
    for who, get in (("author", A.orig_frame), ("ours", A.frame)):
        tr = track(name, 0, size, get, count=count)
        if not tr:
            print("%-8s%9s   the measurer read nothing - treat as a fault here"
                  % (who, "0/%d" % count))
            continue
        r = _summary(tr, count)
        print("%-8s%9s%+8.2f%8.2f%8d%8.1f%8.1f%+8.1f%+8.1f%8.1f%7.1f%7.1f" %
              (who, r["stations"], r["c"], r["s"], r["unresolved"],
               r["b_lo"], r["b_hi"], r["k_lo"], r["k_hi"],
               max(r["bend_lo"], r["bend_hi"]), r["d"], r["rms"]))


def _converge(name, sizes, count):
    """The same station at several rungs: is s a width or the pixel pitch?"""
    print("\n=== %s, s against resolution ===" % name)
    print("%-8s%6s%5s%8s%8s%8s%8s%8s" %
          ("who", "size", "n", "s med", "s p10", "s p90", "unres", "px LU"))
    for who, get in (("author", A.orig_frame), ("ours", A.frame)):
        for size in sizes:
            tr = track(name, 0, size, get, count=count)
            if not tr:
                print("%-8s%6d    0 stations - fault in the measurer" % (who, size))
                continue
            r = _summary(tr, count)
            print("%-8s%6d%5d%8.3f%8.3f%8.3f%8d%8.3f" %
                  (who, size, len(tr), r["s"], r["s_p10"], r["s_p90"],
                   r["unresolved"], V.LOGICAL / float(size)))


def _sheet(name, size, count, out, rows=8):
    """The sections drawn, author left, ours right. A number is easy to get
    from the wrong object - this is the check that the object is right."""
    from PIL import Image
    w, h, pad, bg = 320, 150, 6, 32
    tr = {who: {round(m["t"], 4): m for m in track(name, 0, size, get, count)}
          for who, get in (("author", A.orig_frame), ("ours", A.frame))}
    ts = sorted(set(tr["author"]) & set(tr["ours"]))
    if not ts:
        print("no station resolves on both - nothing to draw")
        return
    ts = ts[:: max(1, len(ts) // rows)][:rows]
    lo = min(min(m["raw"].min() for m in v.values()) for v in tr.values()) - 5
    hi = max(max(m["raw"].max() for m in v.values()) for v in tr.values()) + 5

    def panel(m):
        img = np.full((h, w, 3), bg, np.uint8)
        n = m["n"]
        span = max(float(np.ptp(n)), 1e-9)
        x = ((n - n.min()) / span * (w - 2 * pad) + pad).astype(int)

        def col(v):
            return np.clip((h - pad - (v - lo) / max(hi - lo, 1e-9) *
                            (h - 2 * pad)).astype(int), 0, h - 1)

        for nval, rgb in ((0.0, (70, 110, 200)), (m["c"], (90, 200, 110))):
            if n.min() <= nval <= n.max():
                px = int((nval - n.min()) / span * (w - 2 * pad) + pad)
                img[:, max(0, px):px + 1] = rgb
        phi = 0.5 * (1 + np.tanh((n - m["c"]) / m["s"]))
        fit = m["b_lo"] * (1 - phi) + m["b_hi"] * phi
        # the fit lives in the detrended profile; put the slopes back to draw it
        # over the section as it really is
        img[col(fit + (m["raw"] - m["y"])), x] = (150, 90, 60)
        img[col(m["raw"]), x] = (220, 220, 220)
        if m["d"] > 0:
            k = int(np.argmin(m["res"]))
            yk = int(col(m["raw"])[k])
            img[max(0, yk - 3):yk + 4, max(0, x[k]):x[k] + 1] = (220, 70, 70)
        return img

    strips = []
    for t in ts:
        strips.append(np.hstack([panel(tr["author"][t]),
                                 np.full((h, 3, 3), 90, np.uint8),
                                 panel(tr["ours"][t])]))
        strips.append(np.full((3, strips[-1].shape[1], 3), 90, np.uint8))
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, "%s_%d.png" % (name, size))
    Image.fromarray(np.vstack(strips)).save(path)

    print("\n%s: %d stations drawn, author left / ours right -> %s"
          % (name, len(ts), path))
    print("%6s%16s%14s%16s%14s" % ("t", "c a/o", "s a/o", "notch a/o", "rms a/o"))
    for t in ts:
        a, o = tr["author"][t], tr["ours"][t]
        print("%6.2f%+8.2f%+8.2f%7.2f%7.2f%8.1f%8.1f%7.1f%7.1f" %
              (t, a["c"], o["c"], a["s"], o["s"], a["d"], o["d"],
               a["rms"], o["rms"]))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cursor", default=None, metavar="NAME",
                    help="one of %s; default all" % ", ".join(WEDGES))
    ap.add_argument("--independent", action="store_true",
                    help="only %s - the wedges that are separate evidence"
                         % ", ".join(INDEPENDENT))
    ap.add_argument("--size", type=int, default=256)
    ap.add_argument("--sizes", default=None, metavar="A,B,C",
                    help="report s against resolution instead")
    ap.add_argument("--stations", type=int, default=24)
    ap.add_argument("--debug", action="store_true",
                    help="also draw the sections to --out")
    ap.add_argument("--out", default=os.path.join(HERE, "audit", "fold"),
                    metavar="DIR")
    args = ap.parse_args()

    names = ([args.cursor] if args.cursor else
             list(INDEPENDENT if args.independent else WEDGES))
    for name in names:
        if name not in WEDGES:
            raise SystemExit("%s carries no fold chord; known: %s"
                             % (name, ", ".join(WEDGES)))
        if args.sizes:
            _converge(name, [int(s) for s in args.sizes.split(",")], args.stations)
        else:
            _report(name, args.size, args.stations)
        if args.debug:
            _sheet(name, args.size, args.stations, args.out)


if __name__ == "__main__":
    main()

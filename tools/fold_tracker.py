#!/usr/bin/env python3
"""Reads the fold at the command line: the author's, ours, side by side.

The measurement itself lives in foldfit, which analyze.py gates on. Same code,
so the number a person reads here and the number a commit has to pass are the
same number - this file is the report, not a second opinion.

Written 2026-08-21 because the tracker in analyze.py cannot read the author at
all. That one takes the darkest interior pixel per row inside +-_JAG_BAND of the
chord, and admits a row by counting pixels over `_SOLID_FRAC * al.max()`. The
author's peak alpha is his opaque outline, so on Arrow at 256 the test throws
away 232 rows of 256 before anything is measured, and the resulting silence was
being read as "the reference scores no better than we do". It does not: it was
never reached. What the sections actually show is not a pit either - it is a
transition between two facet levels, with a dark notch sitting on the
transition, and on the author both facets are sloped and the left one is domed.
Since 2026-08-22 that reading is the gate's; see foldfit for how the fit works
and analyze.THRESHOLDS for what is asked of it.

Reported per station:

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
and 512 alike.

`bend` is a confidence figure, not a defect: small means the straight facet is a
fair description and the slope can be trusted, large means it is not. On the
author it runs 1.3 to 3.1 everywhere except Wait, where the left facet is
genuinely curved and reads 11.6 - so Wait's slopes are a control, not a source
of parameters, and a quadratic facet model would be a measuring option to add
later rather than a rewrite of the base fit.

What this does not measure, and it matters: `s`, `d` and `rms` describe one
cross-section's shape and nothing else. They say nothing about whether the
features either side of the fold survived. A change that flattens the lit inner
facet into the fold improves all three at once - width up, notch on target,
residual halved - because a flat field has nothing left to disagree with itself,
and that is exactly what happened on 2026-08-21 to a render whose inner tip had
visibly been destroyed (DEAD_ENDS.md, "Зонный temper"). These numbers are not a
sufficient acceptance test on their own. Render it and look first; that is the
rule in this repo and this tool is not an exception to it.

`--inner` is the companion for that specific blind spot: it asks whether the lit
inner facet is still a separate feature rather than how the fold is shaped. Two
independent classes, both required - a candidate that widens the transition and
loses the inner tip is rejected however good its `s`.

Alpha is used only as a floor for "there is a signal here at all". Admission is
geometric. Any station count of zero is a fault in foldfit until proven
otherwise.

Usage:
    python tools/fold_tracker.py --cursor Arrow --size 256
    python tools/fold_tracker.py --cursor Arrow --size 256 --debug
    python tools/fold_tracker.py --sizes 128,256,512      # is s a real width?
    python tools/fold_tracker.py --inner                  # is the tip still there?
"""
import argparse
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))

import analyze as A
import foldfit as F
from cgr import hybrid as H
from cgr import vectorlib as V

# The five cursors whose silhouette carries a wedge fold. Three of them are
# independent references: Arrow, Arrow_Down, UpArrow. Wait is a control, its
# facets being curved (see `bend` above), and Hand is not a sample at all at
# frame 0 - the author's ani__Hand__0 is his cur__Arrow__0 pixel for pixel, so
# counting it makes one bitmap look like two cursors agreeing. Read Hand at a
# frame where the light has actually moved, or leave it for checking the
# animation once the static wedges are explained.
#
# Five, not ten: Help, Handwriting, NO, SizeAll and AppStarting carry a fold too
# and the gate measures all ten. These are the ones the model was worked out on.
WEDGES = ("Arrow", "Arrow_Down", "Hand", "UpArrow", "Wait")
INDEPENDENT = ("Arrow", "Arrow_Down", "UpArrow")

track = F.track
measure = F.measure
section = F.section
inner_tip = F.inner_tip


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
        tr = F.track(name, 0, size, get, count=count)
        if not tr:
            print("%-8s%9s   the measurer read nothing - treat as a fault here"
                  % (who, "0/%d" % count))
            continue
        r = _summary(tr, count)
        print("%-8s%9s%+8.2f%8.2f%8d%8.1f%8.1f%+8.1f%+8.1f%8.1f%7.1f%7.1f" %
              (who, r["stations"], r["c"], r["s"], r["unresolved"],
               r["b_lo"], r["b_hi"], r["k_lo"], r["k_hi"],
               max(r["bend_lo"], r["bend_hi"]), r["d"], r["rms"]))


def _inner_report(name, size, count):
    """Has the inner tip survived? Ours only - the author has no such structure
    to compare against, his frame being 32px art."""
    r = F.inner_tip(name, 0, size, A.frame, count=count)
    if not r:
        print("%-12s@%-5d no section reaches the rim - fault in the measurer"
              % (name, size))
        return
    dip = np.array([x["dip"] for x in r])
    ridge = np.array([x["ridge"] for x in r])
    print("%-12s@%-5d inner tip kept on %2d of %2d stations | "
          "separator %4.1f (%.1f..%.1f) | ridge %4.1f (%.1f..%.1f)"
          % (name, size, sum(x["ok"] for x in r), len(r),
             np.median(dip), dip.min(), dip.max(),
             np.median(ridge), ridge.min(), ridge.max()))


def _converge(name, sizes, count):
    """The same station at several rungs: is s a width or the pixel pitch?"""
    print("\n=== %s, s against resolution ===" % name)
    print("%-8s%6s%5s%8s%8s%8s%8s%8s" %
          ("who", "size", "n", "s med", "s p10", "s p90", "unres", "px LU"))
    for who, get in (("author", A.orig_frame), ("ours", A.frame)):
        for size in sizes:
            tr = F.track(name, 0, size, get, count=count)
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
    tr = {who: {round(m["t"], 4): m for m in F.track(name, 0, size, get, count)}
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
    ap.add_argument("--stations", type=int, default=F.STATIONS)
    ap.add_argument("--inner", action="store_true",
                    help="report inner-tip survival instead of the fold profile")
    ap.add_argument("--debug", action="store_true",
                    help="also draw the sections to --out")
    ap.add_argument("--out", default=os.path.join(HERE, "audit", "fold"),
                    metavar="DIR")
    args = ap.parse_args()

    names = ([args.cursor] if args.cursor else
             list(INDEPENDENT if args.independent else WEDGES))
    for name in names:
        # Any cursor with a chord can be reported - the gate measures ten - but
        # one without a fold has to say so rather than come back as a measurer
        # that read nothing, which is a different thing entirely.
        if H._fold_chord(name, 0) is None:
            raise SystemExit("%s carries no fold chord at frame 0; the wedges "
                             "this was worked out on are %s"
                             % (name, ", ".join(WEDGES)))
        if args.inner:
            _inner_report(name, args.size, F.INNER_STATIONS)
        elif args.sizes:
            _converge(name, [int(s) for s in args.sizes.split(",")], args.stations)
        else:
            _report(name, args.size, args.stations)
        if args.debug:
            _sheet(name, args.size, args.stations, args.out)


if __name__ == "__main__":
    main()

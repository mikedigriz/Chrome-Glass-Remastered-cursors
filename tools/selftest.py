#!/usr/bin/env python3
"""Negative control: every metric must go red on a defect planted on purpose.

A metric that cannot fail is not a metric. PLAN.md's attempt 36 is the whole
argument for this file: the fold measurement selected its sample rows with
`alpha > 0.8 * max`, which excluded the interior it was supposed to read, and
it returned a clean zero on all sixteen cursors while the straightening it was
watching over did nothing at all. Nobody noticed for nine approaches, because
zero is what passing looks like.

So each check here damages one frame in one specific way and asserts the number
that owns that defect moves. Assertions are relative - damaged against clean,
same cursor, same run - so nothing here has to be re-tuned when a threshold
moves.

    python tools/selftest.py

Cheap on purpose: two cursors, and the frames come out of analyze's own cache,
so it is one render of each rather than a sweep.
"""

import json
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import analyze as A  # noqa: E402
import hybrid as H  # noqa: E402

SIZE = A.JITTER_SIZE
FAILED = []


def check(label, ok, detail):
    print(f"  {'pass' if ok else 'FAIL'}  {label:28s} {detail}")
    if not ok:
        FAILED.append(label)


def repoint():
    """Drop every cached render, from analyze's frames down to hybrid's own
    memoised geometry.

    Swept rather than listed by name on purpose. The tests that damage the
    traced outline need every layer between the polygon and the pixels to
    forget what it knows, and a hand-written list goes stale silently: adding
    _mask_prims between _mask_geom and the polygon left the list looking
    complete while the damage stopped reaching the raster, and the straightness
    control read the undamaged number and called it a pass. A control that
    quietly stops controlling is worse than no control."""
    A._frame_cache.clear()
    for mod in (H, A):
        for nm in dir(mod):
            fn = getattr(mod, nm, None)
            if hasattr(fn, "cache_clear"):
                fn.cache_clear()


def damaged(name, idx, size, fn):
    """Put a damaged copy of one frame into analyze's cache and hand back a
    restore callable. The cache is the seam every metric here goes through, so
    damaging it needs no hooks anywhere else."""
    key = (name, idx, size)
    A.frame(name, idx, size)                       # make sure the real one is in
    orig = A._frame_cache[key]
    A._frame_cache[key] = fn(orig.copy())
    return lambda: A._frame_cache.__setitem__(key, orig)


def fold_rows(name, size):
    """Rows the fold is actually tracked on, not rows the chord passes through.

    The two differ by a lot - Arrow's chord spans 128 rows at 256px and the
    fold resolves on 40 of them - and damage planted outside the tracked range
    is damage the metric is right not to see."""
    ref = A._chord_ref(name, 0, size)
    t = A._fold_track(name, 0, size, ref, A._JAG_BAND * size / 32.0)
    return np.nonzero(~np.isnan(t))[0], ref


def test_topology():
    want = H.C.CURSOR_TOPOLOGY["Arrow"]
    check("topology clean", not A.validate_topology("Arrow"), "no complaints")
    H.C.CURSOR_TOPOLOGY["Arrow"] = dict(want, tips=[want["tips"][0] + 1])
    try:
        bad = A.validate_topology("Arrow")
        check("topology tip count", bool(bad), bad[0] if bad else "nothing reported")
    finally:
        H.C.CURSOR_TOPOLOGY["Arrow"] = want


def test_fold_gap():
    """Paint the fold out over a stretch of rows. The line is then in two
    pieces, and the gap between them is the number that has to move."""
    rows, ref = fold_rows("Arrow", SIZE)
    clean = A.fold_profile("Arrow", 0, SIZE)
    lo = rows[len(rows) // 3]
    span = max(10, len(rows) // 4)
    b = max(2, int(round(A._JAG_BAND * SIZE / 32.0)))

    def wipe(a):
        for y in range(lo, lo + span):
            c = int(ref[y])
            # Flat and bright: whatever is around the fold, without the fold.
            a[y, max(0, c - b):c + b + 1, :3] = a[y, max(0, c - 2 * b):c - b, :3].max()
        return a

    restore = damaged("Arrow", 0, SIZE, wipe)
    try:
        hurt = A.fold_profile("Arrow", 0, SIZE)
        check("fold gap", hurt["gap"] > clean["gap"] + 0.5,
              f"{clean['gap']:.2f} -> {hurt['gap']:.2f} logical units")
    finally:
        restore()


def test_fold_wander():
    """Push every other row of the fold sideways by a pixel: a staircase edge,
    exactly. Wander is curvature, so it sees this and a straight fold at any
    angle still reads zero."""
    rows, _ = fold_rows("Arrow", SIZE)
    clean = A.fold_profile("Arrow", 0, SIZE)

    def stagger(a):
        for y in rows[::2]:
            a[y] = np.roll(a[y], 1, axis=0)
        return a

    restore = damaged("Arrow", 0, SIZE, stagger)
    try:
        hurt = A.fold_profile("Arrow", 0, SIZE)
        check("fold wander", hurt["wander"] > clean["wander"] * 1.5,
              f"{clean['wander']:.3f} -> {hurt['wander']:.3f} logical units")
    finally:
        restore()


def test_fold_jag():
    """Change the section's shape on alternate rows without moving it: a deeper
    crease on one row, a shallower one on the next. Sliding a whole row sideways
    deliberately does not count here - the profiles are read relative to the
    track, so a rigid shift is wander's business and not this one's.

    Both factors stay above 1.0, and that is load-bearing. The control used to
    alternate 1.7 against 0.4, and 0.4 does not make the crease shallow, it
    erases it: prominence fell under _FOLD_DEPTH and the row left the track
    altogether. Nineteen of thirty-nine rows went, and with them every adjacent
    pair the jag reading is built from - so the number the control was reading
    came from the only pair left, rows 145 and 146, which are past the tail
    vertex and are the tracker sitting on a neighbouring facet rather than on
    the fold at all. The control was green on an artefact, and it went red the
    moment _fold_track stopped following the tracker off the crease. Damage
    that destroys the track cannot test what the track measures."""
    rows, ref = fold_rows("Arrow", SIZE)
    clean = A.fold_profile("Arrow", 0, SIZE)
    b = max(2, int(round(A._JAG_BAND * SIZE / 32.0)))

    def reshape(a):
        for n, y in enumerate(rows):
            c = int(ref[y])
            lo, hi = max(0, c - b), min(SIZE, c + b + 1)
            seg = a[y, lo:hi, :3]
            a[y, lo:hi, :3] = np.clip(
                seg.mean() + (seg - seg.mean()) * (1.7 if n % 2 else 1.1), 0, 255)
        return a

    restore = damaged("Arrow", 0, SIZE, reshape)
    try:
        hurt = A.fold_profile("Arrow", 0, SIZE)
        check("fold jag", hurt["jag"] > clean["jag"] * 1.2,
              f"{clean['jag']:.0f} -> {hurt['jag']:.0f} levels")
    finally:
        restore()


def test_temporal():
    """Alternate the fold's brightness frame to frame. The sweep still covers
    the same ground, so amplitude does not change and only the smoothness has
    anything to say about it."""
    clean = A.temporal_smoothness("Wait")
    band = A._fold_band("Wait", SIZE)
    restores = []

    def jitter(sign):
        def fn(a):
            a[..., :3][band] = np.clip(a[..., :3][band] + sign * 18.0, 0, 255)
            return a
        return fn

    try:
        for i in range(A.nframes("Wait")):
            restores.append(damaged("Wait", i, SIZE, jitter(1 if i % 2 else -1)))
        hurt = A.temporal_smoothness("Wait")
        check("temporal fold", hurt["fold"] > clean["fold"] * 1.5,
              f"{clean['fold']:.2f} -> {hurt['fold']:.2f}")
    finally:
        for r in restores:
            r()


def test_delta_e():
    """Give the glass a warm cast, at constant luminance.

    Not a channel swap: Arrow's glass is neutral grey around (150, 152, 155),
    so swapping red and blue on it changes almost nothing and is right not to
    register. A cast is the defect that actually happened here - the warm halo
    from lifting the blacks, the purple along UpArrow's fold from the top hat -
    and it is invisible to every brightness metric in the file."""
    clean = A.delta_e("Arrow")

    def cast(a):
        a[..., 0] = np.clip(a[..., 0] + 22.0, 0, 255)
        a[..., 2] = np.clip(a[..., 2] - 22.0, 0, 255)
        return a

    restore = damaged("Arrow", 0, A._DE_NATIVE, cast)
    try:
        hurt = A.delta_e("Arrow")
        check("delta_e hue swap", hurt["mean"] > clean["mean"] + 5.0,
              f"{clean['mean']:.2f} -> {hurt['mean']:.2f}")
    finally:
        restore()


def test_fold_unmeasured():
    """A fold declared in the topology and resolved nowhere has to fail the
    gate, not pass it quietly. This is attempt 36, written down as a test."""
    rep = {"Arrow": {"scale_drift": 0.0, "density": 0.0, "tip_convergence": 0.0,
                     "tip_convergence_orig": 0.0, "tip_contrast": 1.0,
                     "tip_contrast_orig": 0.0, "topology": [],
                     "multiscale": {"worst": {k: 0.0 for k in
                                              ("gap", "luma_step", "wander", "jag", "tip")},
                                    "resolved": [], "per_size": {}},
                     "delta_e": {"mean": 0.0, "p95": 0.0, "frame": 0}}}
    bad, _ = A.gate(rep)
    check("fold unmeasured", any("fold_unmeasured" in b for b in bad),
          bad[0] if bad else "gate passed an unmeasured fold")


def test_rim_layers():
    """Paint a dark ring at a fixed depth inside the contour - the master's own
    defect, planted deliberately. The share of stations carrying an extra layer
    has to rise. Keyed on H._edge_distance so the ring follows the outline the
    way the real one does, and deliberately not on the route the metric itself
    walks, which is the traced polygon."""
    size = A._RIM_SIZE
    clean = A.rim_layers("Cross", size=size)      # the cleanest cursor there is
    d = H._edge_distance("Cross", 0)
    if d.shape[0] != size:
        d = np.asarray(Image.fromarray(d.astype(np.float32), mode="F")
                       .resize((size, size), Image.BILINEAR), dtype=np.float64)
    ring = (d > 0.6) & (d < 0.8)

    def band(a):
        a[..., :3][ring] *= 0.7
        return a

    restore = damaged("Cross", 0, size, band)
    try:
        hurt = A.rim_layers("Cross", size=size)
        check("rim layers", hurt["share"] > clean["share"] + 0.2,
              f"{clean['share']*100:.0f}% -> {hurt['share']*100:.0f}% of stations")
    finally:
        restore()


def test_edge_straight():
    """Push a sawtooth into the longest corner-free run of vertices.

    The damage is shaped like the defect. A run of vertices alternating either
    side of the line they are meant to lie on is exactly what traced.json holds
    and what the metric exists to find, so that is what gets injected here.

    Bowing a single vertex instead does almost nothing to the reading, and the
    reason is worth recording: C.smooth spreads one displaced vertex into a
    bump some three logical units wide, and a straight line fitted over a
    six-unit window tilts into a bump that wide and absorbs most of it. A raw
    0.5-unit bow moved the reading by 0.001. That is the metric behaving
    correctly - a gentle three-unit swell really is nearly straight at this
    scale - but it makes a single vertex a poor control.

    The amplitude stays under _STRAIGHT_ARC so the window still reads as meant
    to be straight. Past it the metric rightly declines to call the stretch a
    line, and the reading comes back off some other, undamaged window, which
    looks like a miss when it is a refusal to measure a curve nobody claimed
    was straight."""
    name = "Arrow"
    poly = H.C.TRACED[name]["frames"][0]["polys"]
    clean = A.edge_straight(name)
    keep = json.loads(json.dumps(poly))
    try:
        pts = [np.array(p[:2], dtype=np.float64)
               for p in H.C.smooth([tuple(p) for p in poly[0]])]
        n = len(pts)
        flags = [bool(p[2]) if len(p) > 2 else False for p in poly[0]]
        # the longest stretch carrying no traced corner: the metric measures
        # exactly the windows that hold none, so this is where damage lands
        run, start = 0, 0
        for i in range(n):
            ln = 0
            while ln < n and not flags[(i + ln) % n]:
                ln += 1
            if ln > run:
                run, start = ln, i
        amp = 0.4 * A._STRAIGHT_ARC
        for j in range(run):
            v = (start + j) % n
            t = pts[(v + 1) % n] - pts[(v - 1) % n]
            t = t / max(float(np.hypot(*t)), 1e-9)
            s = amp if j % 2 == 0 else -amp
            poly[0][v] = [poly[0][v][0] + t[1] * s,
                          poly[0][v][1] - t[0] * s] + list(poly[0][v][2:])
        repoint()
        hurt = A.edge_straight(name)
        check("edge straightness", hurt["max"] > clean["max"] + 0.1,
              f"{clean['max']:.3f} -> {hurt['max']:.3f} logical units "
              f"({run} vertices sawtoothed by {amp:.2f})")
    finally:
        H.C.TRACED[name]["frames"][0]["polys"][:] = keep
        repoint()


def test_mirror_asym():
    """Eat one arm. A symmetric cursor must stop reading as symmetric."""
    clean = A.mirror_asym("Cross")

    def bite(a):
        a[:a.shape[0] // 2, :, 3] *= 0.5
        return a

    restore = damaged("Cross", 0, 32, bite)
    try:
        hurt = A.mirror_asym("Cross")
        c, h = max(clean["native"].values()), max(hurt["native"].values())
        check("mirror asymmetry", h > c + 2.0, f"{c:.1f} -> {h:.1f} levels")
    finally:
        restore()


def main():
    print("negative control: each defect is planted, the metric must see it")
    for t in (test_topology, test_fold_gap, test_fold_wander, test_fold_jag,
              test_temporal, test_delta_e, test_fold_unmeasured,
              test_rim_layers, test_edge_straight, test_mirror_asym):
        t()
    print()
    if FAILED:
        print(f"FAIL ({len(FAILED)}): " + ", ".join(FAILED))
        print("A metric that does not move on its own defect is not measuring it.")
        return 1
    print("PASS - every metric moved on its own defect")
    return 0


if __name__ == "__main__":
    sys.exit(main())

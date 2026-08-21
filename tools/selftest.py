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
import math
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import analyze as A  # noqa: E402
from cgr import hybrid as H  # noqa: E402

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
    anything to say about it.

    Damages the frames themselves rather than the renderer behind them: these
    metrics read the cycle that ships, which is lit from one canonical render,
    so patching a per-phase master no longer changes what they see."""
    frames = A.product_frames("Wait", SIZE)
    clean = A._smoothness("Wait", frames)
    band = A._fold_band("Wait", SIZE)
    hurt_frames = []
    for i, f in enumerate(frames):
        g = f.copy()
        g[..., :3][band] = np.clip(g[..., :3][band] + (18.0 if i % 2 else -18.0), 0, 255)
        hurt_frames.append(g)
    hurt = A._smoothness("Wait", hurt_frames)
    check("temporal fold", hurt["fold"] > clean["fold"] * 1.5,
          f"{clean['fold']:.2f} -> {hurt['fold']:.2f}")


def test_inner_jitter():
    """Shove the fold sideways on alternate frames of the cycle that ships.

    Two things at once, both of them the point of this metric's rewrite: it has
    to read the product frames, and it has to count pairs of neighbouring frames
    rather than rows resolved in every frame of the cycle. So the damage is
    planted on one frame in three, which under the old all-frames rule would
    have deleted every row instead of raising the number."""
    name = "Hand"
    clean = A.inner_jitter(name)
    frames = [f.copy() for f in A.product_frames(name)]
    band = A._fold_band(name, A.JITTER_SIZE)
    for i, f in enumerate(frames):
        if i % 3 == 0:
            f[..., :3][band] = np.roll(f[..., :3], 2, axis=1)[band]
    key = (name, A.JITTER_SIZE)
    keep = A._product_cache[key]
    try:
        A._product_cache[key] = frames
        hurt = A.inner_jitter(name)
    finally:
        A._product_cache[key] = keep
    check("inner jitter", hurt["p95"] > clean["p95"] * 2.0 and hurt["rows"] >= 10,
          f"p95 {clean['p95']:.3f} -> {hurt['p95']:.3f} on {hurt['rows']} rows, "
          f"coverage {hurt['pair_coverage']:.2f}")


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
    """A fold declared in the topology and resolved nowhere must never read as a
    plain pass. It is no longer counted as a defect of the render - it says the
    tracker could not see the fold, so it comes back in its own class - but a
    reading the baseline had and this run has not is still a regression. This is
    attempt 36, written down as a test."""
    rep = {"Arrow": {"scale_drift": 0.0, "density": 0.0, "tip_convergence": 0.0,
                     "tip_convergence_orig": 0.0, "tip_extreme_contrast": 1.0,
                     "tip_extreme_contrast_orig": 0.0, "tip_profile": 1.0,
                     "topology": [],
                     "multiscale": {"worst": {k: 0.0 for k in
                                              ("gap", "luma_step", "wander", "jag", "tip")},
                                    "resolved": [], "per_size": {}},
                     "delta_e": {"mean": 0.0, "p95": 0.0, "frame": 0}}}
    bad, _, unmeasured, _ = A.gate(rep)
    check("fold unmeasured", any("fold" in u for u in unmeasured) and not bad,
          unmeasured[0] if unmeasured else "gate passed an unmeasured fold in silence")
    # ...and the same reading, once the baseline has one, is a regression.
    bad, _, _, _ = A.gate(rep, {"Arrow": {"fold_gap": 0.5}})
    check("fold unmeasured vs baseline", any("fold_unmeasured" in b for b in bad),
          bad[0] if bad else "gate lost a fold reading without saying so")


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


def test_straighten_runs():
    """Sawtooth a straight edge, then check trace's pass takes it back out.

    The other tests here plant a defect and require a metric to see it. This one
    plants the same defect one stage earlier, in the vector, and requires the
    stage that exists to remove it to actually remove it - and, just as
    importantly, to leave the two anchors exactly where they were. A pass that
    straightens a corner away would score beautifully on this and be useless."""
    from cgr import trace as T                          # noqa: E402
    eps = 0.7 / 4.0
    n = 12
    # One straight edge the way a cursor actually holds one: a flagged corner at
    # each end, both sitting on the line, and the vertices between them sawing
    # across it. The corners have to be on the line or no run can start at one,
    # and then the first and last sawtooth vertex stay where they are - which is
    # correct behaviour on a real bend and useless as a fixture.
    saw = [(3.0 + k, 8.0 + (eps * 0.9 if k % 2 else -eps * 0.9))
           for k in range(n)]
    poly = [(2.0, 8.0)] + saw + [(15.0, 8.0), (8.0, 2.0)]
    flags = [True] + [False] * n + [True, True]
    out = T.straighten_runs(list(poly), flags, eps)
    before = max(abs(p[1] - 8.0) for p in poly[1:1 + n])
    after = max(abs(p[1] - 8.0) for p in out[1:1 + n])
    moved = max(math.hypot(a[0] - b[0], a[1] - b[1])
                for a, b in ((poly[0], out[0]), (poly[n + 1], out[n + 1]),
                             (poly[n + 2], out[n + 2])))
    # not to zero: a finite run of alternating samples has a small net tilt, and
    # the fit follows it, which is what fitting the data rather than assuming the
    # answer looks like
    check("straighten removes the sawtooth", after < 0.25 * before,
          f"{before:.3f} -> {after:.3f} logical units off the line")
    check("straighten pins the anchors", moved < 1e-9,
          f"corner moved {moved:.2e} logical units")


def test_material_basis():
    """The frames in hybrid._MATERIAL_BASIS carry no material of their own, and
    the contract is worth a control: a frame listed there must move when its
    basis moves, and a frame not listed must not move at all.

    Not a picture quality check. It exists so that a year from now "let us
    improve frame 8" cannot quietly change four other frames without anybody
    noticing which ones, and so that the reverse - a basis frame that has
    silently started reading from the frames that borrow from it - shows up as
    a cycle here rather than as a mystery in the render."""
    name, size = "Handwriting", 128
    watch = [2, 3, 4, 5, 6, 7]

    def render():
        return {i: np.asarray(H.frame_image(name, i, size), dtype=float)
                for i in watch}

    repoint()
    base = render()
    orig = H._master_rgb
    for basis, expect in ((2, {2, 3, 4}), (8, {5, 6})):
        def patched(n, i, s, _b=basis, _o=orig):
            rgb = _o(n, i, s)
            if (n, i) != (name, _b):
                return rgb
            # A stripe, not a constant: the layer transfers high frequencies,
            # so a flat offset is exactly the damage it is built to drop, and
            # the first run of this control passed the offset and read nothing.
            y = np.arange(rgb.shape[0])[:, None, None]
            return rgb + 12.0 * ((y // 2) % 2)
        H._master_rgb = patched
        repoint()
        now = render()
        H._master_rgb = orig
        repoint()
        moved = {i for i in watch if np.abs(now[i] - base[i]).max() > 0.5}
        check("material basis %d" % basis, moved == expect,
              "moved %s, expected %s" % (sorted(moved), sorted(expect)))


def test_material_dc():
    """The material layer carries texture, not level.

    Its alpha-weighted mean over the region it is composited onto has to be
    zero: it transfers high frequencies, and a level it did not mean to move is
    a level nobody downstream is watching for. This is not a planted defect -
    it is the contract itself, checked directly, because the last time it broke
    the only symptom was Handwriting[4] shipping +2.1 L bright and delta_e
    drifting 3.55 -> 4.68 under the gate's threshold, where nothing complained
    (NEXT.md 47). Read before the clip: that is a separate nonlinearity, worth
    its own measurement if it ever grows.

    Not a picture check either. A layer may be wrong about where it puts its
    contrast and still pass here; what it may not do is quietly relight the
    frame."""
    size = 256
    for (name, idx), donor in sorted(H._MATERIAL_BASIS.items()):
        detail = H._material_detail(name, idx, donor, size)
        w = (H._mask(name, idx, size) / 255.0) * (H._up_alpha(name, idx, size) / 255.0)
        wsum = max(w.sum(), 1e-9)
        dc = float((detail[..., 0] * w).sum() / wsum)
        # What the clip then adds back, reported but not asserted: it is a
        # separate nonlinearity and it is currently small (0.02-0.36 levels).
        # If it grows, measure the clipped mass by sign before touching it.
        own = H._resize(H._orig(H._key(name, idx)), size)[0]
        after = float(((np.clip(own + detail, 0, 255) - own).mean(2) * w).sum() / wsum)
        check("material DC %s[%d]" % (name, idx), abs(dc) < 0.05,
              "mean residual %+.4f levels, %+.4f after the clip" % (dc, after))


def main():
    print("negative control: each defect is planted, the metric must see it")
    for t in (test_topology, test_fold_gap, test_fold_wander, test_fold_jag,
              test_temporal, test_inner_jitter, test_delta_e, test_fold_unmeasured,
              test_rim_layers, test_edge_straight, test_mirror_asym,
              test_straighten_runs, test_material_basis, test_material_dc):
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

#!/usr/bin/env python3
"""Geometry and motion metrics for the built cursors.

The build's own check_metrics only looks at median alpha and saturation, which
is blind to everything the upscale actually got wrong: a silhouette whose extent
depends on the size it is rendered at, glass that thins out as the size grows,
shading that steps between animation frames, a fold that stops short of the
point, and a morph that falls apart mid-sequence. Each of those has a number
here, measured off hybrid.frame_image directly - no dist/ build needed.

    python tools/analyze.py --check metrics-baseline.json    the gate
    python tools/analyze.py --baseline base.json             full snapshot
    python tools/analyze.py --ratchet metrics-baseline.json  move the baseline

Thresholds are the target. When one does not pass, the fix is the pipeline, not
the threshold.

metrics-baseline.json is where the set actually stands, and it is committed.
A value that misses its threshold but is no worse than that file is debt: it
gets printed every run and it does not fail the build. A value that moves away
from the target fails immediately. That is what lets the gate run today - the
alternative was a gate switched off until everything passes, which is how the
numbers in that file got there in the first place.
"""

import argparse
import concurrent.futures as cf
import functools
import json
import os
import sys
import warnings

from PIL import Image
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hybrid as H  # noqa: E402

LADDER = [32, 48, 64, 96, 128, 256, 384]
LADDER_FULL = LADDER + [512]
LADDER_FAST = [32, 128, 256]       # enough rungs to read a drift, few enough to iterate on
JITTER_SIZE = 256

# The sizes every geometric defect is looked for at. A cursor is shipped at 15
# fixed sizes on Windows and at whatever the compositor asks for on Linux, so a
# seam that only shows at 96 is still a seam. These are all rungs of LADDER
# already, which is why the sweep costs almost nothing: 512 is the one render
# it adds, and only under --full.
VALIDATE_SIZES = (32, 64, 128, 256)
VALIDATE_SIZES_FULL = VALIDATE_SIZES + (512,)
_JAG_BAND = 2.0            # logical units either side of the fold a step is looked for in
_DE_NATIVE = 256           # size the colour is judged at, box-averaged 8:1 down to 32
_FOLD_ROWS = 6             # rows a fold reading needs before it means anything
_RATCHET_SLACK = 0.05      # how far a floor metric may slip before it is a regression
_SOLID_FRAC = 0.85         # of a frame's own peak alpha: the glass proper
_GHOST_FRAC = 0.05         # ...and below this, nothing that can be seen
_FOLD_DEPTH = 6.0          # luma a dip must have to count as a fold and not as flat glass
_TIP_SPLIT = 28.0          # luma across a wedge that means its fold is present there
_MORPH_SIZE = 32           # the size the author's frames actually exist at
_TIP_COS = -0.17           # cos of the widest interior angle (100 deg) still a point

# Directions the silhouette's extent is measured along. Eight is enough to pin
# every cursor in the set: the diagonals catch the arrow points, the axials
# catch the Size* wedges and the Cross arms.
DIRS = {
    "TL": (-1, -1), "TR": (1, -1), "BL": (-1, 1), "BR": (1, 1),
    "L": (-1, 0), "R": (1, 0), "T": (0, -1), "B": (0, 1),
}

THRESHOLDS = {
    "scale_drift": 0.10,        # logical units of coverage spread across the ladder
                                # (the traced mask alone sits at 0.02..0.10)
    "density": 2.0,             # % drift of in-silhouette alpha across the ladder
    "ghost_rgb": 0.5,           # mean RGB delta where alpha < 10 (invisible zone)
    "liveliness_min": 0.9,      # share of the keyframes' own total cycle motion the
                                # sweep must keep - the guard against damping it flat
    "liveliness_max": 1.15,     # peak/mean of visible frame deltas: above this the
                                # sweep visibly hurries and dawdles
    "inner_jitter": 2.0,        # px @256 (a fifth of a logical unit), p95 of the
                                # fold's frame-to-frame step. Was 1.0 while the
                                # shading was pinned to the cycle mean; that pinning
                                # is gone because it cost the creases their edge -
                                # the mean is itself blurred, since the fold wanders
                                # a little between frames and averaging smears it.
                                # What is left does not read: see docs, and the
                                # kymographs the decision was made on.
    # tip_convergence has no threshold - see gate() for why it is diagnostic
    "morph_iou": 1.0,           # min IoU between morph frames, as a share of the
                                # author's own (1.0 = must be at least as coherent)
    "morph_peak": 1.0,          # peak/mean of a morph's frame deltas, same basis
    "tip_contrast": 1.0,        # point contrast on a background, as a share of the
                                # author's own
    # --- geometry read at every size, on every frame (validate_multiscale) ---
    "fold_gap": 0.0,            # logical units of fold missing mid-line. Zero is
                                # reachable and is the point: a fold either runs
                                # the length of the crease or it is broken.
    "fold_wander": 0.0,         # logical units, p95 sideways step of the line per row
    "fold_luma_step": 0.0,      # levels, p95 step in brightness along the line
    "fold_jag": 0.0,            # levels the fold's cross-section changes shape by
                                # from one row to the next. Absolute, not a share of
                                # the author's: at 0.85 of peak alpha the 2006 frame
                                # has almost no solid interior left, so its own fold
                                # cannot be tracked and there is no share to take.
    # --- colour and motion ---
    "temporal": 1.0,            # frame-to-frame step over cycle amplitude, scaled so
                                # a sinusoid sampled n times reads 1.0
    "delta_e": 5.0,             # CIEDE2000 against the author's own 32px frame
    "tip_sheen": 0.75,          # share of the author's own sweep that has to survive
                                # at the points. Not 1.0: the remaster's silhouette is
                                # crisp where his is soft, so the disc holds a little
                                # less glass. Frozen tips score 0.007 of him, so this
                                # separates "damped" from "switched off" with room to
                                # spare either side.
    # tip_wobble is reported, not gated - see gate()
}


def _erode_square(m, r):
    """Binary erosion by a (2r+1) square, in numpy.

    Same result as cv2.erode with a kernel of ones, border rule included:
    outside the canvas counts as set, so a shape that runs to the edge is not
    eaten from that side. Written out because it and one colour conversion were
    the whole of this file's OpenCV use, and cv2 is not in requirements.txt -
    it arrives with requirements-ai.txt, behind torch. A gate that cannot run
    without a machine-learning stack does not get run."""
    if r < 1:
        return m
    k = 2 * r + 1
    p = np.pad(m.astype(np.int64), r, constant_values=1)
    s = np.pad(p.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    tot = s[k:, k:] - s[:-k, k:] - s[k:, :-k] + s[:-k, :-k]
    return (tot == k * k).astype(m.dtype)


_frame_cache = {}


def frame(name, idx, size):
    k = (name, idx, size)
    if k not in _frame_cache:
        _frame_cache[k] = np.asarray(H.frame_image(name, idx, size), dtype=np.float64)
    return _frame_cache[k]


def orig_frame(name, idx, size):
    """The author's 32px frame at `size`, the reference the remaster is judged
    against. Several of these metrics have no meaningful absolute value - how
    much a morph may change between frames, or how much contrast a translucent
    point can carry, is a property of the drawing - so what they gate on is
    being no worse than the 2006 art, measured the same way."""
    k = (name, idx, size, "orig")
    if k not in _frame_cache:
        im = H.original(name, idx)
        if size != im.size[0]:
            im = im.resize((size, size), Image.LANCZOS)
        _frame_cache[k] = np.asarray(im, dtype=np.float64)
    return _frame_cache[k]


def nframes(name):
    return len(H.BY_NAME[name]["frames"])


def _moments(al, size):
    """Blur-invariant shape descriptors in the 32-unit logical grid.

    Thresholds and centroids of an outer band both move when the edge's
    anti-aliasing gets sharper, and it necessarily does: a vector edge is one
    device pixel wide at every size, which is one logical unit at 32px and a
    twelfth of one at 384. Measured that way a perfectly scale-exact mask
    reports half a unit of drift and the metric ends up grading its own blur.

    Coverage mass does not care. A symmetric blur moves alpha around without
    creating or destroying it, so total mass and its centroid survive it
    exactly. sqrt(mass) is that mass as an equivalent edge length, which is the
    number to compare across sizes: half a unit of it is half a unit of cursor
    that appeared or went missing."""
    L = size / 32.0
    w = al / 255.0
    m = w.sum()
    if m < 1e-6:
        return None
    ys, xs = np.mgrid[0:size, 0:size]
    return (float(np.sqrt(m) / L),
            float(((xs + 0.5) * w).sum() / m / L),
            float(((ys + 0.5) * w).sum() / m / L))


def scale_drift(name, sizes):
    """How much of the cursor appears or goes missing across the size ladder.

    Reported in logical units of equivalent edge length (sqrt of coverage
    mass), plus the centroid's own travel. A scale-consistent cursor is the
    same cursor at 32 and at 512; the traced mask alone measures 0.02..0.10
    here, so anything above that is the alpha pipeline being rebuilt per size
    rather than scaled."""
    rows = {}
    for s in sizes:
        m = _moments(frame(name, 0, s)[..., 3], s)
        if m is not None:
            rows[s] = m
    if len(rows) < 2:
        return 0.0, rows
    v = np.array(list(rows.values()))
    mass = float(v[:, 0].max() - v[:, 0].min())
    cent = float(np.hypot(*(v[:, 1:] - v[:, 1:].mean(0)).T).max())
    return max(mass, cent), {str(k): [round(x, 4) for x in val] for k, val in rows.items()}


_DENSITY_SAMPLE = 384      # size the sampling region is defined at
_DENSITY_INSET = 3.0       # logical units of margin, to stay well clear of the edge


@functools.lru_cache(maxsize=None)
def _density_points(name):
    """Interior sample points in logical coordinates, defined once.

    "Inside the mask at this size" is not a fixed region: at 32px only the
    thickest core clears the threshold, at 384 nearly the whole shape does, and
    the thin parts it picks up there are the less opaque ones. Averaging over
    it therefore reports a decline that is the region moving, not the glass
    thinning. One region, chosen in logical units and sampled at every size,
    compares like with like."""
    s = _DENSITY_SAMPLE
    L = s / 32.0
    m = H._mask(name, 0, s)
    u = H._up_alpha(name, 0, s)
    # Solid mask is not the same as solid glass: SizeAll's traced polygon covers
    # the star's hollow centre, where the translucency map is what cuts the hole.
    solid = ((m > 250) & (u > 0.35 * np.percentile(u, 99.5))).astype(np.uint8)
    for inset in (_DENSITY_INSET, 2.0, 1.0, 0.0):
        inner = _erode_square(solid, int(inset * L))
        if inner.sum() >= 64:              # SizeAll's arms are too thin for the full inset
            return inner.astype(np.float32)
    return solid.astype(np.float32)


def density(name, sizes):
    """Percent drift of the glass's own opacity across the size ladder.

    Measured on _up_alpha over one fixed logical region, which is where the
    loss happens: the vector mask is solid there at every size, so anything
    that moves is the alpha blend being rebuilt per size instead of scaled."""
    region = _density_points(name)
    vals = {}
    for s in sizes:
        # Bring each rung up to the region's own resolution rather than shrinking
        # the region down to it: resampling the region blurs its border into the
        # rim and puts a couple of percent of the rim's level back into the
        # reading, which is exactly what this is supposed to be free of.
        u = H._up_alpha(name, 0, s)
        if s != _DENSITY_SAMPLE:
            u = np.asarray(Image.fromarray(u.astype(np.float32), mode="F")
                           .resize((_DENSITY_SAMPLE,) * 2, Image.LANCZOS), dtype=np.float64)
        vals[s] = float((region * u).sum() / region.sum())
    if len(vals) < 2:
        return 0.0, vals
    v = np.array(list(vals.values()))
    return float(100.0 * (v.max() - v.min()) / v.mean()), vals


def _deltas(frames, cyclic):
    """Frame-to-frame colour deltas, split into the solid zone and the ghost one.

    Both zones are cut at fractions of the frame's own peak alpha, never at an
    absolute level: these are translucent glass cursors whose peak sits around
    190 and, on the thin Size* wedges, 158, so a fixed "alpha > 200" selects
    nothing at all and reports a lively animation as perfectly still."""
    A = [np.asarray(f, dtype=np.float64) for f in frames]
    idx = range(len(A)) if cyclic else range(len(A) - 1)
    out = []
    for i in idx:
        a, b = A[i], A[(i + 1) % len(A)]
        # Per pair, not per animation: Handwriting's pencil frames peak far
        # below its opening arrow, so one global level selected nothing in them
        # and reported three consecutive frames as byte-identical.
        peak = min(float(a[..., 3].max()), float(b[..., 3].max()))
        solid, ghost = _SOLID_FRAC * peak, _GHOST_FRAC * peak
        vis = (a[..., 3] > solid) & (b[..., 3] > solid)
        gho = (a[..., 3] < ghost) & (b[..., 3] < ghost)
        out.append((
            float(np.abs(a[..., :3][vis] - b[..., :3][vis]).mean()) if vis.sum() else 0.0,
            float(np.abs(a[..., :3][gho] - b[..., :3][gho]).mean()) if gho.sum() else 0.0,
        ))
    return np.array(out)


def interp_uniformity(name):
    """Frame-to-frame motion, split into what is seen and what is not.

    The visible column is the animation's pace: a cross-fade should hand out
    equal steps, so peak/mean near 1 means an even cadence. The ghost column is
    RGB in fully transparent pixels - it must be flat, or the tweens and the
    keyframes disagree in a way that leaks through any renderer that filters
    before it composites."""
    frames, _ = H.anim_frames(name, JITTER_SIZE, True)
    d = _deltas(frames, name in H.INTERP)
    vis, gho = d[:, 0], d[:, 1]
    o = _deltas([frame(name, i, JITTER_SIZE) for i in range(nframes(name))],
                name in H.INTERP)[:, 0]
    return {
        "n": len(frames),
        "visible_peak_over_mean": float(vis.max() / max(vis.mean(), 1e-9)),
        "ghost_rgb": float(gho.max()),
        "visible_mean": float(vis.mean()),
        # Total motion over the cycle, not per step: the remaster runs 27 frames
        # where the author drew 9, so each of its steps is a third the size
        # while the sweep covers the same ground. Compared against the same
        # pipeline's own keyframes, which is the path interpolation is meant to
        # follow: if the interpolated cycle covers less ground than they do,
        # the sweep has been damped. An even cadence is the goal, not a symptom
        # - gating a low peak/mean as "dead" was the wrong test.
        "cycle_motion": float(vis.sum()),
        "cycle_motion_keys": float(o.sum()),
    }


def _interior(a):
    al, lum = a[..., 3], a[..., :3].mean(-1)
    return al, lum


def _prominence(seg, k):
    """How far a cross-section has to climb out of seg[k] to reach anything
    lower - the standard reading of how much of a dip a minimum is.

    What it is for: telling a fold from a wobble in flat glass. The test it
    replaces compared the whole window's range against _FOLD_DEPTH, and the
    window has the lit sheet in it, so a 78-level range cleared it on every row
    whether or not there was a fold in that row. On UpArrow at 256 two rows out
    of forty came back 1.6 logical units off the line, on a 0.7-level dimple in
    the cream sheet that the row-wide minimum happened to land on; the fold's
    own dip, where it is still readable, is six levels and up. Same constant,
    now read off the dip rather than off the sheet beside it."""
    left = seg[:k].max() if k else seg[k]
    right = seg[k + 1:].max() if k + 1 < len(seg) else seg[k]
    return float(min(left, right) - seg[k])


_OVERLAY_SAT = 0.35        # absolute saturation floor an overlay has to clear
_OVERLAY_RATIO = 8.0       # ...and how many times the glass's own saturation

# A gradient fallback used to run here: where the prominence test said there is
# no fold in this row, it took the steepest edge in the window instead and wrote
# that into the track. It is out, on three readings.
#
# It defeats the metric it feeds. `fold_gap` is the longest run of *unresolved*
# rows (see `_longest_run` and `fold_profile`), so filling the rows the
# prominence test rejected is exactly the case a broken fold reads as a
# continuous one. `_fold_track`'s own docstring below, PLAN.md 36 and the
# standing rule "a silent zero is worse than no measurement" all say the same
# thing: a row with no fold in it has no business being measured.
#
# It was also half a sample out. It returned `k` indexed into `np.diff(seg)`,
# where `grad[k] = seg[k+1] - seg[k]` puts the edge at `k + 0.5`, while every
# other branch here returns an index into `seg` itself.
#
# And the leash meant to contain it was mis-scaled. It read `5.0 * L` with
# `L = size / 256.0`, documented as "~80px at 512px": it is 10px, eight times
# tighter than claimed, and tighter than `hybrid._FOLD_CAP` (1.2 logical units)
# allows the render's own fold to sit from the chord, so it rejected honest rows.
#
# If a fallback is ever wanted again it needs a selftest that plants a fold-free
# stretch and asserts `fold_gap` survives it.


def _without_overlay(a, al, lum):
    """Luma with a coloured overlay's pixels put out of reach of the argmin.

    NO is an arrow with a red forbidden sign drawn over it, and the sign is dark
    in luma, so on the frames where it has grown over the fold the darkest pixel
    in the search window is the sign's edge, not the crease. Measured on frame 3,
    the last one whose fold `CURSOR_TOPOLOGY` declares: saturation along the
    whole track reads 1.00 against 0.01 for the glass beside it, and the numbers
    it produced - jag 193, luma_step 68 - are that edge, not a fold.

    The test is relative so it cannot touch the cursors that are saturated all
    over. Wait, UpArrow and AppStarting read a median saturation of 0.40..0.56
    inside the silhouette, so their threshold lands above 1.0 and nothing is
    excluded; NO's fold frames read 0.006..0.015, so theirs is the 0.35 floor and
    only the sign clears it. Every grey cursor has no pixel over the floor at
    all."""
    rgb = a[..., :3]
    mx, mn = rgb.max(-1), rgb.min(-1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    inside = al > 0.5
    if inside.sum() < 50:
        return lum
    thr = max(_OVERLAY_SAT, _OVERLAY_RATIO * float(np.median(sat[inside])))
    overlay = sat > thr
    if not overlay.any():
        return lum
    return np.where(overlay, np.inf, lum)


def _fold_track(name, idx, size, ref=None, win=None, get=frame, strict=True):
    """Column of the fold (darkest interior pixel) per row.

    A plain row-wide argmin is bimodal - the wedge has a dark seam and a dark
    outer flank, and which of them wins flips between frames, so the raw track
    reports 100px jumps that no eye ever sees. Given a reference track the
    search is confined to a window around it, which pins the metric to one and
    the same feature in every frame.

    `strict` is the prominence test below, and it is off for the pass that only
    locates the run. That pass reduces the whole track to one median offset, and
    a median is not the thing a stray row hurts; what it does need is to stay
    the same anchor it has always been, so that a change to the reading is a
    change to the reading and not a window that has quietly moved."""
    a = get(name, idx, size)
    al, lum = _interior(a)
    lum = _without_overlay(a, al, lum)
    track = np.full(size, np.nan)
    # The rim insets and the width a row must have are logical, not pixel:
    # written as the constants 6, 5 and 16 they were a quarter of the cursor at
    # 32px, so every row was rejected and the track came back empty at exactly
    # the sizes the multiscale sweep exists to look at. Scaled from 256, where
    # they were tuned, they reproduce the old numbers there exactly.
    L = size / 256.0
    ins_lo, ins_hi = max(1, round(6 * L)), max(1, round(5 * L))
    min_on, min_span = max(6, round(16 * L)), max(3, round(6 * L))
    for y in range(size):
        on = np.nonzero(al[y] > _SOLID_FRAC * al.max())[0]
        if len(on) < min_on:
            continue
        lo, hi = on.min() + ins_lo, on.max() - ins_hi
        if ref is not None:
            if np.isnan(ref[y]):
                continue
            lo = max(lo, int(ref[y] - win))
            hi = min(hi, int(ref[y] + win) + 1)

        # A row whose window has collapsed used to have its inset halved so it
        # could be measured anyway. That is the window moving to suit the row it
        # is measuring, which is rule 1 ("any quantity fitted to the thing being
        # measured") applied to the instrument instead of the render. It was
        # added for one row at the tail junction, where the silhouette narrows
        # from 207px to 196px and there genuinely is no room left between the
        # rim insets - and where the honest answer is that this row carries no
        # readable fold, which `min_span` below already says.
        if hi - lo < min_span:
            continue
        seg = lum[y, lo:hi]
        # A window that is all overlay has no glass left to read a fold in, and
        # an infinity anywhere in `seg` would defeat both depth tests below.
        if not np.isfinite(seg).all():
            continue

        k = int(np.argmin(seg))
        if not np.isfinite(seg[k]):
            continue
        # A row with no fold in it has no business being measured: where the
        # glass is flat the minimum lands on whichever end of the search window
        # is darker and flips between the two as the sweep passes, which reads
        # as an 8px step in a cursor whose outline never moved. The row is
        # dropped rather than re-pointed at the next candidate along: the deepest
        # dip in the window is often the rim grazing it, and picking that one
        # walks the track off the fold at exactly the rows near the tail cutout
        # where the old rule was right to give up.
        if k in (0, len(seg) - 1):
            continue

        prom = _prominence(seg, k)
        prom_ok = prom >= _FOLD_DEPTH if strict else seg.max() - seg.min() >= _FOLD_DEPTH
        if not prom_ok:
            continue

        # Subpixel refinement of the darkest pixel
        a0, b0, c0 = seg[k - 1], seg[k], seg[k + 1]
        den = a0 - 2 * b0 + c0
        k = k + (0.5 * (a0 - c0) / den if abs(den) > 1e-6 else 0.0)

        # Past the tail vertex the crease ends and a darker facet begins beside
        # it, and the window is still wide enough to hold both - so the argmin
        # walks off the fold onto the neighbour. Looked at on Arrow, Help and
        # Hand: two to six rows at the very end of each track, always at the
        # vertex, always on a different feature, and 40 to 90 levels darker than
        # the fold they left.
        #
        # The render cannot put its fold there. H._FOLD_CAP is the most the
        # renderer may displace the crease from the chord, so a reading further
        # out than that is not the render's fold whatever it is, and the cap is
        # taken from the render rather than restated here: a number tuned in
        # this file would be a number fitted to the rows it is judging.
        #
        # This is not the leash removed in the Phase 0 cleanup. That one read
        # `5.0 * L` with L = size/256, so it was ten pixels at 512 while its
        # documentation claimed eighty, and it was tighter than the render's own
        # cap - it clipped honest readings. This one is the render's cap in the
        # render's units. Measured over all 92 tracks the split is clean:
        # everything the fold does sits under 0.25 logical units of the chord,
        # every excursion is 1.07 or beyond, and nothing lands between.
        if ref is not None and abs((lo + k) - ref[y]) > H._FOLD_CAP * size / 32.0:
            continue
        track[y] = lo + k
    return track


def inner_jitter(name):
    """How far the fold line moves between frames, in pixels at 256.

    Only meaningful where the silhouette itself is frozen (AppStarting, Hand,
    Wait): there the outline is one static polygon in every frame, so any
    movement of the fold is the shading wobbling, not the cursor animating.

    Anchored on the chord, the same line fold_profile anchors on, plus one
    offset for the whole cycle. It used to anchor on the median of the
    unanchored tracks, and those are not one feature: measured across the nine
    frames at 256, a row's unanchored track spans 143px on Wait and 151px on
    AppStarting, because it hops between the fold, the rim and the flank. A
    median over three features is a fourth thing, and which rows survived the
    windowed pass afterwards was decided by that. The offset is one number per
    cycle, not per frame - a per-frame anchor would follow the very movement
    this is here to measure."""
    n = nframes(name)
    ref = _chord_ref(name, 0, JITTER_SIZE)
    if ref is None:
        return None
    wide = _JAG_BAND * JITTER_SIZE / 32.0
    with warnings.catch_warnings():        # rows outside the cursor are all-NaN
        warnings.simplefilter("ignore", RuntimeWarning)
        off = np.nanmedian([_fold_track(name, i, JITTER_SIZE, ref, wide, strict=False) - ref
                            for i in range(n)])
    if np.isfinite(off):
        ref = ref + off
    win = 0.5 * JITTER_SIZE / 32.0
    T = np.array([_fold_track(name, i, JITTER_SIZE, ref, win) for i in range(n)])
    ok = ~np.isnan(T).any(0)
    if ok.sum() < 10:
        return None
    step = np.abs(np.diff(T[:, ok], axis=0))
    return {
        "rows": int(ok.sum()),
        "mean": float(step.mean()),
        "p95": float(np.percentile(step, 95)),
        "max": float(step.max()),
    }


def _longest_run(flags):
    if not flags.any():
        return 0
    d = np.diff(np.concatenate(([0], flags.astype(np.int8), [0])))
    return int((np.nonzero(d == -1)[0] - np.nonzero(d == 1)[0]).max())


def _chord_ref(name, idx, size):
    """Pixel column of the fold's chord per row, or None if the cursor has none.

    fold_profile needs an anchor that cannot follow the defect it is looking
    for. An unanchored _fold_track is bimodal by its own docstring - the wedge
    has a dark seam and a dark outer flank and the argmin flips between them -
    which came out as a fold jumping seventeen logical units between adjacent
    rows on Wait, and as Cross, which has no fold at all, reporting one.
    inner_jitter anchors on the cycle's median track, which a static cursor
    does not have. The chord hybrid already derives from the outline does not
    move at all, and it is the same line the shading is built on.

    A `- 0.5 * L` used to be subtracted here. Its commit message named Arrow but
    the code was unconditional, so it moved the anchor for `fold_wander`,
    `fold_jag`, `fold_gap` and `inner_jitter` on all sixteen at once - eight
    pixels at 512, and leftward, the opposite direction from the master's own
    measured offset. Half a *pixel* is `- 0.5`; `- 0.5 * L` is half a logical
    unit. Neither belongs here: `_fold_track` returns `lo + k`, a pixel index
    into the same grid this builds, so the two conventions already agree."""
    ch = H._fold_chord(name, idx)
    if ch is None:
        return None
    (x0, y0), (x1, y1) = ch
    if abs(y1 - y0) < 1e-6:
        return None
    L = size / 32.0
    ys = (np.arange(size) + 0.5) / L
    ref = np.full(size, np.nan)
    m = (ys >= min(y0, y1)) & (ys <= max(y0, y1))
    ref[m] = (x0 + (x1 - x0) * (ys[m] - y0) / (y1 - y0)) * L
    return ref


def fold_profile(name, idx, size, get=frame):
    """Whether the fold reads as one continuous line at one size.

    Three defects the eye catches and no existing metric names: the line breaks
    into pieces, its brightness pulses along its length, and its edge steps.
    All three are readings of the track _fold_track already finds, so nothing
    new is searched for here.

    inner_jitter asks whether the line moves between frames. This asks whether
    it is a line at all in the frame it is in, which is the defect PLAN.md
    describes as a dark band "broken into pieces with staircase edges"."""
    L = size / 32.0
    ref = _chord_ref(name, idx, size)
    if ref is None:
        return None
    win = _JAG_BAND * L
    # Two passes. The chord comes from the outline and the crease it stands for
    # is allowed to sit a little off it; with the window centred on the chord
    # the rim falls inside it on some rows and wins the argmin there, which
    # reads as the line jumping. Re-centring on where the first pass found the
    # fold pins the search to one feature, the way inner_jitter pins it across
    # frames.
    #
    # Measured on Arrow, whose fold is the same line at every size: 0.001
    # logical units of curvature at 128, 0.016 at 384, 0.035 at 512 - and 0.941
    # at 256, from four rows out of forty-one. A defect that exists at one rung
    # and at none of its neighbours is the reading, not the render.
    t = _fold_track(name, idx, size, ref, win, get=get, strict=False)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        off = np.nanmedian(t - ref)
    t = _fold_track(name, idx, size, ref + (off if np.isfinite(off) else 0.0), win, get=get)
    rows = np.nonzero(~np.isnan(t))[0]
    if len(rows) < _FOLD_ROWS:
        return None
    a = get(name, idx, size)
    lum = a[..., :3].mean(-1)
    cols = np.clip(np.round(t[rows]).astype(int), 0, size - 1)
    v = lum[rows, cols]

    # Gaps count only between the fold's own first and last row: the rows above
    # and below it are not a broken line, they are where the fold ends.
    gap = _longest_run(np.isnan(t[rows[0]:rows[-1] + 1])) / L

    # Steps along the line, not its spread. A fold is legitimately brighter at
    # one end than the other, and grading that spread marks a clean gradient as
    # a defect; a break shows up as a jump between neighbouring rows instead.
    adj = np.diff(rows) == 1
    step = np.abs(np.diff(v))[adj] if adj.any() else np.zeros(1)

    # Wander is the track's curvature, not its slope. The sideways step per row
    # is the obvious reading and it is the wrong one: Arrow's crease runs at
    # 45 degrees, so a perfect fold steps a whole pixel every row and scores as
    # high as a broken one. The second difference is zero for a straight line
    # at any angle, and _fold_track's sub-pixel fit means a clean fold gives a
    # smooth track rather than a rasterised staircase, so zero is reachable.
    if len(rows) > 2:
        keep = adj[:-1] & adj[1:]              # both steps between real neighbours
        wan = np.abs(np.diff(t[rows], 2))[keep] / L if keep.any() else np.zeros(1)
    else:
        wan = np.zeros(1)

    # Jag is how much the fold's cross-section changes shape from one row to
    # the next, sampled at fixed offsets from the track so the line's own path
    # is not counted twice - wander already says where the fold is.
    #
    # The obvious reading, the sharpest step across the section, does not work:
    # a clean fold's own edge is one pixel wide at every size and scores as
    # high as a staircase does. What separates them is that a clean section
    # keeps its shape down the line while a staircase flips between two.
    b = max(1, int(round(_JAG_BAND * L)))
    off = np.arange(-b, b + 1)
    prof = np.array([lum[y, np.clip(c + off, 0, size - 1)] for y, c in zip(rows, cols)])
    jag = np.abs(np.diff(prof, axis=0)).max(1)[adj] if adj.any() else np.zeros(1)
    return {
        "rows": int(len(rows)),
        "gap": float(gap),
        "luma_step": float(np.percentile(step, 95)),
        "wander": float(np.percentile(wan, 95)),
        "jag": float(np.percentile(jag, 95)),
    }


def validate_multiscale(name, sizes=VALIDATE_SIZES):
    """Every geometric defect, looked for at every size, on every frame.

    A cursor is not a 512px picture. Windows asks for 15 fixed sizes and Linux
    for whatever the compositor wants, and a seam that only opens at 96 is
    still a seam. Frames are swept too, not just frame 0: Handwriting's pencil
    frames are the ones that were broken, and a frame-0 check never saw them.

    Which sizes a fold can be read at is recorded rather than assumed. Below
    128 there is no cross-section to read - the fold is one pixel wide and the
    rows either side of it are rim - so the sweep reports the sizes it resolved
    at and gate() fails a cursor whose fold was never measured anywhere. A
    metric that quietly returns nothing is worse than no metric: that is
    exactly how the fold measurement sat broken through 36 attempts."""
    per = {}
    worst = {k: 0.0 for k in ("gap", "luma_step", "wander", "jag", "tip")}
    resolved = []
    for s in sizes:
        rows = []
        for idx in range(nframes(name)):
            p = fold_profile(name, idx, s)
            if p is None:
                continue
            rows.append((idx, p))
            for k in ("gap", "luma_step", "wander", "jag"):
                worst[k] = max(worst[k], p[k])
        if rows:
            resolved.append(s)
        tip, _ = tip_convergence(name, size=s)
        worst["tip"] = max(worst["tip"], tip)
        per[str(s)] = {"tip": tip, "frames": {str(i): p for i, p in rows}}
    return {"worst": worst, "resolved": resolved, "per_size": per}


def _fold_band(name, size):
    """Mask of the band the fold runs through, from the chord rather than the
    image. One fixed region for the whole cycle: a band cut per frame would
    follow whatever it is meant to be measuring."""
    ref = _chord_ref(name, 0, size)
    m = np.zeros((size, size), bool)
    if ref is None:
        return m
    b = max(1, int(round(_JAG_BAND * size / 32.0)))
    for y in range(size):
        if not np.isnan(ref[y]):
            c = int(round(ref[y]))
            m[y, max(0, c - b):min(size, c + b + 1)] = True
    return m


def _smoothness(name, get, size=JITTER_SIZE):
    """Frame-to-frame step over cycle amplitude, per zone, normalised by n.

    Geometry that is frozen can still flicker: when the sheen jumps between
    frames the eye reads it as the line itself twitching, and no metric here
    caught that - inner_jitter watches where the fold is, not how its light
    behaves.

    The ratio is deliberately scale-free in amplitude, so a strong sweep and a
    weak one score the same if both are smooth. It is not free of frame count:
    a cursor interpolated to 27 frames takes a third of the step a 9-frame one
    takes over the same ground. Scaled by n/2pi the ideal - a sinusoid sampled
    n times - reads 1.0 at any n, and above that the sweep hurries and stalls.

    Composited onto mid grey first. With a static silhouette the background
    cancels out of both halves of the ratio, but the morphs change alpha as
    they redraw, and there the uncomposited reading counts colour under pixels
    that are not on screen."""
    n = nframes(name)
    if n < 3:
        return {}
    fr = [get(name, i, size) for i in range(n)]
    al = np.array([f[..., 3] for f in fr]) / 255.0
    lum = np.array([f[..., :3].mean(-1) for f in fr])
    comp = lum * al + 128.0 * (1.0 - al)
    live = (al > _SOLID_FRAC * al.max(axis=(1, 2), keepdims=True)).all(0)
    cyclic = name in H.INTERP

    body = _density_points(name).astype(bool)
    if body.shape[0] != size:
        i = np.arange(size) * body.shape[0] // size          # nearest, no resampler
        body = body[np.ix_(i, i)]
    zones = {"body": body, "fold": _fold_band(name, size)}

    out = {}
    for label, mask in zones.items():
        m = mask & live
        if m.sum() < 32:
            continue
        x = comp[:, m]
        d = np.abs(np.diff(x, axis=0, append=x[:1]) if cyclic else np.diff(x, axis=0))
        den = np.abs(x - x.mean(0)).mean(0)
        ok = den > 1e-6
        if ok.sum() < 32:
            continue
        out[label] = float((d.mean(0)[ok] / den[ok]).mean() * n / (2.0 * np.pi))
    return out


def temporal_smoothness(name):
    r = {k: v for k, v in _smoothness(name, frame).items()}
    r.update({k + "_orig": v for k, v in _smoothness(name, orig_frame).items()})
    return r


_TIP_DISC = 2.0            # logical units around a corner the sweep is read in


def tip_sheen(name, get=frame):
    """Whether the sweep reaches the points, and how steady it is when it does.

    A cursor whose sheen stops short of its tips looks dead at exactly the part
    of it the eye is on. Nothing here saw that: the shading near a corner was
    frozen to the cycle mean over a disc of six logical units, and every metric
    in this file read the result as perfectly smooth, because a still image is.

    amp    the cycle's own swing inside the disc, in luma levels after
           compositing. Frozen tips measure 0.07 against the author's 10.65.
    wobble frame-to-frame travel of the lit part's centre inside the same disc,
           in logical units. This is what freezing the tips was buying, and it
           is what has to be checked before unfreezing them.
    lean   where that centre sits relative to the apex, positive to the right.
           Reported because it is largely the author's own: he draws the arrow's
           point leaning +0.79 and the remaster reads +0.92."""
    n = nframes(name)
    if n < 3 or name not in H.INTERP:
        return {}
    size = JITTER_SIZE
    fr = [get(name, i, size) for i in range(n)]
    al = np.array([f[..., 3] for f in fr]) / 255.0
    lum = np.array([f[..., :3].mean(-1) for f in fr])
    comp = lum * al + 128.0 * (1.0 - al)
    mean = comp.mean(0)
    L = size / 32.0
    ys, xs = np.mgrid[0:size, 0:size]
    amps, wobs, leans = [], [], []
    for (px, py), _ in corners(name):
        d = np.hypot(xs - px * L, ys - py * L) / L
        m = (d < _TIP_DISC) & (al.min(0) > 0.15)
        if m.sum() < 12:
            continue
        amps.append(float(np.abs(comp[:, m] - mean[m]).mean()))
        cx = []
        for f in range(n):
            w = np.clip(comp[f][m] - mean[m], 0.0, None)
            if w.sum() > 1e-6:
                cx.append(float((w * (xs[m] - px * L)).sum() / w.sum() / L))
        if cx:
            wobs.append(float(np.std(cx)))
            leans.append(float(np.mean(cx)))
    if not amps:
        return {}
    # Worst corner, not the average: one dead point is a dead point.
    return {"amp": min(amps), "wobble": max(wobs) if wobs else 0.0,
            "lean": max(leans, key=abs) if leans else 0.0}


def corners(name, idx=0):
    """Traced corner vertices with their outward direction, in logical units.

    The eight compass extents are the right tool for scale drift - they pin the
    silhouette's bounding shape - but they are the wrong one for the points:
    Arrow's BR extent lands in the concave notch where there is no cursor at
    all, which is how a well-formed point scored a flat zero. The traced
    outline already flags its real corners, so those are what gets measured."""
    out = []
    for poly in H.C.TRACED[name]["frames"][idx]["polys"]:
        pts = np.array([(p[0], p[1]) for p in poly], dtype=np.float64)
        m = len(pts)
        if m < 3:
            continue
        nxt = np.roll(pts, -1, axis=0)                               # sign = winding
        area = float((pts[:, 0] * nxt[:, 1] - pts[:, 1] * nxt[:, 0]).sum())
        for i, p in enumerate(poly):
            if not p[2]:
                continue
            v = pts[i]
            a, b = pts[(i - 1) % m] - v, pts[(i + 1) % m] - v
            na, nb = np.hypot(*a), np.hypot(*b)
            if na < 1e-6 or nb < 1e-6:
                continue
            a, b = a / na, b / nb
            # Convex and sharp only. Concave notches and the blunt joints where
            # two edges merely bend have no point to converge, and grading them
            # measures how thin the cursor is rather than how well it is drawn.
            if (a[0] * b[1] - a[1] * b[0]) * area > 0 or float(a @ b) < _TIP_COS:
                continue
            bis = -(a + b)
            n = np.hypot(*bis)
            if n < 1e-6:
                continue
            out.append(((p[0], p[1]), tuple(bis / n)))
    return out


def tip_convergence(name, size=384, get=frame):
    """Logical distance from a traced point to where the fold reaches it.

    The outer contour is vector-crisp, but the fold lives in the AI colour and
    has nothing holding it: it fades out short of the apex and leaves the point
    blunt on the inside while looking sharp on the outside. Walking inward from
    the apex, the first place the wedge still shows a real light/dark split is
    where the fold actually begins - that gap is the defect.

    Sampled on a line across the wedge, not in a square window around the
    centre: the Size* arrowheads are a couple of logical units thick, so a
    window wide enough to hold a fold is mostly background there and the test
    ends up measuring how thin the cursor is."""
    a = get(name, 0, size)
    al, lum = _interior(a)
    L = size / 32.0
    lim = _SOLID_FRAC * al.max()
    worst = 0.0
    per = {}
    # The cross-section is sampled with numpy rather than a Python loop over
    # its 76 points: at six calls per cursor and 58 steps inward from each
    # point, the loop version was 39 of the 43 seconds a cursor took to measure
    # and it was most of what made the gate too slow to put in CI.
    ss = np.arange(-3.0, 3.001, 0.08)
    for (px, py), d in corners(name):
        ax, ay = px * L, py * L
        nx, ny = -d[1], d[0]
        found = None
        for t in np.arange(0.2, 6.0, 0.1):
            cx, cy = ax - d[0] * t * L, ay - d[1] * t * L
            x = np.rint(cx + nx * ss * L).astype(int)     # across the wedge
            y = np.rint(cy + ny * ss * L).astype(int)
            on = (x >= 0) & (x < size) & (y >= 0) & (y < size)
            x, y = x[on], y[on]
            vals = lum[y, x][al[y, x] > lim] if len(x) else np.zeros(0)
            if len(vals) < 5:
                continue
            # A dip, not a range: a fold is dark with lighter glass on both
            # sides of it. Plain max-minus-min also fires on a monotone ramp,
            # which is what the Lanczos-stretched 32px reference is made of
            # everywhere, so it "converged" on cursors that have no fold there
            # at all while the crisp remaster was marked short.
            k = int(np.argmin(vals))
            if not 0 < k < len(vals) - 1:
                continue
            if min(max(vals[:k + 1]), max(vals[k:])) - vals[k] > _TIP_SPLIT:
                found = t
                break
        if found is None:
            continue
        per[f"{px:.1f},{py:.1f}"] = float(found)
        worst = max(worst, found)
    return worst, per


def morph_health(name, get=frame):
    """Whether a shape-changing animation stays coherent frame to frame.

    Handwriting and NO genuinely redraw themselves, so area is expected to
    move; what is not expected is a frame that shares little with its
    neighbours (low IoU means the silhouette broke rather than morphed) or a
    single step several times larger than the rest."""
    n = nframes(name)
    # Measured at the size the author drew at. The remaster renders a vector
    # edge at any resolution while the 2006 art only exists at 32, so at 128 the
    # reference is a Lanczos stretch whose blur pads every silhouette and lifts
    # its overlap - it scored the author's own pencil frames 0.52 where its
    # native frames give 0.44. At 32 both are the same kind of image.
    ms = [get(name, i, _MORPH_SIZE)[..., 3] > 0.5 * get(name, i, _MORPH_SIZE)[..., 3].max()
          for i in range(n)]
    iou = [float((ms[i] & ms[i - 1]).sum()) / max(1, (ms[i] | ms[i - 1]).sum())
           for i in range(1, n)]
    d = _deltas([get(name, i, JITTER_SIZE) for i in range(n)], False)[:, 0]
    area = [int(m.sum()) for m in ms]
    return {
        "iou_min": float(min(iou)),
        "iou_mean": float(np.mean(iou)),
        "area_ratio": float(max(area) / max(1, min(area))),
        "peak_over_mean": float(d.max() / max(d.mean(), 1e-9)),
    }


_BACKGROUNDS = {"white": 255.0, "grey": 128.0, "black": 0.0}


def tip_contrast(name, size=256, get=frame):
    """Point contrast measured after compositing, not on the raw RGBA.

    Straight RGBA overstates a translucent point: the pixels can be dark while
    the alpha under them is low enough that nothing of it survives on the
    actual desktop. Compositing first is the only reading that matches what is
    seen, and the worst background is the one that counts."""
    a = get(name, 0, size)
    al = a[..., 3] / 255.0
    lum = a[..., :3].mean(-1)
    L = size / 32.0
    ys, xs = np.mgrid[0:size, 0:size]
    out = {}
    for (px, py), _ in corners(name):
        ax, ay = px * L, py * L
        near = np.hypot(xs - ax, ys - ay) < 1.5 * L
        if near.sum() < 4:
            continue
        lbl = f"{px:.1f},{py:.1f}"
        worst = 1.0
        for bg_name, bg in _BACKGROUNDS.items():
            comp = lum * al + bg * (1.0 - al)
            worst = min(worst, float(np.abs(comp[near] - bg).max() / 255.0))
        out[lbl] = worst
    return (min(out.values()) if out else 0.0), out


_RIM_SIZE = 512       # where the rim is measured. The band this looks for is a
                      # fifth of a logical unit wide; at 256 that is 1.6px and at
                      # 128 it is under one, so a clean reading needs the top
                      # rung. LADDER stops at 384, so this asks for its own size
                      # rather than riding the sweep.
_RIM_DEPTH = 2.5      # logical units inward the cross-section is read over
_RIM_STEP = 0.05      # ...and the spacing of its samples
_RIM_STATION = 0.25   # logical units of arc between cross-sections
_RIM_ARC = 3.0        # half-width, in logical units of arc, of the median that
                      # rejects the fold. The band runs ALONG the contour at a
                      # fixed depth; the fold CROSSES it and so occupies only a
                      # short stretch of arc at any one depth. A median over an
                      # arc window therefore keeps the first and drops the
                      # second, which is the separation every previous attempt
                      # lacked: a max filter, a min filter and a smoothed floor
                      # all work in the picture's own axes, where the two
                      # features overlap, and that is what _fold_keepout exists
                      # to paper over.
_RIM_DIP = 6.0        # levels of prominence a dip has to carry to be counted.
                      # Same figure _FOLD_DEPTH uses for the fold's own dip.
_RIM_BG = 128.0       # the ground it is composited on. Glass is translucent;
                      # raw RGBA reads a rim that nothing on a desktop can see.


def _poly_stations(poly, step=_RIM_STATION, corner_reach=1.0):
    """Stations along one smoothed polygon, each flagged if a traced corner
    lies within `corner_reach` logical units of arc.

    The flag rides on the traced vertex (p[2]), set in trace.py from the dense
    boundary chain before simplification - so it is independent of the
    simplifier whose noise this file is measuring."""
    pts = [np.array(p[:2], dtype=np.float64)
           for p in H.C.smooth([tuple(p) for p in poly])]
    n = len(pts)
    if n < 3:
        return []
    flags = [bool(p[2]) if len(p) > 2 else False for p in poly]
    arr = np.array(pts)
    nxt = np.roll(arr, -1, axis=0)
    area = float((arr[:, 0] * nxt[:, 1] - arr[:, 1] * nxt[:, 0]).sum())
    sgn = -1.0 if area > 0 else 1.0
    out, acc = [], 0.0
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        seg = float(np.hypot(*(b - a)))
        if seg < 1e-9:
            continue
        t = (b - a) / seg
        nrm = np.array([-t[1], t[0]]) * sgn
        s = step - acc
        while s < seg:
            near = ((flags[i] and s < corner_reach)
                    or (flags[(i + 1) % n] and seg - s < corner_reach))
            out.append((a + t * s, nrm, near))
            s += step
        acc = (acc + seg) % step
    return out


def _outline_stations(name, idx=0, step=_RIM_STATION):
    """Points and inward normals along the *rendered* outline, every `step`
    logical units of arc.

    Walks C.smooth's output, which is the polygon _mask_geom rasterises, so a
    station sits where the contour actually is. Deliberately not derived from
    H._edge_distance: that field is measured by a different route, and keeping
    these independent means each one can catch the other being wrong."""
    out = []
    for poly in H.C.TRACED[name]["frames"][idx]["polys"]:
        pts = [np.array(p[:2], dtype=np.float64)
               for p in H.C.smooth([tuple(p) for p in poly])]
        n = len(pts)
        if n < 3:
            continue
        nxt = np.roll(np.array(pts), -1, axis=0)
        arr = np.array(pts)
        area = float((arr[:, 0] * nxt[:, 1] - arr[:, 1] * nxt[:, 0]).sum())
        sgn = -1.0 if area > 0 else 1.0          # inward, whichever way it winds
        acc = 0.0
        for i in range(n):
            a, b = pts[i], pts[(i + 1) % n]
            seg = float(np.hypot(*(b - a)))
            if seg < 1e-9:
                continue
            t = (b - a) / seg
            nrm = np.array([-t[1], t[0]]) * sgn
            s = step - acc
            while s < seg:
                out.append((a + t * s, nrm))
                s += step
            acc = (acc + seg) % step
    return out


def _sample(field, x, y):
    """Bilinear read of a 2-D array at float pixel coordinates."""
    x = np.clip(x, 0, field.shape[1] - 1.001)
    y = np.clip(y, 0, field.shape[0] - 1.001)
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    fx, fy = x - x0, y - y0
    return (field[y0, x0] * (1 - fx) * (1 - fy) + field[y0, x0 + 1] * fx * (1 - fy)
            + field[y0 + 1, x0] * (1 - fx) * fy + field[y0 + 1, x0 + 1] * fx * fy)


def _rim_profiles(a, mask, stations, size):
    """Luma from the contour inward at every station, composited on _RIM_BG.

    NaN for a station whose ray leaves the silhouette inside _RIM_DEPTH - a
    thin spike has no cross-section to read and must not be counted as clean.

    Which way is inward is settled per station by probing the mask rather than
    by the polygon's winding: an island runs the other way round from the body
    it sits in, and one flipped normal reads the background as a rim.

    The containment test starts past the rasteriser's own edge ramp, whose
    width is a device pixel and therefore _RAMP * 32 / size logical units - at
    512 that is a tenth of a unit and at 32 it is a unit and a half. Testing
    from a fixed logical depth instead rejects every station at 32px, which is
    where the author's own reading is taken, so the target would never be
    measurable at all."""
    al = a[..., 3] / 255.0
    lum = a[..., :3].mean(-1) * al + _RIM_BG * (1.0 - al)
    us = np.arange(0.0, _RIM_DEPTH + 1e-9, _RIM_STEP)
    L = size / 32.0
    ramp = max(2, int(round(1.5 / L / _RIM_STEP)))     # samples inside the ramp
    prof = np.full((len(stations), len(us)), np.nan)
    for i, (p, nrm) in enumerate(stations):
        probe = [float(_sample(mask, np.array([(p[0] + s * nrm[0] * 0.5) * L - 0.5]),
                               np.array([(p[1] + s * nrm[1] * 0.5) * L - 0.5]))[0])
                 for s in (1.0, -1.0)]
        n = nrm if probe[0] >= probe[1] else -nrm
        px = (p[0] + n[0] * us) * L - 0.5
        py = (p[1] + n[1] * us) * L - 0.5
        if _sample(mask, px, py)[ramp:].min() < 250.0:
            continue
        prof[i] = _sample(lum, px, py)
    return prof


def _rim_dips(prof):
    """Interior local minima carrying at least _RIM_DIP of prominence."""
    n = 0
    for k in range(1, len(prof) - 1):
        if prof[k] <= prof[k - 1] and prof[k] < prof[k + 1]:
            if _prominence(prof, k) >= _RIM_DIP:
                n += 1
    return n


def rim_layers(name, idx=0, size=_RIM_SIZE, get=frame):
    """How much of the contour carries a dark layer the author never drew.

    His rim is one soft falloff. Measured on his own 32px art with this same
    code, along the same normals, Arrow and UpArrow both come back with an
    interior dip on 0% of their stations - the cross-section from the outline
    inward only ever descends. Ours, before this landed, carried at least one
    extra dip on 81-100% of stations on every master-shaded cursor, and on
    17-20% of the seven that draw their shading from geometry instead
    (_SYNTH_BEVEL). That gap is the defect, and it is the reason this is a
    ratio against him rather than an absolute: the shape of his falloff is a
    property of the drawing, the count of layers in it is not.

    The arc median is what makes it readable. Without it the fold, which
    crosses the rim band at an angle, plants a dip of its own on the stations
    it passes through and the number stops being about the rim at all - the
    same confusion `_fold_keepout` was written to work around in the render.

    Depth is in logical units, so the reading does not move with size; it is
    taken at _RIM_SIZE because the band is too narrow to resolve lower down."""
    stations = _outline_stations(name, idx)
    if not stations:
        return None
    prof = _rim_profiles(get(name, idx, size), H._mask(name, idx, size),
                         stations, size)
    ok = np.nonzero(~np.isnan(prof[:, 0]))[0]
    if len(ok) < 8:
        return None
    w = max(1, int(round(_RIM_ARC / _RIM_STATION)))
    counts, second = [], []
    for i in ok:
        lo, hi = max(0, i - w), min(len(prof), i + w + 1)
        win = prof[lo:hi]
        win = win[~np.isnan(win[:, 0])]
        if len(win) < 5:
            continue
        med = np.median(win, axis=0)
        counts.append(_rim_dips(med))
        if counts[-1]:
            k = min((j for j in range(1, len(med) - 1)
                     if med[j] <= med[j - 1] and med[j] < med[j + 1]
                     and _prominence(med, j) >= _RIM_DIP), default=None)
            if k is not None:
                second.append(_prominence(med, k))
    if not counts:
        return None
    c = np.array(counts, dtype=np.float64)
    return {"share": float((c > 0).mean()), "per_station": float(c.mean()),
            "depth": float(np.mean(second)) if second else 0.0,
            "stations": int(len(c))}


def rim_layers_author(name, idx=0):
    """The same reading on the author's own frame - the target, not a constant.

    On his 32px grid one logical unit is one pixel, so the profile is read at
    his own resolution and nothing is stretched. Comparing against his frame
    upscaled with Lanczos is the invalid comparison that has produced two false
    diagnoses in this repo already (DEAD_ENDS.md); this does not do that."""
    stations = _outline_stations(name, idx)
    if not stations:
        return None
    a = np.asarray(H.original(name, idx), dtype=np.float64)
    prof = _rim_profiles(a, H._mask(name, idx, 32), stations, 32)
    ok = ~np.isnan(prof[:, 0])
    if ok.sum() < 8:
        return None
    c = np.array([_rim_dips(prof[i]) for i in np.nonzero(ok)[0]], dtype=np.float64)
    return {"share": float((c > 0).mean()), "per_station": float(c.mean()),
            "stations": int(len(c))}


_STRAIGHT_WIN = 6.0    # logical units of arc every reading spans.
                       #
                       # Fixed, and that is the whole point. The first version
                       # of this searched for the longest runs of vertices that
                       # stayed within a tolerance of their own chord and
                       # measured those. It made the number depend on which
                       # stretches the search happened to pick: widening the
                       # tolerance let a longer run swallow a wavy short one,
                       # and removing tilt across the longer chord then flattened
                       # the very wander being looked for, so Arrow read 0.153,
                       # 0.183, 0.345 and 0.101 at tolerances of 0.35, 0.5, 0.8
                       # and 1.2. A reading that moves like that with a constant
                       # nobody can derive is not measuring the cursor.
                       #
                       # One fixed window, slid along the whole outline, has no
                       # such freedom: every reading is taken at the same scale,
                       # and the constant only says which scale.
_STRAIGHT_ARC = 1.0    # logical units of curvature that mark a window as a
                       # genuine arc rather than a wavy line.
                       #
                       # Which windows are "meant to be straight" must not be
                       # decided by how straight the traced outline is there,
                       # and that mistake is worth spelling out because the
                       # first version made it: the outline is the defective
                       # thing, so filtering on its straightness threw out
                       # exactly the stretches that carry the defect and every
                       # cursor came back pinned just under the threshold
                       # (0.277..0.305 across the set, whatever the threshold
                       # was set to). The filter and the measurement were the
                       # same quantity.
                       #
                       # A window is taken as meant-straight when it holds no
                       # traced corner. That flag is computed in trace.py from
                       # the dense boundary chain before simplification, so it
                       # does not inherit the simplifier's noise. Round islands
                       # and holes are dropped by name. This constant is only a
                       # backstop for an arc that carries no corner flag at all:
                       # a real one bows well past a unit over six units of arc,
                       # the defect being measured is a third of that.


def _fit_residual(q):
    """Max perpendicular distance from the points to their own best-fit line.

    Total least squares, not a fit of y on x: these are contour points and the
    edge can run in any direction, including vertical."""
    c = q - q.mean(axis=0)
    _, _, vt = np.linalg.svd(c, full_matrices=False)
    nrm = vt[1]
    return np.abs(c @ nrm)


def edge_straight(name, idx=0, size=_RIM_SIZE, get=frame):
    """How far the rendered contour wanders off a line the author drew straight.

    Walks the outline in windows of _STRAIGHT_WIN logical units, keeps the ones
    where the traced outline itself is straight, and measures how far the
    silhouette's own 50% crossing departs from a line fitted through that
    window. Reported in logical units, so it is a property of the vector rather
    than of the rung it was rasterised at.

    It is a vector defect. traced.json stores a straight edge as a run of
    vertices alternating either side of it, and C.smooth turns that sawtooth
    into a slower S-curve rather than removing it - which is why the wander
    grows with size instead of averaging out, and why it is fixed in trace.py
    and not here.

    Arrow, Arrow_Down, UpArrow, Hand, Wait and AppStarting all read the same
    number, and that is right, not a bug worth chasing: in this set they are
    one arrow in six colours, and traced.json stores one 51-vertex polygon for
    all of them. rim_layers separates them because it reads the render; this
    reads the silhouette, and the silhouette is shared."""
    mask = H._mask(name, idx, size)
    L = size / 32.0
    half = max(2, int(round(0.5 * _STRAIGHT_WIN / _RIM_STATION)))
    us = np.linspace(-0.7, 0.7, 141)
    res = []
    for poly in H.C.TRACED[name]["frames"][idx]["polys"]:
        if name in H.C.HELP_ROUND_ISLANDS and len(poly) <= 12:
            continue                                   # a drawn circle, not a line
        if name in getattr(H, "_ROUND_HOLES", set()) and len(poly) <= 16:
            continue
        stations = _poly_stations(poly)
        if len(stations) < 2 * half + 1:
            continue
        hits = []
        for p, nrm, corner in stations:
            v = _sample(mask, (p[0] + nrm[0] * us) * L - 0.5,
                        (p[1] + nrm[1] * us) * L - 0.5)
            cross = np.nonzero((v[:-1] - 127.5) * (v[1:] - 127.5) <= 0)[0]
            best = None
            for k in cross:
                if v[k] == v[k + 1]:
                    continue
                o = us[k] + (us[k + 1] - us[k]) * (v[k] - 127.5) / (v[k] - v[k + 1])
                if best is None or abs(o) < abs(best):  # the crossing at hand
                    best = o
            hits.append(None if best is None else (p + nrm * best, p, corner))
        n = len(hits)
        for i in range(n):
            win = [hits[(i + k) % n] for k in range(-half, half + 1)]
            if any(w is None or w[2] for w in win):     # no corner inside
                continue
            if _fit_residual(np.array([w[1] for w in win])).max() > _STRAIGHT_ARC:
                continue                               # a genuine arc
            res.append(float(_fit_residual(np.array([w[0] for w in win])).max()))
    if not res:
        return None
    r = np.array(res)
    return {"max": float(r.max()), "p95": float(np.percentile(r, 95)),
            "rms": float(np.sqrt((r ** 2).mean())), "windows": int(len(r))}


# Axes the author drew these cursors symmetric about. His own 32px raster is
# only approximately symmetric - Cross reads 16.1 levels against its own mirror
# - so the gate is a ratio against him, never against zero. Cursors that are
# genuinely asymmetric are the control: Help and UpArrow score ~100 on both his
# art and ours, and the gap between the two stays near nil, which is how this
# was confirmed to be measuring a defect rather than an axis.
SYMMETRY = {"Cross": ("lr", "ud", "t"), "SizeAll": ("lr", "ud", "t"),
            "IBeam": ("lr", "ud"), "SizeNS": ("lr", "ud"), "SizeWE": ("lr", "ud")}


def _mirror(a, how):
    return {"lr": a[:, ::-1], "ud": a[::-1, :], "t": a.T}[how]


def _asym(alpha):
    """Mean |alpha - mirrored alpha| over the union of the two silhouettes."""
    out = {}
    for how in ("lr", "ud", "t"):
        b = _mirror(alpha, how)
        m = (alpha > 8) | (b > 8)
        out[how] = float(np.abs(alpha - b)[m].mean()) if m.any() else 0.0
    return out


def mirror_asym(name, idx=0, size=_RIM_SIZE, get=frame):
    """Mean |alpha - mirrored alpha| over the silhouette, per declared axis.

    A remaster should make a symmetric drawing more symmetric, not less. Ours
    runs about twice the author's and grows with size, because the asymmetry is
    in traced.json - the outline itself - and rasterising it finer reproduces it
    more faithfully rather than averaging it away.

    Read at two rungs, and they answer different questions. `native` is 32px,
    the author's own grid, and it is the only like-for-like comparison there is;
    that is what the gate should use. `size` is the top rung, where the defect
    is worst, and it is a diagnostic - it says how much the outline's own
    asymmetry has grown by the time it is drawn at the size people look at."""
    if name not in SYMMETRY:
        return None
    axes = SYMMETRY[name]
    big = _asym(get(name, idx, size)[..., 3])
    nat = _asym(get(name, idx, 32)[..., 3])
    return {"native": {k: nat[k] for k in axes},
            "large": {k: big[k] for k in axes}}


def mirror_asym_author(name, idx=0):
    """The same reading on the author's 32px frame - the target for `native`.

    His raster is only approximately symmetric, so this is never zero, and a
    gate against zero would be a gate against his drawing."""
    if name not in SYMMETRY:
        return None
    got = _asym(np.asarray(H.original(name, idx), dtype=np.float64)[..., 3])
    return {k: got[k] for k in SYMMETRY[name]}


_XYZ_D65 = np.array([0.95047, 1.0, 1.08883])
_RGB_TO_XYZ = np.array([[0.4124564, 0.3575761, 0.1804375],
                        [0.2126729, 0.7151522, 0.0721750],
                        [0.0193339, 0.1191920, 0.9503041]])


def _srgb_to_lab(rgb):
    """CIE L*a*b* (D65) from 8-bit sRGB values."""
    u = np.clip(rgb, 0.0, 255.0) / 255.0
    lin = np.where(u <= 0.04045, u / 12.92, ((u + 0.055) / 1.055) ** 2.4)
    xyz = (lin @ _RGB_TO_XYZ.T) / _XYZ_D65
    f = np.where(xyz > 216.0 / 24389.0, np.cbrt(xyz),
                 (24389.0 / 27.0 * xyz + 16.0) / 116.0)
    return np.stack([116.0 * f[..., 1] - 16.0,
                     500.0 * (f[..., 0] - f[..., 1]),
                     200.0 * (f[..., 1] - f[..., 2])], axis=-1)


def _delta_e_2000(lab1, lab2):
    """CIEDE2000, written out rather than pulled in.

    Euclidean distance in Lab is not perceptual: it overstates saturated blues
    and understates near-neutrals, which is exactly the pair of errors this set
    can make - orange glass with a hue shift along a fold, and grey glass that
    drifts warm. colormath and skimage both implement this; neither is worth a
    dependency for forty lines."""
    L1, a1, b1 = lab1.T
    L2, a2, b2 = lab2.T
    C1, C2 = np.hypot(a1, b1), np.hypot(a2, b2)
    Cb = 0.5 * (C1 + C2)
    G = 0.5 * (1.0 - np.sqrt(Cb ** 7 / (Cb ** 7 + 25.0 ** 7 + 1e-30)))
    a1p, a2p = (1.0 + G) * a1, (1.0 + G) * a2
    C1p, C2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360.0
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360.0
    zero = (C1p * C2p) == 0.0

    dh = h2p - h1p
    dh = np.where(dh > 180.0, dh - 360.0, np.where(dh < -180.0, dh + 360.0, dh))
    dLp, dCp = L2 - L1, C2p - C1p
    dHp = np.where(zero, 0.0, 2.0 * np.sqrt(C1p * C2p) * np.sin(np.radians(np.where(zero, 0.0, dh)) / 2.0))

    Lbp, Cbp = 0.5 * (L1 + L2), 0.5 * (C1p + C2p)
    hs = h1p + h2p
    hbp = np.where(zero, hs,
                   np.where(np.abs(h1p - h2p) <= 180.0, 0.5 * hs,
                            np.where(hs < 360.0, 0.5 * (hs + 360.0), 0.5 * (hs - 360.0))))
    T = (1.0 - 0.17 * np.cos(np.radians(hbp - 30.0))
         + 0.24 * np.cos(np.radians(2.0 * hbp))
         + 0.32 * np.cos(np.radians(3.0 * hbp + 6.0))
         - 0.20 * np.cos(np.radians(4.0 * hbp - 63.0)))
    Sl = 1.0 + 0.015 * (Lbp - 50.0) ** 2 / np.sqrt(20.0 + (Lbp - 50.0) ** 2)
    Sc = 1.0 + 0.045 * Cbp
    Sh = 1.0 + 0.015 * Cbp * T
    Rt = (-2.0 * np.sqrt(Cbp ** 7 / (Cbp ** 7 + 25.0 ** 7 + 1e-30))
          * np.sin(np.radians(60.0 * np.exp(-(((hbp - 275.0) / 25.0) ** 2)))))
    return np.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2
                   + Rt * (dCp / Sc) * (dHp / Sh))


def delta_e(name):
    """Colour distance from the author's own frame, after compositing.

    Matching luminance in linear light says the gradient is right; it does not
    say the hue is. Half the dead ends in PLAN.md are hue shifts that every
    brightness metric passed - the top-hat that put a purple cast along
    UpArrow's fold scored clean on luma. Delta-E 2000 is the number that says
    "the same colour", and it is read after compositing onto a background,
    because a translucent pixel's raw RGBA is not what anybody sees.

    Judged at the author's own 32 pixels, with the remaster box-averaged 8:1
    down to them. Comparing at 256 against a Lanczos stretch instead would
    grade the sharpness difference at every edge - the entire point of the
    remaster - as a colour error, and no threshold could tell the two apart."""
    n, s = nframes(name), _DE_NATIVE
    k = s // 32
    worst = {"mean": 0.0, "p95": 0.0, "frame": 0}
    per = {}
    for idx in range(n):
        big = frame(name, idx, s)
        o = np.asarray(H.original(name, idx), dtype=np.float64)
        oa = o[..., 3:4] / 255.0
        vis = (o[..., 3] > H._VIS * o[..., 3].max())
        if vis.sum() < 16:
            continue
        ba = big[..., 3:4] / 255.0
        m = 0.0
        p = 0.0
        for bg in _BACKGROUNDS.values():
            # Composite at full size, then average down: doing it the other way
            # round blends the cursor's own colour with the transparent pixels
            # beside it before the background ever gets there.
            c = (big[..., :3] * ba + bg * (1.0 - ba))
            c = c.reshape(32, k, 32, k, 3).mean(axis=(1, 3))
            d = _delta_e_2000(_srgb_to_lab(c[vis]),
                              _srgb_to_lab(o[..., :3][vis] * oa[vis] + bg * (1.0 - oa[vis])))
            m, p = max(m, float(d.mean())), max(p, float(np.percentile(d, 95)))
        per[str(idx)] = round(m, 2)
        if m > worst["mean"]:
            worst = {"mean": m, "p95": p, "frame": idx}
    worst["per_frame"] = per
    return worst


def validate_topology(name):
    """Frozen shape invariants from cursors.CURSOR_TOPOLOGY, frame by frame.

    Contours, points and the presence of a fold are what every later stage
    builds on, so a trace that quietly merges two outlines or loses an apex has
    to fail here rather than surface later as a cursor that renders wrong for
    reasons nobody can place."""
    want = getattr(H.C, "CURSOR_TOPOLOGY", {}).get(name)
    if want is None:
        return [f"{name}: no CURSOR_TOPOLOGY entry"]
    n = nframes(name)
    bad = []
    for key, got in (("contours", [len(f["polys"]) for f in H.C.TRACED[name]["frames"]]),
                     ("tips", [len(corners(name, i)) for i in range(n)]),
                     ("fold", [H._fold_chord(name, i) is not None for i in range(n)])):
        exp = want[key]
        if len(exp) != n:
            bad.append(f"{name}: {key} has {len(exp)} entries for {n} frames")
        elif list(got) != list(exp):
            where = [i for i, (g, e) in enumerate(zip(got, exp)) if g != e]
            bad.append(f"{name}: {key} {[got[i] for i in where]} != {[exp[i] for i in where]}"
                       f" at frames {where}")
    return bad


def _collect_one(job):
    name, sizes, vsizes = job
    e = {}
    e["topology"] = validate_topology(name)
    e["scale_drift"], e["scale_drift_dirs"] = scale_drift(name, sizes)
    e["density"], e["density_ladder"] = density(name, sizes)
    e["tip_convergence"], _ = tip_convergence(name)
    e["tip_convergence_orig"], _ = tip_convergence(name, get=orig_frame)
    e["tip_contrast"], _ = tip_contrast(name)
    e["tip_contrast_orig"], _ = tip_contrast(name, get=orig_frame)
    e["rim_layers"] = rim_layers(name)
    e["rim_layers_orig"] = rim_layers_author(name)
    e["edge_straight"] = edge_straight(name)
    e["mirror_asym"] = mirror_asym(name)
    e["mirror_asym_orig"] = mirror_asym_author(name)
    e["multiscale"] = validate_multiscale(name, vsizes)
    e["delta_e"] = delta_e(name)
    if name in H.ANIM:
        e["interp"] = interp_uniformity(name)
        e["temporal"] = temporal_smoothness(name)
        e["tip_sheen"] = tip_sheen(name)
        e["tip_sheen_orig"] = tip_sheen(name, get=orig_frame)
        if name in H.INTERP:
            e["inner_jitter"] = inner_jitter(name)
        else:
            e["morph"] = morph_health(name)
            e["morph_orig"] = morph_health(name, get=orig_frame)
    return name, e


def collect(sizes, names=None, jobs=1):
    names = names or [m["name"] for m in H.MANIFEST]
    # Only rungs the ladder is already rendering. The multiscale sweep walks
    # every frame, not just frame 0, so a size it does not share with the
    # ladder is a whole extra render of the set.
    vsizes = tuple(s for s in VALIDATE_SIZES_FULL if s in set(sizes))
    work = [(name, list(sizes), vsizes) for name in names]
    rep = {}
    if jobs > 1 and len(work) > 1:
        # One whole cursor per worker, not one frame. Every metric here wants
        # several sizes and several frames of the same cursor, and the caches
        # that make that affordable (_master, _base128, _up_alpha - seconds
        # each) live inside a process. Split any finer and the workers spend
        # their time recomputing what a sibling just threw away.
        #
        # build.py splits by frame instead because it needs the images back;
        # this one only needs the numbers, so the coarser split is free.
        env = ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")
        prev = {v: os.environ.get(v) for v in env}
        os.environ.update({v: "1" for v in env})     # BLAS threads would fight the pool
        try:
            with cf.ProcessPoolExecutor(max_workers=min(jobs, len(work))) as ex:
                for name, e in ex.map(_collect_one, work):
                    rep[name] = e
                    print(f"  {name} done", file=sys.stderr)
        finally:
            for v, old in prev.items():
                if old is None:
                    os.environ.pop(v, None)
                else:
                    os.environ[v] = old
    else:
        for job in work:
            name, e = _collect_one(job)
            rep[name] = e
            print(f"  {name} done", file=sys.stderr)
    return rep


def gate(rep, base=None):
    """Every threshold, applied. Returns (regressions, debt).

    Without a baseline every value that misses its threshold is a failure.
    With one, a value that misses its threshold but is no worse than the
    baseline is debt instead: named, printed on every run, not fatal.

    That distinction is what lets the gate be switched on today. Sixteen
    cursors currently miss thresholds this repo wrote for itself - the
    silhouette drifts 0.14 logical units across the size ladder against a
    target of 0.10, and the fold breaks on every cursor that has one. A gate
    that has to wait for all of that to be fixed is a gate that is not running,
    and a gate that is not running is how those numbers got there. Anything
    that moves further from the target still fails, on the spot."""
    T = THRESHOLDS
    bad, debt = [], []
    was = {n: (_flat(v) if "multiscale" in v else v) for n, v in (base or {}).items()}

    def fail(name, metric, got, op, want, key=None):
        line = f"{name:12s} {metric:18s} {got:8.3f} {op} {want}"
        prev = was.get(name, {}).get(key or metric)
        # A tenth of a percent of slack. The render is deterministic, so this is
        # not measurement noise - it is the baseline file's own rounding, which
        # is there so a human can read a diff on it. Without the slack a value
        # that never moved fails against its own record.
        tol = abs(prev) * 1e-3 + 1e-6 if prev is not None else 0.0
        if prev is None:
            bad.append(line)
        elif (got > prev + tol) if op == ">" else (got < prev - tol):
            bad.append(f"{line}  (was {prev:.3f})")
        else:
            debt.append(line)

    # Ratcheted whatever they read. Every other check here only consults the
    # baseline once a value has already missed its threshold, which leaves a
    # hole exactly where it matters most: a point's contrast fell 0.170 to 0.095
    # on Wait - 44 per cent - and the gate said nothing, because 0.095 still
    # clears the author's own 0.066. These two have a floor, not a ceiling, and
    # losing most of the headroom above the floor is the regression.
    for name, e in rep.items():
        f, prev = _flat(e), was.get(name, {})
        for key in ("tip_contrast", "tip_sheen"):
            got, ref = f.get(key), prev.get(key)
            if got is None or ref is None:
                continue
            if got < ref * (1.0 - _RATCHET_SLACK):
                bad.append(f"{name:12s} {key:18s} {got:8.3f} < {ref * (1.0 - _RATCHET_SLACK):.3f}"
                           f"  (was {ref:.3f})")

    for name, e in rep.items():
        for msg in e.get("topology", []):
            bad.append(f"{name:12s} {'topology':18s} {msg}")
        if e["scale_drift"] > T["scale_drift"]:
            fail(name, "scale_drift", e["scale_drift"], ">", T["scale_drift"])
        if e["density"] > T["density"]:
            fail(name, "density_%", e["density"], ">", T["density"], "density")
        ms = e.get("multiscale")
        if ms:
            for k in ("gap", "wander", "luma_step", "jag"):
                if ms["worst"][k] > T["fold_" + k]:
                    fail(name, "fold_" + k, ms["worst"][k], ">", T["fold_" + k])
            # Declared but never read is a failure, not a pass. A fold that no
            # size resolved leaves every number above it at a clean zero, which
            # is how the fold measurement sat broken for 36 attempts.
            top = getattr(H.C, "CURSOR_TOPOLOGY", {}).get(name, {})
            if any(top.get("fold", [])) and not ms["resolved"]:
                bad.append(f"{name:12s} {'fold_unmeasured':18s} "
                           f"declared in CURSOR_TOPOLOGY, no size resolved it")
        de = e.get("delta_e")
        if de and de["mean"] > T["delta_e"]:
            fail(name, f"delta_e[{de['frame']}]", de["mean"], ">", T["delta_e"], "delta_e")
        sh, sh0 = e.get("tip_sheen"), e.get("tip_sheen_orig")
        if sh and sh0 and sh0.get("amp"):
            want = sh0["amp"] * T["tip_sheen"]
            if sh["amp"] < want:
                fail(name, "tip_sheen", sh["amp"], "<", round(want, 2), "tip_sheen")
            # tip_wobble is reported, not gated. The author's own is 0.10 at one
            # of Arrow's corners and 0.34 at another, so a ratio against him
            # swings by a factor of three between two corners of one cursor and
            # would be gating his drawing's variance, not ours. The number is
            # here because unfreezing a tip has to be checked against something.
        ts = e.get("temporal")
        if ts:
            for z in ("fold", "body"):
                got, ref = ts.get(z), ts.get(z + "_orig")
                if got is None:
                    continue
                # The morphs redraw themselves, so their steps are large by
                # design and only the author's own cycle says how large is
                # right. The interpolated ones have a frozen silhouette, and
                # there any hurrying is the shading's own.
                want = T["temporal"] if name in H.INTERP else max(T["temporal"], ref or 0.0)
                if got > want:
                    fail(name, "temporal_" + z, got, ">", round(want, 2))
        # Judged against the author's own frame, not an absolute: how far a
        # fold may sit from a point and how much contrast a translucent point
        # can carry are properties of the drawing.
        # tip_convergence is reported, not gated. Near a sharp point the wedge
        # narrows until its two dark rims meet, and at that width the rims are
        # the fold - there is nothing left to tell apart, so no cross-section
        # test can say whether a fold "reached" the apex. Both formulations
        # tried (range across the wedge, and a true dip) score the blurred 2006
        # reference as converged everywhere, which is not a standard anything
        # can be held to. Judge the points on the zoomed render instead; the
        # number is here to show movement between runs.
        if e["tip_contrast"] < e["tip_contrast_orig"] * T["tip_contrast"]:
            fail(name, "tip_contrast", e["tip_contrast"], "<",
                 round(e["tip_contrast_orig"] * T["tip_contrast"], 3))
        it = e.get("interp")
        if it:
            if it["ghost_rgb"] > T["ghost_rgb"]:
                fail(name, "ghost_rgb", it["ghost_rgb"], ">", T["ghost_rgb"])
            if name in H.INTERP:
                pm = it["visible_peak_over_mean"]
                if pm > T["liveliness_max"]:
                    fail(name, "cadence", pm, ">", T["liveliness_max"])
                want = it["cycle_motion_keys"] * T["liveliness_min"]
                if it["cycle_motion"] < want:
                    fail(name, "sheen_damped", it["cycle_motion"], "<", round(want, 2))
        ij = e.get("inner_jitter")
        if ij and ij["p95"] > T["inner_jitter"]:
            fail(name, "inner_jitter_p95", ij["p95"], ">", T["inner_jitter"], "inner_jitter")
        elif ij is None and name in H.INTERP and any(
                getattr(H.C, "CURSOR_TOPOLOGY", {}).get(name, {}).get("fold", [])):
            # Same rule as fold_unmeasured, for the same reason. AppStarting's
            # crease is four to seven levels deep where Arrow's is eighteen to
            # twenty-three, so few enough rows resolve that this returns nothing
            # at all - and nothing at all must not read as a pass.
            bad.append(f"{name:12s} {'jitter_unmeasured':18s} "
                       f"fewer than ten rows of fold resolved across the cycle")
        mo, mo0 = e.get("morph"), e.get("morph_orig")
        if mo and mo0:
            if mo["iou_min"] < mo0["iou_min"] * T["morph_iou"]:
                fail(name, "morph_iou_min", mo["iou_min"], "<",
                     round(mo0["iou_min"] * T["morph_iou"], 3), "morph_iou")
            if mo["peak_over_mean"] > mo0["peak_over_mean"] * T["morph_peak"]:
                fail(name, "morph_peak", mo["peak_over_mean"], ">",
                     round(mo0["peak_over_mean"] * T["morph_peak"], 2))
    return bad, debt


def _flat(e):
    """The scalar readings of one cursor, for the table, the diff and the ratchet."""
    if "multiscale" not in e:
        return e                       # already flat: a committed baseline file
    it, ij, mo = e.get("interp"), e.get("inner_jitter"), e.get("morph")
    ms, ts, de = e.get("multiscale"), e.get("temporal") or {}, e.get("delta_e")
    return {
        "scale_drift": e["scale_drift"],
        "density": e["density"],
        "tip_convergence": e["tip_convergence"],
        "tip_contrast": e["tip_contrast"],
        "fold_gap": ms["worst"]["gap"] if ms else None,
        "fold_wander": ms["worst"]["wander"] if ms else None,
        "fold_luma_step": ms["worst"]["luma_step"] if ms else None,
        "fold_jag": ms["worst"]["jag"] if ms else None,
        "delta_e": de["mean"] if de else None,
        "ghost_rgb": it["ghost_rgb"] if it else None,
        "cadence": it["visible_peak_over_mean"] if it else None,
        "inner_jitter": ij["p95"] if ij else None,
        "morph_iou": mo["iou_min"] if mo else None,
        "temporal_fold": ts.get("fold"),
        "temporal_body": ts.get("body"),
        "tip_sheen": (e.get("tip_sheen") or {}).get("amp"),
        "tip_wobble": (e.get("tip_sheen") or {}).get("wobble"),
        "rim_layers": (e.get("rim_layers") or {}).get("share"),
        "rim_layers_per_station": (e.get("rim_layers") or {}).get("per_station"),
        "rim_layers_orig": (e.get("rim_layers_orig") or {}).get("share"),
        "edge_straight": (e.get("edge_straight") or {}).get("max"),
        "edge_straight_rms": (e.get("edge_straight") or {}).get("rms"),
        "mirror_asym": (max((e.get("mirror_asym") or {}).get("native", {}).values())
                        if e.get("mirror_asym") else None),
        "mirror_asym_large": (max((e.get("mirror_asym") or {}).get("large", {}).values())
                              if e.get("mirror_asym") else None),
        "mirror_asym_orig": (max((e.get("mirror_asym_orig") or {}).values())
                             if e.get("mirror_asym_orig") else None),
    }


_KNOWN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "metrics-known-issues.json")


def _known_issues(path):
    """Accepted numberless complaints, whitespace-normalised for matching.

    Same file and same normalisation build.check_quality uses, so the two gates
    accept exactly the same set. Missing file means nothing is accepted."""
    if not path or not os.path.exists(path):
        return set()
    with open(path) as fh:
        return {" ".join(x.split()) for x in json.load(fh).get("accepted", [])}


def show(rep, base=None):
    cols = [("drift(L)", "scale_drift", 10, ".3f"), ("dens%", "density", 7, ".2f"),
            ("tipconv", "tip_convergence", 8, ".2f"), ("tipcon", "tip_contrast", 7, ".3f"),
            ("gap", "fold_gap", 6, ".2f"), ("wander", "fold_wander", 7, ".2f"),
            ("jag", "fold_jag", 6, ".0f"), ("dE", "delta_e", 6, ".2f"),
            ("sheen", "tip_sheen", 7, ".2f"), ("wob", "tip_wobble", 6, ".2f"),
            ("ghost", "ghost_rgb", 7, ".2f"), ("cad", "cadence", 6, ".2f"),
            ("jit95", "inner_jitter", 7, ".2f"), ("iou", "morph_iou", 6, ".3f"),
            ("tsm", "temporal_fold", 6, ".2f"), ("rim", "rim_layers", 6, ".2f"),
            ("straight", "edge_straight", 9, ".3f"), ("mirr", "mirror_asym", 6, ".1f")]
    hdr = f"{'cursor':12s}" + "".join(h.rjust(w) for h, _, w, _ in cols)
    print(hdr)
    print("-" * len(hdr))
    for name, e in rep.items():
        f = _flat(e)
        print(f"{name:12s}" + "".join(
            (format(f[k], fmt) if f.get(k) is not None else "-").rjust(w)
            for _, k, w, fmt in cols))
    if base:
        print("\nchanged vs baseline (metric: before -> after):")
        for name, e in rep.items():
            if name not in base:
                continue
            b, f = _flat(base[name]), _flat(e)
            for k, v in f.items():
                o = b.get(k)
                if o is not None and v is not None and abs(o - v) > 1e-4:
                    print(f"  {name:12s} {k:16s} {o:8.3f} -> {v:8.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", metavar="FILE", help="write a full snapshot here")
    ap.add_argument("--ratchet", metavar="FILE",
                    help="write the flat scalars here, the shape --check ratchets against")
    ap.add_argument("--check", metavar="FILE", nargs="?", const="", help="gate, optionally against a baseline")
    ap.add_argument("--full", action="store_true", help="include 512 in the size ladder (slow)")
    ap.add_argument("--fast", action="store_true", help="three rungs only, for loop iterations")
    ap.add_argument("--only", metavar="NAME", action="append", help="restrict to these cursors")
    ap.add_argument("--jobs", metavar="N", type=int, default=1,
                    help="cursors to measure in parallel (one process each)")
    ap.add_argument("--known", metavar="FILE", default=_KNOWN,
                    help="complaints that carry no number and are already "
                         "accepted (default: metrics-known-issues.json)")
    args = ap.parse_args()

    sizes = LADDER_FAST if args.fast else LADDER_FULL if args.full else LADDER
    print(f"sizes {sizes}", file=sys.stderr)
    rep = collect(sizes, args.only, args.jobs)

    base = None
    if args.check:
        with open(args.check) as fh:
            base = json.load(fh)
    show(rep, base)

    if args.baseline:
        with open(args.baseline, "w") as fh:
            json.dump(rep, fh, indent=1)
        print(f"\nbaseline written to {args.baseline}")

    if args.ratchet:
        # Flat and sorted: this one is committed, so a diff on it has to be
        # readable by a person deciding whether a number was allowed to move.
        with open(args.ratchet, "w") as fh:
            json.dump({n: {k: (round(v, 6) if isinstance(v, float) else v)
                           for k, v in sorted(_flat(e).items()) if v is not None}
                       for n, e in rep.items()}, fh, indent=1, sort_keys=True)
            fh.write("\n")
        print(f"\nratchet written to {args.ratchet}")

    if args.check is not None:
        bad, debt = gate(rep, base)
        # The same subtraction build.check_quality does, for the same reason:
        # a complaint that carries no number ("this could not be measured at
        # all") cannot be ratcheted, so it lands in `bad` on every run and would
        # wedge the gate shut for good. Those are listed in
        # metrics-known-issues.json with a note on each. Reading it here is what
        # makes CI and the local build gate say the same thing - without it the
        # two disagreed, and the workflow that runs this command was red on
        # exactly the entries build.py had already accepted.
        known = _known_issues(args.known)
        accepted = [b for b in bad if " ".join(b.split()) in known]
        bad = [b for b in bad if " ".join(b.split()) not in known]
        if debt:
            print(f"\ndebt ({len(debt)}) - misses the target, no worse than the baseline")
            for d in debt:
                print("  " + d)
        if accepted:
            print(f"\naccepted ({len(accepted)}) - carried in "
                  f"{os.path.basename(args.known)}, no number to ratchet")
            for a in accepted:
                print("  " + a)
        print()
        if bad:
            print(f"FAIL ({len(bad)})")
            for b in bad:
                print("  " + b)
            return 1
        print("PASS - nothing worse than the baseline, and nothing new off target"
              if base else "PASS - every threshold met")
    return 0


if __name__ == "__main__":
    sys.exit(main())

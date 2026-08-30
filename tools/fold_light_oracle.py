"""One-file oracle: facet-light model for AppStarting/Wait's fold, in local
chord coordinates instead of a per-pixel RGB field.

Spec: docs/dev/NEXT.md, "AppStarting/Wait: воспроизводимый план одного
oracle-файла" (2026-08-30, on 432a262). Diagnostic only - does not import
into cgr/hybrid.py or cgr/lightanim.py, does not touch data/metrics-baseline.json,
does not write outside .metrics/fold-light-oracle/.

Idea: canonical_frame already carries the accepted fold geometry (c(t),
s=_RESTEP_WIDTH). Fix that geometry once, from the canonical frame alone.
Then, instead of animating a per-pixel RGB light field through it (which is
what regressed s and unres on every prior candidate - NEXT.md 64/68 and the
three simple projections logged in section 1 of the spec), extract four
scalars per station per channel from each of the nine authored masters - the
level and slope of the left and right facet - and animate those over phase.
Reconstructing the tanh step from animated facet coefficients cannot re-fit
c(t) or s, because they are never inputs to the interpolation: only aL, kL,
aR, kR travel over phase.
"""
import argparse
import csv
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
TOOLS = os.path.dirname(os.path.abspath(__file__))
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import numpy as np
from PIL import Image

from cgr import hybrid as H
from cgr import lightanim as LA
from cgr import vectorlib as V
import analyze as A
import foldfit as F

CURSORS_DEFAULT = ["AppStarting", "Wait", "Hand"]
SIZES_DEFAULT = [128, 256, 512]
VISUAL_SIZES_DEFAULT = [32, 128, 512]

# Reused verbatim from cgr.hybrid._fold_restep - not reintroduced as new
# constants, per the spec's own ban on inventing new tuning knobs.
_REACH = H._RESTEP_REACH
_PITCH = H._RESTEP_PITCH
_STATIONS = H._RESTEP_STATIONS
_FIT = H._RESTEP_FIT
_WIDTH = H._RESTEP_WIDTH
_SUPPORT = H._RESTEP_SUPPORT
_FADE = H._RESTEP_FADE
_PROTECT = H._RESTEP_PROTECT
_PROTECT_FADE = H._RESTEP_PROTECT_FADE


# --------------------------------------------------------------------------
# Step B: one fixed fold geometry per (name, size), from the canonical frame.
# --------------------------------------------------------------------------

def build_geometry(name, size, idx):
    """Replicates _fold_restep's own station/centre search, once, on the
    already-accepted canonical frame. Nothing here is re-run per source
    master or per output phase - c(t) is computed exactly once."""
    ch = H._fold_chord(name, idx)
    if ch is None:
        return None, "no_fold_chord"
    (tx, ty), (mx, my) = ch
    L = size / V.LOGICAL
    dx, dy = mx - tx, my - ty
    seg = float(np.hypot(dx, dy))
    if seg < 1e-6:
        return None, "degenerate_chord"
    ux, uy = dx / seg, dy / seg
    vx, vy = -uy, ux

    base = np.asarray(LA.canonical_frame(name, size, idx), dtype=np.float64)
    lum_c = np.ascontiguousarray(base[..., :3].mean(-1))
    dist = H._edge_distance_at(name, idx, size)
    alpha = np.ascontiguousarray(H._up_alpha(name, idx, size).astype(np.float64))

    ns = np.arange(-_REACH, _REACH + _PITCH, _PITCH)
    ts = np.linspace(0.0, 1.0, _STATIONS)
    smooth = max(3, int(round(0.15 / _PITCH)) | 1)

    centers = np.full(len(ts), np.nan)
    reasons = ["no_station"] * len(ts)
    station = [None] * len(ts)  # (sx, sy, run, nn, left, right) for good stations

    for k, t in enumerate(ts):
        px, py = tx + dx * t, ty + dy * t
        sx, sy = (px + ns * vx) * L - 0.5, (py + ns * vy) * L - 0.5
        y = H._sample1(lum_c, sx, sy)
        d = H._sample1(dist, sx, sy)
        a = H._sample1(alpha, sx, sy)
        ok = (d >= _PROTECT) & (a >= 24.0) & np.isfinite(y)
        if ok.sum() < 40:
            reasons[k] = "guard<1: fewer than 40 admissible samples"
            continue
        idxs = np.nonzero(ok)[0]
        run = max(np.split(idxs, np.nonzero(np.diff(idxs) > 1)[0] + 1), key=len)
        if len(run) < 40:
            reasons[k] = "guard<1: longest run under 40 samples"
            continue
        nn, yy = ns[run], y[run]
        sm = np.convolve(np.pad(yy, smooth // 2, mode="edge"),
                          np.ones(smooth) / smooth, "valid")
        g = np.gradient(sm, nn)
        room = _FIT[1] + 0.1
        inner = (nn >= nn.min() + room) & (nn <= nn.max() - room)
        if inner.sum() < 3:
            reasons[k] = "guard<1: no room for an inner search window"
            continue
        ce = float(nn[int(np.argmax(np.where(inner, np.abs(g), 0.0)))])
        lo, hi = _FIT
        left = (nn <= ce - lo) & (nn >= ce - hi)
        right = (nn >= ce + lo) & (nn <= ce + hi)
        if left.sum() < 6 or right.sum() < 6:
            reasons[k] = "guard<1: fit window too thin either side"
            continue
        centers[k] = ce
        station[k] = (sx[run], sy[run], nn, left, right)
        reasons[k] = "ok"

    good = np.nonzero(np.isfinite(centers))[0]
    if len(good) < 5:
        return None, "fewer than 5 stations resolved on canonical"

    c = _smooth_stations(centers[good], good, len(ts))

    return dict(name=name, size=size, idx=idx, tip=(tx, ty), notch=(mx, my),
                ux=ux, uy=uy, vx=vx, vy=vy, seg=seg, L=L,
                ts=ts, ns=ns, c=c, good=good, reasons=reasons, station=station,
                dist=dist, alpha=alpha), None


def _smooth_stations(v_at_good, good, n_stations):
    """np.interp fill + median-5 + box-5 - exactly _fold_restep's own
    per-column smoothing, applied here to one column at a time."""
    v = np.interp(np.arange(n_stations), good, v_at_good)
    med = np.array([np.median(v[max(0, i - 2):i + 3]) for i in range(len(v))])
    pad = np.pad(med, 2, mode="edge")
    return np.convolve(pad, np.ones(5) / 5.0, "valid")


# --------------------------------------------------------------------------
# Step C: per-channel facet coefficients from the nine authored masters.
# --------------------------------------------------------------------------

def extract_coefficients(geom):
    """(n_src, stations, 3, 4) array of (aL, kL, aR, kR), filled and smoothed
    exactly as _fold_restep smooths its own five columns - per (source frame,
    channel) column, using the SAME good-station set every time, because the
    admissible sample window is geometry (alpha, edge distance), which every
    master shares with canonical on these frozen-silhouette cursors."""
    name, size = geom["name"], geom["size"]
    n_src = len(H.BY_NAME[name]["frames"])
    ts, good, station = geom["ts"], geom["good"], geom["station"]
    coef = np.full((n_src, len(ts), 3, 4), np.nan)
    for i in range(n_src):
        master = H._master_rgb(name, i, size)
        lin = V.srgb_to_linear(np.clip(master, 0, 255).astype(np.uint8)).astype(np.float64)
        for k in good:
            sx, sy, nn, left, right = station[k]
            ce = geom["c"][k]
            for ch in range(3):
                yy = H._sample1(np.ascontiguousarray(lin[..., ch]), sx, sy)
                al, kl = H._restep_line(nn[left] - ce, yy[left])
                ar, kr = H._restep_line(nn[right] - ce, yy[right])
                coef[i, k, ch] = (al, kl, ar, kr)
        for ch in range(3):
            for p in range(4):
                coef[i, :, ch, p] = _smooth_stations(coef[i, good, ch, p], good, len(ts))
    return coef


# --------------------------------------------------------------------------
# Step D: interpolate coefficients over phase, reconstruct the local field.
# --------------------------------------------------------------------------

def reconstruct_local(coef_row, ns_grid, c):
    """coef_row: (stations, 3, 4). Returns (stations, len(ns_grid), 3), the
    two-facet tanh model at every sampled (t, n), fixed centre and width."""
    x = ns_grid[None, :] - c[:, None]                      # (stations, n)
    phi = 0.5 * (1.0 + np.tanh(x / _WIDTH))
    aL, kL, aR, kR = (coef_row[..., i] for i in range(4))    # each (stations, 3)
    left = aL[:, None, :] + kL[:, None, :] * x[:, :, None]
    right = aR[:, None, :] + kR[:, None, :] * x[:, :, None]
    return (1.0 - phi)[:, :, None] * left + phi[:, :, None] * right


def build_pixel_grid(geom, size):
    """Everything the bilinear remap needs that does not depend on phase or
    channel: station/normal indices, blend weights, the support+guard weight
    that later blends candidate against ship."""
    tx, ty = geom["tip"]
    ux, uy, vx, vy, seg, L = geom["ux"], geom["uy"], geom["vx"], geom["vy"], geom["seg"], geom["L"]
    ts, ns, c = geom["ts"], geom["ns"], geom["c"]
    ys, xs = np.mgrid[0:size, 0:size]
    relx, rely = (xs + 0.5) / L - tx, (ys + 0.5) / L - ty
    tt = (relx * ux + rely * uy) / seg
    nnp = relx * vx + rely * vy
    fk = np.clip(tt, 0.0, 1.0) * (len(ts) - 1)
    fj = (nnp + _REACH) / _PITCH
    k0 = np.clip(np.floor(fk).astype(int), 0, len(ts) - 2)
    j0 = np.clip(np.floor(fj).astype(int), 0, len(ns) - 2)
    a1 = fk - k0
    b1 = np.clip(fj - j0, 0.0, 1.0)
    c_pixel = (1.0 - a1) * c[k0] + a1 * c[k0 + 1]
    inside = ((tt >= 0.0) & (tt <= 1.0) & (np.abs(nnp) <= _REACH)
              & (H._mask(geom["name"], geom["idx"], size) > 0))
    guard = np.clip((geom["dist"] - _PROTECT) / _PROTECT_FADE, 0.0, 1.0)
    support = np.clip((_SUPPORT + _FADE - np.abs(nnp - c_pixel)) / _FADE, 0.0, 1.0)
    weight = np.where(inside, support * guard, 0.0)
    return dict(k0=k0, j0=j0, a1=a1, b1=b1, inside=inside, guard=guard,
                weight=weight, tt=tt, nnp=nnp, c_pixel=c_pixel)


def remap_field(grid, field):
    """field: (stations, n_count, 3). Bilinear gather onto the pixel grid,
    zero outside the fold's reach/mask - the same gather _fold_restep's tail
    does, generalised to a channel axis."""
    k0, j0, a1, b1 = grid["k0"], grid["j0"], grid["a1"], grid["b1"]
    out = ((1 - a1)[..., None] * (1 - b1)[..., None] * field[k0, j0]
           + a1[..., None] * (1 - b1)[..., None] * field[k0 + 1, j0]
           + (1 - a1)[..., None] * b1[..., None] * field[k0, j0 + 1]
           + a1[..., None] * b1[..., None] * field[k0 + 1, j0 + 1])
    return np.where(grid["inside"][..., None], out, 0.0)


# --------------------------------------------------------------------------
# Steps E: candidate = ship, blended with canonical+fold_delta inside the
# fold band only.
# --------------------------------------------------------------------------

def build_frames(name, size, verbose=False):
    idx = LA.canonical_index(name)
    geom, err = build_geometry(name, size, idx)
    if geom is None:
        return None, err, None

    _idx2, base, lin, alpha, raw, n_src, vis, seen, anchor = LA._setup(name, size, LA.HARMONICS, idx)
    phases = LA.paced_phases(name, size)
    out_n = len(phases)

    coef = extract_coefficients(geom)
    anchor_phase = idx / n_src
    coef_anchor = LA.periodic_at(coef, [anchor_phase], LA.HARMONICS)[0]  # (stations,3,4)
    coef_phase = LA.periodic_at(coef, phases, LA.HARMONICS)              # (out_n,stations,3,4)

    # Identity check (spec step D): evaluating the coefficient interpolation
    # at the anchor's own phase must reproduce coef_anchor exactly. A failure
    # here is a bug in this file, not a finding about the model.
    check = LA.periodic_at(coef, [anchor_phase], LA.HARMONICS)[0]
    identity_gap = float(np.max(np.abs(check - coef_anchor)))
    if identity_gap > 1e-10:
        return None, f"identity check failed: {identity_gap:.3e}", None

    grid = build_pixel_grid(geom, size)
    field_light = LA.periodic_at(raw, phases, LA.HARMONICS) - anchor  # production's own field

    ship_frames, candidate_frames, diag = [], [], []
    for t in range(out_n):
        r = field_light[t] * LA._LIGHT_GAIN * vis[..., None]
        ship_lin = LA._lit(lin, r)

        delta_coef = coef_phase[t] - coef_anchor                      # (stations,3,4)
        local = reconstruct_local(delta_coef, geom["ns"], geom["c"])  # (stations,n,3)
        fold_delta = remap_field(grid, local)                          # (size,size,3)

        gscale = LA._gamut_scale(np.clip(lin, 0.0, 1.0), fold_delta)
        fold_lin = lin + fold_delta * gscale[..., None]

        w = grid["weight"][..., None]
        candidate_lin = ship_lin * (1.0 - w) + fold_lin * w

        ship_srgb = V.linear_to_srgb(np.clip(ship_lin, 0.0, 1.0)).astype(np.float64)
        cand_srgb = V.linear_to_srgb(np.clip(candidate_lin, 0.0, 1.0)).astype(np.float64)

        ship_frames.append(np.asarray(H._compose(ship_srgb, alpha), dtype=np.float64))
        candidate_frames.append(np.asarray(H._compose(cand_srgb, alpha), dtype=np.float64))

        if verbose:
            diag.append(dict(t=t, phase=float(phases[t]),
                              weight_max=float(grid["weight"].max()),
                              delta_max=float(np.abs(fold_delta).max())))

    # Contract checks (spec step E), cheap and always run.
    alpha_ok = all(np.array_equal(s[..., 3], c[..., 3])
                    for s, c in zip(ship_frames, candidate_frames))
    outside = ~grid["inside"]
    outside_ok = all(np.allclose(s[..., :3][outside], c[..., :3][outside], atol=1e-6)
                      for s, c in zip(ship_frames, candidate_frames))
    contract = dict(alpha_identical=bool(alpha_ok),
                     outside_band_identical=bool(outside_ok),
                     identity_gap=identity_gap)

    return dict(idx=idx, geom=geom, grid=grid, phases=phases,
                ship=ship_frames, candidate=candidate_frames,
                contract=contract, diag=diag, n_src=n_src, coef=coef,
                coef_anchor=coef_anchor, coef_phase=coef_phase), None, None


# --------------------------------------------------------------------------
# Step F: numerical go/no-go, via the same instruments the real gate uses.
# --------------------------------------------------------------------------

def oracle_step_multiscale(name, sizes, get_frames):
    """Line-for-line mirror of tools.analyze._step_multiscale, except the
    frames per size come from get_frames(size) -> (frames, phases, geom)
    instead of product_cycle - so the exact same reading the real gate takes
    can be pointed at this file's own candidate frames instead of the
    shipped ones. geom follows _cycle_geom's own contract: a fixed authored
    index for a frozen silhouette, or None to use the frame's own index."""
    sizes = [s for s in sizes if s in A._STEP_SIZES]
    out = {"resolved": [], "cover": 1.0, "unres": 0.0, "curv": 0.0,
           "curv_orig": 0.0, "jumps": 0, "rms": 0.0, "s_conv": 1.0,
           "s_ratio_lo": None, "s_ratio_hi": None, "step": None,
           "notch": None, "tip": None, "s_at": {}}
    if not sizes:
        return out
    seen = {}
    for size in sizes:
        frames, phases, geom = get_frames(size)
        out["curv_orig"] = max(out["curv_orig"], A._orig_curv(name, size))
        rows = {}
        for t, f in enumerate(frames):
            idx = t if geom is None else geom
            p = A.fold_step_profile(name, idx, size, get=A._still(f))
            if p is None:
                continue
            rows[t] = p
            seen.setdefault(t, {})[size] = p["s"]
            out["cover"] = min(out["cover"], p["cover"])
            out["unres"] = max(out["unres"], p["unres"])
            out["curv"] = max(out["curv"], p["curv"])
            out["jumps"] = max(out["jumps"], p["jumps"])
            out["rms"] = max(out["rms"], p["rms"])
            ph = phases[t]
            for key, r in (("s_ratio", A._ratio(p["s"], A.author_at(name, size, "s", ph), 1e-3)),
                           ("step", A._ratio(p["step"], A.author_at(name, size, "step", ph), 1.0)),
                           ("notch", A._ratio(p["notch"], A.author_at(name, size, "notch", ph), 1.0))):
                if r is None:
                    continue
                if key == "s_ratio":
                    lo, hi = out["s_ratio_lo"], out["s_ratio_hi"]
                    out["s_ratio_lo"] = r if lo is None else min(lo, r)
                    out["s_ratio_hi"] = r if hi is None else max(hi, r)
                else:
                    out[key] = r if out[key] is None else min(out[key], r)
        if rows:
            out["resolved"].append(size)
            out["s_at"][str(size)] = float(np.median([p["s"] for p in rows.values()]))
        if size in A._TIP_SIZES:
            for t, f in enumerate(frames):
                idx = t if geom is None else geom
                k = A.inner_tip_kept(name, idx, size, get=A._still(f))
                if k is not None:
                    out["tip"] = k if out["tip"] is None else min(out["tip"], k)
    for _idx, by_size in seen.items():
        if len(by_size) > 1:
            v = [x for x in by_size.values() if x > 0]
            if v:
                out["s_conv"] = max(out["s_conv"], max(v) / min(v))
    return out


def gate_step(name, st):
    """The exact fold checks tools/analyze.py's gate() runs on a resolved
    multiscale step reading (analyze.py:2381-2410), reused rather than
    re-derived so this oracle's go/no-go is the real gate, not a guess at
    it. Returns a list of failure strings, empty if this cursor would pass."""
    T = A.THRESHOLDS
    bad = []
    if not st["resolved"]:
        return ["fold_unresolved: no size in the ladder resolved a fold reading"]
    if st["cover"] < T["fold_cover"]:
        bad.append(f"fold_cover {st['cover']:.3f} < {T['fold_cover']}")
    if st["unres"] > T["fold_unres"]:
        bad.append(f"fold_unres {st['unres']:.3f} > {T['fold_unres']}")
    lo, hi = st["s_ratio_lo"], st["s_ratio_hi"]
    if lo is not None and lo < T["fold_s_min"]:
        bad.append(f"fold_s_thin {lo:.3f} < {T['fold_s_min']}")
    if hi is not None and hi > T["fold_s_max"]:
        bad.append(f"fold_s_wide {hi:.3f} > {T['fold_s_max']}")
    if st["s_conv"] > T["fold_s_conv"]:
        bad.append(f"fold_s_conv {st['s_conv']:.3f} > {T['fold_s_conv']}")
    want = max(T["fold_curv"], 2.0 * st["curv_orig"])
    if st["curv"] > want:
        bad.append(f"fold_curv {st['curv']:.3f} > {want:.3f}")
    if st["step"] is not None and st["step"] < T["fold_step"]:
        bad.append(f"fold_step {st['step']:.3f} < {T['fold_step']}")
    if st["notch"] is not None and st["notch"] < T["fold_notch"]:
        bad.append(f"fold_notch {st['notch']:.3f} < {T['fold_notch']}")
    return bad


# --------------------------------------------------------------------------
# Step G: visual contact sheets.
# --------------------------------------------------------------------------

def _composite(rgba, bg):
    a = rgba[..., 3:4] / 255.0
    return rgba[..., :3] * a + bg * (1.0 - a)


def make_contact_sheet(name, size, built, out_path):
    frames = built["candidate"]
    ship = built["ship"]
    idx = built["idx"]
    phases = built["phases"]
    n = len(frames)
    s_vals = []
    for f in frames:
        p = A.fold_step_profile(name, idx, size, get=A._still(f))
        s_vals.append(p["s"] if p else None)
    resolved = [i for i, v in enumerate(s_vals) if v is not None]
    worst = min(resolved, key=lambda i: s_vals[i]) if resolved else 0
    light = int(np.argmax([np.abs(f[..., :3] - ship[0][..., :3]).mean() for f in frames]))
    picks = sorted(set([0, worst, light] +
                        [max(0, worst - 1), min(n - 1, worst + 1)]))

    bgs = {"white": 255.0, "grey": 128.0, "black": 0.0}
    rows = []
    for i in picks:
        cand, shp = frames[i], ship[i]
        diff = np.clip(np.abs(cand[..., :3] - shp[..., :3]) * 15.0, 0, 255)
        tiles = []
        for bg in bgs.values():
            tiles.append(_composite(shp, bg))
            tiles.append(_composite(cand, bg))
        tiles.append(diff)
        rows.append(np.concatenate(tiles, axis=1))
    full = np.concatenate(rows, axis=0)
    Image.fromarray(np.clip(full, 0, 255).astype(np.uint8)).save(out_path)
    return picks, s_vals


# --------------------------------------------------------------------------
# Orchestration.
# --------------------------------------------------------------------------

_FAIL_KIND = lambda msg: msg.split(" ", 1)[0]


def _sample_geom_scalar(geom, t, n):
    """dist/alpha/guard/weight at one continuous (t, n) point on the chord -
    the same fields build_pixel_grid samples on the whole pixel grid, read
    here at a single point for the stations.csv diagnostic row."""
    tx, ty = geom["tip"]
    mx, my = geom["notch"]
    dx, dy = mx - tx, my - ty
    ux, uy, vx, vy, L = geom["ux"], geom["uy"], geom["vx"], geom["vy"], geom["L"]
    px, py = tx + dx * t, ty + dy * t
    sx = np.array([(px + n * vx) * L - 0.5])
    sy = np.array([(py + n * vy) * L - 0.5])
    d = float(H._sample1(geom["dist"], sx, sy)[0])
    a = float(H._sample1(geom["alpha"], sx, sy)[0])
    guard = float(np.clip((d - _PROTECT) / _PROTECT_FADE, 0.0, 1.0))
    return d, a, guard


def _coef_at(built, t_out, t_local):
    """Candidate's reconstructed (aL, kL, aR, kR) at output phase t_out and
    chord fraction t_local, averaged over channel for a readable CSV cell -
    interpolated from this file's own 96-station grid onto foldfit's."""
    ts = built["geom"]["ts"]
    row = built["coef_phase"][t_out]  # (stations, 3, 4)
    out = [float(np.interp(t_local, ts, row[:, :, p].mean(axis=1))) for p in range(4)]
    return out  # aL, kL, aR, kR


def run(cursors, sizes, out_dir, metrics_only, verbose_stations, visual):
    os.makedirs(out_dir, exist_ok=True)
    summary = {"cursors": {}, "verdict": None, "exit": 0}
    station_rows = []
    data_error = False

    built_cache = {}

    def get_built(name, size):
        key = (name, size)
        if key not in built_cache:
            built, err, _ = build_frames(name, size, verbose=verbose_stations)
            built_cache[key] = (built, err)
        return built_cache[key]

    def get_frames_factory(name, which):
        def get_frames(size):
            built, err = get_built(name, size)
            if built is None:
                raise RuntimeError(err)
            return built[which], built["phases"], built["idx"]
        return get_frames

    for name in cursors:
        entry = {"error": None}
        try:
            agg_cand = oracle_step_multiscale(name, sizes, get_frames_factory(name, "candidate"))
            agg_ship = oracle_step_multiscale(name, sizes, get_frames_factory(name, "ship"))
            entry["candidate"] = dict(agg_cand)
            entry["ship"] = dict(agg_ship)
            bad_cand = gate_step(name, agg_cand)
            bad_ship = gate_step(name, agg_ship)
            entry["gate_candidate"] = bad_cand
            entry["gate_ship"] = bad_ship
            new_kinds = ({_FAIL_KIND(m) for m in bad_cand}
                         - {_FAIL_KIND(m) for m in bad_ship})
            entry["new_failures"] = sorted(new_kinds)

            for size in sizes:
                built, err = get_built(name, size)
                if built is None:
                    continue
                if not (built["contract"]["alpha_identical"]
                        and built["contract"]["outside_band_identical"]):
                    data_error = True
            if not metrics_only:
                phase_range = (range(len(get_built(name, sizes[0])[0]["phases"]))
                               if verbose_stations else [0])
                for size in sizes:
                    built, err = get_built(name, size)
                    if built is None:
                        continue
                    for t_out in phase_range:
                        for t_local in np.linspace(F.T_LO, F.T_HI, F.STATIONS):
                            m_ship = F.measure(name, built["idx"], size,
                                                A._still(built["ship"][t_out]), t_local)
                            m_cand = F.measure(name, built["idx"], size,
                                                A._still(built["candidate"][t_out]), t_local)
                            gk = int(np.argmin(np.abs(built["geom"]["ts"] - t_local)))
                            c_local = float(built["geom"]["c"][gk])
                            d, a, guard = _sample_geom_scalar(built["geom"], t_local, c_local)
                            aL, kL, aR, kR = _coef_at(built, t_out, t_local)
                            station_rows.append({
                                "cursor": name, "size": size, "phase_idx": t_out,
                                "t": float(t_local),
                                "ship_s": None if m_ship is None else m_ship["s"],
                                "candidate_s": None if m_cand is None else m_cand["s"],
                                "resolved": None if m_cand is None else m_cand["s_resolved"],
                                "center": c_local, "guard": guard, "alpha": a,
                                "edge_distance": d,
                                "aL": aL, "kL": kL, "aR": aR, "kR": kR,
                                "weight": guard,
                                "reason_if_missing":
                                    built["geom"]["reasons"][gk] if m_cand is None else "ok",
                            })
        except RuntimeError as exc:
            entry["error"] = str(exc)
            data_error = True
        summary["cursors"][name] = entry

    if data_error:
        summary["verdict"] = "FAIL: geometry/reproduction error, see per-cursor 'error'/contract"
        summary["exit"] = 2
    else:
        targets = [n for n in ("AppStarting", "Wait") if n in summary["cursors"]]
        target_ok = all(not summary["cursors"][n]["gate_candidate"] for n in targets)
        guarded = [n for n in cursors if n not in ("AppStarting", "Wait")]
        guard_ok = all(not summary["cursors"][n]["new_failures"] for n in guarded)
        if target_ok and guard_ok and len(targets) >= 1:
            summary["verdict"] = ("PASS: " + ", ".join(targets) +
                                   " clear the real fold gate; no new failures elsewhere")
            summary["exit"] = 0
        else:
            bits = []
            for n in targets:
                if summary["cursors"][n]["gate_candidate"]:
                    bits.append(f"{n}: {'; '.join(summary['cursors'][n]['gate_candidate'])}")
            for n in guarded:
                if summary["cursors"][n]["new_failures"]:
                    bits.append(f"{n} (new): {', '.join(summary['cursors'][n]['new_failures'])}")
            summary["verdict"] = "FAIL: " + " | ".join(bits) if bits else "FAIL: see per-cursor detail"
            summary["exit"] = 1

    with open(os.path.join(out_dir, "summary.json"), "w", newline="\n") as fh:
        json.dump(summary, fh, indent=1, default=lambda o: None)

    if station_rows:
        fields = ["cursor", "size", "phase_idx", "t", "ship_s", "candidate_s",
                  "resolved", "center", "guard", "alpha", "edge_distance",
                  "aL", "kL", "aR", "kR", "weight", "reason_if_missing"]
        with open(os.path.join(out_dir, "stations.csv"), "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(station_rows)

    if visual and not data_error:
        for name in cursors:
            vsize = max(s for s in sizes if s in built_cache and (name, s) in built_cache) \
                if any((name, s) in built_cache for s in sizes) else None
            for size in sizes:
                key = (name, size)
                if key not in built_cache or built_cache[key][0] is None:
                    continue
                built = built_cache[key][0]
                make_contact_sheet(name, size, built, os.path.join(out_dir, f"{name}.png"))
                break  # one representative size per required file name

    print(summary["verdict"])
    for name, entry in summary["cursors"].items():
        if entry.get("error"):
            print(f"  {name}: ERROR {entry['error']}")
            continue
        a = entry["candidate"]
        print(f"  {name}: unres={a.get('unres'):.3f} s_lo={a.get('s_ratio_lo')} "
              f"s_conv={a.get('s_conv'):.3f} curv={a.get('curv'):.3f} "
              f"resolved={a.get('resolved')} gate_fail={entry['gate_candidate']}")
    return summary["exit"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cursors", nargs="+", default=CURSORS_DEFAULT)
    ap.add_argument("--sizes", nargs="+", type=int, default=SIZES_DEFAULT)
    ap.add_argument("--out", default=os.path.join(REPO, ".metrics", "fold-light-oracle"))
    ap.add_argument("--metrics-only", action="store_true")
    ap.add_argument("--verbose-stations", action="store_true")
    ap.add_argument("--visual", action="store_true")
    args = ap.parse_args()

    return run(args.cursors, args.sizes, args.out,
               args.metrics_only, args.verbose_stations,
               args.visual and not args.metrics_only)


if __name__ == "__main__":
    sys.exit(main())

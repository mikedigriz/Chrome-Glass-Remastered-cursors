"""One-file oracle: facet-light model for AppStarting/Wait's fold, in local
chord coordinates instead of a per-pixel RGB field.

Spec: docs/dev/NEXT.md, "AppStarting/Wait: воспроизводимый план одного
oracle-файла" (2026-08-30, on 432a262). The accepted geometry/coefficient
model now lives in cgr.lightanim; this file exercises that production model
against the old per-pixel path and remains the numerical/visual oracle. It does
not touch data/metrics-baseline.json and writes only to its requested out dir.

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

# Only the point-sampling diagnostic below needs these values. Geometry,
# coefficients, reconstruction and pixel remapping come from cgr.lightanim so
# the oracle cannot drift away from the production model it is judging.
_PROTECT = H._RESTEP_PROTECT
_PROTECT_FADE = H._RESTEP_PROTECT_FADE


# --------------------------------------------------------------------------
# Steps E: candidate = ship, blended with canonical+fold_delta inside the
# fold band only.
# --------------------------------------------------------------------------

def build_frames(name, size, verbose=False):
    idx = LA.canonical_index(name)
    facet, err = LA._facet_model(name, size, idx)
    if facet is None:
        return None, err, None
    geom, coef, grid = facet

    _idx2, _base, lin, alpha, raw, n_src, vis, _seen, anchor = LA._setup(
        name, size, LA.HARMONICS, idx)
    phases = LA.paced_phases(name, size)
    out_n = len(phases)

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

    field_light = LA.periodic_at(raw, phases, LA.HARMONICS) - anchor  # production's own field

    ship_frames, candidate_frames, diag = [], [], []
    for t in range(out_n):
        r = field_light[t] * LA._LIGHT_GAIN * vis[..., None]
        ship_lin = LA._lit(lin, r)

        delta_coef = coef_phase[t] - coef_anchor                      # (stations,3,4)
        candidate_lin = LA._facet_apply(lin, ship_lin, delta_coef, geom, grid)

        ship_srgb = V.linear_to_srgb(np.clip(ship_lin, 0.0, 1.0)).astype(np.float64)
        cand_srgb = V.linear_to_srgb(np.clip(candidate_lin, 0.0, 1.0)).astype(np.float64)

        ship_frames.append(np.asarray(H._compose(ship_srgb, alpha), dtype=np.float64))
        candidate_frames.append(np.asarray(H._compose(cand_srgb, alpha), dtype=np.float64))

        if verbose:
            local = LA._facet_reconstruct_local(delta_coef, geom["ns"], geom["c"])
            fold_delta = LA._facet_remap_field(grid, local)
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
    out = {"resolved": [], "cover": 1.0, "unident": 0.0, "unres": 0.0,
           "curv": 0.0,
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
            out["cover"] = min(out["cover"], p["cover"])
            out["unident"] = max(out["unident"], p["unident"])
            if p["unres"] is not None:
                out["unres"] = max(out["unres"], p["unres"])
            out["curv"] = max(out["curv"], p["curv"])
            out["jumps"] = max(out["jumps"], p["jumps"])
            out["rms"] = max(out["rms"], p["rms"])
            ph = phases[t]
            if p["s"] is not None:
                seen.setdefault(t, {})[size] = p["s"]
            for key, r in (("s_ratio", (A._ratio(
                                p["s"], A.author_at(name, size, "s", ph), 1e-3)
                                if p["s"] is not None else None)),
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
            widths = [p["s"] for p in rows.values() if p["s"] is not None]
            if widths:
                out["s_at"][str(size)] = float(np.median(widths))
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


def gate_step(name, st, baseline=None):
    """The exact fold checks tools/analyze.py's gate() runs on a resolved
    multiscale step reading (analyze.py:2381-2410), reused rather than
    re-derived so this oracle's go/no-go is the real gate, not a guess at
    it. With ``baseline`` supplied, a missed absolute target is debt when it is
    no worse than ship and a failure only when it regresses, matching
    analyze.gate. Returns ``(failures, debt)``."""
    T = A.THRESHOLDS
    bad, debt = [], []
    if not st["resolved"]:
        return ["fold_unresolved: no size in the ladder resolved a fold reading"], []

    def check(metric, got, op, want, previous=None):
        misses = got > want if op == ">" else got < want
        if not misses:
            return
        line = f"{metric} {got:.3f} {op} {want}"
        if baseline is None or previous is None:
            bad.append(line)
            return
        tol = abs(previous) * 1e-3 + 1e-6
        worse = got > previous + tol if op == ">" else got < previous - tol
        (bad if worse else debt).append(line)

    check("fold_cover", st["cover"], "<", T["fold_cover"],
          None if baseline is None else baseline["cover"])
    if (baseline is not None
            and st["unident"] > baseline["unident"] * (1.0 + A._RATCHET_SLACK) + 1e-6):
        bad.append(f"fold_unident {st['unident']:.3f} > "
                   f"ship {baseline['unident']:.3f}")
    check("fold_unres", st["unres"], ">", T["fold_unres"],
          None if baseline is None else baseline["unres"])
    lo, hi = st["s_ratio_lo"], st["s_ratio_hi"]
    if lo is not None:
        check("fold_s_thin", lo, "<", T["fold_s_min"],
              None if baseline is None else baseline["s_ratio_lo"])
    if hi is not None:
        check("fold_s_wide", hi, ">", T["fold_s_max"],
              None if baseline is None else baseline["s_ratio_hi"])
    check("fold_s_conv", st["s_conv"], ">", T["fold_s_conv"],
          None if baseline is None else baseline["s_conv"])
    want = max(T["fold_curv"], 2.0 * st["curv_orig"])
    check("fold_curv", st["curv"], ">", want,
          None if baseline is None else baseline["curv"])
    if st["step"] is not None:
        check("fold_step", st["step"], "<", T["fold_step"],
              None if baseline is None else baseline["step"])
    if st["notch"] is not None:
        check("fold_notch", st["notch"], "<", T["fold_notch"],
              None if baseline is None else baseline["notch"])
    return bad, debt


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
    the same fields LA._facet_pixel_grid samples on the whole pixel grid, read
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
    interpolated from production's 96-station grid onto foldfit's."""
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
            bad_cand, debt_cand = gate_step(name, agg_cand, agg_ship)
            bad_ship, _debt_ship = gate_step(name, agg_ship)
            entry["gate_candidate"] = bad_cand
            entry["debt_candidate"] = debt_cand
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
                                "ship_identified": (None if m_ship is None else
                                                    m_ship["s_identified"]),
                                "candidate_identified": (None if m_cand is None else
                                                         m_cand["s_identified"]),
                                "candidate_s_lo": (None if m_cand is None else
                                                   m_cand["s_lo"]),
                                "candidate_s_hi": (None if m_cand is None else
                                                   m_cand["s_hi"]),
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
                  "ship_identified", "candidate_identified", "candidate_s_lo",
                  "candidate_s_hi", "resolved", "center", "guard", "alpha", "edge_distance",
                  "aL", "kL", "aR", "kR", "weight", "reason_if_missing"]
        with open(os.path.join(out_dir, "stations.csv"), "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(station_rows)

    if visual and not data_error:
        for name in cursors:
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
        print(f"  {name}: unident={a.get('unident'):.3f} "
              f"unres={a.get('unres'):.3f} s_lo={a.get('s_ratio_lo')} "
              f"s_conv={a.get('s_conv'):.3f} curv={a.get('curv'):.3f} "
              f"resolved={a.get('resolved')} gate_fail={entry['gate_candidate']} "
              f"debt={entry['debt_candidate']}")
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

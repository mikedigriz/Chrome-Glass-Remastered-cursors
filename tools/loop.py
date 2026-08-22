#!/usr/bin/env python3
"""Driver for the acceptance loop: diagnose, checkpoint, roll back, record.

This does not touch the pipeline. Fixes are code, and code is written by hand;
what gets automated here is the bookkeeping that kept failing around it - which
defect is worst right now, what was already tried and thrown out, and how to
get back to the last state that measured better.

    python tools/loop.py diagnose --fast      what is broken, and what to try
    python tools/loop.py checkpoint pinch-r5  commit + snapshot the metrics
    python tools/loop.py rollback --reason .. undo it and mark the dead end
    python tools/loop.py progress "note"      append the iteration to docs/dev/PROGRESS.md

The rule the loop runs on: one change, then the gate. A change that fails the
gate is rolled back and its name goes into docs/dev/DEAD_ENDS.md, so the next pass does
not spend another iteration rediscovering it. docs/dev/PLAN.md section 5 is 36 attempts
long because nothing wrote them down while they were happening.
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import analyze as A  # noqa: E402

METRICS = os.path.join(ROOT, ".metrics")
PROGRESS = os.path.join(ROOT, "docs", "dev", "PROGRESS.md")
DEAD_ENDS = os.path.join(ROOT, "docs", "dev", "DEAD_ENDS.md")
RATCHET = os.path.join(ROOT, "data", "metrics-baseline.json")

# Every gate failure belongs to exactly one artifact, and every artifact has a
# fixed order of things to try. The point is not that the order is optimal - it
# is that it is decided in advance, so a run does not spend its iterations
# choosing what to do next and does not drift back to an approach that already
# failed.
#
# Each step names where in the pipeline it lands. Guessing which file to open
# is the other half of what these loops waste their time on.
DECISION_TREE = {
    "topology": [
        ("check_trace_input", "art/ai frames feeding trace.py"),
        ("check_snap_corners", "trace.snap_corners, SNAP_R"),
        ("retrace_tolerance", "trace.trace_frame eps"),
        ("escalate", ""),
    ],
    "fold_broken": [
        ("check_fold_chord", "hybrid._fold_chord: is the chord the right one"),
        ("freeze_fold_geometry", "hybrid._fold_offsets, one geometry per cycle"),
        ("widen_fold_band", "hybrid._FOLD_BAND"),
        ("synth_bevel", "hybrid._SYNTH_BEVEL: draw the fold instead of finding it"),
        ("escalate", ""),
    ],
    "staircase_edge": [
        ("check_supersampling", "vectorlib.render ss, floor is 6"),
        ("increase_supersampling", "vectorlib.render ss to 8"),
        ("check_distance_field", "hybrid._chamfer, _edge_distance"),
        ("smooth_field", "hybrid._BEVEL_SMOOTH"),
        ("escalate", ""),
    ],
    "fold_jitter": [
        ("check_temporal", "analyze.temporal_smoothness by zone"),
        ("freeze_lines", "hybrid._freeze_lines, _FREEZE_UNIT"),
        ("check_light_field", "lightanim._LIGHT_UNIT, _MASTER_UNIT: the light "
                              "is what moves, the geometry is one canonical render"),
        ("escalate", ""),
    ],
    "tip_split": [
        ("check_apex", "trace.reconstruct_apex: is the apex where it should be"),
        ("check_facets", "hybrid._FACET_PCT, _FACET_KEEP_RIM: the two surfaces "
                         "must meet at the vertex without eating the rim"),
        ("analytic_tip", "hybrid._tip_pinch from geometry, radius under 4 units"),
        ("escalate", ""),
    ],
    "scale_drift": [
        ("check_alpha_ladder", "hybrid._up_alpha per size vs _LEVEL_REF"),
        ("check_deburr", "hybrid._deburr, _DEBURR_LOGICAL at small sizes"),
        ("check_mask_ss", "vectorlib.render ss at 32"),
        ("escalate", ""),
    ],
    "color_shift": [
        ("check_delta_e", "analyze.delta_e per frame, which frame is worst"),
        ("adjust_reinhard", "hybrid._reinhard against the author's stats"),
        ("adjust_sat_match", "hybrid._sat_match, _sat_anchor"),
        ("reduce_master_weight", "hybrid._BLEND_AI"),
        ("escalate", ""),
    ],
    "ghost_rgb": [
        ("check_hide_ghost", "hybrid._hide_ghost, _GHOST_LO/_GHOST_HI"),
        ("check_bleed", "hybrid._bleed before any resize"),
        ("escalate", ""),
    ],
    "tempo": [
        ("check_spline", "hybrid._spline and its perceptual re-spacing"),
        ("check_pace", "hybrid._PACE_SOLID, _PACE_SAMPLES"),
        ("escalate", ""),
    ],
    "morph_broken": [
        ("check_broken_colour", "hybrid._BROKEN_COLOUR: which frames are substituted"),
        ("check_ai_dropout", "hybrid._ai_dropout, _CRACK_* on the pencil frames"),
        ("author_colour", "fall back to the author's frame for the broken ones"),
        ("escalate", ""),
    ],
}

# Which artifact a gate line belongs to. Longest match wins, so fold_jag lands
# on the staircase rather than on the broken fold.
_ARTIFACT = [
    ("topology", "topology"), ("fold_unmeasured", "topology"),
    ("fold_cover", "fold_broken"), ("fold_step", "fold_broken"),
    ("fold_notch", "fold_broken"),
    ("fold_unres", "staircase_edge"), ("fold_s_thin", "staircase_edge"),
    ("fold_s_wide", "staircase_edge"), ("fold_s_conv", "staircase_edge"),
    ("fold_curv", "staircase_edge"),
    ("inner_tip", "tip_split"),
    ("fold_jitter", "fold_jitter"), ("jitter_unmeasured", "fold_jitter"),
    ("temporal_fold", "fold_jitter"), ("temporal_body", "fold_jitter"),
    ("tip_extreme_contrast", "tip_split"), ("tip_convergence", "tip_split"),
    ("scale_drift", "scale_drift"), ("density", "scale_drift"),
    ("delta_e", "color_shift"),
    ("ghost_rgb", "ghost_rgb"),
    ("cadence", "tempo"), ("sheen_damped", "tempo"),
    ("morph", "morph_broken"),
]

# Topology first: it says the shape the later stages are built on is not the
# shape they think it is, so every number above it is measured on the wrong
# thing. Colour last: it is real, but it is the one class of defect that never
# makes a cursor read as broken.
_WEIGHT = {"topology": 0, "fold_broken": 1, "tip_split": 2, "staircase_edge": 3,
           "fold_jitter": 4, "scale_drift": 5, "morph_broken": 6, "tempo": 7,
           "ghost_rgb": 8, "color_shift": 9}


def git(*args, check=True):
    """Git with the two flags this share always needs.

    The repo lives on SMB, which keeps no unix modes and reports a foreign
    owner: without these every call either refuses with dubious ownership or
    invents mode-only changes that block checkout over nothing."""
    cmd = ["git", "-c", "safe.directory=*", "-c", "core.fileMode=false"] + list(args)
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f"git {' '.join(args)} failed:\n{r.stderr.strip()}")
    return r.stdout.strip()


def classify(line):
    """Artifact name for one gate failure line."""
    metric = line[12:].strip().split()[0] if len(line) > 12 else ""
    for key, art in _ARTIFACT:
        if metric.startswith(key):
            return art
    return "color_shift"


def ratchet():
    """The committed baseline the gate measures movement against, if there is one."""
    if not os.path.exists(RATCHET):
        return None
    with open(RATCHET) as fh:
        return json.load(fh)


def dead_ends():
    """Fix names already tried and rolled back, from docs/dev/DEAD_ENDS.md."""
    if not os.path.exists(DEAD_ENDS):
        return set()
    with open(DEAD_ENDS, encoding="utf-8") as fh:
        return set(re.findall(r"^-\s+`([^`]+)`", fh.read(), re.M))


def next_action(artifact, done):
    for step, where in DECISION_TREE.get(artifact, []):
        if step == "escalate":
            return step, "every step for this artifact is spent, hand it over"
        if step not in done:
            return step, where
    return "escalate", "no steps left"


def cmd_diagnose(args):
    sizes = A.LADDER_FAST if args.fast else A.LADDER_FULL if args.full else A.LADDER
    rep = A.collect(sizes, args.only, args.jobs)
    bad, debt, _, _ = A.gate(rep, ratchet())
    A.show(rep)
    print()
    if debt:
        print(f"debt ({len(debt)}) carried from the baseline, not counted as failures")
        for d in debt:
            print("  " + d)
        print()
    if not bad:
        print("PASS - nothing worse than the baseline. Next is the part no metric closes:")
        print("  512 on the points, six frames of a cycle in a row, the set at real size.")
        return 0

    groups = {}
    for line in bad:
        groups.setdefault(classify(line), []).append(line)
    done = dead_ends()
    print(f"FAIL ({len(bad)}) in {len(groups)} artifacts, worst first\n")
    for art in sorted(groups, key=lambda a: (_WEIGHT.get(a, 99), -len(groups[a]))):
        step, where = next_action(art, done)
        print(f"{art}  ({len(groups[art])} failures)")
        for line in groups[art][:6]:
            print("    " + line)
        if len(groups[art]) > 6:
            print(f"    ... {len(groups[art]) - 6} more")
        print(f"  next: {step}" + (f"  [{where}]" if where else ""))
        if done & {s for s, _ in DECISION_TREE.get(art, [])}:
            print(f"  spent: {', '.join(sorted(done & {s for s, _ in DECISION_TREE[art]}))}")
        print()
    return 1


def _snapshot(name, args):
    os.makedirs(METRICS, exist_ok=True)
    path = os.path.join(METRICS, f"{name}.json")
    rep = A.collect(A.LADDER_FULL if args.full else A.LADDER, None, args.jobs)
    with open(path, "w") as fh:
        json.dump(rep, fh, indent=1)
    return path, A.gate(rep, ratchet())[0]


def cmd_checkpoint(args):
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if branch in ("main", "master"):
        raise SystemExit("refusing to checkpoint onto main, branch first")
    path, bad = _snapshot(args.name, args)
    git("add", "-A")
    if not git("diff", "--cached", "--name-only"):
        print("nothing to commit, snapshot written to " + path)
        return 0
    git("commit", "-m", f"Снял чекпоинт {args.name}")
    sha = git("rev-parse", "--short", "HEAD")
    print(f"checkpoint {args.name} at {sha}, metrics in {path}, "
          f"{'clean' if not bad else str(len(bad)) + ' failures'}")
    return 0


def cmd_rollback(args):
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if branch in ("main", "master"):
        raise SystemExit("refusing to roll back main")
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    os.makedirs(METRICS, exist_ok=True)
    # Never throw the work away outright. A rolled-back approach is still the
    # record of what it did, and twice now a "dead end" turned out to be one
    # good idea wired to one wrong constant.
    patch = os.path.join(METRICS, f"rollback-{stamp}.patch")
    git("add", "-A")
    with open(patch, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(git("diff", "--cached") + "\n")
    sha = git("rev-parse", "--short", "HEAD")
    git("reset", "--hard", "HEAD")
    # reset --hard puts tracked files back but leaves a file the change added as
    # an untracked one, which is a half-rollback and the worst kind. clean
    # without -x, so .metrics and the patch just written survive.
    git("clean", "-fd")
    note(DEAD_ENDS, f"- `{args.fix}` ({datetime.date.today()}, from {sha}) "
                    f"{args.reason}. Patch kept at {os.path.relpath(patch, ROOT)}.")
    print(f"rolled back to {sha}, patch in {patch}, {args.fix} recorded as a dead end")
    return 0


def note(path, line):
    head = ""
    if not os.path.exists(path):
        head = ("# Dead ends\n\nApproaches tried and rolled back, with what they did. "
                "Read before trying anything: the loop skips a fix whose name is "
                "already here.\n\n" if path == DEAD_ENDS else "")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(head + line + "\n")


def cmd_progress(args):
    rep = A.collect(A.LADDER_FAST if args.fast else A.LADDER, args.only, args.jobs)
    bad, debt, _, _ = A.gate(rep, ratchet())
    # Most of these are worst-is-highest. Two are not: a point's contrast and a
    # morph's overlap are both worst at their lowest, and taking a max of them
    # would report the healthiest cursor in the set as the state of the set.
    lower_is_worse = {"morph_iou", "tip_extreme_contrast", "tip_profile",
                      "fold_cover", "fold_s_min_ratio", "fold_step",
                      "fold_notch", "inner_tip"}
    worst = {}
    for name, e in rep.items():
        for k, v in A._flat(e).items():
            if v is None:
                continue
            worst[k] = (min(worst.get(k, 1e9), v) if k in lower_is_worse
                        else max(worst.get(k, 0.0), v))
    cols = ["tip_extreme_contrast", "tip_profile", "tip_convergence",
            "temporal_fold", "fold_jitter",
            "fold_unres", "fold_s_conv", "fold_notch", "inner_tip",
            "delta_e", "scale_drift"]
    head = "| when | what changed | reg | debt | " + " | ".join(cols) + " |"
    rule = "|" + "---|" * (len(cols) + 4)
    if not os.path.exists(PROGRESS):
        note(PROGRESS,
             "# Progress\n\n"
             "One row per iteration. Every number is the worst over all sixteen "
             "cursors, so a row only improves when the weakest one does. "
             "`tip_extreme_contrast` and `tip_profile` are worst at their "
             "lowest; everything else is worst "
             "at its highest.\n\n"
             "`reg` counts values that moved away from a target since the last "
             "committed baseline: that column has to stay at zero. `debt` counts "
             "values that miss a target but have not got worse - that is the "
             "column the work is for, and it starts at 84.\n\n"
             "Targets: drift 0.10 logical units, gap and wander 0, delta_e 5, "
             "temporal 1.0. The full list is THRESHOLDS in tools/analyze.py, "
             "each with why it is that number.\n\n" + head + "\n" + rule)
    elif head not in open(PROGRESS, encoding="utf-8").read():
        # The column set changed - the fold contract was replaced on 2026-08-22.
        # A row written under the old header would line its numbers up with the
        # wrong names and nothing would say so.
        note(PROGRESS, "\n" + head + "\n" + rule)
    note(PROGRESS, f"| {datetime.date.today()} | {args.note} | {len(bad)} | {len(debt)} | "
                   + " | ".join(f"{worst.get(c, float('nan')):.3f}" for c in cols) + " |")
    print(f"{len(bad)} regressions, {len(debt)} debt, row appended to docs/dev/PROGRESS.md")
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--fast", action="store_true")
        p.add_argument("--full", action="store_true")
        p.add_argument("--only", metavar="NAME", action="append")
        p.add_argument("--jobs", metavar="N", type=int, default=1)

    common(sub.add_parser("diagnose"))
    p = sub.add_parser("checkpoint")
    p.add_argument("name")
    common(p)
    p = sub.add_parser("rollback")
    p.add_argument("fix", help="name of the fix being abandoned")
    p.add_argument("--reason", default="failed the gate", help="what it did")
    common(p)
    p = sub.add_parser("progress")
    p.add_argument("note")
    common(p)

    args = ap.parse_args()
    return {"diagnose": cmd_diagnose, "checkpoint": cmd_checkpoint,
            "rollback": cmd_rollback, "progress": cmd_progress}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())

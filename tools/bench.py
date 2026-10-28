#!/usr/bin/env python3
"""Cold/warm build performance baseline: wall, CPU, RSS, phase times, output
hashes. Nothing else in the repo records this - tools/loop.py's .metrics/*.json
snapshots are quality metrics, not performance, and data/metrics-baseline.json
is the quality ratchet. This script never touches either.

    python tools/bench.py                       3 runs: 1 cold, 2 warm
    python tools/bench.py --runs 5 --serial      compare against BUILD_SERIAL=1
    python tools/bench.py --out somewhere.json   default: .metrics/perf/<sha>.json

Each run builds into a scratch directory via `cgr.build --out-dir`, the same
escape hatch BUILD.md documents for experiments, so the committed dist/
packages/assets are never touched. Only the last run's packages/ and assets/
are hashed and kept (as sha256, not the files themselves) - earlier runs exist
only to warm the interpreter and the OS file cache.
"""
import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time

try:
    import resource  # POSIX only
except ImportError:
    resource = None

try:
    import psutil
except ImportError:
    psutil = None

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

PERF_DIR = os.path.join(ROOT, ".metrics", "perf")


def _git_sha():
    r = subprocess.run(["git", "-c", "safe.directory=*", "rev-parse", "--short", "HEAD"],
                        cwd=ROOT, capture_output=True, text=True, timeout=30)
    return r.stdout.strip() or "unknown"


def _clear_pycache():
    for base, dirs, _files in os.walk(ROOT):
        if ".git" in dirs:
            dirs.remove(".git")
        if "__pycache__" in dirs:
            shutil.rmtree(os.path.join(base, "__pycache__"), ignore_errors=True)
            dirs.remove("__pycache__")


def _hash_tree(root):
    out = {}
    if not os.path.isdir(root):
        return out
    for base, _dirs, files in os.walk(root):
        for fn in sorted(files):
            p = os.path.join(base, fn)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            h = hashlib.sha256()
            with open(p, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            out[rel] = {"size": os.path.getsize(p), "sha256": h.hexdigest()}
    return out


def _run(out_dir, perf_json, serial):
    """One build subprocess. Returns {wall_s, cpu_s, rss_peak_mb, phases}."""
    env = dict(os.environ)
    env["BUILD_PERF_JSON"] = perf_json
    if serial:
        env["BUILD_SERIAL"] = "1"
    cmd = [sys.executable, "-m", "cgr.build", "--out-dir", out_dir]
    t0 = time.perf_counter()

    if psutil is not None:
        proc = psutil.Popen(cmd, cwd=ROOT, env=env)
        peak_rss = 0
        cpu_last = {}          # pid -> last user+system seconds seen while alive.
        # A worker that starts and finishes between two 0.2s polls is missed;
        # accepted for a first-cut baseline rather than polling faster.
        while proc.poll() is None:
            try:
                procs = [proc] + proc.children(recursive=True)
            except psutil.Error:
                procs = [proc]
            rss = 0
            for p in procs:
                try:
                    rss += p.memory_info().rss
                    c = p.cpu_times()
                    cpu_last[p.pid] = c.user + c.system
                except psutil.Error:
                    pass
            peak_rss = max(peak_rss, rss)
            time.sleep(0.2)
        wall = time.perf_counter() - t0
        returncode = proc.returncode
        cpu_s = sum(cpu_last.values()) if cpu_last else None
        rss_mb = peak_rss / 1e6 if peak_rss else None
    else:
        r0 = resource.getrusage(resource.RUSAGE_CHILDREN) if resource else None
        res = subprocess.run(cmd, cwd=ROOT, env=env)
        wall = time.perf_counter() - t0
        returncode = res.returncode
        if resource:
            r1 = resource.getrusage(resource.RUSAGE_CHILDREN)
            cpu_s = (r1.ru_utime - r0.ru_utime) + (r1.ru_stime - r0.ru_stime)
            rss_mb = r1.ru_maxrss / 1024.0  # ru_maxrss: KB on Linux, bytes on
            # macOS - this repo's CI is Linux/Debian/Arch, so KB is the read
            # that matters; the macOS number here would overstate by 1024x.
        else:
            cpu_s = rss_mb = None

    if returncode:
        raise SystemExit("build failed, exit %s" % returncode)

    phases = {}
    if os.path.exists(perf_json):
        with open(perf_json, encoding="utf-8") as fh:
            phases = json.load(fh)
    return {"wall_s": round(wall, 2),
            "cpu_s": round(cpu_s, 2) if cpu_s is not None else None,
            "rss_peak_mb": round(rss_mb, 1) if rss_mb is not None else None,
            "phases": {k: round(v, 2) for k, v in phases.items()}}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", type=int, default=3,
                    help="run 0 is cold (__pycache__ cleared first), the rest warm")
    ap.add_argument("--serial", action="store_true",
                    help="BUILD_SERIAL=1 on every run - single-core vs the default")
    ap.add_argument("--out", metavar="FILE", help="default: .metrics/perf/<sha>.json")
    args = ap.parse_args(argv)
    if args.runs < 1:
        raise SystemExit("--runs must be >= 1")

    sha = _git_sha()
    scratch = tempfile.mkdtemp(prefix="cgr-bench-")
    perf_json = os.path.join(scratch, "phases.json")
    runs = []
    artifacts = {}
    try:
        for i in range(args.runs):
            kind = "cold" if i == 0 else "warm"
            if kind == "cold":
                _clear_pycache()
            print("run %d/%d (%s)..." % (i + 1, args.runs, kind))
            if os.path.exists(perf_json):
                os.remove(perf_json)
            build_out = os.path.join(scratch, "build-%d" % i)
            rec = _run(build_out, perf_json, args.serial)
            rec["kind"] = kind
            runs.append(rec)
            print("  wall %.1fs  cpu %s  rss %s MB" % (
                rec["wall_s"], rec["cpu_s"], rec["rss_peak_mb"]))
            if i == args.runs - 1:
                artifacts.update(_hash_tree(os.path.join(build_out, "packages")))
                artifacts.update({"assets/" + k: v for k, v in
                                   _hash_tree(os.path.join(build_out, "assets")).items()})
            shutil.rmtree(build_out, ignore_errors=True)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    report = {
        "sha": sha,
        "date": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "env": {"python": sys.version.split()[0], "platform": platform.platform(),
                "cpu_count": os.cpu_count()},
        "serial": args.serial,
        "rss_cpu_source": "psutil" if psutil else ("getrusage" if resource else None),
        "runs": runs,
        "artifacts": artifacts,
    }

    out_path = args.out or os.path.join(PERF_DIR, "%s.json" % sha)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1, ensure_ascii=False)
    print("wrote", os.path.relpath(out_path, ROOT))


if __name__ == "__main__":
    main()

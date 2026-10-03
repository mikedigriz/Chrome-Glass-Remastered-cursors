"""Frame cache that survives between builds, opt-in (CGR_KEEP_CACHE=1).

A frame is a pure function of the code, the art and the library versions, so
the cache directory is named by a hash of exactly those. Any change gives a new
directory and a full re-render; nothing is ever matched by guess. What is
hashed: cgr/**/*.py, tools/foldfit.py, art/**, data/* (not the metrics files,
which no frame reads), the backend, Python/numpy/Pillow/torch versions.

The build says on one line whether it hit or missed and, on a miss, which group
changed. CGR_CACHE_VERIFY=N re-renders N cached frames from scratch and fails
the build on any difference. At most KEEP directories are kept.
"""
import hashlib
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# local disk, not the repo: the repo may sit on a network share
BASE = os.environ.get("CGR_CACHE_DIR") or os.path.join(
    __import__("tempfile").gettempdir(), "cgr-frame-cache")
KEEP = 2


def _files():
    groups = {"code": [], "art": [], "data": []}
    for top, grp in (("cgr", "code"), ("art", "art"), ("data", "data")):
        for d, _, fs in os.walk(os.path.join(ROOT, top)):
            if "__pycache__" in d:
                continue
            for f in fs:
                if grp == "code" and not f.endswith(".py"):
                    continue
                if grp == "data" and f.startswith("metrics-"):
                    continue
                groups[grp].append(os.path.join(d, f))
    groups["code"].append(os.path.join(ROOT, "tools", "foldfit.py"))
    return groups


def _env():
    import numpy
    import PIL
    try:
        import torch
        tv = torch.__version__
    except ImportError:
        tv = None
    return {"python": sys.version.split()[0], "numpy": numpy.__version__,
            "pillow": PIL.__version__, "torch": tv,
            "backend": os.environ.get("CGR_BACKEND", "cpu")}


def fingerprint():
    """({group: digest}, key)."""
    parts = {}
    for grp, paths in _files().items():
        h = hashlib.sha256()
        for p in sorted(paths):
            h.update(os.path.relpath(p, ROOT).replace("\\", "/").encode())
            with open(p, "rb") as fh:
                h.update(hashlib.sha256(fh.read()).digest())
        parts[grp] = h.hexdigest()
    parts["env"] = hashlib.sha256(json.dumps(_env(), sort_keys=True).encode()).hexdigest()
    key = hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:20]
    return parts, key


def open_cache():
    """(directory, message). A fresh or reused directory for this fingerprint."""
    parts, key = fingerprint()
    path = os.path.join(BASE, key)
    os.makedirs(BASE, exist_ok=True)
    meta = os.path.join(path, "fingerprint.json")
    if os.path.isfile(meta):
        n = sum(1 for f in os.listdir(path) if f.endswith((".npy", ".npz")))
        os.utime(path)
        return path, "frame cache: hit %s, %d files reused" % (key, n)
    prev = []
    for d in os.listdir(BASE):
        try:
            with open(os.path.join(BASE, d, "fingerprint.json")) as fh:
                prev.append((os.path.getmtime(os.path.join(BASE, d)), json.load(fh)))
        except (OSError, ValueError):
            pass
    why = "no earlier cache"
    if prev:
        old = max(prev, key=lambda t: t[0])[1]
        why = "changed: " + (", ".join(g for g in parts if old.get(g) != parts[g]) or "?")
    os.makedirs(path, exist_ok=True)
    tmp = meta + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(parts, fh)
    os.replace(tmp, meta)
    dirs = sorted((os.path.getmtime(os.path.join(BASE, d)), d) for d in os.listdir(BASE))
    for _, d in dirs[:-KEEP]:
        shutil.rmtree(os.path.join(BASE, d), ignore_errors=True)
    return path, "frame cache: miss %s (%s), rendering everything" % (key, why)


def verify(path, count):
    """Re-render `count` cached frames from scratch; (checked, mismatches)."""
    import random
    import numpy as np
    from . import hybrid as H
    files = sorted(f for f in os.listdir(path) if f.startswith(("f_", "b_")) and f.endswith(".npy"))
    random.Random(0).shuffle(files)
    bad = []
    for f in files[:count]:
        kind, rest = f[:-4].split("_", 1)
        name, idx, size = rest.rsplit("_", 2)
        idx, size = int(idx), int(size)
        if kind == "f":
            fresh = H._author_rim(H._frame_chain(name, idx, size), name, idx, size)
        else:
            fresh = H._frame_chain(name, idx, size)
        if not np.array_equal(np.asarray(fresh), np.load(os.path.join(path, f))):
            bad.append(f)
    return min(count, len(files)), bad

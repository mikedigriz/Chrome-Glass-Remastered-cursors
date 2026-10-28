#!/usr/bin/env python3
"""GPU kernel vs CPU reference parity. Exit code 1 on any miss.

    python tools/gpu_parity.py
"""
import os
import sys

import numpy as np
import torch
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cgr.gpu import resample as R  # noqa: E402

PIL_FILTER = {"box": Image.BOX, "bilinear": Image.BILINEAR, "lanczos": Image.LANCZOS}
FAIL = []


def check(name, got, want, tol):
    err = float(np.max(np.abs(got.astype(np.float64) - want.astype(np.float64))))
    ok = err <= tol
    print("%-34s max|d| = %.3g  %s" % (name, err, "ok" if ok else "FAIL (tol %.3g)" % tol))
    if not ok:
        FAIL.append(name)


def resize_f():
    rng = np.random.default_rng(1)
    for kind in PIL_FILTER:
        for n_in, n_out in ((32, 512), (128, 512), (512, 32), (512, 96), (512, 64), (96, 128), (256, 384)):
            a = rng.random((n_in, n_in), dtype=np.float32) * 255
            want = np.asarray(Image.fromarray(a, "F").resize((n_out, n_out), PIL_FILTER[kind]))
            got = R.resize_f(torch.from_numpy(a).cuda(), (n_out, n_out), kind).cpu().numpy()
            check("resize_f %s %d->%d" % (kind, n_in, n_out), got, want, 3.2e-5)  # 1 float32 ulp at 255 is 1.5e-5: order of double sums


def mask_geom():
    import time
    from cgr import hybrid as H, gpu
    worst, tc, tg, n = 0.0, 0.0, 0.0, 0
    for m in H.MANIFEST:
        name = m["name"]
        nfr = len(H.BY_NAME[name]["frames"]) if name in H.BY_NAME else 1
        for idx in range(min(nfr, 3)):
            for size in (32, 48, 64, 96, 128, 256, 512):
                key = H._geom(name, idx)
                gpu.BACKEND = "cpu"; H._mask_geom.cache_clear()
                t = time.time(); c = H._mask_geom(name, key, size); tc += time.time() - t
                gpu.BACKEND = "gpu"; H._mask_geom.cache_clear()
                t = time.time(); g = H._mask_geom(name, key, size); tg += time.time() - t
                worst = max(worst, float(np.abs(c - g).max())); n += 1
    gpu.BACKEND = "cpu"
    check("mask_geom %d masks (cpu %.1fs gpu %.1fs)" % (n, tc, tg), np.array(worst), np.array(0.0), 0.0)


def clear_caches():
    """Every lru_cache in hybrid: a backend swap on warm caches compares the base with itself."""
    from cgr import hybrid as H
    for mod in (H,):
        for v in list(vars(mod).values()):
            if hasattr(v, "cache_clear"):
                v.cache_clear()


def frames(cases):
    import time
    from cgr import gpu, hybrid as H
    for name, idx, size in cases:
        res = {}
        for be in ("cpu", "gpu"):
            gpu.BACKEND = be
            clear_caches()
            t = time.time()
            res[be] = (np.asarray(H.frame_image(name, idx, size), dtype=np.int16), time.time() - t)
        diff = np.abs(res["cpu"][0] - res["gpu"][0])
        check("frame %s %d @%d (cpu %.1fs gpu %.1fs, %d px differ)" % (
            name, idx, size, res["cpu"][1], res["gpu"][1], int((diff > 0).any(-1).sum())),
            np.array(int(diff.max())), np.array(0), 0)
    gpu.BACKEND = "cpu"


def edge_distance():
    import time
    from cgr import hybrid as H, gpu
    worst, tc, tg, n = 0.0, 0.0, 0.0, 0
    for m in H.MANIFEST:
        name = m["name"]
        nfr = len(H.BY_NAME[name]["frames"]) if name in H.BY_NAME else 1
        for idx in range(min(nfr, 2)):
            key = H._geom(name, idx)
            gpu.BACKEND = "cpu"; H._edge_distance_geom.cache_clear()
            t = time.time(); c = H._edge_distance_geom(name, key); tc += time.time() - t
            gpu.BACKEND = "gpu"; H._edge_distance_geom.cache_clear()
            t = time.time(); g = H._edge_distance_geom(name, key); tg += time.time() - t
            worst = max(worst, float(np.abs(c - g).max())); n += 1
    gpu.BACKEND = "cpu"
    check("edge_distance %d fields (cpu %.1fs gpu %.1fs)" % (n, tc, tg), np.array(worst), np.array(0.0), 1e-12)


def foldfit():
    """measure_many on the GPU against measure() station by station."""
    import time
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import foldfit as FF
    from cgr import hybrid as H, gpu
    keys = ("c", "s", "b_lo", "b_hi", "d", "rms", "A", "joint_rms", "profile_score", "s_lo", "s_hi")
    tc = tg = 0.0
    worst, nst, bad = 0.0, 0, 0
    for m in H.MANIFEST:
        name = m["name"]
        nfr = len(H.BY_NAME[name]["frames"]) if name in H.BY_NAME else 1
        for idx in sorted({0, nfr // 2}):
            for size in (64, 128, 256, 512):
                ts = np.linspace(FF.T_LO, FF.T_HI, FF.STATIONS)
                for joint in (False, None):
                    gpu.BACKEND = "cpu"
                    t = time.time()
                    want = [FF.measure(name, idx, size, FF._author_at, x, joint) for x in ts]
                    tc += time.time() - t
                    gpu.BACKEND = "gpu"
                    t = time.time()
                    got = FF.measure_many(name, idx, size, FF._author_at, ts, joint)
                    tg += time.time() - t
                    for w, g in zip(want, got):
                        if (w is None) != (g is None):
                            bad += 1
                            continue
                        if w is None:
                            continue
                        nst += 1
                        if w["s_identified"] != g["s_identified"]:
                            bad += 1
                        for k in keys:
                            worst = max(worst, abs(w[k] - g[k]) / max(1.0, abs(w[k])))
    gpu.BACKEND = "cpu"
    check("foldfit %d stations, %d disagreements (cpu %.0fs gpu %.0fs)" % (nst, bad, tc, tg),
          np.array(worst + bad), np.array(0.0), 1e-5)


def resize_rgba():
    import time
    from PIL import Image
    from cgr import hybrid as H, gpu
    rng = np.random.default_rng(5)
    for src, dst in ((512, 32), (512, 96), (512, 128), (128, 512), (32, 256), (256, 256)):
        for filt in (Image.LANCZOS, Image.BOX, Image.BILINEAR):
            arr = rng.random((src, src, 4)) * 255
            arr[..., 3] *= rng.random((src, src)) > 0.3          # holes, so alpha spans 0..255
            gpu.BACKEND = "cpu"; t = time.time(); wr, wa = H._resize(arr, dst, filt); tc = time.time() - t
            gpu.BACKEND = "gpu"; t = time.time(); gr, ga = H._resize(arr, dst, filt); tg = time.time() - t
            check("resize_rgba %d->%d filt %d (%.3f/%.3f s)" % (src, dst, filt, tc, tg),
                  np.array(max(np.abs(wr - gr).max(), np.abs(wa - ga).max())), np.array(0.0), 3.2e-5 * 255)
    gpu.BACKEND = "cpu"


if __name__ == "__main__":
    if "--foldfit" in sys.argv:
        foldfit()
        sys.exit(1 if FAIL else 0)
    if "--sweep" in sys.argv:
        from cgr import hybrid as H
        cases = []
        for m in H.MANIFEST:
            nm = m["name"]
            nfr = len(H.BY_NAME[nm]["frames"]) if nm in H.BY_NAME else 1
            for size in (32, 96, 256):
                cases.append((nm, nfr // 2, size))
        frames(cases)
        sys.exit(1 if FAIL else 0)
    if "--frames" in sys.argv:
        frames([("Arrow", 0, 512), ("Help", 0, 256), ("Wait", 3, 128), ("Arrow", 0, 64), ("NO", 2, 96)])
        sys.exit(1 if FAIL else 0)
    resize_f()
    resize_rgba()
    edge_distance()
    mask_geom()
    sys.exit(1 if FAIL else 0)

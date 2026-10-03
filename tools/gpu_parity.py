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


def rim_native():
    import time
    from cgr import hybrid as H, gpu
    for name, size in (("Arrow", 512), ("Help", 512), ("Arrow", 64)):
        rgb = H._rgb_pre_rim(name, 0, size)
        out = {}
        for be in ("cpu", "gpu"):
            gpu.BACKEND = be
            t = time.time()
            out[be] = H._rim_native(rgb, name, 0, size)
            out[be + "_t"] = time.time() - t
        check("rim_native %s %d (cpu %.2fs gpu %.2fs)" % (name, size, out["cpu_t"], out["gpu_t"]),
              out["gpu"], out["cpu"], 1e-9)
    gpu.BACKEND = "cpu"


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


def image_stages():
    """Stages that take and return a finished RGBA frame: pixel counts that differ."""
    import time
    from cgr import hybrid as H, gpu
    gpu.BACKEND = "gpu"
    for fn in (H._rim_valley, H._point_along):
        for name in sorted(H._VALLEY_CURSORS):
            for size in (128, 256, 512):
                im = H._rgb_pre_rim  # noqa: F841 (keeps import warm)
                src = H._compose(H._rgb_pre_rim(name, 0, size), H._up_alpha(name, 0, size)
                                 * H._mask(name, 0, size) / 255.0)
                res = {}
                for be in ("cpu", "gpu"):
                    gpu.BACKEND = be
                    t = time.time()
                    res[be] = (np.asarray(fn(src, name, 0, size), dtype=np.int16), time.time() - t)
                diff = np.abs(res["cpu"][0] - res["gpu"][0])
                check("%s %s %d (cpu %.2fs gpu %.2fs, %d px differ)" % (
                    fn.__name__, name, size, res["cpu"][1], res["gpu"][1], int((diff > 0).sum())),
                    np.array(int(diff.max())), np.array(0), 1)
    gpu.BACKEND = "cpu"


def closing():
    from cgr import hybrid as H, gpu
    rng = np.random.default_rng(3)
    for k in (3, 7, 13, 15, 27):
        for shape in ((512, 512), (3, 256, 256), (96, 96)):
            a = (rng.random(shape) * 255).astype(np.uint8)
            gpu.BACKEND = "cpu"; want = H._close_u8(a, k)
            gpu.BACKEND = "gpu"; got = H._close_u8(a, k)
            check("close_u8 k=%d %s" % (k, shape), got, want, 0)
    gpu.BACKEND = "cpu"


def clear_caches():
    """Every lru_cache in hybrid/lightanim: a backend swap on warm caches compares the base with itself."""
    import functools  # noqa: F401
    from cgr import hybrid as H, lightanim as LA
    for mod in (H, LA):
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


def edge_walk():
    import time
    from cgr import hybrid as H, gpu
    rng = np.random.default_rng(7)
    cases = [("SizeAll", 128), ("Cross", 96), ("Arrow", 128), ("Help", 256), ("Wait", 512)]
    for name, size in cases:
        col = rng.random((size, size, 3)) * 255
        gpu.BACKEND = "cpu"; t = time.time(); w = H._along_edge(col, name, 0, size); tc = time.time() - t
        gpu.BACKEND = "gpu"; H._along_edge(col, name, 0, size)
        t = time.time(); g = H._along_edge(col, name, 0, size); tg = time.time() - t
        check("along_edge %s %d (cpu %.2fs gpu %.2fs)" % (name, size, tc, tg), g, w, 1e-9)
        if name in H._EDGE_COMB_CURSORS:
            gpu.BACKEND = "cpu"; t = time.time(); w = H._edge_comb(col, name, 0, size); tc = time.time() - t
            gpu.BACKEND = "gpu"; t = time.time(); g = H._edge_comb(col, name, 0, size); tg = time.time() - t
            check("edge_comb %s %d (cpu %.2fs gpu %.2fs)" % (name, size, tc, tg), g, w, 1e-9)
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
    edge_walk()
    closing()
    edge_distance()
    mask_geom()
    image_stages()
    rim_native()
    sys.exit(1 if FAIL else 0)

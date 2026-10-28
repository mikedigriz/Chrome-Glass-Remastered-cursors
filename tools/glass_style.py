#!/usr/bin/env python3
"""Style against the author, zone by zone, at his 32 px (GLASS_PLAN.md 1c).

The owner's list, each as a number per zone of the surface:

  colour      mean a*, b* (CIELAB) of the glass itself, unpremultiplied
  play        spread of a*, b* inside the zone - colour moving across it
  brightness  mean L*
  brilliance  95th percentile L*
  darkening   5th percentile L*
  alpha       mean opacity - transparency
  peak512     (glass only) the brightest L* the zone reaches at 512 px, unboxed:
              his brightest pixel at 32 is an average over 16x16 of these, so a
              soft render can match every boxed number and still not glisten

And inside the glass (owner, 2026-10-25: layers, homogeneity, fillings):

  fill        per facet, the plane fitted to L*: its slope (L* per LU) and
              direction (degrees, 0 = right, 90 = down), and the alpha slope
  homog       per facet, the spread of L* left after that plane - how evenly
              the facet is filled
  fold        L* of the upper facet minus the lower within 2.5 LU of the fold
  layers      per side, L* against depth from the edge in 0.4 LU bins, and
              the count of bands in it (turns of more than 3 L*)
  inner step  per side, L* 1.0-1.6 LU in minus 0.2-0.8: the step from the
              rim into the facet

And the dirt, read on each render unboxed at 512, where it shows (owner,
2026-10-25: carry what is pleasant, not the dirt - the cursor is Chrome
Glass; 1.1.0 has it too). Lower is cleaner, glass should be ~0:

  blotch      L* spread inside the facets between 0.3 and 2 LU: stains
  grain       L* spread finer than 0.3 LU inside the facets: sand
  tint        a*b* spread between 0.3 and 2 LU inside the facets: colour stains
  rim wave    L* along the rim between 0.3 and 3 LU of arc: a wobbling band
              (his broad highlight along the top side is longer and stays)
  ragged      spread of the edge position along each side, LU: a wavy outline
  junk        alpha beyond 1 LU outside the outline, LU^2: smudge round it

Renders are boxed to 32 in premultiplied linear light first, so every source
is read on the author's own grid. Zones come from cgr.facets at his pixel
centres: the two facets clear of the rim, the rim per side (-0.6..0.9 LU from
the edge), and the notch (2 LU round J).

Usage:
    python tools/glass_style.py Arrow
"""
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from cgr import facets as F  # noqa: E402
from cgr import hybrid as H  # noqa: E402
from cgr import vectorlib as V  # noqa: E402

RELEASE = os.path.join(HERE, "tmp", "look", "v1.1.0")
PROPS = ("a*", "b*", "play", "L*", "L*95", "L*5", "alpha")


def box32(im):
    a = np.asarray(im.convert("RGBA")).astype(np.float64)
    al = a[..., 3] / 255.0
    lin = V.srgb_to_linear(a[..., :3].astype(np.uint8)).astype(np.float64) * al[..., None]
    k = a.shape[0] // 32
    pre = lin.reshape(32, k, 32, k, 3).mean((1, 3))
    A = al.reshape(32, k, 32, k).mean((1, 3))
    return pre / np.maximum(A, 1e-9)[..., None], A


def lab(lin):
    """Linear sRGB (D65) to CIELAB."""
    M = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = lin @ M.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > (6 / 29) ** 3, np.cbrt(xyz), xyz / (3 * (6 / 29) ** 2) + 4 / 29)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]),
                     200 * (f[..., 1] - f[..., 2])], -1)


def zones(name, idx=0):
    s = F.SURFACE[name]
    px, py = F.grid(32, 1)
    sf = F.surface(name, 32, 1, idx)
    sc = F.side_coords(name, px, py, idx)
    o = F.outline(name, idx)
    rim = (sc["dist"] > -0.6) & (sc["dist"] < s["rim"])
    z = {"upper": (sf["facet"] == 1) & (sc["dist"] >= s["rim"]),
         "lower": (sf["facet"] == 2) & (sc["dist"] >= s["rim"])}
    for i in range(len(F.ORDER)):
        z["rim %s%s" % (F.ORDER[i], F.ORDER[(i + 1) % 4])] = rim & (sc["owner"] == i)
    z["notch"] = np.hypot(px - o["J"][0], py - o["J"][1]) < 2.0
    return z


def stats(rgb, A, m):
    m = m & (A > 0.05)
    if not m.any():
        return dict.fromkeys(PROPS, np.nan)
    c = lab(np.clip(rgb[m], 0, 1))
    return {"a*": c[:, 1].mean(), "b*": c[:, 2].mean(),
            "play": float(np.hypot(c[:, 1].std(), c[:, 2].std())),
            "L*": c[:, 0].mean(), "L*95": np.percentile(c[:, 0], 95),
            "L*5": np.percentile(c[:, 0], 5), "alpha": A[m].mean()}


DEPTHS = np.arange(-0.4, 2.01, 0.4)


def _L(rgb):
    return lab(np.clip(rgb, 0, 1))[..., 0]


def _plane(px, py, v, m):
    X = np.stack([np.ones(m.sum()), px[m], py[m]], 1)
    coef, *_ = np.linalg.lstsq(X, v[m], rcond=None)
    return coef, v[m] - X @ coef


def _bands(prof, turn=3.0):
    """Turns of more than `turn` in a profile: a band is a run between two."""
    p = [v for v in prof if np.isfinite(v)]
    n, ext, d = 0, p[0], 0
    for v in p[1:]:
        if d >= 0 and v < ext - turn:
            n, d, ext = n + (d > 0), -1, v
        elif d <= 0 and v > ext + turn:
            n, d, ext = n + (d < 0), 1, v
        elif (d >= 0 and v > ext) or (d <= 0 and v < ext):
            ext = v
    return n + 1


def inner(name, rgb, A, idx=0):
    px, py = F.grid(32, 1)
    sf = F.surface(name, 32, 1, idx)
    sc = F.side_coords(name, px, py, idx)
    o = F.outline(name, idx)
    s = F.SURFACE[name]
    L = _L(rgb)
    ok = A > 0.05
    out = {}
    for k, zn in ((1, "upper"), (2, "lower")):
        m = (sf["facet"] == k) & (sc["dist"] >= s["rim"]) & ok
        (c0, cx, cy), res = _plane(px, py, L, m)
        (_a0, ax, ay), _r = _plane(px, py, A, m)
        out[zn] = {"slope": np.hypot(cx, cy), "dir": np.degrees(np.arctan2(cy, cx)),
                   "homog": res.std(), "a-slope": np.hypot(ax, ay) * 100}
    a, j = np.asarray(o["A"]), np.asarray(o["J"])
    e = (j - a) / np.hypot(*(j - a))
    near = np.abs((px - a[0]) * -e[1] + (py - a[1]) * e[0]) < 2.5
    up = near & (sf["facet"] == 1) & (sc["dist"] >= s["rim"]) & ok
    lo = near & (sf["facet"] == 2) & (sc["dist"] >= s["rim"]) & ok
    out["fold"] = L[up].mean() - L[lo].mean()
    for i in range(len(F.ORDER)):
        side = (sc["owner"] == i) & ok
        prof = []
        for dpt in DEPTHS:
            m = side & (np.abs(sc["dist"] - dpt) < 0.2)
            prof.append(np.average(L[m], weights=A[m]) if m.any() else np.nan)
        deep = side & (sc["dist"] >= 1.0) & (sc["dist"] < 1.6)
        rim = side & (sc["dist"] >= 0.2) & (sc["dist"] < 0.8)
        out["rim %s%s" % (F.ORDER[i], F.ORDER[(i + 1) % 4])] = {
            "profile": prof, "bands": _bands(prof),
            "step": (L[deep].mean() - L[rim].mean()) if deep.any() and rim.any() else np.nan}
    return out


DIRT = ("blotch", "grain", "tint", "rim wave", "ragged", "junk")


def _nblur(v, m, sigma):
    from cgr.glass import _blur
    return _blur(v * m, sigma) / np.maximum(_blur(m, sigma), 1e-6)


def dirt(name, im, idx=0):
    a = np.asarray(im.convert("RGBA")).astype(np.float64)
    n = a.shape[0]
    lu = n / 32.0
    al = a[..., 3] / 255.0
    c = lab(V.srgb_to_linear(a[..., :3].astype(np.uint8)).astype(np.float64))
    px, py = F.grid(n, 1)
    sf = F.surface(name, n, 1, idx)
    sc = F.side_coords(name, px, py, idx)
    rim = F.SURFACE[name]["rim"]
    # per facet: grain is what a 0.3 LU blur takes off, stains what is left
    # off a smooth (quadratic) surface after it; a blur for the broad level
    # read the facet's own curvature at its borders as stains
    res = {k: [] for k in range(3)}
    grain = []
    for f in (1, 2):
        m = ((sf["facet"] == f) & (sc["dist"] > rim + 0.5) & (al > 0.05)).astype(np.float64)
        sel = m > 0
        x, y = px[sel] / 16 - 1, py[sel] / 16 - 1
        X = np.column_stack([np.ones_like(x), x, y, x * x, x * y, y * y])
        for k in range(3):
            fine = _nblur(c[..., k], m, 0.3 * lu)[sel]
            if k == 0:
                grain.append(c[..., 0][sel] - fine)
            res[k].append(fine - X @ np.linalg.lstsq(X, fine, rcond=None)[0])
    res = {k: np.concatenate(v) for k, v in res.items()}
    out = {"blotch": res[0].std(), "grain": np.concatenate(grain).std(),
           "tint": np.hypot(res[1].std(), res[2].std())}
    # along the rim, binned on arc length
    _st, total = F.perimeter(name, idx)
    r = (sc["dist"] > 0) & (sc["dist"] < rim) & (al > 0.05)
    nb = int(total / 0.1)
    b = (sc["s"][r] / total * nb).astype(int) % nb
    wsum = np.bincount(b, al[r], nb)
    prof = np.bincount(b, c[..., 0][r] * al[r], nb) / np.maximum(wsum, 1e-9)
    ok = wsum > 0

    def circ(v, sig):
        k = int(3 * sig)
        g = np.exp(-0.5 * (np.arange(-k, k + 1) / sig) ** 2)
        num = np.convolve(np.r_[v[-k:], v, v[:k]] * np.r_[ok[-k:], ok, ok[:k]], g, "valid")
        den = np.convolve(np.r_[ok[-k:], ok, ok[:k]] * 1.0, g, "valid")
        return num / np.maximum(den, 1e-9)
    prof = np.where(ok, prof, 0)
    out["rim wave"] = (circ(prof, 3) - circ(prof, 30))[ok].std()
    # the edge: alpha integrated across the normal per 0.25 LU of arc, as an offset
    e = (sc["dist"] > -1.5) & (sc["dist"] < 1.0)
    cs = F.corner_s(name, idx)
    near_c = np.min([np.abs((sc["s"] - v + total / 2) % total - total / 2) for v in cs.values()], 0)
    e &= near_c > 2.0
    nb = int(total / 0.25)
    b = (sc["s"][e] / total * nb).astype(int) % nb
    cnt = np.bincount(b, None, nb)
    pos = np.bincount(b, al[e], nb) / (lu * lu) / (total / nb)
    side = np.bincount(b, sc["owner"][e], nb) / np.maximum(cnt, 1)
    res = []
    for i in range(len(F.ORDER)):
        sel = (cnt > 0) & (np.round(side) == i)
        if sel.sum() > 3:
            res.append(pos[sel] - np.median(pos[sel]))
    out["ragged"] = np.concatenate(res).std()
    out["junk"] = al[sc["dist"] < -1.0].sum() / (lu * lu)
    return out


CHROME = ("layers", "weave", "taper", "contrast", "edge")


def chrome(name, im, idx=0):
    """The blades of the rim at 512 (owner, 2026-10-25: blades, layers of
    blades, weaving, chrome; and we build too linearly). Per 0.25 LU of arc
    the L* profile across the rim, 0..2 LU in from the edge:

      layers    bright ridges across the rim (prominence 4 L*), mean count
      weave     how far the brightest ridge wanders in depth along a side, LU
                (std about the side's own mean): blades crossing and swapping
      taper     coefficient of variation of the rim's width along a side, the
                width taken to the last point 4 L* off the facet's level:
                0 is a frame of one width, blades taper
      contrast  max - min L* across the rim: chrome reflects hard
      edge      steepest L* step across, L* per LU: how keen the blade is
    """
    a = np.asarray(im.convert("RGBA")).astype(np.float64)
    n = a.shape[0]
    al = a[..., 3] / 255.0
    L = lab(V.srgb_to_linear(a[..., :3].astype(np.uint8)).astype(np.float64))[..., 0]
    px, py = F.grid(n, 1)
    sc = F.side_coords(name, px, py, idx)
    _st, total = F.perimeter(name, idx)
    cs = F.corner_s(name, idx)
    near_c = np.min([np.abs((sc["s"] - v + total / 2) % total - total / 2) for v in cs.values()], 0)
    dstep = 0.1
    nd = 22
    sel = (sc["dist"] >= 0) & (sc["dist"] < nd * dstep) & (al > 0.3) & (near_c > 1.5)
    nb = int(total / 0.25)
    sb = (sc["s"][sel] / total * nb).astype(int) % nb
    db = (sc["dist"][sel] / dstep).astype(int)
    idx2 = sb * nd + db
    cnt = np.bincount(idx2, None, nb * nd).reshape(nb, nd)
    prof = (np.bincount(idx2, L[sel], nb * nd).reshape(nb, nd) / np.maximum(cnt, 1))
    own = np.bincount(sb, sc["owner"][sel], nb) / np.maximum(np.bincount(sb, None, nb), 1)
    full = (cnt > 0).all(1)
    rows = {"layers": [], "ridge": [], "width": [], "contrast": [], "edge": [], "side": []}
    for i in np.nonzero(full)[0]:
        p = prof[i]
        pk = [j for j in range(1, nd - 1) if p[j] >= p[j - 1] and p[j] > p[j + 1]
              and p[j] - max(p[:j].min(), p[j + 1:].min()) > 4]
        lvl = p[-4:].mean()
        off = np.nonzero(np.abs(p[:-4] - lvl) > 4)[0]
        rows["layers"].append(len(pk))
        rows["ridge"].append((np.argmax(p[:-4]) + 0.5) * dstep)
        rows["width"].append(((off.max() + 1) * dstep) if len(off) else 0.0)
        rows["contrast"].append(p.max() - p.min())
        rows["edge"].append(np.abs(np.diff(p)).max() / dstep)
        rows["side"].append(int(round(own[i])))
    r = {k: np.asarray(v, float) for k, v in rows.items()}
    weave, taper = [], []
    for i in range(len(F.ORDER)):
        m = r["side"] == i
        if m.sum() > 3:
            weave.append(r["ridge"][m].std())
            taper.append(r["width"][m].std() / max(r["width"][m].mean(), 1e-6))
    return {"layers": r["layers"].mean(), "weave": np.mean(weave), "taper": np.mean(taper),
            "contrast": r["contrast"].mean(), "edge": r["edge"].mean()}


def sources(name, idx=0):
    au = np.asarray(H.original(name, idx)).astype(np.float64)
    out = {"author": (V.srgb_to_linear(au[..., :3].astype(np.uint8)).astype(np.float64),
                      au[..., 3] / 255.0)}
    from cgr import glass as G
    out["glass"] = box32(G.frame_image(name, idx, 128))
    out["HEAD"] = box32(H.frame_image(name, idx, 128))
    rel = os.path.join(RELEASE, "%s_%d_128.png" % (name, idx))
    if os.path.exists(rel):
        out["1.1.0"] = box32(Image.open(rel))
    return out


def peak512(name, idx=0):
    """{zone: max L*} of the glass render at 512, zones blown up NEAREST."""
    from cgr import glass as G
    a = np.asarray(G.frame_image(name, idx, 512)).astype(np.float64)
    L = lab(V.srgb_to_linear(a[..., :3].astype(np.uint8)).astype(np.float64))[..., 0]
    ok = a[..., 3] > 25
    return {zn: float(L[np.kron(m, np.ones((16, 16), bool)) & ok].max())
            for zn, m in zones(name, idx).items()}


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "Arrow"
    src = sources(name)
    pk = peak512(name)
    au_rgb, au_a = src["author"]
    au_L = lab(np.clip(au_rgb, 0, 1))[..., 0]
    for zn, m in zones(name).items():
        mm = m & (au_a > 0.05)
        print("%s (%d px)  peak: author 32 %.1f, glass 512 %.1f"
              % (zn, int(m.sum()), au_L[mm].max(), pk[zn]))
        print("  %-7s" % "" + "".join("%8s" % p for p in PROPS))
        for k, (rgb, A) in src.items():
            st = stats(rgb, A, m)
            print("  %-7s" % k + "".join("%8.1f" % st[p] if p != "alpha" else "%8.2f" % st[p]
                                         for p in PROPS))
    ins = {k: inner(name, rgb, A) for k, (rgb, A) in src.items()}
    print("\ninside the glass")
    print("  %-7s" % "" + "".join("%14s" % h for h in
                                  ("upper fill", "upper homog", "lower fill", "lower homog", "fold")))
    for k, d in ins.items():
        print("  %-7s" % k + "".join([
            "%8.2f @%4.0f" % (d["upper"]["slope"], d["upper"]["dir"]), "%14.1f" % d["upper"]["homog"],
            "%8.2f @%4.0f" % (d["lower"]["slope"], d["lower"]["dir"]), "%14.1f" % d["lower"]["homog"],
            "%14.1f" % d["fold"]]))
    print("  alpha slope, %% per LU: " + ", ".join(
        "%s %.2f/%.2f" % (k, d["upper"]["a-slope"], d["lower"]["a-slope"]) for k, d in ins.items()))
    print("\ndirt at 512 (lower is cleaner)")
    print("  %-7s" % "" + "".join("%10s" % h for h in DIRT))
    from cgr import glass as G
    r512 = {"glass": G.frame_image(name, 0, 512), "HEAD": H.frame_image(name, 0, 512)}
    rel = os.path.join(RELEASE, "%s_%d_512.png" % (name, 0))
    if os.path.exists(rel):
        r512["1.1.0"] = Image.open(rel)
    for k, im in r512.items():
        d = dirt(name, im)
        print("  %-7s" % k + "".join("%10.2f" % d[h] for h in DIRT))
    print("\nchrome blades at 512")
    print("  %-7s" % "" + "".join("%10s" % h for h in CHROME))
    for k, im in r512.items():
        d = chrome(name, im)
        print("  %-7s" % k + "".join("%10.2f" % d[h] for h in CHROME))
    print("\nlayers: L* by depth from the edge, LU " + " ".join("%5.1f" % x for x in DEPTHS))
    for zn in [z for z in ins["author"] if z.startswith("rim")]:
        print("  " + zn)
        for k, d in ins.items():
            r = d[zn]
            print("    %-7s" % k + " ".join("%5.0f" % v if np.isfinite(v) else "    ." for v in r["profile"])
                  + "   bands %d  step %+5.1f" % (r["bands"], r["step"]))


if __name__ == "__main__":
    main()

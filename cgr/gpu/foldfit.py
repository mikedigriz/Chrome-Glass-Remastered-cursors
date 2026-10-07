"""The width search of tools/foldfit.py for a whole frame's stations at once.

foldfit._profile_cpu fits one station: per rung of S_GRID, every candidate
centre is a row of a 2- or 3-column least squares with soft-L1 reweighting.
Stations differ in length (n) and in the number of candidate centres (cs), so
they are padded to one box and a mask keeps the padding out of every sum; a
masked-out entry is multiplied by exactly 0.0 and a valid one by exactly 1.0,
so the arithmetic on real samples is unchanged.

The work is launch-bound, not arithmetic-bound: a fit is a few thousand tiny
kernels. So the normal equations are one batched matmul each (columns stacked
as (..., c, N)), and a group of rungs of S_GRID runs together as one more batch
axis, whose size is set by the temporary-tensor budget (CGR_GPU_CHUNK_MB).
"""
import numpy as np
import torch

from . import FIT_MB, ops, rows_for

_EPS = np.finfo(np.float64).eps


def _products(cols, y):
    """What the normal equations need that does not depend on the weights, as
    one stack (..., rows, N): u.u, u.v, v.v, u.y, v.y and, with a third column,
    u.w, v.w, w.w, w.y. The two-column system is the first five rows. Summing
    them against the weights is then one batched matmul, which on this device is
    four times faster than a product and a sum per entry."""
    rows = [cols[0] * cols[0], cols[0] * cols[1], cols[1] * cols[1], cols[0] * y, cols[1] * y]
    if len(cols) == 3:
        rows += [cols[0] * cols[2], cols[1] * cols[2], cols[2] * cols[2], cols[2] * y]
    return torch.stack(rows, -2)


def _normal(pre, wm, c):
    """Gram matrix and right-hand side of the weighted least squares: the
    products summed over the samples, as g[i][j] and r[i]."""
    sums = torch.matmul(pre[..., :5 if c == 2 else 9, :], wm[..., None])[..., 0]
    s = sums.unbind(-1)
    g = [[s[0], s[1]], [s[1], s[2]]]
    r = [s[3], s[4]]
    if c == 3:
        g = [[s[0], s[1], s[5]], [s[1], s[2], s[6]], [s[5], s[6], s[7]]]
        r = [s[3], s[4], s[8]]
    return g, r


def _solve(pre, y, cols, weights, m):
    wm = m if weights is None else weights * m
    g, r = _normal(pre, wm, 2)
    Suu, Suv, Svv = g[0][0], g[0][1], g[1][1]
    Suy, Svy = r
    det = Suu * Svv - Suv * Suv
    ok = det.abs() > 1e-12
    det = torch.where(ok, det, torch.ones_like(det))
    a = (Svv * Suy - Suv * Svy) / det
    b = (Suu * Svy - Suv * Suy) / det
    res = y - (a[..., None] * cols[0] + b[..., None] * cols[1])
    return a, b, res, ok


def _solve3(pre, y, cols, weights, m):
    """The 3-column fit by Cramer's rule: a batched LU solve of 3x3 systems
    costs milliseconds a call on the device, nine products do not."""
    wm = m if weights is None else weights * m
    g, r = _normal(pre, wm, 3)
    c00 = g[1][1] * g[2][2] - g[1][2] * g[2][1]
    c01 = g[1][2] * g[2][0] - g[1][0] * g[2][2]
    c02 = g[1][0] * g[2][1] - g[1][1] * g[2][0]
    det = g[0][0] * c00 + g[0][1] * c01 + g[0][2] * c02
    ok = det.abs() > 1e-12
    det = torch.where(ok, det, torch.ones_like(det))
    r0, r1, r2 = r
    x0 = (r0 * c00 + g[0][1] * (g[1][2] * r2 - r1 * g[2][2])
          + g[0][2] * (r1 * g[2][1] - g[1][1] * r2)) / det
    x1 = (g[0][0] * (r1 * g[2][2] - g[1][2] * r2) + r0 * c01
          + g[0][2] * (g[1][0] * r2 - r1 * g[2][0])) / det
    x2 = (g[0][0] * (g[1][1] * r2 - r1 * g[2][1])
          + g[0][1] * (r1 * g[2][0] - g[1][0] * r2) + r0 * c02) / det
    x0 = torch.where(ok, x0, torch.zeros_like(x0))
    x1 = torch.where(ok, x1, torch.zeros_like(x1))
    x2 = torch.where(ok, x2, torch.zeros_like(x2))
    res = y - (x0[..., None] * cols[0] + x1[..., None] * cols[1] + x2[..., None] * cols[2])
    return x0, x1, x2, res, ok


def _soft_l1_fit(u, v, y, scale, m, nvalid, passes):
    cols = (u, v)
    pre = _products(cols, y)
    a, b, res, ok = _solve(pre, y, cols, None, m)
    for _ in range(passes):
        z = res / scale
        weights = 1.0 / torch.sqrt(1.0 + z * z)
        a2, b2, res2, ok2 = _solve(pre, y, cols, weights, m)
        use = ok & ok2
        a = torch.where(use, a2, a)
        b = torch.where(use, b2, b)
        res = torch.where(use[..., None], res2, res)
        ok = ok & ok2
    z2 = (res / scale) ** 2
    rho = 2.0 * (torch.sqrt(1.0 + z2) - 1.0)
    score = scale[..., 0] * torch.sqrt((rho * m).sum(-1) / nvalid)
    return a, b, torch.zeros_like(a), res, ok, score


def _soft_l1_joint(u, v, w3, y, scale, m, nvalid, passes):
    cols = (u, v, w3)
    pre = _products(cols, y)
    a2, b2, res2, ok2 = _solve(pre, y, cols, None, m)
    a3, b3, A3, res3, ok3 = _solve3(pre, y, cols, None, m)
    for _ in range(passes):
        z = res2 / scale
        n2, m2, r2, k2 = _solve(pre, y, cols, 1.0 / torch.sqrt(1.0 + z * z), m)
        use = ok2 & k2
        a2 = torch.where(use, n2, a2)
        b2 = torch.where(use, m2, b2)
        res2 = torch.where(use[..., None], r2, res2)
        ok2 = use
        z = res3 / scale
        n3, m3, q3, r3, k3 = _solve3(pre, y, cols, 1.0 / torch.sqrt(1.0 + z * z), m)
        use = ok3 & k3
        a3 = torch.where(use, n3, a3)
        b3 = torch.where(use, m3, b3)
        A3 = torch.where(use, q3, A3)
        res3 = torch.where(use[..., None], r3, res3)
        ok3 = use
    zero = 32.0 * _EPS * torch.maximum(torch.ones_like(a3), torch.maximum(a3.abs(), b3.abs()))
    A3 = torch.where((A3 >= 0.0) & (A3 <= zero), torch.zeros_like(A3), A3)
    take3 = ok3 & (A3 > 0.0)
    a = torch.where(take3, a3, a2)
    b = torch.where(take3, b3, b2)
    A = torch.where(take3, A3, torch.zeros_like(A3))
    res = torch.where(take3[..., None], res3, res2)
    ok = torch.where(take3, ok3, ok2)
    rho = 2.0 * (torch.sqrt(1.0 + (res / scale) ** 2) - 1.0)
    return a, b, A, res, ok, scale[..., 0] * torch.sqrt((rho * m).sum(-1) / nvalid)


def _interp_dipole(x, xp, fp):
    """np.interp(x, xp, fp, left=0, right=0) on a tensor of any shape."""
    j = torch.clamp(torch.bucketize(x, xp, right=True) - 1, 0, len(xp) - 2)
    slope = (fp[j + 1] - fp[j]) / (xp[j + 1] - xp[j])
    out = slope * (x - xp[j]) + fp[j]
    out = torch.where(x == xp[-1], fp[-1].expand_as(out), out)
    return torch.where((x < xp[0]) | (x > xp[-1]), torch.zeros_like(out), out)


def profiles(preps, s_grid, lam, passes, dipole, pitch, x0):
    """Per station, foldfit._profile_cpu's list of (score, s, c, a, b, res, A,
    c_path)."""
    out = [None] * len(preps)
    for use_dipole in (False, True):
        idx = [i for i, p in enumerate(preps) if bool(p["use_dipole"]) == use_dipole]
        if idx:
            for i, prof in zip(idx, _batch([preps[i] for i in idx], use_dipole,
                                           s_grid, lam, passes, dipole, pitch, x0)):
                out[i] = prof
    return out


def _batch(ps, use_dipole, s_grid, lam, passes, dipole, pitch, x0):
    B = len(ps)
    N = max(len(p["n"]) for p in ps)
    K = max(len(p["cs"]) for p in ps)
    n_, y_, m_ = np.zeros((B, N)), np.zeros((B, N)), np.zeros((B, N))
    cs_, cm_ = np.zeros((B, K)), np.zeros((B, K))
    for b, p in enumerate(ps):
        k, c = len(p["n"]), len(p["cs"])
        n_[b, :k], y_[b, :k], m_[b, :k] = p["n"], p["y"], 1.0
        cs_[b, :c], cm_[b, :c] = p["cs"], 1.0
    # axes: (station, rung, candidate centre, sample)
    n = ops.t(n_)[:, None, None, :]
    y = ops.t(y_)[:, None, None, :]
    m = ops.t(m_)[:, None, None, :]
    cs = ops.t(cs_)[:, None, :]                                          # (B, 1, K)
    cmask = (ops.t(cm_) > 0)[:, None, :]
    scale = ops.t([p["robust_scale"] for p in ps])[:, None, None, None]
    nvalid = m.sum(-1)                                                   # (B, 1, 1)
    xp = ops.t(np.arange(len(dipole)) * pitch + x0)
    fp = ops.t(dipole)
    fit = _soft_l1_joint if use_dipole else _soft_l1_fit
    ar = torch.arange(B, device=ops.DEV)[:, None]
    group = max(1, rows_for(B * K * N * 14, mb=FIT_MB))
    rungs = ops.t(s_grid)
    got = []
    for r0 in range(0, len(s_grid), group):
        s = rungs[r0:r0 + group][None, :, None, None]                    # (1, R, 1, 1)
        d = n - cs[..., None]                                            # (B, 1, K, N)
        phi = 0.5 * (1.0 + torch.tanh(d / s))                            # (B, R, K, N)
        u = 1.0 - phi
        w3 = _interp_dipole(d, xp, fp).expand_as(phi) if use_dipole else None
        a, b, A, res, ok, rscore = fit(u, phi, w3, y, scale, m, nvalid, passes) if use_dipole \
            else fit(u, phi, y, scale, m, nvalid, passes)
        score = rscore + lam * cs.abs()
        score = torch.where(ok & cmask, score, torch.full_like(score, float("inf")))
        i = torch.argmin(score, -1)                                      # (B, R)
        rr = torch.arange(score.shape[1], device=ops.DEV)[None, :]
        # foldfit._c_path: soft minimum over the candidates, tol one standard error
        tol = torch.clamp(scale[..., 0] / torch.sqrt(torch.clamp(nvalid, min=1.0)), min=1e-9)
        fin = torch.isfinite(score)
        low = torch.where(fin, score, torch.full_like(score, float("inf"))).min(-1, keepdim=True).values
        w = torch.where(fin, torch.exp(-(torch.where(fin, score, low) - low) / tol),
                        torch.zeros_like(score))
        cp = (w * cs).sum(-1) / torch.clamp(w.sum(-1), min=1e-30)          # (B, R)
        got.append(tuple(t_.transpose(0, 1) for t_ in (
            score[ar, rr, i], cs.expand(-1, score.shape[1], -1)[ar, rr, i], a[ar, rr, i],
            b[ar, rr, i], A[ar, rr, i], res[ar, rr, i], cp)))
    sc, cc, aa, bb, AA, rr_, cp_ = (torch.cat([g[k] for g in got]).cpu().numpy() for k in range(7))
    result = []
    for b, p in enumerate(ps):
        k = len(p["n"])
        prof = []
        for r, s in enumerate(s_grid):
            if np.isfinite(sc[r, b]):
                prof.append((float(sc[r, b]), float(s), float(cc[r, b]), float(aa[r, b]),
                             float(bb[r, b]), rr_[r, b, :k].copy(), float(AA[r, b]),
                             float(cp_[r, b])))
        result.append(prof)
    return result

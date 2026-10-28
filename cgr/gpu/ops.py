"""Torch twins of hybrid.py's small numpy helpers, same arithmetic order."""
import torch

from .. import vectorlib as V

DEV = torch.device("cuda")


def t(a, dtype=torch.float64):
    return torch.as_tensor(a, device=DEV).to(dtype)


def sample(field, sx, sy):
    """hybrid._sample: bilinear lookup of field (n, n, C) at float coords, edge-clamped."""
    n = field.shape[0]
    sx = torch.clamp(sx, 0, n - 1.001)
    sy = torch.clamp(sy, 0, n - 1.001)
    x0, y0 = sx.to(torch.int64), sy.to(torch.int64)
    fx, fy = (sx - x0)[..., None], (sy - y0)[..., None]
    x1, y1 = torch.clamp(x0 + 1, max=n - 1), torch.clamp(y0 + 1, max=n - 1)
    return ((field[y0, x0] * (1 - fx) + field[y0, x1] * fx) * (1 - fy)
            + (field[y1, x0] * (1 - fx) + field[y1, x1] * fx) * fy)


def box1(a, r, axis):
    a = a.transpose(0, axis)
    pad = torch.cat([a[:1].repeat_interleave(r, 0), a, a[-1:].repeat_interleave(r, 0)], 0)
    c = torch.cumsum(pad, 0)
    out = (c[2 * r:] - torch.cat([torch.zeros_like(c[:1]), c[:-2 * r - 1]], 0)) / (2.0 * r + 1.0)
    return out.transpose(0, axis)


def smooth1(a, unit, size):
    r = max(0, int(round(unit * size / V.LOGICAL / 3.0)))
    out = a.to(torch.float64)
    if r < 1:
        return out
    for _ in range(3):
        out = box1(box1(out, r, 0), r, 1)
    return out


def grid(size):
    """(py, px) like np.mgrid[0:size, 0:size] as float64."""
    ax = torch.arange(size, device=DEV, dtype=torch.float64)
    return ax[:, None].expand(size, size), ax[None, :].expand(size, size)

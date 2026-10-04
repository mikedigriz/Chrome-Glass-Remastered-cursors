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


def sample1(field, sx, sy):
    return sample(field[..., None], sx, sy)[..., 0]


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


def close_u8(a, k):
    """PIL MaxFilter(k) then MinFilter(k) on uint8 planes (..., H, W), edges included."""
    import torch.nn.functional as F
    x = torch.as_tensor(a, device=DEV)
    lead = x.shape[:-2]
    x = x.reshape(-1, 1, *x.shape[-2:]).to(torch.float32)
    r = k // 2
    x = F.max_pool2d(x, k, 1, r)
    x = -F.max_pool2d(-x, k, 1, r)
    return x.reshape(*lead, *x.shape[-2:]).to(torch.uint8).cpu().numpy()


def band_bilinear(img, x, y):
    """hybrid._band_bilinear (floor, clip to n-1.001, its own sum order)."""
    h, w = img.shape[:2]
    x = torch.clamp(x, 0, w - 1.001)
    y = torch.clamp(y, 0, h - 1.001)
    x0, y0 = torch.floor(x).to(torch.int64), torch.floor(y).to(torch.int64)
    fx, fy = x - x0, y - y0
    if img.ndim == 3:
        fx, fy = fx[..., None], fy[..., None]
    return (img[y0, x0] * (1 - fx) * (1 - fy) + img[y0, x0 + 1] * fx * (1 - fy)
            + img[y0 + 1, x0] * (1 - fx) * fy + img[y0 + 1, x0 + 1] * fx * fy)


def band_cubic(img, x, y):
    """hybrid._band_cubic: Catmull-Rom, the same clip and tap order."""
    h, w = img.shape[:2]
    x = torch.clamp(x, 0, w - 1.001)
    y = torch.clamp(y, 0, h - 1.001)
    x0, y0 = torch.floor(x).to(torch.int64), torch.floor(y).to(torch.int64)

    def taps(t):
        t2, t3 = t * t, t * t * t
        return ((-t3 + 2 * t2 - t) / 2, (3 * t3 - 5 * t2 + 2) / 2,
                (-3 * t3 + 4 * t2 + t) / 2, (t3 - t2) / 2)

    wx, wy = taps(x - x0), taps(y - y0)
    if img.ndim == 3:
        wx, wy = [v[..., None] for v in wx], [v[..., None] for v in wy]
    out = 0.0
    for j in range(4):
        yi = torch.clamp(y0 - 1 + j, 0, h - 1)
        row = sum(img[yi, torch.clamp(x0 - 1 + i, 0, w - 1)] * wx[i] for i in range(4))
        out = out + row * wy[j]
    return out

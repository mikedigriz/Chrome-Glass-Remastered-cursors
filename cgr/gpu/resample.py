"""PIL-exact separable resize on the GPU.

Pillow's resize is two passes (horizontal, then vertical) of a convolution with
per-output coefficients from precompute_coeffs. torch's interpolate has no
Lanczos and its antialiasing differs, so the coefficient matrices are rebuilt
here with the same arithmetic. Mode "F" images accumulate in double and store
float32 between the passes, which is reproduced by rounding through float32.
"""
import math
import functools
import torch

_SUPPORT = {"box": 0.5, "bilinear": 1.0, "lanczos": 3.0}


def _sinc(x):
    if x == 0.0:
        return 1.0
    x *= math.pi
    return math.sin(x) / x


def _filter(kind, x):
    if kind == "box":
        return 1.0 if -0.5 < x <= 0.5 else 0.0
    if kind == "bilinear":
        x = abs(x)
        return 1.0 - x if x < 1.0 else 0.0
    return _sinc(x) * _sinc(x / 3.0) if -3.0 < x < 3.0 else 0.0


@functools.lru_cache(maxsize=None)
def coeff_matrix(kind, n_in, n_out):
    """(n_out, n_in) float64 matrix equal to Pillow's precompute_coeffs rows."""
    scale = n_in / n_out
    fscale = max(scale, 1.0)
    support = _SUPPORT[kind] * fscale
    ss = 1.0 / fscale
    rows = []
    for xx in range(n_out):
        center = (xx + 0.5) * scale
        xmin = max(int(center - support + 0.5), 0)
        xmax = min(int(center + support + 0.5), n_in) - xmin
        w = [_filter(kind, (x + xmin - center + 0.5) * ss) for x in range(xmax)]
        tot = sum(w)
        row = [0.0] * n_in
        for x, v in enumerate(w):
            row[xmin + x] = v / tot if tot != 0.0 else v
        rows.append(row)
    return torch.tensor(rows, dtype=torch.float64)


def resize_f(x, size, kind="lanczos"):
    """Resize float tensor (..., H, W) to (..., size[0], size[1]) like PIL mode "F".

    x is float32-valued (any dtype is accepted and rounded through float32 the
    way a PIL "F" image stores it); the result is float32."""
    h, w = x.shape[-2:]
    oh, ow = size
    dev = x.device
    x = x.to(torch.float32).to(torch.float64)
    if ow != w:                                   # Pillow runs horizontal first
        m = coeff_matrix(kind, w, ow).to(dev)
        x = (x @ m.T).to(torch.float32).to(torch.float64)
    if oh != h:
        m = coeff_matrix(kind, h, oh).to(dev)
        x = (m @ x).to(torch.float32).to(torch.float64)
    return x.to(torch.float32)

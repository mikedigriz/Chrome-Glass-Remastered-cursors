"""Experimental pipeline for the sheen-only animations: one master, one light.

The shipped path renders every keyframe on its own - its own Real-ESRGAN
master, its own shading, its own silhouette - and then tries to make nine
independent interpretations agree with each other after the fact (temporal
kernel, frozen tips, cross-fade). The masters do not agree: the network draws
the fold, the lit sheet and the dark facet in slightly different places in
every frame, so averaging two of them gives two half-transparent folds rather
than a fold half way between.

Here the cycle has one geometry and one light:

    canonical 512 master  ->  silhouette, fold, texture, every high frequency
    author's nine 32px    ->  nothing but how the light moves over it

The light is a per-pixel log-luminance residual against the cycle's own
geometric mean, interpolated as a periodic band-limited signal (the animation
is a loop, so cosines and sines close it by construction - there are no ends to
join), resampled to the render size and applied as a multiplier in linear
light. Alpha never moves: the author's own alpha is bit-identical across all
nine frames of all three cursors, so freezing it is his behaviour, not an
approximation of it.

Nothing here is wired into build.py. Import it and call anim_frames_lighting.
"""

import functools

import numpy as np
from PIL import Image

import hybrid as H
import vectorlib as V

LIGHT_ANIM = ("AppStarting", "Hand", "Wait")

HARMONICS = 4        # k in a_0 + sum_k (a_k cos kt + b_k sin kt). Nine samples
                     # carry exactly four harmonics, so k=4 is the complete
                     # transform: it passes through every one of the author's
                     # keyframes and interpolates between them with the
                     # smoothest periodic curve there is. Truncating was meant
                     # to damp the network's frame-to-frame disagreement, but
                     # the network is no longer in this path at all - the light
                     # comes from the author's own drawings, and damping those
                     # only loses his sheen (k=2 reconstructs his frames to
                     # 4.3/3.2/3.4 levels, k=4 to 0.34/0.01/0.35)
OUT_N = 27           # frames per cycle, the shipped count (3 x 9 at 60 fps)
SOURCE = "master"    # where the light comes from. "author": his own nine 32px
                     # frames, the drawing itself. "master": the nine AI
                     # upscales, low-passed - the network's light, which sits
                     # on the network's geometry and therefore on ours
MODE = "split"       # "split": light that leaves is taken off multiplicatively,
                     # light that arrives is added. Both halves are needed and
                     # for different reasons - see the two notes below.
                     # "add": the light is carried as a difference in linear
                     # light. "mul": as a log ratio, the tidier model for
                     # shading - a facet turning away from the light loses the
                     # same fraction whatever its colour. It is the wrong model
                     # for this art: the author's sheen is a specular highlight
                     # that goes white, and white on saturated yellow glass is
                     # light *added*, not the yellow multiplied. Multiplying it
                     # lifts the master's near-zero blue by a factor of four
                     # and lays a grey-blue haze along the top edge, which is
                     # exactly what the render showed
_EPS = 5e-3          # pedestal under the log, ~0.5% of white. Both the
                     # residual and the frame it is applied to carry it, so
                     # the transform inverts exactly; without it the ratio
                     # of two near-black pixels is noise with a huge log
_ALPHA_LO = 0.35     # author alpha the light is read over. His edge pixels are the
_ALPHA_HI = 0.75     # glass blended with whatever was behind it, so their colour
                     # is not a reading of the light on the glass - but zeroing
                     # them leaves a cliff at the rim that the resampler rings
                     # on, so what happens below _ALPHA_LO is extension, not
                     # truncation (see residual_field)
_FILL_UNIT = 2.5     # logical units the interior light is carried outward over
                     # to fill the rim it could not be read on
_LIGHT_UNIT = 0.75   # logical units the light field is blurred by once it is up
                     # at render size. It is a light field: one 32px pixel of it
                     # is 1/32 of the cursor, and anything finer than that is
                     # either the author's dither or the resampler's ringing.
                     # Wider damps his sheen - at 1.25 the per-pixel swing over
                     # the cycle fell to half his
_MASTER_UNIT = 2.0   # logical units the per-frame master is blurred by to leave
                     # only its light. Narrower keeps more of the author's own
                     # travel and brings the network's redrawn creases back with
                     # it: at 1.0 the cycle's travel matches him (15.6 against
                     # 15.9) and the high-frequency wobble doubles, 2.65 -> 4.41
_LIGHT_GAIN = 2.0    # amplitude of the light field. The blur that takes the
                     # network's disagreement out takes some of the sweep with
                     # it, and scaling a smooth field back up restores the
                     # travel without restoring the creases. 1.45 matches the
                     # author's own travel over a cycle; above that the sweep is
                     # deliberately livelier than his, which is the point of
                     # freezing the geometry - nothing structural moves however
                     # far the light does
_DIM_FLOOR = 0.10    # darkest a facet may be driven by the light leaving it, as
                     # a fraction of its canonical brightness
#
# Two other ways of keeping the light off the master's dark crease were built
# and measured before the split model above made them unnecessary. Both are out:
# fading the field over the outer rim (these are thin wedges - a hold wide
# enough to cover the drawn edge reaches most of the body with it, and the sweep
# at the points fell 24.0 -> 8.1), and scaling the field by how brightly the
# canonical frame lights that spot (the crease went green anyway - it was never
# a question of how much light arrived, but of what subtracting mostly-red light
# does to yellow).
_GAIN_CAP = 2.50     # |log gain| ceiling. The author's own sweep runs to
                     # 2.4 on AppStarting (a dark facet lit to near white is
                     # a factor of eleven), so this clips nothing he drew and
                     # only guards against a division by the log floor


@functools.lru_cache(maxsize=None)
def canonical_index(name):
    """The keyframe every other frame's geometry is borrowed from.

    The medoid, not the mean and not frame 0: the master whose total distance
    to all the others is smallest is by construction the one whose fold and
    facets sit where the network put them most often, and it is a real drawing
    rather than an average of drawings. Measured inside the silhouette only, so
    the halo the network invents outside it cannot vote."""
    n = len(H.BY_NAME[name]["frames"])
    m = H._mask(name, 0, 512) / 255.0
    lin = [V.srgb_to_linear(np.clip(H._master_raw(name, i)[0], 0, 255).astype(np.uint8))
           * m[..., None] for i in range(n)]
    cost = [sum(float(np.abs(lin[i] - lin[j]).mean()) for j in range(n)) for i in range(n)]
    return int(np.argmin(cost))


@functools.lru_cache(maxsize=None)
def residual_field(name):
    """(n, 32, 32) log-luminance residual of the author's own frames.

    MODE "add": C_i - mean_i C_i, in linear light.
    MODE "mul": log(C_i + eps) - mean_i log(C_i + eps): how much brighter or darker
    this frame's light made that spot than the cycle's normal state. A ratio,
    not a difference, because the sheen is light falling on glass - the same
    sweep over a dark facet and a lit one moves them by the same factor, not by
    the same number of levels. Subtracting the mean of the logs (a geometric
    mean in linear light) makes the residuals of a cycle sum to zero, which is
    the constant term the periodic model then does not have to carry.

    Per channel, not per luminance. Holding the canonical frame's chroma and
    modulating only its brightness is the tidier idea and it does not fit the
    drawings: the author's own colour swings 231 levels over Wait's cycle, and
    a luminance-only model reproduces his frames to 9.5 levels where a
    per-channel one reaches 0.35. The sheen on this glass is coloured."""
    n = len(H.BY_NAME[name]["frames"])
    logs, wts = [], []
    for i in range(n):
        a = np.asarray(H.original(name, i), dtype=np.float64)
        lin = V.srgb_to_linear(np.clip(a[..., :3], 0, 255).astype(np.uint8))
        logs.append(np.log(lin + _EPS) if MODE == "mul" else lin.astype(np.float64))
        wts.append(a[..., 3] / 255.0)
    logs = np.stack(logs)
    res = logs - logs.mean(axis=0, keepdims=True)
    if MODE == "mul":
        res = np.clip(res, -_GAIN_CAP, _GAIN_CAP)
    w = np.clip((np.min(wts, axis=0) - _ALPHA_LO) / (_ALPHA_HI - _ALPHA_LO), 0.0, 1.0)
    den = H._smooth1(w, _FILL_UNIT, 32)
    out = np.empty_like(res)
    for i in range(n):
        for c in range(3):
            num = H._smooth1(res[i, ..., c] * w, _FILL_UNIT, 32)
            out[i, ..., c] = res[i, ..., c] * w + (num / np.maximum(den, 1e-6)) * (1.0 - w)
    return out


@functools.lru_cache(maxsize=None)
def master_light(name, size, unit=_MASTER_UNIT):
    """(n, size, size, 3) low-frequency light of each frame's own master.

    The author's frames are the truthful source of the light, and they are
    drawn on his geometry, which is not quite the network's: his lit sheet ends
    a couple of logical units away from where ours does, so his light lands on
    our master beside the edge it belongs to. The network's own frames do sit
    on our geometry. Everything that made them unusable - the fold redrawn in a
    different place every frame, the rim moving, the tip changing shape - is
    high frequency, and a blur wide enough to remove it leaves exactly the
    quantity wanted here: where the light is."""
    n = len(H.BY_NAME[name]["frames"])
    out = []
    for i in range(n):
        lin = V.srgb_to_linear(np.clip(H._master_rgb(name, i, size), 0, 255).astype(np.uint8))
        out.append(np.dstack([H._smooth1(lin[..., c], unit, size) for c in range(3)]))
    out = np.stack(out)
    return out - out.mean(axis=0, keepdims=True)


def periodic_resample(field, out_n=OUT_N, k=HARMONICS):
    """Band-limited periodic interpolation of a per-pixel time series.

    The frames are one cycle sampled at equal phase (all three cursors run a
    flat 3-jiffy rate), so the trigonometric fit is exactly the DFT: keep the
    first k harmonics, drop the rest, evaluate on the finer grid. Start and end
    are the same function, so value, slope and curvature match across the seam
    without anything being joined."""
    n = field.shape[0]
    spec = np.fft.rfft(field, axis=0)
    spec[k + 1:] = 0.0
    out = np.zeros((out_n // 2 + 1,) + spec.shape[1:], dtype=complex)
    keep = min(len(spec), len(out))
    out[:keep] = spec[:keep]
    return np.fft.irfft(out, n=out_n, axis=0) * (out_n / n)


_PACE_FINE = 216     # phase samples the pace curve is measured on, 8 per output
                     # frame. The author's sweep does not move at a constant
                     # rate, and sampling the reconstruction at equal phase
                     # reproduces that unevenness exactly: it reads as hurrying
                     # and dawdling (peak/mean of the visible step 1.39 against
                     # a limit of 1.15). The field is a continuous function of
                     # phase, so the fix is to sample it where it moves evenly
                     # rather than where its parameter says - the same thing
                     # anim_frames does to the old path, one level lower down.
_PACE_DECIM = 4      # the pace is one scalar per phase; measure it on a
                     # decimated field, not on 216 full-size ones
_GHOST_ALPHA = 10.0  # alpha under which the light must not touch the colour.
                     # Nothing there is visible, and RGB that moves under an
                     # alpha of zero is what ghost_rgb exists to catch


def periodic_at(field, phases, k=HARMONICS):
    """The same band-limited fit as periodic_resample, at arbitrary phases.

    periodic_resample can only land on a uniform grid, because irfft evaluates
    on one. Written out as a sum of harmonics instead, the fit takes any phase
    at all - which is what pacing the cycle by its own motion needs."""
    n = field.shape[0]
    spec = np.fft.rfft(field, axis=0)[:k + 1]
    ph = np.asarray(phases, dtype=np.float64)
    out = np.zeros((len(ph),) + field.shape[1:])
    for m in range(spec.shape[0]):
        # every harmonic but DC (and Nyquist, when n is even) stands for a
        # conjugate pair, hence the two
        w = 1.0 if m == 0 or (n % 2 == 0 and m == n // 2) else 2.0
        c = spec[m] * (w / n)
        ang = (2.0 * np.pi * m) * ph
        sl = (slice(None),) + (None,) * (field.ndim - 1)
        out += np.cos(ang)[sl] * c.real[None] - np.sin(ang)[sl] * c.imag[None]
    return out


def _paced_phases(raw, lin, vis, seen, anchor, out_n=OUT_N, k=HARMONICS):
    """out_n phases spaced by equal change of the picture, not by equal time.

    Measured on the rendered colour and not on the field itself: the light model
    is multiplicative on one side and additive on the other, and sRGB on top of
    it, so equal change of the field is not equal change of anything the eye
    sees. Pacing on the field made the sweep hurry worse than not pacing it at
    all (peak/mean 1.39 -> 1.57). Rendered at a decimated size - the pace is one
    scalar per phase, and 216 frames of it are needed."""
    d = _PACE_DECIM
    lin_s, vis_s, seen_s = lin[::d, ::d], vis[::d, ::d], seen[::d, ::d]
    raw_s = raw[:, ::d, ::d] if raw.shape[1] == lin.shape[0] else raw
    a_s = anchor[:, ::d, ::d] if anchor.shape[1] == lin.shape[0] else anchor
    ph = np.arange(_PACE_FINE) / _PACE_FINE
    f = periodic_at(raw_s, ph, k) - a_s
    if f.shape[1] != lin_s.shape[0]:                 # a 32px field under a render
        return np.arange(out_n) / out_n
    # float, not the uint8 linear_to_srgb hands back: a step of -3 levels read
    # as 253 turns the pace curve into noise, and the pacing into nothing
    shot = [V.linear_to_srgb(_lit(lin_s, f[i] * _LIGHT_GAIN * vis_s[..., None])).astype(np.float64)
            for i in range(_PACE_FINE)]
    step = np.array([float(np.abs(shot[(i + 1) % _PACE_FINE][seen_s]
                                  - shot[i][seen_s]).mean()) for i in range(_PACE_FINE)])
    if step.sum() < 1e-12:
        return np.arange(out_n) / out_n
    cum = np.concatenate([[0.0], np.cumsum(step)])
    want = np.arange(out_n) * cum[-1] / out_n
    return np.interp(want, cum, np.concatenate([ph, [1.0]]))


def _gamut_scale(lin, r):
    """Largest t in [0,1] with every channel of lin + t*r still in range.

    Per-channel clipping is what turned the sheen crossing the dark rim into a
    magenta blot: the red channel saturated first and the other two carried on.
    Scaling the whole step back instead keeps the light's colour and only
    shortens it, so the worst that happens where the author's sweep asks for
    more than the glass can hold is that it stops early."""
    with np.errstate(divide="ignore", invalid="ignore"):
        hi = np.where(r > 0, (1.0 - lin) / r, np.inf)
        lo = np.where(r < 0, (0.0 - lin) / r, np.inf)
    t = np.minimum(np.nanmin(hi, axis=-1), np.nanmin(lo, axis=-1))
    return np.clip(np.where(np.isfinite(t), t, 1.0), 0.0, 1.0)


def _lit(lin, r):
    """One frame's linear colour: the canonical glass under a light residual."""
    if MODE == "mul":
        return (lin + _EPS) * np.exp(np.clip(r, -_GAIN_CAP, _GAIN_CAP)) - _EPS
    if MODE == "split":
        # taking light away from saturated yellow glass by subtracting the same
        # numbers the author's sweep loses is what turned the crease green: his
        # loss is mostly red, the glass has no blue to lose, and what is left of
        # a yellow whose red has gone is green. Light that leaves a surface
        # scales it; light that arrives adds to it.
        dy = r[..., 0] * 0.2126 + r[..., 1] * 0.7152 + r[..., 2] * 0.0722
        y = lin[..., 0] * 0.2126 + lin[..., 1] * 0.7152 + lin[..., 2] * 0.0722
        f = np.clip(1.0 + np.minimum(dy, 0.0) / np.maximum(y, 1e-4), _DIM_FLOOR, 1.0)
        add = np.clip(r, 0.0, None)
        return lin * f[..., None] + add * _gamut_scale(lin * f[..., None], add)[..., None]
    return lin + r * _gamut_scale(lin, r)[..., None]


def canonical_frame(name, size, idx=None):
    """The one rendered frame the whole cycle is lit from."""
    if idx is None:
        idx = canonical_index(name)
    return np.asarray(H.frame_image(name, idx, size), dtype=np.float64)


def anim_frames_lighting(name, size, out_n=OUT_N, k=HARMONICS, idx=None):
    """(frames, rates) for a sheen-only animation, geometry frozen.

    One canonical render, out_n light fields over it. The residual is carried
    up from 32px by plain Lanczos on purpose: it is a light field, it has no
    business holding detail one high-resolution pixel wide, and every such
    detail is already in the master underneath it."""
    if idx is None:
        idx = canonical_index(name)
    base = canonical_frame(name, size, idx)
    lin = V.srgb_to_linear(np.clip(base[..., :3], 0, 255).astype(np.uint8))
    alpha = base[..., 3]
    if SOURCE == "master":
        raw = master_light(name, size)
    else:
        raw = residual_field(name)
    n = len(H.BY_NAME[name]["frames"])
    # Where the light is allowed to touch the colour at all. The canonical alpha
    # is the same for every frame, so this mask is too.
    vis = np.clip(alpha / _GHOST_ALPHA, 0.0, 1.0)
    # the glass proper, by the same fraction of the frame's own peak the rest of
    # this repo uses. An absolute level selects almost nothing on translucent
    # glass whose peak sits near 190, and pacing over the wrong region paces
    # over the rim instead of the sheen.
    seen = alpha > H._PACE_SOLID * float(alpha.max())
    # the residual is measured against the cycle's mean light, the render
    # against one keyframe's: re-anchor so the loop is lit relative to the frame
    # it was rendered from, at that frame's own phase
    anchor = periodic_at(raw, [idx / n], k)
    phases = _paced_phases(raw, lin, vis, seen, anchor, out_n, k)
    field = periodic_at(raw, phases, k) - anchor
    frames = []
    for t in range(out_n):
        if field.shape[1] == size:
            r = field[t] * _LIGHT_GAIN
        else:
            r = np.dstack([H._smooth1(H._resample_signed(field[t, ..., c], size),
                                      _LIGHT_UNIT, size) for c in range(3)]) * _LIGHT_GAIN
        r = r * vis[..., None]
        rgb = V.linear_to_srgb(_lit(lin, r)).astype(np.float64)
        frames.append(H._compose(rgb, alpha))
    return frames, [1] * out_n

"""Glass drawn from the surface in cgr.facets (GLASS_PLAN.md stages 1b-1c).

No pixel here comes from the AI master. The lines are the model's: the
profile across the rim (light shoulder, dark steep edge), the fold as the
boundary of two facets, the inner points as mitres. The tone is the
author's, read off his 32 px frame in surface coordinates (`_author`):
along the outline for the rim, per facet for the glass. Box down to 32 the
render lands near his frame (grey 4.2 levels mean, HEAD 7.4, 1.1.0 7.2), and
nothing he drew is averaged across a line.

Every sample is shaded at ss x ss per pixel and box-averaged in
premultiplied linear light, so each size is the same drawing at its own
pixel pitch and there is no blur stage to soften a line.
"""
import functools

import numpy as np
from PIL import Image

from . import facets as F
from . import glyphs as GL
from . import hybrid as H
from . import vectorlib as V

SS = 4
MATERIAL = {
    "Arrow": {
        "rim_alpha": 0.85,            # box to 32 against the author: 0.85-0.97 within 1 level
        "rim_solid": 0.33,            # of the bevel from its inner line where alpha reaches rim_alpha
        "glint": 0.33,                # place across the bevel (0 edge..1 inner) of the glint; at 0.50 the outer half of the rim read dark (owner, 2026-10-25), 1.1.0 lights it
        # soft, as the author's (owner, 2026-10-25: the hairline-thin glint
        # and edge, 0.08 / 0.16, read rough; these are also nearer him boxed
        # to 32, grey 4.2 against 4.7)
        # softer twice over on the owner's word; 0.35 / 0.6 boxed to 32 are
        # nearer him still (grey 3.9)
        "glint_w": 0.30,              # its half-width, same units; wide as 1.1.0's light bands (owner, 2026-10-25: not narrow), silver not white by glint_gain
        "glint_gain": (0.02, 0.45),   # added light: on the darkest rim, on the brightest
        # brilliance (owner, 2026-10-25: like the original). His brightest
        # pixel at 32 averages 16x16 of a 512 render; with the soft glint
        # alone the 512 peak only reached it (rim 85-92 L* against his 86),
        # so nothing glistened. Core 0.5: peaks 90-97, the box to 32 as
        # before; at 1.0 the rim clips to white
        # 1.2 with glint_shape 5 drew a crisp white wire along every rim, too
        # defined against 1.1.0 (owner, 2026-10-25)
        "glint_core": 0.2,            # a narrow bright core inside the soft glint, gain
        "glint_core_w": 0.05,         # its half-width: soft and still glistening
        # with the glint at 0.33 the outer edge 65 L* at 512, 1.1.0 64; 0.50
        # read too dark (owner, 2026-10-25). Lifting the rim tone itself
        # toward 1.1.0's silver left the shaded rims pale and unreadable
        "edge_dark": 0.20,            # darkening at the steep outer edge
        "edge_w": 0.20,               # in units of the bevel's width
        # with the rim at 1.6 LU the fractions of it grew into blur (owner,
        # 2026-10-25: the whole cursor too blurry against the author and
        # 1.1.0): inner 0.28 (0.45 LU), edge 0.2, glint 0.2
        "inner_soft": 0.28,            # of the bevel from its inner line: rim tone eases into the facet's; 0.30 outlined the inner contour too clearly (owner, 2026-10-25), at 1.0 the glint and the inner points go soft
        "outer_soft": 0.20,            # of the bevel from the edge: alpha eases in from outer_floor
        "outer_floor": 0.60,          # 0.35 lost the rim at the notch on a dark ground
        # mirrored out past the inner point (2.2-2.4 LU), his own by 5: at 9
        # the mirror reached most of the two short blades by the notch and
        # pulled their light down 3-4 L*, brilliance 5-6 (glass_style.py)
        # against 1.1.0 at 512 (owner, 2026-10-25: keep the sharpness and
        # brilliance): its brightest 1% L* 96.6, ours was 88; its steepest
        # steps 311 L*/LU, ours 86. A keen core, a deeper edge and the glint
        # placed on his lit runs (glint_place) bring 94.8 and 159 clean
        # chrome (owner, 2026-10-25: almost no chrome): the glint a band with
        # a flat top and steep sides, a reflection, not a soft spot
        "glint_shape": 6.0,           # power of the glint's profile: 2 gaussian, higher flat-topped; 3 read blurry (owner, 2026-10-25), 8 steep as 1.1.0's
        "glint_place": 4.0,          # 2 ran the glint round the whole outline as a wire
        # the twist, drawn (owner, 2026-10-25: the net's scroll pasted read as
        # a beaten artefact): ribbons with keen edges and smooth insides
        "scroll": {"dark_from": 2.6, "dark_to": 2.6, "dark_w": (0.42, 0.10), "dark": 0.55,
                   "lit_from": 3.4, "lit_w": 0.40, "lit": 1.15, "edge_lit": 0.15, "fade": 0.3, "round": 5.0},           # power on the rank of his rim light the glint follows
        "point_even": (3.0, 5.0),     # LU from a point: rim tone mirrored, then the author's own
        # his dark pocket at the notch (owner, 2026-10-25: shadows as the
        # original's): the glint ran into it and lit the inner rim there 5-8 L*
        # above him, notch p5 44.9 against 42.9
        "fold_soft": 0.8,             # LU across the fold, smoothstep: 10-90 over about 0.5
        "notch_dim": (1.0, 5.0),      # LU from a concave corner: no glint, then full
        # against the author's pixels and 1.1.0 (owner, 2026-10-25: compare
        # on many grounds): his rim lightens inward and his upper edge stands
        # further out; ours ran a dark ring at the inner line
        "base_soft": 0.67,            # of the bevel from its inner line: the base eases in from the facet, up to the glint
        "no_valley": True,            # no dip between the glint and the facet
        "edge_out": (0.09, 4.0),      # LU the edge is carried out past the outline, LU from a point it fades over
        # per side A-C, C-J, J-B, B-A: his coverage over ours per LU of side
        # +0.047 / +0.051 / +0.005 / +0.005, at the edge's alpha 0.51
        "edge_out_side": (1.0, 1.1, 0.1, 0.1),
    },
}
# the family: Arrow's material, the tone is read from each author (stage 2)
for _n in ("Arrow_Down", "UpArrow", "Hand", "NO", "Handwriting"):
    MATERIAL[_n] = MATERIAL["Arrow"]
# Wait, AppStarting (stage 5): his light runs round the rim in saturated
# spots of his own colour; added grey it read as pink-white dashes
for _n in ("Wait", "AppStarting"):
    MATERIAL[_n] = dict(MATERIAL["Arrow"], glint_tint=1.0)
MATERIAL["Help"] = dict(MATERIAL["Arrow"], glyph=True)
# the darts of the bevel cursors (GLASS_PLAN.md stage 3): Arrow's material
# without what belongs to Arrow's own outline, its twist at the notch and
# the edge carried out along its upper sides
for _n in F.PART:
    MATERIAL[_n] = {k: v for k, v in MATERIAL["Arrow"].items()
                    if k not in ("scroll", "edge_out", "edge_out_side")}

# Help's "?" (GLASS_PLAN.md stage 2). His body is Arrow pixel for pixel; the
# sign is a glass rod laid over it, the dot a bead. Owner, 2026-10-26: 1.1.0's
# cut bowl read as a broken hook, an outlined stroke as a sticker, a tube as a
# pipe - a smooth glass "?" with chrome, well readable. The centre line runs
# through his stroke's pixel centres, its turning eased along the arc
GLYPH = {
    "Help": {
        "path": ((17.3, 15.1), (17.7, 14.0), (18.7, 13.45), (19.8, 13.3), (21.0, 13.5),
                 (22.0, 14.05), (22.5, 14.95), (22.6, 16.0), (22.55, 17.4), (22.2, 18.6),
                 (21.3, 19.6), (20.3, 20.6), (19.65, 21.6), (19.5, 22.6), (19.5, 23.1)),
        "smooth": 1.2,                 # LU, the heading eased over: through his pixels it turned in kinks
        "w": 2.1,                      # LU, the stroke: his stem's alpha sums to 1.8-2.0 across it
        "dot": (19.48, 26.62, 1.45),   # centre and radius
        "soft": 1.2,                   # the edge's antialias, in the glass's own widths
        # the cross-section: height (1 - u^p)^(1/p) scaled by f, lower and
        # flatter than a tube (at p 2, f 1 it read as a pipe)
        "dome": (2.5, 0.9),
        "light": (-0.707, -0.707, 1.0),  # toward the light, as 1.1.0 lights the sign
        "base": 0.5, "amb": 0.35, "kd": 0.75,  # linear tone: base (ambient + diffuse)
        "glint": (0.7, 40),            # the highlight's gain and exponent
        # light gathered inside the far edge: gain, where (N toward the light), width
        "gather": (0.25, -0.65, 0.35),
        # the room mirrored in it, by the reflected direction: (azimuth deg,
        # its width rad, elevation R_z, its width, gain); the bands bend and
        # come and go along the curve, negative ones are dark
        "mirror": 1.4,
        "room": ((-135, 0.3, 0.6, 0.2, 0.35), (-100, 0.15, 0.2, 0.12, 0.3), (-160, 0.12, 0.0, 0.1, 0.25),
                 (45, 0.35, 0.3, 0.15, 0.22), (80, 0.12, -0.1, 0.1, 0.2), (170, 0.2, 0.75, 0.15, 0.18),
                 (10, 0.15, 0.5, 0.15, 0.15), (-20, 0.3, 0.05, 0.1, -0.2), (120, 0.3, 0.4, 0.15, -0.15),
                 (-60, 0.2, 0.85, 0.08, 0.12)),
        "body": "Arrow",               # read in place of his pixels under the sign
        "keep": 0.8,                   # LU round the sign those pixels are taken from
    },
}

# Pin's and Person's badges (GLASS_PLAN.md stage 2): the shapes of
# glyphs.py in Help's sign's glass, its tone as is. Owner, 2026-10-26: the
# amber ramp read as polished gold with a glint of its own, beside Help's
# glass rod. The flat badge with a dark outline sat on the glass Arrow as a
# sticker. A dome from the shape's depth eased over 0.5 LU: from the raw
# depth the normal broke along the middle in ridges. Domed over 3 LU the
# pin's point ridged still
BADGE = {"bevel": 2.0, "smooth": 0.5, "alpha": 0.94,
         "lit": (0.3, 0.85)}   # glass tone over which a ramp (NO's red) runs dark to light


def _badge_shapes(name):
    """[(outline, hole (x, y, r) or None)] in LU."""
    if name == "Pin":
        prims, _hole = GL._pin_prims()
        return [(prims[0]["poly"], (23.0, 18.2, 1.8))]
    prims, _none = GL._person_prims()
    return [(prims[0]["poly"], None), (prims[1]["poly"], None)]


def _badge(name, px, py, tone, alpha, pitch):
    for poly, hole in _badge_shapes(name):
        q = np.asarray(poly, dtype=np.float64)
        q = q[np.hypot(*(q - np.roll(q, -1, 0)).T) > 1e-6]
        d = np.min([F._seg_dist(px, py, p0, p1) for p0, p1 in zip(q, np.roll(q, -1, 0))], 0)
        d = np.where(F._in_poly(px, py, q), d, -d)
        if hole:
            d = np.minimum(d, np.hypot(px - hole[0], py - hole[1]) - hole[2])
        tone, alpha = _domed(d, px, tone, alpha, pitch, None, 1.0)
    return tone, alpha


def _domed(d, px, tone, alpha, pitch, ramp, opacity=None):
    """A shape of depth d (LU, + inside) laid on as glass: domed by its
    eased depth, lit as Help's sign, its tone run over the ramp's colours
    (none: Help's own tone)."""
    g, b = GLYPH["Help"], BADGE
    step = px[0, 1] - px[0, 0]
    edge = max(0.035, 0.6 * pitch) * g["soft"]
    ds = np.where(d > 0, np.maximum(_blur(d, b["smooth"] / step), 0), d)
    gy, gx = np.gradient(ds, step)
    nn = np.maximum(np.hypot(gx, gy), 1e-9)
    lit = _glass_tone(g, _dome(g, np.clip(1 - ds / b["bevel"], 0, 1), -gx / nn, -gy / nn))
    if ramp is None:
        col = np.repeat(lit[..., None], 3, -1)
    else:
        lo, hi = (V.srgb_to_linear(np.array(c, np.uint8)) for c in ramp)
        t0, t1 = b["lit"]
        s = np.clip((lit - t0) / (t1 - t0), 0, 1)[..., None]
        col = lo + (hi - lo) * s + np.clip(lit - t1, 0, None)[..., None]
    w = np.clip(d / edge + 0.5, 0, 1) * (b["alpha"] if opacity is None else opacity)
    tone = tone + (col - tone) * w[..., None]
    return np.clip(tone, 0, None), alpha + (1 - alpha) * w


# NO's sign: red glass as the badges, a ring and its bar ("\") growing
# frame by frame over the shrinking pointer (facets.shrink); his flat red
# (217, 32, 24) the middle of the ramp
# solid: seen through, the grey under it paled the red to pink below 96
SIGN = {"red": ((200, 8, 4), (255, 64, 46)), "alpha": 1.0,
        "hole": 0.78}   # inner over outer radius, his frames 7-10


def _sign(name, idx, px, py, tone, alpha, pitch):
    geom = F.sign_geom(name, idx)
    if geom is None:
        return tone, alpha
    cx, cy, r_out = geom
    r_in = SIGN["hole"] * r_out
    rho = np.hypot(px - cx, py - cy)
    # the pointer inside the hole is wiped as his is, from the sign back to
    # the point (facets.sign_front), its edge under the ring
    level, front, ax, apex = F.sign_front(name, idx, SIGN["hole"])
    t = (px - apex[0]) * ax[0] + (py - apex[1]) * ax[1]
    keep = level * np.clip((front - t) / F._FRONT_RAMP + 0.5, 0, 1)
    alpha = alpha * (1 - (1 - keep) * np.clip((r_in + 0.3 - rho) / 0.6, 0, 1))
    ring = (r_out - r_in) / 2 - np.abs(rho - (r_out + r_in) / 2)
    bar = np.minimum(H._RING_BAR * (r_out - r_in) / 2 - np.abs((px - cx) - (py - cy)) / np.sqrt(2),
                     (r_out + r_in) / 2 - rho)
    return _domed(np.maximum(ring, bar), px, tone, alpha, pitch, SIGN["red"], SIGN["alpha"])


_RIM_DEPTH = (-0.6, 0.6)  # LU from the edge, + inside: the pixels whose colour is the rim's.
                          # Deeper his pixels are the facet already (side profiles: the
                          # tone turns to the facet's from 0.8 in); taking them averaged
                          # the facet into the rim and the stair phase of a slanted side
                          # beat it into a wave of 13 levels rms along the top side
_RIM_SIGMA = 0.6     # LU along the outline the author's rim tone is averaged over
_FACET_DEG = 2      # the facet's tone: a polynomial surface of this degree
_POCKET = 2.0       # LU, the reach of the round term at a concave corner
_FOLD_MIX = 0.6     # LU off the fold where his pixels hold both facets: kept out of either fit
_S_STEP = 0.05
_SEEN_FROM = 0.5    # pixels: an edge feature narrower than this is not drawn, full from 1.5


def _poly(px, py):
    x, y = px.ravel() / 16.0 - 1, py.ravel() / 16.0 - 1
    return np.column_stack([x ** i * y ** j for i in range(_FACET_DEG + 1)
                            for j in range(_FACET_DEG + 1 - i)])


@functools.lru_cache(maxsize=None)
def _his(name, idx):
    """His frame as an array; under a sign, the body it is drawn on."""
    im = np.asarray(F.original(name, idx)).astype(np.float64)
    g = GLYPH.get(name)
    if g is None:
        return im
    px, py = F.grid(32, 1)
    d = _stroke(g, px, py)[0]
    cx, cy, r = g["dot"]
    near = (d < g["w"] / 2 + g["keep"]) | (np.hypot(px - cx, py - cy) < r + g["keep"])
    return np.where(near[..., None], np.asarray(F.original(g["body"], idx)).astype(np.float64), im)


def _author(name, idx):
    """The author's tone, laid on the surface (GLASS_PLAN.md stage 1c).

    Read at his pixel centres, in linear light:
      rim     colour against arc length round the outline, from the pixels
              in the rim band, alpha-weighted and averaged along the outline
              only - across the rim his 32 px has one pixel, the profile
              across is the model's
      facet   per triangle of the fold, a field smoothed from that facet's
              own pixels (normalised convolution), so the fold stays a
              crease and his gradients and the dark pocket stay where he
              put them
    """
    s = F.SURFACE[name]
    im = _his(name, idx)
    rgb = V.srgb_to_linear(im[..., :3].astype(np.uint8)).astype(np.float64)
    al = im[..., 3] / 255.0
    sf = F.surface(name, 32, 1, idx)
    px, py = F.grid(32, 1)
    sc = F.side_coords(name, px, py, idx)
    _starts, total = F.perimeter(name, idx)

    rim = (al > 0.1) & (sc["dist"] > _RIM_DEPTH[0]) & (sc["dist"] < _RIM_DEPTH[1])
    grid_s = np.arange(0.0, total, _S_STEP)
    ds = grid_s[:, None] - sc["s"][rim][None, :]
    ds = (ds + total / 2) % total - total / 2
    w = np.exp(-0.5 * (ds / _RIM_SIGMA) ** 2) * al[rim][None, :]
    rim_rgb = (w @ rgb[rim]) / np.maximum(w.sum(1), 1e-9)[:, None]
    # where none of his pixels lie along the outline (a SizeAll dart's sides
    # past its quarter, cut away), the nearest stretch that has them: read as
    # black, the gap bled into the hole's rim as dark spots at the seams
    seen = w.sum(1) > 0.05 * np.median(w.sum(1))
    if F.PART.get(name, ("",))[0] in F._STAR and not seen.all():
        k = np.nonzero(seen)[0]
        gap = np.abs(np.arange(len(grid_s))[:, None] - k[None, :])
        gap = np.minimum(gap, len(grid_s) - gap)
        rim_rgb = rim_rgb[k[np.argmin(gap, 1)]]

    # each facet is clean glass: his tone and transparency as a smooth
    # surface of degree _FACET_DEG fitted to his pixels (owner, 2026-10-25:
    # Chrome Glass - carry the pleasant properties, not the dirt). The
    # smoothed field kept the grain of his 32 px, and blown up to 512 that
    # grain is blotches
    fields = {}
    X = _poly(px, py)
    # his dark pocket at the notch is no polynomial of low degree: the fit
    # took it away and the notch went flat and light. A smooth round term at
    # each concave corner lets the fit keep it without his grain
    o = F.outline(name, idx)
    X = np.column_stack([X] + [np.exp(-0.5 * (np.hypot(px.ravel() - o[c][0], py.ravel() - o[c][1])
                                               / _POCKET) ** 2)
                               for c in F.ORDER if c not in F.POINTS])
    # a pixel the fold crosses holds both facets; in the fit it pulled the
    # light facet down 2 L* along the whole fold (box to 32 against him)
    a, j = np.asarray(o["A"]), np.asarray(o["J"])
    own = np.abs(F._line_dist(px, py, a, j, o["C"])) >= _FOLD_MIX
    for k in (1, 2):
        w = (((sf["facet"] == k) & (sc["dist"] >= s["rim"]) & own) * al).ravel()
        Xw = X * w[:, None]
        coef = np.linalg.lstsq(Xw.T @ X + 1e-6 * np.eye(X.shape[1]),
                               Xw.T @ np.column_stack([rgb.reshape(-1, 3), al.ravel()]), rcond=None)[0]
        fit = (X @ coef).reshape(32, 32, 4)
        fields[k] = (np.clip(fit[..., :3], 0, None), np.clip(fit[..., 3], 0, 1))
    return grid_s, rim_rgb, total, fields


def _blur(img, sigma):
    r = int(np.ceil(3 * sigma))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    pad = np.pad(img, r, mode="constant")
    out = np.apply_along_axis(lambda v: np.convolve(v, k, "valid"), 0, pad)
    return np.apply_along_axis(lambda v: np.convolve(v, k, "valid"), 1, out)


@functools.lru_cache(maxsize=None)
def _side_table(name, idx, weights):
    """Per-side weights as a table along the outline, eased over 3 LU at each corner."""
    starts, total = F.perimeter(name, idx)
    grid_s = np.arange(0.0, total, _S_STEP)
    w = np.asarray(weights, float)[np.searchsorted(starts, grid_s, side="right") - 1]
    n = int(round(1.5 / _S_STEP))
    w = np.convolve(np.r_[w[-n:], w, w[:n]], np.ones(2 * n + 1) / (2 * n + 1), "valid")
    return grid_s, w[:, None], total


def _at_s(grid_s, vals, total, s):
    """Periodic linear lookup of a per-arc-length table."""
    x = (s % total) / _S_STEP
    i0 = np.floor(x).astype(int) % len(grid_s)
    f = (x - np.floor(x))[..., None]
    return vals[i0] * (1 - f) + vals[(i0 + 1) % len(grid_s)] * f


def _body(name, idx, size, key=None):
    """The glass at the sample grid: tone (linear rgb), alpha, the grid, facet.
    With key, frame idx's outline in frame key's tone: the rim by arc length,
    the facets through the affine map of idx's corners onto key's."""
    m = MATERIAL[name]
    sf = F.surface(name, size, SS, idx)
    facet = sf["facet"]
    if m.get("scroll"):
        facet, sf["u"] = _round_notch(name, idx, m["scroll"]["round"], *F.grid(size, SS), facet, sf["u"])
    inside = facet > 0
    # steepness across the bevel: 0 at its inner line, 1 at the outer edge
    slope = (1.0 - sf["u"]) * inside
    on_rim = slope > 0
    o = F.outline(name, idx)
    px, py = F.grid(size, SS)
    grid_s, rim_rgb, total, fields = _author(name, idx if key is None else key)
    sr = total / F.perimeter(name, idx)[1]

    # the author's rim colour along the outline; at a point both sides take
    # the mirror average, so the outer point and the inner one are mirror
    # images about the bisector (owner, 2026-10-25: symmetric inside and
    # outside, all on one line), fading to his own colour by point_even[1]
    cs = F.corner_s(name, idx)
    dist_pt = np.stack([np.hypot(px - o[k][0], py - o[k][1]) for k in F.POINTS])
    which = np.argmin(dist_pt, axis=0)
    near = np.min(dist_pt, axis=0)
    c_s = np.asarray([cs[k] for k in F.POINTS])[which]
    own = _at_s(grid_s, rim_rgb, total, sf["s"] * sr)
    mirror = _at_s(grid_s, rim_rgb, total, (2 * c_s - sf["s"]) * sr)
    lo, hi = m["point_even"]
    keep = np.clip((near - lo) / (hi - lo), 0.0, 1.0)
    keep = (keep * keep * (3.0 - 2.0 * keep))[..., None]
    rim_col = keep * own + (1 - keep) * 0.5 * (own + mirror)

    # across the rim the lines are the model's: a dark hairline at the steep
    # edge and a glint, added light, on the shoulder (owner, 2026-10-25: the
    # original glistens, ours read dry - a band of the right mean tone is
    # not glass). The glint is stronger where his rim is brighter, so the
    # lit sides shine and the shaded ones keep a thin line. The base under
    # them is solved so the mean across the rim is still his colour: the box
    # down to 32 lands on him and the light is redistributed, not added.
    u_grid = np.linspace(0.0, 1.0, 201)

    # the edge's dark hairline and its alpha step are fractions of a LU: at
    # 512 a few pixels, at 40-64 less than one, where they only dimmed the
    # outermost pixel and left the glint a pixel inside it, a white line
    # standing apart from the silhouette (owner, 2026-10-25, at a low scale).
    # They fade out as they shrink under a pixel
    pitch = V.LOGICAL / float(size)
    rim_lu = F.SURFACE[name]["rim"]

    def _seen(frac):
        return float(np.clip(frac * rim_lu / pitch - _SEEN_FROM, 0.0, 1.0))
    edge_dark = m["edge_dark"] * _seen(m["edge_w"])
    floor = 1.0 - (1.0 - m["outer_floor"]) * _seen(m["outer_soft"])

    def dark(sl):
        return 1.0 - edge_dark * np.clip((sl - (1 - m["edge_w"])) / m["edge_w"], 0, 1)

    def glint(sl):
        x = (1 - sl) - m["glint"]
        return (np.exp(-0.5 * np.abs(x / m["glint_w"]) ** m.get("glint_shape", 2.0))
                + m["glint_core"] * np.exp(-0.5 * (x / m["glint_core_w"]) ** 2))

    lum = rim_col.mean(-1, keepdims=True)
    g0, g1 = m["glint_gain"]
    if m.get("glint_place"):
        # placed light (owner, 2026-10-25: keep the sharpness and brilliance):
        # the glint goes where his rim is lit, ranked between its darkest and
        # brightest stretch, and rises steeply, so the lit runs sparkle and
        # the shaded ones keep only a trace - a glint of one strength all
        # round reads as a white wire
        rl = rim_rgb.mean(-1)
        lo_l, hi_l = np.percentile(rl, 10), np.percentile(rl, 90)
        rank = np.clip((lum - lo_l) / (hi_l - lo_l), 0.0, 1.0)
        gain = g0 + (g1 - g0) * rank ** m["glint_place"]
    else:
        gain = g0 + (g1 - g0) * np.clip(lum / 0.6, 0.0, 1.0)
    if m.get("notch_dim"):
        n0, n1 = m["notch_dim"]
        for k in F.ORDER:
            if k not in F.POINTS:
                t = np.clip((np.hypot(px - o[k][0], py - o[k][1]) - n0) / (n1 - n0), 0.0, 1.0)
                gain = gain * (t * t * (3.0 - 2.0 * t))[..., None]
    if m.get("glint_tint"):
        hue = rim_col / np.maximum(rim_col.max(-1, keepdims=True), 1e-6)
        gain = gain * (1 + (hue - 1) * m["glint_tint"])
    spec = gain * glint(slope)[..., None]
    base = np.clip((rim_col - gain * glint(u_grid).mean()) / dark(u_grid).mean(), 0.0, None)
    rim_tone = base * dark(slope)[..., None] + spec

    tone = np.zeros(px.shape + (3,))
    alpha = np.zeros(px.shape)
    pts = np.stack([px.ravel(), py.ravel()], 1)
    if key is not None:
        ok = F.outline(name, key)
        src = np.array([[*o[c], 1.0] for c in F.ORDER])
        aff = np.linalg.lstsq(src, np.array([ok[c] for c in F.ORDER]), rcond=None)[0]
        pts = np.column_stack([pts, np.ones(len(pts))]) @ aff
    cols, alphas = {}, {}
    for k, (field, a_field) in fields.items():
        sel = facet == k
        cols[k] = np.stack([F._bilinear(field[..., c], pts).reshape(px.shape) for c in range(3)], -1)
        alphas[k] = F._bilinear(a_field, pts).reshape(px.shape)
        tone[sel] = cols[k][sel]
        alpha[sel] = alphas[k][sel]
    if m.get("fold_soft") and set(cols) >= {1, 2}:
        # the fold eases from one facet's field into the other's over
        # fold_soft LU (owner, 2026-10-25: a hard cut on the author's soft
        # ramp read as a slit); the step between the facets stays his
        a, j = np.asarray(o["A"]), np.asarray(o["J"])
        d = F._line_dist(px, py, a, j, o["C"])          # + on the upper facet's side
        span = max(m["fold_soft"], V.LOGICAL / float(size))
        w = np.clip(d / span + 0.5, 0, 1)
        w = w * w * (3 - 2 * w)
        band = inside & (np.abs(d) < span)
        mix = cols[2] + (cols[1] - cols[2]) * w[..., None]
        tone[band] = mix[band]
        alpha[band] = (alphas[2] + (alphas[1] - alphas[2]) * w)[band]
    # soft where the rim meets the facet: the inner line stays where the
    # geometry puts it, the step across it eases over inner_soft of the rim
    ease = np.clip(slope / m["inner_soft"], 0, 1) if m["inner_soft"] else on_rim * 1.0
    if m.get("base_soft"):
        # the base under the glint eases in from the facet over base_soft
        # of the rim: eased with the glint, it ran a dark ring along the
        # inner line (1.15 LU 59 L* on grey, the facet 69) that neither
        # the author (his pixels lighten inward) nor 1.1.0 has
        eb = np.clip(slope / m["base_soft"], 0, 1)
        eb = eb * eb * (3 - 2 * eb)
        rim_tone = tone + (base * dark(slope)[..., None] - tone) * eb[..., None] + spec
    facet_tone = tone
    tone = np.where(on_rim[..., None], tone + (rim_tone - tone) * ease[..., None], tone)
    if m.get("no_valley"):
        # between the glint and the facet the base showed through darker
        # than both, a second faint line along the lit runs (owner,
        # 2026-10-25: defects, too many inner cursors; upper shoulder 3.9
        # lines across against 1.1.0's 2.5). Inside the glint's centre the
        # tone stays at least the lesser of the two
        sg = 1.0 - m["glint"]
        peak = base * dark(np.full(px.shape, sg))[..., None] + gain * glint(np.full(px.shape, sg))[..., None]
        floor_t = np.minimum(peak, facet_tone)
        tone = np.where((on_rim & (slope < sg))[..., None], np.maximum(tone, floor_t), tone)
    if m.get("scroll"):
        tone = _scroll(name, idx, m, px, py, inside, rim_col, tone, V.LOGICAL / float(size))
    tone = np.clip(tone, 0, 1)
    alpha = np.where(on_rim, alpha + (m["rim_alpha"] - alpha) * np.clip(slope / m["rim_solid"], 0, 1), alpha)
    if m["outer_soft"]:
        alpha = alpha * (floor + (1 - floor)
                         * np.clip((1 - slope) / m["outer_soft"], 0, 1))
        # the alpha the ramp no longer takes off where it is not seen is
        # taken off as a sliver at the edge instead: boxed down, the edge
        # stands that much in, solid, and the cursor weighs the same at
        # every size (48 was 3% heavier than 32 and 512, scale_drift 0.23)
        lost = (floor - m["outer_floor"]) * m["outer_soft"] * rim_lu / 2
        if lost > 0:
            alpha = np.where(on_rim & ((1 - slope) * rim_lu < 2 * lost), alpha * 0.5, alpha)
    alpha = np.clip(alpha, 0, 1) * inside
    if m.get("edge_out"):
        # his edge stands further out than the traced outline on the upper
        # sides: his pixels there are denser by the same +0.05 from 0.6 LU
        # outside to 0.25 in, a shift of the edge, not a strip. A strip 0.28
        # LU wide with its own edge read as a white line along the top
        # (owner, 2026-10-25). So the edge is carried out, in its own tone
        # and alpha, by the width per side; to nothing toward the points
        w_out, pt_out = m["edge_out"]
        poly = F.polygon(name, idx)
        out_d = np.min([F._seg_dist(px, py, p, q) for p, q in zip(poly, poly[1:] + poly[:1])], 0)
        if m.get("scroll"):
            # at the notch the glass ends on the fillet's arc, not on the
            # sharp corner (from the corner it stood off as a white crescent)
            r_n = m["scroll"]["round"]
            cone, dist_c = _notch_arc(name, idx, r_n, px, py)
            out_d = np.where(cone & (dist_c <= r_n), r_n - dist_c, out_d)
        f = np.clip(near / pt_out, 0, 1)
        width = w_out * _at_s(*_side_table(name, idx, m["edge_out_side"]), sf["s"])[..., 0] * f * f * (3 - 2 * f)
        sk = ~inside & (out_d < width)
        one = np.ones(px.shape)
        edge_tone = np.clip(base * dark(one)[..., None] + gain * glint(one)[..., None], 0, 1)
        tone[sk] = edge_tone[sk]
        alpha[sk] = m["rim_alpha"] * floor
    return tone, alpha, px, py, facet, (base, gain, dark, glint, floor)


def _darts(name, idx, size, weigh=True):
    """Each dart on its canvas at 1/_DART_SCALE of the size, its samples laid
    into the frame one to one."""
    n = size * SS
    pre = np.zeros((n, n, 3))
    alpha = np.zeros((n, n))
    for pn in F.parts(name):
        _b, _i, (ox, oy) = F.PART[pn]
        t, a, px, py = _body(pn, idx, size // F._DART_SCALE)[:4]
        if name in F._STAR:
            a = a * F.sector(pn, ox + px / F._DART_SCALE, oy + py / F._DART_SCALE, idx)
        if weigh:
            a = a * _dart_weight(name, idx)[pn]
        x0, y0, k = int(round(ox * n / V.LOGICAL)), int(round(oy * n / V.LOGICAL)), a.shape[0]
        pre[y0:y0 + k, x0:x0 + k] += t * a[..., None]
        alpha[y0:y0 + k, x0:x0 + k] += a
    tone, alpha = pre / np.maximum(alpha, 1e-9)[..., None], np.clip(alpha, 0, 1)
    if name in F._STAR:
        tone, alpha = _ring(name, idx, size, *_fillet(name, idx, size, tone, alpha))
    return tone, alpha


def _at(img, pts, sc):
    """img (samples, sc of them per LU) bilinear at points in LU."""
    n = img.shape[0]
    x, y = pts[:, 0] * sc - 0.5, pts[:, 1] * sc - 0.5
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    fx, fy = (x - x0)[:, None], (y - y0)[:, None]
    g = lambda yy, xx: img[np.clip(yy, 0, n - 1), np.clip(xx, 0, n - 1)].reshape(len(x), -1)
    return (g(y0, x0) * (1 - fx) * (1 - fy) + g(y0, x0 + 1) * fx * (1 - fy)
            + g(y0 + 1, x0) * (1 - fx) * fy + g(y0 + 1, x0 + 1) * fx * fy)


_FILLET = (1.6, 1.5)   # LU: SizeAll's concave corners' radius, and the run past it the rim is eased back over
# in rims, how deep from the arc it is laid on: the rim's dark valley too,
# else the two darts' valleys cross under it in a crease (owner, 2026-10-26)
_FILLET_DEEP = 4.5


def _fillet(name, idx, size, tone, alpha):
    """SizeAll's concave corners, where two darts' outer rims meet, rounded
    (owner, 2026-10-26: the joint smooth from outside): the glass filled out
    to an arc, its rim the two sides' own profiles, read a little off the
    arc and handed from one to the other round it."""
    n = size * SS
    sc = n / float(V.LOGICAL)
    rim = F.SURFACE["Arrow"]["rim"] / F._DART_SCALE
    depth = np.arange(-2.0 / sc, _FILLET_DEEP * rim, 0.5 / sc)
    rho, run = _FILLET
    m, u, big, rw, phi, _r = F._star_geom(name, idx)
    px, py = F.grid(size, SS)
    pre = tone * alpha[..., None]
    out_pre, out_a = pre.copy(), alpha.copy()
    for uu in u:
        sides = []
        for v, sgn in ((uu, 1), (F._rot(uu, 90), -1)):
            a = m + big * v
            e = m + rw * F._rot(v, sgn * phi) - a
            sides.append((a, e / np.hypot(*e)))
        (a1, e1), (a2, e2) = sides
        W = F._meet(a1, e1, a2, e2)
        t1, t2 = -e1, -e2                       # from the corner out along each side
        b = (t1 + t2) / np.hypot(*(t1 + t2))    # into the notch
        half = np.arccos(np.clip(t1 @ t2, -1, 1)) / 2
        c = W + b * rho / np.sin(half)
        tan_l = rho / np.tan(half)
        prof, nrms = [], []
        for tt in (t1, t2):
            nn = np.array([-tt[1], tt[0]])
            if nn @ b > 0:
                nn = -nn                        # into the glass
            pts = W + (tan_l + run) * tt + np.outer(depth, nn)
            al = _at(alpha, pts, sc)[:, 0]
            prof.append((_at(pre, pts, sc), al))
            nrms.append(nn)
        n1, n2 = nrms
        # depth into the glass from the rounded outline: the notch is a
        # wedge, its apex moved to c and grown by rho
        qx, qy = px - c[0], py - c[1]
        g1, g2 = qx * n1[0] + qy * n1[1], qx * n2[0] + qy * n2[1]
        s1, s2 = qx * t1[0] + qy * t1[1], qx * t2[0] + qy * t2[1]
        qd = np.hypot(qx, qy)
        r1 = np.where(s1 > 0, np.abs(g1), qd)
        r2 = np.where(s2 > 0, np.abs(g2), qd)
        outside = (g1 > 0) | (g2 > 0)
        d = np.where(outside, np.minimum(np.where(g1 > 0, r1, np.inf), np.where(g2 > 0, r2, np.inf)),
                     np.maximum(g1, g2)) - rho
        # round the arc from side 1 to side 2: by the angle off n1 toward n2
        span = np.arccos(np.clip(n1 @ n2, -1, 1))
        ang = np.arctan2(n1[0] * qy - n1[1] * qx, qx * n1[0] + qy * n1[1])
        if F._cross(n1, n2) < 0:
            ang = -ang
        s = np.clip(ang / span, 0, 1)
        s = s * s * (3 - 2 * s)
        rp = np.stack([np.interp(d, depth, prof[0][0][:, k]) * (1 - s) + np.interp(d, depth, prof[1][0][:, k]) * s
                       for k in range(3)], -1)
        ra = np.interp(d, depth, prof[0][1]) * (1 - s) + np.interp(d, depth, prof[1][1]) * s
        # laid on round the corner, eased back into the darts along each side
        # past the arc and across the rim's inner line
        along = np.maximum((px - W[0]) * t1[0] + (py - W[1]) * t1[1], (px - W[0]) * t2[0] + (py - W[1]) * t2[1])
        wa = np.clip((tan_l + run - along) / run, 0, 1)
        wd = np.clip(((_FILLET_DEEP - 0.45) * rim - d) / (0.3 * rim), 0, 1)
        w = wa * wa * (3 - 2 * wa) * wd * wd * (3 - 2 * wd) * (np.hypot(px - W[0], py - W[1]) < tan_l + run + 2)
        out_pre = out_pre * (1 - w[..., None]) + rp * w[..., None]
        out_a = out_a * (1 - w) + ra * w
    return out_pre / np.maximum(out_a, 1e-9)[..., None], out_a


def _ring(name, idx, size, tone, alpha):
    """SizeAll's round hole cut into the darts, its rim one profile all
    round: the darts' rim across the star's eight sides, read at their
    middles and averaged, laid on by depth from the circle and eased into
    the glass past it. Read across the darts' own square hole it was the
    notch's dark pocket, a black ring."""
    n = size * SS
    sc = n / float(V.LOGICAL)
    mid, r_c = F.ring(name, idx)
    rim = F.SURFACE["Arrow"]["rim"] / F._DART_SCALE
    pitch = 1.0 / sc
    depth = np.arange(-2 * pitch, 1.6 * rim, pitch / 2)

    def at(img, pts):
        x, y = pts[:, 0] * sc - 0.5, pts[:, 1] * sc - 0.5
        x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
        fx, fy = (x - x0)[:, None], (y - y0)[:, None]
        g = lambda yy, xx: img[np.clip(yy, 0, n - 1), np.clip(xx, 0, n - 1)].reshape(len(x), -1)
        return (g(y0, x0) * (1 - fx) * (1 - fy) + g(y0, x0 + 1) * fx * (1 - fy)
                + g(y0 + 1, x0) * (1 - fx) * fy + g(y0 + 1, x0 + 1) * fx * fy)

    pre_p, al_p = 0.0, 0.0
    m, u, big, rw, phi, _r = F._star_geom(name, idx)
    for uu in u:
        a = m + big * uu
        for sgn in (1, -1):
            wg = m + rw * F._rot(uu, sgn * phi)
            e = (wg - a) / np.hypot(*(wg - a))
            nrm = np.array([-e[1], e[0]])
            if nrm @ (m - a) < 0:
                nrm = -nrm
            # the middle of each of the star's eight sides, off the points
            pts = (a + wg) / 2 + np.outer(depth, nrm)
            pre_p = pre_p + at(tone * alpha[..., None], pts) / 8
            al_p = al_p + at(alpha, pts)[:, 0] / 8
    tone_p = pre_p / np.maximum(al_p, 1e-9)[:, None]

    px, py = F.grid(size, SS)
    d = np.hypot(px - mid[0], py - mid[1]) - r_c
    ring_t = np.stack([np.interp(d, depth, tone_p[:, c]) for c in range(3)], -1)
    ring_a = np.interp(d, depth, al_p)
    # eased into the darts' glass across the rim's inner line: read from
    # the outer sides, the glass past it is theirs, lighter, a halo
    w = np.clip((1.15 * rim - d) / (0.3 * rim), 0, 1)
    w = (w * w * (3 - 2 * w))[..., None]
    pre = (tone * alpha[..., None]) * (1 - w) + (ring_t * ring_a[..., None]) * w
    alpha = alpha * (1 - w[..., 0]) + ring_a * w[..., 0]
    return pre / np.maximum(alpha, 1e-9)[..., None], alpha


_WEIGHT_AT = 128   # size the darts' glass is weighed at against his 32


@functools.lru_cache(maxsize=None)
def _dart_weight(name, idx):
    """{dart: what its alpha is scaled by} to weigh what his pixels of it do.
    They are narrow, mostly rim, and the rim holds Arrow's alpha: the outline
    was his but the glass 5-20% denser (median alpha 0.56 against 0.49),
    heavier at every size than his 32 (scale_drift 0.17-0.97). Weighed as a
    whole, IBeam's lighter upper dart against his heavier lower one moved
    the centre 0.34 LU, so each is weighed on his pixels of it."""
    al = _darts(name, idx, _WEIGHT_AT, weigh=False)[1]
    k = _WEIGHT_AT * SS // V.LOGICAL
    ours = al.reshape(V.LOGICAL, k, V.LOGICAL, k).mean(axis=(1, 3))
    his = np.asarray(H.original(name, idx))[..., 3] / 255.0
    own = F.owner(name, idx)
    return {pn: float(his[own == F.PART[pn][1]].sum() / ours[own == F.PART[pn][1]].sum())
            for pn in F.parts(name)}


_PEN_ALONG = 0.5    # LU, the step along the pen his rim colour is read in
_PEN_ACROSS = 0.25  # LU, the step of his tone across the rod
_PEN_MEET = 3.0     # LU across the axis the two sides' rim colours ease over
_PEN_RIM = 0.8      # of Arrow's rim: his pen's is one pixel of his 32 (1 LU); Arrow's 1.6
                    # over a rod 3.8 LU in half width read as fog; 0.65 crisper by eye
                    # by little, delta_e[6] 10.1 -> 10.5
_CRESCENT = (0.35, 0.80, 0.18)   # across the clip from its inner edge (share), the end of its
                                 # front along the pen (share of L), its half width (share)
_CRESCENT_TONE = 222   # release 1.1.0's crescent (99th of its clip; his eased peak 202)
_PEN_EASE = 0.6     # LU along the pen his colours are eased over: his edge highlights kept short


def _pen_axes(px, py):
    q = np.asarray(F.PEN["point"])
    a = np.radians(F.PEN["deg"])
    t = (px - q[0]) * np.cos(a) + (py - q[1]) * np.sin(a)
    s = -(px - q[0]) * np.sin(a) + (py - q[1]) * np.cos(a)
    return t, s


@functools.lru_cache(maxsize=None)
def _pen_author(name):
    """His pen (frame 8) read off his pixels, premultiplied means: the rim
    colour by side and place along it, eased over 1 LU (his bright clip and
    dark flanks where he drew them), the inside by place across the rod."""
    last = len(F.MORPH[name]["pen"]) - 1
    L = F.MORPH[name]["pen"][last]
    im = np.asarray(H.original(name, last)).astype(np.float64)
    rgb = V.srgb_to_linear(im[..., :3].astype(np.uint8)).astype(np.float64)
    al = im[..., 3] / 255.0
    px, py = F.grid(32)
    d = F.pen_sdf(name, last, px, py)
    t, s = _pen_axes(px, py)
    along = np.arange(-1.0, L + 1.0 + 1e-9, _PEN_ALONG)
    lo, hi = _RIM_DEPTH
    on = (d > lo) & (d < hi) & (al > 0.02)
    rim = np.zeros((2, len(along), 3))
    ker = np.exp(-0.5 * (np.arange(-4, 5) * _PEN_ALONG / _PEN_EASE) ** 2)
    for side in (0, 1):
        sel = on & ((s < 0) if side == 0 else (s >= 0))
        k = np.clip(np.round((t[sel] - along[0]) / _PEN_ALONG).astype(int), 0, len(along) - 1)
        pre = np.zeros((len(along), 3))
        w = np.zeros(len(along))
        np.add.at(pre, k, rgb[sel] * al[sel, None])
        np.add.at(w, k, al[sel])
        pre = np.stack([np.convolve(pre[:, c], ker, "same") for c in range(3)], -1)
        w = np.convolve(w, ker, "same")
        have = w > 1e-3
        for c in range(3):
            rim[side, :, c] = np.interp(along, along[have], pre[have, c] / w[have])
    body = (d >= hi) & (t > F.PEN["nib"]) & (t < L - F.PEN["hw"])
    grid = np.arange(-F.PEN["clip"][3], F.PEN["hw"] + 1e-9, _PEN_ACROSS)
    j = np.clip(np.round((s - grid[0]) / _PEN_ACROSS).astype(int), 0, len(grid) - 1)
    p_in = np.zeros((len(grid), 3))
    a_in = np.zeros(len(grid))
    n_in = np.zeros(len(grid))
    np.add.at(p_in, j[body], rgb[body] * al[body, None])
    np.add.at(a_in, j[body], al[body])
    np.add.at(n_in, j[body], 1.0)
    have = n_in > 0
    tone_in = np.stack([np.interp(grid, grid[have], p_in[have, c] / np.maximum(a_in[have], 1e-6)) for c in range(3)], -1)
    alpha_in = np.interp(grid, grid[have], a_in[have] / n_in[have])
    return along, rim, grid, tone_in, alpha_in


@functools.lru_cache(maxsize=None)
def _pen_weight(name):
    """What the pen's alpha is scaled by to weigh what his does: narrow and
    a good half rim with Arrow's alpha, it was 8% heavier (as the darts)."""
    last = len(F.MORPH[name]["pen"]) - 1
    al = _pen(name, last, _WEIGHT_AT, weigh=False)[1]
    k = _WEIGHT_AT * SS // V.LOGICAL
    ours = al.reshape(V.LOGICAL, k, V.LOGICAL, k).mean(axis=(1, 3)).sum()
    return float(np.asarray(H.original(name, last))[..., 3].sum() / 255.0 / ours)


def _rod(name, d, rim_col, tone, alpha, size):
    """Arrow's glass across the rim of a shape of depth d (LU, + inside):
    its hairline, glint, base and alpha over the given inside tone, the rim
    _PEN_RIM of Arrow's."""
    m = MATERIAL[name]
    rim_lu = F.SURFACE[name]["rim"] * _PEN_RIM
    inside = d > 0
    slope = np.clip(1.0 - d / rim_lu, 0, 1) * inside
    on_rim = inside & (d < rim_lu)
    pitch = V.LOGICAL / float(size)
    shape = d.shape

    def _seen(frac):
        return float(np.clip(frac * rim_lu / pitch - _SEEN_FROM, 0.0, 1.0))
    edge_dark = m["edge_dark"] * _seen(m["edge_w"])
    floor = 1.0 - (1.0 - m["outer_floor"]) * _seen(m["outer_soft"])

    def dark(sl):
        return 1.0 - edge_dark * np.clip((sl - (1 - m["edge_w"])) / m["edge_w"], 0, 1)

    def glint(sl):
        xx = (1 - sl) - m["glint"]
        return (np.exp(-0.5 * np.abs(xx / m["glint_w"]) ** m.get("glint_shape", 2.0))
                + m["glint_core"] * np.exp(-0.5 * (xx / m["glint_core_w"]) ** 2))

    u_grid = np.linspace(0.0, 1.0, 201)
    lum = rim_col.mean(-1, keepdims=True)
    rl = _pen_author(name)[1].reshape(-1, 3).mean(-1)   # the glint's gain by his rim's levels
    lo_l, hi_l = np.percentile(rl, 10), np.percentile(rl, 90)
    g0, g1 = m["glint_gain"]
    gain = g0 + (g1 - g0) * np.clip((lum - lo_l) / max(hi_l - lo_l, 1e-6), 0, 1) ** m["glint_place"]
    spec = gain * glint(slope)[..., None]
    base = np.clip((rim_col - gain * glint(u_grid).mean()) / dark(u_grid).mean(), 0.0, None)
    eb = np.clip(slope / m["base_soft"], 0, 1)
    eb = eb * eb * (3 - 2 * eb)
    rim_tone = tone + (base * dark(slope)[..., None] - tone) * eb[..., None] + spec
    ease = np.clip(slope / m["inner_soft"], 0, 1)
    facet_tone = tone
    tone = np.where(on_rim[..., None], tone + (rim_tone - tone) * ease[..., None], tone)
    sg = 1.0 - m["glint"]
    peak = base * dark(np.full(shape, sg))[..., None] + gain * glint(np.full(shape, sg))[..., None]
    tone = np.where((on_rim & (slope < sg))[..., None], np.maximum(tone, np.minimum(peak, facet_tone)), tone)
    tone = np.clip(tone, 0, 1)
    alpha = np.where(on_rim, alpha + (m["rim_alpha"] - alpha) * np.clip(slope / m["rim_solid"], 0, 1), alpha)
    alpha = alpha * (floor + (1 - floor) * np.clip((1 - slope) / m["outer_soft"], 0, 1))
    return tone, np.clip(alpha, 0, 1) * inside


@functools.lru_cache(maxsize=None)
def _clip_peak_alpha(name):
    """His clip's densest pixel off the rod (frame 8)."""
    last = len(F.MORPH[name]["pen"]) - 1
    px, py = F.grid(32)
    sel = (F.pen_sdf(name, last, px, py, "clip") > 0) & (F.pen_sdf(name, last, px, py, "body") < 0)
    return float(np.asarray(H.original(name, last))[..., 3][sel].max() / 255.0)


@functools.lru_cache(maxsize=None)
def _clip_author(name):
    """His clip (frame 8) where it stands off the rod, by place along it,
    eased over 1 LU: premultiplied tone and mean alpha."""
    last = len(F.MORPH[name]["pen"]) - 1
    L = F.MORPH[name]["pen"][last]
    im = np.asarray(H.original(name, last)).astype(np.float64)
    rgb = V.srgb_to_linear(im[..., :3].astype(np.uint8)).astype(np.float64)
    al = im[..., 3] / 255.0
    px, py = F.grid(32)
    sel = (F.pen_sdf(name, last, px, py, "clip") > 0) & (F.pen_sdf(name, last, px, py, "body") < 0)
    t = _pen_axes(px, py)[0]
    along = np.arange(-1.0, L + 1.0 + 1e-9, _PEN_ALONG)
    k = np.clip(np.round((t[sel] - along[0]) / _PEN_ALONG).astype(int), 0, len(along) - 1)
    ker = np.exp(-0.5 * (np.arange(-4, 5) * _PEN_ALONG / _PEN_EASE) ** 2)
    pre, w, n = np.zeros((len(along), 3)), np.zeros(len(along)), np.zeros(len(along))
    np.add.at(pre, k, rgb[sel] * al[sel, None])
    np.add.at(w, k, al[sel])
    np.add.at(n, k, 1.0)
    pre = np.stack([np.convolve(pre[:, c], ker, "same") for c in range(3)], -1)
    w, n = np.convolve(w, ker, "same"), np.convolve(n, ker, "same")
    have = n > 1e-3
    tone = np.stack([np.interp(along, along[have], pre[have, c] / np.maximum(w[have], 1e-6)) for c in range(3)], -1)
    return along, tone, np.interp(along, along[have], w[have] / n[have])


_BETWEEN_MERGE = 2.0  # LU, the pointer and the pen grown into one shape (smooth union)
_BETWEEN_TONE = 1.0   # LU his colour is eased over inside: his 32 px read as blotches
_BETWEEN_WING = 0.6   # LU, the wing tips' round: his right wing ends 1.2 LU short of the
                      # scaled one, round; sharp it stood as a hook by the clip


def _resize(img, n):
    from PIL import Image
    return np.stack([np.asarray(Image.fromarray(img[..., c].astype(np.float32), "F").resize((n, n), Image.BICUBIC))
                     for c in range(img.shape[-1])], -1).astype(np.float64)


@functools.lru_cache(maxsize=None)
def _between_tone(name, idx, sigma):
    """His frame's colour on a fine grid, eased over sigma LU, and his alpha."""
    im = np.asarray(H.original(name, idx)).astype(np.float64)
    al = im[..., 3:] / 255.0
    pre = V.srgb_to_linear(im[..., :3].astype(np.uint8)).astype(np.float64) * al
    n = 512
    fine = _resize(np.concatenate([pre, al], -1), n)
    step = V.LOGICAL / n
    fine = np.stack([_blur(fine[..., c], sigma / step) for c in range(4)], -1)
    return np.clip(fine[..., :3] / np.maximum(fine[..., 3:], 1e-3), 0, 1), np.clip(fine[..., 3], 0, 1)


def _between(name, idx, size):
    """His in-between frame as one shape: the shrunk pointer and the short
    pen grown together, Arrow's glass over it, his colour on it (eased),
    weighed to his mass. A cross-fade of the two stood as a double exposure."""
    px, py = F.grid(size, SS)
    q = np.asarray(list(F.outline(name, idx).values()), dtype=np.float64)
    da = np.min([F._seg_dist(px, py, p0, p1) for p0, p1 in zip(q, np.roll(q, -1, 0))], 0)
    da = np.where(F._in_poly(px, py, q), da, -da)
    corners = F.outline(name, idx)
    order = list(corners)
    for key in ("B", "C"):
        i = order.index(key)
        c = np.asarray(corners[key])
        u1 = c - np.asarray(corners[order[i - 1]])
        u2 = c - np.asarray(corners[order[(i + 1) % len(order)]])
        u1, u2 = u1 / np.hypot(*u1), u2 / np.hypot(*u2)
        half = np.arccos(np.clip(u1 @ u2, -1, 1)) / 2
        o = c - (u1 + u2) / np.hypot(*(u1 + u2)) * _BETWEEN_WING / np.sin(half)
        cap = ((px - o[0]) * u1[0] + (py - o[1]) * u1[1] > 0) & ((px - o[0]) * u2[0] + (py - o[1]) * u2[1] > 0)
        da = np.where(cap, _BETWEEN_WING - np.hypot(px - o[0], py - o[1]), da)
    dp = F.pen_sdf(name, idx, px, py)
    k = _BETWEEN_MERGE
    h = np.clip(0.5 + 0.5 * (da - dp) / k, 0, 1)
    d = dp + (da - dp) * h + k * h * (1 - h)
    n = size * SS
    rim = _resize(_between_tone(name, idx, 0.4)[0], n)
    tone, al = (_resize(c if c.ndim == 3 else c[..., None], n) for c in _between_tone(name, idx, _BETWEEN_TONE))
    tone, alpha = _rod(name, d, np.clip(rim, 0, 1), np.clip(tone, 0, 1), np.clip(al[..., 0], 0.3, 1), size)
    ours = alpha.mean() * V.LOGICAL ** 2
    return tone, np.clip(alpha * np.asarray(H.original(name, idx))[..., 3].sum() / 255.0 / max(ours, 1e-6), 0, 1)


def _pen(name, idx, size, weigh=True):
    """The pen of frame idx at the sample grid: tone, alpha. Arrow's glass
    across the rim (its hairline, glint, base and alpha), his tone on it."""
    along, rim_c, grid, tone_in, alpha_in = _pen_author(name)
    px, py = F.grid(size, SS)
    d = F.pen_sdf(name, idx, px, py, "body")
    t, s = _pen_axes(px, py)
    # his frame 8's colour at the same share of the length
    last = len(F.MORPH[name]["pen"]) - 1
    tt = t * F.MORPH[name]["pen"][last] / F.MORPH[name]["pen"][idx]
    # the sides meet round the end and at the nib's point: eased across
    # the axis, a cut there stood as a notch in the rim
    w = np.clip(0.5 + s / _PEN_MEET, 0, 1)[..., None]
    w = w * w * (3 - 2 * w)
    rim_col = (np.stack([np.interp(tt, along, rim_c[0, :, c]) for c in range(3)], -1) * (1 - w)
               + np.stack([np.interp(tt, along, rim_c[1, :, c]) for c in range(3)], -1) * w)
    tone = np.stack([np.interp(s, grid, tone_in[:, c]) for c in range(3)], -1)
    alpha = np.interp(s, grid, alpha_in)

    tone, alpha = _rod(name, d, rim_col, tone, alpha, size)
    # the clip: a block of the same glass over the rod's upper flank, his
    # tone along it (bright ahead, dim behind), laid over the rod so its
    # edge shows through as the crease
    dc = F.pen_sdf(name, idx, px, py, "clip")
    c_along, c_tone, c_alpha = _clip_author(name)
    c_col = np.stack([np.interp(tt, c_along, c_tone[:, c]) for c in range(3)], -1)
    # not below the rod's own tone: his clip's back (88-120 on 32 px, half
    # its pixels the rim's dark) stood as a smudge at the end
    c_col = np.maximum(c_col, tone_in[len(tone_in) // 2])
    # the crescent: his clip's brightest tone (215 on 32 px) as a leaf just
    # past the crease, over the clip's front half, as release 1.1.0 lit it
    c0, c1, s_in, s_out, _nose = F.PEN["clip"]
    L8 = F.MORPH[name]["pen"][last]
    v = np.clip((tt - c0 * L8) / ((_CRESCENT[1] - c0) * L8), 0, 1)
    leaf = np.sin(np.pi * v) ** 2
    across = (-s - s_in) / (s_out - s_in) * F.MORPH[name]["pen"][last] / F.MORPH[name]["pen"][idx]
    w = leaf * np.exp(-0.5 * ((across - _CRESCENT[0]) / (_CRESCENT[2] * (0.4 + 0.6 * leaf))) ** 2)
    peak = c_tone[np.argmax(c_tone.mean(-1))]
    peak = peak * V.srgb_to_linear(np.array([_CRESCENT_TONE], np.uint8))[0] / max(peak.mean(), 1e-6)
    c_in = c_col + (np.maximum(peak, c_col) - c_col) * w[..., None]
    # and as dense as his densest clip pixel (0.92 there): at the clip's 0.6
    # the ground under it ate the tone
    a_in = np.interp(tt, c_along, c_alpha)
    a_in = a_in + (_clip_peak_alpha(name) - a_in) * w
    t_c, a_c = _rod(name, dc, c_in, c_in, a_in, size)   # the clip is mostly rim
    pre = t_c * a_c[..., None] + tone * (alpha * (1 - a_c))[..., None]
    alpha = a_c + alpha * (1 - a_c)
    tone = pre / np.maximum(alpha, 1e-9)[..., None]
    if weigh:
        alpha = alpha * _pen_weight(name)
    return tone, np.clip(alpha, 0, 1)


@functools.lru_cache(maxsize=None)
def _frame(name, idx, size, key=None):
    if name in F.DARTS:
        if size % 4:
            raise ValueError("%s at %d: darts need a size divisible by 4" % (name, size))
        tone, alpha = _darts(name, idx, size)
    elif name in GL.NAMES:
        tone, alpha, px, py = _body("Arrow", idx, size)[:4]
        tone, alpha = _badge(name, px, py, tone, alpha, V.LOGICAL / float(size))
    elif name in F.MORPH:
        # Handwriting: his frame 0 shrunk, in its tone, mixed into the pen
        share = F.MORPH[name]["share"][idx]
        if idx in F.MORPH[name]["trace"]:
            share = None
        pre = np.zeros((size * SS, size * SS, 3))
        alpha = np.zeros((size * SS, size * SS))
        if share is None:
            t_p, a_p = _between(name, idx, size)
            pre, alpha = t_p * a_p[..., None], a_p
        elif share < 1:
            t_a, a_a = _body(name, idx, size, 0)[:2]
            pre += t_a * a_a[..., None] * (1 - share)
            alpha += a_a * (1 - share)
        if share is not None and share > 0:
            t_p, a_p = _pen(name, idx, size)
            pre += t_p * a_p[..., None] * share
            alpha += a_p * share
        tone = pre / np.maximum(alpha, 1e-9)[..., None]
    elif name in F.SHRINK:
        # the pointer is his frame 0 shrunk, its tone his frame 0's: his
        # later frames are red where the sign covers it
        tone, alpha, px, py = _body(name, idx, size, 0)[:4]
        tone, alpha = _sign(name, idx, px, py, tone, alpha, V.LOGICAL / float(size))
    else:
        tone, alpha, px, py, _facet, _rim = _body(name, idx, size, key)
        if MATERIAL[name].get("glyph"):
            tone, alpha = _glyph(name, px, py, tone, alpha, V.LOGICAL / float(size))
    pre = tone * alpha[..., None]
    n = size
    pre = pre.reshape(n, SS, n, SS, 3).mean(axis=(1, 3))
    al = alpha.reshape(n, SS, n, SS).mean(axis=(1, 3))
    lin = pre / np.maximum(al, 1e-9)[..., None]
    rgb, a8 = V.linear_to_srgb(lin), np.round(al * 255).astype(np.uint8)
    if name in F.SHRINK and name not in F.MORPH:
        rgb = _sat_band(name, idx, rgb, a8)
    return np.dstack([rgb, a8])


# NO's mean saturation kept within (lo, hi) of his frame's: the sign grows
# over a pointer that fades, so ours ran 4% under him on frame 7 and 13%
# over on 8, past the build's -2/+12% check. Inside the band nothing moves
_SAT_BAND = (1.0, 1.08)


def _sat_band(name, idx, rgb, a8):
    o = np.asarray(H.original(name, idx)).astype(np.float64)
    his = H._mean_sat(o[..., :3], o[..., 3])
    ours = H._mean_sat(rgb.astype(np.float64), a8.astype(np.float64))
    target = float(np.clip(ours, his * _SAT_BAND[0], his * _SAT_BAND[1]))
    if his < 1e-4 or target == ours:
        return rgb
    out = H._sat_match(rgb.astype(np.float64), a8.astype(np.float64), target, iters=8)
    return np.round(out).astype(np.uint8)


def _band(x, lo, hi, e):
    """1 for lo < x < hi, each step a smoothstep `e` wide."""
    a = np.clip((x - lo) / e + 0.5, 0, 1)
    b = np.clip((hi - x) / e + 0.5, 0, 1)
    return a * a * (3 - 2 * a) * b * b * (3 - 2 * b)


def _bezier(p0, p1, p2, n=200):
    t = np.linspace(0.0, 1.0, n)[:, None]
    return (1 - t) ** 2 * p0 + 2 * (1 - t) * t * p1 + t ** 2 * p2, t[:, 0]


def _ribbon(px, py, curve, tt, sel):
    """Arc parameter and signed offset from a sampled curve, for the points
    in sel (chunked: the window is small, the curve dense)."""
    pts = np.stack([px[sel], py[sel]], 1)
    t_out = np.empty(len(pts))
    d_out = np.empty(len(pts))
    tang = np.gradient(curve, axis=0)
    tang /= np.hypot(tang[:, 0], tang[:, 1])[:, None]
    for a in range(0, len(pts), 20000):
        q = pts[a:a + 20000]
        dd = (q[:, None, 0] - curve[None, :, 0]) ** 2 + (q[:, None, 1] - curve[None, :, 1]) ** 2
        k = np.argmin(dd, 1)
        t_out[a:a + 20000] = tt[k]
        v = q - curve[k]
        # past either end the nearest sample is the end itself: no ribbon
        # there, or its line runs on along the tangent as a needle
        d = v[:, 0] * -tang[k, 1] + v[:, 1] * tang[k, 0]
        d_out[a:a + 20000] = np.where((k == 0) | (k == len(tt) - 1), np.inf, d)
    return t_out, d_out


def _notch_arc(name, idx, radius, px, py):
    """The fillet's cone at the notch (bounded 2 rims past the arc) and the
    distance from the fillet's centre: the arc is at `radius`."""
    o = F.outline(name, idx)
    rim = F.SURFACE[name]["rim"]
    j = np.asarray(o["J"])
    e1 = (np.asarray(o["C"]) - j) / np.hypot(*(np.asarray(o["C"]) - j))
    e2 = (np.asarray(o["B"]) - j) / np.hypot(*(np.asarray(o["B"]) - j))
    ob = (e1 + e2) / np.hypot(*(e1 + e2))       # out of the glass, between the sides
    sin_h = np.sqrt(max(0.0, 1.0 - (e1 @ ob) ** 2))
    c = j + ob * radius / sin_h
    vx, vy = px - c[0], py - c[1]
    dist = np.hypot(vx, vy)
    cone = ((-(vx * ob[0] + vy * ob[1])) > dist * sin_h) & (dist < radius + 2 * rim)
    return cone, dist


def _round_notch(name, idx, radius, px, py, facet, u):
    """The notch's corner rounded to a fillet of `radius` LU: the twist
    curves through it, and a sharp mitre under it ran the rim's edge and
    inner line on straight past the curve (owner, 2026-10-25: the line
    continues, rough). Inside the fillet's cone the bevel is measured from
    the arc, so every line across the rim bends with it; the cone's edges
    are the tangent points, where arc and sides agree."""
    o = F.outline(name, idx)
    rim = F.SURFACE[name]["rim"]
    j = np.asarray(o["J"])
    cone, dist = _notch_arc(name, idx, radius, px, py)
    inner = cone & (dist > radius)
    # the fold A-J splits the corner: upper facet on C's side
    a = np.asarray(o["A"])
    side = (j - a)[0] * (py - a[1]) - (j - a)[1] * (px - a[0])
    c_side = (j - a)[0] * (o["C"][1] - a[1]) - (j - a)[1] * (o["C"][0] - a[0])
    facet = np.where(cone, np.where(inner, np.where(side * c_side > 0, 1, 2), 0), facet).astype(np.uint8)
    u = np.where(inner, np.clip((dist - radius) / rim, 0.0, 1.0), u)
    return facet, u


def _scroll(name, idx, m, px, py, inside, rim_col, tone, pitch):
    """The twist at the notch as the net drew it, clean: a dark ribbon comes
    in along the upper rim, rounds the notch and thins out down the lower
    one; a lit blade rises along the lower rim to a point at the corner,
    under the dark ribbon's edge. Edges keen (_band), insides smooth, each
    ribbon fading in from the rim it grows out of so no seam shows."""
    c = m["scroll"]
    o = F.outline(name, idx)
    rim = F.SURFACE[name]["rim"]
    j = np.asarray(o["J"])
    e1 = (np.asarray(o["C"]) - j) / np.hypot(*(np.asarray(o["C"]) - j))
    e2 = (np.asarray(o["B"]) - j) / np.hypot(*(np.asarray(o["B"]) - j))
    sides, bis = F._sides(name, idx)
    n1 = next(n for p, q, n in sides if np.allclose(q, j))
    n2 = next(n for p, q, n in sides if np.allclose(p, j))
    b = bis[F.ORDER.index("J")]
    keen = max(0.035, 0.6 * pitch)
    r = np.hypot(px - j[0], py - j[1])
    sel = inside & (r < max(c["dark_from"], c["lit_from"]) + 0.5)
    lum = rim_col

    # the lit blade first, the dark ribbon over it
    curve, tt = _bezier(j + c["lit_from"] * e2 + 0.38 * rim * n2, j + 1.0 * e2 + 0.38 * rim * n2,
                        j + 0.3 * rim * b)
    t, d = _ribbon(px, py, curve, tt, sel)
    hw = c["lit_w"] * rim * (1 - t) ** 0.7
    v = np.clip(np.abs(d) / np.maximum(hw, 1e-6), 0, 1)
    shade = 1 + (c["lit"] - 1) * (1 - v * v)
    fade = np.clip(t / c["fade"], 0, 1)
    cov = _band(d, -hw, hw, keen) * fade * fade * (3 - 2 * fade)
    col = lum[sel] * shade[:, None]
    tsel = tone[sel]
    tone[sel] = tsel + (col - tsel) * cov[:, None]

    curve, tt = _bezier(j + c["dark_from"] * e1 + 0.45 * rim * n1, j + 0.75 * rim * b,
                        j + c["dark_to"] * e2 + 0.7 * rim * n2)
    t, d = _ribbon(px, py, curve, tt, sel)
    w0, w1 = c["dark_w"]
    hw = rim * (w0 + (w1 - w0) * t)
    v = np.clip(d / np.maximum(hw, 1e-6), -1, 1)
    # darkest at its middle, lifting to the rim's tone at both edges; the
    # light catches its outer edge as a keen line
    shade = c["dark"] + (1 - c["dark"]) * v * v
    shade = shade + c.get("edge_lit", 0.5) * _band(d, -hw, -hw + 0.06, keen * 0.7)
    fin = np.clip((1 - t) / 0.35, 0, 1)
    fade = np.clip(t / c["fade"], 0, 1) * fin * fin * (3 - 2 * fin)
    cov = _band(d, -hw, hw, keen) * fade
    col = lum[sel] * shade[:, None]
    tsel = tone[sel]
    tone[sel] = tsel + (col - tsel) * cov[:, None]
    return tone


@functools.lru_cache(maxsize=None)
def _spline(pts, n=8):
    """Catmull-Rom through the points, as a polyline."""
    p = np.asarray(pts, dtype=np.float64)
    p = np.vstack([2 * p[0] - p[1], p, 2 * p[-1] - p[-2]])
    t = (np.arange(n) / n)[:, None]
    out = []
    for i in range(1, len(p) - 2):
        p0, p1, p2, p3 = p[i - 1], p[i], p[i + 1], p[i + 2]
        out.append(0.5 * (2 * p1 + (p2 - p0) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t ** 2
                          + (3 * p1 - p0 - 3 * p2 + p3) * t ** 3))
    out.append(p[-2][None])
    return np.vstack(out)


@functools.lru_cache(maxsize=None)
def _centre(pts, sigma, step=0.1):
    """The spline with its heading eased along the arc (gaussian, sigma LU),
    re-integrated and laid back on it (rotation and shift, least squares):
    the curvature runs smooth, the line moves under 0.2 LU."""
    p = _spline(pts, 16)
    s = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(p, axis=0).T))])
    S = np.arange(0, s[-1] + 1e-9, step)
    q = np.stack([np.interp(S, s, p[:, 0]), np.interp(S, s, p[:, 1])], -1)
    d = np.diff(q, axis=0)
    th = np.unwrap(np.arctan2(d[:, 1], d[:, 0]))
    n = int(4 * sigma / step)
    k = np.exp(-0.5 * (np.arange(-n, n + 1) * step / sigma) ** 2)
    th = np.convolve(np.concatenate([np.full(n, th[0]), th, np.full(n, th[-1])]), k / k.sum(), "valid")
    r = np.vstack([[0, 0], np.cumsum(np.stack([np.cos(th), np.sin(th)], -1) * step, 0)])
    a, b = r - r.mean(0), q - q.mean(0)
    u, _s, vt = np.linalg.svd(a.T @ b)
    return (a @ (u @ vt) + q.mean(0))[::2]


def _stroke(g, px, py):
    """Distance to the sign's centre line and the unit normal away from it."""
    pts = _centre(g["path"], g["smooth"])
    d = np.full(px.shape, np.inf)
    nx, ny = np.zeros(px.shape), np.zeros(px.shape)
    for a, b in zip(pts[:-1], pts[1:]):
        ab = b - a
        t = np.clip(((px - a[0]) * ab[0] + (py - a[1]) * ab[1]) / (ab @ ab), 0, 1)
        ex, ey = px - a[0] - t * ab[0], py - a[1] - t * ab[1]
        dd = np.hypot(ex, ey)
        k = dd < d
        d = np.where(k, dd, d)
        nx = np.where(k, ex / np.maximum(dd, 1e-9), nx)
        ny = np.where(k, ey / np.maximum(dd, 1e-9), ny)
    return d, nx, ny


def _dome(g, u, ux, uy):
    """The surface normal at u of the half-width out along (ux, uy)."""
    p, f = g["dome"]
    u = np.clip(u, 0, 0.985)
    sl = f * u ** (p - 1) * (1 - u ** p) ** (1 / p - 1)
    n = np.sqrt(1 + sl * sl)
    return np.stack([sl * ux / n, sl * uy / n, 1 / n], -1)


def _glass_tone(g, N):
    """Linear tone of the glass at normal N: lit, glinting, gathering light
    inside its far edge and mirroring the room."""
    L = np.asarray(g["light"]) / np.linalg.norm(g["light"])
    half = L + [0, 0, 1]
    half /= np.linalg.norm(half)
    k_g, e_g = g["glint"]
    tone = g["base"] * (g["amb"] + g["kd"] * np.clip(N @ L, 0, 1)) + k_g * np.clip(N @ half, 0, 1) ** e_g
    k_c, c_at, c_w = g["gather"]
    toward = (N[..., 0] * L[0] + N[..., 1] * L[1]) / np.hypot(L[0], L[1])
    tone = tone + k_c * np.exp(-((toward - c_at) / c_w) ** 2)
    nz = N[..., 2]
    phi = np.arctan2(N[..., 1], N[..., 0])     # the reflection's azimuth is the normal's
    rz = 2 * nz * nz - 1
    for az, w_az, el, w_el, k in g["room"]:
        da = np.angle(np.exp(1j * (phi - np.radians(az))))
        tone = tone + g["mirror"] * k * np.exp(-(da / w_az) ** 2 - ((rz - el) / w_el) ** 2)
    return tone


def _glyph(name, px, py, tone, alpha, pitch):
    """The sign over the glass: the rod, then the bead where the rod is not."""
    g = GLYPH[name]
    hw = g["w"] / 2
    edge = max(0.035, 0.6 * pitch) * g["soft"]
    d, nx, ny = _stroke(g, px, py)
    w_rod = np.clip((hw - d) / edge + 0.5, 0, 1)
    cx, cy, r = g["dot"]
    dd = np.hypot(px - cx, py - cy)
    w_dot = np.clip((r - dd) / edge + 0.5, 0, 1) * (1 - w_rod)
    dd = np.maximum(dd, 1e-9)
    for w, N in ((w_rod, _dome(g, d / hw, nx, ny)),
                 (w_dot, _dome(g, dd / r, (px - cx) / dd, (py - cy) / dd))):
        tone = tone + (_glass_tone(g, N)[..., None] - tone) * w[..., None]
        alpha = alpha + (1 - alpha) * w
    return np.clip(tone, 0, None), alpha


def key_frame_image(name, idx, key, size):
    """An animation's key in frame idx's outline (GLASS_PLAN.md stage 5):
    its geometry still, his tone of frame key on it, at 32 as well."""
    return Image.fromarray(_frame(name, idx, size, key), "RGBA")


def _his_sign(im, idx):
    """Help at 32 with his "?" over the glass: the stroke is a pixel or two
    wide there and his pixels are its drawing; the rod boxed to 32 read pale, its
    glint a stray light pixel on the bowl. Taken over the stroke and the dot
    grown by _SIGN32_PAD, premultiplied."""
    g = GLYPH["Help"]
    ys, xs = np.mgrid[0:V.LOGICAL, 0:V.LOGICAL] + 0.5
    d = np.full(xs.shape, np.inf)
    path = np.asarray(g["path"])
    for p, q in zip(path[:-1], path[1:]):
        v = q - p
        t = np.clip(((xs - p[0]) * v[0] + (ys - p[1]) * v[1]) / (v @ v), 0, 1)
        d = np.minimum(d, np.hypot(xs - p[0] - t * v[0], ys - p[1] - t * v[1]))
    cx, cy, r = g["dot"]
    m = np.clip(np.maximum(g["w"] / 2 + _SIGN32_PAD - d,
                           _SIGN32_PAD + r - np.hypot(xs - cx, ys - cy)) + 0.5, 0, 1)[..., None]
    his = np.asarray(H.original("Help", idx).convert("RGBA"), dtype=np.float64)
    ours = im.astype(np.float64)
    al = his[..., 3:] * m + ours[..., 3:] * (1 - m)
    pre = his[..., :3] * his[..., 3:] * m + ours[..., :3] * ours[..., 3:] * (1 - m)
    rgb = pre / np.maximum(al, 1e-6)
    return np.dstack([rgb, al]).clip(0, 255).round().astype(np.uint8)


_SIGN32_PAD = 0.7   # LU round the "?" his pixels are taken from at 32


def frame_image(name, idx, size):
    # 32 is drawn as every other size (owner, 2026-10-27: the remaster at 32
    # too). Boxed to 32 the glass lands within 13 levels of his pixels and
    # loses his 1 px light line round the outline; Help keeps his "?".
    im = _frame(name, idx, size)
    if size == V.LOGICAL and name == "Help":
        im = _his_sign(im, idx)
    return Image.fromarray(im, "RGBA")

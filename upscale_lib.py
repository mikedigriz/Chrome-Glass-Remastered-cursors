"""Shared RGBA-safe upscale helpers for tools/upscale256.py and hybrid.py.

Real-ESRGAN (and any RGB-only super-res net) has no notion of alpha: fed a
straight RGBA PNG it sees the transparent zone as solid black and "learns"
a dark scalloped halo along every silhouette edge. The fix is standard for
premultiplied-alpha upscaling: extend the visible colour into the
transparent zone (inpaint) before the network ever sees it, then discard
whatever colour the network invents in that zone since the real alpha mask
crops it away anyway.
"""
import numpy as np
import cv2


def bleed_extend(rgba):
    """RGBA float array (H,W,4), 0..255 -> RGB uint8 with colour pushed
    into the transparent zone so an RGB-only upscaler sees no edge halo."""
    rgb = np.clip(rgba[..., :3], 0, 255).astype(np.uint8)
    a = rgba[..., 3]
    transparent = (a < 8).astype(np.uint8)
    if not transparent.any():
        return rgb
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    filled = cv2.inpaint(bgr, transparent, 5, cv2.INPAINT_TELEA)
    return cv2.cvtColor(filled, cv2.COLOR_BGR2RGB)


def pick_device():
    import torch
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def load_model(device, scale=4, weights="RealESRGAN_x4plus_anime_6B.pth", num_block=6):
    """Load a Real-ESRGAN generator. Defaults to the anime_6B model: on this
    synthetic glass art it keeps flat zones clean instead of inventing the
    cross-hatch chroma noise the photographic x4plus model paints on grey glass
    (measured 4x less invented chroma on the pale cursors). The general x4plus
    and the community "sharp" models (4x-AnimeSharp, 4x-UltraSharp) were tested
    and rejected: fed the twice-upscaled smooth glass they either soften it or
    hallucinate crystalline noise on the flat zones. Crispness is added back
    deterministically in hybrid._master instead, where it is controllable and
    invents nothing. Pass weights="RealESRGAN_x4.pth", num_block=23 for the old
    photo model."""
    import os
    from py_real_esrgan.model import RealESRGAN
    from py_real_esrgan.rrdbnet_arch import RRDBNet
    root = os.path.dirname(os.path.abspath(__file__))
    model = RealESRGAN(device, scale=scale)
    model.model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64,
                          num_block=num_block, num_grow_ch=32, scale=scale)
    model.load_weights(os.path.join(root, "weights", weights), download=False)
    return model

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


def load_model(device, scale=4):
    import os
    from py_real_esrgan.model import RealESRGAN
    root = os.path.dirname(os.path.abspath(__file__))
    model = RealESRGAN(device, scale=scale)
    model.load_weights(os.path.join(root, "weights", f"RealESRGAN_x{scale}.pth"),
                        download=True)
    return model

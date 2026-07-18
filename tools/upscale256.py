"""Regenerate src/ai256: a Real-ESRGAN x4 pass over the processed 128px
hybrid frames, downsampled to 256px RGB.

Needs `pip install py-real-esrgan` (pulls torch). The results are committed,
so the normal build (and CI) never needs torch: hybrid.py picks src/ai256 up
when present and falls back to Lanczos otherwise.
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import huggingface_hub
if not hasattr(huggingface_hub, "cached_download"):        # new hub versions
    huggingface_hub.cached_download = huggingface_hub.hf_hub_download
import numpy as np
import torch
from PIL import Image
from py_real_esrgan.model import RealESRGAN

import hybrid as H


def main():
    out_dir = os.path.join(ROOT, "src", "ai256")
    os.makedirs(out_dir, exist_ok=True)
    model = RealESRGAN(torch.device("cpu"), scale=4)
    model.load_weights(os.path.join(ROOT, "weights", "RealESRGAN_x4.pth"),
                       download=True)
    for name in H.STATIC:
        key = H._key(name, 0)
        rgb, _ = H._base128(name, 0)
        im = Image.fromarray(rgb.round().astype(np.uint8), "RGB")
        big = model.predict(im)                            # 512px
        big.resize((256, 256), Image.LANCZOS).save(
            os.path.join(out_dir, key + ".png"))
        print("ai256", key)


if __name__ == "__main__":
    main()

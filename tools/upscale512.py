"""Regenerate src/ai512: the same Real-ESRGAN x4 pass as upscale256, but the
512px network output is kept native instead of being downsampled to 256.

The x4 model turns the processed 128px hybrid frame straight into 512px, so
upscale256 was throwing that resolution away on its final resize. hybrid._master
prefers src/ai512 when present (anchoring the whole set at 512): 384/512 then
carry real network detail instead of a Lanczos stretch of the 256 master, and
the smaller sizes downsample from a genuinely higher-resolution source.

Same dependencies and caveats as upscale256 (py-real-esrgan, opencv, torch;
bleed_extend fills the transparent margin so the RGB-only net grows no edge
halo). Results are committed, so the normal build never needs torch - hybrid.py
falls back to src/ai256, then Lanczos, when a level is absent. Runs on the first
CUDA device if present.
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import huggingface_hub
if not hasattr(huggingface_hub, "cached_download"):        # new hub versions
    huggingface_hub.cached_download = huggingface_hub.hf_hub_download
import numpy as np
from PIL import Image

import hybrid as H
import upscale_lib as U


def main():
    out_dir = os.path.join(ROOT, "src", "ai512")
    os.makedirs(out_dir, exist_ok=True)
    device = U.pick_device()
    print("device:", device)
    model = U.load_model(device, scale=4)

    names = list(H.STATIC) + list(H.ANIM)
    for name in names:
        n = len(H.BY_NAME[name]["frames"])
        for idx in range(n):
            key = H._key(name, idx)
            rgb, alpha = H._base128(name, idx)
            rgba = np.dstack([rgb, alpha])
            clean_rgb = U.bleed_extend(rgba)
            im = Image.fromarray(clean_rgb, "RGB")
            big = model.predict(im)                            # native 512px
            if big.size != (512, 512):
                big = big.resize((512, 512), Image.LANCZOS)
            big.save(os.path.join(out_dir, key + ".png"))
            print("ai512", key)


if __name__ == "__main__":
    main()

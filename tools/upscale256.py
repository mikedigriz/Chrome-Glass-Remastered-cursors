"""Regenerate src/ai256: a Real-ESRGAN x4 pass over the processed 128px
hybrid frames, downsampled to 256px RGB. Covers static and animated cursors:
the 256px master feeds every size (hybrid._master), and Linux ships animated
cursors up to 256px (build.py ANI_SIZES). Windows .ani stays capped at 96px
(ANI_SIZES_WIN), so its frames never carry a 256px image.

Needs `pip install py-real-esrgan opencv-python` (pulls torch). The results
are committed, so the normal build (and CI) never needs torch: hybrid.py
picks src/ai256 up when present and falls back to Lanczos otherwise.

The 128px source is fed through upscale_lib.bleed_extend() first so the
transparent margin around the silhouette is filled with the nearest visible
colour instead of black - Real-ESRGAN has no alpha channel and otherwise
"learns" a dark scalloped halo along every edge. Runs on the first CUDA
device if present.
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
    out_dir = os.path.join(ROOT, "src", "ai256")
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
            big = model.predict(im)                            # 512px
            big.resize((256, 256), Image.LANCZOS).save(
                os.path.join(out_dir, key + ".png"))
            print("ai256", key)


if __name__ == "__main__":
    main()

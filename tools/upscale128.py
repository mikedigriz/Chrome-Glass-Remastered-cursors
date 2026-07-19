"""Regenerate src/ai: a Real-ESRGAN x4 pass over the original 32px frames
(32 -> 128 directly), replacing the previously-committed 128px sources with
a version that never saw a black background.

Real-ESRGAN has no alpha channel; a plain RGBA->RGB fed to it turns the
transparent margin into "solid black" and the network invents a dark
scalloped halo along the silhouette edge. upscale_lib.bleed_extend()
inpaints the transparent margin with the nearest visible colour first so
the network never sees that edge.

Needs `pip install py-real-esrgan opencv-python` (pulls torch). Results are
committed; hybrid.py falls back to a plain Lanczos upscale if src/ai is
missing, so the normal build never needs torch.
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import huggingface_hub
if not hasattr(huggingface_hub, "cached_download"):
    huggingface_hub.cached_download = huggingface_hub.hf_hub_download
import json
import numpy as np
from PIL import Image

import upscale_lib as U

ORIG = os.path.join(ROOT, "src", "orig")
OUT = os.path.join(ROOT, "src", "ai")
MANIFEST = json.load(open(os.path.join(ROOT, "src", "manifest.json")))


def main():
    os.makedirs(OUT, exist_ok=True)
    device = U.pick_device()
    print("device:", device)
    model = U.load_model(device, scale=4)

    for m in MANIFEST:
        kind = m["kind"]
        for idx, fr in enumerate(m["frames"]):
            key = f"{kind}__{m['name']}__{idx}"
            src = os.path.join(ORIG, key + ".png")
            if not os.path.exists(src):
                continue
            rgba = np.asarray(Image.open(src).convert("RGBA"), dtype=np.float64)
            clean_rgb = U.bleed_extend(rgba)
            im = Image.fromarray(clean_rgb, "RGB")
            big = model.predict(im)                            # 128px (32*4)
            out = Image.new("RGBA", big.size, (0, 0, 0, 0))
            out.paste(big, (0, 0))
            out.putalpha(255)                                  # hybrid.py masks alpha itself
            out.save(os.path.join(OUT, key + ".png"))
            print("ai128", key)


if __name__ == "__main__":
    main()

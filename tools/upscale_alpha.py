"""Regenerate src/aialpha: a Real-ESRGAN x4 pass over the original 32px alpha
channel alone, carried to native 512px (32 -> 128 -> 512).

The silhouette edge is already vector-crisp (traced.json), but the glass
*translucency inside* that edge was a plain Lanczos of the 32px original alpha -
stretched 16x it goes soft, so the inner sheen reads as mush at large sizes.
Upscaling the alpha with the same network that sharpens the colour recovers
that inner structure. Alpha is monochrome, so - unlike the colour pass - the
network cannot invent the cross-hatch chroma noise that keeps AI off the pale
glass cursors; this is why an alpha master is safe for the whole set.

hybrid._up_alpha histogram-matches each level to the plain Lanczos, so the two
share an identical value distribution - the overall translucency (and the
build's alpha-drift metric) is unchanged, only the sharpness of the inner
gradient improves.

Same deps/caveats as upscale512 (py-real-esrgan, opencv, torch). Results are
committed; the build falls back to plain Lanczos when src/aialpha is absent.
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import huggingface_hub
if not hasattr(huggingface_hub, "cached_download"):
    huggingface_hub.cached_download = huggingface_hub.hf_hub_download
import numpy as np
from PIL import Image

import hybrid as H
import upscale_lib as U


def main():
    out_dir = os.path.join(ROOT, "src", "aialpha")
    os.makedirs(out_dir, exist_ok=True)
    device = U.pick_device()
    print("device:", device)
    model = U.load_model(device, scale=4)

    for name in list(H.STATIC) + list(H.ANIM):
        for idx in range(len(H.BY_NAME[name]["frames"])):
            key = H._key(name, idx)
            cur = H._orig(key)[..., 3]                      # 32px alpha
            while cur.shape[0] < 512:                        # 32 -> 128 -> 512
                rgb = np.clip(np.dstack([cur, cur, cur]), 0, 255).astype(np.uint8)
                cur = np.asarray(model.predict(Image.fromarray(rgb, "RGB"))
                                 .convert("L"), dtype=np.float64)
            if cur.shape[0] != 512:
                cur = np.asarray(Image.fromarray(cur.astype(np.float32), mode="F")
                                 .resize((512, 512), Image.LANCZOS), dtype=np.float64)
            Image.fromarray(np.clip(cur, 0, 255).astype(np.uint8), "L").save(
                os.path.join(out_dir, key + ".png"))
            print("aialpha", key)


if __name__ == "__main__":
    main()

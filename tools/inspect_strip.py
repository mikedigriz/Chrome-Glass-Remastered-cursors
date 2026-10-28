#!/usr/bin/env python3
"""Animated contact sheet at an inspection size.

build_animations writes assets/animations.webp at a 160px cell, which is what
the README needs: five cells and their gaps come to 884px, near enough to
GitHub's content column that nothing is resampled on the way to the screen.
That is the wrong size for looking for defects, and making the README's own
sheet bigger does not help - the page scales it back down to the column width,
so the reader downloads several times more and sees exactly the same thing.

This writes a separate sheet at whatever cell size is asked for, to be opened
on its own rather than embedded:

    python tools/inspect_strip.py               # 512px cells
    python tools/inspect_strip.py 320 out.webp

Nothing here is committed to the repository or referenced by the README.
"""

import os
import sys
import time

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cgr import hybrid as H  # noqa: E402

WEBP = dict(lossless=False, quality=90, method=6)


def build(box, path):
    names = [m["name"] for m in H.MANIFEST if m["kind"] == "ani"]
    gap = max(4, box // 11)
    per = {n: H.anim_frames(n, box)[0] for n in names}
    count = max(len(f) for f in per.values())
    width = len(names) * (box + gap) + gap
    strip = []
    for i in range(count):
        canvas = Image.new("RGBA", (width, box + 2 * gap), (0, 0, 0, 0))
        for j, name in enumerate(names):
            frames = per[name]
            canvas.alpha_composite(frames[i % len(frames)], (gap + j * (box + gap), gap))
        strip.append(canvas)
    strip[0].save(path, save_all=True, append_images=strip[1:],
                  duration=17, loop=0, **WEBP)
    return width, box + 2 * gap, len(strip)


def main():
    box = int(sys.argv[1]) if len(sys.argv) > 1 else 512
    path = sys.argv[2] if len(sys.argv) > 2 else f"animations-{box}.webp"
    t0 = time.time()
    w, h, n = build(box, path)
    print(f"{path}: {w}x{h}, {n} frames, {os.path.getsize(path) / 1e6:.2f} MB, "
          f"{time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()

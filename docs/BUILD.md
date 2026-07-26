# Building Chrome Glass Remastered

[На русском](BUILD.ru.md) · [back to the README](../README.md)

All AI masters are already committed, so a normal build needs no GPU and no torch.

```sh
pip install -r requirements.txt
python3 build.py
```

This rebuilds `dist/`, `packages/` and the previews, then checks the result against the original (alpha, saturation, timing) and warns if anything drifted.

Two escape hatches:

| Variable | Effect |
|---|---|
| `BUILD_SERIAL=1` | render single-core instead of across every core |
| `ALLOW_METRIC_WARN=1` | ship despite a drift warning |

`dist/original/Chrome Glass (2006)/` is the untouched 2006 set rebuilt as a reference to diff against. It is deliberately local only - not packaged, not released.

## Where each file fits in

| Folder / file | What's in it |
|---|---|
| `src/orig/` | untouched 2006 art, 32 px - the source of truth |
| `src/ai/` | a 128 px AI upscale, the input `trace.py` reads shapes from |
| `src/ai512/` | the AI color master, native resolution |
| `src/aialpha/` | AI upscale of transparency, kept separate from color |
| `traced.json` | vector outlines from `trace.py` |

Build order:

```
src/ -> trace.py -> traced.json -> hybrid.py + glyphs.py -> build.py -> curlib.py / vectorlib.py
```

A couple of details are hand-drawn in `cursors.py` instead of auto-traced - like the dot under the question mark on Help, which sits apart from the arrow and the tracer just misses it.

## Preview assets

`build.py` also generates everything the READMEs embed:

| Asset | What it is |
|---|---|
| `preview.png` | the 15-tile showcase grid |
| `assets/comparison.png` | 2006 stretched vs remaster at native 512 px |
| `assets/animations.webp` | all five animated cursors side by side |
| `assets/<name>.webp` | each animated cursor on its own |
| `assets/<name>.gif` | the same, for places that still refuse animated webp (forums, DeviantArt, Reddit). Nothing in the repo links these; they exist to be uploaded by hand. |

Two cursors are missing from the showcase grid on purpose. **Hand** and **Handwriting** are the same arrow silhouette as **Arrow** in the 2006 original, with only a per-frame shimmer, so a still tile just duplicates Arrow - `assets/animations.webp` shows them moving instead. **Arrow_Down** is in `WIN_UNSHIPPED`, so it is built but never packaged; showing it would advertise a cursor nobody who downloads the release gets.

`assets/social-preview.png` is the repo cover image. It comes from `tools/gen_social_preview.py`, which the build never calls, so it is committed rather than regenerated.

## Recomputing the AI upscales (optional)

Only needed if you want to recompute the upscales instead of using what's already in the repo. This is the one step that needs a GPU and torch (PyTorch):

```sh
pip install -r requirements-ai.txt

python3 tools/upscale128.py     # src/orig -> src/ai       (128 px base)
python3 tools/upscale512.py     # src/ai   -> src/ai512    (color master)
python3 tools/upscale_alpha.py  # src/orig -> src/aialpha  (alpha master)
```

You need one weights file, `RealESRGAN_x4plus_anime_6B.pth` (~18 MB, illustration-tuned) - drop it in `weights/` yourself (`upscale_lib.load_model` loads it locally, no auto-download). Results are already committed, so nobody else has to do this.

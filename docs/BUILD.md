# Building Chrome Glass Remastered

[На русском](BUILD.ru.md) · [back to the README](../README.md) · [what is in the packages](DETAILS.md)

All AI masters are already committed, so a normal build needs no GPU and no torch.

```sh
pip install -r requirements.txt
python3 -m cgr.build
```

This rebuilds `dist/`, `packages/` and the previews, then checks the result against the original (alpha, saturation, timing) and warns if anything drifted.

Optional: a CUDA GPU makes the build and `tools/analyze.py` several times faster (about 3 min against 10 on 12 cores; the gate 1.5 min). It computes the same pixels as the CPU path - masks, distances and resamples are bit-exact, the fold fits agree to 1e-6 with identical decisions (`python tools/gpu_parity.py`).

```sh
pip install -r requirements-gpu.txt
CGR_BACKEND=gpu python3 -m cgr.build
```

Without `CGR_BACKEND=gpu` nothing imports torch.

The defaults are gentle: render processes run below normal priority, six at most, so the desktop stays usable during a build. More processes do not make it faster - the GPU and the cores are shared, and ten workers measured the same as six.

| Variable | Effect |
|---|---|
| `BUILD_SERIAL=1` | render single-core instead of across every core |
| `ALLOW_METRIC_WARN=1` | ship despite a drift warning |
| `CGR_BACKEND=gpu` | run the heavy stages on the GPU (default `cpu`) |
| `CGR_GPU_WORKERS=N` | processes sharing the GPU (default: half the cores, at most 6) |
| `CGR_GPU_MEM_MB=N` | VRAM cap per process (default 1024) |
| `CGR_GPU_CHUNK_MB=N` | size of one temporary tensor (default 48) |
| `CGR_GPU_FIT_MB=N` | the same for the fold width search, which is launch-bound and wants big chunks (default 300) |
| `CGR_NICE=0` | do not lower the priority of GPU workers (Windows) |
| `CGR_WEBP_METHOD=N` | webp encoder effort for the README animations: 4 (default, seconds) or 6 (smallest files, about two minutes for the strip) |
| `CGR_KEEP_CACHE=1` | keep rendered frames between builds in `CGR_CACHE_DIR` (default: temp dir), named by a hash of `cgr/`, `art/`, `data/`, `tools/foldfit.py` and library versions. Any change means a full re-render; the build prints `hit` or `miss (changed: ...)`. Off by default |
| `CGR_CACHE_VERIFY=N` | on a cache hit, re-render N frames from scratch and stop (dropping the cache) if any differs |
| `CGR_JOB_LOG=1` | print how long each warm-up frame took |

`dist/original/Chrome Glass (2006)/` is the untouched 2006 set rebuilt as a reference to diff against. It is deliberately local only - not packaged, not released.

## Where each file fits in

| Folder / file | What's in it |
|---|---|
| `art/orig/` | untouched 2006 art, 32 px - the source of truth |
| `art/ai/` | a 128 px AI upscale, the input `trace.py` reads shapes from |
| `art/ai512/` | the AI color master, native resolution |
| `art/aialpha/` | AI upscale of transparency, kept separate from color |
| `data/traced.json` | vector outlines from `trace.py` |

Build order:

```
art/ -> trace.py -> data/traced.json -> hybrid.py + glyphs.py -> build.py -> curlib.py / vectorlib.py
```

A couple of details are hand-drawn in `cursors.py` instead of auto-traced - like the dot under the question mark on Help, which sits apart from the arrow and the tracer just misses it.

## Checking the render

`cgr/build.py`'s own gate only watches median alpha and saturation. Everything else - a silhouette whose size depends on the size it is drawn at, a fold broken into pieces, a colour that has drifted off the author's, an animation that hurries - is measured by `tools/analyze.py`, straight off `hybrid.frame_image` with no build needed:

```
python tools/analyze.py --check data/metrics-baseline.json --jobs 8
```

`data/metrics-baseline.json` is where the set stands today and it is committed. A value that misses its target but is no worse than that file prints as debt and does not fail; a value that moves further from a target fails on the spot. `--fast` is the short three-rung ladder for iterating; the default ladder already includes 512 and is what acceptance runs on, `--full` is kept for existing scripts but is currently a no-op, and `--ratchet FILE` rewrites the baseline once an improvement is real.

`tools/selftest.py` plants a defect of each kind and asserts the metric that owns it moves. Run it before trusting a clean gate: a metric that cannot fail reports a clean run on a broken cursor.

`tools/loop.py diagnose` groups whatever is failing into artifacts and names the next thing to try; `checkpoint`, `rollback` and `progress` keep `docs/dev/PROGRESS.md` and `docs/dev/DEAD_ENDS.md`.

## Preview assets

`cgr/build.py` also generates everything the READMEs embed:

| Asset | What it is |
|---|---|
| `assets/preview.png` | the 15-tile showcase grid |
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

python3 tools/upscale128.py     # art/orig -> art/ai       (128 px base)
python3 tools/upscale512.py     # art/ai   -> art/ai512    (color master)
python3 tools/upscale_alpha.py  # art/orig -> art/aialpha  (alpha master)
```

You need one weights file, `RealESRGAN_x4plus_anime_6B.pth` (~18 MB, illustration-tuned) - drop it in `weights/` yourself (`upscale_lib.load_model` loads it locally, no auto-download). Results are already committed, so nobody else has to do this.

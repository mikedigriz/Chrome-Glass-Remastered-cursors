<div align="center">

# Chrome Glass Remastered

**Remember the glass cursors from 2006? They're back - and finally don't turn to mush on 4K.**

[![Русская версия](https://img.shields.io/badge/README-на%20русском-0B67A0?style=flat-square)](README.ru.md)
[![Release](https://img.shields.io/github/v/release/mikedigriz/chrome-glass-remastered-cursors?style=flat-square&color=1E3A8A)](../../releases/latest)
[![Windows](https://img.shields.io/badge/Windows-10%20%7C%2011-2496ED?style=flat-square&logo=windows&logoColor=white)](#-windows-10--11)
[![Linux](https://img.shields.io/badge/Linux-Xcursor-FCC624?style=flat-square&logo=linux&logoColor=black)](#-linux)
[![macOS](https://img.shields.io/badge/macOS-Mousecape-000000?style=flat-square&logo=apple&logoColor=white)](#-macos)
[![License](https://img.shields.io/badge/code-MIT-green?style=flat-square)](LICENSE)

<img src="preview.png" alt="preview" width="640">

</div>

In 2006, a cursor set called "Chrome Glass" showed up on DeviantArt - glassy, alive, but drawn for 32 px, so on 4K it turns to mush. I rebuilt it for big screens without losing the charm.

![original vs remastered on HiDPI](assets/comparison.png)

| | Chrome Glass (2006) | Chrome Glass Remastered |
|---|---|---|
| Resolution | 32 px | **up to 256 px** (Windows) / **512 px** (Linux), vector edges, no bitmap mush. Animated ones cap at 96 px on Windows and 384 px on Linux |
| Animation | 9 frames (11 for NO), ~20 fps | **27 frames, 60 fps** for wait, app-starting and the link hand on Windows/macOS, ~20 fps on Linux. Handwriting and NO keep the author's own timing everywhere |
| Cursors | 15 stock Windows slots | plus its own **Pin** and **Person** (Windows only) |
| Platforms | Windows | Windows, Linux (Xcursor, deb, PKGBUILD), macOS (Mousecape) |

## Install

Everything's in the [latest release](../../releases/latest).

### 🪟 Windows 10 / 11

1. Download and unpack `ChromeGlassRemastered-windows.zip`.
2. Right-click `Install.inf` -> **Install**.
3. Settings -> Mouse -> *Additional mouse settings* -> **Pointers** tab -> pick **Chrome Glass Remastered** -> Apply.

To remove it later: right-click the same `Install.inf` -> **Uninstall**. That drops the scheme and deletes the cursors it copied.

### 🐧 Linux

| Distro | Command |
|---|---|
| Debian / Ubuntu / Mint | `sudo dpkg -i chrome-glass-remastered-cursors_*_all.deb` |
| Arch / Manjaro | `cd packaging && makepkg -si` ([PKGBUILD](packaging/PKGBUILD)) - the copy attached to the release has the checksum filled in |
| No root | `mkdir -p ~/.icons/ && tar -xzf ChromeGlassRemastered-linux.tar.gz -C ~/.icons/` |

The `.deb` also registers the theme with `update-alternatives`, so it can become the system cursor theme; `sudo dpkg -r chrome-glass-remastered-cursors` undoes that cleanly.

Then switch the theme:

```sh
gsettings set org.gnome.desktop.interface cursor-theme "Chrome Glass Remastered"  # GNOME
plasma-apply-cursortheme "Chrome Glass Remastered"                                # KDE
```

Or pick it in GNOME Tweaks / KDE System Settings. On bare X11/Wayland set `XCURSOR_THEME="Chrome Glass Remastered"`.

> **Cursor not changing?** Some archive tools extract into an extra wrapper folder. Make sure the theme folder ends up directly at `~/.icons/Chrome Glass Remastered/`, not one level deeper. After switching, GNOME on X11 needs a Shell restart (`killall -3 gnome-shell`); Wayland and KDE need a re-login.

> **Cursor flickering?** The old 60 fps animation would drift out of sync with a 60 Hz screen, causing the wait/app-starting/link cursors to flicker. Those three now run at ~20 fps on Linux, like the original, so there's nothing left to flicker. Handwriting and NO keep the author's faster cadence because they play once and stop rather than loop. Still happens after a theme update? Restart the app - cursors get cached at startup.

### 🍎 macOS

Cursor themes on macOS are applied by the free [Mousecape](https://github.com/alexzielenski/Mousecape):

1. `brew install --cask mousecape`
2. Download `ChromeGlassRemastered.cape`, double-click it.
3. Right-click the cape -> **Apply**.

The cape replaces twelve cursors: arrow, text, pointing hand, crosshair, move, wait, forbidden, help and the four resize arrows. Everything else stays default.

> **Heads up:** every macOS release locks cursor theming down further. Mousecape needs SIP partially disabled and may not work at all on Apple Silicon. If `Apply` does nothing, that's a Mousecape/macOS limitation, not a bug here. Check [Mousecape's issues](https://github.com/alexzielenski/Mousecape/issues) before filing one.

## See it move

![animated cursors](assets/animations.webp)

## How it works

Each cursor is three layers: **the original 32 px art** for authenticity, **an AI upscale to 512 px** for color and shine (computed once, committed to the repo - shrinking down looks cleaner than stretching up), and **a vector outline** for sharp edges at any scale. The upscaler is tuned for illustration, so even the pale, near-grey cursors (Help, IBeam, Cross, the resize arrows) get even color with no noise, and a separate sharpening pass crisps up the edges.

Transparency is upscaled separately from color: stretched straight from 32 px, it loses the glassy glow. There's no color in an alpha channel to get wrong, so every cursor, pale ones included, uses the upscaled version.

## Build from source

All AI masters are already in the repo, so a normal build needs no GPU and no torch.

```sh
pip install -r requirements.txt
python3 build.py
```

This rebuilds `dist/`, `packages/` and the previews, then checks the result against the original (alpha, saturation, timing) and warns if anything drifted. Two escape hatches: `BUILD_SERIAL=1` renders single-core instead of across every core, and `ALLOW_METRIC_WARN=1` ships despite a drift warning.

`dist/original/Chrome Glass (2006)/` is the untouched 2006 set rebuilt as a reference to diff against. It is deliberately local only - not packaged, not released.

### Where each file fits in

| Folder / file | What's in it |
|---|---|
| `src/orig/` | untouched 2006 art, 32 px - the source of truth |
| `src/ai/` | a 128 px AI upscale, the input `trace.py` reads shapes from |
| `src/ai512/` | the AI color master, native resolution |
| `src/aialpha/` | AI upscale of transparency, kept separate from color |
| `traced.json` | vector outlines from `trace.py` |

Build order: `src/` -> `trace.py` -> `traced.json` -> `hybrid.py` + `glyphs.py` -> `build.py` -> `curlib.py` / `vectorlib.py`.

A couple of details are hand-drawn in `cursors.py` instead of auto-traced - like the dot under the question mark on Help, which sits apart from the arrow and the tracer just misses it.

### Rebuilding the AI files yourself (optional)

Only needed if you want to recompute the upscales instead of using what's already in the repo. The one step that needs a GPU and torch (PyTorch):

```sh
pip install -r requirements-ai.txt

python3 tools/upscale128.py     # src/orig -> src/ai       (128 px base)
python3 tools/upscale512.py     # src/ai   -> src/ai512    (color master)
python3 tools/upscale_alpha.py  # src/orig -> src/aialpha  (alpha master)
```

You need one weights file, `RealESRGAN_x4plus_anime_6B.pth` (~18 MB, illustration-tuned) - drop it in `weights/` yourself (`upscale_lib.load_model` loads it locally, no auto-download). Results are already committed, so nobody else has to do this.

## License

Original artwork: ["Chrome Glass" by yoyos, DeviantArt, 2006](https://www.deviantart.com/yoyos/art/Chrome-Glass-32252748) (see [`NOTICE`](NOTICE)). Code is **MIT** ([`LICENSE`](LICENSE)).

Chrome Glass has been my favorite cursor set for years - thanks, yoyos.

---

<div align="center">

*Feeling nostalgic? Star the repo - it helps other 2006 diehards find their way back.* ⭐

</div>

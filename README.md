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

In 2006, a cursor set called "Chrome Glass" showed up on DeviantArt - glassy, alive, but drawn for 32 px, so on 4K it turns to mush. I rebuilt it for big screens without losing the charm - the original ships too, as *Chrome Glass (2006)*.

![original vs remastered on HiDPI](assets/comparison.png)

| | Chrome Glass (2006) | Chrome Glass Remastered |
|---|---|---|
| Resolution | 32 px | **up to 256 px** (Windows) / **512 px** (Linux), vector edges, no bitmap mush |
| Animation | 9 frames, ~20 fps | **27 frames, 60 fps** (Windows/macOS) / ~20 fps (Linux), original rhythm kept |
| Cursors | 15 stock Windows slots | plus its own **Pin** and **Person** |
| Platforms | Windows | Windows, Linux (Xcursor, deb, PKGBUILD), macOS (Mousecape) |

## Install

Everything's in the [latest release](../../releases/latest).

### 🪟 Windows 10 / 11

1. Download and unpack `ChromeGlassRemastered-windows.zip`.
2. Right-click `Install.inf` -> **Install**.
3. Settings -> Mouse -> *Additional mouse settings* -> **Pointers** tab -> pick **Chrome Glass Remastered** -> Apply.

### 🐧 Linux

| Distro | Command |
|---|---|
| Debian / Ubuntu / Mint | `sudo dpkg -i chrome-glass-remastered-cursors_1.0.0_all.deb` |
| Arch / Manjaro | `cd packaging && makepkg -si` ([PKGBUILD](packaging/PKGBUILD)) |
| No root | `mkdir -p ~/.local/share/icons/ && tar -xzf ChromeGlassRemastered-linux.tar.gz -C ~/.local/share/icons/` |

Then switch the theme:

```sh
gsettings set org.gnome.desktop.interface cursor-theme "Chrome Glass Remastered"  # GNOME
plasma-apply-cursortheme "Chrome Glass Remastered"                                # KDE
```

Or pick it in GNOME Tweaks / KDE System Settings. On bare X11/Wayland set `XCURSOR_THEME="Chrome Glass Remastered"`.

> **Cursor not changing?** Some archive tools extract into an extra wrapper folder. Make sure the theme folder ends up directly at `~/.icons/Chrome Glass Remastered/`, not one level deeper. After switching, GNOME on X11 needs a Shell restart (`killall -3 gnome-shell`); Wayland and KDE need a re-login.

> **Cursor flickering?** The old 60 fps animation would drift out of sync with a 60 Hz screen, causing the wait/hand cursors to flicker. Animation now runs at ~20 fps, like the original, so there's nothing left to flicker. Still happens after a theme update? Restart the app - cursors get cached at startup.

### 🍎 macOS

Cursor themes on macOS are applied by the free [Mousecape](https://github.com/alexzielenski/Mousecape):

1. `brew install --cask mousecape`
2. Download `ChromeGlassRemastered.cape`, double-click it.
3. Right-click the cape -> **Apply**.

The cape replaces the core cursors (arrow, text, crosshair, hand, move, wait); everything else stays default.

> **Heads up:** every macOS release locks cursor theming down further. Mousecape needs SIP partially disabled and may not work at all on Apple Silicon. If `Apply` does nothing, that's a Mousecape/macOS limitation, not a bug here. Check [Mousecape's issues](https://github.com/alexzielenski/Mousecape/issues) before filing one.

## See it move

![animated cursors](assets/animations.webp)

## How it works

Each cursor is three layers stacked: **the original 32 px art**, for authenticity; **an AI upscale to 512 px**, computed once and committed to the repo, supplying color and shine at every size (shrinking down looks cleaner than stretching up); and **a vector outline**, keeping edges sharp at any scale. Even the pale, near-grey cursors (Help, IBeam, Cross, the resize arrows) get AI color now - the upscaler is tuned for clean illustration and won't speckle flat grey glass with invented noise, and a separate sharpening pass adds crisp edges without inventing texture.

Transparency gets upscaled the same way but kept separate from color - stretch it straight from 32 px and the glassy glow turns to mush. There's no color in an alpha channel to get wrong, so every cursor, pale ones included, uses the upscaled version.

## Build from source

All AI masters are already in the repo, so a normal build needs no GPU and no torch.

```sh
pip install -r requirements.txt
python3 build.py
```

This rebuilds `dist/`, `packages/` and the previews, then checks the result against the original (alpha, saturation, timing) and warns if anything drifted.

### Where each file fits in

| Folder / file | What's in it |
|---|---|
| `src/orig/` | untouched 2006 art, 32 px - the source of truth |
| `src/ai/` | a 128 px AI upscale, a stepping stone to the bigger sizes |
| `src/ai512/`, `src/ai256/` | AI color masters - the build takes 512 px if present, else 256, else a plain resize |
| `src/aialpha/` | AI upscale of transparency, kept separate from color |
| `traced.json` | vector outlines from `trace.py` |

Build order: `src/` -> `trace.py` -> `traced.json` -> `hybrid.py` + `glyphs.py` -> `build.py` -> `curlib.py` / `vectorlib.py`.

A couple of details are hand-drawn in `cursors.py` instead of auto-traced - like the dot under Help's `?`, which sits apart from the arrow and the tracer just misses it.

### Rebuilding the AI files yourself (optional)

Only needed if you want to recompute the upscales instead of using what's already in the repo. The one step that needs a GPU and torch (PyTorch):

```sh
pip install -r requirements-ai.txt

python3 tools/upscale128.py     # src/orig -> src/ai       (128 px base)
python3 tools/upscale512.py     # src/ai   -> src/ai512    (main color master)
python3 tools/upscale256.py     # src/ai   -> src/ai256    (fallback color master)
python3 tools/upscale_alpha.py  # src/orig -> src/aialpha  (alpha master)
```

Run in that order: color masters build from the 128 px base, the alpha master from the original alpha. You need one weights file, `RealESRGAN_x4plus_anime_6B.pth` (~18 MB, illustration-tuned) - drop it in `weights/` yourself (`upscale_lib.load_model` loads it locally, no auto-download). Results are already committed, so nobody else has to do this.

## License

Original artwork: ["Chrome Glass" by yoyos, DeviantArt, 2006](https://www.deviantart.com/yoyos/art/Chrome-Glass-32252748) (see [`NOTICE`](NOTICE)). Code is **MIT** ([`LICENSE`](LICENSE)).

Chrome Glass has been my favorite cursor set for years - thanks, yoyos. This repo is an attempt to breathe new life into it.

---

<div align="center">

*Feeling nostalgic? Star the repo - it helps other 2006 diehards find their way back.* ⭐

</div>

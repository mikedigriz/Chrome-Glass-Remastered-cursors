<div align="center">

# Chrome Glass Remastered

**Remember the glass cursors from 2006? They're back - and now they're crisp even on a 4K display.**

[![Русская версия](https://img.shields.io/badge/README-на%20русском-0B67A0?style=flat-square)](README.ru.md)
[![Release](https://img.shields.io/github/v/release/mikedigriz/chrome-glass-remastered-cursors?style=flat-square&color=1E3A8A)](../../releases/latest)
[![Windows](https://img.shields.io/badge/Windows-10%20%7C%2011-2496ED?style=flat-square&logo=windows&logoColor=white)](#-windows-10--11)
[![Linux](https://img.shields.io/badge/Linux-Xcursor-FCC624?style=flat-square&logo=linux&logoColor=black)](#-linux)
[![macOS](https://img.shields.io/badge/macOS-Mousecape-000000?style=flat-square&logo=apple&logoColor=white)](#-macos)
[![License](https://img.shields.io/badge/code-MIT-green?style=flat-square)](LICENSE)

![preview](preview.png)

</div>

In 2006 a cursor set called "Chrome Glass" appeared on DeviantArt - translucent, shimmering, alive. On modern screens its 32-pixel art turned into blurry blobs, so I brought it back to life. **This is the exact same set, not a lookalike**: the original ships byte for byte, and everything around it is rebuilt for today's resolutions.

![original vs remastered on HiDPI](assets/comparison.png)

| | Chrome Glass (2006) | Chrome Glass Remastered |
|---|---|---|
| Resolution | 32 px | **32-256 px**, vector edges with no bitmap blur |
| Animation | 9 frames at ~20 fps | **27 frames at 60 fps**, original rhythm preserved |
| Cursor roles | 15 Windows slots | plus **Pin** and **Person** in the set's own style |
| Platforms | Windows | Windows, Linux (Xcursor, deb, PKGBUILD), macOS (Mousecape) |

## Install

Everything you need is in the [latest release](../../releases/latest).

### 🪟 Windows 10 / 11

1. Download and unpack `ChromeGlassRemastered-windows.zip`.
2. Right-click **`Install.inf`** -> **Install**.
3. Settings -> Mouse -> *Additional mouse settings* -> **Pointers** tab -> pick the **Chrome Glass Remastered** scheme -> Apply.

### 🐧 Linux

| Distro | Command |
|---|---|
| Debian / Ubuntu / Mint | `sudo dpkg -i chrome-glass-remastered-cursors_1.0.0_all.deb` |
| Arch / Manjaro | `cd packaging && makepkg -si` ([PKGBUILD](packaging/PKGBUILD)) |
| Any, no root | `tar -xzf ChromeGlassRemastered-linux.tar.gz -C ~/.local/share/icons/` |

Then switch the theme:

```sh
gsettings set org.gnome.desktop.interface cursor-theme "Chrome Glass Remastered"  # GNOME
plasma-apply-cursortheme "Chrome Glass Remastered"                                # KDE
```

Or pick it in GNOME Tweaks / KDE System Settings. On bare X11/Wayland compositors set `XCURSOR_THEME="Chrome Glass Remastered"`.

### 🍎 macOS

Cursor themes on macOS are applied by the free [Mousecape](https://github.com/alexzielenski/Mousecape):

1. `brew install --cask mousecape`
2. Download `ChromeGlassRemastered.cape` and double-click it.
3. Right-click the cape -> **Apply**.

The cape replaces the core cursors (arrow, text, crosshair, hand, move, wait); the rest stay default.

## See it move

![animated cursors](assets/animations.webp)

| Busy (watch) | App starting (progress) |
|:---:|:---:|
| ![](assets/Wait.webp) | ![](assets/AppStarting.webp) |

## How it works

Every cursor is a hybrid of three sources: the original 32 px frames (`src/orig/`) provide the authentic glass translucency, the 128 px AI upscale (`src/ai/`) keeps the inner sheen (a Reinhard colour transfer restores the washed-out saturation), and vector-traced silhouettes (`traced.json`) give a crisp edge at every size. The 256 px layer gets an extra Real-ESRGAN pass (`src/ai256/`); the results are committed, so the build doesn't need torch.

## Build from source

```sh
pip install pillow numpy
python3 build.py
```

The script rebuilds `dist/`, `packages/` and the previews, then checks the result against the original frames (alpha, saturation, timing) and warns if anything drifts. Pipeline map: `src/` -> `trace.py` -> `traced.json` -> `hybrid.py` + `glyphs.py` -> `build.py` -> `curlib.py` / `vectorlib.py`.

## License

Original artwork: ["Chrome Glass" by yoyos, DeviantArt, 2006](https://www.deviantart.com/yoyos/art/Chrome-Glass-32252748) (see [`NOTICE`](NOTICE)). Code is **MIT** ([`LICENSE`](LICENSE)).

Chrome Glass has been my favourite cursor set for many years - thank you, yoyos. This repository is a natural continuation of that work and an attempt to breathe new life into it.

---

<div align="center">

*Took you back? Star the repo - it helps others find their way back to 2006 too.* ⭐

</div>

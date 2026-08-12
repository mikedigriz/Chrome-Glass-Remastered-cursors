<div align="center">

# Chrome Glass Remastered

**Remember the glass cursors from 2006? They're back - and finally don't turn to mush on 4K.**

[![Русская версия](https://img.shields.io/badge/README-на%20русском-0B67A0?style=flat-square)](README.ru.md)
[![Release](https://img.shields.io/github/v/release/mikedigriz/chrome-glass-remastered-cursors?style=flat-square&color=1E3A8A)](../../releases/latest)
[![License](https://img.shields.io/badge/code-MIT-green?style=flat-square)](LICENSE)

[![Download the latest release](https://img.shields.io/badge/%E2%AC%87%20Download%20the%20latest%20release-1E3A8A?style=for-the-badge)](../../releases/latest)

Windows · Linux · macOS · 17 cursors · free

<img src="preview.png" alt="The set as still images: Arrow, Help, IBeam, Cross, SizeAll, the four resize arrows, UpArrow, Pin, Person, NO, Wait and AppStarting">

</div>

In 2006 a cursor set called "Chrome Glass" showed up on DeviantArt - glassy, alive, but drawn for 32 px, so on 4K it turns to mush. I rebuilt it for big screens without losing the charm.

## The difference

The same two cursors as a 4K screen shows them: on the left the 2006 original at 32 px, stretched by the OS. On the right the remaster, drawn natively at 512.

![The 2006 original stretched to 512 px next to the remaster rendered natively at 512 px, for the Arrow and Wait cursors](assets/comparison.png)

| | Chrome Glass (2006) | Chrome Glass Remastered |
|---|---|---|
| Resolution | 32 px | **256 px** on Windows, **512 px** on Linux [^1] |
| Edges | bitmap, mush when scaled | vector, sharp at any size |
| Animation | 9 frames, ~20 fps | **27 frames, 60 fps** [^2] |
| Cursors | 15 slots | **17** - adds Windows 10/11's Pin and Person, which didn't exist in 2006 |
| Platforms | Windows | Windows, Linux, macOS |

[^1]: Animated cursors cap lower: 96 px on Windows, 384 px on Linux. Windows refuses animated frames larger than that, and a 512 px animation would be ~1 MB per frame.
[^2]: On Windows and macOS, for wait, app-starting and the link hand. Linux runs those at ~20 fps like the original, which is what stops them flickering. Handwriting and NO keep the author's own timing everywhere.

## Install

Everything is in the [latest release](../../releases/latest). Pick your system:

<details open>
<summary><b>🪟 &nbsp;Windows 10 / 11</b></summary>

1. Download and unpack `ChromeGlassRemastered-windows.zip`.
2. Right-click `Install.inf` -> **Install**.
3. Settings -> Mouse -> *Additional mouse settings* -> **Pointers** tab -> pick **Chrome Glass Remastered** -> Apply.
4. **Turn the pointer size up.** Settings -> Accessibility -> Mouse pointer. Windows ships at the smallest of 15 sizes, which is the one place this set looks the same as any other. Everything above is what it was rebuilt for.

**Uninstall.** There is no *Uninstall* item in the right-click menu - Windows registers exactly one verb for `.inf`, and it is *Install*. So it takes two steps:

1. Switch the **Pointers** tab back to *Windows Default (system scheme)*. Do this first: step 2 deletes the cursor files, and if the scheme is still applied you are left pointing at files that no longer exist.
2. Run the `[DefaultUninstall]` section the installer already carries, with the full path to `Install.inf`:

```
rundll32.exe setupapi,InstallHinfSection DefaultUninstall 132 "C:\path\to\Install.inf"
```

That drops the scheme from the registry and deletes the cursors it copied into `%WINDIR%\Chrome Glass Remastered`. The folder itself is left behind empty; delete it by hand if you mind.

</details>

<details>
<summary><b>🐧 &nbsp;Linux (Xcursor)</b></summary>

| Distro | Install | Uninstall |
|---|---|---|
| Debian / Ubuntu / Mint | `sudo dpkg -i chrome-glass-remastered-cursors_*_all.deb` | `sudo dpkg -r chrome-glass-remastered-cursors` |
| Arch / Manjaro | `cd packaging && makepkg -si` | `sudo pacman -R chrome-glass-remastered-cursors` |
| No root | `mkdir -p ~/.icons/ && tar -xzf ChromeGlassRemastered-linux.tar.gz -C ~/.icons/` | `rm -rf ~/.icons/"Chrome Glass Remastered"` |

The `.deb` also registers the theme with `update-alternatives`, so it can become the system cursor theme; removing the package undoes that cleanly. The [PKGBUILD](packaging/PKGBUILD) attached to the release has its checksum filled in.

Then switch the theme:

```sh
gsettings set org.gnome.desktop.interface cursor-theme "Chrome Glass Remastered"  # GNOME
plasma-apply-cursortheme "Chrome Glass Remastered"                                # KDE
```

Or pick it in GNOME Tweaks / KDE System Settings. On bare X11/Wayland set `XCURSOR_THEME="Chrome Glass Remastered"`.

**Cursor not changing?** Some archive tools extract into an extra wrapper folder. Make sure the theme lands directly at `~/.icons/Chrome Glass Remastered/`, not one level deeper. After switching, GNOME on X11 needs a Shell restart (`killall -3 gnome-shell`); Wayland and KDE need a re-login.

**Cursor flickering?** The old 60 fps animation drifted out of sync with a 60 Hz screen. Wait, app-starting and the link hand now run at ~20 fps on Linux, like the original, so there is nothing left to flicker. Still happens after a theme update? Restart the app - cursors get cached at startup.

</details>

<details>
<summary><b>🍎 &nbsp;macOS (Mousecape)</b></summary>

Cursor themes on macOS are applied by the free [Mousecape](https://github.com/alexzielenski/Mousecape):

1. `brew install --cask mousecape`
2. Download `ChromeGlassRemastered.cape`, double-click it.
3. Right-click the cape -> **Apply**.

The cape replaces twelve cursors: arrow, text, pointing hand, crosshair, move, wait, forbidden, help and the four resize arrows. Everything else stays default.

**Uninstall:** right-click the cape in Mousecape -> **Restore**, then delete it from the library.

**Heads up:** every macOS release locks cursor theming down further. Mousecape needs SIP partially disabled and may not work at all on Apple Silicon. If `Apply` does nothing, that's a Mousecape/macOS limitation, not a bug here. Check [Mousecape's issues](https://github.com/alexzielenski/Mousecape/issues) before filing one.

</details>

Every release also ships `SHA256SUMS`, if you'd rather check what you downloaded before running an installer: `sha256sum -c SHA256SUMS`.

## See it move

Five of the cursors are animated. Left to right: **AppStarting**, **Hand** (link hover), **Handwriting**, **NO**, **Wait**.

![The five animated cursors playing side by side](assets/animations.webp)

## How it works

Each cursor is three layers: **the original 32 px art** for authenticity, **an AI upscale to 512 px** for color and shine (computed once, committed to the repo - shrinking down looks cleaner than stretching up), and **a vector outline** for sharp edges at any scale. The upscaler is tuned for illustration, so even the pale, near-grey cursors (Help, IBeam, Cross, the resize arrows) get even color with no noise, and a separate sharpening pass crisps up the edges.

Transparency is upscaled separately from color: stretched straight from 32 px, it loses the glassy glow. There's no color in an alpha channel to get wrong, so every cursor, pale ones included, uses the upscaled version.

## Build it yourself

All AI masters are already in the repo, so a normal build needs no GPU and no torch:

```sh
pip install -r requirements.txt
python3 build.py
```

That rebuilds `dist/`, `packages/` and the previews, then diffs the result against the original and warns if anything drifted. Full details - repo layout, build order, recomputing the AI upscales - are in **[docs/BUILD.md](docs/BUILD.md)**.

## License

Original artwork: ["Chrome Glass" by yoyos, DeviantArt, 2006](https://www.deviantart.com/yoyos/art/Chrome-Glass-32252748) (see [`NOTICE`](NOTICE)). Code is **MIT** ([`LICENSE`](LICENSE)).

Chrome Glass has been my favorite cursor set for years - thanks, yoyos.

Something broken? Open an issue with your OS, the release version and your pointer size - those three answer most of it.

---

<div align="center">

*Feeling nostalgic? Star the repo - it helps other 2006 diehards find their way back.* ⭐

</div>

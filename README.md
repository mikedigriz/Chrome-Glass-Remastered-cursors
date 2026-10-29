<div align="center">

# Chrome Glass Remastered

**The 2006 Chrome Glass cursors, redrawn for today's screens.**

[![Русская версия](https://img.shields.io/badge/README-на%20русском-0B67A0?style=flat-square)](README.ru.md)
[![Release](https://img.shields.io/github/v/release/mikedigriz/chrome-glass-remastered-cursors?style=flat-square&color=1E3A8A)](https://github.com/mikedigriz/Chrome-Glass-Remastered-cursors/releases/latest)
[![License](https://img.shields.io/badge/code-MIT-green?style=flat-square)](LICENSE)

[![Download the latest release](https://img.shields.io/badge/%E2%AC%87%20Download%20the%20latest%20release-1E3A8A?style=for-the-badge)](https://github.com/mikedigriz/Chrome-Glass-Remastered-cursors/releases/latest)

**Windows 10/11 · Linux · macOS 14+**

<img src="assets/hero.png" alt="Arrow from the 2006 set at its own 32 px enlarged beside the remaster drawn at 512 px, and a row of the cursors on a light and a dark wallpaper">

</div>

In 2006 yoyos posted the [Chrome Glass](https://www.deviantart.com/yoyos/art/Chrome-Glass-32252748) cursor set on DeviantArt. Screens were small then, and cursors were drawn as 32 by 32 pixel pictures. Today's screens are bigger, the cursor on them is bigger too, and the system simply stretches the old picture. It comes out blurry.

Here every cursor is drawn again for every size, from 32 to 512 pixels, so it stays sharp on any screen and at any pointer size. The shapes, colours and animation are the original's. How it was done: [docs/DETAILS.md](docs/DETAILS.md#how-it-is-built).

## Installation

| Your system | File | How it goes on |
|---|---|---|
| Windows 10/11 | [`ChromeGlassRemastered-windows.zip`](https://github.com/mikedigriz/Chrome-Glass-Remastered-cursors/releases/latest/download/ChromeGlassRemastered-windows.zip) | right-click `Install.inf`, choose **Install** |
| Linux | `.deb`, or [`ChromeGlassRemastered-linux.tar.xz`](https://github.com/mikedigriz/Chrome-Glass-Remastered-cursors/releases/latest/download/ChromeGlassRemastered-linux.tar.xz) | install the package, or unpack into `~/.icons` |
| macOS 14+ | [`ChromeGlassRemastered.cape`](https://github.com/mikedigriz/Chrome-Glass-Remastered-cursors/releases/latest/download/ChromeGlassRemastered.cape) | open it with [Mousecape](https://github.com/sdmj76/Mousecape-swiftUI) |

<details open>
<summary><b>🪟 &nbsp;Windows 10 / 11</b></summary>

1. Unpack `ChromeGlassRemastered-windows.zip`.
2. Right-click `Install.inf` and choose **Install**. On Windows 11, open **Show more options** first if the command is hidden.
3. Go to **Settings → Bluetooth & devices → Mouse → Additional mouse settings → Pointers**, pick **Chrome Glass Remastered** under *Scheme*, click **Apply**.
4. Worth doing: **Settings → Accessibility → Mouse pointer and touch**, and drag the pointer size up. A bigger pointer shows the detail best.

To update: install the new `Install.inf` over the old one as in step 2, then pick the scheme again on the **Pointers** tab and click **Apply**.

To remove it: same **Pointers** tab, select the scheme, click **Delete**, then switch back to **Windows Default** and click **Apply**. The files stay in `%WINDIR%` until you delete them - see [full removal](docs/DETAILS.md#windows).

</details>

<details>
<summary><b>🐧 &nbsp;Linux</b></summary>

| Distro | Install |
|---|---|
| Debian / Ubuntu / Mint | `sudo apt install ./chrome-glass-remastered-cursors_*_all.deb` |
| Arch / Manjaro | download the release `PKGBUILD`, run `makepkg -si` in its directory |
| Any, no root | `mkdir -p "$HOME/.icons" && tar -xf ChromeGlassRemastered-linux.tar.xz -C "$HOME/.icons"` |

Then pick **Chrome Glass Remastered** in GNOME Tweaks, or **System Settings → Colors & Themes → Cursors** on KDE Plasma 6 (**Appearance → Cursors** on Plasma 5). From a terminal:

```sh
gsettings set org.gnome.desktop.interface cursor-theme "Chrome Glass Remastered"  # GNOME
plasma-apply-cursortheme "Chrome Glass Remastered"                                # KDE Plasma
```

To make the pointer bigger: `gsettings set org.gnome.desktop.interface cursor-size 48` on GNOME; on KDE Plasma, the size list on the same **Cursors** page.

On Hyprland the theme also works as a hyprcursor theme, which fits any size by itself. Add to `hyprland.conf`:

```ini
env = HYPRCURSOR_THEME,Chrome Glass Remastered
env = HYPRCURSOR_SIZE,48
```

To remove it: `sudo apt remove chrome-glass-remastered-cursors`, `sudo pacman -R chrome-glass-remastered-cursors`, or `rm -rf ~/.icons/"Chrome Glass Remastered"` for the manual install.

</details>

<details>
<summary><b>🍎 &nbsp;macOS 14+</b></summary>

1. Install [Mousecape SwiftUI](https://github.com/sdmj76/Mousecape-swiftUI/releases). It needs macOS Sonoma 14 or later and runs on Intel and Apple Silicon.
2. Download `ChromeGlassRemastered.cape` from the latest release.
3. Double-click the cape, or import it in Mousecape, then select it and apply.

Not yet tried on a real Mac. 36 system cursors get replaced: Arrow, IBeam, Move, Wait, Busy, Crosshair and Cell, the pointing, open and closed hands, Forbidden, Help, every resize direction, and Copy, Alias, Link and the context menu with the blue arrow. The rest stay stock.

To put the system cursors back: **File → Reset System Cursor**, or <kbd>⌘</kbd>+<kbd>R</kbd>.

</details>

## The whole set

<div align="center">

<img src="assets/preview.png" alt="Chrome Glass Remastered cursor showcase: Arrow, Help, IBeam, Cross, SizeAll, resize cursors, UpArrow, Pin, Person, NO, Wait and AppStarting">

</div>

The names are the files'. IBeam selects text, Cross is precision select, SizeAll moves, UpArrow is the alternate select, AppStarting means working in the background, Wait is busy, NO is unavailable, Pin and Person pick a place and a person.

## Animation in motion

Five pointers are animated, left to right: **AppStarting**, **Hand** on a link, **Handwriting** for the pen, **NO** and **Wait**.

![AppStarting, Hand, Handwriting, NO and Wait animated side by side](assets/animations.webp)

## Not working?

- **The theme is missing from the list, or the old pointer is still there.** Log out and back in. Applications cache the cursor at startup, so restart the ones that still look wrong.
- **A pixelated icon when you middle-click to scroll, drag or zoom in a browser.** Those are the browser's own cursors, built into Chrome, Edge and other browsers. Windows has no scheme slot for them, and no cursor theme can replace them there.
- **macOS changed the pointer only in some places.** Some applications draw their own cursors, and Mousecape cannot safely replace those.

## The original

Chrome Glass is [yoyos' work](https://www.deviantart.com/yoyos/art/Chrome-Glass-32252748). This is an unofficial remaster, published as a tribute, keeping the attribution with the artwork.

The cursor artwork is **not** covered by the MIT license - see [`NOTICE`](NOTICE). The build and packaging code is MIT, see [`LICENSE`](LICENSE).

## More

- **[docs/DETAILS.md](docs/DETAILS.md)** - what is inside each package, what each platform can and cannot do, full removal, checksums, the longer troubleshooting list.
- **[docs/BUILD.md](docs/BUILD.md)** - build it yourself. Python, Pillow, NumPy; a GPU is optional and only speeds the build up.

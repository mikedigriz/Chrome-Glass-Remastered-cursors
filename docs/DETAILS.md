# What is in the packages

[На русском](DETAILS.ru.md) · [back to the README](../README.md) · [building it yourself](BUILD.md)

Everything the README leaves out: what each platform actually gets, why the numbers are what they are, how to take the theme off completely, and what does not work.

Checked on Windows 11 Pro 25H2 (build 26200) and Debian 13 (trixie) with GNOME on X11, hybrid Intel+NVIDIA. The macOS cape is built and validated on every release, but has never been applied on real hardware. CI builds on ubuntu-latest with Python 3.12.

## What does not work

Read this before filing anything.

- **macOS is untested and partial.** 36 cursor identifiers are mapped, the rest stay at the system default. Wait and Busy animate. Applications that draw their own cursors override Mousecape entirely.
- **Windows animation stops at 128 px.** Windows refuses a `.ani` whose frame holds more than about 70 KB of images, and a 256 px image alone is past that. So with the largest pointers the five animated cursors are softer than the static ones, which go to 256.
- **`Install.inf` has no Uninstall item.** Windows 10/11 register exactly one verb for `.inf`, Install. Removal is the manual route below.
- **The blue `Arrow_Down` ships on Linux only.** No Windows scheme slot points at it, so packaging it there would cost every user 407 KB in `%SystemRoot%` for a cursor they cannot select. On Linux it is the context menu and a drag that copies or links.

## Windows

17 scheme slots, in registry order, including the Windows 10/11 **Pin** and **Person** slots that the 2006 set never had. Both are new drawings in the original's style.

| | Sizes | Frames |
|---|---|---|
| Static `.cur` | 32, 40, 48, 56, 64, 96, 128, 256 | - |
| Animated `.ani` | 128, 96, 64, 56, 48, 40, 32 | The author's frames and timing: AppStarting, Hand, Wait 9 each, Handwriting 9, NO 11. |

256 px is the ceiling of the `.cur` format itself: width and height in an `ICONDIRENTRY` are one byte each, with 256 encoded as 0. There is nothing above that to ship.

The installed scheme is about 2.7 MB in `%WINDIR%\Chrome Glass Remastered`. `Install.inf` writes the scheme to HKCU only - the Pointers tab merges the user and machine hives, so writing both would list the scheme twice for everyone, to fix the rare case of an admin installing for somebody else.

### Full removal

Do the first step before anything else, or Windows keeps pointing at files you are about to delete.

1. **Additional mouse settings → Pointers**: select **Chrome Glass Remastered**, click **Delete**, then switch to **Windows Default** and click **OK**. This clears the registry entry.
2. Then either delete `%WINDIR%\Chrome Glass Remastered` by hand with administrator rights, or run the uninstall section of the .inf directly:

```
rundll32.exe setupapi,InstallHinfSection DefaultUninstall 132 "<full path>\Install.inf"
```

## Linux

16 cursor roles, 114 names in `cursors/`. The extra names are aliases: readable ones like `left_ptr`, `pointer`, `nwse-resize`, and the legacy MD5 hex names such as `9d800788f1b08800ae810202380a0822`.

The hex names are not decoration. Firefox, Chromium/Electron, Java and older GTK2 request cursors by those and by nothing else. Without them the pointer silently drops to the fallback theme in the middle of a drag or on link hover, which is the most visible way an Xcursor theme can look unfinished. Each hex is placed by the canonical name Bibata links it to, not from memory - a hex under the wrong role is worse than no hex at all, because the fallback theme would at least have drawn the right shape.

| | Sizes |
|---|---|
| Static | 32, 40, 48, 56, 64, 96, 128, 256, 384, 512 |
| Animated | 32, 40, 48, 56, 64, 96, 128, 256, 384 |

512 stays static-only: nine frames at native 512 is roughly 1 MB of raw ARGB per frame, for the rarest case there is.

**The animations run at the author's ~20 fps on purpose.** Xcursor swaps frames with no compositor-side frame sync, so a 60 fps cadence periodically lands out of phase with a 60 Hz panel and flickers - reproduced on GNOME/Mutter under X11 on a hybrid Intel+NVIDIA machine. The author's native cadence does not do it. Windows `.ani` runs at the same cadence: at 60 fps the Pointers tab preview jerked and dragged.

The unpacked theme is about 76 MB, 9 MB of it hyprcursor. Inside the tarball and the .deb the aliases are symlinks rather than copies, which saves roughly 85% of the payload.

The .deb registers its `cursor.theme`, which inherits this theme, as `x-cursor-theme` in `update-alternatives` at priority 20, under Adwaita's 90: the theme becomes a choice in `sudo update-alternatives --config x-cursor-theme` rather than taking over, and removal unregisters it. Up to 1.1.0 it registered `index.theme`, whose `Inherits=Adwaita` made that pick resolve to Adwaita; an upgrade moves such a pick over. The `PKGBUILD` committed here carries the previous tag and `sha256sums=SKIP` so a plain clone still builds; the copy attached to each release is pinned to that release and carries the real checksum.

For a single session or a single application, set `XCURSOR_THEME="Chrome Glass Remastered"` before it starts.

**Hyprcursor.** The same theme folder holds `manifest.hl` and `hyprcursors/`: the same 16 roles, sizes and frames, as PNG. Hyprland reads them instead of `cursors/` and scales between our sizes by itself. For the centred cursors (Cross, IBeam) the hotspot is a fraction of the canvas, one for every size, so it sits a pixel right and down of the Xcursor one. The hex names stay out of hyprcursor: only X11 clients ask for them.

### Full removal

```sh
sudo apt remove chrome-glass-remastered-cursors        # .deb
sudo pacman -R chrome-glass-remastered-cursors         # Arch
rm -rf ~/.icons/"Chrome Glass Remastered"  # manual install
```

## macOS

macOS has no cursor themes; Mousecape applies "capes". Only identifiers with a confident mapping are included, and Mousecape leaves everything else at the system default.

36 are mapped: Arrow, IBeam, Move, Wait, Busy (AppStarting), Crosshair and Cell, the pointing, open and closed hands (Hand), Forbidden, Help, every resize and window-resize direction (a one-way one gets the two-way arrow of its axis, as on Linux), and Copy, Alias, Link, Copy Drag and the context menu (the blue Arrow_Down). ArrowCtx is left out: Mousecape takes it for an Arrow synonym and would turn every arrow blue. Each ships at scale 1, 2, 5 and 10, that is 32, 64, 160 and 320 px.

Wait and Busy animate, at the author's 9 frames: Mousecape refuses a cursor of more than 24. A cape carries a single `FrameDuration` per cursor, so it cannot express the author's "play once, then hold" timing - Hand therefore ships as its settled last frame rather than the start of the draw-on.

To restore the system cursors: **File → Reset System Cursor**, or <kbd>⌘</kbd>+<kbd>R</kbd>. To have the cape survive a reboot, enable **Settings → General → Launch at Login** in Mousecape.

## Troubleshooting

**The theme is not in the list, or the pointer did not change.** Log out and back in. Applications cache the cursor at startup, so restart anything that still shows the old one.

**Unpacked on Linux and nothing appeared.** The archive has to land as `~/.icons/Chrome Glass Remastered/cursors/`, with no extra wrapper directory in between. Check with `ls ~/.icons/"Chrome Glass Remastered"/cursors | head`.

**The pointer reverts to another theme mid-drag, or on a link in Firefox.** Those requests go by the legacy hex names. All 114 names ship in the release archives, so check you are running this theme and not a partial copy of it.

**Animations flicker on X11.** They should not at ~20 fps. If they do, name the compositor and the GPU in an issue - the 60 fps case is the one that was reproducible, and it was fixed by dropping to the author's cadence.

**Mousecape changed the pointer only in some places.** Open **System Settings → Accessibility → Display → Pointer**, reset the pointer colours to their defaults, then apply the cape again. Applications with their own cursors keep drawing their own.

**Windows: the animated cursors look softer than the arrow.** Expected above 128 px - see the ceiling above.

## Verify what you downloaded

Every release ships `SHA256SUMS`. On Linux, put it next to the downloaded files:

```sh
sha256sum --ignore-missing -c SHA256SUMS
```

On Windows, run `Get-FileHash <file> -Algorithm SHA256` in PowerShell and compare the result against the same file.

## How it is built

The 2006 frames stay the reference for shape, colour and timing. Since 2.0.0 every pointer is drawn from geometry rather than enlarged:

1. the author's silhouette is traced into vectors (off a 128 px upscale of his frames, used for the outline only), and each pointer is built as a glass surface on it: a rim with its light shoulder and dark edge, facets meeting at the fold, the inner point mitred;
2. the tone is the author's own, read off his 32 px frame along the outline and per facet, so at 32 px the arrows land within a few levels of his pixels;
3. every size is shaded fresh at 4x4 samples per pixel in linear light, with no blur or upscaling stage in between. 32 px is drawn the same way; only Help's "?" keeps the author's pixels there, where its stroke is a pixel or two wide.

Animations work the same way: Wait and AppStarting keep one outline while the light runs over it from the author's nine keys, and the body shimmers as his does; Handwriting shrinks the arrow and grows a glass pen out of its point.

No pixel of the shipped cursors comes from a neural network. The AI colour masters that 1.x was built from were removed from the repository with the old pipeline.

Build instructions, the quality gate and how to recompute the masters: **[BUILD.md](BUILD.md)**.

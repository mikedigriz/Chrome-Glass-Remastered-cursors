# What is in the packages

[На русском](DETAILS.ru.md) · [back to the README](../README.md) · [building it yourself](BUILD.md)

Everything the README leaves out: what each platform actually gets, why the numbers are what they are, how to take the theme off completely, and what does not work.

Checked on Windows 11 Pro 25H2 (build 26200) and Debian 13 (trixie) with GNOME on X11, hybrid Intel+NVIDIA. The macOS cape is built and validated on every release, but has never been applied on real hardware. CI builds on ubuntu-latest with Python 3.12.

## What does not work

Read this before filing anything.

- **macOS is untested and partial.** Twelve cursor identifiers are mapped, the rest stay at the system default. Only Wait animates. Applications that draw their own cursors override Mousecape entirely.
- **Windows animation stops at 96 px.** Frames inside a `.ani` cannot hold a 128 px image - Windows refuses the file. So with a large pointer the five animated cursors are visibly softer than the static ones, which go to 256.
- **`Install.inf` has no Uninstall item.** Windows 10/11 register exactly one verb for `.inf`, Install. Removal is the manual route below.
- **`Arrow_Down` is built but never shipped.** No Windows scheme slot points at it, so packaging it would cost every user 407 KB in `%SystemRoot%` for a cursor they cannot select.

## Windows

17 scheme slots, in registry order, including the Windows 10/11 **Pin** and **Person** slots that the 2006 set never had. Both are new drawings in the original's style.

| | Sizes | Frames |
|---|---|---|
| Static `.cur` | 32, 48, 64, 96, 128, 256 | - |
| Animated `.ani` | 96, 64, 48, 32 | AppStarting, Hand, Wait: 27 frames at 60 fps. Handwriting: 9. NO: 11. Both keep the author's own per-frame timing. |

256 px is the ceiling of the `.cur` format itself: width and height in an `ICONDIRENTRY` are one byte each, with 256 encoded as 0. There is nothing above that to ship.

The installed scheme is about 11.3 MB in `%WINDIR%\Chrome Glass Remastered`. `Install.inf` writes the scheme to HKCU only - the Pointers tab merges the user and machine hives, so writing both would list the scheme twice for everyone, to fix the rare case of an admin installing for somebody else.

### Full removal

Do the first step before anything else, or Windows keeps pointing at files you are about to delete.

1. **Additional mouse settings → Pointers**: select **Chrome Glass Remastered**, click **Delete**, then switch to **Windows Default** and click **OK**. This clears the registry entry.
2. Then either delete `%WINDIR%\Chrome Glass Remastered` by hand with administrator rights, or run the uninstall section of the .inf directly:

```
rundll32.exe setupapi,InstallHinfSection DefaultUninstall 132 "<full path>\Install.inf"
```

## Linux

15 cursor roles, 114 names in `cursors/`. The extra names are aliases: readable ones like `left_ptr`, `pointer`, `nwse-resize`, and the legacy MD5 hex names such as `9d800788f1b08800ae810202380a0822`.

The hex names are not decoration. Firefox, Chromium/Electron, Java and older GTK2 request cursors by those and by nothing else. Without them the pointer silently drops to the fallback theme in the middle of a drag or on link hover, which is the most visible way an Xcursor theme can look unfinished. Each hex is placed by the canonical name Bibata links it to, not from memory - a hex under the wrong role is worse than no hex at all, because the fallback theme would at least have drawn the right shape.

| | Sizes |
|---|---|
| Static | 32, 48, 64, 96, 128, 256, 384, 512 |
| Animated | 32, 48, 64, 96, 128, 256, 384 |

512 stays static-only: nine frames at native 512 is roughly 1 MB of raw ARGB per frame, for the rarest case there is.

**The animations run at the author's ~20 fps on purpose.** Xcursor swaps frames with no compositor-side frame sync, so a 60 fps cadence periodically lands out of phase with a 60 Hz panel and flickers - reproduced on GNOME/Mutter under X11 on a hybrid Intel+NVIDIA machine. The author's native cadence does not do it. Windows `.ani` keeps the interpolated 60 fps; no flicker reports from there.

The unpacked theme is about 64 MB. Inside the tarball and the .deb the aliases are symlinks rather than copies, which saves roughly 85% of the payload.

The .deb registers the theme with `update-alternatives` at priority 20 - deliberately below a deliberate pick by the user - and unregisters it on removal. The `PKGBUILD` committed here carries the previous tag and `sha256sums=SKIP` so a plain clone still builds; the copy attached to each release is pinned to that release and carries the real checksum.

For a single session or a single application, set `XCURSOR_THEME="Chrome Glass Remastered"` before it starts.

### Full removal

```sh
sudo apt remove chrome-glass-remastered-cursors        # .deb
sudo pacman -R chrome-glass-remastered-cursors         # Arch
rm -rf ~/.local/share/icons/"Chrome Glass Remastered"  # manual install
```

## macOS

macOS has no cursor themes; Mousecape applies "capes". Only identifiers with a confident mapping are included, and Mousecape leaves everything else at the system default.

Twelve are mapped: Arrow, IBeam, Move, Wait, Crosshair, Pointing Hand, Forbidden, Help and the four resize directions. Each ships at scale 1, 2 and 5, that is 32, 64 and 160 px.

Only Wait animates. A cape carries a single `FrameDuration` per cursor, so it cannot express the author's "play once, then hold" timing - Hand therefore ships as its settled last frame rather than the start of the draw-on.

To restore the system cursors: **File → Reset System Cursor**, or <kbd>⌘</kbd>+<kbd>R</kbd>. To have the cape survive a reboot, enable **Settings → General → Launch at Login** in Mousecape.

## Troubleshooting

**The theme is not in the list, or the pointer did not change.** Log out and back in. Applications cache the cursor at startup, so restart anything that still shows the old one.

**Unpacked on Linux and nothing appeared.** The archive has to land as `~/.local/share/icons/Chrome Glass Remastered/cursors/`, with no extra wrapper directory in between. Check with `ls ~/.local/share/icons/"Chrome Glass Remastered"/cursors | head`.

**The pointer reverts to another theme mid-drag, or on a link in Firefox.** Those requests go by the legacy hex names. All 114 names ship in the release archives, so check you are running this theme and not a partial copy of it.

**Animations flicker on X11.** They should not at ~20 fps. If they do, name the compositor and the GPU in an issue - the 60 fps case is the one that was reproducible, and it was fixed by dropping to the author's cadence.

**Mousecape changed the pointer only in some places.** Open **System Settings → Accessibility → Display → Pointer**, reset the pointer colours to their defaults, then apply the cape again. Applications with their own cursors keep drawing their own.

**Windows: the animated cursors look softer than the arrow.** Expected - see the 96 px ceiling above.

## Verify what you downloaded

Every release ships `SHA256SUMS`. On Linux, put it next to the downloaded files:

```sh
sha256sum --ignore-missing -c SHA256SUMS
```

On Windows, run `Get-FileHash <file> -Algorithm SHA256` in PowerShell and compare the result against the same file.

## How it is built

The 2006 frames stay the reference for shape, colour and timing. Three inputs meet at build time:

1. an illustration-tuned AI colour master, native up to 512 px;
2. a separately upscaled alpha master, so the glass keeps its transparency;
3. a vector-traced silhouette, rasterised fresh at every size that ships.

Both masters are computed once and committed, so a normal build needs neither a GPU nor torch. The vector data belongs to the pipeline, not to the shipped format: what you install is raster cursors at the sizes listed above.

Build instructions, the quality gate and how to recompute the masters: **[BUILD.md](BUILD.md)**.

#!/usr/bin/env python3
"""Reproducible builder for the Chrome Glass Remastered cursor theme (hybrid edition).

Frames come from hybrid.py: an illustration-tuned Real-ESRGAN colour master
(anime_6B, native up to 512px) inside vector-crisp traced silhouettes, packaged
for:
  * Windows - multi-size .cur (32-256px) + 60 fps .ani + Install.inf
              (17 scheme slots incl. the Windows 10/11 Pin and Person)
  * Linux   - native Xcursor theme (multi-size + animated) with name aliases
  * Debian  - installable .deb (aliases as symlinks)
  * packages/ - release artifacts: windows .zip, linux .tar.gz, .deb
  * preview.png + animated assets/*.webp (the READMEs embed these) and a .gif
    of each, for the places that still refuse animated webp - forum posts,
    DeviantArt, Reddit. Nothing in the repo links the gifs; they exist to be
    uploaded by hand.

Every build prints superiority metrics against the original frames and warns
when anything drifts out of tolerance.
"""
import os, io, struct, gzip, tarfile, hashlib, time, shutil, sys, zipfile
import concurrent.futures as cf
import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hybrid as H
import glyphs as G
import curlib

THEME = "Chrome Glass Remastered"
PKG = "chrome-glass-remastered-cursors"
# CI passes the tag. The local fallback is deliberately lower than any release
# so a dev build can never masquerade as one: dpkg used to happily see a
# hand-built 1.0.0 as newer-or-equal to nothing and refuse the real package.
VERSION = os.environ.get("RELEASE_VERSION", "0.0.0+local").lstrip("v")

SIZES = [32, 48, 64, 96, 128, 256]      # static .cur sizes (256 is the .cur ceiling)
# Xcursor has no per-image size cap, so Linux ships the extra HiDPI sizes the
# classic .cur format cannot express (its ICONDIRENTRY width/height is a single
# byte, 256 encoded as 0 - 384/512 are simply not representable there).
LINUX_SIZES = SIZES + [384, 512]        # static Xcursor sizes
# animated Xcursor sizes: up to 384 for HiDPI (4K + large pointer), matching
# the static cursors bar 512. These were once capped at 128 to chase a flicker
# blamed on the ~26 MB files GTK/Mutter had to re-parse, but the flicker was
# really the 60 fps cadence (see anim_frames' interp arg) and the cap did not
# fix it. At the author's ~20 fps these files are a third the size, so the
# HiDPI sizes are affordable again. 512 stays static-only: a 9-frame animation
# at native 512 is ~1 MB/frame of raw ARGB, for the rarest case there is.
ANI_SIZES = [32, 48, 64, 96, 128, 256, 384]
# sizes inside each .ani frame, largest first; Windows refuses animated
# frames holding a 128px image (verified empirically), 96 is the ceiling
ANI_SIZES_WIN = [96, 64, 48, 32]
ANI_SIZE = 128                          # reference size for timing

# Built into dist/ but kept out of the shipped archive. No scheme slot has
# pointed at Arrow_Down since the link-hover experiment was reverted, and
# tools/gen_social_preview.py reads it straight out of dist/, so shipping it
# only cost every user 407 KB in %SystemRoot%.
WIN_UNSHIPPED = {"Arrow_Down.cur"}

# NOTICE asks that the acknowledgement travels with the artwork, so both
# archives carry it next to the cursors rather than only in the repo.
LEGAL = ("LICENSE", "NOTICE")

# Xcursor role -> every name that should resolve to it. The first entry is the
# real file, the rest become symlinks in the tar/deb, so length here is free.
#
# The hex names are the legacy MD5 aliases. Firefox, Chromium/Electron, Java and
# older GTK2 request cursors by those and by nothing else; without them the
# pointer silently reverts to the fallback theme mid-drag or on link hover,
# which is the most visible way this theme can look unfinished on X11.
#
# Each hex below is placed by the canonical name Bibata's configs/normal/x.build.toml
# links it to, not from memory - a hex under the wrong role is worse than no hex
# at all, because the fallback theme would at least have shown the right shape.
XROLES = {
    "Arrow":     ["left_ptr", "default", "arrow", "top_left_arrow", "right_ptr",
                  "context-menu"],
    "Help":      ["help", "question_arrow", "left_ptr_help", "whats_this", "dnd-ask",
                  "5c6cd98b3f3ebcb1f9c7f1c204630408",
                  "d9ce0ab605698f320427677b458ad60b"],
    "AppStarting": ["progress", "left_ptr_watch", "half-busy",
                    "00000000000000020006000e7e9ffc3f",
                    "08e8e1c95fe2fc01f976f1e063a24ccd",
                    "3ecb610c1bf2410f44200f48c40d3599"],
    "Wait":      ["watch", "wait"],
    # `cell` is a plus/crosshair in spreadsheets, so it belongs here rather than
    # falling through to another theme.
    "Cross":     ["cross", "crosshair", "tcross", "cross_reverse", "diamond_cross",
                  "cell", "plus", "X_cursor"],
    "IBeam":     ["xterm", "text", "ibeam", "vertical-text"],
    "Handwriting": ["pencil", "draft"],
    # `circle` stays on NO. It is a literal circle outline in X11 rather than a
    # forbidden sign, but a near-miss glyph from this theme beats the jarring
    # jump to whatever the fallback theme draws - the same call made for
    # `cell`/`plus` above.
    "NO":        ["not-allowed", "crossed_circle", "forbidden", "no-drop", "dnd-none",
                  "circle", "03b6e0fcb3499374a867c041f52298f0"],
    "SizeNS":    ["size_ver", "ns-resize", "sb_v_double_arrow", "v_double_arrow",
                  "n-resize", "s-resize", "double_arrow", "row-resize", "top_side",
                  "bottom_side", "00008160000006810000408080010102",
                  "2870a09082c103050810ffdffffe0204"],
    "SizeWE":    ["size_hor", "ew-resize", "sb_h_double_arrow", "h_double_arrow",
                  "e-resize", "w-resize", "col-resize", "left_side", "right_side",
                  "028006030e0e7ebffc7f7070c0600140"],
    # bd_double_arrow is the NW-SE diagonal (it links to nwse-resize/size_fdiag),
    # so it belongs here. It sat under SizeNESW and drew the wrong diagonal.
    "SizeNWSE":  ["size_fdiag", "nwse-resize", "nw-resize", "se-resize",
                  "top_left_corner", "bottom_right_corner", "bd_double_arrow",
                  "c7088f0f3e6c8088236ef8e1e3e70000"],
    "SizeNESW":  ["size_bdiag", "nesw-resize", "ne-resize", "sw-resize",
                  "top_right_corner", "bottom_left_corner", "fd_double_arrow",
                  "fcf1c3c7cd4491d801f1e1c78f100000"],
    "SizeAll":   ["size_all", "move", "fleur", "all-scroll", "dnd-move",
                  "4498f0e0c1937ffe01fd06f973665830",
                  "9081237383d90e509aa00f00170e968f"],
    "UpArrow":   ["up_arrow", "up-arrow", "center_ptr", "sb_up_arrow"],
    # openhand/grab and closedhand/grabbing are one pair: sending the closed half
    # to SizeAll turned a hand into a four-way arrow mid-drag. The grabbing hex
    # follows them here for the same reason.
    "Hand":      ["pointer", "hand", "hand1", "hand2", "pointing_hand",
                  "openhand", "grab", "closedhand", "grabbing",
                  "dnd-copy", "copy", "alias", "link", "dnd-link",
                  "9d800788f1b08800ae810202380a0822",
                  "e29285e634086352946a0e7090d73106",
                  "1081e37283d90000800003c07f3ef6bf",
                  "6407b0e94181790501fd1e167b474872",
                  "b66166c04f8c3109214a4fbd64a50fc8",
                  "3085a0e285430894940527032f8b26df",
                  "640fb0e74195791501fd1ed57b41487f",
                  "a2a266d0498c3104214a47bd64ab0fc8",
                  "fcf21c00b30f7e3f83fe0dfd12e71cff"],
}

# Windows scheme slots in registry order (17 on Windows 10/11: pin and person
# come after link - verified against the stock Aero scheme definitions).
WIN_SLOTS = [
    ("pointer", "Arrow.cur"), ("help", "Help.cur"), ("work", "AppStarting.ani"),
    ("busy", "Wait.ani"), ("cross", "Cross.cur"), ("text", "IBeam.cur"),
    ("hand", "Handwriting.ani"), ("unavailable", "NO.ani"), ("vert", "SizeNS.cur"),
    ("horz", "SizeWE.cur"), ("dgn1", "SizeNWSE.cur"), ("dgn2", "SizeNESW.cur"),
    ("move", "SizeAll.cur"), ("alternate", "UpArrow.cur"), ("link", "Hand.ani"),
    ("pin", "Pin.cur"), ("person", "Person.cur"),
]

STATIC = H.STATIC + G.NAMES             # 11 originals + Pin + Person
ANIM = H.ANIM


def is_glyph(name):
    return name in G.NAMES


def hotspot(name):
    return G.HOTSPOT if is_glyph(name) else H.hotspot(name)


def static_image(name, size):
    return G.frame(name, size) if is_glyph(name) else H.frame_image(name, 0, size)


# ----------------------------------------------------------------------------- parallel warm-up
# Every frame the build emits comes from H.frame_image, which is pure and
# lru-cached but single-threaded - and a native 512px vector-mask render is the
# expensive part (~seconds each). One machine core did all of it. This renders
# every frame the build will ask for across all CPU cores up front, then feeds
# the results back into H.frame_image's cache, so the sequential build code
# below just reads warm values. Torch/GPU do not enter here: the cost is polygon
# rasterisation and numpy, not tensor math, so cores are the lever.
#
# The unit of work is one (name, idx) frame rendered at ALL sizes, not one
# (name, idx, size). Within a frame the sizes share the expensive _master and
# _base128 (an AI-colour + Reinhard pass, seconds each) through hybrid's own
# lru_cache; splitting sizes across workers instead threw that sharing away and
# ran slower than single-core. Keeping a whole frame on one worker preserves it.
_WARM_SIZES = ()

def _init_worker(sizes):
    global _WARM_SIZES                                  # spawned workers re-import
    _WARM_SIZES = sizes                                 # this module, so seed it here


def _gen_frame(job):
    name, idx = job
    return [((name, idx, s), H.frame_image(name, idx, s)) for s in _WARM_SIZES]


def _warm_frames():
    sizes = tuple(sorted(set(LINUX_SIZES) | set(ANI_SIZES) | set(ANI_SIZES_WIN)
                         | {ANI_SIZE, 512}, reverse=True))
    jobs = [(name, 0) for name in H.STATIC]
    for name in ANIM:
        jobs += [(name, idx) for idx in range(len(H.BY_NAME[name]["frames"]))]
    workers = min(os.cpu_count() or 1, len(jobs))
    t0 = time.time()
    cache = {}
    # numpy/PIL already thread internally via BLAS; 12 processes each spawning
    # 12 BLAS threads oversubscribes the 12 cores and cancels the win. Pin each
    # spawned worker to a single BLAS thread (env is inherited by spawn before
    # its numpy import) so the process pool is the only parallelism.
    prev_env = {v: os.environ.get(v) for v in
                ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")}
    os.environ.update({v: "1" for v in prev_env})
    try:
        with cf.ProcessPoolExecutor(max_workers=workers, initializer=_init_worker,
                                    initargs=(sizes,)) as ex:
            for pairs in ex.map(_gen_frame, jobs):
                cache.update(pairs)
    finally:
        for v, old in prev_env.items():
            if old is None:
                os.environ.pop(v, None)
            else:
                os.environ[v] = old
    inner = H.frame_image
    def cached(name, idx, size):
        hit = cache.get((name, idx, size))
        return hit if hit is not None else inner(name, idx, size)
    H.frame_image = cached
    print("  warm-up: %d frames x %d sizes on %d cores in %.1fs"
          % (len(jobs), len(sizes), workers, time.time() - t0))


def _scale_hot(name, size):
    hx, hy = hotspot(name)
    return round(hx * size / 32), round(hy * size / 32)


# ----------------------------------------------------------------------------- Windows
def _make_anih(nframes, disp_rate):
    return struct.pack("<9I", 36, nframes, nframes, 0, 0, 32, 1, disp_rate, 1)


def build_windows(dist):
    out = os.path.join(dist, "windows", THEME)
    os.makedirs(out, exist_ok=True)
    for name in STATIC:
        frames = []
        for s in SIZES:
            hx, hy = _scale_hot(name, s)
            frames.append({"img": static_image(name, s), "hx": hx, "hy": hy})
        open(os.path.join(out, name + ".cur"), "wb").write(curlib.write_cur(frames))
    for name in ANIM:
        # stock aero .ani ships every frame as a multi-size .cur and no rate
        # chunk when the timing is uniform - mirror that so the Pointers-tab
        # preview animates and Windows picks a native size at any DPI
        per_size = {s: H.anim_frames(name, s)[0] for s in ANI_SIZES_WIN}
        rates = H.anim_frames(name, ANI_SIZE)[1]
        blobs = []
        for i in range(len(rates)):
            entries = [{"img": per_size[s][i], "hx": _scale_hot(name, s)[0],
                        "hy": _scale_hot(name, s)[1]} for s in ANI_SIZES_WIN]
            blobs.append(curlib.write_cur(entries))
        uniform = len(set(rates)) == 1
        ani = {"anih": _make_anih(len(rates), rates[0] if uniform else 1),
               "rates": None if uniform else rates, "seqs": None}
        open(os.path.join(out, name + ".ani"), "wb").write(
            curlib.write_ani(ani, blobs))
    write_inf(out)
    return out


def build_original(dist):
    """The authentic 2006 set, byte for byte at its native 32px - a reference
    baseline next to the remaster (and a fallback to generate from). No Pin or
    Person: those slots did not exist in the original.

    Deliberately a local artefact only: it is not packaged into packages/ and
    not attached to releases. It exists to diff the remaster against, not to
    install - so it ships no Install.inf either."""
    out = os.path.join(dist, "original", "Chrome Glass (2006)")
    os.makedirs(out, exist_ok=True)
    for name in H.STATIC:
        hx, hy = H.hotspot(name)
        frames = [{"img": H.original(name, 0), "hx": hx, "hy": hy}]
        open(os.path.join(out, name + ".cur"), "wb").write(curlib.write_cur(frames))
    for name in H.ANIM:
        hx, hy = H.hotspot(name)
        rates = list(H.BY_NAME[name]["rates"])
        blobs = [curlib.write_cur([{"img": H.original(name, i), "hx": hx, "hy": hy}])
                 for i in range(len(rates))]
        uniform = len(set(rates)) == 1
        ani = {"anih": _make_anih(len(rates), rates[0] if uniform else 1),
               "rates": None if uniform else rates, "seqs": None}
        open(os.path.join(out, name + ".ani"), "wb").write(
            curlib.write_ani(ani, blobs))
    return out


def write_inf(out):
    strings = 'CUR_DIR      = "%s"\nSCHEME_NAME  = "%s"' % (THEME, THEME)
    slot_strings = "\n".join('%-12s = "%s"' % (role, fn) for role, fn in WIN_SLOTS)
    reg_val = ",".join("%%10%%\\%%CUR_DIR%%\\%%%s%%" % role for role, _ in WIN_SLOTS)
    copy = "\n".join('"%s"' % fn for _, fn in WIN_SLOTS)
    inf = f""";  {THEME} - cursor scheme installer
;  Right-click this file, choose "Install", then pick "{THEME}" in
;  Settings > Bluetooth & devices > Mouse > Additional mouse settings > Pointers.
;  Right-click > "Uninstall" removes the scheme and the copied cursors again.

[Version]
signature="$CHICAGO$"

[DefaultInstall]
CopyFiles = Scheme.Cur
AddReg    = Scheme.Reg

[DefaultUninstall]
DelFiles = Scheme.Cur
DelReg   = Scheme.Reg

[DestinationDirs]
Scheme.Cur = 10,"%CUR_DIR%"

; HKCU only. Writing the same scheme name to the machine-wide hive as well
; (HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Control Panel\\Cursors\\Schemes)
; would fix the rare case where the elevating admin is not the logged-in user,
; but the Pointers tab merges both hives, so the common case would get the
; scheme listed twice. Not worth the trade until it can be checked on a real
; machine.
[Scheme.Reg]
HKCU,"Control Panel\\Cursors\\Schemes","%SCHEME_NAME%",,"{reg_val}"

[Scheme.Cur]
{copy}

[Strings]
{strings}

{slot_strings}
"""
    open(os.path.join(out, "Install.inf"), "w", newline="\r\n", encoding="utf-8").write(inf)


# ----------------------------------------------------------------------------- Linux
IMG_TYPE = 0xfffd0002
HOLD_MS = 1000000                       # "freeze on last frame" for Xcursor


def _jiffies_ms(rate):
    return min(round(rate * 1000 / 60), HOLD_MS)


def _pack_ximage(size, img, xh, yh, delay):
    w, h = img.size
    arr = np.asarray(img, dtype=np.uint32)
    v = (arr[..., 3] << 24) | (arr[..., 0] << 16) | (arr[..., 1] << 8) | arr[..., 2]
    return (struct.pack("<9I", 36, IMG_TYPE, size, 1, w, h, xh, yh, delay)
            + v.astype("<u4").tobytes())


def _xcursor(images):
    header = struct.pack("<IIII", 0x72756358, 16, 0x00010000, len(images))
    toc = bytearray(); pos = 16 + len(images) * 12
    for c in images:
        toc += struct.pack("<III", IMG_TYPE, struct.unpack_from("<I", c, 8)[0], pos)
        pos += len(c)
    return header + bytes(toc) + b"".join(images)


def build_linux(dist):
    out = os.path.join(dist, "linux", THEME)
    cur = os.path.join(out, "cursors")
    os.makedirs(cur, exist_ok=True)
    aliases = {}
    for role, names in XROLES.items():
        imgs = []
        if role in ANIM:
            for size in ANI_SIZES:
                # interp=False: Xcursor animated cursors (GNOME/Mutter) flicker
                # at the interpolated 60 fps cadence on at least one hybrid
                # Intel+NVIDIA X11 setup - the swap has no compositor-side
                # frame sync, so on a 60 Hz panel it periodically lands out of
                # phase with the refresh. The author's native ~20 fps cadence
                # (same as Handwriting/NO) doesn't reproduce it. Windows .ani
                # keeps the interpolated 60 fps - untested there, no reports.
                frames, rates = H.anim_frames(role, size, interp=False)
                hx, hy = _scale_hot(role, size)
                for img, rate in zip(frames, rates):
                    imgs.append(_pack_ximage(size, img, hx, hy, _jiffies_ms(rate)))
        else:
            for size in LINUX_SIZES:
                hx, hy = _scale_hot(role, size)
                imgs.append(_pack_ximage(size, static_image(role, size), hx, hy, 0))
        data = _xcursor(imgs)
        real = os.path.join(cur, names[0])
        open(real, "wb").write(data)
        for alias in names[1:]:
            shutil.copyfile(real, os.path.join(cur, alias))
        aliases[names[0]] = names[1:]
    open(os.path.join(out, "index.theme"), "w", newline="\n").write(
        "[Icon Theme]\nName=%s\nComment=Chrome Glass remaster - original pixels, "
        "crisp at 32-512px\nInherits=Adwaita\n" % THEME)
    open(os.path.join(out, "cursor.theme"), "w", newline="\n").write(
        "[Icon Theme]\nName=%s\nInherits=%s\n" % (THEME, THEME))
    return out, aliases


# ----------------------------------------------------------------------------- packaging
def _tar_gz(entries, mtime):
    """entries: (arcname, data_bytes | None, mode, linkname | None)."""
    raw = io.BytesIO()
    tf = tarfile.open(fileobj=raw, mode="w", format=tarfile.GNU_FORMAT)
    seen = set()
    def adddir(p):
        c = "."
        for part in p.strip("/").split("/"):
            c += "/" + part
            if c not in seen:
                seen.add(c)
                ti = tarfile.TarInfo(c); ti.type = tarfile.DIRTYPE
                ti.mode = 0o755; ti.mtime = mtime; tf.addfile(ti)
    for arc, data, mode, link in entries:
        dn = os.path.dirname(arc)
        if dn: adddir(dn)
        ti = tarfile.TarInfo("./" + arc); ti.mode = mode; ti.mtime = mtime
        if link is not None:
            ti.type = tarfile.SYMTYPE; ti.linkname = link
            tf.addfile(ti)
        else:
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    tf.close()
    gz = io.BytesIO()
    with gzip.GzipFile(fileobj=gz, mode="wb", mtime=mtime) as g:
        g.write(raw.getvalue())
    return gz.getvalue()


def _linux_entries(linux_dir, aliases, root):
    """Real files once, aliases as symlinks (saves ~85% of the payload)."""
    alias_of = {a: real for real, al in aliases.items() for a in al}
    entries = []
    for r, _, files in os.walk(linux_dir):
        for fn in sorted(files):
            rel = os.path.relpath(os.path.join(r, fn), linux_dir).replace("\\", "/")
            arc = root + "/" + rel
            if fn in alias_of and rel.startswith("cursors/"):
                entries.append((arc, None, 0o777, alias_of[fn]))
            else:
                entries.append((arc, open(os.path.join(r, fn), "rb").read(), 0o644, None))
    return entries


MAINTAINER = "mikedigriz <mikedigriz@users.noreply.github.com>"
HOMEPAGE = "https://github.com/mikedigriz/" + PKG


def _deb_changelog(mtime):
    """gzipped Debian changelog - Policy 12.7 makes it mandatory, and lintian
    fails the package without it.

    Generated rather than kept in the repository: the only fact it can state is
    which version this is, and that already lives in the git tag. gzip mtime is
    pinned to 0 so the member is byte-stable across builds."""
    import email.utils, datetime
    when = email.utils.format_datetime(
        datetime.datetime.fromtimestamp(mtime, datetime.timezone.utc))
    text = ("%s (%s) unstable; urgency=medium\n\n"
            "  * Release %s. Release notes: %s/releases\n\n"
            " -- %s  %s\n" % (PKG, VERSION, VERSION, HOMEPAGE, MAINTAINER, when))
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9, mtime=0) as g:
        g.write(text.encode())
    return buf.getvalue()


def build_deb(linux_dir, aliases, packages):
    os.makedirs(packages, exist_ok=True)
    mtime = int(time.time())
    root = "usr/share/icons/" + THEME
    entries = _linux_entries(linux_dir, aliases, root)
    # Policy 12.5: every package needs a copyright file. LICENSE covers the
    # code, NOTICE the artwork, and both matter here.
    copyright_txt = b"\n\n".join(open(os.path.join(HERE, fn), "rb").read() for fn in LEGAL)
    entries.append(("usr/share/doc/%s/copyright" % PKG, copyright_txt, 0o644, None))
    entries.append(("usr/share/doc/%s/changelog.gz" % PKG, _deb_changelog(mtime), 0o644, None))
    total = sum(len(d) for _, d, _, _ in entries if d)
    md5 = ["%s  %s" % (hashlib.md5(d).hexdigest(), arc)
           for arc, d, _, link in entries if link is None]
    data_tar = _tar_gz(entries, mtime)
    control = (f"Package: {PKG}\nVersion: {VERSION}\nArchitecture: all\n"
               f"Maintainer: {MAINTAINER}\n"
               f"Installed-Size: {max(1,total//1024)}\n"
               f"Section: x11\nPriority: optional\n"
               f"Homepage: {HOMEPAGE}\n"
               f"Description: {THEME} cursor theme\n"
               f" Chrome Glass remaster: original pixels, crisp edges, 32-512px.\n")
    # Without the alternatives entry the theme installs but never becomes the
    # system X cursor theme, so the user has to go hunting for it in a settings
    # panel - the single most common "the deb did nothing" report for cursor
    # packages. Priority 20 stays below a user's deliberate pick.
    index = "/usr/share/icons/%s/index.theme" % THEME
    postinst = (
        "#!/bin/sh\nset -e\n"
        "if command -v update-alternatives >/dev/null 2>&1; then\n"
        # /usr/share/icons/default is normally provided by another package;
        # on a bare system it does not exist and update-alternatives refuses
        # to create the link, which under `set -e` fails the whole install.
        "    mkdir -p /usr/share/icons/default\n"
        "    update-alternatives --install /usr/share/icons/default/index.theme "
        "x-cursor-theme '%s' 20\nfi\n"
        "exit 0\n" % index)
    prerm = (
        "#!/bin/sh\nset -e\n"
        'if [ "$1" = remove ] || [ "$1" = deconfigure ]; then\n'
        "    if command -v update-alternatives >/dev/null 2>&1; then\n"
        "        update-alternatives --remove x-cursor-theme '%s'\n"
        "    fi\nfi\n"
        "exit 0\n" % index)
    ctl = _tar_gz([("control", control.encode(), 0o644, None),
                   ("md5sums", ("\n".join(md5) + "\n").encode(), 0o644, None),
                   ("postinst", postinst.encode(), 0o755, None),
                   ("prerm", prerm.encode(), 0o755, None)], mtime)
    def ar(name, dd):
        h = "%-16s%-12d%-6d%-6d%-8o%-10d`\n" % (name, mtime, 0, 0, 0o100644, len(dd))
        return h.encode() + dd + (b"\n" if len(dd) % 2 else b"")
    deb = b"!<arch>\n" + ar("debian-binary", b"2.0\n") + ar("control.tar.gz", ctl) + ar("data.tar.gz", data_tar)
    path = os.path.join(packages, f"{PKG}_{VERSION}_all.deb")
    open(path, "wb").write(deb)
    return path


# ----------------------------------------------------------------------------- macOS (Mousecape)
# macOS has no system cursor themes; Mousecape applies "capes". Only cursor
# identifiers with a confident mapping are included - Mousecape leaves the
# rest at the system default.
# Identifiers checked against cursorMap() in Mousecape's mousecloak/MCDefs.m.
# com.apple.cursor.3 is "Forbidden", NOT the crosshair it was mapped to here -
# the cape was replacing the no-entry cursor with a plus sign. The crosshair is
# com.apple.cursor.7. com.apple.cursor.13 ("Pointing") was already right.
MAC_CURSORS = [
    ("com.apple.coregraphics.Arrow", "Arrow", False),
    ("com.apple.coregraphics.IBeam", "IBeam", False),
    ("com.apple.coregraphics.Move", "SizeAll", False),
    ("com.apple.coregraphics.Wait", "Wait", True),
    ("com.apple.cursor.7", "Cross", False),        # Crosshair
    ("com.apple.cursor.13", "Hand", False),        # Pointing
    ("com.apple.cursor.3", "NO", False),           # Forbidden
    ("com.apple.cursor.40", "Help", False),        # Help
    ("com.apple.cursor.23", "SizeNS", False),      # Resize N-S
    ("com.apple.cursor.28", "SizeWE", False),      # Resize E-W
    ("com.apple.cursor.30", "SizeNESW", False),    # Resize NE-SW
    ("com.apple.cursor.34", "SizeNWSE", False),    # Resize NW-SE
]
MAC_SCALES = [1, 2, 5]                             # points x scale = pixels


def _cape_strip(name, animated, scale):
    """Vertical film strip (Mousecape layout) of all frames at one scale."""
    size = 32 * scale
    if animated:
        frames, _ = H.anim_frames(name, size)
    elif name in ANIM:
        # A cape has one FrameDuration, so it cannot express the author's
        # "play once, then hold" rate chunk. Ship the settled last frame
        # instead of frame 0, which is the start of the draw-on.
        frames = [H.frame_image(name, len(H.BY_NAME[name]["frames"]) - 1, size)]
    else:
        frames = [static_image(name, size)]
    strip = Image.new("RGBA", (size, size * len(frames)), (0, 0, 0, 0))
    for i, f in enumerate(frames):
        strip.alpha_composite(f, (0, i * size))
    buf = io.BytesIO()
    strip.save(buf, "PNG")
    return buf.getvalue(), len(frames)


def _cape_version(ver):
    """'1.2.5' -> 1.0205: monotonic in a single float, two digits per component."""
    parts = [int(p) for p in ver.split(".")[:3] if p.isdigit()]
    parts += [0] * (3 - len(parts))
    return parts[0] + parts[1] / 100.0 + parts[2] / 10000.0


def build_mac(packages):
    import plistlib
    cursors = {}
    for ident, name, animated in MAC_CURSORS:
        reps, nframes = [], 1
        for sc in MAC_SCALES:
            data, nframes = _cape_strip(name, animated, sc)
            reps.append(data)
        hx, hy = hotspot(name)
        cursors[ident] = {
            "FrameCount": nframes,
            "FrameDuration": 1.0 / 60.0,
            "HotSpotX": float(hx), "HotSpotY": float(hy),
            "PointsWide": 32.0, "PointsHigh": 32.0,
            "Representations": reps,
        }
    cape = {
        "Author": "Chrome Glass Remastered",
        "CapeName": THEME,
        # Mousecape wants a number, so fold the patch component in rather than
        # dropping it - "1.0.5" used to become 1.0 and no patch release ever
        # looked newer than the one before it.
        "CapeVersion": _cape_version(VERSION),
        "Cloud": False,
        "HiDPI": True,
        "Identifier": "com.github.chrome-glass-remastered",
        "MinimumVersion": 2.0,
        "Version": 2.0,
        "Cursors": cursors,
    }
    path = os.path.join(packages, "ChromeGlassRemastered.cape")
    with open(path, "wb") as f:
        plistlib.dump(cape, f, fmt=plistlib.FMT_XML)
    return path


def build_artifacts(win_dir, linux_dir, aliases, packages):
    os.makedirs(packages, exist_ok=True)
    zpath = os.path.join(packages, "ChromeGlassRemastered-windows.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for fn in sorted(os.listdir(win_dir)):
            if fn not in WIN_UNSHIPPED:
                z.write(os.path.join(win_dir, fn), THEME + "/" + fn)
        for fn in LEGAL:
            z.write(os.path.join(HERE, fn), THEME + "/" + fn)
    tpath = os.path.join(packages, "ChromeGlassRemastered-linux.tar.gz")
    entries = _linux_entries(linux_dir, aliases, THEME)
    entries += [(THEME + "/" + fn, open(os.path.join(HERE, fn), "rb").read(), 0o644, None)
                for fn in LEGAL]
    open(tpath, "wb").write(_tar_gz(entries, int(time.time())))
    return zpath, tpath


# ----------------------------------------------------------------------------- previews
def _onbg(im, light=(244, 244, 246), dark=(222, 222, 226)):
    b = Image.new("RGB", im.size, light); px = b.load()
    for y in range(im.size[1]):
        for x in range(im.size[0]):
            if (x // 10 + y // 10) % 2 == 0: px[x, y] = dark
    b = b.convert("RGBA"); b.alpha_composite(im); return b


def build_preview():
    # Hand and Handwriting are skipped here: in the 2006 original they're the
    # same arrow silhouette as Arrow with only a per-frame shimmer, so a single
    # still frame just duplicates the Arrow tile. They're still built and
    # shipped - only this showcase grid leaves them out, and assets/animations
    # shows them moving, which is the only way they read as distinct anyway.
    # Arrow_Down is left out for the opposite reason: WIN_UNSHIPPED keeps it out
    # of the archive, so putting it in the showcase advertises a cursor nobody
    # who downloads the release actually gets.
    order = ["Arrow", "Help", "IBeam", "Cross", "SizeAll", "SizeNS", "SizeWE",
             "SizeNWSE", "SizeNESW", "UpArrow", "Pin", "Person",
             "NO", "Wait", "AppStarting"]
    # 5 columns divides the 15 tiles evenly, and the labels are sized for what
    # a README actually shows: GitHub caps the content column near 880 px, so
    # a 1092 px sheet lands close to 1:1 instead of shrinking the text to mush.
    cell, pad, cols, lab = 192, 22, 5, 34
    rows = (len(order) + cols - 1) // cols
    # the cursors are pale translucent glass, invisible on white - use a dark
    # sheet with a subtle checkerboard so every one of them reads. Render each
    # at 192px (native from the 256 master) so nothing looks soft.
    sheet = Image.new("RGBA", (pad + cols * (cell + pad), pad + rows * (cell + pad + lab)), (43, 45, 51, 255))
    d = ImageDraw.Draw(sheet)
    f = _font(26)
    # Frame 2 reads fine for the cursors that only shimmer, but NO animates a
    # red forbidden sign growing from nothing, and frame 2 catches it as a red
    # smear across the arrow. 7 of its 11 is the last frame where the sign is
    # complete and still fits the cell - past that it outgrows the frame and
    # clips, and it also hides the arrow underneath.
    still = {"NO": 7}
    for i, name in enumerate(order):
        if name in ANIM:
            img = H.frame_image(name, still.get(name, 2), cell)
        else:
            img = static_image(name, cell)
        r, c = divmod(i, cols); x = pad + c * (cell + pad); y = pad + r * (cell + pad + lab)
        sheet.alpha_composite(_onbg(img, light=(84, 87, 96), dark=(66, 69, 77)), (x, y))
        d.text((x + 2, y + cell + 3), name, fill=(198, 200, 206), font=f)
    sheet.convert("RGB").save(os.path.join(HERE, "preview.png"))


def _pad(img, box):
    c = Image.new("RGBA", (box, box), (0, 0, 0, 0))
    c.alpha_composite(img, ((box - img.size[0]) // 2, (box - img.size[1]) // 2))
    return c


def _gif_frame(rgba, bg=(248, 248, 250)):
    flat = Image.new("RGB", rgba.size, bg); flat.paste(rgba, (0, 0), rgba)
    return flat.quantize(colors=256, method=Image.MEDIANCUT, dither=Image.NONE)


# Lossless webp on a 27-frame animation is what made assets/animations.webp
# 914 KB - a README-only asset heavier than any release artifact, re-fetched on
# every page view. These are translucent glass gradients viewed at a couple of
# hundred pixels; q=90 is indistinguishable and roughly a tenth the bytes.
_WEBP = dict(lossless=False, quality=90, method=6)


def build_animations():
    assets = os.path.join(HERE, "assets")
    os.makedirs(assets, exist_ok=True)
    # Only clear what this function rewrites. Wiping the whole directory also
    # took assets/social-preview.png with it - that one is committed and comes
    # from tools/gen_social_preview.py, which the build never calls, so every
    # build silently deleted the repo's cover image.
    stale = [n + ext for n in ANIM for ext in (".webp", ".gif")]
    stale += ["animations.webp", "animations.gif"]
    for fn in stale:
        p = os.path.join(assets, fn)
        if os.path.exists(p): os.remove(p)
    disp = 128
    for name in ANIM:
        frames, rates = H.anim_frames(name, disp)
        # previews loop: cap the author's freeze-forever at 2 s
        durs = [min(_jiffies_ms(r), 2000) for r in rates]
        rgba = [_pad(f, disp + 32) for f in frames]
        rgba[0].save(os.path.join(assets, name + ".webp"), save_all=True,
                     append_images=rgba[1:], duration=durs, loop=0, **_WEBP)
        gif = [_gif_frame(f) for f in rgba]
        gif[0].save(os.path.join(assets, name + ".gif"), save_all=True,
                    append_images=gif[1:], duration=durs, loop=0, disposal=2, optimize=True)
    # Combined strip at 60 fps, and the heaviest asset in the repo: 27 frames of
    # the full width, re-fetched on every README view. 128 px cells made a 712 px
    # sheet that every README then stretched to its ~880 px content column, so it
    # showed blurry as well. 160 px puts the sheet at 884 px, near enough 1:1 that
    # nothing is resampled either way - and since weight here scales with pixels
    # rather than with quality (dropping q from 90 to 70 buys ~11%, visibly),
    # sizing the sheet to the column is the whole optimisation.
    # The cells stay unlabelled and the sheet stays transparent on purpose: text
    # baked in here would be one language only, and a fill light enough to read
    # on GitHub's dark theme disappears on the light one. The READMEs name the
    # five in order in their own prose.
    box, gap = 160, 14
    per = {n: H.anim_frames(n, box)[0] for n in ANIM}
    n = max(len(f) for f in per.values())
    W = len(ANIM) * (box + gap) + gap
    strip = []
    for f in range(n):
        canvas = Image.new("RGBA", (W, box + 2 * gap), (0, 0, 0, 0))
        for j, name in enumerate(ANIM):
            fr = per[name][f % len(per[name])]
            canvas.alpha_composite(fr, (gap + j * (box + gap), gap))
        strip.append(canvas)
    strip[0].save(os.path.join(assets, "animations.webp"), save_all=True,
                  append_images=strip[1:], duration=17, loop=0, **_WEBP)
    sg = [_gif_frame(f) for f in strip]
    sg[0].save(os.path.join(assets, "animations.gif"), save_all=True,
               append_images=sg[1:], duration=20, loop=0, disposal=2, optimize=True)
    return assets


# ----------------------------------------------------------------------------- checks
def _font(size):
    from PIL import ImageFont
    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    from PIL import ImageFont as F
    return F.load_default()


def build_comparison(assets):
    """assets/comparison.png: what a 4K/HiDPI screen actually shows - the 2006
    bitmap stretched by the OS vs the remaster's native detail. Dark sheet so
    the pale translucent glass reads.

    Stacked in pairs rather than laid out in one row. Six 512 px cells side by
    side came to 3328 px, and a README scales that to its ~880 px column: a 3.8x
    downscale, which resamples away the exact stair-stepping the picture exists
    to prove. Two pairs deep is 1120 px wide, near 1:1, and the aliasing
    survives. Arrow and Wait carry it - the pointer you look at all day, plus a
    saturated animated one - so the third pair only added width.

    Labels are bare pixel counts, and the explanatory sentence that used to be
    drawn across the top is gone: it was English baked into a file README.ru.md
    embeds too, so half of the Russian page's headline visual was untranslated.
    Numbers need no translation; each README captions the picture in its own
    language."""
    cell, pad, lab = 512, 32, 40
    pairs = [("Arrow", 0), ("Wait", 2)]
    W = pad + 2 * (cell + pad)
    height = pad + len(pairs) * (cell + lab + pad)
    sheet = Image.new("RGBA", (W, height), (43, 45, 51, 255))
    d = ImageDraw.Draw(sheet)
    f = _font(28)
    onbg = lambda im: _onbg(im, light=(84, 87, 96), dark=(66, 69, 77))
    for i, (name, idx) in enumerate(pairs):
        y = pad + i * (cell + lab + pad)
        orig = H.original(name, idx).resize((cell, cell), Image.NEAREST)
        new = H.frame_image(name, idx, cell)
        sheet.alpha_composite(onbg(orig), (pad, y))
        sheet.alpha_composite(onbg(new), (pad + cell + pad, y))
        d.text((pad + 4, y + cell + 8), "32 px", fill=(232, 150, 150), font=f)
        d.text((pad + cell + pad + 4, y + cell + 8), "512 px",
               fill=(150, 224, 165), font=f)
    sheet.convert("RGB").save(os.path.join(assets, "comparison.png"))


def check_inf(win):
    """Every filename referenced by Install.inf must exist next to it."""
    import re
    inf = open(os.path.join(win, "Install.inf"), encoding="utf-8").read()
    referenced = set(re.findall(r'"([\w\-]+\.(?:cur|ani))"', inf))
    missing = [f for f in referenced if not os.path.exists(os.path.join(win, f))]
    if missing:
        raise SystemExit("Install.inf references missing files: %s" % ", ".join(missing))
    # every slot, not just the two newest - a slot silently dropping out of
    # WIN_SLOTS used to be invisible until someone installed the scheme
    lost = [fn for _, fn in WIN_SLOTS if fn not in referenced]
    if lost:
        raise SystemExit("Install.inf lost slots: %s" % ", ".join(lost))
    for section in ("[DefaultInstall]", "[DefaultUninstall]"):
        if section not in inf:
            raise SystemExit("Install.inf lost %s" % section)


def _med_alpha(img):
    a = np.asarray(img)[..., 3].astype(float)
    vis = a > 0.25 * a.max()
    return float(np.median(a[vis])) if vis.any() else 0.0


def _sat(img):
    arr = np.asarray(img).astype(float)
    return H._mean_sat(arr[..., :3], arr[..., 3])


def check_metrics():
    """Superiority metrics vs the original frames; drift prints a WARN.

    Checked at 128px (the tuning anchor) and at each cursor's native shipped
    anchor (256 or 512, see hybrid._master) - a regression only visible in the
    native master would otherwise pass silently at 128."""
    warns = 0
    for name in H.STATIC + ANIM:
        n = len(H.BY_NAME[name]["frames"])
        for idx in range(n):
            o = H.original(name, idx)
            _, native = H._master(name, idx)
            for size in sorted({128, native}):
                h = H.frame_image(name, idx, size)
                da = (_med_alpha(h) - _med_alpha(o)) / max(_med_alpha(o), 1e-6) * 100
                so, sh = _sat(o), _sat(h)
                sat_ok = (so <= 1e-6 or -2 <= (sh - so) / max(so, 1e-6) * 100 <= 12
                          or abs(sh - so) <= 0.02)
                if abs(da) > 8:
                    print(f"  WARN {name}[{idx}]@{size}: median alpha drift {da:+.1f}% (>8%)")
                    warns += 1
                if not sat_ok:
                    print(f"  WARN {name}[{idx}]@{size}: saturation {so:.3f} -> {sh:.3f}")
                    warns += 1
    return warns


def check_packages(win):
    """Round-trip the written .cur/.ani files and verify sizes and timing."""
    for name in STATIC:
        frames = curlib.read_cur(open(os.path.join(win, name + ".cur"), "rb").read())
        sizes = sorted(f["img"].size[0] for f in frames)
        assert sizes == sorted(SIZES), f"{name}.cur sizes {sizes}"
    for name in ANIM:
        ani = curlib.read_ani(open(os.path.join(win, name + ".ani"), "rb").read())
        nf = struct.unpack_from("<I", ani["anih"], 4)[0]
        disp = struct.unpack_from("<I", ani["anih"], 28)[0]
        sizes = sorted(f["img"].size[0] for f in curlib.read_cur(ani["frames"][0]))
        assert sizes == sorted(ANI_SIZES_WIN), f"{name}.ani frame sizes {sizes}"
        orig_rates = H.BY_NAME[name]["rates"]
        if name in H.INTERP:
            want_n = len(H.BY_NAME[name]["frames"]) * H.INTERP_N
            assert nf == want_n and disp == 1 and ani["rates"] is None, \
                f"{name}.ani timing"
            orig_cycle = sum(orig_rates)
            assert abs(nf * disp - orig_cycle) / orig_cycle <= 0.05, \
                f"{name}.ani cycle length"
            uniq = len({f for f in ani["frames"]})
            assert uniq == want_n, f"{name}.ani only {uniq}/{want_n} distinct frames"
        else:
            assert nf == len(orig_rates) and ani["rates"] == orig_rates, \
                f"{name}.ani must keep the author's rate chunk"
    print("  .cur: %d cursors x %d sizes (incl. 256px)" % (len(STATIC), len(SIZES)))
    print("  .ani: 60 fps (27 frames rate=1: %s; author's timing kept: %s)" % (
        ", ".join(sorted(H.INTERP)), ", ".join(sorted(set(ANIM) - H.INTERP))))


def main():
    dist = os.path.join(HERE, "dist")
    if os.path.exists(dist): shutil.rmtree(dist)
    if os.environ.get("BUILD_SERIAL") != "1":           # escape hatch: BUILD_SERIAL=1
        _warm_frames()                                   # renders single-core instead
    win = build_windows(dist)
    check_inf(win)
    orig_theme = build_original(dist)
    lin, aliases = build_linux(dist)
    packages = os.path.join(HERE, "packages")
    if os.path.exists(packages): shutil.rmtree(packages)
    deb = build_deb(lin, aliases, packages)
    zpath, tpath = build_artifacts(win, lin, aliases, packages)
    cape = build_mac(packages)
    build_preview()
    assets = build_animations()
    build_comparison(assets)
    print("macOS   :", os.path.relpath(cape, HERE))
    print("Windows :", os.path.relpath(win, HERE), "-", len(os.listdir(win)), "files")
    print("Original:", os.path.relpath(orig_theme, HERE), "-", len(os.listdir(orig_theme)), "files (2006, 32px)")
    print("Linux   :", os.path.relpath(lin, HERE), "-", len(os.listdir(os.path.join(lin, "cursors"))), "cursor files")
    print("Debian  :", os.path.relpath(deb, HERE))
    print("Zips    :", os.path.relpath(zpath, HERE), "+", os.path.relpath(tpath, HERE))
    print("Preview : preview.png   Animations: assets/*.webp")
    print("Checks:")
    check_packages(win)
    warns = check_metrics()
    print("  metrics: %s" % ("all within tolerance" if not warns else f"{warns} warning(s)"))
    if warns and os.environ.get("ALLOW_METRIC_WARN") != "1":
        raise SystemExit(f"check_metrics: {warns} warning(s) out of tolerance "
                          "(set ALLOW_METRIC_WARN=1 to ship anyway)")


if __name__ == "__main__":
    main()

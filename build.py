#!/usr/bin/env python3
"""Reproducible builder for the Chrome Glass Remastered cursor theme (hybrid edition).

Frames come from hybrid.py: the original Chrome Glass pixels (32px verbatim,
AI-restored colour at 128px) inside vector-crisp traced silhouettes, packaged
for:
  * Windows - multi-size .cur (32-256px) + 60 fps .ani + Install.inf
              (17 scheme slots incl. the Windows 10/11 Pin and Person)
  * Linux   - native Xcursor theme (multi-size + animated) with name aliases
  * Debian  - installable .deb (aliases as symlinks)
  * packages/ - release artifacts: windows .zip, linux .tar.gz, .deb
  * preview.png + animated assets/*.webp (+ .gif fallback)

Every build prints superiority metrics against the original frames and warns
when anything drifts out of tolerance.
"""
import os, io, struct, gzip, tarfile, hashlib, time, shutil, sys, zipfile
import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hybrid as H
import glyphs as G
import curlib

THEME = "Chrome Glass Remastered"
PKG = "chrome-glass-remastered-cursors"
VERSION = "1.0.0"

SIZES = [32, 48, 64, 96, 128, 256]      # static .cur / Xcursor sizes
ANI_SIZES = [32, 48, 64, 96, 128]       # animated Xcursor sizes
# sizes inside each .ani frame, largest first; Windows refuses animated
# frames holding a 128px image (verified empirically), 96 is the ceiling
ANI_SIZES_WIN = [96, 64, 48, 32]
ANI_SIZE = 128                          # reference size for timing

XROLES = {
    "Arrow":     ["left_ptr", "default", "arrow", "top_left_arrow", "context-menu"],
    "Help":      ["help", "question_arrow", "left_ptr_help", "whats_this", "dnd-ask"],
    "AppStarting": ["progress", "left_ptr_watch", "half-busy"],
    "Wait":      ["watch", "wait"],
    "Cross":     ["cross", "crosshair", "tcross", "cross_reverse", "diamond_cross"],
    "IBeam":     ["xterm", "text", "ibeam", "vertical-text"],
    "Handwriting": ["pencil", "draft"],
    "NO":        ["not-allowed", "crossed_circle", "forbidden", "no-drop", "dnd-none", "circle"],
    "SizeNS":    ["size_ver", "ns-resize", "sb_v_double_arrow", "v_double_arrow",
                  "n-resize", "s-resize", "double_arrow", "row-resize", "top_side", "bottom_side"],
    "SizeWE":    ["size_hor", "ew-resize", "sb_h_double_arrow", "h_double_arrow",
                  "e-resize", "w-resize", "col-resize", "left_side", "right_side"],
    "SizeNWSE":  ["size_fdiag", "nwse-resize", "nw-resize", "se-resize",
                  "top_left_corner", "bottom_right_corner"],
    "SizeNESW":  ["size_bdiag", "nesw-resize", "ne-resize", "sw-resize",
                  "top_right_corner", "bottom_left_corner", "fd_double_arrow", "bd_double_arrow"],
    "SizeAll":   ["size_all", "move", "fleur", "all-scroll", "closedhand", "grabbing", "dnd-move"],
    "UpArrow":   ["up_arrow", "center_ptr", "sb_up_arrow"],
    "Hand":      ["pointer", "hand", "hand1", "hand2", "pointing_hand",
                  "openhand", "grab", "dnd-copy", "copy", "alias", "link"],
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
            curlib.write_ani(ani, blobs, 0, 0))
    write_inf(out)
    return out


def write_inf(out):
    strings = 'CUR_DIR      = "%s"\nSCHEME_NAME  = "%s"' % (THEME, THEME)
    slot_strings = "\n".join('%-12s = "%s"' % (role, fn) for role, fn in WIN_SLOTS)
    reg_val = ",".join("%%10%%\\%%CUR_DIR%%\\%%%s%%" % role for role, _ in WIN_SLOTS)
    copy = "\n".join('"%s"' % fn for _, fn in WIN_SLOTS) + '\n"Arrow_Down.cur"'
    inf = f""";  {THEME} - cursor scheme installer
;  Right-click this file, choose "Install", then pick "{THEME}" in
;  Settings > Bluetooth & devices > Mouse > Additional mouse settings > Pointers.

[Version]
signature="$CHICAGO$"

[DefaultInstall]
CopyFiles = Scheme.Cur
AddReg    = Scheme.Reg

[DestinationDirs]
Scheme.Cur = 10,"%CUR_DIR%"

[Scheme.Reg]
HKCU,"Control Panel\\Cursors\\Schemes","%SCHEME_NAME%",,"{reg_val}"

[Scheme.Cur]
{copy}

[Strings]
{strings}

{slot_strings}
"""
    open(os.path.join(out, "Install.inf"), "w", newline="\r\n").write(inf)


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
                frames, rates = H.anim_frames(role, size)
                hx, hy = _scale_hot(role, size)
                for img, rate in zip(frames, rates):
                    imgs.append(_pack_ximage(size, img, hx, hy, _jiffies_ms(rate)))
        else:
            for size in SIZES:
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
        "crisp at 32-256px, 60 fps\nInherits=Adwaita\n" % THEME)
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


def build_deb(linux_dir, aliases, packages):
    os.makedirs(packages, exist_ok=True)
    mtime = int(time.time())
    root = "usr/share/icons/" + THEME
    entries = _linux_entries(linux_dir, aliases, root)
    total = sum(len(d) for _, d, _, _ in entries if d)
    md5 = ["%s  %s" % (hashlib.md5(d).hexdigest(), arc)
           for arc, d, _, link in entries if link is None]
    data_tar = _tar_gz(entries, mtime)
    control = (f"Package: {PKG}\nVersion: {VERSION}\nArchitecture: all\n"
               f"Maintainer: {THEME} <noreply@localhost>\nInstalled-Size: {max(1,total//1024)}\n"
               f"Section: x11\nPriority: optional\n"
               f"Description: {THEME} cursor theme\n"
               f" Chrome Glass remaster: original pixels, crisp edges, 32-256px, 60 fps.\n")
    postinst = ("#!/bin/sh\nset -e\ncommand -v update-icon-caches >/dev/null 2>&1 && "
                "update-icon-caches /usr/share/icons/'%s' || true\nexit 0\n" % THEME)
    ctl = _tar_gz([("control", control.encode(), 0o644, None),
                   ("md5sums", ("\n".join(md5) + "\n").encode(), 0o644, None),
                   ("postinst", postinst.encode(), 0o755, None)], mtime)
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
MAC_CURSORS = [
    ("com.apple.coregraphics.Arrow", "Arrow", False),
    ("com.apple.coregraphics.IBeam", "IBeam", False),
    ("com.apple.coregraphics.Move", "SizeAll", False),
    ("com.apple.coregraphics.Wait", "Wait", True),
    ("com.apple.cursor.3", "Cross", False),        # crosshair
    ("com.apple.cursor.13", "Hand", False),        # pointing hand
]
MAC_SCALES = [1, 2, 5]                             # points x scale = pixels


def _cape_strip(name, animated, scale):
    """Vertical film strip (Mousecape layout) of all frames at one scale."""
    size = 32 * scale
    if animated:
        frames, _ = H.anim_frames(name, size)
    else:
        frames = [H.frame_image(name, 0, size)]
    strip = Image.new("RGBA", (size, size * len(frames)), (0, 0, 0, 0))
    for i, f in enumerate(frames):
        strip.alpha_composite(f, (0, i * size))
    buf = io.BytesIO()
    strip.save(buf, "PNG")
    return buf.getvalue(), len(frames)


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
        "CapeVersion": float(VERSION.rsplit(".", 1)[0]),
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
            z.write(os.path.join(win_dir, fn), THEME + "/" + fn)
    tpath = os.path.join(packages, "ChromeGlassRemastered-linux.tar.gz")
    entries = _linux_entries(linux_dir, aliases, THEME)
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
    order = ["Arrow", "Hand", "Help", "IBeam", "Cross", "SizeAll", "SizeNS", "SizeWE",
             "SizeNWSE", "SizeNESW", "UpArrow", "Arrow_Down", "Pin", "Person",
             "Handwriting", "NO", "Wait", "AppStarting"]
    cell, pad, cols = 96, 16, 6
    rows = (len(order) + cols - 1) // cols
    sheet = Image.new("RGBA", (pad + cols * (cell + pad), pad + rows * (cell + pad + 14)), (255, 255, 255, 255))
    d = ImageDraw.Draw(sheet)
    for i, name in enumerate(order):
        if name in ANIM:
            img = H.frame_image(name, 2, cell)
        else:
            img = static_image(name, cell)
        r, c = divmod(i, cols); x = pad + c * (cell + pad); y = pad + r * (cell + pad + 14)
        sheet.alpha_composite(_onbg(img), (x, y)); d.text((x, y + cell + 1), name, fill=(60, 60, 60))
    sheet.convert("RGB").save(os.path.join(HERE, "preview.png"))


def _pad(img, box):
    c = Image.new("RGBA", (box, box), (0, 0, 0, 0))
    c.alpha_composite(img, ((box - img.size[0]) // 2, (box - img.size[1]) // 2))
    return c


def _gif_frame(rgba, bg=(248, 248, 250)):
    flat = Image.new("RGB", rgba.size, bg); flat.paste(rgba, (0, 0), rgba)
    return flat.quantize(colors=256, method=Image.MEDIANCUT, dither=Image.NONE)


def build_animations():
    assets = os.path.join(HERE, "assets")
    if os.path.exists(assets): shutil.rmtree(assets)
    os.makedirs(assets)
    disp = 128
    for name in ANIM:
        frames, rates = H.anim_frames(name, disp)
        # previews loop: cap the author's freeze-forever at 2 s
        durs = [min(_jiffies_ms(r), 2000) for r in rates]
        rgba = [_pad(f, disp + 32) for f in frames]
        rgba[0].save(os.path.join(assets, name + ".webp"), save_all=True,
                     append_images=rgba[1:], duration=durs, loop=0, lossless=True, method=6)
        gif = [_gif_frame(f) for f in rgba]
        gif[0].save(os.path.join(assets, name + ".gif"), save_all=True,
                    append_images=gif[1:], duration=durs, loop=0, disposal=2, optimize=True)
    # combined strip at 60 fps
    box, gap = 128, 12
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
                  append_images=strip[1:], duration=17, loop=0, lossless=True, method=6)
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
    """assets/comparison.png: what a 4K/HiDPI screen actually shows -
    the 2006 bitmap stretched by the OS vs the remaster's native detail."""
    cell, pad, top = 256, 28, 64
    pairs = [("Arrow", 0), ("UpArrow", 0), ("Wait", 2)]
    W = pad + len(pairs) * 2 * (cell + pad) + pad
    sheet = Image.new("RGBA", (W, top + cell + pad + 12), (250, 250, 252, 255))
    d = ImageDraw.Draw(sheet)
    f_big, f_small = _font(26), _font(19)
    d.text((pad, 14), "On a HiDPI / 4K display (large pointer size):",
           fill=(20, 20, 24), font=f_big)
    for i, (name, idx) in enumerate(pairs):
        x0 = pad + i * 2 * (cell + pad)
        orig = H.frame_image(name, idx, 32).resize((cell, cell), Image.NEAREST)
        new = H.frame_image(name, idx, 256)
        sheet.alpha_composite(_onbg(orig), (x0, top))
        sheet.alpha_composite(_onbg(new), (x0 + cell + pad, top))
        d.text((x0 + 4, top + cell + 4), "2006: 32 px stretched",
               fill=(150, 40, 40), font=f_small)
        d.text((x0 + cell + pad + 4, top + cell + 4), "Remastered: native 256 px",
               fill=(30, 110, 50), font=f_small)
    sheet.convert("RGB").save(os.path.join(assets, "comparison.png"))


def check_inf(win):
    """Every filename referenced by Install.inf must exist next to it."""
    import re
    inf = open(os.path.join(win, "Install.inf"), encoding="utf-8").read()
    referenced = set(re.findall(r'"([\w\-]+\.(?:cur|ani))"', inf))
    missing = [f for f in referenced if not os.path.exists(os.path.join(win, f))]
    if missing:
        raise SystemExit("Install.inf references missing files: %s" % ", ".join(missing))
    for must in ("Pin.cur", "Person.cur"):
        if must not in referenced:
            raise SystemExit("Install.inf lost the %s slot" % must)


def _med_alpha(img):
    a = np.asarray(img)[..., 3].astype(float)
    vis = a > 0.25 * a.max()
    return float(np.median(a[vis])) if vis.any() else 0.0


def _sat(img):
    arr = np.asarray(img).astype(float)
    return H._mean_sat(arr[..., :3], arr[..., 3])


def check_metrics():
    """Superiority metrics vs the original frames; drift prints a WARN."""
    warns = 0
    for name in H.STATIC + ANIM:
        n = len(H.BY_NAME[name]["frames"])
        for idx in range(n):
            o = H.frame_image(name, idx, 32)
            h = H.frame_image(name, idx, 128)
            da = (_med_alpha(h) - _med_alpha(o)) / max(_med_alpha(o), 1e-6) * 100
            so, sh = _sat(o), _sat(h)
            sat_ok = (so <= 1e-6 or -2 <= (sh - so) / max(so, 1e-6) * 100 <= 12
                      or abs(sh - so) <= 0.02)
            if abs(da) > 8:
                print(f"  WARN {name}[{idx}]: median alpha drift {da:+.1f}% (>8%)")
                warns += 1
            if not sat_ok:
                print(f"  WARN {name}[{idx}]: saturation {so:.3f} -> {sh:.3f}")
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
    win = build_windows(dist)
    check_inf(win)
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
    print("Linux   :", os.path.relpath(lin, HERE), "-", len(os.listdir(os.path.join(lin, "cursors"))), "cursor files")
    print("Debian  :", os.path.relpath(deb, HERE))
    print("Zips    :", os.path.relpath(zpath, HERE), "+", os.path.relpath(tpath, HERE))
    print("Preview : preview.png   Animations: assets/*.webp")
    print("Checks:")
    check_packages(win)
    warns = check_metrics()
    print("  metrics: %s" % ("all within tolerance" if not warns else f"{warns} warning(s)"))


if __name__ == "__main__":
    main()

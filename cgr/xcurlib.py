"""Xcursor reader, symmetric with cgr.build's _pack_ximage/_xcursor writer,
and the premultiply step the two share.

A reader and not a writer: nothing in this repo needs to rebuild an Xcursor
file from parsed parts, only to check that the bytes build_linux() already
wrote match the canonical render.
"""
import struct
import numpy as np
from PIL import Image

MAGIC = 0x72756358
IMG_TYPE = 0xfffd0002


def premultiply(img):
    """RGBA image -> HxWx4 uint8 with RGB multiplied by alpha, the form an
    Xcursor file stores. X Render and Wayland's ARGB8888 blend premultiplied,
    and xcursorgen writes it so (premultiply_data); straight RGB read that way
    comes out over-bright wherever the glass is translucent. Rounds like
    xcursorgen's div_255."""
    arr = np.asarray(img.convert("RGBA"), dtype=np.uint32)
    x = arr[..., :3] * arr[..., 3:4] + 0x80
    out = arr.copy()
    out[..., :3] = (x + (x >> 8)) >> 8
    return out.astype(np.uint8)


def read_xcursor(data):
    """.xcursor bytes -> [{"size": int, "hx": int, "hy": int, "delay": int,
    "img": PIL.Image RGBA}, ...], one per image chunk, TOC order. The pixels
    are returned as stored, premultiplied; compare them against premultiply()
    of the canonical render."""
    magic, _header_size, _version, ntoc = struct.unpack_from("<IIII", data, 0)
    if magic != MAGIC:
        raise ValueError("not an Xcursor file (bad magic)")
    out = []
    for i in range(ntoc):
        toc_type, _subtype, pos = struct.unpack_from("<III", data, 16 + i * 12)
        if toc_type != IMG_TYPE:
            continue
        (_chdr_size, chtype, size, _cver, w, h, xhot, yhot, delay
         ) = struct.unpack_from("<9I", data, pos)
        if chtype != IMG_TYPE:
            raise ValueError("TOC/chunk type mismatch at 0x%x" % pos)
        n = w * h
        raw = np.frombuffer(data, dtype="<u4", count=n, offset=pos + 36).reshape(h, w)
        a = (raw >> 24) & 0xFF
        r = (raw >> 16) & 0xFF
        g = (raw >> 8) & 0xFF
        b = raw & 0xFF
        img = Image.fromarray(np.dstack([r, g, b, a]).astype(np.uint8), "RGBA")
        out.append({"size": size, "hx": xhot, "hy": yhot, "delay": delay, "img": img})
    return out

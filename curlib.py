"""Reusable .cur/.ani read/write helpers for the cursor upscale pipeline.

Frames are represented as dicts: {"img": PIL.Image RGBA, "hx": int, "hy": int}.
"""
import struct, io
from PIL import Image


def _decode_dib_entry(data):
    """Decode one ICONDIRENTRY image blob (PNG or BMP/DIB) -> (RGBA Image)."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return Image.open(io.BytesIO(data)).convert("RGBA")
    # BITMAPINFOHEADER
    hsize, w, h2, planes, bpp = struct.unpack_from("<IiiHH", data, 0)
    comp = struct.unpack_from("<I", data, 16)[0]
    real_h = h2 // 2
    # color table size
    ncolors = struct.unpack_from("<I", data, 32)[0]
    if ncolors == 0 and bpp < 24:
        ncolors = 1 << bpp
    palette_off = hsize
    palette = data[palette_off:palette_off + ncolors * 4]
    row_xor = ((w * bpp + 31) // 32) * 4
    xor_off = palette_off + ncolors * 4
    xor = data[xor_off:xor_off + row_xor * real_h]
    and_row = ((w + 31) // 32) * 4
    and_off = xor_off + row_xor * real_h
    andmask = data[and_off:and_off + and_row * real_h]

    out = Image.new("RGBA", (w, real_h))
    px = out.load()
    for y in range(real_h):
        sy = real_h - 1 - y  # bottom-up
        for x in range(w):
            if bpp == 32:
                b, g, r, a = xor[sy * row_xor + x * 4: sy * row_xor + x * 4 + 4]
            elif bpp == 24:
                b, g, r = xor[sy * row_xor + x * 3: sy * row_xor + x * 3 + 3]
                a = 0
            elif bpp == 8:
                idx = xor[sy * row_xor + x]
                b, g, r, _ = palette[idx * 4: idx * 4 + 4]
                a = 0
            elif bpp in (4, 1):
                bitpos = x * bpp
                byte = xor[sy * row_xor + bitpos // 8]
                if bpp == 4:
                    idx = (byte >> (4 if x % 2 == 0 else 0)) & 0xF
                else:
                    idx = (byte >> (7 - x % 8)) & 1
                b, g, r, _ = palette[idx * 4: idx * 4 + 4]
                a = 0
            else:
                b = g = r = a = 0
            # AND mask: bit set -> transparent
            mbyte = andmask[sy * and_row + x // 8]
            mbit = (mbyte >> (7 - x % 8)) & 1
            if mbit:
                a = 0
            elif bpp != 32:
                a = 255
            elif a == 0:
                # 32bpp but no alpha info at all -> opaque where mask says visible
                a = 255
            px[x, y] = (r, g, b, a)
    return out


def read_cur(data):
    """Parse .cur bytes -> list of frame dicts (one per embedded image)."""
    reserved, itype, count = struct.unpack_from("<HHH", data, 0)
    frames = []
    for i in range(count):
        off = 6 + i * 16
        w = data[off] or 256
        h = data[off + 1] or 256
        hx, hy = struct.unpack_from("<HH", data, off + 4)
        size, imgoff = struct.unpack_from("<II", data, off + 8)
        img = _decode_dib_entry(data[imgoff:imgoff + size])
        frames.append({"img": img, "hx": hx, "hy": hy})
    return frames


def _encode_dib(img):
    """RGBA Image -> DIB blob (BITMAPINFOHEADER + 32bpp BGRA XOR + AND mask)."""
    w, h = img.size
    try:
        import numpy as np
        arr = np.asarray(img.convert("RGBA"), dtype=np.uint8)[::-1]  # bottom-up
        xor_b = arr[..., [2, 1, 0, 3]].tobytes()
        and_row = ((w + 31) // 32) * 4
        bits = np.zeros((h, and_row * 8), dtype=np.uint8)
        bits[:, :w] = arr[..., 3] == 0
        and_b = np.packbits(bits, axis=1).tobytes()
        hdr = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0,
                          len(xor_b) + len(and_b), 0, 0, 0, 0)
        return hdr + xor_b + and_b
    except ImportError:
        pass
    px = img.load()
    row_xor = w * 4
    xor = bytearray()
    for y in range(h - 1, -1, -1):
        for x in range(w):
            r, g, b, a = px[x, y]
            xor += bytes((b, g, r, a))
    and_row = ((w + 31) // 32) * 4
    andmask = bytearray()
    for y in range(h - 1, -1, -1):
        rowbits = bytearray(and_row)
        for x in range(w):
            a = px[x, y][3]
            if a == 0:
                rowbits[x // 8] |= (1 << (7 - x % 8))
        andmask += rowbits
    hdr = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0,
                      len(xor) + len(andmask), 0, 0, 0, 0)
    return bytes(hdr) + bytes(xor) + bytes(andmask)


def write_cur(frames):
    """frames: list of dicts -> .cur bytes (multi-image)."""
    n = len(frames)
    blobs = [_encode_dib(f["img"]) for f in frames]
    out = bytearray(struct.pack("<HHH", 0, 2, n))
    offset = 6 + n * 16
    for f, blob in zip(frames, blobs):
        w, h = f["img"].size
        out += bytes((w if w < 256 else 0, h if h < 256 else 0, 0, 0))
        out += struct.pack("<HHII", f["hx"], f["hy"], len(blob), offset)
        offset += len(blob)
    for blob in blobs:
        out += blob
    return bytes(out)


def read_ani(data):
    """Parse .ani -> dict with header fields, rates, seqs, and per-frame .cur bytes."""
    assert data[:4] == b"RIFF" and data[8:12] == b"ACON"
    pos = 12
    anih = None
    rates = None
    seqs = None
    frames = []
    end = struct.unpack_from("<I", data, 4)[0] + 8
    while pos < end - 8:
        cid = data[pos:pos + 4]
        csize = struct.unpack_from("<I", data, pos + 4)[0]
        body = data[pos + 8:pos + 8 + csize]
        if cid == b"anih":
            anih = body
        elif cid == b"rate":
            rates = list(struct.unpack_from("<%dI" % (csize // 4), body, 0))
        elif cid == b"seq ":
            seqs = list(struct.unpack_from("<%dI" % (csize // 4), body, 0))
        elif cid == b"LIST" and body[:4] == b"fram":
            p = 4
            while p < len(body) - 8:
                sid = body[p:p + 4]
                ssize = struct.unpack_from("<I", body, p + 4)[0]
                if sid == b"icon":
                    frames.append(body[p + 8:p + 8 + ssize])
                p += 8 + ssize + (ssize & 1)
        pos += 8 + csize + (csize & 1)
    return {"anih": anih, "rates": rates, "seqs": seqs, "frames": frames}


def _chunk(cid, body):
    out = cid + struct.pack("<I", len(body)) + body
    if len(body) & 1:
        out += b"\x00"
    return out


def write_ani(ani, new_frames_bytes, new_w, new_h):
    """Rebuild .ani with new frame .cur bytes and updated width/height in anih."""
    anih = bytearray(ani["anih"])
    # anih layout: cbSize,nFrames,nSteps,iWidth,iHeight,iBitCount,nPlanes,iDispRate,bfAttributes
    struct.pack_into("<ii", anih, 12, new_w, new_h)
    body = _chunk(b"anih", bytes(anih))
    if ani["rates"] is not None:
        body += _chunk(b"rate", struct.pack("<%dI" % len(ani["rates"]), *ani["rates"]))
    if ani["seqs"] is not None:
        body += _chunk(b"seq ", struct.pack("<%dI" % len(ani["seqs"]), *ani["seqs"]))
    fram = b"fram"
    for fb in new_frames_bytes:
        fram += _chunk(b"icon", fb)
    body += _chunk(b"LIST", fram)
    return b"RIFF" + struct.pack("<I", len(b"ACON") + len(body)) + b"ACON" + body

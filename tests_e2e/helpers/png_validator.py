"""Pure-Python stdlib PNG validator and synthetic PNG builder (zero PIL/numpy dependency)."""

from __future__ import annotations

import math
import struct
from typing import Callable
import zlib

PNG_SIG = b"\x89PNG\r\n\x1a\n"
BG_RGB = (0xDC, 0xE2, 0xE8)


def inspect_png_bytes(data: bytes, sample_stride: int = 2) -> dict:
    """Validate PNG structure/CRC32/scanlines and compute deterministic image quality metrics."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise ValueError("PNG input must be bytes-like")
    buf = bytes(data)
    if len(buf) < 33 or buf[:8] != PNG_SIG:
        raise ValueError("Invalid PNG magic signature")

    pos = 8
    ihdr = None
    idats: list[bytes] = []
    saw_iend = False

    while pos + 8 <= len(buf):
        length, ctype = struct.unpack(">I4s", buf[pos : pos + 8])
        body_end = pos + 8 + length
        if body_end + 4 > len(buf):
            raise ValueError(f"Truncated PNG chunk {ctype!r}")
        (expected_crc,) = struct.unpack(">I", buf[body_end : body_end + 4])
        actual_crc = zlib.crc32(buf[pos + 4 : body_end]) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise ValueError(f"CRC32 mismatch in chunk {ctype!r}")
        body = buf[pos + 8 : body_end]
        if ctype == b"IHDR":
            if length != 13 or ihdr is not None:
                raise ValueError("Invalid IHDR chunk")
            ihdr = struct.unpack(">IIBBBBB", body)
        elif ctype == b"IDAT":
            idats.append(body)
        elif ctype == b"IEND":
            if length != 0:
                raise ValueError("Non-empty IEND chunk")
            saw_iend = True
            break
        pos = body_end + 4

    if ihdr is None or not idats or not saw_iend:
        raise ValueError("Missing required IHDR/IDAT/IEND chunks")

    w, h, bit_depth, color_type, comp, filt, interlace = ihdr
    if w <= 0 or h <= 0 or bit_depth not in (8, 16) or comp != 0 or filt != 0 or interlace != 0:
        raise ValueError(f"Unsupported PNG IHDR parameters: {ihdr}")

    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if channels is None:
        raise ValueError(f"Invalid PNG color_type {color_type}")

    try:
        raw = zlib.decompress(b"".join(idats))
    except zlib.error as exc:
        raise ValueError(f"Corrupt PNG deflate stream: {exc}") from exc

    bpp = channels * (bit_depth // 8)
    row_bytes = w * bpp
    stride = 1 + row_bytes
    if len(raw) != h * stride:
        raise ValueError(f"Inflated scanline byte count {len(raw)} != {h * stride}")

    prev = bytearray(row_bytes)
    cur = bytearray(row_bytes)
    r_s = g_s = b_s = 0.0
    r_s2 = g_s2 = b_s2 = 0.0
    n = 0
    counts: dict[tuple[int, int, int], int] = {}
    third_totals = [0, 0, 0]
    third_fg = [0, 0, 0]
    step_x = max(1, sample_stride) * bpp

    for y in range(h):
        off = y * stride
        ft = raw[off]
        scan = raw[off + 1 : off + stride]
        if ft == 0:
            cur[:] = scan
        elif ft == 1:
            for i in range(row_bytes):
                cur[i] = (scan[i] + (cur[i - bpp] if i >= bpp else 0)) & 0xFF
        elif ft == 2:
            for i in range(row_bytes):
                cur[i] = (scan[i] + prev[i]) & 0xFF
        elif ft == 3:
            for i in range(row_bytes):
                left = cur[i - bpp] if i >= bpp else 0
                cur[i] = (scan[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ft == 4:
            for i in range(row_bytes):
                a = cur[i - bpp] if i >= bpp else 0
                b_p = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b_p - c
                pa, pb, pc = abs(p - a), abs(p - b_p), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b_p if pb <= pc else c)
                cur[i] = (scan[i] + pr) & 0xFF
        else:
            raise ValueError(f"Invalid PNG scanline filter {ft} at row {y}")

        if y % max(1, sample_stride) == 0:
            c_g = 1 if channels >= 3 else 0
            c_b = 2 if channels >= 3 else 0
            if bit_depth == 16:
                c_g *= 2
                c_b *= 2
            for px in range(0, row_bytes, step_x):
                x_coord = px // bpp
                rv, gv, bv = cur[px], cur[px + c_g], cur[px + c_b]
                r_s += rv
                g_s += gv
                b_s += bv
                r_s2 += rv * rv
                g_s2 += gv * gv
                b_s2 += bv * bv
                k = (rv >> 3, gv >> 3, bv >> 3)
                counts[k] = counts.get(k, 0) + 1
                t_idx = min(2, (x_coord * 3) // max(1, w))
                third_totals[t_idx] += 1
                if (
                    abs(rv - BG_RGB[0]) > 10
                    or abs(gv - BG_RGB[1]) > 10
                    or abs(bv - BG_RGB[2]) > 10
                ):
                    third_fg[t_idx] += 1
                n += 1
        prev, cur = cur, prev

    def _std(s: float, s2: float) -> float:
        if n <= 0:
            return 0.0
        return math.sqrt(max(0.0, s2 / n - (s / n) ** 2))

    entropy = -sum((c / n) * math.log2(c / n) for c in counts.values()) if n > 0 else 0.0
    fg_ratios = [
        (third_fg[i] / third_totals[i]) if third_totals[i] > 0 else 0.0 for i in range(3)
    ]
    return {
        "width": w,
        "height": h,
        "bit_depth": bit_depth,
        "color_type": color_type,
        "rgb_std": (_std(r_s, r_s2), _std(g_s, g_s2), _std(b_s, b_s2)),
        "unique_5bit": len(counts),
        "entropy_bits": entropy,
        "third_foreground_ratio": fg_ratios,
    }


def _png_chunk(ctype: bytes, body: bytes) -> bytes:
    crc = zlib.crc32(ctype + body) & 0xFFFFFFFF
    return struct.pack(">I4s", len(body), ctype) + body + struct.pack(">I", crc)


def make_synthetic_png(
    width: int,
    height: int,
    pixel_fn: Callable[[int, int], tuple[int, int, int, int]] | None = None,
) -> bytes:
    """Build a valid 8-bit RGBA PNG in memory using pure stdlib."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    rows = bytearray()
    for y in range(height):
        rows.append(0)  # Filter type 0 (None)
        for x in range(width):
            if pixel_fn is not None:
                r, g, b, a = pixel_fn(x, y)
            else:
                r = (x * 37 + y * 13) & 0xFF
                g = (x * 17 + y * 53 + 80) & 0xFF
                b = (x * 71 + y * 29 + 140) & 0xFF
                a = 255
            rows.extend((r & 0xFF, g & 0xFF, b & 0xFF, a & 0xFF))
    idat = zlib.compress(bytes(rows), level=1)
    return PNG_SIG + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", idat) + _png_chunk(b"IEND", b"")


def validate_render_quality(
    metrics: dict,
    *,
    is_overview: bool = False,
    min_width: int = 1200,
    min_height: int = 720,
) -> list[str]:
    """Check F12 resolution, colour variance, palette diversity, entropy, and framing."""
    errors: list[str] = []
    req_w = 1600 if is_overview else min_width
    req_h = 1000 if is_overview else min_height
    if metrics.get("width", 0) < req_w or metrics.get("height", 0) < req_h:
        errors.append(
            f"Resolution {metrics.get('width')}x{metrics.get('height')} < {req_w}x{req_h}"
        )
    rgb_std = metrics.get("rgb_std") or (0.0, 0.0, 0.0)
    min_std_req = 12.0 if is_overview else 10.0
    if min(rgb_std) < min_std_req:
        errors.append(f"min(rgb_std)={min(rgb_std):.2f} < {min_std_req}")
    min_u5 = 400 if is_overview else 200
    if metrics.get("unique_5bit", 0) < min_u5:
        errors.append(f"unique_5bit={metrics.get('unique_5bit')} < {min_u5}")
    min_ent = 2.5 if is_overview else 2.0
    if metrics.get("entropy_bits", 0.0) < min_ent:
        errors.append(f"entropy_bits={metrics.get('entropy_bits', 0.0):.3f} < {min_ent}")
    if is_overview:
        thirds = metrics.get("third_foreground_ratio") or [0.0, 0.0, 0.0]
        if len(thirds) < 3 or thirds[0] < 0.12 or thirds[1] < 0.20 or thirds[2] < 0.12:
            errors.append(f"Overview horizontal third foreground framing out of bounds: {thirds}")
    return errors

"""Tiny PNG previews for a template tile. Stdlib only, no brand art."""

from __future__ import annotations

import struct
import zlib


def _chunk(tag: bytes, data: bytes) -> bytes:
    """One PNG chunk: length, tag, data, crc."""
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def png(width: int, height: int, paint) -> bytes:
    """An RGB PNG. `paint(x, y)` returns a 3-byte colour."""
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            row.extend(paint(x, y))
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)
    return b"".join([
        b"\x89PNG\r\n\x1a\n",
        _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
        _chunk(b"IDAT", raw),
        _chunk(b"IEND", b""),
    ])


def _rgb(hex_colour: str) -> bytes:
    """Three bytes from a six-digit hex colour."""
    value = int(hex_colour, 16)
    return bytes(((value >> 16) & 255, (value >> 8) & 255, value & 255))


def variant_thumb(variant: str) -> bytes:
    """A 320x180 stand-in of the shell: a field, a bar, a title block."""
    if variant == "dark":
        field, ink, bar = _rgb("1C1C1F"), _rgb("F4F4F2"), _rgb("5C6B73")
    elif variant == "light":
        field, ink, bar = _rgb("F7F7F5"), _rgb("1C1C1F"), _rgb("5C6B73")
    else:
        raise ValueError(f"unknown variant {variant}")

    def paint(x: int, y: int) -> bytes:
        """One pixel: a bar, a title rule, or the field."""
        if y < 14:
            return bar
        if 78 <= y <= 96 and 36 <= x <= 220:
            return ink
        if 108 <= y <= 116 and 36 <= x <= 160:
            return bar
        return field

    return png(320, 180, paint)

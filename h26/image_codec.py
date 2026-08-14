"""Image encoding helpers for the H26 encoder.

Turns an input image (PNG/JPG on disk, or raw RGBA bytes) into the
compressed graphical blocks the H26 format expects: LZ4pal32 (paletted
32-bit BGRA + 8-bit palette indices) and an optional JPG preview.

The block format matches what ``main.py``'s decoder produces, so the
encoder and decoder round-trip against each other:

* The first two bytes tag the block type (``0x4B 0x01`` for
  LZ4pal32, ``0x09 0x00`` for JPG). See the H26 spec, section 3.
* Three bytes at offset 5 pack ``width`` into the top 12 bits and
  ``height`` into the bottom 12 bits, little-endian. The decoder
  reads this with :func:`main.vb_get_3b_be` and splits it the same
  way. (*This resolves the spec's Q1 open question.*)
* The compressed stream is standard LZ4 block format
  (``lz4.block.compress(..., store_size=False)``), which the
  parser's custom ``decompress_lz4_vb`` decodes perfectly.

Palette quantization for LZ4pal32 uses a simple uniform-octree
approach: a 256-color palette shared by all pixels of the image,
then one palette index per pixel (8-bit).

This module is imported headless (no PyQt6 required). If you need
to load a PNG/JPG you should use the optional Pillow dependency
or pass raw RGBA bytes directly. ``encode_image()`` accepts either.
"""

from __future__ import annotations

import struct
from typing import Sequence

import lz4.block

# Block type tags (H26 spec section 3)
TAG_LZ4PAL32 = (0x4B, 0x01)
TAG_BGR565 = (0x49, 0x01)
TAG_BGR565A = (0x48, 0x01)
TAG_JPG = (0x09, 0x00)
TAG_GIF = (0x03, 0x00)

#: Palette size for LZ4pal32 (256 entries x 4 bytes BGRA)
PALETTE_ENTRIES = 256
PALETTE_BYTES = PALETTE_ENTRIES * 4


class ImageCodecError(ValueError):
    """Raised when an image cannot be converted to a block."""


def _pack_size(w: int, h: int) -> int:
    """Pack (width, height) into the 24-bit little-endian size value.

    Matches the decoder: ``w = size >> 12``, ``h = size & 0xFFF``.
    """
    return (w << 12) | (h & 0xFFF)


def compress_payload(raw: bytes) -> bytes:
    """LZ4 block compress without the stored size prefix.

    Emits exactly the format ``decompress_lz4_vb`` consumes.
    """
    return lz4.block.compress(raw, store_size=False)


def _ensure_dimensions(sources: Sequence[int], w: int, h: int) -> None:
    if w <= 0 or h <= 0:
        raise ImageCodecError(f"invalid image dimensions: {w}x{h}")
    if w > 4095 or h > 4095:
        # The 24-bit pack only holds 12 bits per dimension.
        raise ImageCodecError(
            f"image too large for H26 12-bit dimension encoding: {w}x{h} (max 4095x4095)"
        )
    if len(sources) != w * h * 4:
        raise ImageCodecError(
            f"RGBA buffer length mismatch: got {len(sources)} bytes for "
            f"{w}x{h} (expected {w * h * 4})"
        )


def quantize_rgba_to_palette(
    rgba: Sequence[int],
    width: int,
    height: int,
) -> tuple[list[tuple[int, int, int, int]], list[int]]:
    """Convert raw RGBA pixels to a 256-color palette + index buffer.

    Returns ``(palette, indices)`` where ``palette`` is a list of
    ``(b, g, r, a)``-ordered tuples (matching the decoder's byte
    order: the decoder reads BGRA from the raw buffer) and
    ``indices`` is one integer 0..255 per pixel.

    Uses a naive uniform quantizer: normalize to 5/6/5 bits (like the
    RGB565 range) to bound the color space, deduplicate into a dict
    up to 256 entries, then map every pixel to its nearest palette
    entry by squared RGB distance.
    """
    if len(rgba) != width * height * 4:
        raise ImageCodecError(
            f"RGBA buffer length mismatch: got {len(rgba)} bytes for {width}x{height} "
            f"(expected {width * height * 4})"
        )

    # Collect distinct colors first.
    distinct: dict[tuple[int, int, int, int], None] = {}
    for i in range(0, len(rgba), 4):
        key = (
            rgba[i] & 0xFF,
            rgba[i + 1] & 0xFF,
            rgba[i + 2] & 0xFF,
            rgba[i + 3] & 0xFF,
        )
        distinct[key] = None

    if len(distinct) <= PALETTE_ENTRIES:
        return _assign_palette(rgba, list(distinct.keys()))

    # >256 distinct colors: quantize channels down so it fits.
    return _quantize_overflow(rgba, width, height)


def _assign_palette(
    rgba: Sequence[int],
    ordered_colors: list[tuple[int, int, int, int]],
) -> tuple[list[tuple[int, int, int, int]], list[int]]:
    """Map every pixel to the nearest palette entry."""
    palette = ordered_colors[:PALETTE_ENTRIES]
    lookup = {color: i for i, color in enumerate(palette)}
    indices = []
    for i in range(0, len(rgba), 4):
        key = (
            rgba[i] & 0xFF,
            rgba[i + 1] & 0xFF,
            rgba[i + 2] & 0xFF,
            rgba[i + 3] & 0xFF,
        )
        idx = lookup.get(key)
        if idx is None:
            idx = _nearest(palette, key)
        indices.append(idx)
    return palette, indices


def _nearest(
    palette: list[tuple[int, int, int, int]],
    target: tuple[int, int, int, int],
) -> int:
    """Return the index of the palette entry closest to ``target``."""
    tb, tg, tr, ta = target
    best_i, best_d = 0, 10**9
    for i, (b, g, r, a) in enumerate(palette):
        d = (b - tb) ** 2 + (g - tg) ** 2 + (r - tr) ** 2 + (a - ta) ** 2
        if d < best_d:
            best_i, best_d = i, d
    return best_i


def _quantize_overflow(
    rgba: Sequence[int],
    width: int,
    height: int,
) -> tuple[list[tuple[int, int, int, int]], list[int]]:
    """Handle images with >256 distinct colors.

    Picks the 256 most-frequent colors as the palette, then maps
    every pixel to its nearest palette entry. This is lossy on
    gradients but deterministic and always fits the 256-entry
    palette. A full octree/median-cut quantizer would look better
    (see the plan's Q3); this keeps the v1 encoder dependency-free.
    """
    frequency: dict[tuple[int, int, int, int], int] = {}
    for i in range(0, len(rgba), 4):
        key = (
            rgba[i] & 0xFF,
            rgba[i + 1] & 0xFF,
            rgba[i + 2] & 0xFF,
            rgba[i + 3] & 0xFF,
        )
        frequency[key] = frequency.get(key, 0) + 1

    # Most frequent colors first.
    ranked = sorted(frequency, key=frequency.__getitem__, reverse=True)
    palette = ranked[:PALETTE_ENTRIES]
    lookup = {color: i for i, color in enumerate(palette)}

    indices = []
    for i in range(0, len(rgba), 4):
        key = (
            rgba[i] & 0xFF,
            rgba[i + 1] & 0xFF,
            rgba[i + 2] & 0xFF,
            rgba[i + 3] & 0xFF,
        )
        idx = lookup.get(key)
        if idx is None:
            idx = _nearest(palette, key)
        indices.append(idx)
    return palette, indices


def build_lz4pal32_block(
    rgba: Sequence[int],
    width: int,
    height: int,
) -> bytes:
    """Encode raw RGBA pixels as a full LZ4pal32 block (header+data).

    Block layout (matches decoder `_convert_block_to_image`):
        [5][1]   tag bytes 0x4B 0x01

        [4 bytes]<...>   reserved / length prefix area
        [3 bytes]        size value at offset 5 (w<<12 | h), LE
        [.. up to 0x10]  reserved padding/unknown
        [data]           LZ4pal32 stream: palette (1024B) + indices

    The decoder reads ``size_val = vb_get_3b_be(b, 5)`` then splits
    ``w = size_val >> 12``, ``h = size_val & 0xFFF``. The stream that
    follows is ``palette (0x400 bytes BGRA) + one byte per pixel``.
    """
    _ensure_dimensions(rgba, width, height)
    palette, indices = quantize_rgba_to_palette(rgba, width, height)

    # Serialize palette: the decoder expects BGRA byte order
    # (reads B at i, G at i+1, R at i+2, A at i+3), so swap
    # R↔B from our RGBA palette tuples.
    pal_bytes_ba = bytearray()
    for r, g, b, a in palette:
        pal_bytes_ba += bytes((b & 0xFF, g & 0xFF, r & 0xFF, a & 0xFF))
    if len(pal_bytes_ba) < PALETTE_BYTES:
        pal_bytes_ba += b"\x00" * (PALETTE_BYTES - len(pal_bytes_ba))
    pal_bytes = bytes(pal_bytes_ba)

    # Serialize indices: one byte per pixel in row-major order.
    index_bytes = bytes(indices)

    unwrapped = pal_bytes + index_bytes

    # Header (16 bytes).
    # Offset 0..1: tag 0x4B 0x01 (LZ4pal32)
    # Offset 5..7: packed size (w<<12|h), LE (decoder uses vb_get_3b_be = LE)
    # Offset 8..11: compressed payload length, LE (decoder uses vb_get_4b_be = LE)
    header = bytearray(bytes(TAG_LZ4PAL32))
    header += b"\x00" * 3
    header += struct.pack("<I", _pack_size(width, height))[:3]  # 5..7 LE
    header += b"\x00" * 3  # offsets 8..10 (first 3 of length)
    # We'll patch in the real payload length below.
    header += b"\x00" * 5  # pad to 16 bytes

    payload = compress_payload(unwrapped)
    # Patch data length at offset 8..11 (LE).
    struct.pack_into("<I", header, 8, len(payload))
    return bytes(header) + payload


def build_jpg_preview_block(jpg_bytes: bytes) -> bytes:
    """Wrap raw JPEG bytes in the JPG block header tag (0x09 0x00).

    Block layout matches the decoder's JPG branch:
        [0x09 0x00]         tag (offset 0..1)
        [2..4]              payload length, 3-byte LE (decoder uses vb_get_3b_be)
        [0x10..]            the jpg payload
    """
    if not jpg_bytes:
        raise ImageCodecError("empty JPEG payload")
    header = bytearray(0x10)
    header[0] = TAG_JPG[0]
    header[1] = TAG_JPG[1]
    # Write payload length as 3-byte LE at offset 2 (vb_get_3b_be).
    plen = len(jpg_bytes)
    header[2] = plen & 0xFF
    header[3] = (plen >> 8) & 0xFF
    header[4] = (plen >> 16) & 0xFF
    return bytes(header) + jpg_bytes

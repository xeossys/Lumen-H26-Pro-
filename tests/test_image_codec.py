"""
Image codec tests (h26/image_codec.py).

Covers quantization, block header encoding, LZ4 round-trip
against the real decoder in main.py, and JPG preview block.
"""

from __future__ import annotations

import pytest

from h26.image_codec import (
    PALETTE_ENTRIES,
    TAG_JPG,
    TAG_LZ4PAL32,
    ImageCodecError,
    _pack_size,
    build_jpg_preview_block,
    build_lz4pal32_block,
    quantize_rgba_to_palette,
)
from h26.utils import decompress_lz4_vb, vb_get_3b_be


def test_pack_size():
    """_pack_size encodes w<<12 | h in 3 bytes."""
    assert _pack_size(0, 0) == 0
    assert _pack_size(1, 1) == (1 << 12) | 1
    assert _pack_size(0xFFF, 0xFFF) == (0xFFF << 12) | 0xFFF
    assert _pack_size(240, 240) == (240 << 12) | 240


def test_quantize_simple_4_colors():
    """4 distinct colors → 4 palette entries."""
    # 2x2 image: red, green, blue, white
    rgba = bytes([255, 0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 255, 255, 255, 255, 255])
    pal, indices = quantize_rgba_to_palette(rgba, 2, 2)
    assert len(pal) == 4
    assert len(indices) == 4
    # Each index must be valid
    for idx in indices:
        assert 0 <= idx < len(pal)


def test_quantize_single_color():
    """All pixels same color → 1 palette entry, all index 0."""
    rgba = bytes([128, 64, 32, 255] * 4)
    pal, indices = quantize_rgba_to_palette(rgba, 2, 2)
    assert len(pal) == 1
    assert all(i == 0 for i in indices)


def test_quantize_overflow():
    """More than 256 unique colors should not crash."""
    pixels = []
    for i in range(257):
        pixels.extend([i & 0xFF, (i >> 8) & 0xFF, 0, 255])
    rgba = bytes(pixels)
    pal, indices = quantize_rgba_to_palette(rgba, 257, 1)
    assert len(pal) <= PALETTE_ENTRIES
    assert len(indices) == 257


def test_quantize_rgba_mismatch():
    with pytest.raises(ImageCodecError):
        quantize_rgba_to_palette(b"\x00" * 10, 2, 2)


def test_build_lz4pal32_block_header():
    """LZ4pal32 block has correct tag and size header."""
    rgba = bytes([255, 0, 0, 255] * 4)
    block = build_lz4pal32_block(rgba, 2, 2)
    assert block[0] == TAG_LZ4PAL32[0]
    assert block[1] == TAG_LZ4PAL32[1]
    size_val = vb_get_3b_be(block, 5)
    assert (size_val >> 12) == 2  # width
    assert (size_val & 0xFFF) == 2  # height


def test_build_lz4pal32_roundtrip_decoder():
    """Encoder output is decompressible by main.py's decoder."""
    rgba = bytes([255, 0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 255, 255, 255, 255, 255])
    block = build_lz4pal32_block(rgba, 2, 2)
    payload = block[0x10:]
    unpacked = decompress_lz4_vb(payload)
    assert len(unpacked) >= 0x400 + 4


def test_build_jpg_preview_block():
    """JPG preview block has correct tag."""
    jpg = b"\xff\xd8\xff\xe0" + b"\x00" * 100
    block = build_jpg_preview_block(jpg)
    assert block[0] == TAG_JPG[0]
    assert block[1] == TAG_JPG[1]


def test_build_jpg_preview_empty():
    with pytest.raises(ImageCodecError):
        build_jpg_preview_block(b"")


def test_build_lz4pal32_invalid_dimensions():
    with pytest.raises(ImageCodecError):
        build_lz4pal32_block(b"\x00" * 4, 0, 1)

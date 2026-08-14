"""
Test image replacement round-trip.

Compiles a project with a custom image and verifies the output.
"""

from __future__ import annotations

import struct
import tempfile
from pathlib import Path

from h26.encoder import compile
from h26.image_codec import (
    PALETTE_BYTES,
    build_lz4pal32_block,
    quantize_rgba_to_palette,
)
from h26.project import (
    FrameItem,
    ImageAsset,
    Layout,
    Project,
)


def _make_tiny_png(path: Path, width: int = 4, height: int = 4, color=(0, 255, 0)):
    """Write a minimal valid PNG file."""

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        import binascii

        c = chunk_type + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", binascii.crc32(c) & 0xFFFFFFFF)

    import zlib

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b""
    for _ in range(height):
        raw += b"\x00" + bytes(color) * width
    compressed = zlib.compress(raw)
    with open(path, "wb") as f:
        f.write(sig)
        f.write(_chunk(b"IHDR", ihdr))
        f.write(_chunk(b"IDAT", compressed))
        f.write(_chunk(b"IEND", b""))


def test_image_swap_compile(main_module, tmp_path):
    """Compile a project with a custom image and verify the output."""
    img_path = tmp_path / "custom.png"
    _make_tiny_png(img_path)
    asset = ImageAsset(name="custom", source_path=str(img_path), width=4, height=4)
    proj = Project(
        name="swap_test",
        images=[asset],
        layout=Layout(
            x=0,
            y=0,
            children=[FrameItem(x=0, y=0, image_name="custom")],
        ),
    )
    result = compile(proj)
    assert len(result) > 0
    assert result[:4] == b"Sb@*"

    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
        tmp.write(result)
        tmp_path2 = tmp.name
    try:
        an = main_module.H26WatchfaceAnalyzer()
        assert an.load_file(tmp_path2)
        graphical = [
            b
            for b in an.blocks
            if b.b_type
            in (
                main_module.BlockType.LZ4pal32,
                main_module.BlockType.JPG,
            )
        ]
        assert len(graphical) > 0
    finally:
        Path(tmp_path2).unlink(missing_ok=True)


def test_quantize_and_build_block():
    """Quantize RGBA and build an LZ4pal32 block."""
    rgba = bytes([128, 64, 32, 255]) * 16  # 4x4
    pal, indices = quantize_rgba_to_palette(rgba, 4, 4)
    assert len(pal) <= PALETTE_BYTES
    assert len(indices) == 16

    block = build_lz4pal32_block(rgba, 4, 4)
    assert block[0] == 0x4B
    assert block[1] == 0x01

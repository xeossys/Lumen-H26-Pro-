"""
Integration test for h26.encoder.compile().

Tests the full pipeline: Project → compile → parse → verify.
"""

from __future__ import annotations

import struct
import tempfile
from pathlib import Path

import pytest

from h26.encoder import EncoderError, compile
from h26.project import (
    AnimationItem,
    FrameItem,
    HandItem,
    ImageAsset,
    Layout,
    Project,
    ProjectSchemaError,
)


def _make_tiny_png(path: Path, width: int = 2, height: int = 2):
    """Write a minimal valid PNG file (solid red)."""

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", _crc32(c))

    def _crc32(data: bytes) -> int:
        import binascii

        return binascii.crc32(data) & 0xFFFFFFFF

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    # Raw pixel data: each row has filter byte (0) + RGB pixels
    raw = b""
    for _ in range(height):
        raw += b"\x00" + b"\xff\x00\x00" * width
    import zlib

    compressed = zlib.compress(raw)
    with open(path, "wb") as f:
        f.write(sig)
        f.write(_chunk(b"IHDR", ihdr))
        f.write(_chunk(b"IDAT", compressed))
        f.write(_chunk(b"IEND", b""))


def _project_with_image(tmp_path: Path, name: str = "test"):
    """Create a project with a real image file."""
    img_path = tmp_path / "bg.png"
    _make_tiny_png(img_path)
    bg = ImageAsset(name="bg", source_path=str(img_path), width=2, height=2)
    return Project(
        name=name,
        images=[bg],
        layout=Layout(x=0, y=0, children=[FrameItem(x=0, y=0, image_name="bg")]),
    )


def _compile_and_parse(project, main_module):
    """Compile a project and parse the result with main.py."""
    result = compile(project)
    assert len(result) > 0
    assert result[:4] == b"Sb@*"

    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
        tmp.write(result)
        tmp_path = tmp.name
    try:
        an = main_module.H26WatchfaceAnalyzer()
        assert an.load_file(tmp_path), "Failed to load compiled output"
        return result, an
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def test_compile_minimal(main_module, tmp_path):
    """Minimal project compiles and parses correctly."""
    proj = _project_with_image(tmp_path)
    result, an = _compile_and_parse(proj, main_module)
    assert len(result) > 0
    assert len(an.ui_items) > 0


def test_compile_header_fields(main_module, tmp_path):
    """Compiled output has correct header fields."""
    proj = _project_with_image(tmp_path, "header_test")
    result, an = _compile_and_parse(proj, main_module)
    assert an.preview_offset > 0
    assert an.l2 > 0


def test_compile_with_hand(main_module, tmp_path):
    """Project with a hand compiles correctly."""
    img_path = tmp_path / "hour.png"
    _make_tiny_png(img_path)
    hour = ImageAsset(name="hour_hand", source_path=str(img_path), width=2, height=2)
    proj = Project(
        name="test_hand",
        images=[hour],
        layout=Layout(
            x=0,
            y=0,
            children=[
                HandItem(
                    x=120,
                    y=120,
                    image_name="hour_hand",
                    pivot_x=1,
                    pivot_y=1,
                ),
            ],
        ),
    )
    result, an = _compile_and_parse(proj, main_module)
    hands = [it for it in an.ui_items if it.item_type == 0x0F]
    assert len(hands) == 1


def test_compile_with_animation(main_module, tmp_path):
    """Project with animation compiles correctly."""
    img1 = tmp_path / "f1.png"
    img2 = tmp_path / "f2.png"
    _make_tiny_png(img1)
    _make_tiny_png(img2)
    frame1 = ImageAsset(name="frame1", source_path=str(img1), width=2, height=2)
    frame2 = ImageAsset(name="frame2", source_path=str(img2), width=2, height=2)
    proj = Project(
        name="test_anim",
        images=[frame1, frame2],
        layout=Layout(
            x=0,
            y=0,
            children=[
                AnimationItem(
                    x=0,
                    y=0,
                    frame_names=["frame1", "frame2"],
                ),
            ],
        ),
    )
    result, an = _compile_and_parse(proj, main_module)
    anims = [it for it in an.ui_items if it.item_type == 0x14]
    assert len(anims) == 1


def test_compile_missing_image(main_module):
    """Compile with missing image reference — encoder skips the item."""
    proj = Project(
        name="test_missing",
        images=[],
        layout=Layout(
            x=0,
            y=0,
            children=[FrameItem(x=0, y=0, image_name="nonexistent")],
        ),
    )
    # Encoder silently skips items with missing images
    result, an = _compile_and_parse(proj, main_module)
    assert len(result) > 0


def test_compile_empty_layout(main_module):
    """Project with empty layout raises EncoderError."""
    proj = Project(
        name="empty",
        images=[],
        layout=Layout(x=0, y=0, children=[]),
    )
    with pytest.raises(EncoderError):
        compile(proj)


def test_compile_roundtrip_serialize(main_module, tmp_path):
    """Compiled output round-trips through serialize()."""
    proj = _project_with_image(tmp_path, "roundtrip")
    result, an = _compile_and_parse(proj, main_module)
    serialized = an.serialize()
    assert serialized == result

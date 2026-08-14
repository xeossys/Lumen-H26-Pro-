"""
Image codec tests (h26/image_codec.py).

Covers quantization, block header encoding, LZ4 round-trip
against the real decoder in main.py, and JPG preview block.

Run with::

    python3 tests/test_image_codec.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# We need main.py's decompress_lz4_vb to verify the encoder output.
import types

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

qt = types.ModuleType("PyQt6.QtCore")
qt.Qt = type("Qt", (), {})
qt.QRect = type("QRect", (), {})
qt.QTimer = type("QTimer", (), {})
qt.QTime = type("QTime", (), {})
qtg = types.ModuleType("PyQt6.QtGui")


class QColor:
    def __init__(self, *a):
        pass

    def rgba(self):
        return 0


class QImage:
    class Format:
        Format_ARGB32 = 0
        Format_RGB16 = 1
        Format_Indexed8 = 2

    def __init__(self, *a, **k):
        pass

    def loadFromData(self, *a, **k):
        return False

    def setPixel(self, *a):
        pass

    def width(self):
        return 0

    def height(self):
        return 0


class QPainter:
    pass


class QPen:
    pass


class QFont:
    pass


qtg.QColor = QColor
qtg.QImage = QImage
qtg.QPainter = QPainter
qtg.QPen = QPen
qtg.QFont = QFont
qtw = types.ModuleType("PyQt6.QtWidgets")
for n in [
    "QApplication",
    "QMainWindow",
    "QWidget",
    "QVBoxLayout",
    "QHBoxLayout",
    "QPushButton",
    "QLabel",
    "QFileDialog",
    "QTreeWidget",
    "QTreeWidgetItem",
    "QTableWidget",
    "QTableWidgetItem",
    "QSplitter",
    "QTextEdit",
    "QHeaderView",
    "QTabWidget",
    "QStatusBar",
    "QSizePolicy",
]:
    setattr(qtw, n, type(n, (), {}))
p = types.ModuleType("PyQt6")
p.QtCore = qt
p.QtGui = qtg
p.QtWidgets = qtw
sys.modules["PyQt6"] = p
sys.modules["PyQt6.QtCore"] = qt
sys.modules["PyQt6.QtGui"] = qtg
sys.modules["PyQt6.QtWidgets"] = qtw

main_path = Path(__file__).resolve().parent.parent / "main.py"
spec = importlib.util.spec_from_file_location("main", main_path)
assert spec is not None and spec.loader is not None
main = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(main)
except Exception as exc:
    print(f"[warn] main.py import warning: {exc}")

decompress_lz4_vb = main.decompress_lz4_vb
vb_get_3b_be = main.vb_get_3b_be


# ---- Helpers -----------------------------------------------------------


def make_rgba_grid(w: int, h: int, colors: list[tuple[int, int, int, int]]) -> bytes:
    """Build a flat RGBA buffer: cycle through `colors` row by row."""
    out = bytearray()
    for y in range(h):
        for x in range(w):
            c = colors[(y * w + x) % len(colors)]
            out += bytes(c)
    return bytes(out)


# ---- Tests -------------------------------------------------------------


def test_pack_size():
    """width=410 (0x19A), height=502 (0x1F6) packs into 24 bits."""
    size = _pack_size(410, 502)
    assert size == (410 << 12) | 502
    assert size >> 12 == 410
    assert size & 0xFFF == 502
    # LE 3-byte encoding
    le = (size).to_bytes(3, "little")
    assert len(le) == 3
    # Round-trip back
    unpacked = int.from_bytes(le, "little")
    assert unpacked >> 12 == 410
    assert unpacked & 0xFFF == 502


def test_quantize_simple_4_colors():
    """A 4x4 grid with 4 distinct RGBA colors → 4-entry palette."""
    rgba = make_rgba_grid(
        4,
        4,
        [
            (255, 0, 0, 255),  # red   → BGRA = (0,0,255,255)
            (0, 255, 0, 255),  # green → BGRA = (0,255,0,255)
            (0, 0, 255, 255),  # blue  → BGRA = (255,0,0,255)
            (255, 255, 0, 255),  # cyan  → BGRA = (0,255,255,255)
        ],
    )
    palette, indices = quantize_rgba_to_palette(rgba, 4, 4)
    assert len(palette) == 4
    assert len(indices) == 16
    # Every index must be in range
    assert all(0 <= i < len(palette) for i in indices)


def test_quantize_single_color():
    """A solid-color image → 1-entry palette."""
    rgba = bytes([128, 64, 32, 255]) * 9  # 3x3
    palette, indices = quantize_rgba_to_palette(rgba, 3, 3)
    assert len(palette) == 1
    assert all(i == 0 for i in indices)


def test_quantize_overflow():
    """An image with >256 distinct colors → frequency-based palette."""
    # Generate 300 distinct colors.
    rgba = bytearray()
    for i in range(300):
        rgba += bytes([i & 0xFF, (i >> 1) & 0xFF, (i >> 2) & 0xFF, 255])
    # Pad to 300 pixels (each pixel = 4 bytes).
    palette, indices = quantize_rgba_to_palette(bytes(rgba), 10, 30)
    assert len(palette) <= PALETTE_ENTRIES
    assert len(indices) == 300
    assert all(0 <= i < len(palette) for i in indices)


def test_quantize_rgba_mismatch():
    """Buffer length mismatch → ImageCodecError."""
    try:
        quantize_rgba_to_palette(bytes(10), 3, 3)
        assert False, "expected ImageCodecError"
    except ImageCodecError as e:
        assert "mismatch" in str(e)


def test_build_lz4pal32_block_header():
    """Block header: tag + size encoding matches decoder expectations."""
    rgba = make_rgba_grid(4, 4, [(255, 0, 0, 255), (0, 255, 0, 255)])
    block = build_lz4pal32_block(rgba, 4, 4)
    assert block[0] == TAG_LZ4PAL32[0]
    assert block[1] == TAG_LZ4PAL32[1]
    assert len(block) >= 0x10
    # Size bytes at offset 5..7 decode to w=4, h=4
    size_val = vb_get_3b_be(block, 5)
    assert size_val >> 12 == 4
    assert size_val & 0xFFF == 4


def test_build_lz4pal32_roundtrip_decoder():
    """Encoder output is decompressible by main.py's decoder.

    This is the critical compatibility test: the LZ4 stream produced
    by lz4.block.compress(store_size=False) must be readable by the
    hand-rolled decompress_lz4_vb in main.py, and the palette +
    indices round-trip perfectly.
    """
    w, h = 8, 8
    rgba = make_rgba_grid(
        w,
        h,
        [
            (255, 0, 0, 255),  # red
            (0, 255, 0, 255),  # green
            (0, 0, 255, 255),  # blue
            (128, 128, 128, 255),  # gray
        ],
    )
    block = build_lz4pal32_block(rgba, w, h)
    assert len(block) > 0x10

    # Decompress the payload (everything after the 16-byte header).
    payload = block[0x10:]
    unpacked = decompress_lz4_vb(payload)
    assert len(unpacked) > 0x400, f"unpacked too short: {len(unpacked)}"

    # First 0x400 bytes = palette (256 × 4 BGRA).
    raw_palette = unpacked[:0x400]
    palette = []
    for i in range(0, 0x400, 4):
        b, g, r, a = raw_palette[i], raw_palette[i + 1], raw_palette[i + 2], raw_palette[i + 3]
        palette.append((b, g, r, a))

    # Remaining bytes = indices, one per pixel.
    index_buf = unpacked[0x400:]
    assert len(index_buf) >= w * h, (
        f"index buffer too short: got {len(index_buf)}, expected {w * h}"
    )

    # Reconstruct pixels and verify they match the original.
    for y in range(h):
        for x in range(w):
            src_idx = (y * w + x) * 4
            orig_rgba = (rgba[src_idx], rgba[src_idx + 1], rgba[src_idx + 2], rgba[src_idx + 3])
            pal_idx = index_buf[y * w + x]
            assert pal_idx < len(palette), f"pal_idx {pal_idx} out of range"
            b, g, r, a = palette[pal_idx]
            # BGRA palette entry → the original was (R, G, B, A).
            decoded_rgba = (r, g, b, a)
            # Exact match for ≤256 distinct colors.
            assert decoded_rgba == orig_rgba, (
                f"pixel ({x},{y}): expected {orig_rgba}, got {decoded_rgba}"
            )


def test_build_jpg_preview_block():
    """JPG preview block: tag at start, payload at offset 0x10."""
    jpg_data = b"\xff\xd8\xff\xe0" + b"\x00" * 50  # fake JPEG
    block = build_jpg_preview_block(jpg_data)
    assert block[0] == TAG_JPG[0]
    assert block[1] == TAG_JPG[1]
    assert block[0x10:] == jpg_data
    assert len(block) == 0x10 + len(jpg_data)


def test_build_jpg_preview_empty():
    """Empty JPEG payload → ImageCodecError."""
    try:
        build_jpg_preview_block(b"")
        assert False, "expected ImageCodecError"
    except ImageCodecError as e:
        assert "empty" in str(e)


def test_build_lz4pal32_invalid_dimensions():
    """Invalid or oversized dimensions → ImageCodecError."""
    rgba = b"\x00" * 4
    for w, h in [(0, 1), (1, 0), (-1, 1), (4096, 1), (1, 5000)]:
        try:
            build_lz4pal32_block(rgba, w, h)
            assert False, f"expected ImageCodecError for {w}x{h}"
        except (ImageCodecError, ValueError):
            pass


def main_runner():
    tests = [
        test_pack_size,
        test_quantize_simple_4_colors,
        test_quantize_single_color,
        test_quantize_overflow,
        test_quantize_rgba_mismatch,
        test_build_lz4pal32_block_header,
        test_build_lz4pal32_roundtrip_decoder,
        test_build_jpg_preview_block,
        test_build_jpg_preview_empty,
        test_build_lz4pal32_invalid_dimensions,
    ]
    failures = []
    for fn in tests:
        try:
            fn()
            print(f"[ok] {fn.__name__}")
        except AssertionError as e:
            failures.append((fn.__name__, str(e)))
            print(f"[FAIL] {fn.__name__}: {e}")
        except Exception as e:
            failures.append((fn.__name__, repr(e)))
            print(f"[ERROR] {fn.__name__}: {e!r}")
    if failures:
        print(f"\n{len(failures)} test(s) failed")
        sys.exit(1)
    print("\nALL IMAGE CODEC TESTS PASSED")


if __name__ == "__main__":
    main_runner()

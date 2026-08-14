"""
Integration test for h26.encoder.compile().

Tests the full pipeline: Project → compile → parse → verify.
The compiled output must be parseable by main.py's analyzer and
produce the correct UI items and block structure.

Run with::

    python3 tests/test_compile.py
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from h26.encoder import EncoderError, compile  # noqa: E402
from h26.image_codec import (  # noqa: E402
    TAG_LZ4PAL32,
    build_lz4pal32_block,
    compress_payload,
)
from h26.project import (  # noqa: E402
    AnimationItem,
    FrameItem,
    HandItem,
    ImageAsset,
    Layout,
    Project,
)

# PyQt6 stub for main.py parser.
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


qtg.QColor = QColor
qtg.QImage = QImage
qtg.QPainter = type("QPainter", (), {})
qtg.QPen = type("QPen", (), {})
qtg.QFont = type("QFont", (), {})
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


# ---- Helpers -----------------------------------------------------------


def _make_test_image(path: Path, w: int, h: int) -> None:
    """Create a small RGBA PNG for testing."""
    from PIL import Image

    img = Image.new("RGBA", (w, h), (255, 0, 0, 255))
    # Add some variety so the palette has >1 color.
    for y in range(h):
        for x in range(w):
            if (x + y) % 2 == 0:
                img.putpixel((x, y), (0, 255, 0, 255))
    img.save(str(path))


def _parse_compiled(data: bytes) -> main.H26WatchfaceAnalyzer:
    """Parse compiled bytes with main.py's analyzer."""
    an = main.H26WatchfaceAnalyzer()
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        ok = an.load_file(tmp_path)
        assert ok, "analyzer.load_file returned False"
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    return an


# ---- Tests -------------------------------------------------------------


def test_compile_minimal():
    """Compile a project with 1 image + 1 layout + 1 frame → valid .bin."""
    with tempfile.TemporaryDirectory() as td:
        img_path = Path(td) / "bg.png"
        _make_test_image(img_path, 8, 8)

        project = Project(
            name="test_minimal",
            canvas_width=8,
            canvas_height=8,
            images=[ImageAsset(name="bg", source_path=str(img_path), width=8, height=8)],
            layout=Layout(children=[FrameItem(x=0, y=0, image_name="bg")]),
        )

        result = compile(project)
        assert len(result) > 0x40, f"output too short: {len(result)}"

        # Verify magic header.
        assert result[:4] == b"Sb@*"

        # Parse with the real analyzer.
        an = _parse_compiled(result)
        assert len(an.ui_items) >= 2  # layout + frame
        assert an.ui_items[0].item_type == 0x00  # layout
        assert an.ui_items[1].item_type == 0x01  # frame


def test_compile_header_fields():
    """Verify header fields are correctly patched."""
    with tempfile.TemporaryDirectory() as td:
        img_path = Path(td) / "bg.png"
        _make_test_image(img_path, 8, 8)

        project = Project(
            name="test_header",
            images=[ImageAsset(name="bg", source_path=str(img_path), width=8, height=8)],
            layout=Layout(children=[FrameItem(x=0, y=0, image_name="bg")]),
        )

        result = compile(project)

        # Preview offset (0x0C) should be 0x40.
        preview_offset = int.from_bytes(result[0x0C:0x10], "big")
        assert preview_offset == 0x40

        # l3 (0x14) should be preview_offset + preview_length.
        l3 = int.from_bytes(result[0x14:0x18], "big")
        assert l3 > preview_offset

        # l2 (0x1C) should be l3 + l3_length.
        l3_length = int.from_bytes(result[0x18:0x1C], "big")
        l2 = int.from_bytes(result[0x1C:0x20], "big")
        assert l2 == l3 + l3_length


def test_compile_with_hand():
    """Compile a project with a hand item (Type 0x0F)."""
    with tempfile.TemporaryDirectory() as td:
        img_path = Path(td) / "hour.png"
        _make_test_image(img_path, 4, 16)

        project = Project(
            name="test_hand",
            images=[ImageAsset(name="hour", source_path=str(img_path), width=4, height=16)],
            layout=Layout(
                children=[
                    HandItem(x=120, y=120, image_name="hour", pivot_x=2, pivot_y=14),
                ]
            ),
        )

        result = compile(project)
        an = _parse_compiled(result)

        # Layout + hand.
        assert len(an.ui_items) >= 2
        hand = [it for it in an.ui_items if it.item_type == 0x0F]
        assert len(hand) == 1
        assert hand[0].x == 120
        assert hand[0].y == 120
        # Pivot values (data_values[0], data_values[1]) should be 2, 14.
        assert hand[0].data_values[0] == 2
        assert hand[0].data_values[1] == 14


def test_compile_with_animation():
    """Compile a project with an animation item (Type 0x14)."""
    with tempfile.TemporaryDirectory() as td:
        frames = []
        assets = []
        for i in range(3):
            fp = Path(td) / f"f{i}.png"
            _make_test_image(fp, 4, 4)
            frames.append(f"f{i}")
            assets.append(ImageAsset(name=f"f{i}", source_path=str(fp), width=4, height=4))

        project = Project(
            name="test_anim",
            images=assets,
            layout=Layout(
                children=[
                    AnimationItem(x=10, y=20, frame_names=frames),
                ]
            ),
        )

        result = compile(project)
        an = _parse_compiled(result)

        anims = [it for it in an.ui_items if it.item_type == 0x14]
        assert len(anims) == 1


def test_compile_missing_image():
    """Missing image file → EncoderError."""
    project = Project(
        name="test_missing",
        images=[ImageAsset(name="nope", source_path="/nonexistent.png", width=4, height=4)],
        layout=Layout(children=[FrameItem(x=0, y=0, image_name="nope")]),
    )
    try:
        compile(project)
        assert False, "expected EncoderError"
    except EncoderError as e:
        assert "not found" in str(e)


def test_compile_empty_layout():
    """Empty layout → EncoderError."""
    project = Project(name="test_empty", layout=Layout(children=[]))
    try:
        compile(project)
        assert False, "expected EncoderError"
    except EncoderError as e:
        assert "no children" in str(e)


def test_compile_roundtrip_serialize():
    """Compiled output round-trips through serialize()."""
    with tempfile.TemporaryDirectory() as td:
        img_path = Path(td) / "bg.png"
        _make_test_image(img_path, 8, 8)

        project = Project(
            name="test_rt",
            images=[ImageAsset(name="bg", source_path=str(img_path), width=8, height=8)],
            layout=Layout(children=[FrameItem(x=0, y=0, image_name="bg")]),
        )

        result = compile(project)
        an = _parse_compiled(result)
        out = an.serialize()
        assert out == result, f"serialize() not byte-perfect: in={len(result)} out={len(out)}"


# ---- Runner ------------------------------------------------------------


def main_runner():
    tests = [
        test_compile_minimal,
        test_compile_header_fields,
        test_compile_with_hand,
        test_compile_with_animation,
        test_compile_missing_image,
        test_compile_empty_layout,
        test_compile_roundtrip_serialize,
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
    print("\nALL COMPILE INTEGRATION TESTS PASSED")


if __name__ == "__main__":
    main_runner()

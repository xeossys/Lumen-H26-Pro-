"""
Shared test helpers and pytest fixtures.

The H26 analyzer code in main.py imports PyQt6 at module top — even
when we only want the pure-Python parsing primitives. This conftest
provides a minimal PyQt6 stub so the test suite can exercise the
parser without requiring PyQt6 to be installed.

Why a stub and not just installing PyQt6?
* PyQt6 pulls in Qt binaries (~50MB)
* The CI matrix doesn't need a real GUI to validate parsing
* Tests should fail for the right reason (parser bug), not for
  environment reasons (Qt not installed)

If PyQt6 is already importable we use it; otherwise we install a
minimal stub. The stub implements only the methods the analyzer
actually calls during parsing.
"""

from __future__ import annotations

import importlib.util
import struct
import sys
import tempfile
import types
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAIN_PY = Path(__file__).resolve().parent.parent / "main.py"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


# ---------------------------------------------------------------------------
# PyQt6 stub
# ---------------------------------------------------------------------------


def install_pyqt6_stub() -> None:
    """Install a minimal PyQt6 stub into sys.modules.

    Idempotent: safe to call multiple times.
    """
    if "PyQt6" in sys.modules and hasattr(sys.modules["PyQt6"], "_is_h26_stub"):
        return
    if "PyQt6" in sys.modules:
        # Real PyQt6 is available; nothing to do.
        return

    qt = types.ModuleType("PyQt6.QtCore")
    qt.Qt = type("Qt", (), {})
    qt.QRect = type("QRect", (), {})
    qt.QTimer = type("QTimer", (), {})
    qt.QTime = type("QTime", (), {})

    qtg = types.ModuleType("PyQt6.QtGui")

    class QColor:
        def __init__(self, r=0, g=0, b=0, a=255):
            self._rgba = (a << 24) | (r << 16) | (g << 8) | b

        def rgba(self):
            return self._rgba

        def getRgb(self):
            return (
                (self._rgba >> 16) & 0xFF,
                (self._rgba >> 8) & 0xFF,
                self._rgba & 0xFF,
                (self._rgba >> 24) & 0xFF,
            )

    class QImage:
        class Format:
            Format_ARGB32 = 0
            Format_RGB16 = 1
            Format_Indexed8 = 2

        def __init__(self, *args):
            if len(args) == 3:
                # QImage(w, h, fmt)
                self._w, self._h, _fmt = args
                self._data = None
            elif len(args) == 4:
                # QImage(data, w, h, fmt)
                _data, self._w, self._h, _fmt = args
                self._data = _data
            else:
                self._w = 0
                self._h = 0
                self._data = None
            self._px = {}

        def loadFromData(self, *_a, **_k):
            return False

        def setPixel(self, x, y, c):
            self._px[(x, y)] = c

        def width(self):
            return self._w

        def height(self):
            return self._h

    class QPainter:  # noqa: D401 - stub
        pass

    class QPen:  # noqa: D401 - stub
        pass

    class QFont:  # noqa: D401 - stub
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
        "QSplitter",
        "QLabel",
        "QPushButton",
        "QTreeWidget",
        "QTreeWidgetItem",
        "QTableWidget",
        "QTableWidgetItem",
        "QHeaderView",
        "QTextEdit",
        "QTabWidget",
        "QStatusBar",
        "QFileDialog",
    ]:
        setattr(qtw, n, type(n, (), {}))

    pyqt6 = types.ModuleType("PyQt6")
    pyqt6.QtCore = qt
    pyqt6.QtGui = qtg
    pyqt6.QtWidgets = qtw
    pyqt6._is_h26_stub = True  # marker to detect our own stub

    sys.modules["PyQt6"] = pyqt6
    sys.modules["PyQt6.QtCore"] = qt
    sys.modules["PyQt6.QtGui"] = qtg
    sys.modules["PyQt6.QtWidgets"] = qtw


# ---------------------------------------------------------------------------
# Synthetic binary builder
# ---------------------------------------------------------------------------


def build_synthetic_binary() -> bytes:
    """Build a minimal-but-valid H26 binary in-memory.

    The payload exercises every parser path the spec-gap patches
    touched (Type 37 system-screen buttons, Type 47 angled fonts,
    Type 5B solid rectangles, Type 14 animations). The four UI
    items at the end are wrapped in a minimal header + a fake
    preview block so the parser can locate the UI table.

    Used by ``test_smoke.py`` and ``test_roundtrip.py`` so they
    stay in sync.
    """
    HDR_SIZE = 0x40

    def be32(v):
        return struct.pack(">I", v & 0xFFFFFFFF)

    def be32s(v):
        return struct.pack(">i", v)

    def make_ui_5x4(t, st, align, x, y):
        return be32(t) + be32(st) + be32(align) + be32s(x) + be32s(y)

    b = bytearray()
    b += b"Sb@*"
    b += b"\x00" * (0x0C - len(b))
    b += be32(HDR_SIZE)  # preview_offset
    b += b"\x00" * (0x14 - len(b))
    b += be32(HDR_SIZE)  # l3
    b += be32(0)  # l3 length
    b += be32(0)  # l2 (placeholder)
    assert len(b) == 0x20
    b += b"\x00" * (HDR_SIZE - len(b))
    JPG_BLOCK = b"\x09\x00" + b"\x00\x00\x00" + b"\x00" * (0x10 - 5)
    b += JPG_BLOCK
    L2 = len(b)

    # Type 37: button with system-screen strings (62 bytes total)
    TYPE37_PAYLOAD = be32(3) + be32s(120) + be32s(40)
    str_area = (b"WeatherScreen\x00" + b"HRScreen\x00").ljust(30, b"\x00")
    TYPE37_PAYLOAD += str_area
    item37 = make_ui_5x4(0x37, 0, 0, 10, 20) + TYPE37_PAYLOAD

    # Type 47: angled font with dX=2, dY=1 and 1 frame (40 bytes total)
    TYPE47_PAYLOAD = be32(3) + be32s(2) + be32s(1) + be32(0) + be32(0)
    item47 = make_ui_5x4(0x47, 0, 0, 5, 5) + TYPE47_PAYLOAD

    # Type 5B: solid rectangle (35 bytes total)
    TYPE5B_PAYLOAD = be32(3) + be32s(100) + be32s(50) + bytes([0xFF, 0, 0])
    item5b = make_ui_5x4(0x5B, 0, 0, 30, 30) + TYPE5B_PAYLOAD

    # Type 14: animation, 0 frames (24 bytes total)
    # 20-byte header (5*4) + 4-byte counter=2 (0 frames: 2-2=0)
    item14 = make_ui_5x4(0x14, 0x34, 0, 0, 0) + be32s(0)

    ui_table = item37 + item47 + item5b + item14
    struct.pack_into(">I", b, 0x1C, L2)
    b += ui_table
    return bytes(b)


# ---------------------------------------------------------------------------
# Module-level stub installation (runs at import time)
# ---------------------------------------------------------------------------

install_pyqt6_stub()


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def main_module():
    """Load main.py as a module (session-scoped for performance)."""
    spec = importlib.util.spec_from_file_location("main", MAIN_PY)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:
        # QApplication-using code at the bottom of main.py is
        # unreachable in tests, so this is safe to swallow.
        print(f"[warn] main.py import warning: {exc}")
    return mod


@pytest.fixture(scope="session")
def synthetic_binary():
    """Build the synthetic H26 binary once per session."""
    return build_synthetic_binary()


@pytest.fixture
def synthetic_file(synthetic_binary, tmp_path):
    """Write the synthetic binary to a temp file and return its path."""
    p = tmp_path / "synthetic.bin"
    p.write_bytes(synthetic_binary)
    return p


@pytest.fixture
def analyzer(main_module, synthetic_file):
    """Return a loaded H26WatchfaceAnalyzer from the synthetic binary."""
    an = main_module.H26WatchfaceAnalyzer()
    assert an.load_file(str(synthetic_file))
    return an


@pytest.fixture
def fixture_paths():
    """Return sorted list of all .bin fixture files."""
    if not FIXTURES_DIR.is_dir():
        return []
    return sorted(FIXTURES_DIR.glob("*.bin"))


def load_fixture(main_mod, path: Path):
    """Load a fixture file into an analyzer and return it."""
    an = main_mod.H26WatchfaceAnalyzer()
    assert an.load_file(str(path)), f"load_file returned False on {path.name}"
    return an


def reparse_bytes(main_mod, data: bytes):
    """Serialize and re-parse to verify round-trip."""
    an = main_mod.H26WatchfaceAnalyzer()
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        assert an.load_file(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    return an

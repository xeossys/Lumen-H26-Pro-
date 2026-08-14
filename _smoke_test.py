"""
Smoke test for the spec-gap patches in H26WatchfaceAnalyzer.

We synthesize a minimal-but-valid H26 watchface binary that exercises
the parser code paths we just patched (Type 37 with system-screen
strings, Type 47 with dX/dY, Type 5B with a solid color rectangle)
and confirm each item is decoded correctly.

Run with:
    cd /tmp/Lumen-H26-Pro-Encoder
    python3 _smoke_test.py
"""

import os
import struct
import sys

# We can't import the GUI-using main.py without PyQt6. Stub the PyQt6
# import path so we only get the parsing primitives.
import types

qtcore = types.ModuleType("PyQt6.QtCore")
qtcore.Qt = type("Qt", (), {})
qtcore.QRect = type("QRect", (), {})
qtcore.QTimer = type("QTimer", (), {})
qtcore.QTime = type("QTime", (), {})

qtgui = types.ModuleType("PyQt6.QtGui")


class _Stub:
    pass


qtgui.QImage = _Stub
qtgui.QPainter = _Stub
qtgui.QColor = _Stub
qtgui.QPen = _Stub
qtgui.QFont = _Stub

qtwidgets = types.ModuleType("PyQt6.QtWidgets")
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
    setattr(qtwidgets, n, _Stub)

pyqt6 = types.ModuleType("PyQt6")
pyqt6.QtCore = qtcore
pyqt6.QtGui = qtgui
pyqt6.QtWidgets = qtwidgets
sys.modules["PyQt6"] = pyqt6
sys.modules["PyQt6.QtCore"] = qtcore
sys.modules["PyQt6.QtGui"] = qtgui
sys.modules["PyQt6.QtWidgets"] = qtwidgets

# Now safe to import.
import importlib.util

spec = importlib.util.spec_from_file_location(
    "main", os.path.join(os.path.dirname(__file__), "main.py")
)
main = importlib.util.module_from_spec(spec)
# main.py runs QApplication-related code at import time? Let's check by
# trying. We pre-stubbed so it should be fine.
try:
    spec.loader.exec_module(main)
except Exception as e:
    print(f"[warn] main.py top-level import failed: {e}")
    # The QMainWindow/etc are stubbed but main.py uses QApplication at
    # the very end. As long as we don't reach the bottom of the file,
    # we're fine.

# ---- Build a synthetic H26 binary ---------------------------------------


def be32(v):
    return struct.pack(">I", v & 0xFFFFFFFF)


def be32s(v):
    return struct.pack(">i", v)


def be16(v):
    return struct.pack(">H", v & 0xFFFF)


# Header (32 bytes)
#   0x00 magic "Sb@*"
#   0x0C preview_offset (point past header for now)
#   0x14 l3 (block-with-internal-addressing offset)
#   0x18 l3 length
#   0x1C l2 (UI table offset)
HDR_SIZE = 0x40
PREVIEW_OFFSET = HDR_SIZE  # skip preview for smoke test
L3 = HDR_SIZE
L3_LEN = 0
L2_PLACEHOLDER = 0  # will fill in after we know UI table size

b = bytearray()
b += b"Sb@*"  # 0x00 magic
b += b"\x00" * (0x0C - len(b))  # pad
b += be32(PREVIEW_OFFSET)  # 0x0C preview offset
b += b"\x00" * (0x14 - len(b))
b += be32(L3)  # 0x14 l3
b += be32(L3_LEN)  # 0x18 l3 length
b += be32(L2_PLACEHOLDER)  # 0x1C l2 (UI table offset) — TBD
assert len(b) == 0x20
b += b"\x00" * (HDR_SIZE - len(b))  # pad to HDR_SIZE

# UI Table starts at L2. We'll put it after a tiny "preview" placeholder
# (a JPG block header) to exercise the parser's flow.
# Just use a single 0x09 0x00 JPG block as a fake preview (won't be
# loadable but the parser only needs the header bytes to skip it).

# ---- Fake preview block (JPG header only, parser will skip gracefully) -
JPG_BLOCK = b"\x09\x00" + b"\x00\x00\x00" + b"\x00" * (0x10 - 5)
b += JPG_BLOCK
L2 = len(b)

# ---- UI Items ----
# Build them as raw bytes then append.


def make_ui_item_5x4(t, st, align, x, y):
    """Standard 5*4 header: Type, SubType, Align, X, Y."""
    return be32(t) + be32(st) + be32(align) + be32s(x) + be32s(y)


def make_ui_item_3x4(t, st, align):
    return be32(t) + be32(st) + be32(align)


# Item 0: Type 37 (button/system screen) with full payload.
# Spec: header(5*4=20) + 4b unknown + 4b width + 4b height + 30b strings
#       = 20 + 12 + 30 = 62 bytes total
TYPE37_PAYLOAD = b""
TYPE37_PAYLOAD += be32(3)  # unknown = 3
TYPE37_PAYLOAD += be32s(120)  # width
TYPE37_PAYLOAD += be32s(40)  # height
# 30 bytes of NUL-terminated strings
str_area = b"WeatherScreen\x00"  # 14 bytes
str_area += b"HRScreen\x00"  # 10 bytes
str_area = str_area.ljust(30, b"\x00")  # pad to 30
TYPE37_PAYLOAD += str_area
item37 = make_ui_item_5x4(0x37, 0, 0, 10, 20) + TYPE37_PAYLOAD
assert len(item37) == 62, f"item37 should be 62 bytes, got {len(item37)}"

# Item 1: Type 47 (angled font) with dX=2, dY=1, then 1 frame.
TYPE47_PAYLOAD = b""
TYPE47_PAYLOAD += be32(1 + 2)  # counter = frame_count + 2 = 3
TYPE47_PAYLOAD += be32s(2)  # dX
TYPE47_PAYLOAD += be32s(1)  # dY
TYPE47_PAYLOAD += be32(0)  # frame 0 offset
TYPE47_PAYLOAD += be32(0)  # frame 0 length
item47 = make_ui_item_5x4(0x47, 0, 0, 5, 5) + TYPE47_PAYLOAD
# l1 = 32 + (count * 8) = 32 + 8 = 40 ; 20 hdr + 20 payload = 40
assert len(item47) == 40, len(item47)

# Item 2: Type 5B (solid rectangle) Width=100 Height=50 Color=blue(BGR=FF,00,00)
TYPE5B_PAYLOAD = b""
TYPE5B_PAYLOAD += be32(3)  # counter = 3
TYPE5B_PAYLOAD += be32s(100)  # width
TYPE5B_PAYLOAD += be32s(50)  # height
TYPE5B_PAYLOAD += bytes([0xFF, 0x00, 0x00])  # BGR = blue
item5b = make_ui_item_5x4(0x5B, 0, 0, 30, 30) + TYPE5B_PAYLOAD
# l1 = 32 + 3 = 35
# But our header is 5*4=20, payload is 4+4+4+3=15, total 35. l1 = 35. OK.
assert len(item5b) == 35, len(item5b)

ui_table = item37 + item47 + item5b

# Patch L2 in the header
struct.pack_into(">I", b, 0x1C, L2)

# Append UI table
b += ui_table

# ---- Now run the parser ----
an = main.H26WatchfaceAnalyzer()
an.load_file_from_bytes(bytes(b)) if hasattr(an, "load_file_from_bytes") else None

# If load_file_from_bytes doesn't exist, write to tmp and use load_file.
tmp_path = "/tmp/_smoke_h26.bin"
with open(tmp_path, "wb") as f:
    f.write(b)
ok = an.load_file(tmp_path)
assert ok, "load_file returned False"

print(f"Total UI items parsed: {len(an.ui_items)}")
print(f"wf_name: {an.wf_name!r}")
print(f"unknown_blocks: {len(an.unknown_blocks)}")

# Find each type
by_type = {it.item_type: it for it in an.ui_items}
assert 0x37 in by_type, f"Type 37 missing; got types: {sorted(by_type)}"
assert 0x47 in by_type, f"Type 47 missing; got types: {sorted(by_type)}"
assert 0x5B in by_type, f"Type 5B missing; got types: {sorted(by_type)}"

# Verify Type 37
it = by_type[0x37]
print(f"Type 37 data_values: {it.data_values}")
print(f"Type 37 system_screens: {it.system_screens}")
assert it.data_values == [3, 120, 40], it.data_values
assert it.system_screens == ["WeatherScreen", "HRScreen"], it.system_screens

# Verify Type 47
it = by_type[0x47]
print(f"Type 47 data_values (dX, dY should be first 2): {it.data_values}")
print(f"Type 47 frame_indices: {it.frame_indices}")
assert it.data_values == [2, 1], f"expected dX=2, dY=1, got {it.data_values}"
assert it.frame_indices == [0], it.frame_indices

# Verify Type 5B
it = by_type[0x5B]
print(f"Type 5B data_values: {it.data_values}")
assert it.data_values == [3, 100, 50, 0xFF, 0x00, 0x00], it.data_values

# Verify backwards-compat alias still works
assert main.vb_get_4b_signed_le is main.vb_get_4b_signed_be

print("\nALL SMOKE TESTS PASSED ✅")

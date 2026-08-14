#!/usr/bin/env python3
"""H26 Watchface CLI — compile, parse, and inspect `.bin` files.

Usage::

    # Compile a project JSON into a .bin watchface
    python3 -m h26.cli compile project.json -o watchface.bin

    # Parse a .bin and dump its structure as JSON
    python3 -m h26.cli parse watchface.bin

    # Quick summary of a .bin file
    python3 -m h26.cli info watchface.bin

    # Round-trip test: parse → serialize → compare
    python3 -m h26.cli verify watchface.bin
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _vb_get_4b_le(b: bytes, pos: int) -> int:
    """Read 4 bytes as big-endian unsigned (matches main.py's vb_get_4b_le)."""
    if pos < 0 or pos + 3 >= len(b):
        return -1
    return (b[pos] << 24) | (b[pos + 1] << 16) | (b[pos + 2] << 8) | b[pos + 3]


def _vb_get_4b_be(b: bytes, pos: int) -> int:
    """Read 4 bytes as little-endian unsigned (matches main.py's vb_get_4b_be)."""
    if pos < 0 or pos + 3 >= len(b):
        return -1
    return b[pos] | (b[pos + 1] << 8) | (b[pos + 2] << 16) | (b[pos + 3] << 24)


def _vb_get_3b_be(b: bytes, pos: int) -> int:
    """Read 3 bytes as little-endian unsigned (matches main.py's vb_get_3b_be)."""
    if pos < 0 or pos + 2 >= len(b):
        return -1
    return b[pos] | (b[pos + 1] << 8) | (b[pos + 2] << 16)


MAGIC = b"Sb@*"
TAG_NAMES = {
    (0x4B, 0x01): "LZ4pal32",
    (0x48, 0x01): "BGR565A",
    (0x49, 0x01): "BGR565",
    (0x09, 0x00): "JPG",
    (0x03, 0x00): "GIF",
}


# ---------------------------------------------------------------------------
# compile
# ---------------------------------------------------------------------------


def cmd_compile(args: argparse.Namespace) -> int:
    """Compile a project JSON file into a .bin watchface."""
    from h26.encoder import EncoderError, compile
    from h26.project import Project, ProjectSchemaError

    project_path = Path(args.project)
    if not project_path.exists():
        print(f"error: project file not found: {project_path}", file=sys.stderr)
        return 1

    try:
        text = project_path.read_text(encoding="utf-8")
        project = Project.from_json(text)
    except (ProjectSchemaError, json.JSONDecodeError) as exc:
        print(f"error: invalid project JSON: {exc}", file=sys.stderr)
        return 1

    try:
        data = compile(project)
    except EncoderError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    output = Path(args.output) if args.output else project_path.with_suffix(".bin")
    output.write_bytes(data)
    print(f"✓ Compiled {len(data):,} bytes → {output}")
    return 0


# ---------------------------------------------------------------------------
# parse
# ---------------------------------------------------------------------------


def cmd_parse(args: argparse.Namespace) -> int:
    """Parse a .bin file and dump its structure as JSON."""
    # We use a lightweight header parser (no PyQt6 needed) for the
    # JSON dump. For full UI-item parsing, use main.py directly.
    bin_path = Path(args.file)
    if not bin_path.exists():
        print(f"error: file not found: {bin_path}", file=sys.stderr)
        return 1

    b = bin_path.read_bytes()
    if len(b) < 0x20 or b[:4] != MAGIC:
        print("error: not a valid H26 file (bad magic)", file=sys.stderr)
        return 1

    preview_offset = _vb_get_4b_le(b, 0x0C)
    l3 = _vb_get_4b_le(b, 0x14)
    l3_len = _vb_get_4b_le(b, 0x18)
    l2 = _vb_get_4b_le(b, 0x1C)

    result = {
        "file": str(bin_path),
        "size": len(b),
        "header": {
            "magic": "Sb@*",
            "preview_offset": f"0x{preview_offset:X}",
            "l3": f"0x{l3:X}",
            "l3_length": f"0x{l3_len:X}",
            "l2_ui_table": f"0x{l2:X}",
        },
        "blocks": [],
    }

    # Scan graphical blocks
    pos = preview_offset
    tpos = min(len(b) - 1, l2)
    block_idx = 0
    while pos < tpos:
        if pos + 1 >= len(b):
            break
        b1, b2 = b[pos], b[pos + 1]
        tag = (b1, b2)
        tag_name = TAG_NAMES.get(tag, f"unknown_0x{b1:02X}_0x{b2:02X}")

        if tag in ((0x4B, 0x01), (0x48, 0x01), (0x49, 0x01)):
            data_len = _vb_get_4b_be(b, pos + 8)
            l1 = data_len + 0x10
            size_val = _vb_get_3b_be(b, pos + 5)
            w = size_val >> 12
            h = size_val & 0xFFF
            result["blocks"].append(
                {
                    "index": block_idx,
                    "offset": f"0x{pos:X}",
                    "type": tag_name,
                    "size": l1,
                    "width": w,
                    "height": h,
                }
            )
        elif tag == (0x09, 0x00):
            data_len = _vb_get_3b_be(b, pos + 2)
            l1 = data_len + 0x10
            result["blocks"].append(
                {
                    "index": block_idx,
                    "offset": f"0x{pos:X}",
                    "type": "JPG",
                    "size": l1,
                }
            )
        elif tag == (0x03, 0x00):
            data_len = _vb_get_3b_be(b, pos + 2)
            l1 = data_len + 0x10
            result["blocks"].append(
                {
                    "index": block_idx,
                    "offset": f"0x{pos:X}",
                    "type": "GIF",
                    "size": l1,
                }
            )
        else:
            guess = _vb_get_3b_be(b, pos + 2) + 0x10
            l1 = guess if 0x10 < guess < len(b) - pos else 1
            result["blocks"].append(
                {
                    "index": block_idx,
                    "offset": f"0x{pos:X}",
                    "type": tag_name,
                    "size": l1,
                }
            )

        block_idx += 1
        pos += l1

    # UI table summary
    ui_size = len(b) - l2
    result["ui_table"] = {
        "offset": f"0x{l2:X}",
        "size": ui_size,
    }

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------------------
# info
# ---------------------------------------------------------------------------


def cmd_info(args: argparse.Namespace) -> int:
    """Print a quick summary of a .bin file."""
    bin_path = Path(args.file)
    if not bin_path.exists():
        print(f"error: file not found: {bin_path}", file=sys.stderr)
        return 1

    b = bin_path.read_bytes()
    if len(b) < 0x20 or b[:4] != MAGIC:
        print("error: not a valid H26 file (bad magic)", file=sys.stderr)
        return 1

    preview_offset = _vb_get_4b_le(b, 0x0C)
    l3 = _vb_get_4b_le(b, 0x14)
    l3_len = _vb_get_4b_le(b, 0x18)
    l2 = _vb_get_4b_le(b, 0x1C)

    print(f"File:    {bin_path}")
    print(f"Size:    {len(b):,} bytes")
    print("Magic:   Sb@* ✓")
    print(f"Preview: 0x{preview_offset:X}")
    print(f"L3:      0x{l3:X} (len 0x{l3_len:X})")
    print(f"L2 (UI): 0x{l2:X}")

    # Count blocks
    pos = preview_offset
    tpos = min(len(b) - 1, l2)
    counts: dict[str, int] = {}
    while pos < tpos:
        if pos + 1 >= len(b):
            break
        b1, b2 = b[pos], b[pos + 1]
        tag = (b1, b2)
        tag_name = TAG_NAMES.get(tag, "unknown")

        if tag in ((0x4B, 0x01), (0x48, 0x01), (0x49, 0x01)):
            data_len = _vb_get_4b_be(b, pos + 8)
            l1 = data_len + 0x10
        elif tag in ((0x09, 0x00), (0x03, 0x00)):
            data_len = _vb_get_3b_be(b, pos + 2)
            l1 = data_len + 0x10
        else:
            guess = _vb_get_3b_be(b, pos + 2) + 0x10
            l1 = guess if 0x10 < guess < len(b) - pos else 1

        counts[tag_name] = counts.get(tag_name, 0) + 1
        pos += l1

    print(f"\nBlocks ({sum(counts.values())} total):")
    for name, count in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {name}: {count}")

    ui_size = len(b) - l2
    print(f"\nUI table: {ui_size:,} bytes at 0x{l2:X}")

    return 0


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


def cmd_verify(args: argparse.Namespace) -> int:
    """Round-trip test: parse → serialize → compare."""
    # This requires the full parser (PyQt6 stubs).
    import importlib.util
    import types

    # Minimal PyQt6 stub
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
    if not main_path.exists():
        print("error: main.py not found — cannot verify round-trip", file=sys.stderr)
        return 1

    spec = importlib.util.spec_from_file_location("main", main_path)
    assert spec is not None and spec.loader is not None
    main = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(main)
    except Exception as exc:
        print(f"warning: main.py import: {exc}", file=sys.stderr)

    bin_path = Path(args.file)
    if not bin_path.exists():
        print(f"error: file not found: {bin_path}", file=sys.stderr)
        return 1

    original = bin_path.read_bytes()
    an = main.H26WatchfaceAnalyzer()
    ok = an.load_file(str(bin_path))
    if not ok:
        print("✗ load_file returned False — file may be corrupt", file=sys.stderr)
        return 1

    out = an.serialize()
    if out == original:
        print(f"✓ Round-trip OK: {len(original):,} bytes preserved byte-for-byte")
        return 0
    else:
        # Find first diff
        for i in range(min(len(out), len(original))):
            if out[i] != original[i]:
                print(f"✗ Round-trip FAILED: first diff at offset 0x{i:X}")
                print(f"  original: 0x{original[i]:02X}")
                print(f"  serialize: 0x{out[i]:02X}")
                break
        print(f"  sizes: original={len(original)} serialize={len(out)}")
        return 1


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="h26",
        description="H26 Watchface CLI — compile, parse, and inspect .bin files",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # compile
    p_compile = sub.add_parser("compile", help="Compile a project JSON into a .bin")
    p_compile.add_argument("project", help="Path to project JSON file")
    p_compile.add_argument("-o", "--output", help="Output .bin path (default: <project>.bin)")

    # parse
    p_parse = sub.add_parser("parse", help="Parse a .bin and dump structure as JSON")
    p_parse.add_argument("file", help="Path to .bin file")

    # info
    p_info = sub.add_parser("info", help="Quick summary of a .bin file")
    p_info.add_argument("file", help="Path to .bin file")

    # verify
    p_verify = sub.add_parser("verify", help="Round-trip test: parse → serialize → compare")
    p_verify.add_argument("file", help="Path to .bin file")

    args = parser.parse_args()
    handlers = {
        "compile": cmd_compile,
        "parse": cmd_parse,
        "info": cmd_info,
        "verify": cmd_verify,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())

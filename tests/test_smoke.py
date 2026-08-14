"""
Smoke test using a SYNTHETIC H26 binary.

The synthetic binary is built by ``tests.conftest.build_synthetic_binary()``
and exercises every parser path the spec-gap patches touched (Type 37
system-screen buttons, Type 47 angled fonts, Type 5B solid rectangles,
Type 14 animations). The test asserts the analyzer extracts every
named field correctly.

This test is the safety net for the spec-gap work in
``5ce4154 (feat: close spec gaps in UI table parser)`` — if any of
these assertions fail after a parser change, the change has
regressed one of the spec-covered types.

Run with::

    python3 tests/test_smoke.py
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tests.conftest import (  # noqa: E402
    MAIN_PY,
    build_synthetic_binary,
    install_pyqt6_stub,
)

install_pyqt6_stub()

# ---- Load the analyzer -------------------------------------------------

spec = importlib.util.spec_from_file_location("main", MAIN_PY)
assert spec is not None and spec.loader is not None
main = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(main)
except Exception as exc:
    # The QApplication-using code at the bottom of main.py is
    # unreachable here, so this is safe to swallow.
    print(f"[warn] main.py import warning: {exc}")


# ---- Build the synthetic binary and parse it ---------------------------

original = build_synthetic_binary()
analyzer = main.H26WatchfaceAnalyzer()

# load_file is path-based; write to a temp file.
with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
    tmp.write(original)
    tmp_path = tmp.name
try:
    ok = analyzer.load_file(tmp_path)
    assert ok, "load_file returned False on synthetic valid binary"
finally:
    Path(tmp_path).unlink(missing_ok=True)

print(f"Total UI items parsed: {len(analyzer.ui_items)}")
print(f"wf_name: {analyzer.wf_name!r}")
print(f"unknown_blocks: {len(analyzer.unknown_blocks)}")

by_type = {it.item_type: it for it in analyzer.ui_items}

# --- Type 37 (button / system screen) ---
assert 0x37 in by_type, f"Type 37 missing; got types: {sorted(by_type)}"
it = by_type[0x37]
print(f"Type 37 data_values: {it.data_values}")
print(f"Type 37 system_screens: {it.system_screens}")
assert it.data_values == [3, 120, 40], it.data_values
assert it.system_screens == ["WeatherScreen", "HRScreen"], it.system_screens

# --- Type 47 (angled font) ---
assert 0x47 in by_type, f"Type 47 missing; got types: {sorted(by_type)}"
it = by_type[0x47]
print(f"Type 47 data_values (dX, dY should be first 2): {it.data_values}")
print(f"Type 47 frame_indices: {it.frame_indices}")
assert it.data_values == [2, 1], f"expected dX=2, dY=1, got {it.data_values}"
assert it.frame_indices == [0], it.frame_indices

# --- Type 5B (solid rectangle) ---
assert 0x5B in by_type, f"Type 5B missing; got types: {sorted(by_type)}"
it = by_type[0x5B]
print(f"Type 5B data_values: {it.data_values}")
assert it.data_values == [3, 100, 50, 0xFF, 0x00, 0x00], it.data_values

# --- Type 14 (animation) ---
assert 0x14 in by_type, f"Type 14 missing; got types: {sorted(by_type)}"
it = by_type[0x14]
print(f"Type 14 sub_type: 0x{it.header_values[1]:02X}, frames: {it.frame_indices}")
assert it.header_values[1] == 0x34
assert it.frame_indices == [], it.frame_indices

# --- Backwards-compat alias ---
assert main.vb_get_4b_signed_le is main.vb_get_4b_signed_be, "vb_get_4b_signed_le alias broken"

# --- Round-trip: serialize() must reproduce the input bytes ---
out = analyzer.serialize()
assert out == original, f"serialize() not byte-perfect: in={len(original)} out={len(out)}"
print(f"Round-trip: {len(original)} bytes in → {len(out)} bytes out (byte-perfect)")

print("\nALL SMOKE TESTS PASSED ✅")

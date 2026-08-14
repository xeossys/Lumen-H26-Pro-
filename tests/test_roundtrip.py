"""
Round-trip + adversarial parser tests.

Four test functions:

* ``test_roundtrip_byte_perfect_smoke``: the synthetic binary
* ``test_roundtrip_byte_perfect_real``: every real fixture in
  ``tests/fixtures/`` — the test suite auto-discovers them
* ``test_roundtrip_idempotent_structure_synthetic``: parse →
  serialize → re-parse → all fields equal
* ``test_roundtrip_idempotent_structure_real``: same for every
  real fixture

These are the regression-net for the ``serialize()`` API: any change
that silently breaks round-trip stability fails here.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tests.conftest import (  # noqa: E402
    FIXTURES_DIR,
    MAIN_PY,
    build_synthetic_binary,
    install_pyqt6_stub,
)

install_pyqt6_stub()


def _load_main_module():
    spec = importlib.util.spec_from_file_location("main", MAIN_PY)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:
        # QApplication-using code at the bottom of main.py is fine
        # to ignore — we never call it.
        print(f"[warn] main.py import warning: {exc}")
    return mod


main = _load_main_module()


def _parse_bytes(main_mod, data: bytes):
    an = main_mod.H26WatchfaceAnalyzer()
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        assert an.load_file(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    return an


# ---- Test functions ----------------------------------------------------


def test_roundtrip_byte_perfect_smoke():
    """Synthetic binary: serialize() reproduces the input byte-for-byte."""
    original = build_synthetic_binary()
    an = _parse_bytes(main, original)
    out = an.serialize()
    assert out == original, f"smoke round-trip differs: in={len(original)} out={len(out)}"
    print(f"[ok] smoke round-trip: {len(original)} bytes preserved")


def test_roundtrip_byte_perfect_real():
    """Every real fixture: serialize() reproduces the file byte-for-byte."""
    fixtures = sorted(FIXTURES_DIR.glob("*.bin"))
    assert fixtures, f"no fixtures found in {FIXTURES_DIR}"
    for path in fixtures:
        original = path.read_bytes()
        an = main.H26WatchfaceAnalyzer()
        assert an.load_file(str(path))
        out = an.serialize()
        assert out == original, f"{path.name}: round-trip differs in={len(original)} out={len(out)}"
        print(f"[ok] {path.name} round-trip: {len(original):,} bytes preserved")


def test_roundtrip_idempotent_structure_synthetic():
    """Re-parsing the serialized synthetic output must yield the same structure."""
    original = build_synthetic_binary()
    an1 = _parse_bytes(main, original)
    out = an1.serialize()
    an2 = _parse_bytes(main, out)

    assert len(an2.ui_items) == len(an1.ui_items)
    assert len(an2.blocks) == len(an1.blocks)
    assert len(an2.unknown_blocks) == len(an1.unknown_blocks)

    for i, (a, b) in enumerate(zip(an1.ui_items, an2.ui_items, strict=True)):
        assert a.item_type == b.item_type, f"item {i} type differs"
        assert a.x == b.x and a.y == b.y, f"item {i} pos differs"
        assert a.data_values == b.data_values, (
            f"item {i} (type 0x{a.item_type:02X}) data_values differs: "
            f"{a.data_values} != {b.data_values}"
        )
        assert a.system_screens == b.system_screens, (
            f"item {i} (type 0x{a.item_type:02X}) system_screens differs"
        )
        assert a.frame_indices == b.frame_indices, (
            f"item {i} (type 0x{a.item_type:02X}) frame_indices differs"
        )
    print(f"[ok] structure idempotent across re-parse: {len(an1.ui_items)} items")


def test_roundtrip_idempotent_structure_real():
    """Re-parsing the serialized real fixture must yield the same structure."""
    fixtures = sorted(FIXTURES_DIR.glob("*.bin"))
    assert fixtures, f"no fixtures found in {FIXTURES_DIR}"
    for path in fixtures:
        an1 = main.H26WatchfaceAnalyzer()
        assert an1.load_file(str(path))
        out = an1.serialize()
        an2 = _parse_bytes(main, out)
        assert len(an2.ui_items) == len(an1.ui_items), (
            f"{path.name}: ui_items count differs after re-parse"
        )
        assert len(an2.blocks) == len(an1.blocks)
        for i, (a, b) in enumerate(zip(an1.ui_items, an2.ui_items, strict=True)):
            assert a.item_type == b.item_type
            assert a.x == b.x and a.y == b.y
            assert a.data_values == b.data_values
            assert a.frame_indices == b.frame_indices
        print(
            f"[ok] {path.name} structure idempotent: "
            f"{len(an1.ui_items)} items, {len(an1.blocks)} blocks"
        )


# ---- Runner ------------------------------------------------------------


def main_runner():
    failures = []
    for fn in (
        test_roundtrip_byte_perfect_smoke,
        test_roundtrip_byte_perfect_real,
        test_roundtrip_idempotent_structure_synthetic,
        test_roundtrip_idempotent_structure_real,
    ):
        try:
            fn()
        except AssertionError as e:
            failures.append((fn.__name__, str(e)))
            print(f"[FAIL] {fn.__name__}: {e}")
        except Exception as e:
            failures.append((fn.__name__, repr(e)))
            print(f"[ERROR] {fn.__name__}: {e!r}")
    if failures:
        print(f"\n{len(failures)} test(s) failed")
        sys.exit(1)
    print("\nALL ROUND-TRIP TESTS PASSED ✅")


if __name__ == "__main__":
    main_runner()

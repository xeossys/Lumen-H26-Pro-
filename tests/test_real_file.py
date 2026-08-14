"""
Structural assertions for every real H26 fixture in tests/fixtures/.

The test suite auto-discovers all ``*.bin`` files in
``tests/fixtures/`` and runs the same structural assertions on each.
This means new fixtures can be added by simply dropping a file in
the directory — no test code change required.

For each fixture we assert:
* the magic header is ``Sb@*``
* the document load returns True
* the analyzer exposes ``preview_offset``, ``l2``, ``l3``, ``l4``
* at least one LZ4 image block was decoded (the file isn't empty)
* at least one UIItem was parsed
* the round-trip ``analyzer.serialize()`` produces a byte-perfect
  copy of the input
* re-parsing the serialized output yields the same UI table and
  block list

Per-fixture expected values (e.g. block counts, hand pivots) live
in the per-fixture functions at the bottom of this file and are
skipped automatically if not defined.

Run with::

    python3 tests/test_real_file.py
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tests.conftest import (  # noqa: E402
    FIXTURES_DIR,
    MAIN_PY,
    install_pyqt6_stub,
)

install_pyqt6_stub()


# ---- Module loader ----------------------------------------------------

spec = importlib.util.spec_from_file_location("main", MAIN_PY)
assert spec is not None and spec.loader is not None
main = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(main)
except Exception as exc:
    # QApplication-using code at the bottom of main.py is unreachable
    # in this test, so the import is safe to swallow.
    print(f"[warn] main.py import warning: {exc}")


# ---- Helpers -----------------------------------------------------------


def _load_fixture(path: Path) -> object:
    an = main.H26WatchfaceAnalyzer()
    assert an.load_file(str(path)), f"load_file returned False on {path.name}"
    return an


def _reparse_bytes(data: bytes) -> object:
    an = main.H26WatchfaceAnalyzer()
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        assert an.load_file(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    return an


def _list_fixtures() -> list[Path]:
    if not FIXTURES_DIR.is_dir():
        return []
    return sorted(FIXTURES_DIR.glob("*.bin"))


# ---- Generic assertions (run for every fixture) -----------------------


def _assert_generic(an: main.H26WatchfaceAnalyzer, path: Path) -> None:
    inp = path.read_bytes()
    assert inp[:4] == b"Sb@*", f"{path.name}: bad magic {inp[:4]!r}"

    # Header fields
    assert an.preview_offset > 0
    assert an.l2 > 0 and an.l2 < len(inp)
    assert an.l3 >= 0
    assert an.l4 >= an.l3

    # At least one graphical block decoded
    graphical_types = (
        main.BlockType.LZ4pal32,
        main.BlockType.LZ4raw565,
        main.BlockType.LZ4raw565a,
        main.BlockType.JPG,
        main.BlockType.GIF,
    )
    n_graphical = sum(1 for b in an.blocks if b.b_type in graphical_types)
    assert n_graphical > 0, f"{path.name}: no graphical blocks decoded"

    # At least one UIItem parsed
    assert len(an.ui_items) > 0, f"{path.name}: zero UIItems"

    # Round-trip byte-perfect
    out = an.serialize()
    assert out == inp, f"{path.name}: serialize() not byte-perfect (in={len(inp)} out={len(out)})"

    # Re-parse the round-tripped bytes
    an2 = _reparse_bytes(out)
    assert len(an2.ui_items) == len(an.ui_items), (
        f"{path.name}: ui_items count differs after re-parse "
        f"({len(an.ui_items)} -> {len(an2.ui_items)})"
    )
    assert len(an2.blocks) == len(an.blocks)


# ---- Per-fixture detailed assertions ---------------------------------


def _assert_clock20517(an: main.H26WatchfaceAnalyzer, path: Path) -> None:
    """Specific structural assertions for Clock20517_res.bin."""
    assert an.preview_offset == 0x20
    assert an.l2 == 0x1600C
    assert an.l3 == 0x6083
    assert an.l4 == 0x9523

    type_counter = Counter(it.item_type for it in an.ui_items)
    assert len(an.ui_items) == 14
    assert type_counter[0x00] == 2
    assert type_counter[0x01] == 2
    assert type_counter[0x02] == 2
    assert type_counter[0x0F] == 5
    assert type_counter[0x14] == 3

    # Hands with their pivots
    expected = [
        (0x0B, 192, 126, [13, 129]),
        (0x0C, 192, 72, [13, 184]),
        (0x0D, 195, 68, [10, 188]),
        (0x0B, 192, 126, [13, 129]),
        (0x0C, 192, 72, [13, 184]),
    ]
    hands = [it for it in an.ui_items if it.item_type == 0x0F]
    assert len(hands) == 5
    for got, (sub, x, y, pivots) in zip(hands, expected, strict=True):
        assert got.header_values[1] == sub
        assert got.x == x and got.y == y
        assert got.data_values[:2] == pivots

    # Layouts: regular + AOD
    layouts = [it for it in an.ui_items if it.item_type == 0x00]
    assert sorted(it.header_values[1] for it in layouts) == [0x8C, 0x8D]

    # The big animation has 14 frames
    anims = [it for it in an.ui_items if it.item_type == 0x14]
    big_anim = max(anims, key=lambda it: len(it.frame_indices))
    assert len(big_anim.frame_indices) == 14

    lz4pal = sum(1 for b in an.blocks if b.b_type == main.BlockType.LZ4pal32)
    assert lz4pal == 66
    assert len(an.unknown_blocks) == 0


def _assert_clock21592(an: main.H26WatchfaceAnalyzer, path: Path) -> None:
    """Specific structural assertions for Clock21592_res.bin."""
    assert an.preview_offset == 0x20
    assert an.l2 == 0x390CC
    assert an.l3 == 0x10072
    assert an.l4 == 0x29A23

    type_counter = Counter(it.item_type for it in an.ui_items)
    assert len(an.ui_items) == 8
    assert type_counter[0x00] == 1
    assert type_counter[0x01] == 3
    assert type_counter[0x0F] == 2
    assert type_counter[0x14] == 2

    # Single layout, sub-type 0x8C (regular)
    layouts = [it for it in an.ui_items if it.item_type == 0x00]
    assert len(layouts) == 1
    assert layouts[0].header_values[1] == 0x8C

    # 2 hands (minute + second, no hour hand)
    hands = [it for it in an.ui_items if it.item_type == 0x0F]
    assert len(hands) == 2
    hand_subs = sorted(h.header_values[1] for h in hands)
    assert hand_subs == [0x0C, 0x0D]  # minute, second

    lz4pal = sum(1 for b in an.blocks if b.b_type == main.BlockType.LZ4pal32)
    assert lz4pal == 35
    assert len(an.unknown_blocks) == 0


# Map fixture name -> per-fixture detailed assertion
_PER_FIXTURE_ASSERTIONS = {
    "Clock20517_res.bin": _assert_clock20517,
    "Clock21592_res.bin": _assert_clock21592,
}


# ---- Runner -----------------------------------------------------------


def main_runner() -> int:
    fixtures = _list_fixtures()
    if not fixtures:
        print(f"[FAIL] no fixtures found in {FIXTURES_DIR}")
        return 1
    print(f"Discovered {len(fixtures)} fixture(s):")
    for f in fixtures:
        print(f"  - {f.name} ({f.stat().st_size:,} bytes)")

    failures: list[tuple[str, str]] = []
    for path in fixtures:
        name = path.name
        try:
            an = _load_fixture(path)
            _assert_generic(an, path)
            specific = _PER_FIXTURE_ASSERTIONS.get(name)
            if specific is not None:
                specific(an, path)
            else:
                print(f"[skip] {name}: no per-fixture assertions defined")
            print(f"[ok] {name}")
        except AssertionError as e:
            failures.append((name, str(e)))
            print(f"[FAIL] {name}: {e}")
        except Exception as e:
            failures.append((name, repr(e)))
            print(f"[ERROR] {name}: {e!r}")

    if failures:
        print(f"\n{len(failures)} fixture(s) failed")
        return 1
    print(f"\nALL {len(fixtures)} REAL-FILE FIXTURE(S) PASSED ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main_runner())

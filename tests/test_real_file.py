"""
Structural assertions for every real H26 fixture in tests/fixtures/.

Auto-discovers all ``*.bin`` files and runs generic structural
assertions on each. Per-fixture detailed assertions are in separate
test classes.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from tests.conftest import FIXTURES_DIR, load_fixture, reparse_bytes

# ---------------------------------------------------------------------------
# Parametrized fixture discovery
# ---------------------------------------------------------------------------


def _fixture_params():
    return sorted(FIXTURES_DIR.glob("*.bin"))


def _fixture_ids():
    return [p.stem for p in sorted(FIXTURES_DIR.glob("*.bin"))]


# ---------------------------------------------------------------------------
# Generic assertions (run for every fixture)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", _fixture_params(), ids=_fixture_ids())
def test_magic_header(path):
    data = path.read_bytes()
    assert data[:4] == b"Sb@*"


@pytest.mark.parametrize("path", _fixture_params(), ids=_fixture_ids())
def test_load_file(main_module, path):
    an = load_fixture(main_module, path)
    assert an.preview_offset > 0
    assert an.l2 > 0 and an.l2 < len(path.read_bytes())
    assert an.l3 >= 0
    assert an.l4 >= an.l3


@pytest.mark.parametrize("path", _fixture_params(), ids=_fixture_ids())
def test_has_graphical_blocks(main_module, path):
    an = load_fixture(main_module, path)
    graphical_types = (
        main_module.BlockType.LZ4pal32,
        main_module.BlockType.LZ4raw565,
        main_module.BlockType.LZ4raw565a,
        main_module.BlockType.JPG,
        main_module.BlockType.GIF,
    )
    n_graphical = sum(1 for b in an.blocks if b.b_type in graphical_types)
    assert n_graphical > 0


@pytest.mark.parametrize("path", _fixture_params(), ids=_fixture_ids())
def test_has_ui_items(main_module, path):
    an = load_fixture(main_module, path)
    assert len(an.ui_items) > 0


@pytest.mark.parametrize("path", _fixture_params(), ids=_fixture_ids())
def test_roundtrip_byte_perfect(main_module, path):
    an = load_fixture(main_module, path)
    inp = path.read_bytes()
    out = an.serialize()
    assert out == inp


@pytest.mark.parametrize("path", _fixture_params(), ids=_fixture_ids())
def test_roundtrip_idempotent(main_module, path):
    an = load_fixture(main_module, path)
    out = an.serialize()
    an2 = reparse_bytes(main_module, out)
    assert len(an2.ui_items) == len(an.ui_items)
    assert len(an2.blocks) == len(an.blocks)


# ---------------------------------------------------------------------------
# Per-fixture detailed assertions
# ---------------------------------------------------------------------------


class TestClock20517:
    """Specific structural assertions for Clock20517_res.bin."""

    @pytest.fixture(autouse=True)
    def setup(self, main_module):
        path = FIXTURES_DIR / "Clock20517_res.bin"
        self.an = load_fixture(main_module, path)

    def test_header_fields(self):
        assert self.an.preview_offset == 0x20
        assert self.an.l2 == 0x1600C
        assert self.an.l3 == 0x6083
        assert self.an.l4 == 0x9523

    def test_item_counts(self):
        tc = Counter(it.item_type for it in self.an.ui_items)
        assert len(self.an.ui_items) == 14
        assert tc[0x00] == 2
        assert tc[0x01] == 2
        assert tc[0x02] == 2
        assert tc[0x0F] == 5
        assert tc[0x14] == 3

    def test_hands(self):
        expected = [
            (0x0B, 192, 126, [13, 129]),
            (0x0B, 192, 126, [13, 129]),
            (0x0C, 192, 72, [13, 184]),
            (0x0C, 192, 72, [13, 184]),
            (0x0D, 195, 68, [10, 188]),
        ]
        hands = sorted(
            [it for it in self.an.ui_items if it.item_type == 0x0F],
            key=lambda it: (it.header_values[1], it.x, it.y),
        )
        assert len(hands) == 5
        for got, (sub, x, y, pivots) in zip(hands, expected, strict=True):
            assert got.header_values[1] == sub
            assert got.x == x and got.y == y
            assert got.data_values[:2] == pivots

    def test_layouts(self):
        layouts = [it for it in self.an.ui_items if it.item_type == 0x00]
        assert sorted(it.header_values[1] for it in layouts) == [0x8C, 0x8D]

    def test_big_animation_frames(self):
        anims = [it for it in self.an.ui_items if it.item_type == 0x14]
        big_anim = max(anims, key=lambda it: len(it.frame_indices))
        assert len(big_anim.frame_indices) == 14


class TestClock21592:
    """Specific structural assertions for Clock21592_res.bin."""

    @pytest.fixture(autouse=True)
    def setup(self, main_module):
        path = FIXTURES_DIR / "Clock21592_res.bin"
        self.an = load_fixture(main_module, path)

    def test_header_fields(self):
        assert self.an.preview_offset == 0x20
        assert self.an.l2 == 0x390CC
        assert self.an.l3 == 0x10072
        assert self.an.l4 == 0x29A23

    def test_item_counts(self):
        tc = Counter(it.item_type for it in self.an.ui_items)
        assert len(self.an.ui_items) == 8
        assert tc[0x00] == 1
        assert tc[0x01] == 3
        assert tc[0x0F] == 2
        assert tc[0x14] == 2

    def test_single_layout(self):
        layouts = [it for it in self.an.ui_items if it.item_type == 0x00]
        assert len(layouts) == 1
        assert layouts[0].header_values[1] == 0x8C

    def test_hands(self):
        hands = [it for it in self.an.ui_items if it.item_type == 0x0F]
        assert len(hands) == 2
        subs = sorted(h.header_values[1] for h in hands)
        assert subs == [0x0C, 0x0D]


class TestClock20493:
    """Specific structural assertions for Clock20493_res.bin."""

    @pytest.fixture(autouse=True)
    def setup(self, main_module):
        path = FIXTURES_DIR / "Clock20493_res.bin"
        self.an = load_fixture(main_module, path)

    def test_header_fields(self):
        assert self.an.preview_offset == 0x20
        assert self.an.l2 == 0x5C29E
        assert self.an.l3 == 0x12C15
        assert self.an.l4 == 0x18AE4

    def test_item_counts(self):
        tc = Counter(it.item_type for it in self.an.ui_items)
        assert len(self.an.ui_items) == 19
        assert tc[0x00] == 2
        assert tc[0x0F] == 5
        assert tc[0x37] == 3
        assert tc[0x47] == 7
        assert tc[0x14] == 2

    def test_system_screens(self):
        buttons = [it for it in self.an.ui_items if it.item_type == 0x37]
        assert len(buttons) == 3
        all_screens = [s for b in buttons for s in b.system_screens]
        assert len(all_screens) > 0

    def test_angled_fonts(self):
        fonts = [it for it in self.an.ui_items if it.item_type == 0x47]
        assert len(fonts) == 7
        assert len(fonts[0].frame_indices) == 10

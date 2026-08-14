"""
Smoke test using a SYNTHETIC H26 binary.

The synthetic binary is built by ``conftest.build_synthetic_binary()``
and exercises every parser path the spec-gap patches touched (Type 37
system-screen buttons, Type 47 angled fonts, Type 5B solid rectangles,
Type 14 animations).
"""

from __future__ import annotations


def test_smoke_parse_items(analyzer):
    """Analyzer parses all 4 UI items from synthetic binary."""
    assert len(analyzer.ui_items) == 4


def test_smoke_wf_name(analyzer):
    assert analyzer.wf_name == "@"


def test_smoke_no_unknown_blocks(analyzer):
    assert len(analyzer.unknown_blocks) == 0


def test_smoke_type37_button(analyzer):
    by_type = {it.item_type: it for it in analyzer.ui_items}
    assert 0x37 in by_type
    it = by_type[0x37]
    assert it.data_values == [3, 120, 40]
    assert it.system_screens == ["WeatherScreen", "HRScreen"]


def test_smoke_type47_angled_font(analyzer):
    by_type = {it.item_type: it for it in analyzer.ui_items}
    assert 0x47 in by_type
    it = by_type[0x47]
    assert it.data_values == [2, 1]
    assert it.frame_indices == [0]


def test_smoke_type5b_solid_rect(analyzer):
    by_type = {it.item_type: it for it in analyzer.ui_items}
    assert 0x5B in by_type
    it = by_type[0x5B]
    assert it.data_values == [3, 100, 50, 0xFF, 0x00, 0x00]


def test_smoke_type14_animation(analyzer):
    by_type = {it.item_type: it for it in analyzer.ui_items}
    assert 0x14 in by_type
    it = by_type[0x14]
    assert it.header_values[1] == 0x34
    assert it.frame_indices == []


def test_smoke_roundtrip(main_module, synthetic_binary):
    """serialize() reproduces the synthetic binary byte-perfectly."""
    from tests.conftest import reparse_bytes

    an = main_module.H26WatchfaceAnalyzer()
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
        tmp.write(synthetic_binary)
        tmp_path = tmp.name
    try:
        an.load_file(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    out = an.serialize()
    assert out == synthetic_binary

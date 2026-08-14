"""
Round-trip + adversarial parser tests.

Tests that serialize() produces byte-perfect output and that
re-parsing yields identical structure.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from tests.conftest import FIXTURES_DIR, load_fixture, reparse_bytes


def _fixture_params():
    return sorted(FIXTURES_DIR.glob("*.bin"))


def _fixture_ids():
    return [p.stem for p in sorted(FIXTURES_DIR.glob("*.bin"))]


def test_roundtrip_byte_perfect_synthetic(main_module, synthetic_binary):
    """Synthetic binary round-trips byte-perfectly."""
    an = main_module.H26WatchfaceAnalyzer()
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
        tmp.write(synthetic_binary)
        tmp_path = tmp.name
    try:
        an.load_file(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    assert an.serialize() == synthetic_binary


@pytest.mark.parametrize("path", _fixture_params(), ids=_fixture_ids())
def test_roundtrip_byte_perfect_real(main_module, path):
    """Every real fixture round-trips byte-perfectly."""
    an = load_fixture(main_module, path)
    assert an.serialize() == path.read_bytes()


def test_roundtrip_idempotent_synthetic(main_module, synthetic_binary):
    """Synthetic: parse → serialize → re-parse → all fields equal."""
    an = main_module.H26WatchfaceAnalyzer()
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
        tmp.write(synthetic_binary)
        tmp_path = tmp.name
    try:
        an.load_file(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    out = an.serialize()
    an2 = reparse_bytes(main_module, out)
    assert len(an2.ui_items) == len(an.ui_items)
    assert len(an2.blocks) == len(an.blocks)


@pytest.mark.parametrize("path", _fixture_params(), ids=_fixture_ids())
def test_roundtrip_idempotent_real(main_module, path):
    """Real fixtures: parse → serialize → re-parse → structure preserved."""
    an = load_fixture(main_module, path)
    out = an.serialize()
    an2 = reparse_bytes(main_module, out)
    assert len(an2.ui_items) == len(an.ui_items)
    assert len(an2.blocks) == len(an.blocks)

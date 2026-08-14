"""
CLI integration tests (h26/cli.py).

Tests all CLI commands against real fixtures and a fresh compile.
"""

from __future__ import annotations

import binascii
import json
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

CLI = [sys.executable, "-m", "h26.cli"]
ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"


def _run(args: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    """Run a CLI command and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        CLI + args,
        capture_output=True,
        text=True,
        cwd=str(cwd or ROOT),
    )
    return result.returncode, result.stdout, result.stderr


def _make_tiny_png(path: Path, width: int = 2, height: int = 2):
    """Write a minimal valid PNG file."""

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", binascii.crc32(c) & 0xFFFFFFFF)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b""
    for _ in range(height):
        raw += b"\x00" + b"\xff\x00\x00" * width
    compressed = zlib.compress(raw)
    with open(path, "wb") as f:
        f.write(sig)
        f.write(_chunk(b"IHDR", ihdr))
        f.write(_chunk(b"IDAT", compressed))
        f.write(_chunk(b"IEND", b""))


def test_info_fixture():
    """`info` on a real fixture prints block counts and header fields."""
    rc, out, err = _run(["info", str(FIXTURES / "Clock20517_res.bin")])
    assert rc == 0, f"exit {rc}: {err}"
    assert "Magic:   Sb@*" in out
    assert "Blocks (66 total):" in out
    assert "LZ4pal32: 66" in out
    assert "UI Table:" in out


def test_info_invalid_file():
    """`info` on a non-H26 file returns exit 1."""
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
        f.write(b"not a watchface")
        tmp = Path(f.name)
    try:
        rc, out, err = _run(["info", str(tmp)])
        assert rc == 1
        assert "error" in err.lower()
    finally:
        tmp.unlink()


def test_parse_fixture():
    """`parse` on a real fixture returns valid JSON with blocks."""
    rc, out, err = _run(["parse", str(FIXTURES / "Clock21592_res.bin")])
    assert rc == 0, f"exit {rc}: {err}"
    data = json.loads(out)
    assert "blocks" in data
    assert "ui_items" in data
    assert len(data["blocks"]) > 0


def test_verify_valid():
    """`verify` on a valid fixture returns exit 0."""
    rc, out, err = _run(["verify", str(FIXTURES / "Clock20493_res.bin")])
    assert rc == 0, f"exit {rc}: {err}"


def test_verify_invalid():
    """`verify` on garbage returns exit 1."""
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
        f.write(b"garbage")
        tmp = Path(f.name)
    try:
        rc, out, err = _run(["verify", str(tmp)])
        assert rc == 1
    finally:
        tmp.unlink()


def test_export_fixture():
    """`export` on a fixture creates output files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        rc, out, err = _run(["export", str(FIXTURES / "Clock20517_res.bin"), "-o", tmpdir])
        assert rc == 0, f"exit {rc}: {err}"
        exported = list(Path(tmpdir).iterdir())
        assert len(exported) > 0


def test_compile_from_json(tmp_path):
    """`compile` from a project JSON produces a valid .bin."""
    from h26.project import FrameItem, ImageAsset, Layout, Project

    img_path = tmp_path / "bg.png"
    _make_tiny_png(img_path)
    proj = Project(
        name="cli_test",
        images=[ImageAsset(name="bg", source_path=str(img_path), width=2, height=2)],
        layout=Layout(x=0, y=0, children=[FrameItem(x=0, y=0, image_name="bg")]),
    )
    json_path = tmp_path / "project.json"
    json_path.write_text(proj.to_json())
    out_path = tmp_path / "out.bin"
    rc, out, err = _run(
        ["compile", str(json_path), "-o", str(out_path)],
        cwd=tmp_path,
    )
    assert rc == 0, f"exit {rc}: {err}"
    assert out_path.exists()
    data = out_path.read_bytes()
    assert data[:4] == b"Sb@*"

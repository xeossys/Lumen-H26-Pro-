"""
CLI integration tests (h26/cli.py).

Tests all four CLI commands against real fixtures and a fresh
compile. Run with::

    python3 tests/test_cli.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
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


# --- Tests ---


def test_info_fixture():
    """`info` on a real fixture prints block counts and header fields."""
    rc, out, err = _run(["info", str(FIXTURES / "Clock20517_res.bin")])
    assert rc == 0, f"exit {rc}: {err}"
    assert "Magic:   Sb@*" in out
    assert "Blocks (66 total):" in out
    assert "LZ4pal32: 66" in out
    assert "UI table:" in out


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
    assert data["header"]["magic"] == "Sb@*"
    assert len(data["blocks"]) > 0
    assert data["blocks"][0]["type"] == "LZ4pal32"
    assert data["blocks"][0]["width"] > 0
    assert data["blocks"][0]["height"] > 0


def test_verify_fixture():
    """`verify` on a real fixture passes the round-trip test."""
    for name in ["Clock20517_res.bin", "Clock21592_res.bin", "Clock20493_res.bin"]:
        rc, out, err = _run(["verify", str(FIXTURES / name)])
        assert rc == 0, f"{name} exit {rc}: {err}"
        assert "Round-trip OK" in out


def test_compile_and_verify():
    """`compile` a project JSON → `verify` the result → round-trip OK."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)

        # Create a test image.
        from PIL import Image

        img_path = td / "bg.png"
        Image.new("RGBA", (8, 8), (128, 64, 32, 255)).save(str(img_path))

        # Write project JSON.
        project = {
            "name": "cli_test",
            "canvas_width": 8,
            "canvas_height": 8,
            "images": [{"name": "bg", "source_path": str(img_path), "width": 8, "height": 8}],
            "layout": {
                "item_type": 0,
                "sub_type": 140,
                "x": 0,
                "y": 0,
                "align": 0,
                "image_name": "",
                "children": [
                    {"item_type": 1, "sub_type": 0, "x": 0, "y": 0, "align": 0, "image_name": "bg"}
                ],
            },
        }
        project_path = td / "project.json"
        project_path.write_text(json.dumps(project))

        # Compile.
        output_path = td / "output.bin"
        rc, out, err = _run(["compile", str(project_path), "-o", str(output_path)])
        assert rc == 0, f"compile exit {rc}: {err}"
        assert "Compiled" in out
        assert output_path.exists()
        assert output_path.stat().st_size > 0

        # Verify round-trip.
        rc, out, err = _run(["verify", str(output_path)])
        assert rc == 0, f"verify exit {rc}: {err}"
        assert "Round-trip OK" in out

        # Info.
        rc, out, err = _run(["info", str(output_path)])
        assert rc == 0
        assert "Magic:   Sb@*" in out
        assert "JPG: 1" in out  # preview block
        assert "LZ4pal32: 1" in out  # image block


def test_compile_missing_project():
    """`compile` with a nonexistent file returns exit 1."""
    rc, out, err = _run(["compile", "/nonexistent/project.json"])
    assert rc == 1
    assert "error" in err.lower()


def test_compile_invalid_json():
    """`compile` with invalid JSON returns exit 1."""
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
        f.write("{not valid json")
        tmp = Path(f.name)
    try:
        rc, out, err = _run(["compile", str(tmp)])
        assert rc == 1
        assert "error" in err.lower()
    finally:
        tmp.unlink()


def test_parse_as_json():
    """`parse` output is valid JSON with expected top-level keys."""
    rc, out, err = _run(["parse", str(FIXTURES / "Clock20493_res.bin")])
    assert rc == 0
    data = json.loads(out)
    assert "file" in data
    assert "size" in data
    assert "header" in data
    assert "blocks" in data
    assert "ui_table" in data
    assert data["size"] == 378952


# --- Runner ---


def main_runner():
    tests = [
        test_info_fixture,
        test_info_invalid_file,
        test_parse_fixture,
        test_verify_fixture,
        test_compile_and_verify,
        test_compile_missing_project,
        test_compile_invalid_json,
        test_parse_as_json,
    ]
    failures = []
    for fn in tests:
        try:
            fn()
            print(f"[ok] {fn.__name__}")
        except AssertionError as e:
            failures.append((fn.__name__, str(e)))
            print(f"[FAIL] {fn.__name__}: {e}")
        except Exception as e:
            failures.append((fn.__name__, repr(e)))
            print(f"[ERROR] {fn.__name__}: {e!r}")
    if failures:
        print(f"\n{len(failures)} test(s) failed")
        sys.exit(1)
    print("\nALL CLI TESTS PASSED")


if __name__ == "__main__":
    main_runner()

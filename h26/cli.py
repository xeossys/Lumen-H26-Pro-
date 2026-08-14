#!/usr/bin/env python3
"""H26 Watchface CLI — compile, parse, inspect, export and build `.bin` files.

Usage::

    # Compile a project JSON into a .bin watchface
    python3 -m h26.cli compile project.json -o watchface.bin

    # Parse a .bin and dump its structure as JSON
    python3 -m h26.cli parse watchface.bin

    # Quick summary of a .bin file
    python3 -m h26.cli info watchface.bin

    # Round-trip test: parse → serialize → compare
    python3 -m h26.cli verify watchface.bin

    # Export a .bin to a folder with images + project.json
    python3 -m h26.cli export watchface.bin -o watchface_project/

    # Export a .bin to a zip archive
    python3 -m h26.cli export watchface.bin -o watchface_project.zip

    # Build a .bin from a folder or zip with project.json + images
    python3 -m h26.cli build watchface_project/ -o watchface.bin
    python3 -m h26.cli build watchface_project.zip -o watchface.bin
"""

from __future__ import annotations

import argparse
import io
import json
import struct
import sys
import zipfile
from pathlib import Path

from h26.decoder import (
    decode_block_to_rgba,
    extract_jpg_bytes,
    scan_blocks,
)
from h26.utils import MAGIC

# ---------------------------------------------------------------------------
# Image output helpers (PNG via Pillow)
# ---------------------------------------------------------------------------


def _rgba_to_png(rgba: bytes, width: int, height: int) -> bytes:
    """Convert raw RGBA bytes to PNG using Pillow."""
    from PIL import Image

    img = Image.frombytes("RGBA", (width, height), rgba)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _decode_block_to_png(block: bytes) -> tuple[bytes, int, int] | None:
    """Decode any supported image block to PNG bytes.

    Returns (png_bytes, width, height) or None if unsupported/invalid.
    """
    b1, b2 = block[0], block[1]

    # JPG blocks: extract raw bytes (no RGBA conversion)
    if b1 == 0x09 and b2 == 0x00:
        jpg_data = extract_jpg_bytes(block)
        if jpg_data:
            return jpg_data, 0, 0
        return None

    # LZ4pal32 / BGR565A: decode to RGBA then convert to PNG
    result = decode_block_to_rgba(block)
    if result is None:
        return None

    rgba, w, h = result
    png = _rgba_to_png(rgba, w, h)
    return png, w, h


# ---------------------------------------------------------------------------
# cmd_compile
# ---------------------------------------------------------------------------


def cmd_compile(args: argparse.Namespace) -> int:
    """Compile a project JSON into a .bin watchface."""
    from h26.encoder import compile as h26_compile
    from h26.project import Project

    project_path = Path(args.project)
    if not project_path.exists():
        print(f"error: file not found: {project_path}", file=sys.stderr)
        return 1

    try:
        project = Project.from_json(project_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"error: invalid project JSON: {exc}", file=sys.stderr)
        return 1

    try:
        result = h26_compile(project)
    except Exception as exc:
        print(f"error: compilation failed: {exc}", file=sys.stderr)
        return 1

    out_path = Path(args.output) if args.output else project_path.with_suffix(".bin")
    out_path.write_bytes(result)
    print(f"Compiled: {out_path} ({len(result):,} bytes)")
    return 0


# ---------------------------------------------------------------------------
# cmd_parse
# ---------------------------------------------------------------------------


def cmd_parse(args: argparse.Namespace) -> int:
    """Parse a .bin and dump its structure as JSON."""
    bin_path = Path(args.file)
    if not bin_path.exists():
        print(f"error: file not found: {bin_path}", file=sys.stderr)
        return 1

    b = bin_path.read_bytes()
    if len(b) < 0x20 or b[:4] != MAGIC:
        print("error: not a valid H26 file (bad magic)", file=sys.stderr)
        return 1

    scan = scan_blocks(b)

    result = {
        "file": str(bin_path),
        "size": len(b),
        "preview_offset": f"0x{scan['preview_offset']:X}",
        "l3": f"0x{scan['l3']:X}",
        "l3_len": f"0x{scan['l3_len']:X}",
        "l2": f"0x{scan['l2']:X}",
        "block_count": len(scan["blocks"]),
        "blocks": [blk.to_dict() for blk in scan["blocks"][:20]],
        "ui_items": [item.to_dict() for item in scan["ui_items"]],
    }
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0


# ---------------------------------------------------------------------------
# cmd_info
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

    scan = scan_blocks(b)

    print(f"File:    {bin_path}")
    print(f"Size:    {len(b):,} bytes")
    print("Magic:   Sb@* ✓")
    print(f"Preview: 0x{scan['preview_offset']:X}")
    print(f"L3:      0x{scan['l3']:X} (len 0x{scan['l3_len']:X})")
    print(f"L2 (UI): 0x{scan['l2']:X}")

    # Block counts
    counts: dict[str, int] = {}
    for blk in scan["blocks"]:
        t = blk.type_name
        counts[t] = counts.get(t, 0) + 1

    print(f"\nBlocks ({len(scan['blocks'])} total):")
    for tag_name, count in sorted(counts.items()):
        print(f"  {tag_name}: {count}")

    print(f"\nUI Table: {len(scan['ui_items'])} items")
    for item in scan["ui_items"][:10]:
        print(
            f"  [{item.index:2d}] Type 0x{item.type:02X} "
            f"sub=0x{item.sub_type:02X} ({item.x},{item.y})"
        )
    if len(scan["ui_items"]) > 10:
        print(f"  ... and {len(scan['ui_items']) - 10} more")
    return 0


# ---------------------------------------------------------------------------
# cmd_verify
# ---------------------------------------------------------------------------


def cmd_verify(args: argparse.Namespace) -> int:
    """Round-trip test: parse → serialize → compare."""
    import tempfile

    try:
        from main import H26WatchfaceAnalyzer
    except ImportError:
        print("error: cannot import main.py (PyQt6 required for verify)", file=sys.stderr)
        return 1

    bin_path = Path(args.file)
    if not bin_path.exists():
        print(f"error: file not found: {bin_path}", file=sys.stderr)
        return 1

    original = bin_path.read_bytes()
    analyzer = H26WatchfaceAnalyzer()
    if not analyzer.load_file(str(bin_path)):
        print("error: failed to load file", file=sys.stderr)
        return 1

    reparsed = analyzer.serialize()
    if original != reparsed:
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(reparsed)
            print(f"MISMATCH: original={len(original)} bytes, reparsed={len(reparsed)} bytes")
            print(f"Reparsed written to: {f.name}")
        return 1

    print(f"✓ Round-trip OK: {len(original):,} bytes preserved")
    print(f"  Blocks: {len(analyzer.blocks)}")
    print(f"  UI items: {len(analyzer.ui_items)}")
    return 0


# ---------------------------------------------------------------------------
# cmd_export
# ---------------------------------------------------------------------------


def cmd_export(args: argparse.Namespace) -> int:
    """Export a .bin watchface to a folder or zip with images + project.json."""
    bin_path = Path(args.file)
    if not bin_path.exists():
        print(f"error: file not found: {bin_path}", file=sys.stderr)
        return 1

    b = bin_path.read_bytes()
    if len(b) < 0x20 or b[:4] != MAGIC:
        print("error: not a valid H26 file (bad magic)", file=sys.stderr)
        return 1

    scan = scan_blocks(b)

    # Determine output mode
    out_arg = args.output or bin_path.stem
    out_path = Path(out_arg)
    use_zip = out_path.suffix.lower() == ".zip"

    # Build block offset → index map for image references
    block_offset_map: dict[int, int] = {}
    for i, blk in enumerate(scan["blocks"]):
        block_offset_map[blk.offset] = i

    # Extract images
    images: list[dict] = []
    images_dir = "images"
    for i, blk in enumerate(scan["blocks"]):
        result = _decode_block_to_png(blk.raw)

        if result is not None:
            png_data, w, h = result
            fname = f"block_{i:03d}.jpg" if blk.type_name == "JPG" else f"block_{i:03d}.png"
            images.append({
                "name": fname,
                "block_index": i,
                "block_offset": blk.offset,
                "type": blk.type_name,
                "width": w,
                "height": h,
                "file": f"{images_dir}/{fname}",
                "data": png_data,
            })

    # Build UI items with image references
    ui_items_export: list[dict] = []
    for item in scan["ui_items"]:
        export_item: dict = {
            "type": f"0x{item.type:02X}",
            "sub_type": f"0x{item.sub_type:02X}",
            "x": item.x,
            "y": item.y,
        }

        # Map frame indices to image names
        if item.frame_indices:
            export_item["images"] = []
            for frame_off in item.frame_indices:
                if frame_off in block_offset_map:
                    blk_idx = block_offset_map[frame_off]
                    for img in images:
                        if img["block_index"] == blk_idx:
                            export_item["images"].append(img["name"])
                            break

        if item.pivot:
            export_item["pivot"] = item.pivot

        ui_items_export.append(export_item)

    # Build project structure
    project = {
        "name": bin_path.stem,
        "source_file": bin_path.name,
        "canvas_width": 480,
        "canvas_height": 480,
        "blocks": [blk.to_dict() for blk in scan["blocks"]],
        "ui_table": ui_items_export,
    }

    if use_zip:
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("project.json", json.dumps(project, indent=2, ensure_ascii=False))
            for img in images:
                zf.writestr(img["file"], img["data"])
        print(f"Exported to zip: {out_path}")
    else:
        out_path.mkdir(parents=True, exist_ok=True)
        img_dir = out_path / images_dir
        img_dir.mkdir(exist_ok=True)
        (out_path / "project.json").write_text(
            json.dumps(project, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        for img in images:
            (out_path / img["file"]).write_bytes(img["data"])
        print(f"Exported to folder: {out_path}")

    print(f"  Blocks: {len(scan['blocks'])}")
    print(f"  Images extracted: {len(images)}")
    print(f"  UI items: {len(scan['ui_items'])}")
    return 0


# ---------------------------------------------------------------------------
# cmd_build
# ---------------------------------------------------------------------------


def cmd_build(args: argparse.Namespace) -> int:
    """Build a .bin watchface from a folder or zip with project.json + images."""
    source = Path(args.source)
    if not source.exists():
        print(f"error: source not found: {source}", file=sys.stderr)
        return 1

    use_zip = source.suffix.lower() == ".zip"

    # Load project.json and images
    if use_zip:
        if not zipfile.is_zipfile(source):
            print(f"error: not a valid zip file: {source}", file=sys.stderr)
            return 1
        with zipfile.ZipFile(source, "r") as zf:
            if "project.json" not in zf.namelist():
                print("error: project.json not found in zip", file=sys.stderr)
                return 1
            project_data = json.loads(zf.read("project.json"))
            images: dict[str, bytes] = {}
            for name in zf.namelist():
                if name.startswith("images/") and not name.endswith("/"):
                    images[name] = zf.read(name)
    else:
        if not source.is_dir():
            print(f"error: not a directory: {source}", file=sys.stderr)
            return 1
        project_file = source / "project.json"
        if not project_file.exists():
            print(f"error: project.json not found in {source}", file=sys.stderr)
            return 1
        project_data = json.loads(project_file.read_text(encoding="utf-8"))
        images = {}
        img_dir = source / "images"
        if img_dir.is_dir():
            for f in img_dir.iterdir():
                if f.is_file():
                    images[f"images/{f.name}"] = f.read_bytes()

    # Validate project structure
    required_fields = ["name", "canvas_width", "canvas_height", "blocks", "ui_table"]
    missing = [f for f in required_fields if f not in project_data]
    if missing:
        print(f"error: project.json missing fields: {missing}", file=sys.stderr)
        return 1

    # Build image blocks
    from h26.image_codec import build_jpg_preview_block, build_lz4pal32_block

    block_data_list: list[bytes] = []
    for i, _blk_info in enumerate(project_data["blocks"]):
        img_path_png = f"images/block_{i:03d}.png"
        img_path_jpg = f"images/block_{i:03d}.jpg"

        if img_path_png in images:
            from PIL import Image

            img = Image.open(io.BytesIO(images[img_path_png]))
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            rgba = img.tobytes()
            block_data_list.append(build_lz4pal32_block(rgba, img.width, img.height))
        elif img_path_jpg in images:
            block_data_list.append(build_jpg_preview_block(images[img_path_jpg]))
        else:
            print(f"warning: no image for block {i}, skipping", file=sys.stderr)

    # Build header (0x40 bytes)
    header = bytearray(0x40)
    header[0:4] = MAGIC

    preview_offset = 0x40
    l3 = preview_offset
    l3_len = sum(len(bd) for bd in block_data_list)
    l2 = l3 + l3_len

    struct.pack_into(">I", header, 0x0C, preview_offset)
    struct.pack_into(">I", header, 0x14, l3)
    struct.pack_into(">I", header, 0x18, l3_len)
    struct.pack_into(">I", header, 0x1C, l2)

    # Build UI table
    ui_table = bytearray()
    for item in project_data["ui_table"]:
        t_type = int(item["type"], 16) if isinstance(item["type"], str) else item["type"]
        t_sub = int(item["sub_type"], 16) if isinstance(item["sub_type"], str) else item["sub_type"]
        t_x = item.get("x", 0)
        t_y = item.get("y", 0)

        ui_table.extend(struct.pack(">5I", t_type, t_sub, 0, t_x, t_y))

        if t_type == 0x00:  # Layout
            ui_table.extend(struct.pack(">II", 0, 0))
        elif t_type in (0x01, 0x02):  # Frame
            ui_table.extend(struct.pack(">I", 0))
        elif t_type == 0x0F:  # Hand
            pivot = item.get("pivot", [0, 0])
            ui_table.extend(struct.pack(">II", pivot[0], pivot[1]))
        elif t_type == 0x14:  # Animation
            ui_table.extend(struct.pack(">I", 0))
            ui_table.extend(struct.pack(">I", 0))
            ui_table.extend(struct.pack(">I", len(item.get("images", []))))
            for _ in item.get("images", []):
                ui_table.extend(struct.pack(">II", 0, 0))

    # Assemble final binary
    result = bytes(header)
    for bd in block_data_list:
        result += bd
    result += bytes(ui_table)

    out_path = Path(args.output) if args.output else source.with_suffix(".bin")
    out_path.write_bytes(result)
    print(f"Built: {out_path} ({len(result):,} bytes)")
    return 0


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="h26.cli",
        description="H26 Watchface CLI — compile, parse, export and build .bin files",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # compile
    p_compile = subparsers.add_parser("compile", help="Compile project JSON → .bin watchface")
    p_compile.add_argument("project", help="Path to project JSON file")
    p_compile.add_argument("-o", "--output", help="Output .bin file (default: <project>.bin)")
    p_compile.set_defaults(func=cmd_compile)

    # parse
    p_parse = subparsers.add_parser("parse", help="Parse .bin → JSON structure")
    p_parse.add_argument("file", help="Path to .bin file")
    p_parse.set_defaults(func=cmd_parse)

    # info
    p_info = subparsers.add_parser("info", help="Quick summary of a .bin file")
    p_info.add_argument("file", help="Path to .bin file")
    p_info.set_defaults(func=cmd_info)

    # verify
    p_verify = subparsers.add_parser("verify", help="Round-trip test: parse → serialize → compare")
    p_verify.add_argument("file", help="Path to .bin file")
    p_verify.set_defaults(func=cmd_verify)

    # export
    p_export = subparsers.add_parser(
        "export", help="Export .bin → folder/zip with images + project.json"
    )
    p_export.add_argument("file", help="Path to .bin file")
    p_export.add_argument("-o", "--output", help="Output path (folder or .zip)")
    p_export.set_defaults(func=cmd_export)

    # build
    p_build = subparsers.add_parser(
        "build", help="Build .bin from folder/zip with project.json + images"
    )
    p_build.add_argument("source", help="Path to folder or .zip file")
    p_build.add_argument("-o", "--output", help="Output .bin file")
    p_build.set_defaults(func=cmd_build)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

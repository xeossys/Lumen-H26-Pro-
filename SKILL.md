---
name: h26-watchface-encoder
description: "Use when working on the Lumen-H26-Pro-Encoder project — parsing, encoding, CLI, tests, or any .bin watchface file. Covers the H26 binary format, the h26/ encoder package, and the main.py parser."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [h26, watchface, encoder, xiaomi, vela, reverse-engineering]
    related_skills: [watchface-conversion, xiaomi-watchface-development]
---

# H26 Watchface Encoder

## When to Use

- Working on the `Lumen-H26-Pro-Encoder` repository (parser, encoder, CLI, tests)
- Parsing or compiling `.bin` H26 watchface files
- Extracting images from watchface binaries
- Debugging the encoder pipeline or the parser
- Adding new UIItem type support

## Quick Reference

### Repository Layout

```
Lumen-H26-Pro-Encoder/
├── main.py                  # Parser + GUI emulator (PyQt6)
├── h26/                     # Encoder package (headless)
│   ├── project.py           # Data model + JSON I/O
│   ├── image_codec.py       # Quantize + LZ4pal32 + JPG blocks
│   ├── encoder.py           # compile() pipeline
│   └── cli.py               # CLI: compile, parse, info, verify
├── tests/                   # 8 test files, 45 tests
│   ├── fixtures/            # 3 real .bin files
│   └── conftest.py          # PyQt6 stubs for headless testing
├── docs/
│   └── h26-watchface-spec-en.md
├── AGENTS.md                # Agent operational notes
└── pyproject.toml           # ruff config
```

### Dependencies

```bash
pip install lz4 Pillow       # encoder
pip install PyQt6             # GUI emulator only
pip install ruff              # linting
```

### Run All Tests

```bash
cd /tmp/Lumen-H26-Pro-Encoder
python3 tests/test_smoke.py
python3 tests/test_real_file.py
python3 tests/test_roundtrip.py
python3 tests/test_encoder.py
python3 tests/test_image_codec.py
python3 tests/test_compile.py
python3 tests/test_image_swap.py
python3 tests/test_cli.py
```

### CLI Commands

```bash
python3 -m h26.cli compile project.json -o out.bin
python3 -m h26.cli parse out.bin          # JSON dump
python3 -m h26.cli info out.bin           # quick summary
python3 -m h26.cli verify out.bin         # round-trip test
```

### Programmatic API

```python
from h26 import Project, Layout, FrameItem, HandItem, AnimationItem, ImageAsset, compile

project = Project(
    name="my_watchface",
    images=[ImageAsset(name="bg", source_path="bg.png", width=240, height=240)],
    layout=Layout(children=[FrameItem(x=0, y=0, image_name="bg")]),
)
data = compile(project)
with open("out.bin", "wb") as f:
    f.write(data)
```

## H26 Binary Format

### Header (0x40 bytes)

| Offset | Size | Field | Encoding |
|--------|------|-------|----------|
| 0x00 | 4 | Magic | `Sb@*` (0x53 0x62 0x40 0x2A) |
| 0x04 | 8 | Watchface name | ASCII (e.g. `O2GG...`) |
| 0x0C | 4 | Preview offset | Big-endian |
| 0x10 | 4 | Preview length | Big-endian |
| 0x14 | 4 | L3 (internal block start) | Big-endian |
| 0x18 | 4 | L3 length | Big-endian |
| 0x1C | 4 | L2 (UI table offset) | Big-endian |

### Graphical Blocks

| Tag | Type | Length field |
|-----|------|-------------|
| `0x4B 0x01` | LZ4pal32 | 4-byte LE at offset+8 |
| `0x48 0x01` | BGR565A | 4-byte LE at offset+8 |
| `0x49 0x01` | BGR565 | 4-byte LE at offset+8 |
| `0x09 0x00` | JPG | 3-byte LE at offset+2 |
| `0x03 0x00` | GIF | 3-byte LE at offset+2 |

LZ4pal32 size encoding: 3 bytes at offset+5, LE 24-bit.
`w = size_val >> 12`, `h = size_val & 0xFFF` (max 4095×4095).

Payload = LZ4 block-compressed stream (compatible with `lz4.block.compress(store_size=False)`).
Layout = 1024-byte BGRA palette (256 entries) + 1 byte per pixel index.

### UI Table

Each UIItem starts with a 5×4-byte **big-endian** header:
`[Type:4b] [SubType:4b] [Align:4b] [X:4b (signed)] [Y:4b (signed)]`

Extended bytes depend on Type:

| Type | Sub | Meaning | Extended format |
|------|-----|---------|----------------|
| 0x00 | 0x8C/0x8D | Layout | `[loops:4b] [count:4b] [indices...]` per group |
| 0x01/0x02 | — | Frame | `[count:4b] [offset:4b] [length:4b]` per frame |
| 0x0F | 0x0B/0x0C/0x0D | Hand | `[count:4b] [rX:4b] [rY:4b] [offset:4b] [length:4b]` |
| 0x14 | 0x34/0x3B | Animation | `[unk:4b] [X:4b] [Y:4b] [count:4b] [off:4b len:4b]...` |
| 0x37 | — | Button | `[unk:4b] [W:4b] [H:4b] [BGR:12b] [screens...]` |
| 0x47/48/4B/4C | — | Angled font | `[count:4b] [dX:4b] [dY:4b] [frames...]` |
| 0x5B | — | Rectangle | `[count:4b] [W:4b] [H:4b] [B:4b] [G:4b] [R:4b]` |

## Critical Gotchas (Read Before Editing)

### Endianness Naming Bug

`main.py`'s byte readers have **backwards names**:
- `vb_get_4b_le` → actually reads **big-endian** (byte[0] = MSB)
- `vb_get_4b_be` → actually reads **little-endian** (byte[0] = LSB)
- `vb_get_3b_be` → actually reads **little-endian**

The encoder uses explicit `struct.pack(">I", ...)` for BE and `struct.pack("<I", ...)` for LE.

### Palette Byte Order

The decoder reads palette as **BGRA** (B at offset+0, G at +1, R at +2, A at +3).
The encoder stores RGBA internally and **swaps R↔B** when writing the palette.

### JPG Block Header

JPG blocks use a **3-byte LE** length at **offset+2** (not 4-byte at offset+8 like LZ4 blocks).

### Layout Extended Bytes

The parser reads Layout children as nested groups: `[loops:4b] × [count:4b + indices...]`.
The encoder emits a single group: `[loops=1:4b] [count:4b] [indices...]`.

### PyQt6 Stubs for Headless Testing

Tests and CLI import `main.py` headlessly by injecting PyQt6 stub modules into `sys.modules`. See `tests/conftest.py` for the pattern.

## Git Conventions

- **Branch model**: Git Flow. `feature/*` → `develop`, `hotfix/*` → `main`.
- **Push policy**: never push without explicit user instruction.
- **Commit prefixes**: `feat:`, `fix:`, `test:`, `docs:`, `chore:`
- **Lint**: `ruff check .` + `ruff format --check .` must pass before commit.

## Extracting Images from a .bin

```python
# Quick extraction (requires Pillow)
import sys, types
from pathlib import Path
from PIL import Image

# ... (inject PyQt6 stubs, then import main.py) ...
b = Path("watchface.bin").read_bytes()
# Scan blocks, decompress LZ4pal32, save as PNG
# See extract_images.py in the repo for the full script.
```

Or use the CLI:
```bash
python3 -m h26.cli info watchface.bin    # see block counts
python3 -m h26.cli parse watchface.bin   # JSON dump with dimensions
```

# AGENTS.md

> Operational notes for AI coding agents (Hermes, Claude Code, OpenCode, Codex, etc.) working in this repository.
> Read this before making any non-trivial change. Andrea (the maintainer) uses multiple AI agents in parallel and expects consistent behavior across them.

## TL;DR

- **Stack**: Python 3.8+, PyQt6 (GUI only), pure-Python LZ4 decoder, `lz4`+`Pillow` for encoder.
- **Lint**: `ruff` (config in `pyproject.toml`). Run `ruff check .` before any commit.
- **Tests**: `python3 tests/test_smoke.py` (parser) + `python3 tests/test_compile.py` (encoder) + `python3 tests/test_roundtrip.py` + `python3 tests/test_real_file.py` + `python3 tests/test_encoder.py` + `python3 tests/test_image_codec.py`. All must pass before any commit.
- **Branch model**: Git Flow. `feature/*` and `fix/*` → `develop`. `hotfix/*` → `main`. Tags use `YYYY.M.D`.
- **Push policy**: agents must NOT push to remote without explicit user instruction. Local git only by default.
- **Credentials**: there are none in this repo. If you find any, stop and tell Andrea.
- **No CSRF, no DNS, no secrets**: standard Andrea rule — don't touch anything that looks like a credential, token, or remote endpoint.

## Repository map

```
Lumen-H26-Pro-Encoder/
├── main.py                  # Parser + GUI emulator (PyQt6, ~1100 lines)
├── h26/                     # Encoder package (headless, no PyQt6 at import)
│   ├── __init__.py          # Public API re-exports
│   ├── project.py           # Data model: Project, Layout, UI items, JSON I/O
│   ├── image_codec.py       # Quantize RGBA→256 pal, LZ4pal32 block, JPG block
│   ├── encoder.py           # compile(project) → bytes pipeline
│   └── cli.py               # CLI: compile, parse, info, verify
├── tests/
│   ├── conftest.py          # PyQt6 stub + build_synthetic_binary() helper
│   ├── test_smoke.py        # Synthetic parser smoke test
│   ├── test_real_file.py    # 3 real fixture structural assertions
│   ├── test_roundtrip.py    # Round-trip + idempotency
│   ├── test_encoder.py      # Data model + JSON I/O
│   ├── test_image_codec.py  # Quantize + block encoding
│   ├── test_compile.py      # Full encoder pipeline integration
│   └── fixtures/
│       ├── Clock20517_res.bin   (91 KB, 14 UI items, 66 blocks)
│       ├── Clock21592_res.bin   (234 KB, 8 UI items, 35 blocks)
│       ├── Clock20493_res.bin   (379 KB, 19 UI items, 85 blocks)
│       └── README.md
├── pyproject.toml           # ruff config (lint rules + per-file ignores)
├── requirements.txt         # PyQt6 only (lz4 + Pillow for encoder)
├── README.md                # User-facing docs
├── CONTRIBUTING.md          # Contribution conventions
├── AGENTS.md                # This file
├── LICENSE                  # MIT
├── docs/                    # Format specs and reference material
│   └── h26-watchface-spec-en.md   # The reverse-engineering spec
└── .gitignore
```

## Public API (stable)

Agents MUST preserve the signatures of:

### Parser (main.py)

- `H26WatchfaceAnalyzer.__init__()`
- `H26WatchfaceAnalyzer.load_file(path: str) -> bool`
- `H26WatchfaceAnalyzer.blocks: list[BlockInfo]`
- `H26WatchfaceAnalyzer.ui_items: list[UIItem]`
- `H26WatchfaceAnalyzer.serialize() -> bytes`
- `UIItem`, `BlockInfo`, `BlockType` classes
- `vb_get_4b_le`, `vb_get_4b_signed_be`, `vb_get_3b_be` byte readers
- `decompress_lz4_vb(b: bytes) -> bytes`

### Encoder (h26/ package)

- `h26.compile(project: Project) -> bytes`
- `h26.Project`, `h26.Layout`, `h26.FrameItem`, `h26.HandItem`, `h26.AnimationItem`, `h26.ImageAsset`
- `h26.build_lz4pal32_block(rgba, width, height) -> bytes`
- `h26.build_jpg_preview_block(jpg_bytes) -> bytes`

### CLI (h26/cli.py)

- `python3 -m h26.cli compile <project.json> [-o output.bin]`
- `python3 -m h26.cli parse <file.bin>`
- `python3 -m h26.cli info <file.bin>`
- `python3 -m h26.cli verify <file.bin>`

## Important domain concepts

- **H26**: the proprietary binary format used by Vela OS watchfaces. Header → Graphical blocks → UI Table.
- **Magic header**: `0x53 0x62 0x40 0x2A` (ASCII `Sb@*`). Every valid `.bin` starts with this.
- **Graphical blocks**: LZ4-compressed image data. Types: LZ4pal32 (`0x4B 0x01`), BGR565A (`0x48 0x01`), BGR565 (`0x49 0x01`), JPG (`0x09 0x00`), GIF (`0x03 0x00`).
- **UI Table**: a flat sequence of UIItems. Each starts with a 5×4-byte big-endian header (Type, SubType, Align, X, Y). The parser's `_parse_ui_table_fixed` handles all known types.
- **Endianness warning**: `vb_get_4b_le` is actually **big-endian** and `vb_get_4b_be` is actually **little-endian**. The names are backwards. The encoder uses explicit `struct.pack(">I", ...)` for BE and `struct.pack("<I", ...)` for LE to avoid confusion.
- **PyQt6 stubs**: the test suite and CLI import `main.py` headlessly by injecting PyQt6 stub modules into `sys.modules` before import. See `tests/conftest.py` for the pattern.

## Commit checklist

Before ANY commit that touches the parser or encoder:

1. `python3 -m py_compile main.py` — smoke compile
2. `ruff check .` — must be clean
3. `ruff format --check .` — must be clean
4. `python3 tests/test_smoke.py` — `ALL SMOKE TESTS PASSED ✅`
5. `python3 tests/test_real_file.py` — `ALL 3 REAL-FILE FIXTURE(S) PASSED ✅`
6. `python3 tests/test_roundtrip.py` — `ALL ROUND-TRIP TESTS PASSED ✅`
7. `python3 tests/test_encoder.py` — `ALL ENCODER PROJECT TESTS PASSED`
8. `python3 tests/test_image_codec.py` — `ALL IMAGE CODEC TESTS PASSED`
9. `python3 tests/test_compile.py` — `ALL COMPILE INTEGRATION TESTS PASSED`

If ANY test fails, do not commit. Fix it first.

## Things to watch out for

- `vb_get_4b_le` is actually big-endian (see above). Don't trust the name.
- The UI Table parser handles sub-records by advancing a `pos` pointer. If you add a new UIItem type, you MUST correctly calculate the sub-record length or the parser will misalign every subsequent item.
- The `serialize()` method concatenates raw bytes. It does NOT re-serialize. This is intentional: it proves the parser is lossless.
- `QImage` uses `Format_ARGB32` with BGRA byte order in memory. When converting to/from raw bytes, channels are swapped.
- The encoder's palette serialization swaps R↔B (RGBA→BGRA) to match the decoder's expectations. See `h26/image_codec.py`.
- The JPG block header uses a 3-byte LE length at offset+2 (not 4-byte at offset+8 like LZ4 blocks). See `h26/image_codec.py:build_jpg_preview_block`.
- The Layout UI item's extended bytes use a nested group format: `[loops:4b] [count:4b] [indices...]`. See `h26/encoder.py:_encode_layout`.

## Test fixtures

Three real `.bin` files in `tests/fixtures/`:

| Fixture | Size | UI Items | Blocks | Notable |
|---|---|---|---|---|
| Clock20517_res.bin | 91 KB | 14 | 66 LZ4pal32 | Regular + AOD layouts, 3 hands × 2 layouts, 1 animation |
| Clock21592_res.bin | 234 KB | 8 | 35 LZ4pal32 | Single layout, 2 hands (minute+second), 2 animations |
| Clock20493_res.bin | 379 KB | 19 | 85 LZ4pal32 | Richest: 3 system-screen buttons (Type 37), 7 angled fonts (Type 47) with negative dX/dY |

All three round-trip byte-perfectly through `serialize()`.

## Git conventions

- `feat:`, `fix:`, `test:`, `docs:`, `chore:` — conventional commit prefixes
- `Merge --no-ff feature/xyz into develop` — merge commits always
- No rebasing, no force-push, no squashing (keeps history clean)
- Tags on `main` only: `YYYY.M.D`

# ⌚ OpenLumen H26pro+
> **An Open-Source Reverse-Engineering & Modding Studio for H26 Smartwatches.**

![Python Version](https://img.shields.io/badge/python-3.8%2B-blue.svg)
![PyQt6](https://img.shields.io/badge/PyQt-6-green.svg)
![Ruff](https://img.shields.io/badge/lint-ruff-orange.svg)
![Contributions](https://img.shields.io/badge/contributions-welcome-orange.svg)
![License](https://img.shields.io/badge/license-MIT-purple.svg)

**OpenLumen H26pro+** is a pure-Python reverse-engineering and modding suite for H26 smartwatch watchfaces. It can **decompile**, **analyze**, **compile**, and **verify** `.bin` watchface files — bridging the gap between raw binary and visual design.

---

## 🙏 Credits & Acknowledgments

**Full Credit:**
This Python version was ported and is fully based on the watchface analyzer and all binary data provided by **[@vx_vxsw](https://t.me/vx_vxsw)** on Telegram. All credit for the original reverse-engineering research, structural analysis, and data mapping goes entirely to him!

The UI Table parser was hardened against the [H26 Watchface File Format Specification](https://github.com/paraflu/Lumen-H26-Pro-Encoder/blob/main/docs/h26-watchface-spec-en.md) (reverse-engineering worksheet) — every UIItem type the spec lists is now actually decoded into structured fields.

---

## ✨ Current Features

* **Full Decompilation & Extraction:** Unpacks `.bin` files, maps memory
  offsets and UI tables, extracts all image layers (PNG, JPG, GIF).
* **Encoder (v1):** Compiles a `Project` JSON + PNG/JPG assets into a
  valid `.bin` watchface (`h26/encoder.py`). Supports Layout, Frame,
  Hand, Animation items. Byte-perfect round-trip on 3 real fixtures.
* **CLI:** `python3 -m h26.cli compile|parse|info|verify|export|build` — no PyQt6
  needed for parse/info/verify/export/build. See [CLI section](#-cli).
* **Zero-Dependency LZ4 Decoder:** Pure-Python LZ4 decompression (no C
  extensions). The encoder uses `lz4` (`pip install lz4`).
* **Live Watchface Emulator:** Real-time PyQt6 canvas with moving hands.
* **Spec-aligned UI Table parsing:** Every UIItem type from the H26 spec:
  * **Type 0** — Layout (regular + AOD) with UIItem indexes
  * **Type 0xF** — Hands (hour / minute / second) with rotation pivots
  * **Type 0x14** — Animations (both `0x34`/`0x3B` and the extended `0x70` variant)
  * **Type 0x37** — System-screen buttons with the decoded NUL-terminated
    screen list (`WeatherScreen`, `CompassScreen`, `StepDetailScreen`,
    `HRScreen`) available on `UIItem.system_screens`
  * **Type 0x47 / 0x48 / 0x4B / 0x4C** — Angled fonts, with the `dX`/`dY`
    position-shift vector available on `UIItem.data_values`
  * **Type 0x5B** — Solid-color rectangles (width, height, BGR color)
  * **Type 1/2/3/5/6/0x18/0x56** — Generic font / image frames
* **Header introspection:** the analyzer exposes
  `wf_name`, `preview_offset`, the internal-block offset/length
  (`l3`/`l4`) and the UI table offset (`l2`) as named attributes.
* **Unknown-block bookkeeping:** block tags that don't match any known
  type are recorded in `analyzer.unknown_blocks` (with the raw 2-byte
  tag) instead of being silently dropped — this is the main hook for
  the Compiler / Repacker work.
* **Tolerant parsing:** malformed UIItem sub-records are logged at
  `DEBUG` level and the parser advances to the next item rather than
  aborting the whole file.

---

## 🛠 Requirements

* Python **3.8+**
* [uv](https://docs.astral.sh/uv/) (recommended) or pip for dependency management
* PyQt6 — only for the GUI emulator
* `lz4` — for the encoder
* `Pillow` — for loading PNG/JPG in the encoder
* [`ruff`](https://docs.astral.sh/ruff/) for linting
---

## 🚀 Quick Start

```bash
git clone https://github.com/paraflu/Lumen-H26-Pro-Encoder.git
cd Lumen-H26-Pro-Encoder

# With uv (recommended)
uv sync
uv run python main.py

# Or with pip
pip install -r requirements.txt
python3 main.py
```

Then **File → Open** any H26 `.bin` watchface file. The GUI will:
1. Display the watchface preview
2. Render the live clock with moving hands
3. List all decoded blocks and UIItems in the side panel

### Programmatic use

```python
from main import H26WatchfaceAnalyzer

an = H26WatchfaceAnalyzer()
an.load_file("my_watchface.bin")

print("Name:", an.wf_name)
print("UI Table offset:", an.l2)
print(f"Decoded {len(an.ui_items)} UI items")
for item in an.ui_items:
    print(
        f"  type=0x{item.item_type:X}  x={item.x}  y={item.y}  "
        f"data={item.data_values}  screens={item.system_screens}"
    )
```

---

## 🧪 Development

### Setup

```bash
# Install all dependencies (including dev tools)
uv sync --all-extras
```

### Run the tests

The repo includes a comprehensive test suite under `tests/`:

```bash
uv run python tests/test_smoke.py          # synthetic parser smoke test
uv run python tests/test_real_file.py      # 3 real fixture assertions
uv run python tests/test_roundtrip.py      # round-trip + idempotency
uv run python tests/test_encoder.py        # encoder data model + JSON I/O
uv run python tests/test_image_codec.py    # image quantization + block encoding
uv run python tests/test_compile.py        # full encoder pipeline integration
```
Expected last line for each: `ALL ... PASSED ✅`.

### Linting

The project uses [ruff](https://docs.astral.sh/ruff/) for linting. The
configuration lives in `pyproject.toml`.

```bash
uv run ruff check .          # lint
uv run ruff format --check . # style (read-only)
uv run ruff format .         # auto-format
```

The config enables the rules that catch real bugs (`F`, `BLE`, `S`)
plus the cheap mechanical ones (`I` import sort, `UP` pyupgrade, `SIM`
simplify, `PLR` pylint refactor) and disables the noisy style rules
that don't add value to a PyQt6 desktop tool with inline CSS strings
and binary offsets (see the comment block in `pyproject.toml` for the
full rationale).

### Project conventions

* Git Flow: `feature/*` and `fix/*` branches merge into `develop`,
  `hotfix/*` branches merge into `main`, tags use the `YYYY.M.D`
  format. See [CONTRIBUTING.md](CONTRIBUTING.md).
* Public API: `H26WatchfaceAnalyzer`, `UIItem`, `BlockInfo`,
  `BlockType` and the `vb_get_*` byte-readers are considered stable.
  Everything else is internal.
* Prefer logging (`logging.debug` / `logging.warning`) over `print`
  for diagnostics — the GUI's `QStatusBar` reads from the logging
  system.


---

## 🔨 Building Executables

Build standalone executables for distribution:

```bash
# Install PyInstaller
uv sync --all-extras

# Build for current platform
uv run python build.py

# Clean build artifacts
uv run python build.py --clean
```

The executable will be created in `dist/LumenH26Pro/`.

### CI/CD Releases

The project uses GitHub Actions to automatically build executables when a tag is pushed:

```bash
# Create and push a tag
git tag 2024.1.1
git push origin 2024.1.1
```

This will create a GitHub Release with:
- `LumenH26Pro-linux-x86_64.tar.gz` — Linux executable
- `LumenH26Pro-windows-x86_64.zip` — Windows executable

---

## 📐 System Architecture & Parsing Pipeline

```text
  +-----------------------+
  |  Raw H26 .bin File    |
  +-----------+-----------+
              |
              v
  +-----------------------+   Check Magic Header (0x53 0x62 0x40 0x2A "Sb@*")
  |  Magic Header Check   |--> Read UI Table Pointer (L2 at 0x1C)
  +-----------+-----------+    Read Memory Boundaries (L3, L4)
              |                Read Watchface Name (from trailing block)
              v
  +-----------------------+   Iterate Memory Chunks from Offset 0x0C
  | Memory Block Scanner  |--> Read Block Headers (2-byte Magic Tags)
  +-----------+-----------+    Decompress LZ4 Payload (Pure Python)
              |                Record unknown block tags for later analysis
              v
  +-----------------------+   Parse UI Structs at L2 Offset
  |   UI Table Decoder    |--> Extract (X, Y) Coordinates & Element Types
  +-----------+-----------+    Harvest Image Offset Pointers
              |                Decode system-screens (Type 37)
              |                Decode dX/dY shift (Type 47/48/4B/4C)
              |                Decode BGR color (Type 5B)
              v
  +-----------------------+
  |  Live Emulator Canvas |
  +-----------------------+
```

### Supported Memory Blocks

| Compression / Block | ID Header | Description |
|---|---|---|
| LZ4 Palette32 | `0x4B 0x01` | 8-bit Indexed Palette (256 Colors) |
| LZ4 RGB565 + A | `0x48 0x01` | 16-bit RGB565 with Alpha Channel |
| LZ4 RGB565 | `0x49 0x01` | 16-bit RGB565 Opaque |
| JPEG Graphic | `0x09 0x00` | Standard Compressed Image |
| GIF Graphic | `0x03 0x00` | Standard Compressed Image |
| Unknown | *other* | Logged to `analyzer.unknown_blocks` |

### Supported UIItem Types

| Type | Subtype | Meaning | Parser Output |
|---|---|---|---|
| `0x00` | `0x8C` / `0x8D` | Layout (regular / AOD) | UIItem indexes list |
| `0x0F` | `0x0B`/`0x0C`/`0x0D` | Hour/Minute/Second hand | Pivots + frame refs |
| `0x14` | `0x34`/`0x3B`/`0x70` | Animation | Frame refs |
| `0x37` | — | System-screen button | `data_values=[unk, W, H]`, `system_screens=[...]` |
| `0x47`/`0x48`/`0x4B`/`0x4C` | — | Angled font | `data_values=[dX, dY, ...]`, frame refs |
| `0x5B` | — | Solid rectangle | `data_values=[counter, W, H, B, G, R]` |
| `0x01`/`0x02`/`0x03`/`0x05`/`0x06`/`0x18`/`0x56` | — | Font / image frames | Frame refs |

---

## 🔧 CLI

The `h26.cli` module provides six commands. No PyQt6 needed for
`parse`, `info`, `verify`, `export`, and `build`.

```bash
# Compile a project JSON into a .bin watchface
uv run python -m h26.cli compile project.json -o watchface.bin

# Parse a .bin and dump its structure as JSON
uv run python -m h26.cli parse watchface.bin

# Quick summary (header fields, block counts)
uv run python -m h26.cli info watchface.bin

# Round-trip test: parse → serialize → compare
uv run python -m h26.cli verify watchface.bin

# Export a .bin to a folder with images + project.json
uv run python -m h26.cli export watchface.bin -o project/

# Export a .bin to a zip archive
uv run python -m h26.cli export watchface.bin -o project.zip

# Build a .bin from a folder or zip with project.json + images
uv run python -m h26.cli build project/ -o watchface.bin
uv run python -m h26.cli build project.zip -o watchface.bin
```

You can also use the shortcut `cli.py`:

```bash
uv run python cli.py export watchface.bin -o project/
uv run python cli.py build project/ -o watchface.bin
```

Example `info` output:

```
File:    Clock20493_res.bin
Size:    378,952 bytes
Magic:   Sb@* ✓
Preview: 0x20
L3:      0x12C15 (len 0x5ECF)
L2 (UI): 0x5C29E

Blocks (85 total):
  LZ4pal32: 85

UI table: 1,450 bytes at 0x5C29E
```

---

## ✅ Encoder (v1)

The encoder (`h26/encoder.py`) compiles a `Project` data model into a
valid `.bin` watchface file. It is the inverse of the parser:
PNG/JPG assets → LZ4pal32 blocks → H26 binary.

**What v1 supports:**
- LZ4pal32 image blocks (8-bit paletted, 256 colors)
- JPG preview blocks
- UI items: Layout (0x00), Frame (0x01), Hand (0x0F), Animation (0x14)
- Byte-perfect round-trip: `compile(project)` → `analyzer.serialize()` → identical bytes

**What v1 does NOT support (contributions welcome):**
- BGR565 / BGR565A blocks
- AOD layouts (sub-type 0x8D)
- Type 37 (system-screen buttons), 47/48/4B/4C (angled fonts), 5B (solid rectangles)
- Animation frame-by-frame editing in the GUI

### Quick start (programmatic)

```python
from h26 import Project, Layout, FrameItem, ImageAsset, compile

project = Project(
    name="my_watchface",
    images=[ImageAsset(name="bg", source_path="bg.png", width=240, height=240)],
    layout=Layout(children=[FrameItem(x=0, y=0, image_name="bg")]),
)
data = compile(project)
with open("my_watchface.bin", "wb") as f:
    f.write(data)
```

Requires `lz4` and `Pillow` (installed automatically with `uv sync`).

### Export & Build (CLI)

The CLI also supports exporting a `.bin` to a folder/zip and rebuilding it:

```bash
# Export: .bin → folder with images + project.json
uv run python -m h26.cli export watchface.bin -o project/

# Build: folder/zip → .bin
uv run python -m h26.cli build project/ -o watchface.bin
```

### Test suite

```bash
uv run python tests/test_encoder.py        # data model + JSON I/O (7 tests)
uv run python tests/test_image_codec.py    # quantize + block encoding (10 tests)
uv run python tests/test_compile.py        # full pipeline integration (7 tests)
uv run python tests/test_smoke.py          # synthetic parser smoke test
uv run python tests/test_real_file.py      # 3 real fixture assertions
uv run python tests/test_roundtrip.py      # round-trip + idempotency
```

---

## 🚧 Roadmap: GUI Encoder Tab (contributions welcome)

The encoder CLI/API is complete. The next step is a **GUI tab** in
the existing PyQt6 app that lets users:

1. Drag-and-drop PNG/JPG assets onto a virtual canvas
2. Position UI items (frames, hands, animations) visually
3. Click "Compile" to produce a valid `.bin` file
4. "Test load" → re-parse the compiled file in the existing View tab

See the implementation plan in `~/.hermes/plans/h26-encoder.md`
(Tasks 11-13) for the detailed wireframe and code structure.

**What remains to be built:**
1. **GUI Encoder Tab** (Tasks 11-13): PyQt6 interface with drag-and-drop
   canvas, property editing, and a "Compile" button. See the plan.
2. **BGR565 / BGR565A block encoding**: currently only LZ4pal32 is supported.
3. **AOD layout support** (sub-type 0x8D): the parser reads it but the
   encoder doesn't emit it yet.
4. **Additional UIItem types**: 0x37 (buttons), 0x47/48/4B/4C (angled
   fonts), 0x5B (solid rectangles) — the parser decodes them but the
   encoder rejects them with a clear error message.

If you want to contribute, please fork the repository, open a Pull
Request, or start a discussion in the Issues tab!

---

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

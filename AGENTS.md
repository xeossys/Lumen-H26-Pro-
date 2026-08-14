# AGENTS.md

> Operational notes for AI coding agents (Hermes, Claude Code, OpenCode, Codex, etc.) working in this repository.
> Read this before making any non-trivial change. Andrea (the maintainer) uses multiple AI agents in parallel and expects consistent behavior across them.

## TL;DR

- **Stack**: Python 3.8+, PyQt6, pure-Python LZ4. No C extensions.
- **Lint**: `ruff` (config in `pyproject.toml`). Run `ruff check .` before any commit.
- **Smoke test**: `python3 _smoke_test.py` must end with `ALL SMOKE TESTS PASSED ✅` before any commit that touches the parser.
- **Branch model**: Git Flow. `feature/*` and `fix/*` → `develop`. `hotfix/*` → `main`. Tags use `YYYY.M.D`.
- **Push policy**: agents must NOT push to remote without explicit user instruction. Local git only by default.
- **Credentials**: there are none in this repo. If you find any, stop and tell Andrea.
- **No CSRF, no DNS, no secrets**: standard Andrea rule — don't touch anything that looks like a credential, token, or remote endpoint.

## Repository map

```
Lumen-H26-Pro-Encoder/
├── main.py              # The whole parser + GUI in one file (PyQt6)
├── _smoke_test.py       # Synthetic-binary smoke test (run before commits)
├── pyproject.toml       # ruff config (lint rules + per-file ignores)
├── requirements.txt     # PyQt6 only
├── README.md            # User-facing docs
├── CONTRIBUTING.md      # Contribution conventions
├── AGENTS.md            # This file
├── LICENSE              # MIT
├── docs/                # Format specs and reference material
│   └── h26-watchface-spec-en.md   # The reverse-engineering spec
└── .gitignore
```

## Public API (stable)

Agents MUST preserve the signatures of:

- `H26WatchfaceAnalyzer.__init__()`
- `H26WatchfaceAnalyzer.load_file(path: str) -> bool`
- `H26WatchfaceAnalyzer.blocks: List[BlockInfo]`
- `H26WatchfaceAnalyzer.ui_items: List[UIItem]`
- `H26WatchfaceAnalyzer.unknown_blocks: List[BlockInfo]`  *(new in v1.1)*
- `H26WatchfaceAnalyzer.wf_name: str`  *(new in v1.1)*
- `H26WatchfaceAnalyzer.preview_offset: int`  *(new in v1.1)*
- `UIItem.item_type`, `x`, `y`, `data_values`, `frame_indices`, `pointer_offsets`
- `UIItem.system_screens: List[str]`  *(new in v1.1, populated for Type 37)*
- `BlockInfo.base_offset`, `raw`, `b_type`, `qimage`
- `BlockType` enum
- `decompress_lz4_vb(data: bytes) -> bytes`
- `vb_get_4b_be`, `vb_get_4b_le`, `vb_get_4b_signed_be`, `vb_get_3b_be`

## Parser rules (DO NOT BREAK)

The parser must remain **tolerant**: malformed sub-records log at DEBUG
and the parser advances to the next UIItem rather than aborting the
whole file. This is critical for the reverse-engineering use case —
a real H26 `.bin` file is full of proprietary, undocumented, or
half-decoded sub-records.

Specific invariants:

- The 4-byte magic header `0x53 0x62 0x40 0x2A` ("Sb@*") MUST be checked first.
- All integer reads in the UI Table are **signed big-endian** (`vb_get_4b_signed_be`). The legacy `vb_get_4b_signed_le` is an alias.
- Unknown block tags are **recorded**, not skipped silently. Use `analyzer.unknown_blocks` for this.
- `_convert_block_to_image` must never raise — return `None` on bad input.

## Adding a new UIItem type

1. Read `docs/h26-watchface-spec-en.md` §4 carefully.
2. Add the type to the if/elif chain in `_parse_ui_table_fixed` in `main.py`.
3. **Decode all named fields into `UIItem.data_values`** (and add a dedicated list attribute if the field is a string, e.g. `system_screens`).
4. Compute `l1` (the byte length of this item including the 20-byte header) defensively: if your offset math could overflow, use `pos + l1 > tpos` as a guard and fall back to `l1 = tpos - pos`.
5. **Extend `_smoke_test.py`** with a synthetic UIItem of the new type and assert the parsed fields.
6. Update the "Supported UIItem Types" table in `README.md`.

## Adding a new Block type

1. Add the 2-byte tag detection in `H26WatchfaceAnalyzer.load_file` (the `while pos < tpos` loop, `if/elif` chain).
2. Implement the decode in `_convert_block_to_image` (return a `QImage` or `None`).
3. Add a new `BlockType` enum value.
4. Document in the "Supported Memory Blocks" table in `README.md`.

## Commit hygiene

- One logical change per commit. Don't bundle lint fixes with parser changes unless they touch the same lines.
- Commit messages: imperative mood, ≤ 72 char subject, blank line, body explaining *why* (not what).
- Reference any spec section (e.g. `per docs/h26-watchface-spec-en.md §4.6`) in the body when the change is a spec-driven parser improvement.

## Tool preferences

- **Linter**: `ruff` (already configured).
- **Formatter**: `ruff format` (PEP 8 + ruff's defaults).
- **Type checker**: none currently. Don't add `mypy` or `pyright` without Andrea's say-so — the codebase uses runtime duck typing extensively.
- **Test runner**: plain `python3 _smoke_test.py`. Don't introduce `pytest` / `unittest` for the parser until the test suite grows beyond a single file.
- **Build**: not applicable (pure Python).

## Communication

- When in doubt: **stop and ask**. Andrea prefers a clarifying question over a wrong assumption (rule: "azione > domande" applies only when the action is reversible and low-risk — parser logic is neither).
- Report test results in the form `ALL SMOKE TESTS PASSED ✅` or quote the exact failure line. Don't paraphrase.
- Never log the raw binary content of a real watchface file — it may contain identifying information.

## See also

- `CONTRIBUTING.md` — the human-facing version of these conventions.
- `README.md` — feature list, quick start, architecture diagram.
- `docs/h26-watchface-spec-en.md` — the canonical format spec the parser implements.

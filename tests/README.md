# Tests

Three test files, each runnable as a standalone Python script. The
project deliberately avoids `pytest` / `unittest` until the test
suite grows beyond a handful of files (see CONTRIBUTING.md).

## Files

| File | Purpose |
|---|---|
| `conftest.py` | Shared PyQt6 stub + path constants. Imported by every other test file. |
| `test_smoke.py` | Synthetic-binary smoke test. Builds a minimal valid H26 file in-memory that exercises every parser path the spec-gap patches touched (Type 37, 47, 5B, 14) and asserts the analyzer extracts every named field. |
| `test_real_file.py` | Structural assertions on the real fixture `fixtures/Clock20517_res.bin` — block counts, UI table composition, hand pivots, byte-perfect serialize() round-trip. |
| `test_roundtrip.py` | Pure round-trip + idempotency tests. Verifies `analyzer.serialize()` produces byte-perfect output for both the synthetic and real files, and that re-parsing the serialized output yields the same structure. |

## Running

```bash
python3 tests/test_smoke.py
python3 tests/test_real_file.py
python3 tests/test_roundtrip.py
```

Each script ends with `ALL ... TESTS PASSED ✅` on success and exits
non-zero on failure. Suitable for `pre-commit` and CI.

## Why the PyQt6 stub?

`main.py` imports PyQt6 at module top because the file is also a GUI
app. We don't want every test to drag in Qt just to exercise the pure
parser logic, so `conftest.py` installs a tiny stub (QtCore, QtGui,
QtWidgets with only the methods the parser calls). If real PyQt6 is
already importable we use it; the stub only kicks in when it's not.

## Adding a new test

1. Pick the most specific file: synthetic-only → `test_smoke.py`,
   real-fixture-specific → `test_real_file.py`, both → `test_roundtrip.py`.
2. Build a synthetic payload or load the fixture.
3. Parse it, assert semantic fields, exit with a clear error message.
4. Keep the script standalone (no `pytest` dependency) — the test
   runner is just `python3 tests/<your_test>.py`.

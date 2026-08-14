# Contributing to OpenLumen H26pro+

Thank you for your interest in contributing! OpenLumen is a pure-Python
reverse-engineering and modding suite for H26 smartwatch watchfaces.
Contributions of all sizes are welcome — bug reports, documentation
fixes, new parser features, new emulator widgets, and especially
**work on the Compiler & Repacker** (see the README roadmap).

## Quick checklist

Before opening a Pull Request, make sure:

- [ ] You branched from `develop` (not `main`).
- [ ] `python3 _smoke_test.py` ends with `ALL SMOKE TESTS PASSED ✅`.
- [ ] `ruff check .` reports no errors.
- [ ] `ruff format --check .` reports no changes needed (or run `ruff format .` first).
- [ ] You added a smoke-test case if you touched the parser.
- [ ] You updated the relevant tables in `README.md` (UIItem types, Block types).
- [ ] Your commit messages are imperative-mood, ≤ 72 char subject, with a body explaining the *why*.

## Git Flow

We follow the [Git Flow](https://nvie.com/posts/a-successful-git-branching-model/) branching model.

| Branch type | Created from | Merges into | Tag format |
|---|---|---|---|
| `feature/*` | `develop` | `develop` (via PR) | — |
| `fix/*` | `develop` | `develop` (via PR) | — |
| `hotfix/*` | `main` | `main` (via PR) | `YYYY.M.D` |
| `release/*` | `develop` | `main` + `develop` | `YYYY.M.D` |

```
*─── main  ─────●──────────────────●───  (tags: 2026.8.14, 2026.9.1, ...)
│               ↑                  ↑
│          hotfix/X          release/2026.9.1
│
└── develop  ──●──●──●──●──●──●──●──●──
              └──┘  └─┘  └──┘
              feature/...   fix/...
```

### Workflow

```bash
# 1. Make sure you're on develop and up to date
git checkout develop
git pull origin develop

# 2. Create a feature branch
git checkout -b feature/my-new-thing

# 3. Make your changes, commit often
git commit -m "feat: describe the change"

# 4. Before pushing: run the smoke test + linter
python3 _smoke_test.py
ruff check .
ruff format --check .

# 5. Push and open a PR against `develop` (NOT `main`)
git push origin feature/my-new-thing
gh pr create --base develop --title "feat: my new thing" --body "..."
```

## Commit message format

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short description>

<optional body>

<optional footer>
```

Common types:

- `feat` — new user-facing feature
- `fix` — bug fix
- `refactor` — no behavior change
- `docs` — README, CONTRIBUTING, AGENTS.md, docstrings
- `test` — smoke test, integration test
- `chore` — tooling, linting, dependencies, CI

Examples:

```
feat(parser): decode Type 37 system-screen list

Per docs/h26-watchface-spec-en.md §4.8, Type 37 UIItems carry a
30-byte NUL-terminated list of system screen names
(WeatherScreen, CompassScreen, StepDetailScreen, HRScreen).
Previously the parser only consumed l1 = 0x3E without surfacing
any of the fields. Now they land in UIItem.system_screens.
```

```
fix(lint): replace try/except: pass with contextlib.suppress

Ruff S110 / SIM105. The original code silently swallowed decode
errors in a loop. Use contextlib.suppress(UnicodeDecodeError) and
fall back to errors='replace' for the rare invalid byte sequence.
```

## Parser contributions (the interesting ones)

If you're working on the parser (the `_parse_ui_table_fixed` method
in `main.py`), please:

1. **Reference the spec section** you're implementing in your commit
   message. The canonical spec lives at `docs/h26-watchface-spec-en.md`.
2. **Decode all named fields**, not just enough to skip the item. We
   want the analyzer to be a useful RE tool, not just a "make the
   GUI not crash" tool.
3. **Tolerate malformed data**. Wrap risky reads in
   `except (ValueError, IndexError, struct.error)` and `logging.debug`
   the failure. The parser must never abort the whole file on one bad
   sub-record.
4. **Record unknowns**. If you encounter a block tag or UIItem type
   that's not in the spec, add it to `analyzer.unknown_blocks` (or
   `UIItem.unknown_fields`) with the raw bytes. This is how we crack
   new formats.

## Linting and formatting

We use [ruff](https://docs.astral.sh/ruff/). The config in
`pyproject.toml` deliberately enables the bug-catching rule families
(`F`, `BLE`, `S`) plus the cheap mechanical ones (`I`, `UP`, `SIM`,
`PLR`) and disables the noisy style rules that don't add value to a
PyQt6 desktop tool (see the comment block in `pyproject.toml` for the
full rationale).

```bash
ruff check .            # lint
ruff format .           # auto-format
ruff format --check .   # check without writing
```

If you must add a new ignore (e.g. for a one-off import), add a
comment explaining *why*, don't just `# noqa` silently.

## Adding tests

The smoke test (`_smoke_test.py`) is intentionally a single-file
plain-`assert` script. If you touch the parser:

1. Add a new `UIItem` payload to the synthetic binary.
2. Add a `print` and `assert` for the parsed fields.
3. Verify the last line of output is `ALL SMOKE TESTS PASSED ✅`.

If the smoke test ever needs to grow beyond a single file, switch
to `pytest` (and update the CI workflow, if any, accordingly) — but
don't introduce `pytest` just for one test.

## Reporting bugs

Open a GitHub Issue with:

- A minimal H26 `.bin` file that reproduces the problem (if possible).
- The exact error message or wrong output.
- The expected behavior.
- Your Python version (`python3 --version`) and OS.

**Do NOT paste the entire `.bin` file content into the issue** —
it may contain identifying information about the original watchface
designer.

## Code of conduct

Be kind, be patient, and remember that this project is built on the
generous reverse-engineering work of **[@vx_vxsw](https://t.me/vx_vxsw)**.
Credit where credit is due.

## License

By contributing, you agree that your contributions will be licensed
under the MIT License (see [LICENSE](LICENSE)).

# pytest-cov-affected

[![CI](https://github.com/AI-Colleagues/pytest-cov-affected/actions/workflows/ci.yml/badge.svg?event=push)](https://github.com/AI-Colleagues/pytest-cov-affected/actions/workflows/ci.yml?query=branch%3Amain)

A pytest plugin that runs only the tests for source modules you changed and
reports coverage exclusively for those modules.

## Why

Running the full test suite and full coverage report on every change is slow
and the resulting coverage number is diluted by code you didn't touch. With
`--cov-affected`, pytest collects only `tests/<rel>/test_<module>.py` for the
`src/<pkg>/<rel>/<module>.py` files in your local staged/unstaged changes. If
the tree is clean, it falls back to comparing against the merge-base with
`main`. Any subsequent `coverage html` / `coverage xml` reports contain rows
only for those modules.
`--cov` is optional and does not change the affected set.

## Install

```bash
uv add --dev pytest-cov-affected
# or
pip install pytest-cov-affected
```

## Usage

```bash
# run only tests for modules changed in local edits, or since merge-base with main
pytest --cov-affected

# show the coverage table without needing `--cov`
pytest --cov-affected --cov-report term-missing

# optional: also enable pytest-cov terminal reporting
pytest --cov-affected --cov

# pick a different diff base
pytest --cov-affected --cov-affected-base=origin/release

# include new untracked .py files under src/
pytest --cov-affected --cov-affected-include-untracked

# follow up with coverage reports — these will only contain affected modules
coverage html
coverage xml
```

## Convention

The plugin assumes the standard `src/` layout:

```
src/<package>/path/to/module.py    ⇒    tests/path/to/test_module.py
```

Configurable via:

- `--cov-affected-src-root` (default: `src`)
- `--cov-affected-tests-root` (default: `tests`)

Source files without a matching test file produce a `UserWarning` and are
counted in the summary line — they don't fail the run.

## How it works

1. Local staged/unstaged changes are checked first; if any exist, their changed
   `.py` files under `src_root` become the affected set.
2. If there are no local changes, `git diff` against the configured base
   produces the list of changed `.py` files under `src_root`.
3. Each path is mapped to its expected test file; missing tests are reported.
4. Pytest's collection is narrowed to the matching test files only.
5. The active `coverage.py` instance's `include` patterns are constrained to
   the affected sources so measurement is scoped, or a managed coverage
   session is started when `pytest-cov` is not active.
6. At session end, the `.coverage` SQLite data file is filtered in place so
   later `coverage html` / `coverage xml` calls report only affected modules.
   A `.coveragerc.affected` sidecar is written alongside for users who prefer
   `coverage --rcfile`.

## Documentation

See [docs/](docs/):

- [Requirements](docs/1_requirements.md)
- [Design](docs/2_design.md)
- [Plan](docs/3_plan.md)

## Development

```bash
uv sync
uv run pytest
```

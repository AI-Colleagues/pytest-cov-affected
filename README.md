# pytest-cov-affected

[![CI](https://github.com/AI-Colleagues/pytest-cov-affected/actions/workflows/ci.yml/badge.svg?event=push)](https://github.com/AI-Colleagues/pytest-cov-affected/actions/workflows/ci.yml?query=branch%3Amain)

A pytest plugin that runs only the tests for source modules you changed and
reports coverage exclusively for those modules.

## Why

Running the full test suite and full coverage report on every change is slow
and the resulting coverage number is diluted by code you didn't touch. With
`--cov-affected`, pytest collects only `tests/<rel>/test_<module>.py` for the
`src/<pkg>/<rel>/<module>.py` files in your current diff, and any subsequent
`coverage html` / `coverage xml` reports contain rows only for those modules.

## Install

```bash
uv add --dev pytest-cov-affected
# or
pip install pytest-cov-affected
```

## Usage

```bash
# run only tests for modules changed since merge-base with main
pytest --cov-affected

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

1. `git diff` against the configured base produces the list of changed `.py`
   files under `src_root`.
2. Each path is mapped to its expected test file; missing tests are reported.
3. Pytest's collection is narrowed to the matching test files only.
4. The active `coverage.py` instance's `include` patterns are constrained to
   the affected sources so measurement is scoped.
5. At session end, the `.coverage` SQLite data file is filtered in place so
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

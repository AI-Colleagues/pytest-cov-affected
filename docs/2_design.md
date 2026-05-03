# Design Document

## For pytest-cov-affected

- **Version:** 0.1
- **Author:** Shaojie Jiang
- **Date:** 2026-05-03
- **Status:** Draft

---

## Overview

`pytest-cov-affected` is a pytest plugin that adds a `--cov-affected` CLI option. When enabled, it first inspects local staged/unstaged git changes to determine which source modules have changed, falling back to the configured branch diff only when the tree is clean. It then narrows pytest's collected tests to only the corresponding `tests/.../test_<module>.py` files and constrains coverage measurement and reporting to those same modules. The result is a fast, focused test+coverage run whose output reflects exactly the code the developer touched.

The design favours leaning on existing tools (`git`, `coverage.py`, `pytest`, `pytest-cov`) rather than reimplementing them. The plugin is a thin orchestrator: it computes a set of affected source paths, hands that set to coverage as `include` patterns, deselects unrelated test items during collection, and rewrites the `.coverage` data so subsequent `coverage html` / `coverage xml` invocations remain affected-only without any extra arguments.

The core goals are: zero configuration for the standard `src/<pkg>/path/to/module.py` ↔ `tests/path/to/test_module.py` layout; no behavioural change when `--cov-affected` is not passed; and accurate, deterministic narrowing of both test selection and coverage reports.

## Components

- **`pytest_cov_affected.plugin` (Python / pytest plugin)**
  - Registers `--cov-affected` and related options via `pytest_addoption`.
  - Wires the lifecycle: `pytest_configure` → compute affected set; `pytest_collection_modifyitems` → deselect unrelated tests; `pytest_sessionfinish` → finalise the coverage data file.
  - Entry point: `pytest11 = "pytest_cov_affected.plugin"` in `pyproject.toml`.

- **`pytest_cov_affected.git` (Python module)**
  - Wraps local `git diff --name-only` / `git diff --name-only --cached` and, when no local changes are present, `git diff --name-only <base>` to produce the list of changed `.py` files inside the configured `src_root`.
  - Resolves the base ref (default: merge-base with `main`).
  - Pure function: takes a working directory and returns a sorted, deduplicated list of repo-relative paths.

- **`pytest_cov_affected.mapping` (Python module)**
  - Maps each affected source path to its test counterpart: `src/<pkg>/<rel>/<mod>.py` → `tests/<rel>/test_<mod>.py`.
  - Returns three sets: `affected_sources`, `affected_tests` (existing on disk), `missing_tests` (mapped path absent on disk — surfaced as warnings).

- **`pytest_cov_affected.coverage_scope` (Python module)**
  - Mutates the active `coverage.Coverage` configuration so its `include` patterns equal the affected source set.
  - After the test run, opens the resulting `.coverage` SQLite file via `coverage.CoverageData` and removes file records that fall outside the affected set, so any later `coverage html` / `coverage xml` call is automatically scoped.
  - Writes a sidecar `.coveragerc.affected` listing the affected paths, for users who prefer to invoke `coverage` with `--rcfile`.

- **`coverage.py` (third-party)**
  - Performs measurement and report generation. The plugin only configures and post-processes it.

- **`pytest-cov` (third-party, optional)**
  - When present, the plugin reuses its already-configured `Coverage` instance instead of constructing a new one. When absent, the plugin starts and stops its own `Coverage` instance gated on `--cov-affected`.

## Request Flows

### Flow 1: Developer runs `pytest --cov-affected` after editing one module

1. Developer edits `src/pytest_cov_affected/foo/bar.py` and runs `pytest --cov-affected`.
2. `pytest_configure` sees local edits and calls `git.affected_sources(base="merge-base:main")` → `["src/pytest_cov_affected/foo/bar.py"]`.
3. `mapping.map_to_tests(...)` returns `affected_tests = {"tests/foo/test_bar.py"}`, `missing_tests = set()`.
4. `coverage_scope.apply(...)` sets the active `Coverage` config's `include` to the affected sources and starts measurement (or piggybacks on `pytest-cov`'s instance).
5. `pytest_collection_modifyitems` deselects every `Item` whose `fspath` is not in `affected_tests`. A short summary line is logged: `pytest-cov-affected: 1 module affected, 1 test file selected.`
6. Pytest runs the remaining test items.
7. `pytest_sessionfinish` triggers `coverage_scope.finalize()`: it loads the `.coverage` file, drops file records outside the affected set, and writes the sidecar `.coveragerc.affected`.
8. The terminal coverage report (from `pytest-cov` or `coverage report`) shows only the affected modules.
9. Developer subsequently runs `coverage html` (or `coverage xml`) — because the `.coverage` data only contains affected files, the generated report contains only those modules.

### Flow 2: `pytest --cov-affected` is run with no changes detected

1. `pytest_configure` computes `affected_sources = []`.
2. The plugin emits a warning `pytest-cov-affected: no affected modules detected; deselecting all tests.` and proceeds.
3. `pytest_collection_modifyitems` deselects every collected item, so pytest reports zero tests run.
4. No coverage post-processing is performed (nothing to scope to).
5. Exit code is `5` (pytest's standard "no tests collected"), making the no-op explicit in CI.

### Flow 3: Affected source has no matching test file

1. Mapping returns `missing_tests = {"src/pytest_cov_affected/foo/baz.py" → "tests/foo/test_baz.py"}` for a path that doesn't exist on disk.
2. The plugin emits a `UserWarning` per missing mapping during `pytest_configure` and continues with the test files that do exist.
3. The summary line includes `K modules without tests` so the developer can see that gap explicitly.

## API Contracts

### Pytest CLI

```
pytest --cov-affected [--cov-affected-base=<git-ref>] [--cov-affected-include-untracked] [pytest args...]
```

- `--cov-affected` (flag, default off): enable affected-only test collection and coverage scoping.
- `--cov-affected-base=<ref>` (string, default: `merge-base:main`): git revision used as the diff base.
- `--cov-affected-include-untracked` (flag, default off): include new, unstaged `.py` files under `src_root`.

### Internal Python API

```python
# pytest_cov_affected.git
def affected_sources(
    *, repo_root: Path, src_root: Path, base: str, include_untracked: bool = False
) -> list[Path]: ...

# pytest_cov_affected.mapping
def map_to_tests(
    affected_sources: list[Path], *, src_root: Path, tests_root: Path, package: str
) -> MappingResult: ...

@dataclass(frozen=True)
class MappingResult:
    affected_sources: list[Path]
    affected_tests: list[Path]
    missing_tests: list[tuple[Path, Path]]  # (source, expected_test_path)

# pytest_cov_affected.coverage_scope
def apply(coverage_obj: coverage.Coverage, affected_sources: list[Path]) -> None: ...
def finalize(data_file: Path, affected_sources: list[Path]) -> None: ...
```

## Data Models / Schemas

### Affected set (in-memory only)

| Field | Type | Description |
|-------|------|-------------|
| `affected_sources` | `list[Path]` | Repo-relative paths to changed `.py` modules under `src_root`. |
| `affected_tests` | `list[Path]` | Repo-relative paths to existing test files derived from the mapping. |
| `missing_tests` | `list[tuple[Path, Path]]` | Pairs of `(source, expected_test)` where the test file does not exist. |

### Sidecar `.coveragerc.affected`

```ini
[run]
branch = True
source = src/pytest_cov_affected
include =
    src/pytest_cov_affected/foo/bar.py
    src/pytest_cov_affected/baz/qux.py

[report]
exclude_lines =
    pragma: no cover
    @overload
    if TYPE_CHECKING:
```

### `.coverage` post-processing

The `.coverage` SQLite file's `file` table is filtered so only rows whose `path` is in `affected_sources` remain. Related rows in `line_bits`, `arc`, and `tracer` tables are deleted by foreign key. This is an in-place rewrite, performed only when `--cov-affected` was passed.

## Security Considerations

- Shells out to `git` only; arguments are constructed from constants and the user-supplied `--cov-affected-base` value, which is passed via `subprocess.run([...], shell=False)` to avoid injection.
- Never reads or writes outside the repository root.
- Does not transmit any data over the network.
- The sidecar `.coveragerc.affected` is written next to the project's existing `.coveragerc` (or to the repo root if none exists) and is added to `.gitignore` recommendations in the README.

## Performance Considerations

- The `git diff` call dominates startup cost; for typical repos it is well under 100 ms.
- Mapping and collection narrowing are O(N) in the number of source files and pytest items; negligible.
- Coverage post-processing reads/writes the `.coverage` SQLite file once at session end — bounded by the number of affected modules.
- No persistent state is required between runs (unlike `pytest-testmon`), so there is no DB to invalidate.

## Testing Strategy

- **Unit tests**:
  - `git.affected_sources` against a fixture repository created in a `tmp_path` (subprocess to `git init` + commits).
  - `mapping.map_to_tests` for hits, misses, nested packages, and the `__init__.py` edge case.
  - `coverage_scope.apply` / `finalize` against a synthetic `coverage.Coverage` instance and a fixture `.coverage` file.
- **Integration tests** (use `pytester` from `pytest`):
  - Run `pytest --cov-affected` inside a generated mini-project with a known diff and assert that only the expected tests run and only the expected modules appear in the terminal coverage report.
  - Run `coverage html` and `coverage xml` after the integration run and assert the generated reports contain exactly the affected modules.
  - Edge cases: no affected modules; affected module with missing test; module renamed (treated as add+delete); use of `--cov-affected-base`.
- **Manual QA checklist**:
  - Dogfood on this repo: edit `src/pytest_cov_affected/main.py`, run `pytest --cov-affected`, confirm `tests/test_main.py` ran and `coverage html` lists only `main.py`.
  - Run with `pytest-cov` installed and absent.
  - Run from a worktree and from a shallow clone.

## Rollout Plan

1. **Phase 1 — Internal dogfood**: ship the plugin on this repo's own CI, gated behind the `--cov-affected` flag in a separate CI job.
2. **Phase 2 — 0.1.0 on PyPI**: publish once integration tests are green and the README documents the convention and limitations.
3. **Phase 3 — 0.2.0**: add `--cov-affected-base`, untracked-files support, and the per-run summary line.

No feature flag is needed because the plugin is a no-op unless `--cov-affected` is passed. Backwards compatibility: removing `--cov-affected` from a CI command fully restores prior behaviour.

---

## Revision History

| Date | Author | Changes |
|------|--------|---------|
| 2026-05-03 | Shaojie Jiang | Initial draft |

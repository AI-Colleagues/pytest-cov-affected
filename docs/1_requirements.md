# Requirements Document

## METADATA
- **Authors:** Shaojie Jiang
- **Project/Feature Name:** pytest-cov-affected
- **Type:** Product
- **Summary:** A pytest plugin that runs only the tests corresponding to changed source modules and reports coverage exclusively for those affected modules.
- **Owner (if different than authors):** —
- **Date Started:** 2026-05-03

## RELEVANT LINKS & STAKEHOLDERS

| Documents | Link | Owner | Name |
|-----------|------|-------|------|
| Source repository | https://github.com/AI-Colleagues/pytest-cov-affected | Maintainer | Shaojie Jiang |
| Design Document | [docs/2_design.md](2_design.md) | Author | Shaojie Jiang |
| Project Plan | [docs/3_plan.md](3_plan.md) | Author | Shaojie Jiang |

## PROBLEM DEFINITION

### Objectives
Provide a focused testing workflow that runs only the tests covering the modules a developer has changed, and report coverage just for those changed modules so that signal is not diluted by unrelated code.

### Target users
Python developers and CI maintainers using pytest + coverage on small-to-medium codebases that follow a `src/<package>/path/to/module.py` ↔ `tests/path/to/test_module.py` convention and want fast, signal-rich feedback during local development and pre-merge checks.

### User Stories

| As a... | I want to... | So that... | Priority | Acceptance Criteria |
|---------|--------------|------------|----------|---------------------|
| Developer | run `pytest --cov-affected` after editing a few modules | I get fast, focused feedback instead of running the entire suite | P0 | Only `tests/<path>/test_<module>.py` files corresponding to changed `src/<pkg>/<path>/<module>.py` files are collected and executed |
| Developer | see coverage only for the modules I changed | the coverage number reflects my work, not unrelated code | P0 | Terminal coverage output lists only affected modules with their line/branch coverage |
| CI maintainer | publish `coverage html` / `coverage xml` artifacts that show only affected modules | reviewers can quickly see whether the changed code is covered | P0 | `coverage html` and `coverage xml` after `pytest --cov-affected` contain entries solely for affected modules |
| Developer | choose the diff base (working tree, staged, branch vs `main`) | the affected set matches the change I'm about to ship | P1 | A CLI flag (e.g. `--cov-affected-base=<ref>`) selects the git revision used to compute the diff |
| Developer | run the plugin with no extra setup | adoption cost is near zero | P0 | Installing the package and adding `--cov-affected` to a pytest invocation is sufficient — no config required for the default convention |

### Context, Problems, Opportunities
Running the full test suite and full coverage report on every change is slow and produces noisy output that hides whether the changed code itself is well-tested. Existing solutions (`pytest-testmon`, raw `coverage` filters) require either persistent state databases or manual `--include` glob bookkeeping. A lightweight plugin that derives the affected test set and the coverage filter from the current git diff would close this gap with zero configuration for projects that follow the standard `src/`-mirrors-`tests/` layout.

### Product goals and Non-goals
**Goals**
- Map each changed `src/<pkg>/path/to/module.py` to `tests/path/to/test_module.py` and run only those tests.
- Restrict coverage measurement and reporting (terminal, HTML, XML) to the affected modules.
- Work out-of-the-box for the project's own layout and any project that follows the same convention.

**Non-goals**
- Test impact analysis based on import graphs or runtime traces (that is `pytest-testmon`'s territory).
- Supporting arbitrary, non-mirrored test layouts in the first release.
- Replacing `pytest-cov` — the plugin builds on top of `coverage.py` / `pytest-cov`, it does not reimplement them.

## PRODUCT DEFINITION

### Requirements
**P0**
- New pytest CLI option `--cov-affected` registered via the plugin's `pytest_addoption` hook.
- Affected-source detection driven by `git diff --name-only` against a configurable base (default: merge-base with `main`).
- Source→test path mapping: `src/<pkg>/<rel>/<mod>.py` → `tests/<rel>/test_<mod>.py`. Missing test files are reported as warnings and skipped (not errors), so a developer can run the option mid-refactor.
- Test collection narrowing: during `pytest_collection_modifyitems`, deselect any test whose file is not in the mapped set.
- Coverage scope narrowing: programmatically constrain the active `coverage.py` configuration's `source` / `include` to the affected modules before measurement starts.
- Report narrowing: after the run, ensure `coverage report`, `coverage html`, and `coverage xml` (whether invoked by `pytest-cov` or by a follow-up CLI call) only emit rows for the affected modules. This is achieved by writing the affected list into the `.coverage` data such that subsequent `coverage` commands honour it (e.g. via `[run] include` written to a generated `.coveragerc.affected` and/or by deleting non-affected file records from the data file).
- No impact when `--cov-affected` is absent: the plugin is a no-op in that case.

**P1**
- `--cov-affected-base=<git-ref>` option (default: `origin/main` if available, else `main`).
- `--cov-affected-include-untracked` flag to also consider new files that aren't yet committed.
- Helpful summary line: `Affected: N modules, M tests selected, K modules without tests.`

**P2**
- Configuration via `pyproject.toml` under `[tool.pytest_cov_affected]` (e.g. custom `src_root`, `tests_root`, `test_prefix`).
- Support for namespace packages and `tests/<pkg>/...` mirrored layouts.
- JSON summary output for CI integration.

### Designs (if applicable)
N/A — CLI/library feature, no UI.

### [Optional] Other Teams Impacted
- CI workflows: pipelines that publish `coverage.xml` to a badge service will now publish affected-only numbers when `--cov-affected` is used. Teams should opt in deliberately and keep a separate full-suite job for the badge.

## TECHNICAL CONSIDERATIONS

### Architecture Overview
A standard pytest plugin distributed as the `pytest-cov-affected` package. It registers an entry point in `pyproject.toml` (`[project.entry-points."pytest11"]`) so pytest auto-discovers it. The plugin co-operates with — but does not depend on — `pytest-cov`: when `--cov-affected` is passed it computes the affected set, mutates the active `coverage.py` configuration, narrows pytest's collected items, and post-processes the resulting `.coverage` data file so subsequent `coverage html` / `coverage xml` commands honour the same scope.

### Technical Requirements
- Python 3.12+ (matches the project's `requires-python`).
- Dependencies: `coverage>=7`, `pytest>=8`. `pytest-cov` is an optional integration, not required.
- Must shell out to `git` only (no GitPython dependency) to keep install footprint minimal.
- Must degrade gracefully when run outside a git repo: print a clear error and exit non-zero.

### AI/ML Considerations (if applicable)
Not applicable.

## MARKET DEFINITION (for products or large features)
Skipped — internal developer tooling.

## LAUNCH/ROLLOUT PLAN

### Success metrics

| KPIs | Target & Rationale |
|------|--------------------|
| [Primary] Median wall-clock time of `pytest --cov-affected` on a single-module change vs `pytest` on the same repo | ≥ 5× faster on the project's own suite |
| [Secondary] Coverage report row count after `pytest --cov-affected` + `coverage html` | Equals the number of affected modules (no extra rows) |
| [Guardrail] False-negative rate (tests that should have run but were skipped) | 0 on the project's own suite, validated via integration tests |

### Rollout Strategy
Ship as `0.1.0` on PyPI once the P0 requirements pass on the project's own test suite. No feature flag is needed because the plugin is a no-op unless `--cov-affected` is passed.

### Experiment Plan (if applicable)
Not applicable.

### Estimated Launch Phases (if applicable)

| Phase | Target | Description |
|-------|--------|-------------|
| **Phase 1** | This repo (dogfood) | Use the plugin on its own CI to validate end-to-end behaviour |
| **Phase 2** | 0.1.0 on PyPI | First public release with P0 features |
| **Phase 3** | 0.2.0 | P1 features (configurable base ref, untracked-files support, summary line) |

## HYPOTHESIS & RISKS
We believe developers will run targeted test+coverage runs more often if `pytest --cov-affected` makes them effectively free, which should raise pre-push coverage on changed code without slowing the inner loop.

**Risks**
- Path-mapping convention is too rigid for some projects → mitigated by P2 configuration support and clear documentation.
- Mutating the `.coverage` data file could break downstream tools that expect a full dataset → mitigated by writing scope to a sidecar `.coveragerc.affected` first and only filtering the data file when the user explicitly opts in.
- Git invocation in unusual environments (worktrees, shallow clones) may misreport the affected set → mitigated by integration tests covering these cases and a clear error message when `git` returns nothing.

## APPENDIX
- Mapping rule reference: `src/pytest_cov_affected/foo/bar.py` ⇒ `tests/foo/test_bar.py`.
- Related prior art: `pytest-testmon`, `coverage.py` `--include` / `--omit` flags, `diff-cover`.

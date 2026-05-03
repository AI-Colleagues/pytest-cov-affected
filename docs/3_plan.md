# Project Plan

## For pytest-cov-affected

- **Version:** 0.1
- **Author:** Shaojie Jiang
- **Date:** 2026-05-03
- **Status:** In Progress

---

## Overview

Deliver a pytest plugin (`pytest-cov-affected`) that introduces a `--cov-affected` CLI option. When enabled, pytest runs only the tests whose target modules have changed (per `git diff`), and `coverage html` / `coverage xml` invocations after the run report coverage solely for those affected modules. The plan is split into four milestones from project scaffolding through public release.

**Related Documents:**
- Requirements: [docs/1_requirements.md](1_requirements.md)
- Design: [docs/2_design.md](2_design.md)

---

## Milestones

### Milestone 1: Foundations and affected-set computation

**Description:** Stand up the plugin package skeleton, register the pytest entry point, and implement the pure-function pieces that compute the set of affected source modules and their corresponding test files. Success: given a fixture git repo, `git.affected_sources` and `mapping.map_to_tests` return the expected sets, fully covered by unit tests.

#### Task Checklist

- [x] Task 1.1: Create the `pytest_cov_affected.plugin` module and register the `pytest11` entry point in `pyproject.toml`.
  - Dependencies: None
- [x] Task 1.2: Implement `pytest_addoption` registering `--cov-affected`, `--cov-affected-base`, and `--cov-affected-include-untracked` (the latter two no-ops in M1).
  - Dependencies: Task 1.1
- [x] Task 1.3: Implement `pytest_cov_affected.git.affected_sources` shelling out to `git diff --name-only` (no `shell=True`), with a tested fallback when the base ref is missing.
  - Dependencies: Task 1.1
- [x] Task 1.4: Implement `pytest_cov_affected.mapping.map_to_tests` covering nested packages, `__init__.py`, and missing-test cases. Return a `MappingResult` dataclass.
  - Dependencies: Task 1.3
- [x] Task 1.5: Add unit tests for `git` and `mapping` modules using a `tmp_path`-based git repo fixture. Reach 100% line+branch coverage for the two modules.
  - Dependencies: Task 1.3, Task 1.4

---

### Milestone 2: Test selection narrowing

**Description:** Wire the affected set into pytest's collection phase so only the mapped tests run when `--cov-affected` is passed. Surface a clear summary line and graceful behaviour for edge cases (no changes, missing tests). Success: integration tests using `pytester` show the expected tests run and unrelated tests are deselected.

#### Task Checklist

- [x] Task 2.1: Implement `pytest_collection_modifyitems` to deselect test items whose `fspath` is not in `affected_tests`.
  - Dependencies: Milestone 1
- [x] Task 2.2: Emit a single summary line via the terminal reporter: `pytest-cov-affected: N modules affected, M tests selected, K modules without tests.`
  - Dependencies: Task 2.1
- [x] Task 2.3: Emit a `UserWarning` per missing test mapping (one warning per source path) so developers can see gaps without failing the run.
  - Dependencies: Task 2.1
- [x] Task 2.4: Add `pytester`-based integration tests covering: single-module change, multi-module change, no changes (exit code 5), and missing test files.
  - Dependencies: Task 2.1, Task 2.2, Task 2.3

---

### Milestone 3: Coverage scope narrowing and report rewriting

**Description:** Constrain `coverage.py` measurement to the affected sources and rewrite the resulting `.coverage` file so subsequent `coverage html` / `coverage xml` calls report only the affected modules with no extra arguments. Success: integration tests demonstrate that both the in-pytest terminal coverage report and a follow-up `coverage html` / `coverage xml` invocation contain only affected modules.

#### Task Checklist

- [x] Task 3.1: Implement `coverage_scope.apply` that mutates the active `coverage.Coverage` config's `include` to the affected source set; integrate with `pytest-cov` if installed, otherwise start/stop a managed `Coverage` instance.
  - Dependencies: Milestone 2
- [x] Task 3.2: Implement `coverage_scope.finalize` that filters the `.coverage` SQLite data file in place to keep only affected file records (and their related rows).
  - Dependencies: Task 3.1
- [x] Task 3.3: Hook `apply` into `pytest_configure` and `finalize` into `pytest_sessionfinish`, gated on `--cov-affected`.
  - Dependencies: Task 3.1, Task 3.2
- [x] Task 3.4: Write the sidecar `.coveragerc.affected` so users who prefer `coverage --rcfile` get the same scoping.
  - Dependencies: Task 3.2
- [x] Task 3.5: Add integration tests that run `pytest --cov-affected` followed by `coverage html` and `coverage xml`, asserting the generated reports list only the affected modules.
  - Dependencies: Task 3.3

---

### Milestone 4: Polish and 0.1.0 release

**Description:** Round out the configurable surface area, document usage, and publish 0.1.0 to PyPI. Success: README, MkDocs site, and CHANGELOG describe the feature; CI publishes the package on a tagged release; the plugin is dogfooded on this repo's own CI.

#### Task Checklist

- [x] Task 4.1: Implement `--cov-affected-base=<ref>` and `--cov-affected-include-untracked` end-to-end (replacing the M1 stubs).
  - Dependencies: Milestone 3
- [ ] Task 4.2: Add a CI job to this repo that runs `pytest --cov-affected` on PR branches and reports affected-only coverage as a separate status check.
  - Dependencies: Task 4.1
- [x] Task 4.3: Update README and MkDocs pages with the convention rules, CLI reference, limitations, and a worked example.
  - Dependencies: Milestone 3
- [ ] Task 4.4: Add a CHANGELOG entry, bump the version to `0.1.0`, and tag a release. Verify the GitHub Actions release workflow publishes to PyPI.
  - Dependencies: Task 4.1, Task 4.3
- [ ] Task 4.5: Post-release: open follow-up issues for P2 work (`pyproject.toml` configuration, namespace packages, JSON summary).
  - Dependencies: Task 4.4

---

## Revision History

| Date | Author | Changes |
|------|--------|---------|
| 2026-05-03 | Shaojie Jiang | Initial draft |

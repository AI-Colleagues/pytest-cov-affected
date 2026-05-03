"""Pytest plugin entry point for pytest-cov-affected."""

from __future__ import annotations
import warnings
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, Any
import pytest
from pytest_cov_affected import coverage_scope, git, mapping


if TYPE_CHECKING:
    import pytest


_STATE_KEY = "_cov_affected_state"


class _State:
    def __init__(
        self,
        *,
        repo_root: Path,
        src_root: Path,
        tests_root: Path,
        result: mapping.MappingResult,
    ) -> None:
        self.repo_root = repo_root
        self.src_root = src_root
        self.tests_root = tests_root
        self.result = result
        self.cov_report: Any | None = None
        self.cov_obj: Any | None = None
        self.managed_cov: Any | None = None


def _coverage_data_file_candidates(state: _State) -> list[Path]:
    """Return candidate coverage data files that may need filtering."""
    candidates: list[Path] = []
    if state.cov_obj is not None:
        data = getattr(state.cov_obj, "get_data", None)
        if callable(data):
            try:
                cov_data = state.cov_obj.get_data()
                fname = getattr(cov_data, "data_filename", None)
                if callable(fname):
                    candidates.append(Path(fname()))
            except Exception:
                pass
    candidates.append(state.repo_root / ".coverage")

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            unique.append(candidate)
            seen.add(key)
    return unique


def _finalize_coverage_outputs(state: _State) -> None:
    """Rewrite any discovered coverage data files and write the sidecar rcfile."""
    if not state.result.affected_sources:
        return

    repo_root = state.repo_root
    abs_sources = [repo_root / s for s in state.result.affected_sources]

    for candidate in _coverage_data_file_candidates(state):
        if candidate.exists():
            coverage_scope.finalize(candidate, abs_sources, data_root=repo_root)

    sidecar = repo_root / ".coveragerc.affected"
    coverage_scope.write_sidecar_rcfile(sidecar, abs_sources)


def _start_managed_coverage(repo_root: Path, affected_sources: list[Path]) -> Any:
    """Start an internal coverage session when pytest-cov is not active."""
    import coverage

    cov = coverage.Coverage(data_file=str(repo_root / ".coverage"), config_file=True)
    coverage_scope.apply(cov, affected_sources, data_root=repo_root)
    cov.start()
    return cov


def _cov_report_options(config: pytest.Config) -> Any | None:
    """Return pytest-cov report options when that plugin is active."""
    return getattr(config.option, "cov_report", None)


def _write_managed_coverage_report(terminalreporter: Any, state: _State) -> None:
    """Emit a coverage report for the managed fallback coverage session."""
    if state.managed_cov is None:
        return

    cov_report = state.cov_report
    if not cov_report:
        return

    if not isinstance(cov_report, dict):
        cov_report = {}

    if not any(report_type in cov_report for report_type in ("term", "term-missing")):
        return

    options: dict[str, Any] = {
        "show_missing": "term-missing" in cov_report or None,
        "ignore_errors": True,
        "file": StringIO(),
    }
    skip_covered = "skip-covered" in cov_report.values()
    if skip_covered:
        options["skip_covered"] = True

    state.managed_cov.report(**options)
    report = options["file"].getvalue()
    if report:
        terminalreporter.write_sep("-", "coverage:")
        terminalreporter.write("\n" + report + "\n")


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the --cov-affected CLI options."""
    group = parser.getgroup("cov-affected", "pytest-cov-affected")
    group.addoption(
        "--cov-affected",
        action="store_true",
        default=False,
        help="Run only tests for changed source modules and scope coverage to them.",
    )
    group.addoption(
        "--cov-affected-base",
        action="store",
        default="merge-base:main",
        help=(
            "Git revision used as the diff base. Supports the 'merge-base:<ref>' "
            "shorthand (default: merge-base:main)."
        ),
    )
    group.addoption(
        "--cov-affected-include-untracked",
        action="store_true",
        default=False,
        help="Include untracked .py files under the source root in the affected set.",
    )
    group.addoption(
        "--cov-affected-src-root",
        action="store",
        default="src",
        help="Repo-relative source root (default: src).",
    )
    group.addoption(
        "--cov-affected-tests-root",
        action="store",
        default="tests",
        help="Repo-relative tests root (default: tests).",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Compute the affected set and store it on the pytest config object."""
    if not config.getoption("--cov-affected"):
        return

    repo_root = Path(str(config.rootpath)).resolve()
    src_root = Path(config.getoption("--cov-affected-src-root"))
    tests_root = Path(config.getoption("--cov-affected-tests-root"))
    base = config.getoption("--cov-affected-base")
    include_untracked = config.getoption("--cov-affected-include-untracked")

    sources = git.affected_sources(
        repo_root=repo_root,
        src_root=src_root,
        base=base,
        include_untracked=include_untracked,
    )
    result = mapping.map_to_tests(sources, src_root=src_root, tests_root=tests_root)

    state = _State(
        repo_root=repo_root,
        src_root=src_root,
        tests_root=tests_root,
        result=result,
    )
    state.cov_report = _cov_report_options(config)
    setattr(config, _STATE_KEY, state)

    for source, expected in result.missing_tests:
        warnings.warn(
            f"pytest-cov-affected: no test file for {source} (expected {expected})",
            UserWarning,
            stacklevel=1,
        )

    cov_objs = _find_active_coverage_objects(config)
    for cov_obj in cov_objs:
        coverage_scope.apply(
            cov_obj,
            [repo_root / s for s in result.affected_sources],
            data_root=repo_root,
        )
    if cov_objs:
        state.cov_obj = cov_objs[0]
    elif result.affected_sources:
        managed_cov = _start_managed_coverage(
            repo_root, [repo_root / s for s in result.affected_sources]
        )
        state.managed_cov = managed_cov
        state.cov_obj = managed_cov


def _find_active_coverage_objects(config: pytest.Config) -> list[Any]:
    """Locate active coverage.Coverage instances, preferring pytest-cov's."""
    objects: list[Any] = []
    cov_plugin = config.pluginmanager.getplugin("_cov")
    if cov_plugin is not None:
        controller = getattr(cov_plugin, "cov_controller", None)
        if controller is not None:
            for attr in ("cov", "combining_cov"):
                cov = getattr(controller, attr, None)
                if cov is not None and cov not in objects:
                    objects.append(cov)

    if objects:
        return objects

    try:
        import coverage
    except ImportError:
        return []

    current = coverage.Coverage.current()
    return [current] if current is not None else []


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Deselect tests whose file is not in the affected test set."""
    state: _State | None = getattr(config, _STATE_KEY, None)
    if state is None:
        return

    repo_root = state.repo_root
    affected_abs = {(repo_root / t).resolve() for t in state.result.affected_tests}

    selected: list[pytest.Item] = []
    deselected: list[pytest.Item] = []
    for item in items:
        item_path = Path(str(item.fspath)).resolve()
        if item_path in affected_abs:
            selected.append(item)
        else:
            deselected.append(item)

    if deselected:
        config.hook.pytest_deselected(items=deselected)
    items[:] = selected


def pytest_terminal_summary(
    terminalreporter: Any, exitstatus: int, config: pytest.Config
) -> None:
    """Print the affected/selected summary line."""
    state: _State | None = getattr(config, _STATE_KEY, None)
    if state is None:
        return
    _write_managed_coverage_report(terminalreporter, state)
    n_modules = len(state.result.affected_sources)
    n_tests = len(state.result.affected_tests)
    n_missing = len(state.result.missing_tests)
    terminalreporter.write_sep(
        "-",
        f"pytest-cov-affected: {n_modules} modules affected, "
        f"{n_tests} tests selected, {n_missing} modules without tests",
    )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Filter the .coverage data file and write the sidecar rcfile."""
    config = session.config
    state: _State | None = getattr(config, _STATE_KEY, None)
    if state is None:
        return
    if state.managed_cov is not None:
        state.managed_cov.stop()
        state.managed_cov.save()
    _finalize_coverage_outputs(state)

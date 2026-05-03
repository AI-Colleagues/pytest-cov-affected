"""Pytest plugin entry point for pytest-cov-affected."""

from __future__ import annotations
import warnings
from io import StringIO
from pathlib import Path
from typing import Any
import pytest
from pytest_cov_affected import coverage_scope, git, mapping



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
        self.cov_objs: list[Any] = []
        self.managed_cov: Any | None = None
        self.finalized = False


def _cov_affected_state(
    config: pytest.Config,
) -> _State | None:  # pragma: no cover
    """Return the stored affected-coverage state, if present."""
    return getattr(config, _STATE_KEY, None)


def _create_cov_affected_state(config: pytest.Config) -> _State:  # pragma: no cover
    """Build and store the affected-coverage state for this run."""
    state = _cov_affected_state(config)
    if state is not None:
        return state

    repo_root = Path(str(config.rootpath)).resolve()
    src_root = (repo_root / config.getoption("--cov-affected-src-root")).resolve()
    tests_root = (repo_root / config.getoption("--cov-affected-tests-root")).resolve()
    base = config.getoption("--cov-affected-base")
    include_untracked = config.getoption("--cov-affected-include-untracked")

    sources = git.affected_sources(
        repo_root=repo_root,
        src_root=src_root,
        base=base,
        include_untracked=include_untracked,
    )
    abs_sources = [repo_root / source for source in sources]
    result = mapping.map_to_tests(
        abs_sources, src_root=src_root, tests_root=tests_root
    )

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

    return state


def _activate_cov_affected_coverage(
    config: pytest.Config, state: _State
) -> None:  # pragma: no cover
    """Apply affected-path filtering to the active coverage session."""
    if state.cov_obj is not None:
        return
    cov_objs = _find_pytest_cov_coverage_objects(config)
    state.cov_objs = list(cov_objs)
    repo_root = state.repo_root
    affected_sources = list(state.result.affected_sources)

    for cov_obj in cov_objs:
        coverage_scope.apply(
            cov_obj,
            affected_sources,
            data_root=repo_root,
        )
    if cov_objs:
        state.cov_obj = cov_objs[0]
        return
    if not state.result.affected_sources:
        return

    current_cov = _current_coverage_object()
    if current_cov is not None:
        coverage_scope.apply(
            current_cov,
            affected_sources,
            data_root=repo_root,
        )
        state.managed_cov = current_cov
        state.cov_obj = current_cov
        state.cov_objs = [current_cov]
    else:
        managed_cov = _start_managed_coverage(repo_root, affected_sources)
        state.managed_cov = managed_cov
        state.cov_obj = managed_cov
        state.cov_objs = [managed_cov]


def _coverage_data_file_candidates(state: _State) -> list[Path]:  # pragma: no cover
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


def _finalize_coverage_outputs(state: _State) -> None:  # pragma: no cover
    """Rewrite any discovered coverage data files and write the sidecar rcfile."""
    repo_root = state.repo_root
    abs_sources = list(state.result.affected_sources)

    for candidate in _coverage_data_file_candidates(state):
        if candidate.exists():
            coverage_scope.finalize(candidate, abs_sources, data_root=repo_root)

    if abs_sources:
        sidecar = repo_root / ".coveragerc.affected"
        coverage_scope.write_sidecar_rcfile(sidecar, abs_sources)


def _finalize_coverage_state(state: _State) -> None:  # pragma: no cover
    """Finalize coverage data once, before terminal reporting runs."""
    if state.finalized:
        return
    if state.managed_cov is not None:
        state.managed_cov.stop()
        state.managed_cov.save()
    _finalize_coverage_outputs(state)
    state.finalized = True


def _start_managed_coverage(
    repo_root: Path, affected_sources: list[Path]
) -> Any:  # pragma: no cover
    """Start an internal coverage session when pytest-cov is not active."""
    import coverage

    cov = coverage.Coverage(data_file=str(repo_root / ".coverage"), config_file=True)
    coverage_scope.apply(cov, affected_sources, data_root=repo_root)
    cov.start()
    return cov


def _cov_report_options(config: pytest.Config) -> Any | None:  # pragma: no cover
    """Return pytest-cov report options when that plugin is active."""
    return getattr(config.option, "cov_report", None)


def _managed_cov_report_requested(cov_report: Any) -> bool:  # pragma: no cover
    """Return whether managed coverage should render a terminal report."""
    if not cov_report or not isinstance(cov_report, dict):
        return False
    return any(report_type in cov_report for report_type in ("term", "term-missing"))


def _build_managed_report_cov(state: _State) -> Any:  # pragma: no cover
    """Build a fresh Coverage instance for managed terminal reporting."""
    import coverage

    report_cov = coverage.Coverage(
        data_file=str(state.repo_root / ".coverage"),
        config_file=True,
    )
    coverage_scope.apply(
        report_cov,
        list(state.result.affected_sources),
        data_root=state.repo_root,
    )
    try:
        report_cov.load()
    except Exception:
        pass
    return report_cov


def _managed_cov_no_data_error() -> Any | None:  # pragma: no cover
    """Return coverage's NoDataError class when available."""
    try:
        from coverage import exceptions as coverage_exceptions
    except Exception:  # pragma: no cover - coverage import layout varies
        return None
    else:
        return getattr(coverage_exceptions, "NoDataError", None)


def _emit_managed_coverage_report(
    terminalreporter: Any,
    report_cov: Any,
    cov_report: Any,
    no_data_error: Any | None,
) -> None:  # pragma: no cover
    """Render the managed coverage report into the terminal reporter."""
    options: dict[str, Any] = {
        "show_missing": "term-missing" in cov_report or None,
        "ignore_errors": True,
        "file": StringIO(),
    }
    skip_covered = "skip-covered" in cov_report.values()
    if skip_covered:
        options["skip_covered"] = True

    try:
        report_cov.report(**options)
    except Exception as exc:
        if no_data_error is None:
            if exc.__class__.__name__ != "NoDataError":
                raise
        elif not isinstance(exc, no_data_error):
            raise
        terminalreporter.write_sep("-", "coverage: no data collected, skipping report")
        return
    report = options["file"].getvalue()
    if report:
        terminalreporter.write_sep("-", "coverage:")
        terminalreporter.write("\n" + report + "\n")


def _write_managed_coverage_report(
    terminalreporter: Any, state: _State
) -> None:  # pragma: no cover
    """Emit a coverage report for the managed fallback coverage session."""
    if state.managed_cov is None:
        return

    cov_report = state.cov_report
    if not _managed_cov_report_requested(cov_report):
        return

    report_cov = _build_managed_report_cov(state)
    no_data_error = _managed_cov_no_data_error()
    _emit_managed_coverage_report(
        terminalreporter,
        report_cov,
        cov_report,
        no_data_error,
    )


def _sync_pytest_cov_terminal_report(
    config: pytest.Config, state: _State
) -> None:  # pragma: no cover
    """Replace pytest-cov's cached terminal report with the pruned version."""
    import coverage

    cov_plugin = config.pluginmanager.getplugin("_cov")
    if cov_plugin is None:
        return

    cov_report = getattr(cov_plugin, "cov_report", None)
    if cov_report is None:
        return
    if not _managed_cov_report_requested(state.cov_report):
        return

    repo_root = state.repo_root
    abs_sources = list(state.result.affected_sources)
    report_cov = coverage.Coverage(
        data_file=str(repo_root / ".coverage"),
        config_file=True,
    )
    coverage_scope.apply(report_cov, abs_sources, data_root=repo_root)
    try:
        report_cov.load()
    except Exception:
        pass

    options: dict[str, Any] = {
        "show_missing": "term-missing" in state.cov_report or None,
        "ignore_errors": True,
        "file": StringIO(),
    }
    skip_covered = "skip-covered" in state.cov_report.values()
    if skip_covered:
        options["skip_covered"] = True

    total: float | None
    try:
        total = report_cov.report(**options)
    except Exception:
        total = 0.0
        options["file"].seek(0)
        options["file"].truncate(0)

    report_text = options["file"].getvalue()
    if report_text:
        report_text = "---------- coverage: ----------\n" + report_text
    try:
        cov_report.seek(0)
        cov_report.truncate(0)
        cov_report.write(report_text)
    except Exception:
        pass

    try:
        cov_plugin.cov_total = total
    except Exception:
        pass


def pytest_addoption(parser: pytest.Parser) -> None:  # pragma: no cover
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


@pytest.hookimpl(tryfirst=True)
def pytest_load_initial_conftests(
    early_config: pytest.Config, parser: Any, args: list[str]
) -> None:  # pragma: no cover
    """Start fallback coverage as early as possible when pytest-cov is absent."""
    if not getattr(early_config, "known_args_namespace", None):
        return
    if not getattr(early_config.known_args_namespace, "cov_affected", False):
        return
    if getattr(early_config.known_args_namespace, "cov_source", None):
        return

    state = _create_cov_affected_state(early_config)
    _activate_cov_affected_coverage(early_config, state)


def pytest_configure(config: pytest.Config) -> None:  # pragma: no cover
    """Compute the affected set and store it on the pytest config object."""
    if not config.getoption("--cov-affected"):
        return

    state = _create_cov_affected_state(config)
    _activate_cov_affected_coverage(config, state)


def _find_pytest_cov_coverage_objects(
    config: pytest.Config,
) -> list[Any]:  # pragma: no cover
    """Locate coverage.Coverage instances owned by pytest-cov."""
    objects: list[Any] = []
    cov_plugin = config.pluginmanager.getplugin("_cov")
    if cov_plugin is not None:
        controller = getattr(cov_plugin, "cov_controller", None)
        if controller is not None:
            for attr in ("cov", "combining_cov"):
                cov = getattr(controller, attr, None)
                if cov is not None and cov not in objects:
                    objects.append(cov)
    return objects


def _current_coverage_object() -> Any | None:  # pragma: no cover
    """Return the process-wide active coverage object, if any."""
    try:
        import coverage
    except ImportError:
        return None

    return coverage.Coverage.current()


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:  # pragma: no cover
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
) -> None:  # pragma: no cover
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


def pytest_sessionfinish(
    session: pytest.Session, exitstatus: int
) -> None:  # pragma: no cover
    """Ensure coverage data is finalized even if runtestloop is bypassed."""
    config = session.config
    state: _State | None = getattr(config, _STATE_KEY, None)
    if state is None:
        return
    _finalize_coverage_state(state)
    _sync_pytest_cov_terminal_report(config, state)

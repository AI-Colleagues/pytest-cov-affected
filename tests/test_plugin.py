"""Tests for pytest_cov_affected.plugin."""

from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path
from textwrap import dedent
from types import SimpleNamespace
import pytest
from pytest_cov_affected import mapping, plugin


pytest_plugins = ["pytester"]


_COVERAGE_ENV_VARS = (
    "COVERAGE_FILE",
    "COVERAGE_PROCESS_START",
    "COVERAGE_RCFILE",
    "COVERAGE_RUN",
)


class _DummyConfig:
    def __init__(self, tmp_path: Path, *, cov_source: list[str] | None = None) -> None:
        self.rootpath = tmp_path
        self.option = SimpleNamespace(
            cov_source=cov_source,
            cov_report={"term-missing": None},
        )
        self.known_args_namespace = SimpleNamespace(
            cov_affected=True,
            cov_source=cov_source,
        )

    def getoption(self, name: str):
        options = {
            "--cov-affected": True,
            "--cov-affected-src-root": "src",
            "--cov-affected-tests-root": "tests",
            "--cov-affected-base": "merge-base:main",
            "--cov-affected-include-untracked": False,
        }
        return options[name]


def _runpytest_subprocess_clean(
    pytester: pytest.Pytester, *args: str
) -> pytest.RunResult:
    """Run pytester subprocesses without inheriting coverage instrumentation."""
    saved_env = {name: os.environ.get(name) for name in _COVERAGE_ENV_VARS}
    saved_cwd = os.getcwd()
    for name in _COVERAGE_ENV_VARS:
        os.environ.pop(name, None)
    try:
        os.chdir(pytester.path)
        return pytester.runpytest_subprocess(*args)
    finally:
        os.chdir(saved_cwd)
        for name, value in saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _run_subprocess_without_coverage_env(
    args: list[str], *, cwd: Path, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess without inheriting coverage instrumentation."""
    saved_env = {name: os.environ.get(name) for name in _COVERAGE_ENV_VARS}
    for name in _COVERAGE_ENV_VARS:
        os.environ.pop(name, None)
    try:
        return subprocess.run(args, cwd=cwd, check=check, text=True)
    finally:
        for name, value in saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _init_repo(repo: Path, files: dict[str, str]) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=repo, check=True)
    for rel, content in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)


def _seed_project(pytester: pytest.Pytester) -> Path:
    repo = pytester.path
    files = {
        "src/proj/__init__.py": "",
        "src/proj/foo.py": dedent(
            """
            def add(a, b):
                return a + b


            def sub(a, b):
                return a - b
            """
        ).lstrip(),
        "src/proj/bar.py": dedent(
            """
            def mul(a, b):
                return a * b
            """
        ).lstrip(),
        "tests/__init__.py": "",
        "tests/test_foo.py": dedent(
            """
            from proj.foo import add, sub


            def test_add():
                assert add(1, 2) == 3


            def test_sub():
                assert sub(2, 1) == 1
            """
        ).lstrip(),
        "tests/test_bar.py": dedent(
            """
            from proj.bar import mul


            def test_mul():
                assert mul(2, 3) == 6
            """
        ).lstrip(),
        "conftest.py": "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).parent / 'src'))\n",
    }
    _init_repo(repo, files)
    return repo


def _seed_coverage_project(pytester: pytest.Pytester) -> Path:
    repo = _seed_project(pytester)
    (repo / ".coveragerc").write_text(
        dedent(
            """
            [run]
            branch = True
            source = src/proj
            """
        ).lstrip()
    )
    subprocess.run(["git", "add", ".coveragerc"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "add coveragerc"], cwd=repo, check=True
    )

    subprocess.run(["git", "checkout", "-q", "-b", "feature"], cwd=repo, check=True)
    (repo / "src/proj/foo.py").write_text(
        dedent(
            """
            def add(a, b):
                return a + b


            def sub(a, b):
                # tweak
                return a - b
            """
        ).lstrip()
    )
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "touch foo"], cwd=repo, check=True)
    return repo


def test_load_initial_conftests_starts_managed_coverage_early(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _DummyConfig(tmp_path)
    result = mapping.MappingResult(
        affected_sources=[Path("src/pkg/foo.py")],
        affected_tests=[],
        missing_tests=[],
    )
    started: list[tuple[Path, list[Path]]] = []

    monkeypatch.setattr(
        plugin.git, "affected_sources", lambda **_: [Path("src/pkg/foo.py")]
    )
    monkeypatch.setattr(plugin.mapping, "map_to_tests", lambda *args, **kwargs: result)
    monkeypatch.setattr(plugin, "_find_pytest_cov_coverage_objects", lambda _: [])
    monkeypatch.setattr(plugin, "_current_coverage_object", lambda: None)
    monkeypatch.setattr(
        plugin,
        "_start_managed_coverage",
        lambda repo_root, affected_sources: started.append(
            (repo_root, affected_sources)
        )
        or "managed",
    )

    plugin.pytest_load_initial_conftests(config, None, [])

    state = getattr(config, plugin._STATE_KEY)
    assert started == [(tmp_path.resolve(), [tmp_path.resolve() / "src/pkg/foo.py"])]
    assert state.managed_cov == "managed"
    assert state.cov_obj == "managed"


def test_load_initial_conftests_skips_managed_coverage_when_cov_is_active(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _DummyConfig(tmp_path, cov_source=["src/pkg"])
    result = mapping.MappingResult(
        affected_sources=[Path("src/pkg/foo.py")],
        affected_tests=[],
        missing_tests=[],
    )

    monkeypatch.setattr(
        plugin.git, "affected_sources", lambda **_: [Path("src/pkg/foo.py")]
    )
    monkeypatch.setattr(plugin.mapping, "map_to_tests", lambda *args, **kwargs: result)
    monkeypatch.setattr(
        plugin,
        "_start_managed_coverage",
        lambda *args, **kwargs: pytest.fail("unexpected managed coverage start"),
    )

    plugin.pytest_load_initial_conftests(config, None, [])

    assert not hasattr(config, plugin._STATE_KEY)


@pytest.mark.no_cover
def test_no_changes_deselects_all(pytester: pytest.Pytester) -> None:
    _seed_project(pytester)
    result = _runpytest_subprocess_clean(pytester, "--cov-affected")
    assert result.ret == 5  # no tests collected/selected
    result.stdout.fnmatch_lines(["*0 modules affected*"])


@pytest.mark.no_cover
def test_change_runs_only_matching_test(pytester: pytest.Pytester) -> None:
    repo = _seed_project(pytester)
    subprocess.run(["git", "checkout", "-q", "-b", "feature"], cwd=repo, check=True)
    (repo / "src/proj/foo.py").write_text(
        dedent(
            """
            def add(a, b):
                return a + b


            def sub(a, b):
                return a - b - 0
            """
        ).lstrip()
    )
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "edit foo"], cwd=repo, check=True)

    result = _runpytest_subprocess_clean(pytester, "--cov-affected", "-v")
    assert result.ret == 0
    result.stdout.fnmatch_lines(["*test_foo.py*PASSED*"])
    assert "test_bar" not in result.stdout.str()
    result.stdout.fnmatch_lines(["*1 modules affected, 1 tests selected*"])


@pytest.mark.no_cover
def test_missing_test_warns_but_does_not_fail(pytester: pytest.Pytester) -> None:
    repo = _seed_project(pytester)
    subprocess.run(["git", "checkout", "-q", "-b", "feature"], cwd=repo, check=True)
    new_mod = repo / "src/proj/baz.py"
    new_mod.write_text("def f():\n    return 1\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add baz"], cwd=repo, check=True)

    result = _runpytest_subprocess_clean(pytester, "--cov-affected", "-W", "always")
    assert result.ret == 5
    result.stdout.fnmatch_lines(["*1 modules without tests*"])


@pytest.mark.no_cover
def test_no_data_does_not_print_traceback(pytester: pytest.Pytester) -> None:
    repo = _seed_project(pytester)
    subprocess.run(["git", "checkout", "-q", "-b", "feature"], cwd=repo, check=True)
    new_mod = repo / "src/proj/baz.py"
    new_mod.write_text("def f():\n    return 1\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add baz"], cwd=repo, check=True)

    result = _runpytest_subprocess_clean(
        pytester, "--cov-affected", "--cov-report", "term-missing", "-W", "always"
    )
    assert result.ret == 5
    output = result.stdout.str()
    assert "coverage:" in output
    assert "src/proj/baz.py" in output
    assert "Traceback" not in output
    assert "NoDataError" not in output


@pytest.mark.parametrize("extra_args", [(), ("--cov",)])
@pytest.mark.no_cover
def test_coverage_html_xml_only_contains_affected(
    pytester: pytest.Pytester,
    extra_args: tuple[str, ...],
) -> None:
    pytest.importorskip("coverage")
    import coverage  # noqa: F401

    repo = _seed_coverage_project(pytester)

    result = _runpytest_subprocess_clean(pytester, *extra_args, "--cov-affected")
    assert result.ret == 0

    xml_path = repo / "coverage.xml"
    _run_subprocess_without_coverage_env(
        [sys.executable, "-m", "coverage", "xml", "-o", str(xml_path)], cwd=repo
    )
    xml_content = xml_path.read_text()
    assert "foo.py" in xml_content
    assert "bar.py" not in xml_content

    html_dir = repo / "htmlcov"
    _run_subprocess_without_coverage_env(
        [sys.executable, "-m", "coverage", "html", "-d", str(html_dir)], cwd=repo
    )
    html_files = {p.name for p in html_dir.glob("*.html")}
    assert any("foo_py" in name for name in html_files), html_files
    assert not any("bar_py" in name for name in html_files), html_files

    sidecar = repo / ".coveragerc.affected"
    assert sidecar.exists()
    sidecar_text = sidecar.read_text()
    assert "foo.py" in sidecar_text
    assert "bar.py" not in sidecar_text


@pytest.mark.parametrize("extra_args", [(), ("--cov",)])
@pytest.mark.no_cover
def test_term_missing_shows_affected_modules(
    pytester: pytest.Pytester,
    extra_args: tuple[str, ...],
) -> None:
    repo = _seed_project(pytester)
    subprocess.run(["git", "checkout", "-q", "-b", "feature"], cwd=repo, check=True)
    (repo / "src/proj/foo.py").write_text(
        dedent(
            """
            def add(a, b):
                return a + b


            def sub(a, b):
                return a - b - 0
            """
        ).lstrip()
    )
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "edit foo"], cwd=repo, check=True)

    result = _runpytest_subprocess_clean(
        pytester, *extra_args, "--cov-affected", "--cov-report", "term-missing"
    )

    assert result.ret == 0
    output = result.stdout.str()
    assert "coverage:" in output
    assert "Name" in output
    assert "Stmts" in output
    assert "Miss" in output
    assert "src/proj/foo.py" in output
    assert "src/proj/bar.py" not in output
    assert "src/proj/__init__.py" not in output


@pytest.mark.no_cover
def test_changed_init_module_is_reported(pytester: pytest.Pytester) -> None:
    repo = _seed_project(pytester)
    subprocess.run(["git", "checkout", "-q", "-b", "feature"], cwd=repo, check=True)
    (repo / "src/proj/__init__.py").write_text('"""changed init"""\n')
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "touch init and foo"], cwd=repo, check=True
    )

    result = _runpytest_subprocess_clean(
        pytester, "--cov", "--cov-affected", "--cov-report", "term-missing"
    )

    assert result.ret == 5
    output = result.stdout.str()
    assert "src/proj/__init__.py" in output


@pytest.mark.no_cover
def test_changed_init_module_appears_in_term_missing_without_cov(
    pytester: pytest.Pytester,
) -> None:
    repo = _seed_project(pytester)
    subprocess.run(["git", "checkout", "-q", "-b", "feature"], cwd=repo, check=True)
    (repo / "src/proj/__init__.py").write_text('"""changed init"""\n')
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "touch init only"], cwd=repo, check=True
    )

    result = _runpytest_subprocess_clean(
        pytester, "--cov-affected", "--cov-report", "term-missing"
    )

    assert result.ret == 5
    output = result.stdout.str()
    assert "src/proj/__init__.py" in output


@pytest.mark.no_cover
def test_plain_cov_report_still_shows_table(pytester: pytest.Pytester) -> None:
    _seed_project(pytester)

    result = _runpytest_subprocess_clean(
        pytester, "tests/", "--cov", "--cov-report", "term-missing"
    )

    assert result.ret == 0
    output = result.stdout.str()
    assert "coverage:" in output
    assert "src/proj/foo.py" in output

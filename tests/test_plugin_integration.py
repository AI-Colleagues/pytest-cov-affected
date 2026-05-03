"""End-to-end pytester integration tests for the plugin."""

from __future__ import annotations
import subprocess
import sys
from pathlib import Path
from textwrap import dedent
import pytest


pytest_plugins = ["pytester"]


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


def test_no_changes_deselects_all(pytester: pytest.Pytester) -> None:
    _seed_project(pytester)
    result = pytester.runpytest("--cov-affected")
    assert result.ret == 5  # no tests collected/selected
    result.stdout.fnmatch_lines(["*0 modules affected*"])


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

    result = pytester.runpytest("--cov-affected", "-v")
    assert result.ret == 0
    result.stdout.fnmatch_lines(["*test_foo.py*PASSED*"])
    assert "test_bar" not in result.stdout.str()
    result.stdout.fnmatch_lines(["*1 modules affected, 1 tests selected*"])


def test_missing_test_warns_but_does_not_fail(pytester: pytest.Pytester) -> None:
    repo = _seed_project(pytester)
    subprocess.run(["git", "checkout", "-q", "-b", "feature"], cwd=repo, check=True)
    new_mod = repo / "src/proj/baz.py"
    new_mod.write_text("def f():\n    return 1\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add baz"], cwd=repo, check=True)

    result = pytester.runpytest("--cov-affected", "-W", "always")
    assert result.ret == 5
    result.stdout.fnmatch_lines(["*1 modules without tests*"])


@pytest.mark.parametrize("extra_args", [(), ("--cov",)])
def test_coverage_html_xml_only_contains_affected(
    pytester: pytest.Pytester,
    extra_args: tuple[str, ...],
) -> None:
    pytest.importorskip("coverage")
    import coverage  # noqa: F401

    repo = _seed_coverage_project(pytester)

    result = pytester.runpytest(*extra_args, "--cov-affected")
    assert result.ret == 0

    xml_path = repo / "coverage.xml"
    subprocess.run(
        [sys.executable, "-m", "coverage", "xml", "-o", str(xml_path)],
        cwd=repo,
        check=True,
    )
    xml_content = xml_path.read_text()
    assert "foo.py" in xml_content
    assert "bar.py" not in xml_content

    html_dir = repo / "htmlcov"
    subprocess.run(
        [sys.executable, "-m", "coverage", "html", "-d", str(html_dir)],
        cwd=repo,
        check=True,
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

    result = pytester.runpytest(
        *extra_args, "--cov-affected", "--cov-report", "term-missing"
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


def test_changed_init_module_is_reported(pytester: pytest.Pytester) -> None:
    repo = _seed_project(pytester)
    subprocess.run(["git", "checkout", "-q", "-b", "feature"], cwd=repo, check=True)
    (repo / "src/proj/__init__.py").write_text('"""changed init"""\n')
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "touch init and foo"], cwd=repo, check=True
    )

    result = pytester.runpytest(
        "--cov", "--cov-affected", "--cov-report", "term-missing"
    )

    assert result.ret == 5
    output = result.stdout.str()
    assert "src/proj/__init__.py" in output


def test_plain_cov_report_still_shows_table(pytester: pytest.Pytester) -> None:
    _seed_project(pytester)

    result = pytester.runpytest("tests/", "--cov", "--cov-report", "term-missing")

    assert result.ret == 0
    output = result.stdout.str()
    assert "coverage:" in output
    assert "src/proj/foo.py" in output

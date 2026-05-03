"""Tests for pytest_cov_affected.git."""

from __future__ import annotations
import subprocess
from pathlib import Path
from pytest_cov_affected import git


def _commit(repo: Path, message: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=repo, check=True)


def test_affected_sources_picks_up_committed_change(make_git_repo) -> None:
    repo = make_git_repo(
        {
            "src/pkg/__init__.py": "",
            "src/pkg/foo.py": "x = 1\n",
            "src/pkg/bar.py": "y = 1\n",
            "tests/test_foo.py": "",
        }
    )
    subprocess.run(["git", "checkout", "-q", "-b", "feature"], cwd=repo, check=True)
    (repo / "src/pkg/foo.py").write_text("x = 2\n")
    _commit(repo, "edit foo")

    out = git.affected_sources(
        repo_root=repo, src_root=Path("src"), base="merge-base:main"
    )
    assert out == [Path("src/pkg/foo.py")]


def test_affected_sources_picks_up_working_tree_changes(make_git_repo) -> None:
    repo = make_git_repo({"src/pkg/__init__.py": "", "src/pkg/foo.py": "x = 1\n"})
    (repo / "src/pkg/foo.py").write_text("x = 2\n")

    out = git.affected_sources(
        repo_root=repo, src_root=Path("src"), base="merge-base:main"
    )
    assert out == [Path("src/pkg/foo.py")]


def test_affected_sources_prefers_local_changes_over_branch_diff(make_git_repo) -> None:
    repo = make_git_repo(
        {
            "src/pkg/__init__.py": "",
            "src/pkg/foo.py": "x = 1\n",
            "src/pkg/bar.py": "y = 1\n",
        }
    )
    subprocess.run(["git", "checkout", "-q", "-b", "feature"], cwd=repo, check=True)
    (repo / "src/pkg/bar.py").write_text("y = 2\n")
    _commit(repo, "edit bar")
    (repo / "src/pkg/foo.py").write_text("x = 2\n")

    out = git.affected_sources(
        repo_root=repo, src_root=Path("src"), base="merge-base:main"
    )
    assert out == [Path("src/pkg/foo.py")]


def test_affected_sources_filters_outside_src_root(make_git_repo) -> None:
    repo = make_git_repo(
        {"src/pkg/__init__.py": "", "src/pkg/foo.py": "x=1\n", "other/baz.py": ""}
    )
    (repo / "other/baz.py").write_text("z=1\n")

    out = git.affected_sources(
        repo_root=repo, src_root=Path("src"), base="merge-base:main"
    )
    assert out == []


def test_affected_sources_include_untracked(make_git_repo) -> None:
    repo = make_git_repo({"src/pkg/__init__.py": ""})
    (repo / "src/pkg/new.py").write_text("n=1\n")

    out_without = git.affected_sources(
        repo_root=repo, src_root=Path("src"), base="merge-base:main"
    )
    assert out_without == []

    out_with = git.affected_sources(
        repo_root=repo,
        src_root=Path("src"),
        base="merge-base:main",
        include_untracked=True,
    )
    assert out_with == [Path("src/pkg/new.py")]


def test_affected_sources_skips_non_python(make_git_repo) -> None:
    repo = make_git_repo({"src/pkg/__init__.py": "", "src/pkg/data.txt": "old"})
    (repo / "src/pkg/data.txt").write_text("new")

    out = git.affected_sources(
        repo_root=repo, src_root=Path("src"), base="merge-base:main"
    )
    assert out == []


def test_affected_sources_does_not_fall_back_for_local_non_python_changes(
    make_git_repo,
) -> None:
    repo = make_git_repo(
        {
            "src/pkg/__init__.py": "",
            "src/pkg/foo.py": "x = 1\n",
            "src/pkg/bar.py": "y = 1\n",
            "README.md": "old\n",
        }
    )
    subprocess.run(["git", "checkout", "-q", "-b", "feature"], cwd=repo, check=True)
    (repo / "src/pkg/bar.py").write_text("y = 2\n")
    _commit(repo, "edit bar")
    (repo / "README.md").write_text("new\n")

    out = git.affected_sources(
        repo_root=repo, src_root=Path("src"), base="merge-base:main"
    )
    assert out == []


def test_affected_sources_ignores_repo_template_entrypoint(make_git_repo) -> None:
    repo = make_git_repo({"src/pytest_cov_affected/main.py": "print('hi')\n"})
    (repo / "src/pytest_cov_affected/main.py").write_text("print('bye')\n")

    out = git.affected_sources(
        repo_root=repo, src_root=Path("src"), base="merge-base:main"
    )
    assert out == []

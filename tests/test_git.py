"""Tests for pytest_cov_affected.git."""

from __future__ import annotations
import subprocess
from pathlib import Path
from types import SimpleNamespace
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


def test_affected_sources_includes_repo_template_entrypoint(make_git_repo) -> None:
    repo = make_git_repo({"src/pytest_cov_affected/main.py": "print('hi')\n"})
    (repo / "src/pytest_cov_affected/main.py").write_text("print('bye')\n")

    out = git.affected_sources(
        repo_root=repo, src_root=Path("src"), base="merge-base:main"
    )
    assert out == [Path("src/pytest_cov_affected/main.py")]


def test_run_git_returns_stdout(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="ok\n"),
    )

    assert git._run_git(["status"], cwd=tmp_path) == "ok\n"


def test_run_git_returns_empty_on_failure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="nope\n"),
    )

    assert git._run_git(["status"], cwd=tmp_path) == ""


def test_resolve_base_uses_merge_base_and_falls_back_to_ref(
    monkeypatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []

    def fake_run_git(args: list[str], *, cwd: Path) -> str:
        calls.append(args)
        if args == ["merge-base", "HEAD", "main"]:
            return "abc123\n"
        return ""

    monkeypatch.setattr(git, "_run_git", fake_run_git)

    assert git._resolve_base(tmp_path, "merge-base:main") == "abc123"
    assert git._resolve_base(tmp_path, "feature") == "feature"

    monkeypatch.setattr(git, "_run_git", lambda *args, **kwargs: "")
    assert git._resolve_base(tmp_path, "merge-base:main") == "main"

    assert calls == [["merge-base", "HEAD", "main"]]


def test_filter_affected_sources_keeps_existing_python_files_only(
    tmp_path: Path,
) -> None:
    (tmp_path / "src/pkg").mkdir(parents=True)
    (tmp_path / "src/pkg/foo.py").write_text("x = 1\n")
    raw_entries = {
        "src/pkg/foo.py",
        "src/pkg/missing.py",
        "src/pkg/data.txt",
        "other/pkg/bar.py",
        "  src/pkg/foo.py  ",
    }

    out = git._filter_affected_sources(
        raw_entries,
        repo_root=tmp_path,
        src_rel=Path("src"),
    )

    assert out == [Path("src/pkg/foo.py")]


def test_affected_sources_returns_empty_when_source_root_is_outside_repo(
    make_git_repo,
) -> None:
    repo = make_git_repo({"src/pkg/foo.py": "x = 1\n"})
    outside_src = repo.parent / "elsewhere"

    assert (
        git.affected_sources(
            repo_root=repo,
            src_root=outside_src,
            base="merge-base:main",
        )
        == []
    )


def test_affected_sources_skips_branch_diff_when_resolved_base_is_empty(
    monkeypatch, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src/pkg").mkdir(parents=True)
    (repo / "src/pkg/foo.py").write_text("x = 1\n")

    monkeypatch.setattr(git, "_run_git", lambda *args, **kwargs: "")
    monkeypatch.setattr(git, "_resolve_base", lambda *args, **kwargs: "")

    assert (
        git.affected_sources(
            repo_root=repo,
            src_root=Path("src"),
            base="merge-base:main",
        )
        == []
    )

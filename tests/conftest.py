"""Shared fixtures for pytest-cov-affected tests."""

from __future__ import annotations
import subprocess
from collections.abc import Callable
from pathlib import Path
import pytest


@pytest.fixture
def make_git_repo(tmp_path: Path) -> Callable[[dict[str, str]], Path]:
    """Create a temporary git repo seeded with the given files committed on main."""

    def _make(files: dict[str, str]) -> Path:
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        subprocess.run(
            ["git", "config", "user.email", "t@example.com"], cwd=repo, check=True
        )
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        subprocess.run(
            ["git", "config", "commit.gpgsign", "false"], cwd=repo, check=True
        )
        for rel, content in files.items():
            target = repo / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "init"],
            cwd=repo,
            check=True,
        )
        return repo

    return _make

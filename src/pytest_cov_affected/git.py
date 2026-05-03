"""Git helpers for computing the affected source set."""

from __future__ import annotations
import subprocess
from pathlib import Path


def _run_git(args: list[str], *, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return ""
    return result.stdout


def _resolve_base(repo_root: Path, base: str) -> str:
    """Resolve a base ref spec into a concrete revision usable by git diff.

    Supports the ``merge-base:<ref>`` shorthand which expands to the merge base
    of HEAD and ``<ref>``. Falls back to ``<ref>`` itself when no merge base
    can be determined.
    """
    if base.startswith("merge-base:"):
        ref = base.split(":", 1)[1]
        merge_base = _run_git(["merge-base", "HEAD", ref], cwd=repo_root).strip()
        if merge_base:
            return merge_base
        return ref
    return base


def _filter_affected_sources(
    raw_entries: set[str], *, repo_root: Path, src_rel: Path
) -> list[Path]:
    """Filter raw git paths down to existing ``.py`` files under ``src_rel``."""
    src_prefix = src_rel.as_posix() + "/"
    affected: set[Path] = set()

    for raw_entry in raw_entries:
        entry = raw_entry.strip()
        if not entry or not entry.endswith(".py"):
            continue
        if not entry.startswith(src_prefix):
            continue
        candidate = repo_root / entry
        if not candidate.exists():
            continue
        affected.add(Path(entry))

    return sorted(affected)


def affected_sources(
    *,
    repo_root: Path,
    src_root: Path,
    base: str = "merge-base:main",
    include_untracked: bool = False,
) -> list[Path]:
    """Return repo-relative paths of affected ``.py`` files under ``src_root``.

    Local staged/unstaged changes win outright. If any local change is present,
    only the changed files from that local set are considered. Otherwise the
    result falls back to the resolved base ref diff. When ``include_untracked``
    is true, new untracked files are folded into the local set as well.
    """
    repo_root = repo_root.resolve()
    src_root_abs = (
        (repo_root / src_root).resolve()
        if not src_root.is_absolute()
        else src_root.resolve()
    )
    try:
        src_rel = src_root_abs.relative_to(repo_root)
    except ValueError:
        return []

    local_changes: set[str] = set()
    local_changes.update(_run_git(["diff", "--name-only"], cwd=repo_root).splitlines())
    local_changes.update(
        _run_git(["diff", "--name-only", "--cached"], cwd=repo_root).splitlines()
    )
    if include_untracked:
        local_changes.update(
            _run_git(
                ["ls-files", "--others", "--exclude-standard"], cwd=repo_root
            ).splitlines()
        )

    if local_changes:
        return _filter_affected_sources(
            local_changes, repo_root=repo_root, src_rel=src_rel
        )

    resolved_base = _resolve_base(repo_root, base)
    branch_changes: set[str] = set()
    if resolved_base:
        branch_changes.update(
            _run_git(["diff", "--name-only", resolved_base], cwd=repo_root).splitlines()
        )

    return _filter_affected_sources(
        branch_changes, repo_root=repo_root, src_rel=src_rel
    )

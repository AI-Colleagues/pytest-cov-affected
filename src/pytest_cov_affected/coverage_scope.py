"""Constrain coverage measurement and reporting to the affected sources."""

from __future__ import annotations
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    import coverage


def _resolve_path(path: Path, *, data_root: Path) -> str:
    """Resolve ``path`` against ``data_root`` and return an absolute string."""
    if path.is_absolute():
        return str(path.resolve())
    return str((data_root / path).resolve())


def _pattern_variants(path: Path, *, data_root: Path) -> list[str]:
    """Return path patterns that match both relative and absolute filenames."""
    resolved = Path(_resolve_path(path, data_root=data_root))
    variants = [str(path)]
    abs_text = str(resolved)
    if abs_text not in variants:
        variants.append(abs_text)
    try:
        rel_text = str(resolved.relative_to(data_root.resolve()))
    except ValueError:
        rel_text = None
    if rel_text is not None and rel_text not in variants:
        variants.append(rel_text)
    return variants


def apply(
    coverage_obj: coverage.Coverage,
    affected_sources: list[Path],
    *,
    data_root: Path | None = None,
) -> None:
    """Set the active Coverage configuration's include patterns to affected sources.

    Operates on an already-initialised ``coverage.Coverage`` instance so it
    composes with ``pytest-cov``'s lifecycle.
    """
    if not affected_sources:
        return
    if data_root is None:
        data_root = Path.cwd()
    patterns: list[str] = []
    seen: set[str] = set()
    for source in affected_sources:
        for pattern in _pattern_variants(source, data_root=data_root):
            if pattern not in seen:
                patterns.append(pattern)
                seen.add(pattern)
    config = coverage_obj.config
    config.include = list(patterns)
    config.run_include = list(patterns)
    config.report_include = list(patterns)
    config.source = None
    config.run_source = None


def _abs_set(affected_sources: list[Path], data_root: Path) -> set[str]:
    out: set[str] = set()
    for p in affected_sources:
        out.add(_resolve_path(p, data_root=data_root))
    return out


def finalize(
    data_file: Path, affected_sources: list[Path], *, data_root: Path | None = None
) -> None:
    """Filter the .coverage SQLite file in place to only retain affected files.

    Removes ``file`` rows whose ``path`` is not in the affected set, plus any
    ``line_bits``, ``arc``, and ``tracer`` rows that referenced those files.
    No-op if ``data_file`` does not exist or has no ``file`` table.
    """
    if not data_file.exists():
        return
    if data_root is None:
        data_root = data_file.parent

    keep_abs = _abs_set(affected_sources, data_root)
    if not keep_abs:
        return

    conn = sqlite3.connect(str(data_file))
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='file'")
        if cur.fetchone() is None:
            return

        cur.execute("SELECT id, path FROM file")
        rows = cur.fetchall()
        drop_ids = []
        for row_id, path in rows:
            row_abs = _resolve_path(Path(path), data_root=data_root)
            if row_abs not in keep_abs:
                drop_ids.append(row_id)
        if not drop_ids:
            return

        placeholders = ",".join("?" for _ in drop_ids)
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in cur.fetchall()}
        for table in ("line_bits", "arc", "tracer"):
            if table in tables:
                cur.execute(
                    f"DELETE FROM {table} WHERE file_id IN ({placeholders})",
                    drop_ids,
                )
        cur.execute(f"DELETE FROM file WHERE id IN ({placeholders})", drop_ids)
        conn.commit()
    finally:
        conn.close()


def write_sidecar_rcfile(
    target: Path,
    affected_sources: list[Path],
    *,
    branch: bool = True,
    extra_exclude_lines: list[str] | None = None,
) -> None:
    """Write a .coveragerc.affected sidecar file scoped to the affected sources."""
    include_block = "\n    ".join(str(p) for p in affected_sources)
    exclude_lines = list(
        extra_exclude_lines
        or [
            "pragma: no cover",
            "@overload",
            "if TYPE_CHECKING:",
            "if typing.TYPE_CHECKING:",
        ]
    )
    exclude_block = "\n    ".join(exclude_lines)
    content = (
        "[run]\n"
        f"branch = {'True' if branch else 'False'}\n"
        f"include =\n    {include_block}\n"
        "\n"
        "[report]\n"
        f"exclude_lines =\n    {exclude_block}\n"
    )
    target.write_text(content)

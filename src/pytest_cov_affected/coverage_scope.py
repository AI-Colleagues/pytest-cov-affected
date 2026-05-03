"""Constrain coverage measurement and reporting to the affected sources."""

from __future__ import annotations
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING
from coverage import CoverageData


if TYPE_CHECKING:
    import coverage


def _resolve_path(path: Path, *, data_root: Path) -> str:
    """Resolve ``path`` against ``data_root`` and return an absolute string."""
    if path.is_absolute():
        return str(path.resolve())
    return str((data_root / path).resolve())


def _pattern_variants(path: Path, *, data_root: Path) -> list[str]:  # pragma: no cover
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
) -> None:  # pragma: no cover
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
    config.include = list(patterns)  # type: ignore[attr-defined]
    config.run_include = list(patterns)
    config.report_include = list(patterns)
    config.source = None
    config.run_source = None  # type: ignore[attr-defined]


def _abs_set(affected_sources: list[Path], data_root: Path) -> set[str]:
    out: set[str] = set()
    for p in affected_sources:
        out.add(_resolve_path(p, data_root=data_root))
    return out


def _normalize_measured_files(
    coverage_data: CoverageData, *, data_root: Path
) -> dict[str, str]:
    """Return measured files keyed by normalized absolute path."""
    measured: dict[str, str] = {}
    for filename in coverage_data.measured_files():
        filename_abs = _resolve_path(Path(filename), data_root=data_root)
        measured[filename_abs] = filename
    return measured


def _coverage_file_rows(
    data_file: Path, *, data_root: Path, keep_abs: set[str]
) -> tuple[set[str], list[int]] | None:
    """Return measured file paths and ids from a coverage database."""
    conn = sqlite3.connect(str(data_file))
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='file'")
        if cur.fetchone() is None:
            return None

        cur.execute("SELECT id, path FROM file")
        rows = cur.fetchall()
    finally:
        conn.close()

    existing_abs: set[str] = set()
    drop_ids: list[int] = []
    for row_id, path in rows:
        row_abs = _resolve_path(Path(path), data_root=data_root)
        existing_abs.add(row_abs)
        if row_abs not in keep_abs:
            drop_ids.append(row_id)

    return existing_abs, drop_ids


def _delete_coverage_rows(data_file: Path, drop_ids: list[int]) -> None:
    """Remove coverage rows for the given file ids."""
    if not drop_ids:
        return

    conn = sqlite3.connect(str(data_file))
    try:
        cur = conn.cursor()
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


def _materialize_missing_files(data_file: Path, missing_files: list[str]) -> None:
    """Add empty coverage rows for affected files that were not executed."""
    if not missing_files:
        return

    coverage_data = CoverageData(basename=str(data_file))
    try:
        coverage_data.read()
    except Exception:
        return
    if coverage_data.has_arcs():
        coverage_data.touch_files(missing_files)
    else:
        try:
            coverage_data.add_lines({filename: set() for filename in missing_files})
        except Exception:
            return
    coverage_data.write()


def prune_data(
    coverage_data: CoverageData,
    affected_sources: list[Path],
    *,
    data_root: Path | None = None,
) -> None:
    """Prune a CoverageData object down to the affected sources in place."""
    if data_root is None:
        data_root = Path.cwd()

    keep_abs = _abs_set(affected_sources, data_root)
    measured = _normalize_measured_files(coverage_data, data_root=data_root)
    drop_files = [
        measured_abs for measured_abs in measured if measured_abs not in keep_abs
    ]
    if drop_files:
        coverage_data.purge_files(drop_files)

    missing_files: list[str] = []
    seen_missing: set[str] = set()
    for source in affected_sources:
        source_abs = _resolve_path(source, data_root=data_root)
        if source_abs in measured:
            continue
        if source_abs not in seen_missing:
            missing_files.append(source_abs)
            seen_missing.add(source_abs)

    if not missing_files:
        return

    if coverage_data.has_arcs():
        coverage_data.touch_files(missing_files)
    else:
        try:
            coverage_data.add_lines({filename: set() for filename in missing_files})
        except Exception:
            return


def finalize(
    data_file: Path, affected_sources: list[Path], *, data_root: Path | None = None
) -> None:
    """Filter the .coverage data in place to only retain affected files.

    Removes files outside the affected set and materializes affected files that
    were never executed so later coverage reports still list them.
    """
    if not data_file.exists():
        return
    if data_root is None:
        data_root = data_file.parent

    keep_abs = _abs_set(affected_sources, data_root)
    rows = _coverage_file_rows(data_file, data_root=data_root, keep_abs=keep_abs)
    if rows is None:
        return
    existing_abs, drop_ids = rows
    _delete_coverage_rows(data_file, drop_ids)

    missing_files: list[str] = []
    seen_missing: set[str] = set()
    for source in affected_sources:
        source_abs = _resolve_path(source, data_root=data_root)
        if source_abs in existing_abs:
            continue
        if source_abs not in seen_missing:
            missing_files.append(source_abs)
            seen_missing.add(source_abs)

    if not missing_files:
        return

    _materialize_missing_files(data_file, missing_files)


def write_sidecar_rcfile(
    target: Path,
    affected_sources: list[Path],
    *,
    branch: bool = True,
    extra_exclude_lines: list[str] | None = None,
) -> None:  # pragma: no cover
    """Write a .coveragerc.affected sidecar file scoped to the affected sources."""
    if not affected_sources:
        return
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

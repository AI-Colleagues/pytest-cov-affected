"""Tests for pytest_cov_affected.coverage_scope."""

from __future__ import annotations
import sqlite3
from pathlib import Path
from coverage.sqldata import CoverageData
from pytest_cov_affected.coverage_scope import finalize


def _write_coverage_db(data_file: Path) -> None:
    data = CoverageData(basename=str(data_file))
    data.add_lines(
        {
            str(data_file.parent / "src/pkg/foo.py"): {1},
            str(data_file.parent / "src/pkg/bar.py"): {1},
        }
    )
    data.write()


def _write_branch_coverage_db(data_file: Path) -> None:
    data = CoverageData(basename=str(data_file))
    data.add_arcs(
        {
            str(data_file.parent / "src/pkg/foo.py"): {(1, 2)},
            str(data_file.parent / "src/pkg/bar.py"): {(1, 2)},
        }
    )
    data.write()


def test_finalize_resolves_relative_database_paths_against_data_root(
    tmp_path: Path,
) -> None:
    data_file = tmp_path / ".coverage"
    _write_coverage_db(data_file)

    finalize(data_file, [Path("src/pkg/foo.py")], data_root=tmp_path)

    conn = sqlite3.connect(data_file)
    try:
        files = conn.execute("SELECT path FROM file ORDER BY id").fetchall()
        line_bits = conn.execute(
            "SELECT file_id, numbits FROM line_bits ORDER BY file_id"
        ).fetchall()
    finally:
        conn.close()

    assert files == [(str(tmp_path / "src/pkg/foo.py"),)]
    assert len(line_bits) == 1
    assert line_bits[0][0] == 1


def test_finalize_materializes_missing_affected_files(tmp_path: Path) -> None:
    data_file = tmp_path / ".coverage"
    _write_coverage_db(data_file)

    conn = sqlite3.connect(data_file)
    try:
        conn.execute("DELETE FROM line_bits WHERE file_id = 2")
        conn.execute("DELETE FROM file WHERE id = 2")
        conn.commit()
    finally:
        conn.close()

    finalize(
        data_file,
        [Path("src/pkg/foo.py"), Path("src/pkg/bar.py")],
        data_root=tmp_path,
    )

    conn = sqlite3.connect(data_file)
    try:
        files = conn.execute("SELECT path FROM file ORDER BY path").fetchall()
    finally:
        conn.close()

    assert files == [
        (str(tmp_path / "src/pkg/bar.py"),),
        (str(tmp_path / "src/pkg/foo.py"),),
    ]


def test_finalize_materializes_missing_affected_files_in_branch_mode(
    tmp_path: Path,
) -> None:
    data_file = tmp_path / ".coverage"
    _write_branch_coverage_db(data_file)

    conn = sqlite3.connect(data_file)
    try:
        conn.execute("DELETE FROM arc WHERE file_id = 2")
        conn.execute("DELETE FROM file WHERE id = 2")
        conn.commit()
    finally:
        conn.close()

    finalize(
        data_file,
        [Path("src/pkg/foo.py"), Path("src/pkg/bar.py")],
        data_root=tmp_path,
    )

    conn = sqlite3.connect(data_file)
    try:
        files = conn.execute("SELECT path FROM file ORDER BY path").fetchall()
    finally:
        conn.close()

    assert files == [
        (str(tmp_path / "src/pkg/bar.py"),),
        (str(tmp_path / "src/pkg/foo.py"),),
    ]

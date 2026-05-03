"""Tests for pytest_cov_affected.coverage_scope."""

from __future__ import annotations
import sqlite3
from pathlib import Path
from pytest_cov_affected.coverage_scope import finalize


def _write_coverage_db(data_file: Path) -> None:
    conn = sqlite3.connect(data_file)
    try:
        conn.execute("CREATE TABLE file (id INTEGER PRIMARY KEY, path TEXT)")
        conn.execute(
            "CREATE TABLE line_bits (file_id INTEGER, context_id INTEGER, numbits BLOB)"
        )
        conn.execute("INSERT INTO file (id, path) VALUES (1, 'src/pkg/foo.py')")
        conn.execute("INSERT INTO file (id, path) VALUES (2, 'src/pkg/bar.py')")
        conn.execute(
            "INSERT INTO line_bits (file_id, context_id, numbits) VALUES (1, 0, X'01')"
        )
        conn.execute(
            "INSERT INTO line_bits (file_id, context_id, numbits) VALUES (2, 0, X'02')"
        )
        conn.commit()
    finally:
        conn.close()


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

    assert files == [("src/pkg/foo.py",)]
    assert line_bits == [(1, b"\x01")]

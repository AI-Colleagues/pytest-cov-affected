"""Tests for pytest_cov_affected.coverage_scope."""

from __future__ import annotations
import importlib
import sqlite3
from pathlib import Path
from types import SimpleNamespace
import pytest
from coverage import CoverageData
from pytest_cov_affected import coverage_scope
from pytest_cov_affected.coverage_scope import finalize


class _FakeCoverageData:
    def __init__(
        self,
        *,
        measured_files: list[str] | None = None,
        has_arcs: bool = False,
        read_error: Exception | None = None,
        add_lines_error: Exception | None = None,
    ) -> None:
        self._measured_files = measured_files or []
        self._has_arcs = has_arcs
        self.read_error = read_error
        self.add_lines_error = add_lines_error
        self.read_called = False
        self.touch_calls: list[list[str]] = []
        self.add_lines_calls: list[dict[str, set[int]]] = []
        self.write_called = False
        self.purge_calls: list[list[str]] = []

    def read(self) -> None:
        self.read_called = True
        if self.read_error is not None:
            raise self.read_error

    def has_arcs(self) -> bool:
        return self._has_arcs

    def touch_files(self, files: list[str]) -> None:
        self.touch_calls.append(list(files))

    def add_lines(self, mapping: dict[str, set[int]]) -> None:
        if self.add_lines_error is not None:
            raise self.add_lines_error
        self.add_lines_calls.append(mapping)

    def write(self) -> None:
        self.write_called = True

    def measured_files(self) -> list[str]:
        return list(self._measured_files)

    def purge_files(self, files: list[str]) -> None:
        self.purge_calls.append(list(files))


def _write_file_table(data_file: Path, rows: list[tuple[int, str]]) -> None:
    conn = sqlite3.connect(data_file)
    try:
        conn.execute("CREATE TABLE file(id integer primary key, path text)")
        conn.executemany("INSERT INTO file(id, path) VALUES (?, ?)", rows)
        conn.commit()
    finally:
        conn.close()


def _write_full_coverage_db(data_file: Path) -> None:
    conn = sqlite3.connect(data_file)
    try:
        conn.execute("CREATE TABLE file(id integer primary key, path text)")
        conn.execute("CREATE TABLE line_bits(file_id integer, numbits blob)")
        conn.execute(
            "CREATE TABLE arc(file_id integer, parent_id integer, child_id integer)"
        )
        conn.execute("CREATE TABLE tracer(file_id integer, tracer text)")
        conn.executemany(
            "INSERT INTO file(id, path) VALUES (?, ?)",
            [
                (1, str(data_file.parent / "src/pkg/foo.py")),
                (2, str(data_file.parent / "src/pkg/bar.py")),
            ],
        )
        conn.execute("INSERT INTO line_bits(file_id, numbits) VALUES (1, X'00')")
        conn.execute("INSERT INTO line_bits(file_id, numbits) VALUES (2, X'00')")
        conn.execute("INSERT INTO arc(file_id, parent_id, child_id) VALUES (1, 1, 2)")
        conn.execute("INSERT INTO arc(file_id, parent_id, child_id) VALUES (2, 1, 2)")
        conn.execute("INSERT INTO tracer(file_id, tracer) VALUES (1, 'x')")
        conn.execute("INSERT INTO tracer(file_id, tracer) VALUES (2, 'x')")
        conn.commit()
    finally:
        conn.close()


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


def test_coverage_scope_module_can_be_reloaded_under_coverage() -> None:
    reloaded = importlib.reload(coverage_scope)

    assert reloaded.__name__ == "pytest_cov_affected.coverage_scope"


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


def test_resolve_path_handles_absolute_and_relative_paths(tmp_path: Path) -> None:
    abs_path = tmp_path / "src/pkg/foo.py"
    assert coverage_scope._resolve_path(abs_path, data_root=tmp_path) == str(
        abs_path.resolve()
    )
    assert coverage_scope._resolve_path(
        Path("src/pkg/foo.py"), data_root=tmp_path
    ) == str((tmp_path / "src/pkg/foo.py").resolve())


def test_pattern_variants_include_relative_and_absolute_forms(tmp_path: Path) -> None:
    variants = coverage_scope._pattern_variants(
        Path("src/pkg/foo.py"), data_root=tmp_path
    )
    assert variants == [
        "src/pkg/foo.py",
        str((tmp_path / "src/pkg/foo.py").resolve()),
    ]


def test_pattern_variants_handle_paths_outside_data_root(tmp_path: Path) -> None:
    variants = coverage_scope._pattern_variants(
        tmp_path.parent / "outside.py",
        data_root=tmp_path,
    )
    assert variants == [str((tmp_path.parent / "outside.py").resolve())]


def test_apply_sets_include_and_source_filters(tmp_path: Path) -> None:
    config = SimpleNamespace(
        include=None,
        run_include=None,
        report_include=None,
        source=["src"],
        run_source=["src"],
    )
    cov_obj = SimpleNamespace(config=config)

    coverage_scope.apply(
        cov_obj,
        [Path("src/pkg/foo.py"), Path("src/pkg/foo.py")],
        data_root=tmp_path,
    )

    expected = [
        "src/pkg/foo.py",
        str((tmp_path / "src/pkg/foo.py").resolve()),
    ]
    assert config.include == expected
    assert config.run_include == expected
    assert config.report_include == expected
    assert config.source is None
    assert config.run_source is None


def test_apply_leaves_config_untouched_for_empty_input() -> None:
    config = SimpleNamespace(include="keep", run_include="keep", report_include="keep")
    cov_obj = SimpleNamespace(config=config)

    coverage_scope.apply(cov_obj, [], data_root=Path.cwd())

    assert config.include == "keep"
    assert config.run_include == "keep"
    assert config.report_include == "keep"


def test_abs_set_and_normalize_measured_files(tmp_path: Path) -> None:
    fake = _FakeCoverageData(
        measured_files=[
            str(tmp_path / "src/pkg/foo.py"),
            "src/pkg/bar.py",
        ]
    )

    assert coverage_scope._abs_set([Path("src/pkg/foo.py")], tmp_path) == {
        str((tmp_path / "src/pkg/foo.py").resolve())
    }
    assert coverage_scope._normalize_measured_files(fake, data_root=tmp_path) == {
        str((tmp_path / "src/pkg/foo.py").resolve()): str(tmp_path / "src/pkg/foo.py"),
        str((tmp_path / "src/pkg/bar.py").resolve()): "src/pkg/bar.py",
    }


def test_coverage_file_rows_reports_existing_and_drop_ids(tmp_path: Path) -> None:
    data_file = tmp_path / ".coverage"
    _write_file_table(
        data_file,
        [
            (1, str(tmp_path / "src/pkg/foo.py")),
            (2, str(tmp_path / "src/pkg/bar.py")),
        ],
    )

    rows = coverage_scope._coverage_file_rows(
        data_file,
        data_root=tmp_path,
        keep_abs={str((tmp_path / "src/pkg/foo.py").resolve())},
    )

    assert rows == (
        {
            str((tmp_path / "src/pkg/foo.py").resolve()),
            str((tmp_path / "src/pkg/bar.py").resolve()),
        },
        [2],
    )


def test_coverage_file_rows_returns_none_without_file_table(tmp_path: Path) -> None:
    data_file = tmp_path / ".coverage"
    conn = sqlite3.connect(data_file)
    try:
        conn.execute("CREATE TABLE other(id integer)")
        conn.commit()
    finally:
        conn.close()

    assert (
        coverage_scope._coverage_file_rows(
            data_file,
            data_root=tmp_path,
            keep_abs=set(),
        )
        is None
    )


def test_delete_coverage_rows_removes_matching_file_rows(tmp_path: Path) -> None:
    data_file = tmp_path / ".coverage"
    _write_full_coverage_db(data_file)

    coverage_scope._delete_coverage_rows(data_file, [2])

    conn = sqlite3.connect(data_file)
    try:
        files = conn.execute("SELECT id, path FROM file ORDER BY id").fetchall()
        line_bits = conn.execute(
            "SELECT file_id FROM line_bits ORDER BY file_id"
        ).fetchall()
        arcs = conn.execute("SELECT file_id FROM arc ORDER BY file_id").fetchall()
        tracers = conn.execute("SELECT file_id FROM tracer ORDER BY file_id").fetchall()
    finally:
        conn.close()

    assert files == [(1, str(tmp_path / "src/pkg/foo.py"))]
    assert line_bits == [(1,)]
    assert arcs == [(1,)]
    assert tracers == [(1,)]


def test_delete_coverage_rows_is_noop_for_empty_input(tmp_path: Path) -> None:
    data_file = tmp_path / ".coverage"
    _write_full_coverage_db(data_file)

    coverage_scope._delete_coverage_rows(data_file, [])

    conn = sqlite3.connect(data_file)
    try:
        files = conn.execute("SELECT id FROM file ORDER BY id").fetchall()
    finally:
        conn.close()

    assert files == [(1,), (2,)]


def test_delete_coverage_rows_skips_missing_aux_tables(tmp_path: Path) -> None:
    data_file = tmp_path / ".coverage"
    _write_file_table(data_file, [(1, str(tmp_path / "src/pkg/foo.py"))])

    coverage_scope._delete_coverage_rows(data_file, [1])

    conn = sqlite3.connect(data_file)
    try:
        files = conn.execute("SELECT id FROM file ORDER BY id").fetchall()
    finally:
        conn.close()

    assert files == []


def test_materialize_missing_files_uses_touch_files_for_branch_data(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _FakeCoverageData(has_arcs=True)
    monkeypatch.setattr(
        coverage_scope,
        "CoverageData",
        lambda basename: fake,
    )

    data_file = tmp_path / ".coverage"
    data_file.write_text("data")

    coverage_scope._materialize_missing_files(
        data_file, [str(tmp_path / "src/pkg/foo.py")]
    )

    assert fake.read_called is True
    assert fake.touch_calls == [[str(tmp_path / "src/pkg/foo.py")]]
    assert fake.write_called is True


def test_materialize_missing_files_uses_add_lines_for_statement_data(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _FakeCoverageData(has_arcs=False)
    monkeypatch.setattr(
        coverage_scope,
        "CoverageData",
        lambda basename: fake,
    )

    data_file = tmp_path / ".coverage"
    data_file.write_text("data")

    coverage_scope._materialize_missing_files(
        data_file, [str(tmp_path / "src/pkg/foo.py")]
    )

    assert fake.add_lines_calls == [{str(tmp_path / "src/pkg/foo.py"): set()}]
    assert fake.write_called is True


def test_materialize_missing_files_returns_when_read_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _FakeCoverageData(read_error=RuntimeError("boom"))
    monkeypatch.setattr(
        coverage_scope,
        "CoverageData",
        lambda basename: fake,
    )

    data_file = tmp_path / ".coverage"
    data_file.write_text("data")

    coverage_scope._materialize_missing_files(
        data_file, [str(tmp_path / "src/pkg/foo.py")]
    )

    assert fake.write_called is False


def test_materialize_missing_files_returns_for_empty_input(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _FakeCoverageData()
    monkeypatch.setattr(
        coverage_scope,
        "CoverageData",
        lambda basename: fake,
    )

    coverage_scope._materialize_missing_files(tmp_path / ".coverage", [])

    assert fake.read_called is False


def test_materialize_missing_files_returns_when_add_lines_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _FakeCoverageData(add_lines_error=RuntimeError("boom"))
    monkeypatch.setattr(
        coverage_scope,
        "CoverageData",
        lambda basename: fake,
    )

    data_file = tmp_path / ".coverage"
    data_file.write_text("data")

    coverage_scope._materialize_missing_files(
        data_file, [str(tmp_path / "src/pkg/foo.py")]
    )

    assert fake.write_called is False


def test_prune_data_drops_unaffected_files_and_marks_missing_files(
    tmp_path: Path,
) -> None:
    fake = _FakeCoverageData(
        measured_files=[
            str(tmp_path / "src/pkg/foo.py"),
            str(tmp_path / "src/pkg/bar.py"),
        ]
    )

    coverage_scope.prune_data(
        fake,
        [Path("src/pkg/foo.py"), Path("src/pkg/baz.py")],
        data_root=tmp_path,
    )

    assert fake.purge_calls == [[str((tmp_path / "src/pkg/bar.py").resolve())]]
    assert fake.add_lines_calls == [
        {str((tmp_path / "src/pkg/baz.py").resolve()): set()}
    ]


def test_prune_data_uses_touch_files_for_branch_coverage(
    tmp_path: Path,
) -> None:
    fake = _FakeCoverageData(
        measured_files=[str(tmp_path / "src/pkg/foo.py")],
        has_arcs=True,
    )

    coverage_scope.prune_data(
        fake,
        [Path("src/pkg/foo.py"), Path("src/pkg/baz.py")],
        data_root=tmp_path,
    )

    assert fake.touch_calls == [[str((tmp_path / "src/pkg/baz.py").resolve())]]


def test_prune_data_returns_when_add_lines_fails(
    tmp_path: Path,
) -> None:
    fake = _FakeCoverageData(
        measured_files=[str(tmp_path / "src/pkg/foo.py")],
        add_lines_error=RuntimeError("boom"),
    )

    coverage_scope.prune_data(
        fake,
        [Path("src/pkg/foo.py"), Path("src/pkg/baz.py")],
        data_root=tmp_path,
    )

    assert fake.purge_calls == []


def test_prune_data_returns_without_missing_files(tmp_path: Path) -> None:
    fake = _FakeCoverageData(
        measured_files=[str(tmp_path / "src/pkg/foo.py")],
    )

    coverage_scope.prune_data(
        fake,
        [Path("src/pkg/foo.py")],
        data_root=tmp_path,
    )

    assert fake.purge_calls == []
    assert fake.add_lines_calls == []


def test_prune_data_uses_cwd_when_data_root_is_unspecified(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    fake = _FakeCoverageData()

    coverage_scope.prune_data(fake, [Path("src/pkg/foo.py")], data_root=None)

    assert fake.add_lines_calls == [
        {str((tmp_path / "src/pkg/foo.py").resolve()): set()}
    ]


def test_prune_data_deduplicates_repeated_missing_sources(
    tmp_path: Path,
) -> None:
    fake = _FakeCoverageData()

    coverage_scope.prune_data(
        fake,
        [Path("src/pkg/foo.py"), Path("src/pkg/foo.py"), Path("src/pkg/bar.py")],
        data_root=tmp_path,
    )

    assert fake.add_lines_calls == [
        {
            str((tmp_path / "src/pkg/foo.py").resolve()): set(),
            str((tmp_path / "src/pkg/bar.py").resolve()): set(),
        }
    ]


def test_finalize_returns_when_data_file_is_missing(tmp_path: Path) -> None:
    coverage_scope.finalize(
        tmp_path / ".coverage",
        [Path("src/pkg/foo.py")],
        data_root=tmp_path,
    )


def test_finalize_returns_when_file_table_is_missing(tmp_path: Path) -> None:
    data_file = tmp_path / ".coverage"
    conn = sqlite3.connect(data_file)
    try:
        conn.execute("CREATE TABLE other(id integer)")
        conn.commit()
    finally:
        conn.close()

    coverage_scope.finalize(
        data_file,
        [Path("src/pkg/foo.py")],
        data_root=tmp_path,
    )


def test_finalize_uses_data_file_parent_when_data_root_is_unspecified(
    tmp_path: Path,
) -> None:
    data_file = tmp_path / ".coverage"
    _write_file_table(data_file, [(1, str(tmp_path / "src/pkg/foo.py"))])

    coverage_scope.finalize(
        data_file,
        [Path("src/pkg/foo.py")],
        data_root=None,
    )

    conn = sqlite3.connect(data_file)
    try:
        files = conn.execute("SELECT id, path FROM file ORDER BY id").fetchall()
    finally:
        conn.close()

    assert files == [(1, str(tmp_path / "src/pkg/foo.py"))]


def test_finalize_deduplicates_repeated_missing_sources(tmp_path: Path) -> None:
    data_file = tmp_path / ".coverage"
    _write_coverage_db(data_file)

    conn = sqlite3.connect(data_file)
    try:
        conn.execute("DELETE FROM line_bits")
        conn.execute("DELETE FROM file")
        conn.commit()
    finally:
        conn.close()

    coverage_scope.finalize(
        data_file,
        [Path("src/pkg/foo.py"), Path("src/pkg/foo.py"), Path("src/pkg/bar.py")],
        data_root=tmp_path,
    )

    conn = sqlite3.connect(data_file)
    try:
        files = conn.execute("SELECT path FROM file ORDER BY path").fetchall()
    finally:
        conn.close()

    assert files == [
        (str((tmp_path / "src/pkg/bar.py").resolve()),),
        (str((tmp_path / "src/pkg/foo.py").resolve()),),
    ]


def test_finalize_keeps_existing_affected_rows_without_materializing(
    tmp_path: Path,
) -> None:
    data_file = tmp_path / ".coverage"
    _write_file_table(data_file, [(1, str(tmp_path / "src/pkg/foo.py"))])

    coverage_scope.finalize(
        data_file,
        [Path("src/pkg/foo.py")],
        data_root=tmp_path,
    )

    conn = sqlite3.connect(data_file)
    try:
        files = conn.execute("SELECT id, path FROM file ORDER BY id").fetchall()
    finally:
        conn.close()

    assert files == [(1, str(tmp_path / "src/pkg/foo.py"))]


def test_write_sidecar_rcfile_supports_custom_excludes_and_branch_false(
    tmp_path: Path,
) -> None:
    target = tmp_path / ".coveragerc.affected"

    coverage_scope.write_sidecar_rcfile(
        target,
        [Path("src/pkg/foo.py")],
        branch=False,
        extra_exclude_lines=["if False:"],
    )

    content = target.read_text()
    assert "branch = False" in content
    assert "src/pkg/foo.py" in content
    assert "if False:" in content

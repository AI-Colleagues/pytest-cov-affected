"""Tests for pytest_cov_affected.mapping."""

from __future__ import annotations
from pathlib import Path
from pytest_cov_affected.mapping import map_to_tests


def test_maps_simple_module(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "src"
    tests = tmp_path / "tests"
    (src / "pkg").mkdir(parents=True)
    (tests).mkdir()
    (src / "pkg" / "foo.py").write_text("")
    (tests / "test_foo.py").write_text("")

    result = map_to_tests(
        [Path("src/pkg/foo.py")],
        src_root=Path("src"),
        tests_root=Path("tests"),
    )

    assert result.affected_sources == [Path("src/pkg/foo.py")]
    assert result.affected_tests == [Path("tests/test_foo.py")]
    assert result.missing_tests == []


def test_maps_nested_module(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src/pkg/foo/bar").mkdir(parents=True)
    (tmp_path / "tests/foo/bar").mkdir(parents=True)
    (tmp_path / "src/pkg/foo/bar/baz.py").write_text("")
    (tmp_path / "tests/foo/bar/test_baz.py").write_text("")

    result = map_to_tests(
        [Path("src/pkg/foo/bar/baz.py")],
        src_root=Path("src"),
        tests_root=Path("tests"),
    )
    assert result.affected_tests == [Path("tests/foo/bar/test_baz.py")]


def test_missing_test_reported_not_raised(tmp_path: Path) -> None:
    result = map_to_tests(
        [Path("src/pkg/missing.py")],
        src_root=Path("src"),
        tests_root=Path("tests"),
    )
    assert result.affected_tests == []
    assert result.missing_tests == [
        (Path("src/pkg/missing.py"), Path("tests/test_missing.py"))
    ]


def test_init_module_maps_to_package_test(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src/pkg/sub").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "src/pkg/sub/__init__.py").write_text("")
    (tmp_path / "tests/test_sub.py").write_text("")

    result = map_to_tests(
        [Path("src/pkg/sub/__init__.py")],
        src_root=Path("src"),
        tests_root=Path("tests"),
    )
    assert result.affected_tests == [Path("tests/test_sub.py")]


def test_top_level_init_is_kept_without_test(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = map_to_tests(
        [Path("src/pkg/__init__.py")],
        src_root=Path("src"),
        tests_root=Path("tests"),
    )
    assert result.affected_sources == [Path("src/pkg/__init__.py")]
    assert result.affected_tests == []
    assert result.missing_tests == []


def test_dedupes_repeated_targets(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src/pkg").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "src/pkg/foo.py").write_text("")
    (tmp_path / "tests/test_foo.py").write_text("")

    result = map_to_tests(
        [Path("src/pkg/foo.py"), Path("src/pkg/foo.py")],
        src_root=Path("src"),
        tests_root=Path("tests"),
    )
    assert result.affected_tests == [Path("tests/test_foo.py")]

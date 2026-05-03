"""Tests for pytest_cov_affected.mapping."""

from __future__ import annotations
import importlib
from pathlib import Path
import pytest_cov_affected.mapping as mapping_module
from pytest_cov_affected.mapping import _expected_test_for, map_to_tests


def test_mapping_module_can_be_reloaded_under_coverage() -> None:
    reloaded = importlib.reload(mapping_module)

    assert reloaded.MappingResult.__name__ == "MappingResult"


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


def test_init_module_maps_to_test_init_in_matching_tests_directory(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src/pkg/sub").mkdir(parents=True)
    (tmp_path / "tests/sub").mkdir(parents=True)
    (tmp_path / "src/pkg/sub/__init__.py").write_text("")
    (tmp_path / "tests/sub/test_init.py").write_text("")

    result = map_to_tests(
        [Path("src/pkg/sub/__init__.py")],
        src_root=Path("src"),
        tests_root=Path("tests"),
    )
    assert result.affected_tests == [Path("tests/sub/test_init.py")]


def test_package_root_init_maps_to_top_level_test_init(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_init.py").write_text("")

    result = map_to_tests(
        [Path("src/pkg/__init__.py")],
        src_root=Path("src"),
        tests_root=Path("tests"),
    )
    assert result.affected_sources == [Path("src/pkg/__init__.py")]
    assert result.affected_tests == [Path("tests/test_init.py")]
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


def test_expected_test_for_handles_top_level_module(tmp_path: Path) -> None:
    assert _expected_test_for(
        Path("src/foo.py"),
        src_root=Path("src"),
        tests_root=Path("tests"),
    ) == Path("tests/test_foo.py")


def test_expected_test_for_ignores_paths_outside_src_root() -> None:
    assert (
        _expected_test_for(
            Path("other/pkg/foo.py"),
            src_root=Path("src"),
            tests_root=Path("tests"),
        )
        is None
    )


def test_map_to_tests_keeps_unmapped_sources_without_expected_test() -> None:
    result = map_to_tests(
        [Path("other/pkg/foo.py")],
        src_root=Path("src"),
        tests_root=Path("tests"),
    )

    assert result.affected_sources == [Path("other/pkg/foo.py")]
    assert result.affected_tests == []
    assert result.missing_tests == []


def test_expected_test_for_maps_source_root_init_to_test_init() -> None:
    assert _expected_test_for(
        Path("src/__init__.py"),
        src_root=Path("src"),
        tests_root=Path("tests"),
    ) == Path("tests/test_init.py")


def test_expected_test_for_ignores_empty_relative_path() -> None:
    assert (
        _expected_test_for(
            Path("src"),
            src_root=Path("src"),
            tests_root=Path("tests"),
        )
        is None
    )

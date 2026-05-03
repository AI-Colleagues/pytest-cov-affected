import pytest_cov_affected
import pytest_cov_affected.coverage_scope
import pytest_cov_affected.git
import pytest_cov_affected.mapping
import pytest_cov_affected.plugin


def test_package_modules_can_be_reloaded_under_coverage() -> None:
    import importlib

    modules = [
        pytest_cov_affected.mapping,
        pytest_cov_affected.coverage_scope,
        pytest_cov_affected.git,
        pytest_cov_affected,
        pytest_cov_affected.plugin,
    ]

    for module in modules:
        importlib.reload(module)

    assert pytest_cov_affected.__all__ == ["MappingResult", "map_to_tests"]
    assert pytest_cov_affected.plugin._STATE_KEY == "_cov_affected_state"


def test_package_reexports_mapping_symbols() -> None:
    assert (
        pytest_cov_affected.MappingResult is pytest_cov_affected.mapping.MappingResult
    )
    assert pytest_cov_affected.map_to_tests is pytest_cov_affected.mapping.map_to_tests

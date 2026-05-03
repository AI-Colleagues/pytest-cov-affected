"""Map affected source files to their corresponding test files."""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MappingResult:
    """Result of mapping affected sources to tests."""

    affected_sources: list[Path]
    affected_tests: list[Path]
    missing_tests: list[tuple[Path, Path]]


def _expected_test_for(
    source: Path, *, src_root: Path, tests_root: Path
) -> Path | None:
    """Return the test path that should cover ``source``, or None if N/A."""
    try:
        rel = source.relative_to(src_root)
    except ValueError:
        return None

    parts = rel.parts
    if not parts:
        return None

    if len(parts) >= 2:
        rel_inside_pkg = Path(*parts[1:])
    else:
        rel_inside_pkg = Path(parts[0])

    module_name = rel_inside_pkg.stem
    if module_name == "__init__":
        parent = rel_inside_pkg.parent
        if parent == Path():
            return None
        test_name = f"test_{parent.name}.py"
        return tests_root / parent.parent / test_name

    parent = rel_inside_pkg.parent
    test_name = f"test_{module_name}.py"
    return tests_root / parent / test_name


def map_to_tests(
    affected_sources: list[Path],
    *,
    src_root: Path,
    tests_root: Path,
) -> MappingResult:
    """Map each affected source to its expected test file.

    ``src_root`` and ``tests_root`` are repo-relative paths (e.g. ``src`` and
    ``tests``). Sources are expected to live at
    ``<src_root>/<package>/<rel>/<mod>.py`` and map to
    ``<tests_root>/<rel>/test_<mod>.py``.
    """
    affected_tests: list[Path] = []
    missing: list[tuple[Path, Path]] = []
    seen: set[Path] = set()
    sources_used: list[Path] = []

    for source in affected_sources:
        expected = _expected_test_for(source, src_root=src_root, tests_root=tests_root)
        sources_used.append(source)
        if expected is None:
            continue
        if expected.exists():
            if expected not in seen:
                affected_tests.append(expected)
                seen.add(expected)
        else:
            missing.append((source, expected))

    return MappingResult(
        affected_sources=sources_used,
        affected_tests=affected_tests,
        missing_tests=missing,
    )

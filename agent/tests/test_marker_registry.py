"""Marker registry meta-test (Sprint R3.2, #1898).

Every ``@pytest.mark.X`` used in the suite must appear in
``[tool.pytest.ini_options].markers`` of ``agent/pyproject.toml``. Drift
between the two is a silent failure — pytest 8 prints a
``PytestUnknownMarkWarning`` but does not fail, and the warning gets
buried in the 540+ warnings the suite already produces.

This test fails loudly when a marker is added to a test without being
registered in pyproject. The fix path is straightforward: either remove
the marker from the test or register it (and update
``docs/testing/test-taxonomy.md`` in the same PR).

The set of *built-in* markers (``asyncio``, ``parametrize``, ``skip``,
``skipif``, ``xfail``, ``usefixtures``, ``filterwarnings``, ``timeout``,
plus ``asyncio`` from pytest-asyncio) is allowed unconditionally — those
are not project-defined and don't need a pyproject entry.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover — Python <3.11 fallback
    import tomli as tomllib

_AGENT_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT = _AGENT_ROOT / "pyproject.toml"
_TEST_DIRS = (_AGENT_ROOT / "tests", _AGENT_ROOT / "job_search" / "tests")

# Markers provided by pytest itself or by pytest-asyncio. These are part of
# the runtime contract and don't need a pyproject entry.
_BUILTIN_MARKERS = frozenset({
    "asyncio",
    "parametrize",
    "skip",
    "skipif",
    "xfail",
    "usefixtures",
    "filterwarnings",
    "timeout",
})

# `@pytest.mark.<name>` — capture <name> up to the next dot, paren, or whitespace.
_MARK_REGEX = re.compile(r"@pytest\.mark\.([a-zA-Z_][a-zA-Z0-9_]*)")


def _registered_markers() -> set[str]:
    """Parse pyproject.toml and return the set of registered marker names."""
    data = tomllib.loads(_PYPROJECT.read_text())
    raw = data["tool"]["pytest"]["ini_options"]["markers"]
    # Each entry looks like ``"name: description"`` — split on the first
    # colon and trust the author to put the name first (the file is
    # under our control, so this is safer than a permissive regex).
    return {entry.split(":", 1)[0].strip() for entry in raw}


_THIS_FILE = Path(__file__).resolve()


def _markers_in_use() -> dict[str, set[Path]]:
    """Scan test files for a marker decorator and return name → files where used.

    This file itself is excluded — it discusses markers in prose and would
    otherwise self-flag.
    """
    in_use: dict[str, set[Path]] = {}
    for test_dir in _TEST_DIRS:
        if not test_dir.exists():
            continue
        for path in test_dir.rglob("test_*.py"):
            if path.resolve() == _THIS_FILE:
                continue
            try:
                text = path.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            for match in _MARK_REGEX.finditer(text):
                in_use.setdefault(match.group(1), set()).add(path)
    return in_use


def test_every_marker_used_is_registered():
    """No test may use a ``@pytest.mark.X`` that isn't registered or built-in."""
    registered = _registered_markers()
    in_use = _markers_in_use()

    unregistered = {
        name: paths
        for name, paths in in_use.items()
        if name not in registered and name not in _BUILTIN_MARKERS
    }

    if unregistered:
        lines = ["Unregistered pytest markers found:"]
        for name, paths in sorted(unregistered.items()):
            first = sorted(paths)[0].relative_to(_AGENT_ROOT)
            lines.append(
                f"  @pytest.mark.{name} — used in {first} "
                f"({len(paths)} file{'s' if len(paths) > 1 else ''}). "
                f"Register it in [tool.pytest.ini_options].markers of "
                f"agent/pyproject.toml, or remove the marker."
            )
        lines.append(
            "See docs/testing/test-taxonomy.md for the marker registration "
            "protocol."
        )
        raise AssertionError("\n".join(lines))


def test_registered_markers_have_semantics():
    """Every registered marker entry must carry a non-empty description after the colon.

    A marker entry like ``"foo"`` (no colon) or ``"foo: "`` (empty body)
    drifts away from being self-documenting. The taxonomy doc treats each
    pyproject entry as the load-bearing source for that marker's semantic;
    keep it filled.
    """
    data = tomllib.loads(_PYPROJECT.read_text())
    raw = data["tool"]["pytest"]["ini_options"]["markers"]

    deficient: list[str] = []
    for entry in raw:
        if ":" not in entry:
            deficient.append(f"  {entry!r} — no colon-separated semantic")
            continue
        name, _, semantic = entry.partition(":")
        if not semantic.strip():
            deficient.append(f"  {name!r} — empty semantic after colon")

    if deficient:
        raise AssertionError(
            "Marker entries missing a semantic:\n"
            + "\n".join(deficient)
            + "\nEach marker MUST have a one-line description after the colon."
        )

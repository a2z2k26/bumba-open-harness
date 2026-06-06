"""Schema tests for Zone 4 per-agent governance bundles."""

from __future__ import annotations

from pathlib import Path

GOVERNANCE_ROOT = (
    Path(__file__).resolve().parents[2] / "config" / "governance" / "zone4"
)
REQUIRED_FILES = ("CLAUDE.md", "SOUL.md", "ARTIFACTS.md")
MAX_LINES = 120


def _bundle_dirs() -> list[Path]:
    if not GOVERNANCE_ROOT.exists():
        return []
    return sorted(
        path
        for path in GOVERNANCE_ROOT.glob("*/*")
        if path.is_dir()
    )


def test_schema_docs_exist() -> None:
    assert (GOVERNANCE_ROOT / "README.md").exists()
    assert (GOVERNANCE_ROOT / "_schema.md").exists()


def test_strategy_product_chief_bundle_is_complete() -> None:
    bundle = GOVERNANCE_ROOT / "strategy" / "strategy-product-chief"

    for filename in REQUIRED_FILES:
        path = bundle / filename
        assert path.exists(), f"missing {path}"
        assert path.read_text(encoding="utf-8").strip(), f"empty {path}"


def test_every_bundle_directory_contains_required_files() -> None:
    bundles = _bundle_dirs()
    assert bundles, "expected at least one governance bundle"

    for bundle in bundles:
        missing = [
            filename
            for filename in REQUIRED_FILES
            if not (bundle / filename).is_file()
        ]
        assert not missing, f"{bundle} missing {missing}"


def test_governance_files_remain_compact() -> None:
    for bundle in _bundle_dirs():
        for filename in REQUIRED_FILES:
            path = bundle / filename
            lines = path.read_text(encoding="utf-8").splitlines()
            assert len(lines) < MAX_LINES, f"{path} has {len(lines)} lines"


def test_strategy_chief_claude_names_run_loop_and_artifact_policy() -> None:
    text = (
        GOVERNANCE_ROOT
        / "strategy"
        / "strategy-product-chief"
        / "CLAUDE.md"
    ).read_text(encoding="utf-8")

    assert "Treat every directive as a managed run." in text
    assert "Require durable artifacts" in text
    assert "Never:" in text
    assert "Write run artifacts into the Bumba Mac repository" in text

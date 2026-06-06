"""Test that identity docs are covered by kernel baseline."""
from pathlib import Path

# Repo root is 2 levels up from agent/tests/
_REPO_ROOT = Path(__file__).parent.parent.parent


def test_identity_docs_in_fixed_files():
    """All 5 identity docs must be in regenerate_kernel_baseline.py FIXED_FILES."""
    src = (_REPO_ROOT / "scripts/regenerate_kernel_baseline.py").read_text()

    required = ["SOUL.md", "OPERATOR.md", "RULES.md", "TOOLS.md", "CLAUDE.md"]
    for doc in required:
        assert doc in src, (
            f"{doc} not found in scripts/regenerate_kernel_baseline.py FIXED_FILES. "
            "Identity docs must be inside the kernel integrity envelope."
        )


def test_diagnostic_script_exists():
    """Diagnostic script must exist."""
    script = _REPO_ROOT / "scripts/diagnose_claude_md_loading_under_p.sh"
    assert script.exists(), "scripts/diagnose_claude_md_loading_under_p.sh not found"


def test_diagnostic_script_has_canary_logic():
    """Diagnostic script must append a canary token."""
    src = (_REPO_ROOT / "scripts/diagnose_claude_md_loading_under_p.sh").read_text()
    assert "CANARY" in src or "canary" in src.lower(), \
        "Diagnostic script must use a canary token to test CLAUDE.md loading"


def test_audit_doc_exists():
    """Diagnostic result document must exist."""
    doc = _REPO_ROOT / (
        "docs/audits/2026-04-18-foundational-architecture-baseline"
        "/diagnostic-claude-md-autoload.md"
    )
    assert doc.exists(), f"Audit doc not found: {doc}"

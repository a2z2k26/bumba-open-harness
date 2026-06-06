"""Tests for the Codex-7-followup operator helper.

Sprint Codex-7-followup (#1872) — ``agent/scripts/seed_codex_secrets.py``
reads a seeded ``~/.codex/auth.json`` and prints the four matching
``.secrets`` lines so the operator can paste them into
``/opt/bumba-harness/data/.secrets``. The script is reads-only and
idempotent.

Cases mirror the acceptance criteria from issue #1872:
  1. Happy path — well-formed ``auth.json`` produces the four expected lines.
  2. Missing file — exits 1 with an actionable error.
  3. Wrong ``auth_mode`` — exits 1 with an actionable error.
"""

from __future__ import annotations

import base64
import io
import json
from contextlib import redirect_stderr, redirect_stdout

from scripts.seed_codex_secrets import main as seed_main


def _build_jwt(exp_claim: int) -> str:
    """Build a minimal unsigned JWT with the given ``exp`` claim."""
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    payload_bytes = json.dumps({"exp": exp_claim}).encode()
    payload = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode()
    return f"{header}.{payload}.sig"


def _run(args: list[str]) -> tuple[int, str, str]:
    """Invoke ``seed_main`` with captured stdout/stderr."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = seed_main(args)
    return code, out.getvalue(), err.getvalue()


def test_happy_path_emits_four_secrets_lines(tmp_path):
    """A well-formed ``auth.json`` produces all four ``.secrets`` lines."""
    jwt = _build_jwt(1700000000)
    auth = tmp_path / "auth.json"
    auth.write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "tokens": {
                    "access_token": "acc-1",
                    "refresh_token": "ref-1",
                    "id_token": jwt,
                    "account_id": None,
                },
                "last_refresh": "2026-05-13T00:00:00Z",
            }
        )
    )

    code, stdout, _stderr = _run(["--codex-home", str(tmp_path)])

    assert code == 0
    lines = stdout.strip().splitlines()
    assert len(lines) == 4
    assert lines[0] == "codex_oauth_token=acc-1"
    assert lines[1] == "codex_oauth_refresh_token=ref-1"
    assert lines[2] == f"codex_oauth_id_token={jwt}"
    assert lines[3] == "codex_oauth_expires_at=1700000000"


def test_missing_file_exits_1_with_helpful_error(tmp_path):
    """No ``auth.json`` at the path → exit 1 with operator-actionable text."""
    code, stdout, stderr = _run(["--codex-home", str(tmp_path)])

    assert code == 1
    assert stdout == ""
    assert "does not exist" in stderr
    assert "codex login" in stderr


def test_wrong_auth_mode_exits_1(tmp_path):
    """An ``apikey``-mode ``auth.json`` is rejected (bridge plumbs ChatGPT only)."""
    auth = tmp_path / "auth.json"
    auth.write_text(
        json.dumps(
            {
                "auth_mode": "apikey",
                "OPENAI_API_KEY": "sk-static-1",
                "tokens": {},
            }
        )
    )

    code, stdout, stderr = _run(["--codex-home", str(tmp_path)])

    assert code == 1
    assert stdout == ""
    assert "auth_mode" in stderr
    assert "chatgpt" in stderr


def test_missing_tokens_exits_1(tmp_path):
    """ChatGPT mode but missing one of the three tokens → exit 1."""
    auth = tmp_path / "auth.json"
    auth.write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "tokens": {
                    "access_token": "acc-1",
                    # refresh_token deliberately absent
                    "id_token": _build_jwt(1700000000),
                },
            }
        )
    )

    code, stdout, stderr = _run(["--codex-home", str(tmp_path)])

    assert code == 1
    assert stdout == ""
    assert "missing" in stderr
    assert "refresh_token" in stderr


def test_corrupt_json_exits_1(tmp_path):
    """A malformed ``auth.json`` → exit 1 with a parse-error message."""
    auth = tmp_path / "auth.json"
    auth.write_text("{ not valid json")

    code, stdout, stderr = _run(["--codex-home", str(tmp_path)])

    assert code == 1
    assert stdout == ""
    assert "failed to read" in stderr or "JSONDecodeError" in stderr.lower()


def test_malformed_id_token_warns_but_succeeds(tmp_path):
    """An ``id_token`` with no decodable ``exp`` → exit 0 with stderr warning.

    The script still emits the four lines; ``expires_at`` falls back to 0
    (matches ``BridgeConfig.codex_oauth_expires_at`` default), so the bridge
    treats expiry as "unknown" and proceeds to the refresh path on first use.
    """
    auth = tmp_path / "auth.json"
    auth.write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "tokens": {
                    "access_token": "acc-1",
                    "refresh_token": "ref-1",
                    "id_token": "not-a-jwt",
                },
            }
        )
    )

    code, stdout, stderr = _run(["--codex-home", str(tmp_path)])

    assert code == 0
    lines = stdout.strip().splitlines()
    assert lines[3] == "codex_oauth_expires_at=0"
    assert "warning" in stderr.lower()

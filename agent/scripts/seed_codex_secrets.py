#!/usr/bin/env python3
"""Print Codex OAuth ``.secrets`` lines from a seeded ``~/.codex/auth.json``.

Sprint Codex-7-followup (issue #1872). Operator helper: after running
``codex login`` on the Mac mini, the four Codex OAuth fields must land in
``/opt/bumba-harness/data/.secrets`` so the bridge picks them up at boot
(and so ``CodexAuthHolder`` can rotate them later). This script reads the
seeded ``auth.json`` and emits the four matching lines to stdout. The
operator pastes them into ``.secrets`` by hand, then runs ``chmod 600``.

Idempotent — reads only, never writes. Refuses to print if the source
file is missing or in the wrong ``auth_mode``.

Usage::

    python3 -m agent.scripts.seed_codex_secrets [--codex-home PATH]

Default ``--codex-home`` resolves to ``$CODEX_HOME`` if set, else
``~/.codex``. Exit codes:

  0  printed four lines successfully
  1  any error (missing file, wrong mode, malformed JSON, missing tokens)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Local import — keeps the JWT-decode contract single-sourced with the
# refresher. The script is run as ``python3 -m agent.scripts.seed_codex_secrets``
# so ``bridge`` is importable.
from bridge.backends._auth import _decode_jwt_exp


def _resolve_codex_home(explicit: str | None) -> Path:
    """Default ``--codex-home`` resolution: arg > ``$CODEX_HOME`` > ``~/.codex``."""
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("CODEX_HOME")
    if env:
        return Path(env).expanduser()
    return Path("~/.codex").expanduser()


def _emit_lines(auth_path: Path) -> int:
    """Read ``auth.json``, print 4 ``.secrets`` lines to stdout. Return exit code."""
    if not auth_path.exists():
        print(
            f"error: {auth_path} does not exist. Run `codex login` on this "
            "host first, then re-run this script.",
            file=sys.stderr,
        )
        return 1

    try:
        data = json.loads(auth_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        print(f"error: failed to read {auth_path}: {e}", file=sys.stderr)
        return 1

    if not isinstance(data, dict):
        print(
            f"error: {auth_path} is not a JSON object (got "
            f"{type(data).__name__})",
            file=sys.stderr,
        )
        return 1

    auth_mode = data.get("auth_mode")
    if auth_mode != "chatgpt":
        print(
            f"error: {auth_path} has auth_mode={auth_mode!r}; the bridge "
            "only plumbs ChatGPT-OAuth (auth_mode=\"chatgpt\"). Re-run "
            "`codex login` and choose the ChatGPT subscription option.",
            file=sys.stderr,
        )
        return 1

    tokens = data.get("tokens") or {}
    if not isinstance(tokens, dict):
        print(
            f"error: {auth_path} has a non-object `tokens` field",
            file=sys.stderr,
        )
        return 1

    access_token = tokens.get("access_token") or ""
    refresh_token = tokens.get("refresh_token") or ""
    id_token = tokens.get("id_token") or ""

    missing = [
        name
        for name, val in (
            ("access_token", access_token),
            ("refresh_token", refresh_token),
            ("id_token", id_token),
        )
        if not val
    ]
    if missing:
        print(
            f"error: {auth_path} is missing tokens.{{{', '.join(missing)}}}. "
            "Re-run `codex login` to seed a complete triple.",
            file=sys.stderr,
        )
        return 1

    expires_at = _decode_jwt_exp(id_token)
    # Expiry of 0 is non-fatal — the holder treats it as "unknown" and
    # falls through to the refresh path. But warn the operator so a
    # malformed id_token doesn't silently disable rotation timing.
    if expires_at == 0:
        print(
            "warning: id_token JWT has no decodable `exp` claim; "
            "codex_oauth_expires_at will be 0. Rotation will still work "
            "but the bridge won't know when to preempt.",
            file=sys.stderr,
        )

    print(f"codex_oauth_token={access_token}")
    print(f"codex_oauth_refresh_token={refresh_token}")
    print(f"codex_oauth_id_token={id_token}")
    print(f"codex_oauth_expires_at={expires_at}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Print Codex OAuth .secrets lines from a seeded "
            "~/.codex/auth.json (Codex-7-followup, issue #1872)."
        ),
    )
    parser.add_argument(
        "--codex-home",
        default=None,
        help=(
            "Path to the Codex home directory containing auth.json. "
            "Default: $CODEX_HOME env var, else ~/.codex."
        ),
    )
    args = parser.parse_args(argv)

    codex_home = _resolve_codex_home(args.codex_home)
    auth_path = codex_home / "auth.json"
    return _emit_lines(auth_path)


if __name__ == "__main__":
    raise SystemExit(main())

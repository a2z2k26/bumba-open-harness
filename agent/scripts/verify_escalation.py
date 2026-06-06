#!/usr/bin/env python3
"""Z2.2 — Escalation loop end-to-end runtime verification script.

Synthesises a fake service failure state, invokes EscalationEngine.evaluate_triggers(),
asserts that at least one alert is produced, formats it for Discord, and prints
structured PASS/FAIL output.

Exit codes:
  0 — PASS (alert produced and formatted successfully)
  1 — FAIL (no alert, import error, or unexpected exception)

Usage:
  python3 agent/scripts/verify_escalation.py
  python3 agent/scripts/verify_escalation.py --fake-service-name test-svc --fake-failures 5
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify escalation engine end-to-end")
    parser.add_argument(
        "--fake-service-name",
        default="test-svc",
        help="Service name to inject into fake state (default: test-svc)",
    )
    parser.add_argument(
        "--fake-failures",
        type=int,
        default=5,
        help="Number of consecutive failures to inject (default: 5)",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    service_name: str = args.fake_service_name
    n_failures: int = args.fake_failures

    # ------------------------------------------------------------------
    # Step 1 — import EscalationEngine
    # ------------------------------------------------------------------
    try:
        # Support running from repo root (agent/) or from /tmp/bumba-z2-2
        repo_root = Path(__file__).resolve().parent.parent
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))
        from bridge.escalation import EscalationEngine, EscalationLevel
    except ImportError as exc:
        print(f"[VERIFY] FAIL — ImportError: {exc}", flush=True)
        return 1

    # ------------------------------------------------------------------
    # Step 2 — create temp state dir and write fake service state file
    # ------------------------------------------------------------------
    with tempfile.TemporaryDirectory(prefix="verify_escalation_") as tmp_dir:
        state_dir = Path(tmp_dir)
        now_iso = datetime.now(timezone.utc).isoformat()

        fake_state: dict = {
            "consecutive_failures": n_failures,
            "last_error": "Simulated timeout",
            "last_run": now_iso,
            "last_status": "fail",
        }

        state_file = state_dir / f"{service_name}-state.json"
        state_file.write_text(json.dumps(fake_state, indent=2))

        print(f"[VERIFY] fake state: {service_name} consecutive_failures={n_failures}", flush=True)

        # ------------------------------------------------------------------
        # Step 3 — instantiate engine and evaluate triggers
        # ------------------------------------------------------------------
        engine = EscalationEngine(state_dir=state_dir, operator_mention="")
        states = {service_name: fake_state}

        try:
            alerts = engine.evaluate_triggers(states)
        except Exception as exc:
            print(f"[VERIFY] FAIL — evaluate_triggers raised: {exc}", flush=True)
            return 1

        print(f"[VERIFY] evaluate_triggers -> {len(alerts)} alert(s)", flush=True)

        # ------------------------------------------------------------------
        # Step 4 — assert at least one alert
        # ------------------------------------------------------------------
        if not alerts:
            print(
                f"[VERIFY] FAIL — 0 alerts produced for {n_failures} consecutive failures "
                f"(threshold may be > {n_failures} or engine misconfigured)",
                flush=True,
            )
            return 1

        # ------------------------------------------------------------------
        # Step 5 — inspect and format the primary alert
        # ------------------------------------------------------------------
        primary = alerts[0]
        level_name = primary.level.name if hasattr(primary.level, "name") else str(primary.level)
        print(f"[VERIFY] alert: {level_name} — {primary.source}: {primary.message}", flush=True)

        try:
            discord_fmt = engine.format_alert(primary)
        except Exception as exc:
            print(f"[VERIFY] FAIL — format_alert raised: {exc}", flush=True)
            return 1

        print(f"[VERIFY] Discord format: {discord_fmt}", flush=True)

        # ------------------------------------------------------------------
        # Step 6 — validate expectations
        # ------------------------------------------------------------------
        # For >= 5 failures the engine should produce an URGENT alert
        if n_failures >= 5 and primary.level != EscalationLevel.URGENT:
            print(
                f"[VERIFY] FAIL — expected URGENT alert for {n_failures} failures, "
                f"got {level_name}",
                flush=True,
            )
            return 1

        # For >= 3 failures (but < 5) a NUDGE is acceptable
        if 3 <= n_failures < 5 and primary.level not in (
            EscalationLevel.NUDGE,
            EscalationLevel.URGENT,
        ):
            print(
                f"[VERIFY] FAIL — expected NUDGE or URGENT for {n_failures} failures, "
                f"got {level_name}",
                flush=True,
            )
            return 1

        print("[VERIFY] PASS", flush=True)
        return 0


if __name__ == "__main__":
    sys.exit(main())

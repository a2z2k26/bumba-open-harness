"""Capture a per-board browser storage state for the BrowserUseSpecialist (D5.7).

Operator workflow (one evening, 8-13 boards):

    cd /opt/bumba-harness/agent
    python -m scripts.capture_browser_profile remotive --url https://remotive.com

The script:
  1. Launches a real Chromium window via Playwright (headed, not headless)
  2. Navigates to the board's login URL
  3. Waits for the operator to complete login (manual)
  4. Operator hits ENTER in this terminal once logged in
  5. Saves storage_state to /opt/bumba-harness/data/browser-profiles/<board>.json

The captured file is what the BrowserUseSpecialist reads via
``BrowserInput.storage_state_path`` (D5.5 type, D5.7 wiring).

Re-capture every ~30 days or whenever the loader's staleness warning fires.

This script is operator-evening choreography — kept deliberately minimal.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_PROFILES_ROOT = Path("/opt/bumba-harness/data/browser-profiles")
DEFAULT_TIMEOUT_MS = 5 * 60 * 1000  # 5 minutes


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.capture_browser_profile",
        description="Capture a logged-in browser session for a job board (D5.7).",
    )
    parser.add_argument(
        "board",
        help="Board name slug (e.g. remotive, himalayas, ycombinator). "
        "Matches the key used by the chief in BrowserInput threading.",
    )
    parser.add_argument(
        "--url",
        required=True,
        help="The board's login URL — what to navigate to first. "
        "Operator logs in from there.",
    )
    parser.add_argument(
        "--profiles-root",
        type=Path,
        default=DEFAULT_PROFILES_ROOT,
        help=f"Directory to write <board>.json into (default: {DEFAULT_PROFILES_ROOT})",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=DEFAULT_TIMEOUT_MS,
        help=f"Login timeout in ms (default: {DEFAULT_TIMEOUT_MS})",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns 0 on success, non-zero on failure."""
    args = _build_arg_parser().parse_args(argv)

    args.profiles_root.mkdir(parents=True, exist_ok=True)
    output_path = args.profiles_root / f"{args.board}.json"

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "ERROR: playwright not installed in this venv. Install with:\n"
            "  cd agent && uv sync --dev && playwright install chromium",
            file=sys.stderr,
        )
        return 2

    print(f"Capturing browser profile for board={args.board!r}")
    print(f"  → output: {output_path}")
    print(f"  → login URL: {args.url}")
    print()
    print("A Chromium window will open. Log in to the board, then press ENTER here.")
    print()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        try:
            page.goto(args.url, timeout=args.timeout_ms)
        except Exception as exc:
            print(f"ERROR: failed to navigate to {args.url}: {exc}", file=sys.stderr)
            browser.close()
            return 3

        try:
            input("[ENTER once logged in to capture storage_state, Ctrl-C to abort] ")
        except KeyboardInterrupt:
            print("\nAborted by operator.", file=sys.stderr)
            browser.close()
            return 130

        context.storage_state(path=str(output_path))
        browser.close()

    print(f"\nSaved: {output_path}")
    print("Verify size > 0 and re-run capture_browser_profile if anything looks off.")
    print(
        "BrowserUseSpecialist will pick this up automatically via "
        "BrowserInput.storage_state_path (chief threads it via "
        "_browser_profiles.profile_path_for_board)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

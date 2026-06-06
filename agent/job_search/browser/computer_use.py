"""Computer-use BrowserDriver — Anthropic computer-use API over CloakBrowser.

Sprint 5j.04 (#2129) — authorizes Claude computer-use as a BrowserDriver
implementation. Computer-use is PIXEL/SCREEN-based AI grounding: the
model sees screenshots, decides actions (click coordinates, type text,
key chords), and the driver translates those decisions into Playwright
operations against a CloakBrowser-backed Chromium session.

## Stack (per ADR #2156 + sandbox ADR #2158 + credential vault ADR #2159)

  Claude computer-use API (AI grounding via vision)
      │
      ▼
  This driver (translates model decisions → Playwright ops)
      │
      ▼
  Playwright protocol
      │
      ▼
  CloakBrowser stealth Chromium (per-session ephemeral profile)
      │
      ▼
  bumba-browser macOS user sandbox (UID isolation + pfctl egress allowlist)

## Safety rules (load-bearing — non-negotiable)

1. **`computer_use_enabled` config flag default OFF.** Activation is an
   operator decision per the sandbox runbook
   (`docs/operator/computer-use-sandbox-setup.md`). The runbook covers:
   create bumba-browser user, mode-0640 `.secrets` with group access,
   pfctl allowlist seeding, computer-use API capability check.

2. **`browser-use-specialist` is the ONLY caller.** This driver MUST run
   inside the bumba-browser UID per #2158. Caller-side checks (verify
   `os.geteuid()` matches bumba-browser's UID) raise SandboxBoundaryError
   if the invocation is from the wrong UID.

3. **Per-session ephemeral profile.** Each driver instance gets a fresh
   profile directory under the configured profile root
   (`BUMBA_BROWSER_PROFILE_ROOT`, default
   `/opt/bumba-harness/browser-profiles/<session-id>/`).
   On `close()` the directory is removed.

4. **Audit log on every action.** Per the sandbox ADR's per-session JSONL
   contract: every model decision + Playwright op + screenshot path
   captures to `data/job_search/sandbox-audit/<session-id>.jsonl`. Sensitive
   field values redact to type-class only (`password`, `email`, etc.).

## When this driver is invoked

ATS workflows (#2157, #2161-#2164) request `get_browser_driver(use_stealth=False)`
ONLY when (a) `computer_use_enabled=True` in config AND (b) caller is
bumba-browser UID. Otherwise the workflow falls back to CloakBrowser
direct (stealth without AI grounding) or Playwright fallback (#2165).
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class SandboxBoundaryError(Exception):
    """Raised when ComputerUseDriver is invoked outside the bumba-browser
    UID sandbox. Load-bearing safety check per #2158 sandbox ADR.
    """


# bumba-browser UID resolved at runtime — None means "skip the check"
# (used by tests). Production callers via the sandbox set the env var.
_BUMBA_BROWSER_UID_ENV = "BUMBA_BROWSER_UID"

# Audit log root — per sandbox ADR contract
_AUDIT_LOG_ROOT = Path("/opt/bumba-harness/data/job_search/sandbox-audit")

# Per-session profile root. Override when using a dedicated sandbox account.
_PROFILE_ROOT = Path(
    os.environ.get("BUMBA_BROWSER_PROFILE_ROOT", "/opt/bumba-harness/browser-profiles")
)


def _check_sandbox_boundary() -> None:
    """Verify the current process is running as bumba-browser UID.

    Skipped when ``BUMBA_BROWSER_UID`` env var is unset (test mode).
    """
    expected_uid_str = os.environ.get(_BUMBA_BROWSER_UID_ENV)
    if not expected_uid_str:
        # Test mode — boundary check skipped. Production callers MUST
        # set BUMBA_BROWSER_UID=<bumba-browser uid> in the launchd plist
        # OR equivalent invocation wrapper.
        return
    try:
        expected_uid = int(expected_uid_str)
    except ValueError as exc:
        raise SandboxBoundaryError(
            f"Invalid {_BUMBA_BROWSER_UID_ENV}={expected_uid_str!r} — must be int"
        ) from exc
    current_uid = os.geteuid()
    if current_uid != expected_uid:
        raise SandboxBoundaryError(
            f"ComputerUseDriver invoked outside sandbox: "
            f"current uid={current_uid}, expected={expected_uid} (bumba-browser). "
            f"Per #2158 sandbox ADR this driver runs ONLY as bumba-browser."
        )


def _redact_field_value(field_name: str, value: str) -> str:
    """Map a field name + value to a type-class for audit logging.

    Sensitive fields are redacted to their CLASS only, never the value.
    Non-sensitive field values pass through truncated to 60 chars.
    """
    sensitive_classes = {
        "password": "password",
        "mfa_secret": "mfa_secret",
        "ssn": "ssn",
        "otp": "otp",
        "token": "token",
    }
    name_lower = (field_name or "").lower()
    for needle, class_name in sensitive_classes.items():
        if needle in name_lower:
            return f"<{class_name}-redacted>"
    # Email: redact local-part, keep domain (useful for audit without leak)
    if "email" in name_lower and "@" in value:
        local, _, domain = value.partition("@")
        return f"<email>@{domain}"
    return value[:60] + ("..." if len(value) > 60 else "")


class ComputerUseDriver:
    """Computer-use BrowserDriver — Anthropic computer-use API on top of
    CloakBrowser stealth Chromium.

    Per the stack architecture: model sees screenshots, decides actions,
    driver translates to Playwright ops. The model-loop (taking a screenshot,
    sending to Claude API, parsing the action response) is the load-bearing
    piece this driver wraps.

    Per the sandbox ADR (#2158), this driver:
      - Verifies UID matches bumba-browser at construction time
      - Uses a fresh per-session profile directory (ephemeral)
      - Writes a per-action audit log line to the session JSONL
      - Refuses to read credentials from anywhere except the vault
        (#2159 / #2160) — credentials arrive as in-process state, never
        pulled from the filesystem at use-time
    """

    def __init__(
        self,
        *,
        session_id: str | None = None,
        humanize: bool = True,
        audit_log_root: Path | None = None,
        profile_root: Path | None = None,
        skip_boundary_check: bool = False,
    ) -> None:
        if not skip_boundary_check:
            _check_sandbox_boundary()
        self.session_id = session_id or f"cu-{uuid.uuid4().hex[:12]}"
        self.humanize = humanize
        self._audit_log_root = audit_log_root or _AUDIT_LOG_ROOT
        self._profile_root = profile_root or _PROFILE_ROOT
        self._browser: Any | None = None
        self._page: Any | None = None
        self._profile_dir: Path | None = None
        self._audit_path: Path | None = None
        self._audit_log_session_start()

    def _audit_log_path(self) -> Path:
        if self._audit_path is None:
            self._audit_log_root.mkdir(parents=True, exist_ok=True)
            self._audit_path = self._audit_log_root / f"{self.session_id}.jsonl"
        return self._audit_path

    def _audit_append(self, event: str, **fields: Any) -> None:
        """Append a single audit event line."""
        try:
            row = {"ts": time.time(), "event": event, **fields}
            with self._audit_log_path().open("a") as f:
                f.write(json.dumps(row) + "\n")
        except Exception:  # noqa: BLE001
            log.warning("Audit log append failed for session %s", self.session_id, exc_info=True)

    def _audit_log_session_start(self) -> None:
        self._audit_append(
            "session_start",
            session_id=self.session_id,
            humanize=self.humanize,
        )

    async def _ensure_page(self) -> Any:
        """Lazy-construct the CloakBrowser session + profile dir."""
        if self._page is None:
            try:
                import cloakbrowser
            except ImportError as exc:
                raise RuntimeError(
                    "cloakbrowser is required for ComputerUseDriver. "
                    "Install on the mini via `uv pip install -e \".[job-search-browser]\"`."
                ) from exc
            # Per-session ephemeral profile
            self._profile_root.mkdir(parents=True, exist_ok=True)
            self._profile_dir = self._profile_root / self.session_id
            self._profile_dir.mkdir(parents=True, exist_ok=True)
            self._browser = cloakbrowser.launch(
                humanize=self.humanize,
                user_data_dir=str(self._profile_dir),
            )
            self._page = self._browser.new_page()
        return self._page

    async def _model_decide(self, screenshot_path: str, intent: str) -> dict[str, Any]:
        """Send screenshot + intent to Claude computer-use API; return action.

        Returns a dict like {"action": "click", "coords": [x, y]} or
        {"action": "type", "text": "..."}. Real Claude API wiring is
        installed by the operator runbook; this seam is the contract.
        """
        # Implementation seam — real API call lives here in production.
        # The runbook (`docs/operator/computer-use-sandbox-setup.md`)
        # walks the operator through the API auth + tool config.
        raise NotImplementedError(
            "_model_decide requires computer-use API authorization. "
            "See docs/operator/computer-use-sandbox-setup.md."
        )

    # ------------------------------------------------------------------
    # BrowserDriver protocol
    # ------------------------------------------------------------------

    async def navigate(self, url: str) -> None:
        page = await self._ensure_page()
        self._audit_append("url_visited", url=url)
        page.goto(url)

    async def fill_field(self, selector: str, value: str) -> None:
        page = await self._ensure_page()
        self._audit_append(
            "form_field_filled",
            field_selector=selector,
            redacted_value=_redact_field_value(selector, value),
        )
        page.fill(selector, value)

    async def upload_file(self, selector: str, path: str) -> None:
        page = await self._ensure_page()
        self._audit_append(
            "file_uploaded",
            field_selector=selector,
            file_path=path,
        )
        page.set_input_files(selector, path)

    async def click(self, selector: str) -> None:
        page = await self._ensure_page()
        self._audit_append("submit_clicked", selector=selector)
        page.click(selector)

    async def screenshot(self, path: str) -> None:
        page = await self._ensure_page()
        page.screenshot(path=path)
        self._audit_append("screenshot_captured", path=path)

    async def get_page_text(self) -> str:
        page = await self._ensure_page()
        return page.content() or ""

    async def close(self) -> None:
        """Idempotent teardown — close browser + remove ephemeral profile."""
        if self._page is not None:
            try:
                self._page.close()
            except Exception:  # noqa: BLE001
                pass
            self._page = None
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:  # noqa: BLE001
                pass
            self._browser = None
        # Remove ephemeral profile dir
        if self._profile_dir is not None and self._profile_dir.exists():
            import shutil
            try:
                shutil.rmtree(self._profile_dir)
            except Exception:  # noqa: BLE001
                log.warning("Failed to remove profile dir %s", self._profile_dir, exc_info=True)
        self._audit_append("session_end", exit_code=0)

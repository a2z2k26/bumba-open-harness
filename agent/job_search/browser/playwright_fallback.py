"""Playwright fallback driver for job-search BrowserDriver protocol.

Sprint 5j.11 (#2165) — when the primary substrate (CloakBrowser stealth
Chromium per ADR #2156, or computer-use per #2129) can't handle a
specific ATS form, fall back to Playwright MCP. Playwright already
exists globally; this module wires it as the explicit fallback path.

## Trigger contract

The fallback engages when the primary driver raises ``UnhandledFormError``.
ATS workflow chiefs detect the trigger condition (captcha wall encountered,
form contract violated, submit-button never resolved, etc.) and explicitly
raise the error, signalling "primary substrate is wedged on this form;
escalate to Playwright". The fallback driver instantiates a fresh Playwright
context + retries the operation.

## Boundaries

Playwright fallback is the LAST RESORT in the substrate stack:
  Claude computer-use → CloakBrowser → Playwright MCP

If Playwright fallback also fails, the workflow HALTs and surfaces an
operator blocker. NEVER record "submitted" on a fallback-after-fallback
silent skip.

## Lazy import

Like CloakBrowserDriver, this module lazy-imports `playwright` so the
rest of the bridge runs on machines without Playwright installed.
"""
from __future__ import annotations

import logging
from typing import Any

from .driver import BrowserDriver

log = logging.getLogger(__name__)


class UnhandledFormError(Exception):
    """Raised by a primary BrowserDriver when it cannot complete an
    operation on the current page. The workflow chief catches this and
    invokes ``PlaywrightFallbackDriver`` to retry.

    Carries optional context (current URL, last operation attempted)
    so the fallback driver can resume cleanly.
    """

    def __init__(
        self,
        message: str,
        *,
        url: str | None = None,
        last_op: str | None = None,
    ) -> None:
        super().__init__(message)
        self.url = url
        self.last_op = last_op


class PlaywrightFallbackDriver:
    """Concrete BrowserDriver using vanilla Playwright (no stealth).

    Intended as a LAST RESORT fallback when the primary substrate
    can't handle a specific form. Caller (workflow chief) instantiates
    this only after catching ``UnhandledFormError`` from the primary.

    Behavioral notes:
    - No stealth — exposes the standard Playwright automation signature
    - Account-ban risk is HIGHER than CloakBrowser; use sparingly
    - Operator should be notified when fallback engages (audit signal)
    """

    def __init__(self, headless: bool = True) -> None:
        self._headless = headless
        self._browser: Any | None = None
        self._context: Any | None = None
        self._page: Any | None = None

    async def _ensure_page(self) -> Any:
        if self._page is None:
            try:
                from playwright.async_api import async_playwright
            except ImportError as exc:
                raise RuntimeError(
                    "playwright is required for PlaywrightFallbackDriver. "
                    "Install with: pip install playwright && playwright install chromium"
                ) from exc
            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(headless=self._headless)
            self._context = await self._browser.new_context()
            self._page = await self._context.new_page()
            log.warning(
                "PlaywrightFallbackDriver engaged — NO STEALTH. Account-ban risk elevated."
            )
        return self._page

    async def navigate(self, url: str) -> None:
        page = await self._ensure_page()
        await page.goto(url, wait_until="domcontentloaded")

    async def fill_field(self, selector: str, value: str) -> None:
        page = await self._ensure_page()
        await page.fill(selector, value)

    async def upload_file(self, selector: str, path: str) -> None:
        page = await self._ensure_page()
        await page.set_input_files(selector, path)

    async def click(self, selector: str) -> None:
        page = await self._ensure_page()
        await page.click(selector)

    async def screenshot(self, path: str) -> None:
        page = await self._ensure_page()
        await page.screenshot(path=path, full_page=True)

    async def get_page_text(self) -> str:
        page = await self._ensure_page()
        body = await page.query_selector("body")
        if body is None:
            return ""
        return await body.inner_text()

    async def close(self) -> None:
        # Idempotent — safe to call multiple times
        if self._page is not None:
            try:
                await self._page.close()
            except Exception:  # noqa: BLE001
                pass
            self._page = None
        if self._context is not None:
            try:
                await self._context.close()
            except Exception:  # noqa: BLE001
                pass
            self._context = None
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:  # noqa: BLE001
                pass
            self._browser = None
        if hasattr(self, "_pw") and self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:  # noqa: BLE001
                pass
            self._pw = None


async def with_fallback(
    primary: BrowserDriver,
    op_name: str,
    *args,
    **kwargs,
) -> Any:
    """Execute ``op_name`` on the primary driver; on UnhandledFormError,
    fall back to a fresh PlaywrightFallbackDriver.

    Usage:
        result = await with_fallback(primary, "fill_field", "#email", "x@y.com")

    Returns whatever the operation returns (typically None for the
    BrowserDriver mutation methods).

    Logs WARNING on fallback engagement so operator can correlate via audit.
    """
    op = getattr(primary, op_name, None)
    if op is None:
        raise AttributeError(f"BrowserDriver missing operation: {op_name}")
    try:
        return await op(*args, **kwargs)
    except UnhandledFormError as exc:
        log.warning(
            "Primary driver raised UnhandledFormError on %s (url=%s, last_op=%s); engaging Playwright fallback",
            op_name,
            exc.url,
            exc.last_op,
        )
        fallback = PlaywrightFallbackDriver()
        try:
            if exc.url:
                await fallback.navigate(exc.url)
            fallback_op = getattr(fallback, op_name)
            return await fallback_op(*args, **kwargs)
        finally:
            await fallback.close()

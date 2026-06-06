"""Browser substrate driver protocol + concrete implementations.

Implements the install + invocation pathway selected in the 2026-05-17 ADR
(`docs/architecture/adr/2026-05-17-job-search-browser-substrate.md`,
issue #2156, Sprint 5j.00). Sprint 5j.03 / issue #2128.

Stack (job-search):

    Claude computer-use API  (AI grounding)        -- ComputerUseDriver
            │
            ▼
    Playwright protocol      (driver layer)
            │
            ▼
    CloakBrowser stealth     (Chromium engine)     -- CloakBrowserDriver

CloakBrowser is the default for job-search workflows because the
account-ban risk surface (operator's real Greenhouse / Lever / Workday /
Ashby / BambooHR candidate accounts) is high. The ADR scopes stealth to
job-search only; non-job-search browser work uses default Chromium.

`ComputerUseDriver` is intentionally a NotImplementedError stub in this
sprint — real computer-use API authorization lands in #2129 (Sprint
5j.04). Default-deny until that authorization sprint ships.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class BrowserDriver(Protocol):
    """Common browser automation surface for job-search workflows.

    All methods are async to accommodate Playwright-style drivers and
    HTTP-based computer-use APIs uniformly. Concrete implementations
    must satisfy every method on this protocol; the runtime_checkable
    decorator allows `isinstance(driver, BrowserDriver)` checks at the
    boundary (Sprint 5j.06 Greenhouse workflow will use this).
    """

    async def navigate(self, url: str) -> None:
        """Load `url` in the active browser context."""
        ...

    async def fill_field(self, selector: str, value: str) -> None:
        """Type `value` into the form field matched by `selector`."""
        ...

    async def upload_file(self, selector: str, path: str) -> None:
        """Attach the file at `path` to the file-input matched by `selector`."""
        ...

    async def click(self, selector: str) -> None:
        """Click the element matched by `selector`."""
        ...

    async def screenshot(self, path: str) -> None:
        """Write a PNG screenshot of the current viewport to `path`."""
        ...

    async def get_page_text(self) -> str:
        """Return the visible text content of the current page."""
        ...

    async def close(self) -> None:
        """Tear down the browser context. Must be idempotent."""
        ...


class CloakBrowserDriver:
    """Concrete BrowserDriver using CloakBrowser stealth Chromium.

    Drop-in Playwright-compatible engine; behavioral mimicry enabled via
    `humanize=True` per CloakBrowser README + ADR recommendation. Use
    this driver for job-search ATS submissions where session bans on
    the operator's real candidate accounts are the failure mode.

    Lazy-imports `cloakbrowser` so the rest of the bridge can run on
    machines that haven't installed the ~200MB stealth Chromium binary.
    """

    def __init__(self, *, humanize: bool = True, headless: bool = True) -> None:
        self._humanize = humanize
        self._headless = headless
        self._browser: Any | None = None
        self._page: Any | None = None

    async def _ensure_page(self) -> Any:
        if self._page is not None:
            return self._page
        # Lazy import: cloakbrowser ships a 200MB binary; only download
        # the stealth engine when an actual session is requested.
        import cloakbrowser  # type: ignore[import-not-found]

        self._browser = await cloakbrowser.launch(
            humanize=self._humanize,
            headless=self._headless,
        )
        self._page = await self._browser.new_page()
        return self._page

    async def navigate(self, url: str) -> None:
        page = await self._ensure_page()
        await page.goto(url)

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
        await page.screenshot(path=path)

    async def get_page_text(self) -> str:
        page = await self._ensure_page()
        text = await page.inner_text("body")
        return str(text)

    async def close(self) -> None:
        # Idempotent: tearing down twice is a no-op.
        if self._browser is None:
            return
        try:
            await self._browser.close()
        finally:
            self._browser = None
            self._page = None


class ComputerUseDriver:
    """Stub BrowserDriver for the Claude computer-use API path.

    Per ADR 2026-05-17 the Claude computer-use API is the primary
    AI-grounding substrate, but authorization on the Mac mini sandbox
    is deferred to Sprint 5j.04 (#2129). Until that sprint ships,
    instantiating this driver is a default-deny error — operator must
    explicitly request the stealth (CloakBrowser) path or wait for
    #2129 to land.

    Real implementation will:
      1. Open an Anthropic API client with computer-use tools enabled
      2. Drive a CloakBrowser-backed Chromium via the Playwright
         protocol (engine reused from CloakBrowserDriver)
      3. Pipe screenshots back into the model loop for AI grounding
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError(
            "ComputerUseDriver requires computer-use API authorization on "
            "the Mac mini sandbox (Sprint 5j.04, issue #2129). Until that "
            "lands, use get_browser_driver(use_stealth=True) for the "
            "CloakBrowser stealth path."
        )

    async def navigate(self, url: str) -> None:  # pragma: no cover - stub
        raise NotImplementedError

    async def fill_field(self, selector: str, value: str) -> None:  # pragma: no cover - stub
        raise NotImplementedError

    async def upload_file(self, selector: str, path: str) -> None:  # pragma: no cover - stub
        raise NotImplementedError

    async def click(self, selector: str) -> None:  # pragma: no cover - stub
        raise NotImplementedError

    async def screenshot(self, path: str) -> None:  # pragma: no cover - stub
        raise NotImplementedError

    async def get_page_text(self) -> str:  # pragma: no cover - stub
        raise NotImplementedError

    async def close(self) -> None:  # pragma: no cover - stub
        raise NotImplementedError


def get_browser_driver(use_stealth: bool = True) -> BrowserDriver:
    """Return the appropriate BrowserDriver for the requested mode.

    Args:
        use_stealth: When True (default for job-search), returns the
            CloakBrowser stealth-Chromium driver. When False, returns
            the Claude computer-use driver — which is a NotImplemented
            stub until Sprint 5j.04 (#2129) ships authorization.

    Returns:
        A BrowserDriver-conforming instance.

    Raises:
        NotImplementedError: When use_stealth=False before #2129 ships.
    """
    if use_stealth:
        return CloakBrowserDriver()
    # Default-deny: computer-use path requires authorization (#2129).
    return ComputerUseDriver()

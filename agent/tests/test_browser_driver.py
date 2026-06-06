"""Tests for the job-search browser substrate (Sprint 5j.03, issue #2128).

Covers the install + invocation pathway selected in ADR 2026-05-17
(`docs/architecture/adr/2026-05-17-job-search-browser-substrate.md`):

- `BrowserDriver` protocol surface (all 7 methods present)
- `CloakBrowserDriver` instantiation + method dispatch with mocked
  cloakbrowser.launch
- `ComputerUseDriver` raises NotImplementedError until #2129 ships
- `get_browser_driver(use_stealth=True)` returns CloakBrowserDriver
- `get_browser_driver(use_stealth=False)` raises NotImplementedError
  (computer-use path not yet authorized)

No actual browser launches happen in these tests; cloakbrowser is
mocked at the import boundary.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

from job_search.browser import (
    BrowserDriver,
    CloakBrowserDriver,
    ComputerUseDriver,
    get_browser_driver,
)


# ---------------------------------------------------------------------------
# Protocol surface
# ---------------------------------------------------------------------------


class TestBrowserDriverProtocol:
    """The BrowserDriver protocol must expose all 7 methods named in
    the issue #2128 code sketch."""

    def test_protocol_has_navigate(self):
        assert hasattr(BrowserDriver, "navigate")

    def test_protocol_has_fill_field(self):
        assert hasattr(BrowserDriver, "fill_field")

    def test_protocol_has_upload_file(self):
        assert hasattr(BrowserDriver, "upload_file")

    def test_protocol_has_click(self):
        assert hasattr(BrowserDriver, "click")

    def test_protocol_has_screenshot(self):
        assert hasattr(BrowserDriver, "screenshot")

    def test_protocol_has_get_page_text(self):
        assert hasattr(BrowserDriver, "get_page_text")

    def test_protocol_has_close(self):
        assert hasattr(BrowserDriver, "close")

    def test_cloakbrowser_satisfies_protocol(self):
        """runtime_checkable Protocol should accept CloakBrowserDriver."""
        driver = CloakBrowserDriver()
        assert isinstance(driver, BrowserDriver)


# ---------------------------------------------------------------------------
# CloakBrowserDriver — mocked cloakbrowser.launch
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_cloakbrowser(monkeypatch):
    """Inject a fake `cloakbrowser` module so tests never touch the
    real ~200MB stealth Chromium binary."""
    fake_page = MagicMock()
    fake_page.goto = AsyncMock()
    fake_page.fill = AsyncMock()
    fake_page.set_input_files = AsyncMock()
    fake_page.click = AsyncMock()
    fake_page.screenshot = AsyncMock()
    fake_page.inner_text = AsyncMock(return_value="hello world")

    fake_browser = MagicMock()
    fake_browser.new_page = AsyncMock(return_value=fake_page)
    fake_browser.close = AsyncMock()

    fake_module = types.ModuleType("cloakbrowser")
    fake_module.launch = AsyncMock(return_value=fake_browser)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "cloakbrowser", fake_module)

    return {"module": fake_module, "browser": fake_browser, "page": fake_page}


class TestCloakBrowserDriver:
    def test_instantiation_does_not_launch_browser(self, mock_cloakbrowser):
        """Construction is cheap — no binary download until first action."""
        driver = CloakBrowserDriver()
        assert driver._browser is None
        assert driver._page is None
        mock_cloakbrowser["module"].launch.assert_not_called()

    def test_humanize_default_true(self):
        """Per ADR 2026-05-17, humanize=True is the default for stealth."""
        driver = CloakBrowserDriver()
        assert driver._humanize is True

    def test_humanize_can_be_disabled(self):
        driver = CloakBrowserDriver(humanize=False)
        assert driver._humanize is False

    @pytest.mark.asyncio
    async def test_navigate_calls_goto(self, mock_cloakbrowser):
        driver = CloakBrowserDriver()
        await driver.navigate("https://example.com")
        mock_cloakbrowser["module"].launch.assert_awaited_once_with(
            humanize=True, headless=True
        )
        mock_cloakbrowser["page"].goto.assert_awaited_once_with("https://example.com")

    @pytest.mark.asyncio
    async def test_fill_field_calls_fill(self, mock_cloakbrowser):
        driver = CloakBrowserDriver()
        await driver.fill_field("#email", "test@example.com")
        mock_cloakbrowser["page"].fill.assert_awaited_once_with(
            "#email", "test@example.com"
        )

    @pytest.mark.asyncio
    async def test_upload_file_calls_set_input_files(self, mock_cloakbrowser):
        driver = CloakBrowserDriver()
        await driver.upload_file("#resume", "/tmp/resume.pdf")
        mock_cloakbrowser["page"].set_input_files.assert_awaited_once_with(
            "#resume", "/tmp/resume.pdf"
        )

    @pytest.mark.asyncio
    async def test_click_calls_click(self, mock_cloakbrowser):
        driver = CloakBrowserDriver()
        await driver.click("button[type=submit]")
        mock_cloakbrowser["page"].click.assert_awaited_once_with(
            "button[type=submit]"
        )

    @pytest.mark.asyncio
    async def test_screenshot_calls_screenshot(self, mock_cloakbrowser):
        driver = CloakBrowserDriver()
        await driver.screenshot("/tmp/page.png")
        mock_cloakbrowser["page"].screenshot.assert_awaited_once_with(
            path="/tmp/page.png"
        )

    @pytest.mark.asyncio
    async def test_get_page_text_returns_body_text(self, mock_cloakbrowser):
        driver = CloakBrowserDriver()
        text = await driver.get_page_text()
        assert text == "hello world"
        mock_cloakbrowser["page"].inner_text.assert_awaited_once_with("body")

    @pytest.mark.asyncio
    async def test_close_tears_down_browser(self, mock_cloakbrowser):
        driver = CloakBrowserDriver()
        await driver.navigate("https://example.com")
        await driver.close()
        mock_cloakbrowser["browser"].close.assert_awaited_once()
        assert driver._browser is None
        assert driver._page is None

    @pytest.mark.asyncio
    async def test_close_is_idempotent(self, mock_cloakbrowser):
        """Double-close must not raise."""
        driver = CloakBrowserDriver()
        await driver.close()  # never launched — should no-op
        await driver.navigate("https://example.com")
        await driver.close()
        await driver.close()  # second teardown — should no-op
        # Only one real close call despite three close() invocations
        assert mock_cloakbrowser["browser"].close.await_count == 1

    @pytest.mark.asyncio
    async def test_reuses_page_across_calls(self, mock_cloakbrowser):
        """Browser launch happens once even across multiple actions."""
        driver = CloakBrowserDriver()
        await driver.navigate("https://example.com")
        await driver.click("a")
        await driver.fill_field("#x", "y")
        assert mock_cloakbrowser["module"].launch.await_count == 1
        assert mock_cloakbrowser["browser"].new_page.await_count == 1


# ---------------------------------------------------------------------------
# ComputerUseDriver — stub until Sprint 5j.04 (#2129)
# ---------------------------------------------------------------------------


class TestComputerUseDriver:
    def test_instantiation_raises_not_implemented(self):
        """Default-deny: computer-use path requires #2129 authorization."""
        with pytest.raises(NotImplementedError, match="2129"):
            ComputerUseDriver()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class TestGetBrowserDriver:
    def test_default_is_stealth(self):
        """Default for job-search is the stealth path per ADR 2026-05-17."""
        driver = get_browser_driver()
        assert isinstance(driver, CloakBrowserDriver)

    def test_explicit_stealth_true_returns_cloak(self):
        driver = get_browser_driver(use_stealth=True)
        assert isinstance(driver, CloakBrowserDriver)

    def test_stealth_false_raises_until_2129(self):
        """Non-stealth path is the computer-use driver, which is stubbed
        until Sprint 5j.04 (#2129) authorizes computer-use on the mini."""
        with pytest.raises(NotImplementedError, match="2129"):
            get_browser_driver(use_stealth=False)

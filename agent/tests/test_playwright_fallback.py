"""Tests for the Playwright fallback driver + with_fallback dispatcher (#2165)."""
from __future__ import annotations

import pytest

from job_search.browser.driver import BrowserDriver
from job_search.browser.playwright_fallback import (
    PlaywrightFallbackDriver,
    UnhandledFormError,
    with_fallback,
)


class TestUnhandledFormError:
    def test_basic_construction(self):
        err = UnhandledFormError("captcha detected")
        assert str(err) == "captcha detected"
        assert err.url is None
        assert err.last_op is None

    def test_with_context(self):
        err = UnhandledFormError(
            "captcha wall",
            url="https://boards.greenhouse.io/x/jobs/123",
            last_op="submit_application",
        )
        assert err.url == "https://boards.greenhouse.io/x/jobs/123"
        assert err.last_op == "submit_application"

    def test_is_exception_subclass(self):
        assert issubclass(UnhandledFormError, Exception)


class TestPlaywrightFallbackDriverSatisfiesProtocol:
    def test_implements_browser_driver_protocol(self):
        """PlaywrightFallbackDriver must satisfy the BrowserDriver protocol
        so workflow chiefs can dispatch to it interchangeably with the
        primary substrate."""
        driver = PlaywrightFallbackDriver()
        assert isinstance(driver, BrowserDriver)

    def test_close_is_idempotent_without_session(self):
        """close() must be safe to call multiple times without a session
        having been opened. Async test via asyncio.run."""
        import asyncio
        driver = PlaywrightFallbackDriver()
        asyncio.run(driver.close())
        asyncio.run(driver.close())  # second call must not raise


class TestWithFallbackHelper:
    @pytest.mark.asyncio
    async def test_primary_succeeds_no_fallback(self):
        """When primary succeeds, fallback never engages."""
        class FakePrimary:
            def __init__(self):
                self.fill_called = False
            async def fill_field(self, selector, value):
                self.fill_called = True

        primary = FakePrimary()
        await with_fallback(primary, "fill_field", "#email", "x@y.com")
        assert primary.fill_called is True

    @pytest.mark.asyncio
    async def test_unknown_op_raises_attribute_error(self):
        """with_fallback rejects ops the primary doesn't expose."""
        class EmptyDriver:
            pass

        with pytest.raises(AttributeError, match="missing operation"):
            await with_fallback(EmptyDriver(), "doesnt_exist")

    @pytest.mark.asyncio
    async def test_primary_unhandled_form_error_triggers_fallback(self, monkeypatch):
        """When primary raises UnhandledFormError, fallback driver is
        instantiated + the op retried. Mock the fallback so we don't
        actually launch Playwright."""
        from job_search.browser import playwright_fallback as pf_mod

        class FakePrimary:
            async def click(self, selector):
                raise UnhandledFormError(
                    "captcha detected",
                    url="https://example.com/listing",
                    last_op="click",
                )

        class MockFallback:
            def __init__(self):
                self.navigate_called = False
                self.click_called = False
                self.close_called = False
            async def navigate(self, url):
                self.navigate_called = True
            async def click(self, selector):
                self.click_called = True
            async def close(self):
                self.close_called = True

        # Replace PlaywrightFallbackDriver with our mock for this test
        mock_instances = []
        def _factory():
            inst = MockFallback()
            mock_instances.append(inst)
            return inst

        monkeypatch.setattr(pf_mod, "PlaywrightFallbackDriver", _factory)

        primary = FakePrimary()
        await with_fallback(primary, "click", "#submit")

        # Verify fallback was used + cleaned up
        assert len(mock_instances) == 1
        fb = mock_instances[0]
        assert fb.navigate_called is True  # restored to err.url
        assert fb.click_called is True
        assert fb.close_called is True  # cleanup ran

    @pytest.mark.asyncio
    async def test_non_unhandled_form_errors_propagate(self):
        """Errors other than UnhandledFormError propagate without fallback."""
        class FakePrimary:
            async def fill_field(self, selector, value):
                raise RuntimeError("unrelated error")

        with pytest.raises(RuntimeError, match="unrelated error"):
            await with_fallback(FakePrimary(), "fill_field", "#x", "y")

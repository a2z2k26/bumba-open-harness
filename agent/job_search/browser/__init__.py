"""Browser substrate package for job-search ATS workflows.

Implements the install + invocation pathway selected by ADR
2026-05-17 (`docs/architecture/adr/2026-05-17-job-search-browser-substrate.md`,
Sprint 5j.00 / issue #2156). Sprint 5j.03 / issue #2128.

Public surface:

- `BrowserDriver`        — Protocol all driver implementations satisfy
- `CloakBrowserDriver`   — stealth Chromium concrete (default for job-search)
- `ComputerUseDriver`    — Claude computer-use stub (real impl in #2129)
- `get_browser_driver`   — factory; returns the right driver per mode
"""
from __future__ import annotations

from job_search.browser.driver import (
    BrowserDriver,
    CloakBrowserDriver,
    ComputerUseDriver,
    get_browser_driver,
)

__all__ = [
    "BrowserDriver",
    "CloakBrowserDriver",
    "ComputerUseDriver",
    "get_browser_driver",
]

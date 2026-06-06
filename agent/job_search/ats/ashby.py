"""Ashby ATS form handler — prompt template + field patterns."""
from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class AshbyApplication:
    job_url: str
    company: str
    posting_id: str


ASHBY_PROMPT = """## ATS: Ashby (jobs.ashbyhq.com)

Ashby is a React SPA — elements render dynamically. Always snapshot after any navigation or click.

**Steps:**
1. Open the URL — you'll see the job description
2. Look for "Apply" button and click it, OR navigate to <url>/application
3. Snapshot to get the form — Ashby loads form fields via React, so wait for render

**Field mapping:**
- First Name, Last Name (TWO separate fields)
- Email, Phone
- Resume: file input, click then `playwright-cli upload <path>`
- LinkedIn URL
- Cover Letter textarea (if present)
- Custom questions: dropdowns, radio buttons, text inputs — fill with reasonable defaults

**Ashby quirks:**
- React-based: element refs change after every navigation. ALWAYS take a fresh snapshot before interacting.
- Dropdowns may be custom React components, not native <select>. Try `playwright-cli click <ref>` to open, snapshot to see options, then click the option.
- Radio buttons: use `playwright-cli check <ref>` on the correct option
- Some forms have multi-step sections. Fill each section, click Next/Continue.
- Submit button is "Submit" or "Submit Application"
- After submit, Ashby shows a "Thanks for applying" or similar confirmation"""

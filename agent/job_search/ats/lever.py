"""Lever ATS form handler — prompt template + field patterns."""
from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class LeverApplication:
    job_url: str
    company: str
    posting_id: str


LEVER_PROMPT = """## ATS: Lever (jobs.lever.co)

Lever has the job description on the main page. You must navigate to the /apply page.

**Steps:**
1. If URL doesn't end in /apply, navigate: `playwright-cli goto <url>/apply`
2. Snapshot to see the form

**Field mapping:**
- Full Name (SINGLE field — use the full name, do NOT split)
- Email, Phone
- Resume: click "Upload resume" or the file input, then `playwright-cli upload <path>`
- LinkedIn URL, Portfolio/Website URL (separate fields under "Links")
- "Additional information" textarea → paste the full cover letter here

**Lever quirks:**
- The form is on a separate /apply page — you MUST navigate there first
- Name is a single field (not first/last split)
- Cover letter goes in "Additional information", not a dedicated cover letter field
- Submit button is "Submit application"
- Confirmation page says 'Application submitted' or 'Thanks for applying'"""

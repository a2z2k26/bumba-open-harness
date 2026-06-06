"""Greenhouse ATS form handler — prompt template + field patterns."""
from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class GreenhouseApplication:
    job_url: str
    company: str
    job_id: str


GREENHOUSE_PROMPT = """## ATS: Greenhouse (boards.greenhouse.io)

Greenhouse shows the application form directly on the job page — no separate "Apply" page.

**Field mapping:**
- First Name + Last Name (TWO separate fields — split the name)
- Email, Phone
- Resume: click the file input or "Attach" button, then `playwright-cli upload <path>`
- Cover Letter: large textarea, paste the full cover letter
- LinkedIn URL field (if present)
- Website/Portfolio URL field (if present)
- "How did you hear about us?" → select "Job Board" or "Other" or type "Job Board"

**Greenhouse quirks:**
- Resume upload: look for an input[type=file] or an "Attach" / "Choose File" button. Click it, then immediately run `playwright-cli upload <path>`. If upload doesn't work on first try, snapshot to find the file input ref and try again.
- Some Greenhouse forms have custom questions (dropdowns, text). Fill with reasonable defaults.
- Submit button is usually "Submit Application" at the bottom.
- After submit, page shows "Application submitted" or redirects to thank-you page."""

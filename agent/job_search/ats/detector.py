"""ATS detection from job URL patterns."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ATSResult:
    ats: str  # "greenhouse", "lever", "ashby", "workday", "linkedin", "rippling", "jobvite", "icims", "other", "unknown"
    job_id: str | None
    company: str | None


ATS_PATTERNS = [
    # Greenhouse — boards.greenhouse.io/<company>/jobs/<job_id>
    (re.compile(r'boards\.greenhouse\.io/([^/]+)/jobs/(\d+)', re.I), 'greenhouse'),
    (re.compile(r'boards\.greenhouse\.io/([^/]+)', re.I), 'greenhouse'),
    # Lever — jobs.lever.co/<company>/<uuid>
    (re.compile(r'jobs\.lever\.co/([^/]+)/([a-f0-9-]{36})', re.I), 'lever'),
    (re.compile(r'jobs\.lever\.co/([^/]+)', re.I), 'lever'),
    # Ashby — jobs.ashbyhq.com/<company>/<uuid>
    (re.compile(r'jobs\.ashbyhq\.com/([^/]+)/([a-f0-9-]{36})', re.I), 'ashby'),
    (re.compile(r'jobs\.ashbyhq\.com/([^/]+)', re.I), 'ashby'),
    # Workday — <company>.wd<N>.myworkdayjobs.com
    (re.compile(r'([^.]+)\.wd\d+\.myworkdayjobs\.com', re.I), 'workday'),
    # LinkedIn
    (re.compile(r'linkedin\.com/jobs', re.I), 'linkedin'),
    # Rippling
    (re.compile(r'ats\.rippling\.com', re.I), 'rippling'),
    # Jobvite
    (re.compile(r'jobs\.jobvite\.com', re.I), 'jobvite'),
    # iCIMS
    (re.compile(r'careers\.icims\.com', re.I), 'icims'),
]


def detect_ats(url: str) -> ATSResult:
    """Detect ATS from job URL. Returns ATSResult with ats name, job_id, company."""
    for pattern, ats_name in ATS_PATTERNS:
        m = pattern.search(url)
        if m:
            groups = m.groups()
            company = groups[0] if groups else None
            job_id = groups[1] if len(groups) > 1 else None
            return ATSResult(ats=ats_name, job_id=job_id, company=company)
    return ATSResult(ats='unknown', job_id=None, company=None)

"""Tests for ATS URL detection."""
from job_search.ats.detector import detect_ats

def test_greenhouse_with_job_id():
    r = detect_ats("https://boards.greenhouse.io/stripe/jobs/12345")
    assert r.ats == "greenhouse"
    assert r.company == "stripe"
    assert r.job_id == "12345"

def test_greenhouse_no_job_id():
    r = detect_ats("https://boards.greenhouse.io/airbnb")
    assert r.ats == "greenhouse"
    assert r.company == "airbnb"

def test_lever_with_job_id():
    r = detect_ats("https://jobs.lever.co/acme/550e8400-e29b-41d4-a716-446655440000")
    assert r.ats == "lever"
    assert r.company == "acme"
    assert r.job_id == "550e8400-e29b-41d4-a716-446655440000"

def test_lever_no_job_id():
    r = detect_ats("https://jobs.lever.co/notion")
    assert r.ats == "lever"
    assert r.company == "notion"

def test_ashby_with_job_id():
    r = detect_ats("https://jobs.ashbyhq.com/linear/550e8400-e29b-41d4-a716-446655440000")
    assert r.ats == "ashby"
    assert r.company == "linear"

def test_ashby_no_job_id():
    r = detect_ats("https://jobs.ashbyhq.com/figma")
    assert r.ats == "ashby"
    assert r.company == "figma"

def test_workday():
    r = detect_ats("https://amazon.wd5.myworkdayjobs.com/en-US/amazon_jobs/job/1234")
    assert r.ats == "workday"

def test_linkedin():
    r = detect_ats("https://www.linkedin.com/jobs/view/12345")
    assert r.ats == "linkedin"

def test_unknown():
    r = detect_ats("https://example.com/careers/senior-engineer")
    assert r.ats == "unknown"
    assert r.job_id is None
    assert r.company is None

def test_rippling():
    r = detect_ats("https://ats.rippling.com/companyxyz/jobs/123")
    assert r.ats == "rippling"

def test_icims():
    r = detect_ats("https://careers.icims.com/jobs/1234/job")
    assert r.ats == "icims"

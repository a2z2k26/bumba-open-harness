"""Tests for deduplication logic."""
from job_search.deduplication import Deduplicator, _fingerprint, _normalize_url

def test_same_url_is_duplicate():
    d = Deduplicator()
    d.mark_seen("https://example.com/jobs/1", "Engineer", "Acme")
    assert d.is_duplicate("https://example.com/jobs/1", "Engineer", "Acme")

def test_different_url_not_duplicate():
    d = Deduplicator()
    d.mark_seen("https://example.com/jobs/1", "Engineer", "Acme")
    assert not d.is_duplicate("https://example.com/jobs/2", "Engineer", "Acme")

def test_url_normalization_strips_query():
    assert _normalize_url("https://example.com/jobs/1?ref=board") == "https://example.com/jobs/1"

def test_url_normalization_strips_trailing_slash():
    assert _normalize_url("https://example.com/jobs/1/") == "https://example.com/jobs/1"

def test_fingerprint_deterministic():
    fp1 = _fingerprint("https://example.com/jobs/1", "Engineer", "Acme")
    fp2 = _fingerprint("https://example.com/jobs/1", "Engineer", "Acme")
    assert fp1 == fp2

def test_fingerprint_different_for_different_urls():
    fp1 = _fingerprint("https://example.com/jobs/1")
    fp2 = _fingerprint("https://example.com/jobs/2")
    assert fp1 != fp2

def test_mark_seen_returns_fingerprint():
    d = Deduplicator()
    fp = d.mark_seen("https://example.com/jobs/1")
    assert isinstance(fp, str) and len(fp) == 16

def test_url_with_query_deduplicates_correctly():
    d = Deduplicator()
    d.mark_seen("https://example.com/jobs/1")
    assert d.is_duplicate("https://example.com/jobs/1?utm_source=wwr")

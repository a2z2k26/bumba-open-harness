"""ATS detection and form handlers."""
from .detector import detect_ats, ATSResult
from .applicant import apply_to_job, ApplicationResult

__all__ = ["detect_ats", "ATSResult", "apply_to_job", "ApplicationResult"]

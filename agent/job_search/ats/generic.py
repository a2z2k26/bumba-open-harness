"""Generic application form handler — prompt template for any ATS/career page."""
from __future__ import annotations

GENERIC_PROMPT = """## ATS: Unknown / Generic Career Page

This could be any job board or company career page. Adapt to what you see.

**Strategy:**
1. Open the URL and snapshot
2. Look for "Apply", "Apply Now", "Submit Application" button or link
3. If the apply button links to an external ATS (Greenhouse, Lever, Ashby, Workday), follow it
4. If it opens a form on the same page, fill it
5. If there's no apply button, look for "Visit Website" or "Apply on Company Site" and follow that link

**Common patterns:**
- Some boards (Dribbble, RemoteOK, WWR) link out to the company's own career page
- Follow redirects — you may go through 2-3 pages before reaching the actual form
- After each navigation, snapshot to get fresh element refs

**Form filling:**
- Name: try Full Name first. If First/Last separate fields, split accordingly.
- Resume: find the file input (input[type=file], "Attach", "Upload", "Choose File"). Click it, then `playwright-cli upload <path>`.
- Cover letter: look for a textarea labeled "Cover Letter", "Additional Information", "Why do you want to work here?", etc.
- "How did you hear about us?" → "Job Board" or "Other"
- Checkboxes for legal/consent → check them

**Multi-step forms:**
- Fill visible fields, click Next/Continue, snapshot, fill next section, repeat
- Keep going until you find Submit

**After submission:**
- Snapshot to capture confirmation
- Look for "thank you", "received", "submitted" text"""

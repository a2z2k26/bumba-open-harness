# Job Search Pipeline

This package contains the job-search scaffold for the Bumba harness: board
scrapers, criteria loading, deduplication, scoring, ATS detection, approval
staging, and execution helpers.

It is intentionally generic for public release. No resume, personal profile,
portfolio, LinkedIn URL, target-company list, approval database ID, browser
session, or credential is checked in.

## Public Default

The workflow fails closed until an adopter supplies local configuration:

- `candidate.json` copied from `candidate.json.example`
- `criteria.json` copied from `criteria.json.example`
- `notion_api_token` in the local `.secrets` file
- `notion_job_db_id` in `.secrets` or `BUMBA_NOTION_JOB_DB_ID`
- Backend/model credentials required by the chosen harness variant

Filled `candidate.json` and `criteria.json` are ignored by Git because they may
contain personal data.

## Workflow Shape

1. Research jobs from configured boards.
2. Filter and score against adopter-owned criteria.
3. Generate application or outreach drafts with the configured model backend.
4. Stage results in the adopter-owned approval database.
5. Execute only items the adopter has approved.

Automatic application submission and outreach are high-impact workflows. Verify
provider terms, rate limits, form behavior, and approval gates before enabling
them.

## Board Coverage

- Public API boards: Remotive, Himalayas, Jobicy, RemoteOK, WorkingNomads,
  WeWorkRemotely, and Y Combinator Work at a Startup.
- ATS direct APIs: Ashby, Greenhouse, and Lever when seeded with adopter-owned
  company config.
- HTML boards: Dribbble, Behance, Coroflot, BuiltIn, Nodesk, and Dice.
- Stubbed boards: boards requiring authentication, subscriptions, or matching
  products return no results until implemented by the adopter.

## Tests

```bash
cd agent
.venv/bin/python -m pytest job_search/tests/ -q
```

## Security Notes

- Do not commit browser profiles or cookies.
- Do not commit filled candidate data.
- Do not hardcode Notion database IDs.
- Keep outbound email/application execution behind explicit approval.

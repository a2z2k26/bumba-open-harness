# Job Search Scaffold

The job-search package is a public scaffold. It contains board scrapers,
deduplication, scoring, ATS detection, approval staging, and tests, but it does
not contain an adopter's resume, profile, target-company list, LinkedIn URL,
portfolio URL, or private approval database.

## Required Local Files

Create untracked local copies before running live job-search automation:

```bash
cp agent/job_search/candidate.json.example agent/job_search/candidate.json
cp agent/job_search/criteria.json.example agent/job_search/criteria.json
```

Fill in your own candidate data and search criteria. Do not commit the filled
files if they contain personal information.

## Required Secrets

At minimum:

```text
notion_api_token=
notion_job_db_id=
```

The pipeline also needs whichever model/backend credentials your deployment
uses for generation work.

`notion_job_db_id` can also be supplied as `BUMBA_NOTION_JOB_DB_ID`. If neither
value is present, the pipeline fails closed.

## Approval Model

The intended workflow is prepare first, approve second, execute last:

1. Research and stage opportunities.
2. Review staged records in the adopter-owned approval database.
3. Execute only approved applications or outreach.

Do not enable automatic submission or outreach until you have verified form
behavior, rate limits, provider terms, and your local approval gates.

## Tests

```bash
cd agent
.venv/bin/python -m pytest job_search/tests/ -q
```

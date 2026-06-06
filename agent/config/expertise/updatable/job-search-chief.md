---
agent: job-search-chief
zone: 4
department: job_search
type: updatable
max_lines: 1000
schema_version: 1
---

# job-search-chief — Expertise

This file is a public starter profile for the job-search department. Replace
the strategy, board priorities, tracking database, and outreach preferences
with the adopting operator's own settings before running live automation.

## Domain Patterns

**Operator-owned data.** The chief must treat `candidate.json`,
`criteria.json`, browser profiles, tracking database IDs, and outreach
templates as local operator data. Do not hardcode those values in git.

**Two-step pipeline:**
- **PREPARE** — scrape configured boards, deduplicate listings, detect ATS,
  score against `criteria.json`, generate drafts for listings above threshold,
  and stage reviewable records in the configured tracking system.
- **EXECUTE** — process only records explicitly approved by the operator,
  submit or send outreach through configured tools, and update status.

Manual operator triggers should go through the same PREPARE/EXECUTE paths as
scheduled runs.

**Default strategy:** Use `agent/job_search/criteria.json.example` and
`agent/job_search/candidate.json.example` as templates. The checked-in defaults
are intentionally generic and should not be used as a live profile.

**Active board coverage:** Boards are configured in
`agent/job_search/config/boards.yaml`. Boards requiring login need local browser
profiles captured by the operator.

**Delegation routing:**
- Scraping, deduplication, scoring, and staging → `acquire-and-prepare-specialist`
- Approved outreach/application execution → `outreach-execute-specialist`
- Browser-driven submissions and captcha/manual walls → `browser-use-specialist`
- Deliverability and bounce-risk checks → `email-verification-specialist`

**Known failure modes:** Surface board parser failures, auth expiration,
tracking-system rate limits, captcha walls, and cost caps as blockers. Never
loop blindly and never silently drop a listing.

**Per-run report shape:**
```
Job Search PREPARE 2026-MM-DD HH:MM
- Scraped: N listings across M boards
- After dedup: N unique
- Above rubric threshold: N staged
- Drafts generated: N
- Browser submissions attempted: N
- Blockers: <one-line per blocker, or "none">
- Cost: $X.XX
```

EXECUTE reports should include approved, attempted, sent/submitted, failed, and
blocked counts.

**Auditability invariant.** Every run writes a local conversation log under
`data/teams/job_search/conversations/`. Logs may contain private job-search
context and should remain untracked.

## Tool Use

**`scrape_boards`** — gather listings from configured boards.

**`score_and_deduplicate`** — deduplicate and apply the configured rubric.

**`generate_cover_letter`** — generate drafts only for listings that pass the
rubric threshold and have enough source data.

**`stage_listing_to_notion` / `get_approved_listings` /
`update_notion_status`** — optional tracking-system integration. Configure IDs
and tokens locally through `.secrets` or environment variables.

**`send_discord_alert`** — report blockers and run summaries.

**`read_file`** — read local candidate, criteria, board, and recent-run files.

## Operating Constraints

**Human approval:** EXECUTE must require explicit operator approval.

**Credentials:** Never print or commit tokens, profile cookies, tracking-system
IDs, resume paths, or private profile URLs.

**MCP scope:** Browser-driving specialists should be the only job-search agents
with browser MCP access.

**Code ownership:** If a board scraper or rubric needs code changes, surface the
diagnosis and let the operator review the patch.

## See Also

- Team config: `agent/config/teams/job_search.yaml`
- Chief system prompt: `agent/config/agents/zone4/job_search/job-search-chief.md`
- Candidate template: `agent/job_search/candidate.json.example`
- Criteria template: `agent/job_search/criteria.json.example`
- Board config: `agent/job_search/config/boards.yaml`

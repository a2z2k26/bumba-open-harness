---
name: notion-github-bridge
description: Bidirectional sync between GitHub issues and Notion task databases using MCP tools. Handles status mapping, conflict resolution, and sync state tracking across any repository.
---

# GitHub ↔ Notion Bridge

Bidirectional sync between GitHub issues and Notion tasks using MCP tools. No standalone scripts — all operations go through `Notion:notion-*` and `github:*` MCP tools.

## Quick Start

- **GitHub → Notion:** Fetch issues via `github:list_issues`, create/update Notion tasks via `Notion:notion-create-pages`
- **Notion → GitHub:** Query tasks DB via `Notion:notion-search`, detect status changes, update GitHub via `github:update_issue`
- **Full sync:** Run both directions, reconcile conflicts by timestamp

## Config Loading

All database IDs, property names, and status mappings live in the workspace config. Load it at the start of every sync operation:

```
Read file: /opt/bumba-harness/agent-flat/agent/config/notion-bridge/workspace-config.json
```

Key fields:
- `databases.tasks` — Tasks Master database ID
- `databases.projects` — Projects Master database ID
- `statusMapping.githubToNotion` — GitHub state → Notion status
- `statusMapping.notionToGithub` — Notion status → GitHub state + labels
- `propertyMapping` — Notion property names for GitHub fields
- `syncDefaults.syncStateFile` — Path to sync state JSON

## MCP Tools Reference

### Notion Tools (prefix: `Notion:notion-`)

| Tool | Purpose |
|------|---------|
| `Notion:notion-search` | Search pages/databases by title |
| `Notion:notion-fetch` | Get database contents with filters |
| `Notion:notion-create-pages` | Create new pages in a database |
| `Notion:notion-update-page` | Update page properties |
| `Notion:notion-get-self` | Test connectivity / get workspace info |

### GitHub Tools (prefix: `github:`)

| Tool | Purpose |
|------|---------|
| `github:list_issues` | List issues for a repo (with filters) |
| `github:get_issue` | Get single issue details |
| `github:create_issue` | Create a new issue |
| `github:update_issue` | Update issue state/labels/body |
| `github:search_repositories` | Verify repo exists |

## GitHub → Notion Flow

### 1. Fetch Issues

```
Call github:list_issues with:
  owner: <owner>
  repo: <repo>
  state: "all"        # or "open" for incremental
  per_page: 100
```

### 2. Load Sync State

Read the sync state file (path from `syncDefaults.syncStateFile`). If it doesn't exist, treat all issues as new.

```json
{
  "repos": {
    "owner/repo": {
      "lastSync": "2026-03-04T00:00:00Z",
      "notionProjectId": "page-id",
      "issues": {
        "42": {
          "notionPageId": "notion-page-id",
          "lastGithubUpdate": "2026-03-03T12:00:00Z",
          "lastNotionUpdate": "2026-03-03T12:00:00Z",
          "statusChecksum": "md5-of-status"
        }
      }
    }
  }
}
```

### 3. For Each Issue

**If issue NOT in sync state** (new issue):

```
Call Notion:notion-create-pages with:
  databaseId: <databases.tasks from config>
  properties:
    "Task Name": { "title": [{ "text": { "content": "<issue.title>" } }] }
    "Status": { "select": { "name": "<mapped-status>" } }
    "GitHub Issue URL": { "url": "<issue.html_url>" }
    "GitHub Issue Number": { "number": <issue.number> }
    "GitHub Repo": { "url": "https://github.com/<owner>/<repo>" }
```

**If issue IN sync state** (existing — check for updates):

Compare `issue.updated_at` against `lastGithubUpdate`. If newer:

```
Call Notion:notion-update-page with:
  pageId: <notionPageId from sync state>
  properties:
    "Status": { "select": { "name": "<mapped-status>" } }
    "Task Name": { "title": [{ "text": { "content": "<issue.title>" } }] }
```

### 4. Map Status (GitHub → Notion)

Use `statusMapping.githubToNotion` from config:

| GitHub State | GitHub Labels | Notion Status |
|---|---|---|
| `open` | (none relevant) | `backlog` |
| `open` | `ready` | `ready` |
| `open` | `in-progress` | `in_progress` |
| `open` | `blocked` | `blocked` |
| `closed` | (any) | `completed` |

Priority: Labels override base state. Check labels first, fall back to state-only mapping.

### 5. Update Sync State

After processing all issues, write updated sync state with new timestamps and page IDs.

## Notion → GitHub Flow

### 1. Query Tasks Database

```
Call Notion:notion-fetch with:
  resource: "database/<databases.tasks>"
  # Filter for tasks that have a GitHub Repo URL matching the target repo
```

### 2. Detect Changes

For each task with a GitHub Issue Number:
- Compare current Notion status against `statusChecksum` in sync state
- If changed: this task needs to push updates to GitHub

### 3. Update GitHub Issues

Use `statusMapping.notionToGithub` from config:

```
Call github:update_issue with:
  owner: <owner>
  repo: <repo>
  issue_number: <from Notion property>
  state: <mapped state>

# Then manage labels:
Call github:add_labels_to_issue with addLabels
Call github:remove_label with removeLabels (for each)
```

### 4. Create New Issues (Notion → GitHub)

For tasks with a GitHub Repo URL but NO GitHub Issue Number:

```
Call github:create_issue with:
  owner: <owner>
  repo: <repo>
  title: <Task Name>
  body: <page content summary>
```

Then update the Notion page with the new issue URL and number.

## Property Mapping

| GitHub Field | Notion Property | Type |
|---|---|---|
| `issue.title` | Task Name | title |
| `issue.body` | Page content (body) | content blocks |
| `issue.state` + labels | Status | select |
| `issue.html_url` | GitHub Issue URL | url |
| `issue.number` | GitHub Issue Number | number |
| `https://github.com/owner/repo` | GitHub Repo | url |

## Conflict Resolution

When both sides changed since last sync:

1. Compare `issue.updated_at` (GitHub) vs Notion page `last_edited_time`
2. **Most recent wins** — apply that side's changes to the other
3. Log the conflict for user review:
   ```
   CONFLICT: Issue #42 "Fix login bug"
     GitHub updated: 2026-03-04T10:00:00Z (status: closed)
     Notion updated: 2026-03-04T10:05:00Z (status: in_progress)
     Resolution: Notion wins (more recent) → reopening GitHub issue
   ```
4. If timestamps are within 60 seconds, flag as **unresolved** and skip — let user decide

## Error Handling

### Rate Limits
- Notion: 3 requests/second. If 429 received, wait and retry (the MCP server handles this).
- GitHub: 5000 requests/hour. Check `X-RateLimit-Remaining` header.

### API Failures
- Log failed operations with issue number and error
- Continue processing remaining issues
- Report failures in sync summary
- Failed items remain in sync state with their old timestamps (will retry next sync)

### Partial Sync Recovery
- Sync state is written after EACH successful issue operation
- If sync is interrupted, next run picks up where it left off
- The `lastSync` timestamp only updates after all issues are processed

## Dry Run Mode

When `--dry-run` is specified:
- Perform all reads (GitHub issues, Notion tasks, sync state)
- Calculate all changes that WOULD be made
- Display summary without executing any writes
- Do NOT update sync state

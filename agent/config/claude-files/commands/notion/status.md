---
name: notion/status
description: Check sync status between GitHub and Notion
arguments:
  - name: repo
    description: "GitHub repo in owner/repo format (optional — shows all repos if omitted)"
    required: false
---

# /notion/status — Sync Status

Displays the current sync state between GitHub issues and Notion tasks.

## Usage

```
/notion/status [owner/repo]
```

## Implementation

### Step 1: Load Sync State

Read the workspace config:
```
Read file: /opt/bumba-harness/agent-flat/agent/config/notion-bridge/workspace-config.json
```

Read the sync state file (path from `syncDefaults.syncStateFile`):
```
Read file: /opt/bumba-harness/data/notion-sync-state.json
```

If the sync state file doesn't exist, display:
```
No sync state found. No repositories have been synced yet.

To get started:
  1. Run /notion/project create <owner/repo> to set up a project
  2. Run /notion/sync <owner/repo> to sync issues
```

### Step 2: Display Status

**If no repo specified** — show all repos:

```
Notion-GitHub Sync Status
=========================

Repository              Last Sync            Issues   Status
----                    ----                  ----     ----
your-org/bumba-open-harness       2026-03-04 10:00     15       Fresh
your-org/other-repo      2026-03-03 08:00     42       Stale
owner/old-repo          2026-02-28 12:00     7        Very Stale

Freshness:
  Fresh     = synced within last 1 hour
  Stale     = synced 1-24 hours ago
  Very Stale = synced >24 hours ago
```

**If specific repo specified** — show detailed view:

### Step 3: Detailed Repo Status

For the specified repo, also query live data to detect drift:

1. Call `github:list_issues` with `owner`, `repo`, `state: "all"`, `per_page: 1` — get total count
2. Compare against sync state issue count
3. Call `Notion:notion-fetch` on tasks DB filtered by GitHub Repo — get Notion task count

```
Sync Status: <owner/repo>
============================

Last Sync: <timestamp>
Freshness: <Fresh|Stale|Very Stale>

GitHub Issues: <live-count>
Notion Tasks:  <live-count>
Synced:        <sync-state-count>

Drift Detection:
  Unsynced GitHub issues: <count>  (new issues since last sync)
  Unsynced Notion tasks:  <count>  (tasks without GitHub issue number)

Notion Project: <project-page-url or "Not linked">

To sync now: /notion/sync <owner/repo>
```

### Step 4: Staleness Calculation

Calculate staleness from `lastSync` timestamp:
- **Fresh**: `now - lastSync < 1 hour`
- **Stale**: `1 hour <= now - lastSync < 24 hours`
- **Very Stale**: `now - lastSync >= 24 hours`
- **Never**: `lastSync` is null

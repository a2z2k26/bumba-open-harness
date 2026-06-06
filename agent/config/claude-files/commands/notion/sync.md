---
name: notion/sync
description: Bidirectional sync between GitHub issues and Notion tasks
arguments:
  - name: repo
    description: "GitHub repo in owner/repo format (e.g., your-org/bumba-open-harness)"
    required: true
  - name: direction
    description: "Sync direction: github-to-notion, notion-to-github, or both (default: both)"
    required: false
  - name: dry-run
    description: "Show what would change without making modifications"
    required: false
---

# /notion/sync — Bidirectional GitHub ↔ Notion Sync

Syncs GitHub issues with Notion tasks in the Tasks Master database.

## Usage

```
/notion/sync <owner/repo> [--direction github-to-notion|notion-to-github|both] [--dry-run]
```

## Implementation

When the user runs this command, execute the following steps:

### Step 1: Parse Arguments

Extract from `$ARGUMENTS`:
- `repo`: Required. Format `owner/repo` (e.g., `your-org/bumba-open-harness`)
- `--direction`: Optional. One of `github-to-notion`, `notion-to-github`, `both`. Default: `both`
- `--dry-run`: Optional flag. If present, only show what would change.

If repo is a full URL (`https://github.com/owner/repo`), extract `owner/repo` from it.

### Step 2: Load Configuration

Read the workspace config:
```
Read file: /opt/bumba-harness/agent-flat/agent/config/notion-bridge/workspace-config.json
```

Read the sync state (create empty structure if file doesn't exist):
```
Read file: /opt/bumba-harness/data/notion-sync-state.json
```

If sync state doesn't exist, initialize:
```json
{ "repos": {} }
```

### Step 3: Verify Connectivity

Call `Notion:notion-get-self` to verify Notion MCP is working.
Call `github:list_issues` with `owner`, `repo`, `per_page: 1` to verify GitHub access.

If either fails, report the error and stop.

### Step 4: GitHub → Notion Phase

Skip if `--direction notion-to-github`.

1. Call `github:list_issues` with `owner`, `repo`, `state: "all"`, `per_page: 100`
2. For each issue:
   - Check sync state for existing mapping
   - **New issue**: Call `Notion:notion-create-pages` with mapped properties (see skill for property format)
   - **Existing issue with changes**: Call `Notion:notion-update-page` with updated properties
   - **Existing issue unchanged**: Skip
3. Map status using `statusMapping.githubToNotion` from config
4. Track results: created, updated, unchanged, errors

### Step 5: Notion → GitHub Phase

Skip if `--direction github-to-notion`.

1. Call `Notion:notion-fetch` with the tasks database ID, filtering for tasks where GitHub Repo matches `https://github.com/<owner>/<repo>`
2. For each task with a GitHub Issue Number:
   - Compare current Notion status against sync state checksum
   - If changed: Call `github:update_issue` with mapped state and labels (per `statusMapping.notionToGithub`)
3. For tasks with GitHub Repo but NO Issue Number (Notion-originated):
   - Call `github:create_issue` with task title and content
   - Update Notion page with the new issue URL and number
4. Track results

### Step 6: Handle Conflicts

If both sides changed since last sync (direction = `both`):
- Compare GitHub `updated_at` vs Notion `last_edited_time`
- Most recent wins; log the conflict
- If within 60 seconds, skip and flag for user review

### Step 7: Update Sync State

If NOT `--dry-run`:
- Write updated sync state to the sync state file
- Include new page IDs, timestamps, and checksums

### Step 8: Display Summary

```
Sync Complete: <owner/repo>
Direction: <direction>
Duration: <elapsed>

GitHub -> Notion:
  Created: <n>
  Updated: <n>
  Unchanged: <n>
  Errors: <n>

Notion -> GitHub:
  Created: <n>
  Updated: <n>
  Unchanged: <n>
  Errors: <n>

Conflicts: <n> (resolved: <n>, skipped: <n>)

Last sync: <ISO timestamp>
```

If `--dry-run`, prefix with `[DRY RUN]` and show what WOULD change.

If errors occurred, list each failed item with its error message.

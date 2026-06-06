# /sync-github Command Guide

**Complete guide to syncing GitHub issues to Notion tasks**

---

## Overview

The `/sync-github` command performs **one-way synchronization** from GitHub → Notion:
- Fetches open issues from a GitHub repository
- Creates corresponding tasks in your Notion Tasks Master database
- Filters tasks by GitHub Repo (project-specific views)
- Detects duplicates to prevent re-creation
- Handles rate limits with automatic retry logic

---

## Prerequisites

### 1. GitHub CLI Installed

The command uses GitHub CLI (`gh`) to fetch issues.

**Check if installed:**
```bash
gh --version
```

**Install if needed:**
```bash
# macOS
brew install gh

# Linux
# See: https://cli.github.com/

# Windows
# See: https://cli.github.com/
```

**Authenticate:**
```bash
gh auth login
```

### 2. Project Created with /project-init

The GitHub repository must already have a Notion project dashboard created via `/project-init`.

**If you haven't created a project yet:**
```bash
/project-init my-project
# Enable "Notion Dashboard" feature
# Enter GitHub repo: https://github.com/owner/repo
```

### 3. bumba-memory MCP Running

The command uses bumba-memory MCP for project lookup. Ensure the MCP server is running.

---

## Basic Usage

### Syntax

```bash
/sync-github <github-repo-url>
```

### Example

```bash
/sync-github https://github.com/facebook/react
```

---

## How It Works

### Step 1: Validate GitHub URL

Checks that the URL matches the pattern: `https://github.com/owner/repo`

### Step 2: Find Project

Uses three-tier lookup strategy:

1. **Direct MCP lookup**: `bumba-notion:project:owner-repo`
2. **Index lookup**: Query `bumba-notion:projects:index` for GitHub repo mapping
3. **Local fallback**: Search `~/.claude/plugins/bumba-notion/state/`

### Step 3: Fetch GitHub Issues

Uses `gh issue list` to fetch up to 100 open issues:
- Filters by state: `open`
- Excludes pull requests
- Includes: number, title, URL, labels, dates

### Step 4: Check for Duplicates

Queries Notion Tasks database for each issue:
- Matches by "GitHub Issue" URL property
- Skips issues that already have tasks

### Step 5: Create Tasks

For each new issue:
- Maps GitHub state → Notion status (open → backlog)
- Creates task with all properties
- Links to GitHub issue via URL
- Filters by GitHub Repo for project views

**Retry Logic:**
- Max 3 retry attempts
- Exponential backoff: 1s, 2s, 4s
- Handles rate limits (429) and server errors (5xx)

### Step 6: Update Sync State

Stores sync results in:
- **bumba-memory MCP**: `bumba-notion:sync:{project-slug}`
- **Local backup**: `~/.claude/plugins/bumba-notion/state/sync-{slug}.json`

---

## Output Example

```
🔄 Starting GitHub → Notion sync...
📦 Repository: https://github.com/myorg/myrepo

✓ Validated GitHub URL: myorg/myrepo
✓ Found project: myrepo
  Dashboard: https://notion.so/abc123...
✓ Loaded configuration

📥 Fetching GitHub issues...
✓ Found 15 open issues

🔍 Checking for existing tasks...
  ✨ Creating #123: Add user authentication
     ✓ Created successfully
  ✨ Creating #124: Fix login bug
     ✓ Created successfully
  ⏭  Skipped #125: Update docs (already exists)
  ...

============================================================
✅ GitHub sync complete: https://github.com/myorg/myrepo

📊 Sync Summary:
  • Found: 15 open issues
  • Created: 12 new tasks
  • Skipped: 3 existing tasks
  • Errors: 0

🔗 View in Notion: https://notion.so/abc123...

✨ 12 tasks added to your Notion dashboard!
   Tasks are filtered by GitHub Repo: https://github.com/myorg/myrepo

Last sync: 2026-01-15T22:30:00.000Z
Duration: 28.5s
============================================================
```

---

## Common Scenarios

### First Sync (New Project)

When syncing a project for the first time:

```bash
/sync-github https://github.com/myorg/new-project

# Result:
# ✅ Found 20 open issues
# ✨ Created: 20 new tasks
# ⏭  Skipped: 0 existing tasks
```

All issues become tasks in Notion.

### Re-sync (Updates)

Running the command again on the same project:

```bash
/sync-github https://github.com/myorg/new-project

# Result:
# ✅ Found 22 open issues
# ✨ Created: 2 new tasks
# ⏭  Skipped: 20 existing tasks
```

Only new issues are created; existing tasks are skipped.

### Large Repository (100+ Issues)

The command fetches up to 100 issues per sync:

```bash
/sync-github https://github.com/facebook/react

# Result:
# ✅ Found 847 open issues (showing first 100)
# ✨ Created: 100 new tasks
```

To sync more issues, use GitHub issue filters (future enhancement).

---

## Error Handling

### Project Not Found

```
❌ No project found for GitHub repository: https://github.com/myorg/unknown

Searched in:
  • bumba-memory MCP (key: bumba-notion:project:*)
  • Local state files (~/.claude/plugins/bumba-notion/state/)

Did you run /project-init with this GitHub repo?

To create a project:
  /project-init
  # Enable "Notion Dashboard" feature
  # Enter GitHub repo: https://github.com/myorg/unknown
```

**Solution**: Run `/project-init` first to create the project.

### GitHub CLI Not Found

```
❌ GitHub CLI (gh) not found

Please install GitHub CLI:
  macOS: brew install gh
  Linux: https://cli.github.com/
  Windows: https://cli.github.com/

Then authenticate:
  gh auth login
```

**Solution**: Install and authenticate GitHub CLI.

### GitHub API Rate Limit

```
🔍 Checking for existing tasks...
  ✨ Creating #123: Add feature
     Retry attempt 1/3 in 1000ms... (rate limited)
     Retry attempt 2/3 in 2000ms... (rate limited)
     ✓ Created successfully
```

The command automatically retries with exponential backoff.

### Notion API Errors

```
⚠️ Errors encountered:
  • Issue #45: Rate limit exceeded
  • Issue #47: Network timeout

💡 Tip: Tasks with errors were not created. You can:
  1. Check error messages above
  2. Fix issues in GitHub
  3. Run /sync-github again to retry
```

Failed tasks can be retried by running the command again.

---

## Status Mapping

GitHub issue states are mapped to Notion statuses:

| GitHub State | Notion Status |
|--------------|---------------|
| open         | backlog       |
| in_progress  | in_progress   |
| closed       | completed     |

**Note**: GitHub only has `open` and `closed` states by default. The `in_progress` mapping is for future enhancements or custom workflows.

---

## Task Properties Created

Each GitHub issue creates a Notion task with:

| Property | Source |
|----------|--------|
| **Task ID** (title) | Issue title |
| **Status** | Mapped from GitHub state |
| **GitHub Repo** | Repository URL |
| **GitHub Issue** | Issue URL (for linking) |
| **Priority** | Default: 5 |
| **Started At** | Issue creation date |
| **Completed At** | Issue closed date (if closed) |

**Not Set Automatically**:
- Epic Name (manually assign in Notion)
- Sprint ID (manually assign in Notion)

---

## Performance

Expected sync times:

| Issue Count | Time |
|-------------|------|
| 20 issues   | ~30 seconds |
| 50 issues   | ~1 minute |
| 100 issues  | ~2-3 minutes |

**Breakdown**:
- Fetch issues: ~5 seconds
- Check duplicates: ~10 seconds per 20 issues
- Create tasks: ~15 seconds per 20 issues

---

## Sync State Tracking

### Local State

Sync history is stored locally:

```bash
cat ~/.claude/plugins/bumba-notion/state/sync-myproject.json
```

**Contains**:
- Last sync timestamp
- Sync history (last 10 syncs)
- Total syncs count
- Total issues created
- Error log (last 20 errors)

### bumba-memory State

Sync state is also stored in bumba-memory MCP:

**Key**: `bumba-notion:sync:myproject`

**Value**:
```json
{
  "projectSlug": "myproject",
  "projectName": "myproject",
  "githubRepo": "https://github.com/myorg/myproject",
  "lastSync": "2026-01-15T22:30:00.000Z",
  "stats": {
    "totalSyncs": 3,
    "totalIssuesCreated": 45,
    "lastError": null
  },
  "lastSyncResult": {
    "totalIssues": 20,
    "created": 5,
    "skipped": 15,
    "errors": 0
  }
}
```

---

## Viewing Tasks in Notion

After syncing, tasks appear in your project dashboard:

1. **Open Dashboard**: Click the dashboard URL from sync output
2. **View Tasks**: Tasks are automatically filtered by GitHub Repo
3. **Project Isolation**: Each project shows only its tasks

**Filter Applied**:
```
GitHub Repo = https://github.com/myorg/myproject
```

This ensures tasks from different projects don't mix.

---

## Best Practices

### 1. Sync Regularly

Run `/sync-github` periodically to keep tasks up-to-date:
- After standup meetings
- When new issues are created
- Before sprint planning

### 2. Clean Up Closed Issues

The command only syncs **open** issues. Closed issues are not synced.

To mark tasks as complete in Notion:
- Manually update task status to "completed"
- Or implement bidirectional sync (future enhancement)

### 3. Use GitHub Labels

GitHub labels are fetched but not currently mapped to Notion properties.

**Future Enhancement**: Map labels to:
- Priority (bug → high, enhancement → medium)
- Epic Name (label prefix: `epic:`)
- Sprint ID (label: `sprint-1`)

### 4. Batch Processing

For repositories with 500+ issues:
- Use GitHub filters to sync specific subsets
- Create multiple projects for different areas
- Example: `frontend-issues`, `backend-issues`

---

## Troubleshooting

### Issue: Sync is slow (>5 minutes)

**Causes**:
- Large number of issues (100+)
- Notion API rate limiting
- Network latency

**Solutions**:
- Reduce issue count with GitHub filters
- Run sync during off-peak hours
- Check internet connection

### Issue: Duplicate tasks created

**Causes**:
- GitHub Issue URL property not set correctly
- Notion database schema mismatch

**Solutions**:
- Verify "GitHub Issue" property exists in Tasks database
- Check property type is "URL" not "Text"
- Re-run Phase 0 setup if needed

### Issue: Tasks not showing in dashboard

**Causes**:
- GitHub Repo filter not applied
- Tasks created in wrong database

**Solutions**:
- Check dashboard linked database views
- Verify "GitHub Repo" property matches exactly
- Refresh Notion page (Cmd+R / Ctrl+R)

---

## Future Enhancements

### Bidirectional Sync (Week 2)

Sync changes from Notion → GitHub:
- Update issue status when task status changes
- Add comments to GitHub issues
- Close issues when tasks are completed

### Real-time Sync (Week 3)

Use GitHub webhooks for automatic sync:
- New issue → Create task immediately
- Issue closed → Mark task completed
- Issue updated → Update task properties

### Advanced Filtering

Sync specific issue subsets:
- By label: `label:bug`
- By milestone: `milestone:"v2.0"`
- By assignee: `assignee:@me`

### Label Mapping

Map GitHub labels to Notion properties:
- `bug` → Priority: High
- `enhancement` → Priority: Medium
- `epic:auth` → Epic Name: Authentication

---

## Related Documentation

- **Quick Start**: `QUICK-START.md` - Get started with bumba-notion plugin
- **Project Init Integration**: `PROJECT-INIT-INTEGRATION.md` - How /project-init works
- **bumba-memory Integration**: `BUMBA-MEMORY-INTEGRATION.md` - State management architecture
- **Troubleshooting**: `TROUBLESHOOTING.md` - Common issues and solutions

---

## Summary

The `/sync-github` command provides a simple, reliable way to sync GitHub issues to Notion tasks:

✅ **One command**: `/sync-github <repo-url>`
✅ **Automatic duplicate detection**
✅ **Retry logic for rate limits**
✅ **Project isolation** (filtered views)
✅ **Sync state tracking**
✅ **Works from any directory** (via bumba-memory)

For most projects, running this command once or twice per week keeps Notion tasks in sync with GitHub issues.

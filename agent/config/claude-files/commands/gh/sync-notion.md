---
name: sync-notion
description: Sync GitHub issues to Notion tasks (one-way GitHub → Notion)
arguments:
  - name: githubRepo
    description: GitHub repository URL (e.g., https://github.com/owner/repo)
    required: true
---

# /gh/sync-notion - GitHub to Notion Sync

Syncs open GitHub issues from a repository to Notion tasks in the Tasks Master database.

## Implementation Steps

When the user runs `/sync-github <github-repo-url>`, execute the following:

### Step 1: Parse and Validate GitHub URL

Extract owner and repo from the URL:
```javascript
const urlPattern = /^https:\/\/github\.com\/([^\/]+)\/([^\/]+)\/?$/;
const match = githubRepoUrl.match(urlPattern);

if (!match) {
  throw new Error('Invalid GitHub repository URL. Expected format: https://github.com/owner/repo');
}

const owner = match[1];
const repo = match[2];
const repoSlug = `${owner}-${repo}`;
```

### Step 2: Find Project in bumba-memory (Three-Tier Lookup)

**Option A: Direct Lookup**
```javascript
const contextKey = `bumba-notion:project:${repoSlug}`;
let projectMetadata = await mcp__bumba-memory__retrieve_context({ key: contextKey });
```

**Option B: Index Lookup (if Option A returns null)**
```javascript
const indexKey = 'bumba-notion:projects:index';
const index = await mcp__bumba-memory__retrieve_context({ key: indexKey });

if (index && index.byRepo && index.byRepo[githubRepoUrl]) {
  const projectSlug = index.byRepo[githubRepoUrl];
  const contextKey = `bumba-notion:project:${projectSlug}`;
  projectMetadata = await mcp__bumba-memory__retrieve_context({ key: contextKey });
}
```

**Option C: Local Fallback (if both MCP lookups fail)**

Use the sync-helper.js module:
```bash
node ~/.claude/plugins/bumba-notion/lib/sync-helper.js findProject <github-repo-url>
```

**If no project found:**
```
❌ No project found for GitHub repository: <github-repo-url>

Searched in:
  • bumba-memory MCP (key: bumba-notion:project:*)
  • Local state files (~/.claude/plugins/bumba-notion/state/)

Did you run /project-init with this GitHub repo?

To create a project:
  /project-init
  # Enable "Notion Dashboard" feature
  # Enter GitHub repo: <github-repo-url>
```

### Step 3: Display Pre-Sync Status

Before running the sync, show the current sync state if available:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 Current Sync Status

🎯 Project: <project-name>
📦 GitHub Repo: <github-repo-url>
🔗 Notion Dashboard: <dashboard-url>

📅 Last Sync: <timestamp or "Never">
📋 Tasks Synced: <count or "0">
⏱️  Sync Age: <human-readable time since last sync>
```

**Status Indicators:**
- ✅ "Fresh" if synced within last 1 hour
- ⚠️ "Stale" if synced 1-24 hours ago
- 🔴 "Very Stale" if synced >24 hours ago or never

### Step 4: Execute Sync Using Runner Script

Once project metadata is found, pass it to the sync runner:

```bash
node ~/.claude/plugins/bumba-notion/lib/sync-github-runner.js \
  "<github-repo-url>" \
  '<project-metadata-json>'
```

The runner script will:
1. Validate GitHub URL
2. Fetch GitHub issues using `gh` CLI
3. Check for duplicate tasks in Notion
4. Create new tasks with retry logic
5. Update local sync state
6. Output sync summary and MCP data

### Step 5: Store Sync State in bumba-memory

After the runner completes, parse its output to extract MCP data:

The runner outputs a JSON block like:
```json
{
  "mcpKey": "bumba-notion:sync:project-slug",
  "syncState": {
    "projectSlug": "...",
    "projectName": "...",
    "githubRepo": "...",
    "lastSync": "...",
    "stats": {...},
    "lastSyncResult": {...}
  }
}
```

Store this in bumba-memory:
```javascript
await mcp__bumba-memory__store_context({
  key: mcpData.mcpKey,
  value: mcpData.syncState,
  ttl: 0 // Never expire
});
```

### Step 6: Display Result

Show the sync summary to the user (already displayed by runner script).

The final output should include:
- ✅ Completion status
- 📊 Sync statistics (created, skipped, errors)
- 🔗 Notion dashboard link
- ⏱️ Duration
- 📅 Timestamp

## Error Handling

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

### GitHub API Rate Limit
The runner script automatically retries with exponential backoff (1s, 2s, 4s delays).

### Notion API Errors
Errors are captured and displayed in the sync summary. Failed tasks can be retried by running `/sync-github` again.

## Example Usage

```bash
# Sync GitHub issues to Notion
/sync-github https://github.com/facebook/react

# Output:
# 🔄 Starting GitHub → Notion sync...
# 📦 Repository: https://github.com/facebook/react
#
# ✓ Validated GitHub URL: facebook/react
# ✓ Found project: react-dashboard
#   Dashboard: https://notion.so/abc123...
# ✓ Loaded configuration
#
# 📥 Fetching GitHub issues...
# ✓ Found 15 open issues
#
# 🔍 Checking for existing tasks...
#   ✨ Creating #123: Add user authentication
#      ✓ Created successfully
#   ✨ Creating #124: Fix login bug
#      ✓ Created successfully
#   ...
#
# ============================================================
# ✅ GitHub sync complete: https://github.com/facebook/react
#
# 📊 Sync Summary:
#   • Found: 15 open issues
#   • Created: 15 new tasks
#   • Skipped: 0 existing tasks
#   • Errors: 0
#
# 🔗 View in Notion: https://notion.so/abc123...
#
# ✨ 15 tasks added to your Notion dashboard!
#    Tasks are filtered by GitHub Repo: https://github.com/facebook/react
#
# Last sync: 2026-01-15T22:30:00.000Z
# Duration: 28.5s
# ============================================================
```

## Performance

Expected timing for 20 issues:
- Fetch GitHub issues: ~5 seconds
- Check duplicates: ~10 seconds
- Create tasks: ~15 seconds
- **Total: ~30 seconds**

For 100 issues: ~2-3 minutes

## Dependencies

- **GitHub CLI (`gh`)**: Required for fetching issues
- **bumba-memory MCP**: For project lookup and sync state storage
- **Notion API**: For task creation and duplicate detection

## Files Used

- `~/.claude/plugins/bumba-notion/lib/sync-helper.js` - Core sync functions
- `~/.claude/plugins/bumba-notion/lib/sync-github-runner.js` - Executable runner
- `~/.claude/plugins/bumba-notion/config/workspace-mapping.json` - Notion credentials
- `~/.claude/plugins/bumba-notion/config/sync-rules.json` - Status mapping and retry config
- `~/.claude/plugins/bumba-notion/state/sync-{slug}.json` - Local sync state backup

---
name: sync-github
description: Sync GitHub issues to Notion tasks (one-way GitHub → Notion)
arguments:
  - name: githubRepo
    description: GitHub repository URL (e.g., https://github.com/owner/repo)
    required: true
---

# GitHub to Notion Sync Workflow

Syncs open GitHub issues from a repository to Notion tasks in the Tasks Master database.

## Prerequisites

- Notion workspace configured with bumba-notion plugin
- GitHub repository URL provided
- Project must exist in Projects Master database with matching GitHub Repo

## Step 1: Validate GitHub Repository URL

Parse and validate the GitHub repository URL:

```bash
# Expected format: https://github.com/{owner}/{repo}
# Extract: owner, repo
```

Validation checks:
- URL starts with `https://github.com/`
- Contains owner and repo segments
- No trailing slashes or extra paths

If invalid:
- Display error: "Invalid GitHub repository URL. Expected format: https://github.com/owner/repo"
- Exit

Store parsed values: `{{owner}}`, `{{repo}}`

---

## Step 2: Find Project in bumba-memory

Query bumba-memory MCP to find project by GitHub repo:

### Option A: Direct Lookup (if using standard slug)

Try direct retrieval first:
```javascript
// Extract project slug from GitHub URL
// https://github.com/owner/repo → owner-repo
const repoSlug = `${owner}-${repo}`;
const contextKey = `bumba-notion:project:${repoSlug}`;

// Attempt direct retrieval
projectMetadata = await mcp__bumba-memory__retrieve_context(contextKey);
```

### Option B: Search by GitHub Repo (fallback)

If direct lookup fails, search through all projects:
```javascript
// Get project index
const indexKey = 'bumba-notion:projects:index';
const index = await mcp__bumba-memory__retrieve_context(indexKey);

// Find project slug by GitHub repo URL
const projectSlug = index.byRepo[githubRepo];

if (projectSlug) {
  const contextKey = `bumba-notion:project:${projectSlug}`;
  projectMetadata = await mcp__bumba-memory__retrieve_context(contextKey);
}
```

### Option C: Local State Fallback

If bumba-memory lookup fails, check local state files:
```bash
# Search local state directory
ls ~/.claude/plugins/bumba-notion/state/project-*.json

# Read each file and match by githubRepo
for file in ~/.claude/plugins/bumba-notion/state/project-*.json; do
  if grep -q "{{githubRepo}}" "$file"; then
    projectMetadata=$(cat "$file")
    break
  fi
done
```

**If no project found (all methods fail):**
- Display error message:
  ```
  ❌ No project found for GitHub repository: {{githubRepo}}

  Searched in:
    • bumba-memory MCP (key: bumba-notion:project:*)
    • Local state files (~/.claude/plugins/bumba-notion/state/)

  Did you run /project-init with this GitHub repo?

  To create a project:
    /project-init
    # Enable "Notion Dashboard" feature
    # Enter GitHub repo: {{githubRepo}}
  ```
- Exit

**If project found:**
- Store project details from metadata:
  - `projectName`: metadata.projectName
  - `projectSlug`: metadata.projectSlug
  - `dashboardPageId`: metadata.dashboardPageId
  - `dashboardUrl`: metadata.dashboardUrl
  - `notionDatabases`: metadata.notionDatabases (tasks, epics, sprints, projects)
- Log: "Found project: {{projectName}} ({{projectSlug}})"

---

## Step 3: Fetch GitHub Issues

Use `gh` CLI via Bash tool (or GitHub MCP if available):

```bash
# List open issues in JSON format
gh issue list --repo {{owner}}/{{repo}} \
  --state open \
  --limit 100 \
  --json number,title,state,url,body,labels,createdAt,updatedAt
```

**Alternative using GitHub API:**
```bash
curl -H "Authorization: token $GITHUB_TOKEN" \
  "https://api.github.com/repos/{{owner}}/{{repo}}/issues?state=open&per_page=100"
```

Store result: Array of issues

Filter criteria:
- Include: state = "open"
- Exclude: Pull requests (check if `pull_request` field exists)
- Limit: 100 issues per sync

Log: "Found {{count}} open issues to sync"

**If no issues found:**
- Display: "No open issues found in {{githubRepo}}"
- Exit with success (nothing to sync)

---

## Step 4: Load Sync Rules

Read `~/.claude/plugins/bumba-notion/config/sync-rules.json`:

Extract:
- `statusMapping.github_to_notion`: Map GitHub states to Notion statuses
- `syncBehavior.maxRetries`: Max retry attempts (default: 3)
- `syncBehavior.retryBackoff`: Backoff delays in milliseconds [1000, 2000, 4000]

Default status mapping if file missing:
```json
{
  "open": "backlog",
  "closed": "completed"
}
```

---

## Step 5: Check for Existing Tasks (Duplicate Detection)

For each GitHub issue, check if task already exists in Notion:

Use `Notion:notion-database-query`:
- database_id: Load from `workspace-mapping.json`
  - Path: `masterDatabases.tasks`
- filter:
  ```json
  {
    "property": "GitHub Issue",
    "url": { "equals": "{{issue.url}}" }
  }
  ```

**Logic:**
```
for each issue in issues:
  existingTask = query Notion for issue.url

  if existingTask found:
    skip this issue
    increment skippedCount
    log: "Skipped #{{issue.number}}: {{issue.title}} (already exists)"
  else:
    add issue to createQueue
```

Result: `createQueue` array containing only new issues

Log: "{{createQueue.length}} new issues to create"

---

## Step 6: Create Notion Tasks with Retry Logic

For each issue in `createQueue`:

### 6.1 Map GitHub State to Notion Status

Apply status mapping from sync-rules.json:
```javascript
notionStatus = statusMapping[issue.state] || "backlog"
```

Examples:
- GitHub "open" → Notion "backlog"
- GitHub "closed" → Notion "completed"

### 6.2 Prepare Task Properties

Build Notion page properties:
```json
{
  "parent": {
    "database_id": "{{workspace.databases.tasks}}"
  },
  "properties": {
    "Task ID": {
      "title": [
        {
          "text": {
            "content": "{{issue.title}}"
          }
        }
      ]
    },
    "Status": {
      "select": {
        "name": "{{notionStatus}}"
      }
    },
    "GitHub Repo": {
      "url": "{{githubRepo}}"
    },
    "GitHub Issue": {
      "url": "{{issue.url}}"
    },
    "Priority": {
      "number": 5
    },
    "Started At": {
      "date": null
    },
    "Completed At": {
      "date": null
    }
  }
}
```

**Note:** We're NOT setting Epic Name or Sprint ID - those will be managed manually in Notion or via future features.

### 6.3 Create Task with Retry Logic

Use `Notion:notion-create-page` with exponential backoff:

```javascript
async function createTaskWithRetry(taskData, maxRetries = 3) {
  const backoffDelays = [1000, 2000, 4000]; // milliseconds

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      const result = await Notion.createPage(taskData);
      return { success: true, data: result };
    } catch (error) {
      // Check if it's a rate limit error (429)
      if (error.status === 429 && attempt < maxRetries) {
        const delay = backoffDelays[attempt];
        log(`Rate limited. Retrying in ${delay}ms... (attempt ${attempt + 1}/${maxRetries})`);
        await sleep(delay);
        continue;
      }

      // Check if it's a temporary error
      if (error.status >= 500 && attempt < maxRetries) {
        const delay = backoffDelays[attempt];
        log(`Server error. Retrying in ${delay}ms... (attempt ${attempt + 1}/${maxRetries})`);
        await sleep(delay);
        continue;
      }

      // Non-retryable error or max retries exceeded
      return { success: false, error: error.message };
    }
  }

  return { success: false, error: "Max retries exceeded" };
}
```

### 6.4 Track Results

For each create attempt:
- **Success**: Increment `createdCount`, log success
- **Failure**: Increment `errorCount`, store error details

Example logs:
```
✅ Created #123: Add user authentication
✅ Created #124: Fix login bug
❌ Failed #125: Rate limit exceeded (max retries)
```

---

## Step 7: Update Sync State

Store sync state in bumba-memory MCP for global access:

### Store Sync Metadata

Use `mcp__bumba-memory__store_context`:

**Key**: `bumba-notion:sync:{{projectSlug}}`

**Value**:
```json
{
  "projectSlug": "{{projectSlug}}",
  "projectName": "{{projectName}}",
  "githubRepo": "{{githubRepo}}",
  "dashboardPageId": "{{dashboardPageId}}",
  "lastSync": "{{ISO timestamp}}",
  "syncHistory": [
    {
      "timestamp": "{{ISO timestamp}}",
      "totalIssues": {{issues.length}},
      "created": {{createdCount}},
      "skipped": {{skippedCount}},
      "errors": {{errorCount}},
      "duration": {{durationMs}},
      "success": {{errorCount === 0}}
    }
  ],
  "stats": {
    "totalSyncs": {{syncCount}},
    "totalIssuesCreated": {{totalCreated}},
    "lastError": {{lastError || null}}
  },
  "errors": [
    {
      "issueNumber": {{number}},
      "issueTitle": "{{title}}",
      "error": "{{errorMessage}}",
      "timestamp": "{{ISO timestamp}}"
    }
  ]
}
```

**TTL**: 0 (never expire)

### Local State Backup

Also write to local state file as backup:
```bash
# Ensure state directory exists
mkdir -p ~/.claude/plugins/bumba-notion/state

# Write sync state
cat > ~/.claude/plugins/bumba-notion/state/sync-{{projectSlug}}.json <<EOF
{
  "mcpKey": "bumba-notion:sync:{{projectSlug}}",
  "lastSync": "{{ISO timestamp}}",
  "stats": {...},
  "errors": [...]
}
EOF
```

This provides redundancy in case MCP server is unavailable.

---

## Step 8: Display Sync Summary

Output formatted summary to user:

```
✅ GitHub sync complete: {{githubRepo}}

📊 Sync Summary:
  • Found: {{issues.length}} open issues
  • Created: {{createdCount}} new tasks
  • Skipped: {{skippedCount}} existing tasks
  • Errors: {{errorCount}}

🔗 View in Notion: https://notion.so/{{dashboardPageId}}

{{if errors.length > 0}}
⚠️ Errors encountered:
{{for each error}}
  • Issue #{{number}}: {{message}}
{{end}}

💡 Tip: Tasks with errors were not created. You can:
  1. Check error messages above
  2. Fix issues in GitHub
  3. Run /sync-github again to retry
{{endif}}

{{if createdCount > 0}}
✨ {{createdCount}} task{{createdCount > 1 ? 's' : ''}} added to your Notion dashboard!
   Tasks are filtered by GitHub Repo: {{githubRepo}}
{{endif}}

Last sync: {{timestamp}}
Next sync: Run /sync-github {{githubRepo}} again to sync new issues
```

---

## Error Handling

### Invalid GitHub Repo URL
```
❌ Invalid GitHub repository URL

Expected format: https://github.com/owner/repo
You provided: {{githubRepo}}

Example: https://github.com/facebook/react
```

### Project Not Found
```
❌ No project found for GitHub repository: {{githubRepo}}

This repository is not linked to any Notion project.

To create a project:
  1. Run: /project-init
  2. Enable "Notion Dashboard" feature
  3. Enter GitHub repo: {{githubRepo}}
```

### GitHub API Errors
```
❌ Failed to fetch GitHub issues

Error: {{error.message}}

Possible causes:
  • Repository does not exist or is private
  • GitHub API rate limit exceeded
  • Network connection issue
  • Invalid GitHub token (if using GitHub MCP)

Solution: Verify repository exists and is accessible
```

### Notion API Errors
```
❌ Failed to sync issues to Notion

Created: {{createdCount}} tasks
Errors: {{errorCount}} tasks

Error details:
{{for each error}}
  • Issue #{{number}}: {{message}}
{{end}}

All failed tasks can be retried by running:
  /sync-github {{githubRepo}}
```

---

## Performance Expectations

| Operation | Expected Time |
|-----------|--------------|
| Fetch 20 GitHub issues | < 5 seconds |
| Check duplicates (20 issues) | < 10 seconds |
| Create 20 Notion tasks | < 30 seconds |
| **Total sync time** | **< 45 seconds** |

For 100 issues: ~2-3 minutes

---

## Usage Examples

### Example 1: Sync Public Repo
```bash
/sync-github https://github.com/facebook/react

# Output:
# ✅ GitHub sync complete: https://github.com/facebook/react
# 📊 Sync Summary:
#   • Found: 847 open issues
#   • Created: 100 new tasks (limited to first 100)
#   • Skipped: 0 existing tasks
#   • Errors: 0
```

### Example 2: Re-sync (Duplicate Detection)
```bash
# First sync
/sync-github https://github.com/myorg/myrepo
# Created: 15 tasks

# Second sync (no new issues)
/sync-github https://github.com/myorg/myrepo
# Created: 0 tasks
# Skipped: 15 existing tasks
```

### Example 3: Sync with Errors
```bash
/sync-github https://github.com/myorg/myrepo

# Output:
# ✅ GitHub sync complete
# 📊 Sync Summary:
#   • Found: 10 open issues
#   • Created: 8 new tasks
#   • Skipped: 0 existing tasks
#   • Errors: 2
#
# ⚠️ Errors encountered:
#   • Issue #45: Rate limit exceeded
#   • Issue #47: Network timeout
```

---

## Implementation Notes

### GitHub CLI vs GitHub API

**Option A: Use `gh` CLI (Simpler)**
```bash
gh issue list --repo owner/repo --state open --limit 100 --json number,title,state,url
```
**Pros:** Easy, no token management
**Cons:** Requires `gh` CLI installed

**Option B: Use GitHub API directly (More Flexible)**
```bash
curl -H "Authorization: token $GITHUB_TOKEN" \
  "https://api.github.com/repos/owner/repo/issues?state=open&per_page=100"
```
**Pros:** More control, works everywhere
**Cons:** Token management needed

**Recommendation:** Start with `gh` CLI, fall back to API if not available.

### Notion API Calls

All Notion operations use the native Node.js HTTPS approach we established in the hook:

```javascript
async function notionApiRequest(token, method, endpoint, body = null) {
  const https = require('https');
  return new Promise((resolve, reject) => {
    const options = {
      hostname: 'api.notion.com',
      port: 443,
      path: endpoint,
      method: method,
      headers: {
        'Authorization': `Bearer ${token}`,
        'Notion-Version': '2022-06-28',
        'Content-Type': 'application/json'
      }
    };
    // ... implementation
  });
}
```

This ensures consistency with the `/project-init` integration approach.

---

## Testing Checklist

Before considering this task complete:

- [ ] Command file created and valid
- [ ] GitHub repo URL validation works
- [ ] Project lookup in Projects database works
- [ ] GitHub issues fetched successfully
- [ ] Duplicate detection prevents re-creation
- [ ] Status mapping applied correctly
- [ ] Notion tasks created with all properties
- [ ] GitHub Issue URL linked properly
- [ ] Retry logic handles rate limits
- [ ] Sync state saved correctly
- [ ] Summary displayed with accurate counts
- [ ] Error messages clear and actionable
- [ ] Tested with real repo (10-20 issues)
- [ ] Tested re-sync (duplicate detection)
- [ ] Performance meets expectations (< 45s for 20 issues)

---

## Next Steps

After implementing `/sync-github`:

1. **Test with Real Repository**
   - Use a public repo with 10-20 open issues
   - Verify all tasks appear in Notion
   - Check filtering by GitHub Repo works

2. **Test Edge Cases**
   - Empty repository (no issues)
   - Repository with 100+ issues (pagination)
   - Rate limiting scenarios

3. **Optional Enhancements** (Week 2)
   - Bidirectional sync (Notion → GitHub)
   - Webhook-based real-time sync
   - Label mapping
   - Assignee sync
   - Comment sync

---

**Implementation Time Estimate:** 8-10 hours
**Critical Success Factor:** Duplicate detection must work perfectly to avoid creating duplicate tasks

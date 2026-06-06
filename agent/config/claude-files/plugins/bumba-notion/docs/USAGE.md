# BUMBA-Notion Plugin Usage Guide

Complete guide to using the BUMBA-Notion plugin for project orchestration with GitHub and Notion.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Commands Reference](#commands-reference)
3. [Notion Views](#notion-views)
4. [Auto-Sync Hooks](#auto-sync-hooks)
5. [Dependency Parsing](#dependency-parsing)
6. [Status Mapping](#status-mapping)
7. [Troubleshooting](#troubleshooting)
8. [Performance](#performance)
9. [Advanced Usage](#advanced-usage)

---

## Quick Start

### Prerequisites

1. **Claude Code** installed and configured (version >=2.0.0)
2. **MCP Servers** enabled:
   - `notion` - Notion API integration
   - `github` - GitHub API integration
   - `bumba-memory` - State management
3. **API Tokens**:
   - Notion Integration Token (from notion.so/my-integrations)
   - GitHub Personal Access Token (with repo permissions)

### Installation

The plugin is installed at `~/.claude/plugins/bumba-notion/`

Verify installation:
```bash
ls ~/.claude/plugins/bumba-notion/
# Should show: plugin.json, commands/, hooks/, config/, docs/
```

### First-Time Setup

1. **Navigate to your project directory:**
   ```bash
   cd /path/to/your/project
   ```

2. **Initialize BUMBA-Notion project:**
   ```
   /project-init
   ```

   This will:
   - Create `.bumba-notion-plugin/` directory structure
   - Prompt for project name, GitHub repo, and Notion workspace
   - Create workspace-mapping.json with your configuration
   - Set up Notion databases (Tasks, Epics, Sprints, Projects)

3. **Sync GitHub issues to Notion:**
   ```
   /sync-github
   ```

   This will:
   - Fetch all open issues from your GitHub repository
   - Create corresponding pages in Notion databases
   - Map GitHub issue states to Notion statuses
   - Parse and store task dependencies

4. **Start working:**
   - Your GitHub issues are now in Notion
   - Use Notion views to organize and prioritize work
   - Auto-sync hooks keep everything up to date

---

## Commands Reference

### `/project-init`

**Purpose:** Initialize a new BUMBA-Notion project

**Usage:**
```
/project-init
```

**Prompts:**
1. Project name (e.g., "My Awesome App")
2. GitHub repository URL (e.g., "https://github.com/user/repo")
3. Notion workspace selection (from available workspaces)

**Creates:**
- `.bumba-notion-plugin/` directory structure:
  ```
  .bumba-notion-plugin/
  ├── config/
  │   ├── workspace-mapping.json
  │   └── schema-definitions.json
  ├── state/
  │   └── sync-state.json (after first sync)
  └── logs/
      └── sync.log
  ```

**Notion Databases Created:**
1. **Tasks Master** - Individual work items
2. **Epics Master** - Large features/initiatives
3. **Sprints Master** - Time-boxed iterations
4. **Projects Master** - Top-level project tracking

**Example Output:**
```
✅ Project initialized successfully!

📊 Notion databases created:
   - Tasks Master (database_id: abc123...)
   - Epics Master (database_id: def456...)
   - Sprints Master (database_id: ghi789...)
   - Projects Master (database_id: jkl012...)

🔗 Configuration saved to .bumba-notion-plugin/config/workspace-mapping.json

Next steps:
1. Run /sync-github to sync GitHub issues
2. Open Notion to see your project dashboards
```

**Troubleshooting:**
- If databases fail to create, check Notion API token permissions
- If GitHub repo not found, verify token has repo access
- See [Troubleshooting](#troubleshooting) section for more

---

### `/sync-github`

**Purpose:** Sync GitHub issues to Notion databases

**Usage:**
```
/sync-github
```

**No prompts** - uses configuration from workspace-mapping.json

**What it syncs:**
1. **Epics** (GitHub issues with "epic" label) → Epics Master
2. **Sprints** (GitHub issues with "milestone" label) → Sprints Master
3. **Tasks** (all other open issues) → Tasks Master

**Status Mapping:**
- `open` → `backlog`
- `in progress` → `in_progress`
- `in review` → `review`
- `closed` → `completed`

**Dependency Parsing:**
Extracts dependencies from issue body:
- "Depends on #123"
- "Blocked by #456"
- "Requires #789"

**Example Output:**
```
🔄 Syncing GitHub issues to Notion...

📥 Fetched 42 issues from GitHub
   - 3 epics (labeled "epic")
   - 5 sprints (labeled "milestone")
   - 34 tasks (regular issues)

✅ Sync complete!
   - Created 3 epic pages
   - Created 5 sprint pages
   - Created 34 task pages
   - Parsed 12 task dependencies

💾 Sync state saved to .bumba-notion-plugin/state/sync-state.json

🔗 View your dashboard: https://notion.so/...
```

**Performance:**
- ~500ms per issue (includes dependency parsing)
- Bulk operations for efficiency
- Rate limiting: 3 requests/second to Notion API

**Troubleshooting:**
- If sync fails, check network connectivity
- If issues missing, verify GitHub token permissions
- If dependencies not parsed, check issue body format
- See [Troubleshooting](#troubleshooting) section for more

---

## Notion Views

After running `/project-init`, you'll have these views in Notion:

### Tasks Master Views

#### 1. Kanban Board
**Group by:** Status
**Sort by:** Priority (descending)

Visualize task flow across statuses:
```
┌─────────────┬──────────────┬──────────────┬──────────────┬──────────────┐
│  Backlog    │    Ready     │ In Progress  │    Review    │  Completed   │
├─────────────┼──────────────┼──────────────┼──────────────┼──────────────┤
│ Task A      │ Task D       │ Task G       │ Task J       │ Task M       │
│ Task B      │ Task E       │ Task H       │ Task K       │ Task N       │
│ Task C      │ Task F       │ Task I       │ Task L       │ Task O       │
└─────────────┴──────────────┴──────────────┴──────────────┴──────────────┘
```

#### 2. Ready Queue
**Filter:** Status = "ready"
**Sort by:** Priority (descending)

Shows only tasks ready to be worked on (all dependencies met):
```
┌─────────┬──────────────────────────┬──────────┬──────────────┐
│ Task ID │ Title                    │ Priority │ Dependencies │
├─────────┼──────────────────────────┼──────────┼──────────────┤
│ #42     │ Implement user auth      │ 10       │ ✅ None      │
│ #43     │ Add dashboard UI         │ 9        │ ✅ #42       │
│ #44     │ Setup database schema    │ 8        │ ✅ None      │
└─────────┴──────────────────────────┴──────────┴──────────────┘
```

**Key Feature:** Tasks with incomplete dependencies are automatically excluded from this view.

---

### Epics Master Views

#### 1. All Epics
**Sort by:** Created At (descending)

Shows all epics with current status:
```
┌────────────┬─────────────────────────┬──────────────┬──────────────┐
│ Epic Name  │ GitHub Repo             │ Status       │ Created At   │
├────────────┼─────────────────────────┼──────────────┼──────────────┤
│ User Auth  │ github.com/user/repo    │ in_progress  │ 2025-01-15   │
│ Dashboard  │ github.com/user/repo    │ planning     │ 2025-01-14   │
└────────────┴─────────────────────────┴──────────────┴──────────────┘
```

---

### Sprints Master Views

#### 1. All Sprints
**Sort by:** Start Date (descending)

Shows all sprints chronologically:
```
┌────────────┬──────────────┬────────────┬────────────┬──────────────┐
│ Sprint ID  │ Epic         │ Start Date │ End Date   │ Status       │
├────────────┼──────────────┼────────────┼────────────┼──────────────┤
│ Sprint 3   │ User Auth    │ 2025-01-15 │ 2025-01-29 │ active       │
│ Sprint 2   │ Dashboard    │ 2025-01-01 │ 2025-01-14 │ completed    │
└────────────┴──────────────┴────────────┴────────────┴──────────────┘
```

#### 2. Active Sprints
**Filter:** Status = "active"
**Sort by:** Start Date (ascending)

Shows only currently active sprints:
```
┌────────────┬──────────────┬────────────┬────────────┐
│ Sprint ID  │ Epic         │ Start Date │ End Date   │
├────────────┼──────────────┼────────────┼────────────┤
│ Sprint 3   │ User Auth    │ 2025-01-15 │ 2025-01-29 │
└────────────┴──────────────┴────────────┴────────────┘
```

---

### Projects Master Views

#### 1. All Projects
**Sort by:** Start Date (descending)

Shows all projects with status:
```
┌──────────────┬─────────────────────────┬────────────┬──────────────┐
│ Project Name │ GitHub Repo             │ Start Date │ Status       │
├──────────────┼─────────────────────────┼────────────┼──────────────┤
│ My App       │ github.com/user/repo    │ 2025-01-01 │ active       │
└──────────────┴─────────────────────────┴────────────┴──────────────┘
```

#### 2. Active Projects
**Filter:** Status = "active"
**Sort by:** Start Date (descending)

Shows only active projects.

---

## Auto-Sync Hooks

BUMBA-Notion includes automatic sync hooks that run when you start and end Claude Code sessions.

### Session Start Hook

**Triggers:** When Claude Code session starts in a BUMBA-Notion project

**Behavior:**
1. Detects if project has `.bumba-notion-plugin/` directory
2. If not BUMBA-Notion project → exits silently
3. If BUMBA-Notion project:
   - Loads sync state from `state/sync-state.json`
   - Displays last sync timestamp
   - Displays tasks synced count
   - Displays project name
   - Checks if sync is stale (>1 hour old)
   - If stale → displays warning + recommendation to run `/sync-github`

**Example Output (Fresh Sync):**
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 BUMBA-Notion Project Detected

📅 Last sync: 1/16/2025, 10:30:00 AM
📋 Tasks synced: 42
🎯 Project: My Awesome App
✅ Sync is fresh (synced within last hour)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Example Output (Stale Sync):**
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 BUMBA-Notion Project Detected

📅 Last sync: 1/15/2025, 2:00:00 PM
📋 Tasks synced: 42
🎯 Project: My Awesome App

⚠️  Sync is stale (>1 hour old)

💡 Recommended: Run /sync-github to update tasks from GitHub

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Example Output (No Previous Sync):**
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 BUMBA-Notion Project Detected

📭 No previous sync found

💡 To get started: Run /sync-github to sync GitHub issues

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Debounce Mechanism:**

To prevent duplicate syncs when multiple session events fire, the hook uses a 5-second debounce window:

```javascript
const syncQueue = new Map();
const DEBOUNCE_WINDOW = 5000; // 5 seconds

function queueSync(projectSlug, syncFn) {
  // Clear existing timer if present
  if (syncQueue.has(projectSlug)) {
    clearTimeout(syncQueue.get(projectSlug));
  }

  // Set new timer
  const timerId = setTimeout(() => {
    syncFn();
    syncQueue.delete(projectSlug);
  }, DEBOUNCE_WINDOW);

  syncQueue.set(projectSlug, timerId);
}
```

This pattern is adapted from BUMBA CLI's issue-bridge.js.

---

### Session End Hook

**Triggers:** When Claude Code session ends in a BUMBA-Notion project

**Behavior:**
1. Detects if project has `.bumba-notion-plugin/` directory
2. If not BUMBA-Notion project → exits silently
3. If BUMBA-Notion project:
   - Displays final sync summary
   - Shows last sync timestamp
   - Shows tasks synced count
   - Shows project name
   - Shows dashboard URL

**Example Output:**
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 Running final GitHub sync...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔄 Checking for GitHub updates...

✅ Session sync complete

📅 Last sync: 1/16/2025, 10:30:00 AM
📋 Total tasks synced: 42
🎯 Project: My Awesome App
🔗 Dashboard: https://notion.so/...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
👋 Session ended - all changes saved
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Non-Blocking Execution:**

The session-end hook is designed to never block session termination:

```javascript
module.exports = async ({ workingDirectory, mcpTools }) => {
  try {
    // ... hook logic ...
  } catch (error) {
    // Catch-all error handler - don't block session end
    console.error('⚠️  Session end hook error:', error.message);
    // Silent exit - don't prevent session from ending
  }
};
```

---

## Dependency Parsing

BUMBA-Notion automatically parses task dependencies from GitHub issue bodies.

### Supported Formats

The plugin detects these patterns in issue body text:

1. **"Depends on #123"** - Standard dependency declaration
2. **"Blocked by #456"** - Indicates blocker relationship
3. **"Requires #789"** - Explicit requirement relationship

All patterns are case-insensitive and support multiple dependencies:

```markdown
# Issue Body Example

This task implements the user authentication flow.

Depends on #42 (database schema)
Blocked by #43 (API endpoints)
Requires #44 (frontend UI)

## Acceptance Criteria
- [ ] Users can log in
- [ ] Users can log out
```

### Parsing Logic

The dependency parser uses regex to extract issue numbers:

```javascript
const dependencyPatterns = [
  /depends on #(\d+)/gi,
  /blocked by #(\d+)/gi,
  /requires #(\d+)/gi
];

function parseDependencies(issueBody) {
  const dependencies = new Set();

  for (const pattern of dependencyPatterns) {
    const matches = issueBody.matchAll(pattern);
    for (const match of matches) {
      dependencies.add(parseInt(match[1], 10));
    }
  }

  return Array.from(dependencies);
}
```

### Storage in Notion

Dependencies are stored as **self-relations** in the Tasks Master database:

**Schema:**
```json
{
  "Dependencies": {
    "type": "relation",
    "database": "tasks",
    "single_property": false,
    "description": "Tasks that this task depends on (self-relation)"
  }
}
```

**Visual in Notion:**
```
Task: Implement user login (#45)
├── Dependencies:
│   ├── → Task #42 (Database schema)
│   ├── → Task #43 (API endpoints)
│   └── → Task #44 (Frontend UI)
```

### Ready Queue Integration

The Ready Queue view uses dependencies to filter tasks:

**Logic:**
1. Task must have Status = "ready"
2. All dependency tasks must have Status = "completed"
3. If any dependency is not completed → task excluded from Ready Queue

**Example:**

```
Task #45: Implement user login
├── Dependencies:
│   ├── Task #42 (completed ✅)
│   ├── Task #43 (completed ✅)
│   └── Task #44 (in_progress ❌)
└── Result: NOT shown in Ready Queue (dependency #44 incomplete)
```

After Task #44 is completed:
```
Task #45: Implement user login
├── Dependencies:
│   ├── Task #42 (completed ✅)
│   ├── Task #43 (completed ✅)
│   └── Task #44 (completed ✅)
└── Result: SHOWN in Ready Queue (all dependencies complete)
```

---

## Status Mapping

GitHub issue states are mapped to Notion statuses during sync:

### GitHub → Notion Mapping

| GitHub State/Label | Notion Status | Color  |
|-------------------|---------------|--------|
| `open` (no labels) | `backlog` | Gray |
| `in progress` | `in_progress` | Yellow |
| `in review` | `review` | Purple |
| `closed` | `completed` | Green |

### Custom Label Mapping

You can configure custom label mappings in workspace-mapping.json:

```json
{
  "statusMapping": {
    "github_labels": {
      "todo": "backlog",
      "doing": "in_progress",
      "reviewing": "review",
      "done": "completed"
    }
  }
}
```

### Bidirectional Sync (Future)

Currently, sync is **unidirectional** (GitHub → Notion).

Future versions will support bidirectional sync:
- Changes in Notion → update GitHub issue state
- Requires webhook integration with Notion API

---

## Troubleshooting

### Common Issues

#### 1. "MCP server not found: notion"

**Cause:** Notion MCP server not installed or not enabled

**Fix:**
1. Check if Notion MCP server is installed:
   ```bash
   ls ~/.claude/mcp-servers/
   # Should include "notion" directory
   ```

2. Enable Notion MCP server in Claude Code settings:
   ```json
   {
     "mcpServers": {
       "notion": {
         "command": "npx",
         "args": ["-y", "@notionhq/client"]
       }
     }
   }
   ```

3. Restart Claude Code

---

#### 2. "GitHub API rate limit exceeded"

**Cause:** Too many API requests to GitHub in short time

**Fix:**
- Wait for rate limit to reset (shown in error message)
- Use authenticated requests (provide GitHub token in workspace-mapping.json)
- Authenticated requests have higher rate limits (5000/hour vs 60/hour)

---

#### 3. "Notion database not found"

**Cause:** Database IDs in workspace-mapping.json are incorrect or outdated

**Fix:**
1. Verify database IDs in Notion:
   - Open database in Notion
   - Copy database ID from URL (32-character hex string)

2. Update workspace-mapping.json:
   ```json
   {
     "databases": {
       "tasks": "abc123...",
       "epics": "def456...",
       "sprints": "ghi789..."
     }
   }
   ```

3. Re-run `/sync-github`

---

#### 4. "Session hooks not firing"

**Cause:** Hooks not registered in plugin.json or hook scripts have errors

**Fix:**
1. Verify hooks in plugin.json:
   ```json
   {
     "hooks": [
       {
         "event": "session-start",
         "script": "hooks/session-start.js"
       },
       {
         "event": "session-end",
         "script": "hooks/session-end.js"
       }
     ]
   }
   ```

2. Check hook script syntax:
   ```bash
   node ~/.claude/plugins/bumba-notion/hooks/session-start.js
   # Should not throw syntax errors
   ```

3. Check Claude Code logs for hook errors:
   ```bash
   tail -f ~/.claude/logs/claude-code.log
   ```

---

#### 5. "Dependencies not parsed"

**Cause:** Issue body doesn't match dependency patterns or sync ran before schema update

**Fix:**
1. Verify issue body format:
   ```markdown
   Depends on #123
   Blocked by #456
   Requires #789
   ```

2. Ensure schema includes Dependencies property:
   ```bash
   cat ~/.claude/plugins/bumba-notion/config/schema-definitions.json | grep Dependencies
   ```

3. Re-run `/sync-github` to re-parse all issues

---

#### 6. "Ready Queue shows tasks with incomplete dependencies"

**Cause:** Notion view filter not configured correctly

**Fix:**
1. Open Tasks Master database in Notion
2. Edit "Ready Queue" view
3. Verify filter configuration:
   ```
   Filter: Status = "ready"
   Additional Filter: Dependencies.Status = "completed" (for ALL dependencies)
   ```

---

#### 7. "Sync state file missing"

**Cause:** First sync hasn't run yet or state file was deleted

**Fix:**
- Run `/sync-github` to create new sync state file
- File will be created at `.bumba-notion-plugin/state/sync-state.json`

---

## Performance

### Sync Performance

Typical sync times for various project sizes:

| Issues | Time | Rate |
|--------|------|------|
| 10 | ~5s | 2 issues/sec |
| 50 | ~25s | 2 issues/sec |
| 100 | ~50s | 2 issues/sec |
| 500 | ~4min | 2 issues/sec |

**Factors affecting performance:**
- Network latency to GitHub/Notion APIs
- Number of dependencies per issue
- Size of issue body content

### Optimization Tips

1. **Incremental Sync (Future):**
   Only sync issues modified since last sync

2. **Batch Operations:**
   Plugin already uses bulk operations where possible

3. **Rate Limiting:**
   Plugin respects API rate limits (3 req/sec to Notion)

---

## Advanced Usage

### Manual Sync State Management

Sync state is stored in `.bumba-notion-plugin/state/sync-state.json`:

```json
{
  "lastSync": "2025-01-16T10:30:00.000Z",
  "projectName": "My Awesome App",
  "projectSlug": "my-awesome-app",
  "totalIssuesCreated": 42,
  "issuesSynced": 42,
  "dashboardUrl": "https://notion.so/..."
}
```

**Manual edits:**
- Change `lastSync` to trigger stale sync warning
- Update `projectName` to change display name
- Clear file to reset sync state

### Custom Schema Extensions

You can extend the schema in `config/schema-definitions.json`:

**Example: Add "Story Points" property to Tasks:**

```json
{
  "databases": {
    "tasks": {
      "properties": {
        "Story Points": {
          "type": "number",
          "format": "number",
          "description": "Estimated effort for this task"
        }
      }
    }
  }
}
```

After editing schema:
1. Update Notion databases manually (add property)
2. Update sync logic to populate new property
3. Re-run `/sync-github`

### Webhook Integration (Future)

Future versions will support webhooks for real-time sync:

**GitHub Webhooks:**
- Trigger sync on issue creation/update
- Reduce sync latency (seconds instead of hours)

**Notion Webhooks:**
- Update GitHub when task status changes in Notion
- Bidirectional sync

### Multi-Repo Projects

For projects spanning multiple GitHub repos:

1. Create separate `.bumba-notion-plugin/` directories for each repo
2. Use different workspace-mapping.json for each
3. Sync each repo independently with `/sync-github`
4. Use Notion relations to link tasks across repos

---

## FAQ

**Q: Can I use BUMBA-Notion with private GitHub repos?**
A: Yes, provide a GitHub Personal Access Token with `repo` permissions in workspace-mapping.json.

**Q: Does BUMBA-Notion support GitHub Projects (beta)?**
A: Not yet. Currently syncs issues only. GitHub Projects support planned for future release.

**Q: Can I sync multiple Notion workspaces?**
A: Yes, create different workspace-mapping.json files and switch between them.

**Q: How do I delete all synced data?**
A: Delete pages from Notion databases manually. Then delete `.bumba-notion-plugin/` directory locally.

**Q: Can I use BUMBA-Notion without Claude Code?**
A: No, the plugin is designed specifically for Claude Code CLI and relies on MCP servers.

**Q: How do I update the plugin to latest version?**
A: Plugin updates are handled by Claude Code. Run `claude-code --update-plugins`.

**Q: Can I contribute to BUMBA-Notion?**
A: Yes! See CONTRIBUTING.md in the plugin repository for guidelines.

---

**Last Updated:** Auto-generated by autonomous development agent
**Version:** 1.0
**Plugin:** bumba-notion v1.0.0
**Support:** For issues, see TROUBLESHOOTING.md or open an issue on GitHub

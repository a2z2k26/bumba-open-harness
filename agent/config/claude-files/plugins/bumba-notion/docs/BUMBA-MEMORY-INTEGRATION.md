# bumba-memory MCP Integration

**How bumba-notion uses bumba-memory for project state management**

## Overview

The bumba-notion plugin uses the `bumba-memory` MCP server for **global state management** across all projects. This allows commands like `/sync-github` to work from any directory and provides centralized project discovery.

## Architecture: Hybrid Storage

We use a **hybrid approach** combining bumba-memory MCP with local file storage:

### bumba-memory MCP (Primary)
- **Purpose**: Global, cross-project access
- **Use Cases**: Project lookups, sync state, cross-project queries
- **Benefits**: Access from any directory, structured queries, no file I/O
- **Dependency**: Requires bumba-memory MCP server running

### Local Files (Backup)
- **Purpose**: Redundancy and debugging
- **Location**: `~/.claude/plugins/bumba-notion/state/`
- **Use Cases**: Fallback when MCP unavailable, manual inspection
- **Benefits**: Always available, easy to inspect, no dependencies

---

## Data Stored in bumba-memory

### 1. Project Metadata

**Key Pattern**: `bumba-notion:project:{slug}`

**Example Key**: `bumba-notion:project:my-awesome-app`

**Value Structure**:
```json
{
  "projectName": "my-awesome-app",
  "projectSlug": "my-awesome-app",
  "githubRepo": "https://github.com/me/my-awesome-app",
  "dashboardPageId": "abc123def456...",
  "dashboardUrl": "https://notion.so/abc123...",
  "localPath": "/home/me/projects/my-awesome-app",
  "createdAt": "2026-01-15T21:30:00.000Z",
  "notionDatabases": {
    "tasks": "...",
    "epics": "...",
    "sprints": "...",
    "projects": "..."
  },
  "template": "node",
  "features": {
    "gitInit": true,
    "autoSandbox": true,
    "githubIntegration": true,
    "notionDashboard": true
  }
}
```

**Stored By**: `/project-init` hook (`on-project-init-complete.js`)

**Used By**: `/sync-github`, future commands

**TTL**: 0 (never expires)

---

### 2. Project Index

**Key**: `bumba-notion:projects:index`

**Value Structure**:
```json
{
  "projects": [
    "my-awesome-app",
    "another-project",
    "third-project"
  ],
  "byRepo": {
    "https://github.com/me/my-awesome-app": "my-awesome-app",
    "https://github.com/me/another-project": "another-project"
  },
  "lastUpdated": "2026-01-15T22:00:00.000Z"
}
```

**Purpose**: Fast project discovery and GitHub repo → project slug mapping

**Stored By**: `/project-init` hook

**Used By**: `/sync-github` for GitHub repo lookups

**TTL**: 0 (never expires)

---

### 3. Sync State

**Key Pattern**: `bumba-notion:sync:{slug}`

**Example Key**: `bumba-notion:sync:my-awesome-app`

**Value Structure**:
```json
{
  "projectSlug": "my-awesome-app",
  "projectName": "my-awesome-app",
  "githubRepo": "https://github.com/me/my-awesome-app",
  "dashboardPageId": "abc123...",
  "lastSync": "2026-01-15T22:30:00.000Z",
  "syncHistory": [
    {
      "timestamp": "2026-01-15T22:30:00.000Z",
      "totalIssues": 15,
      "created": 15,
      "skipped": 0,
      "errors": 0,
      "duration": 12500,
      "success": true
    },
    {
      "timestamp": "2026-01-15T23:00:00.000Z",
      "totalIssues": 15,
      "created": 0,
      "skipped": 15,
      "errors": 0,
      "duration": 5200,
      "success": true
    }
  ],
  "stats": {
    "totalSyncs": 2,
    "totalIssuesCreated": 15,
    "lastError": null
  },
  "errors": []
}
```

**Stored By**: `/sync-github` command

**Used By**: Status commands, analytics, debugging

**TTL**: 0 (never expires)

---

## Workflow: Project Creation

When a user runs `/project-init` with Notion Dashboard enabled:

```
1. User runs /project-init
   ↓
2. Command writes .claude/config/project-config.json
   ↓
3. Hook detects file write (on-project-init-complete.js)
   ↓
4. Hook creates E2B structure
   ↓
5. Hook creates Notion dashboard
   ↓
6. Hook stores project metadata:

   a) Store in bumba-memory (via MCP):
      Key: bumba-notion:project:my-app
      Value: {projectName, githubRepo, dashboardPageId, ...}

   b) Store locally (backup):
      File: ~/.claude/plugins/bumba-notion/state/project-my-app.json

   c) Update global index:
      Key: bumba-notion:projects:index
      Add project to list
      Map githubRepo → projectSlug

   d) Store locally (backup):
      File: ~/.claude/plugins/bumba-notion/state/projects-index.json
   ↓
7. Success message displayed with dashboard URL
```

---

## Workflow: GitHub Sync

When a user runs `/sync-github https://github.com/me/my-app`:

```
1. User runs /sync-github from ANY directory
   ↓
2. Parse GitHub repo URL → owner: "me", repo: "my-app"
   ↓
3. Find project (3 methods, try in order):

   a) Direct lookup:
      Key: bumba-notion:project:me-my-app
      Try: mcp__bumba-memory__retrieve_context

   b) Index lookup (if direct fails):
      Key: bumba-notion:projects:index
      Get: index.byRepo["https://github.com/me/my-app"]
      → Returns: "my-app"
      Then: mcp__bumba-memory__retrieve_context("bumba-notion:project:my-app")

   c) Local fallback (if MCP fails):
      Search: ~/.claude/plugins/bumba-notion/state/project-*.json
      Match: githubRepo field
   ↓
4. If project found:
   Extract: dashboardPageId, notionDatabases, projectSlug
   ↓
5. Fetch GitHub issues
   ↓
6. Sync to Notion (create tasks)
   ↓
7. Store sync state:

   a) Store in bumba-memory:
      Key: bumba-notion:sync:my-app
      Value: {lastSync, stats, history, errors}

   b) Store locally (backup):
      File: ~/.claude/plugins/bumba-notion/state/sync-my-app.json
   ↓
8. Display summary
```

---

## MCP Tool Usage

### Store Context

```javascript
// Store project metadata
await mcp__bumba-memory__store_context({
  key: "bumba-notion:project:my-app",
  value: projectMetadata,
  ttl: 0 // Never expire
});
```

### Retrieve Context

```javascript
// Get project metadata
const project = await mcp__bumba-memory__retrieve_context({
  key: "bumba-notion:project:my-app"
});
```

### Search Context (Future)

```javascript
// Find all projects
const allProjects = await mcp__bumba-memory__search_memory({
  query: "bumba-notion:project:*",
  limit: 100
});
```

---

## Local File Structure

Backup files stored in `~/.claude/plugins/bumba-notion/state/`:

```
state/
├── project-my-app.json              # Project metadata backup
├── project-another-project.json     # Another project
├── projects-index.json              # Global index backup
├── sync-my-app.json                 # Sync state for my-app
└── sync-another-project.json        # Sync state for another project
```

### Example: project-my-app.json

```json
{
  "mcpKey": "bumba-notion:project:my-app",
  "projectName": "my-app",
  "projectSlug": "my-app",
  "githubRepo": "https://github.com/me/my-app",
  "dashboardPageId": "abc123...",
  "dashboardUrl": "https://notion.so/abc123...",
  "localPath": "/home/me/projects/my-app",
  "createdAt": "2026-01-15T21:30:00.000Z",
  "notionDatabases": {...},
  "template": "node",
  "features": {...},
  "storedAt": "2026-01-15T21:30:05.000Z"
}
```

---

## Benefits of This Architecture

### 1. Global Access
```bash
# Works from ANY directory
cd ~/Desktop
/sync-github https://github.com/me/my-app
# ✅ Finds project via bumba-memory
```

### 2. Fast Lookups
```bash
# Direct key access is instant
mcp__bumba-memory__retrieve_context("bumba-notion:project:my-app")
# < 100ms response time
```

### 3. Redundancy
```bash
# If MCP server is down, fallback to local files
# If local files missing, still have MCP
# Double redundancy ensures data safety
```

### 4. Cross-Project Queries
```javascript
// Get all projects
const index = await retrieve_context("bumba-notion:projects:index");
console.log(`Total projects: ${index.projects.length}`);

// Find project by GitHub repo
const slug = index.byRepo["https://github.com/me/my-app"];
```

### 5. No File I/O in Commands
```javascript
// No need to read files, search directories, parse JSON
// Just one MCP call
const project = await retrieve_context(key);
```

---

## Error Handling

### MCP Server Unavailable

If bumba-memory MCP server is not running:

```
⚠️ bumba-memory MCP server unavailable, using local fallback

Searching local state: ~/.claude/plugins/bumba-notion/state/
Found project: my-app

⚡ Sync will continue using local state
💡 Tip: Start bumba-memory MCP server for better performance
```

### Project Not Found

If project doesn't exist in either location:

```
❌ No project found for GitHub repository: https://github.com/me/my-app

Searched in:
  • bumba-memory MCP (key: bumba-notion:project:*)
  • Local state files (~/.claude/plugins/bumba-notion/state/)

Did you run /project-init with this GitHub repo?

To create a project:
  /project-init
  # Enable "Notion Dashboard" feature
  # Enter GitHub repo: https://github.com/me/my-app
```

---

## Debugging

### Check if Project is Stored

```bash
# Via MCP (if available)
# Use Claude Code or bumba-memory CLI

# Via local files
cat ~/.claude/plugins/bumba-notion/state/project-my-app.json

# Check index
cat ~/.claude/plugins/bumba-notion/state/projects-index.json
```

### List All Projects

```bash
# Via local files
ls ~/.claude/plugins/bumba-notion/state/project-*.json

# Extract project names
for f in ~/.claude/plugins/bumba-notion/state/project-*.json; do
  jq -r '.projectName' "$f"
done
```

### View Sync History

```bash
# Via local files
cat ~/.claude/plugins/bumba-notion/state/sync-my-app.json | jq '.syncHistory'
```

---

## Migration / Cleanup

### Export All Project Data

```bash
# Create backup
mkdir -p ~/bumba-notion-backup
cp -r ~/.claude/plugins/bumba-notion/state ~/bumba-notion-backup/

# Or export as single JSON
jq -s '.' ~/.claude/plugins/bumba-notion/state/project-*.json > ~/all-projects.json
```

### Remove Old Projects

```bash
# Remove from local state
rm ~/.claude/plugins/bumba-notion/state/project-old-app.json
rm ~/.claude/plugins/bumba-notion/state/sync-old-app.json

# Remove from bumba-memory (via MCP)
# Use Claude Code to call:
# mcp__bumba-memory__delete_context("bumba-notion:project:old-app")
# mcp__bumba-memory__delete_context("bumba-notion:sync:old-app")

# Update index
# Edit projects-index.json and remove from projects array and byRepo mapping
```

---

## Future Enhancements

### Analytics Commands

```bash
# Show all projects
/bumba-notion-projects

# Show project stats
/bumba-notion-stats my-app

# Show sync history
/bumba-notion-sync-history my-app
```

### Auto-Sync

```bash
# Watch GitHub repos and auto-sync
/bumba-notion-watch enable my-app

# Periodic sync every 30 minutes
# Stores last sync time in bumba-memory
# Skips if no new issues
```

### Cross-Project Reports

```bash
# Generate report across all projects
/bumba-notion-report

# Output:
# Total projects: 5
# Total tasks synced: 342
# Active projects: 3
# Last 7 days: 42 new tasks
```

---

## Related Documentation

- **Quick Start**: `QUICK-START.md`
- **Project Init Integration**: `PROJECT-INIT-INTEGRATION.md`
- **Sync GitHub Command**: `../commands/sync-github.md`
- **Troubleshooting**: `TROUBLESHOOTING.md`

---

**Summary**: The bumba-memory integration provides global, fast, and reliable project state management while maintaining local file backups for redundancy. This architecture enables commands to work from any directory and provides a foundation for future cross-project features.

# /project-init Integration Guide

**Version:** 1.0.0
**Status:** Production Ready

## Overview

The bumba-notion plugin seamlessly integrates with the global `/project-init` command to create both local E2B Orchestrator project structures and Notion project management dashboards in a single workflow.

## Architecture

### Two-Phase Integration

**Phase 1: User Interaction (Command)**
- User runs `/project-init` command
- Interactive prompts collect configuration
- Includes new "Notion Dashboard" feature option
- Writes `project-config.json` with all settings

**Phase 2: Automated Execution (Hook)**
- `on-project-init-complete` hook detects config write
- Creates E2B Orchestrator structure (existing)
- Creates Notion dashboard (new integration)
- Returns dashboard URL to user

### Hook Architecture

The `on-project-init-complete.js` hook now includes:

```javascript
// Step 11: Create Notion dashboard (if enabled)
if (config.options?.notionDashboard) {
  notionDashboardUrl = await this.createNotionDashboard(projectPath, config);
}
```

### Notion API Integration

The hook uses native Node.js `https` module to interact with Notion API:

1. **Load Configuration**: Reads `workspace-mapping.json` from plugin
2. **Duplicate Template**: Creates new page from master template
3. **Create Project Entry**: Adds row to Projects Master database
4. **Apply Filters**: Linked views automatically filter by GitHub Repo

## User Workflow

### Step-by-Step Example

```bash
# 1. Navigate to your project directory
cd ~/projects/my-awesome-app

# 2. Run the enhanced project-init command
/project-init

# 3. Answer interactive prompts:

# Prompt: "Which language template would you like to use?"
# Selection: Node.js ✓

# Prompt: "Which features do you want to enable?" (multi-select)
# Selection:
# - Git Init ✓
# - Auto-Sandbox ✓
# - GitHub Integration ✓
# - Notion Dashboard ✓  ← NEW!

# Prompt: "What is the GitHub repository URL for this project?"
# Input: https://github.com/username/my-awesome-app

# Prompt: "What should be the default execution mode?"
# Selection: Auto ✓

# 4. Wait for completion (3-5 seconds)

# 5. Success output shows:
# ✅ E2B Orchestrator structure created
# ✅ Notion dashboard created
# 🔗 Notion URL: https://notion.so/12345...
```

### Configuration Stored

The command creates `.claude/project-config.json`:

```json
{
  "version": "1.0.0",
  "project": {
    "name": "my-awesome-app",
    "template": "node",
    "createdAt": "2026-01-15T21:30:00.000Z"
  },
  "options": {
    "gitInit": true,
    "autoSandbox": true,
    "githubIntegration": true,
    "notionDashboard": true,
    "githubRepo": "https://github.com/username/my-awesome-app",
    "defaultMode": "auto"
  }
}
```

## What Gets Created

### Local Structure (E2B Orchestrator)

```
my-awesome-app/
├── .claude/
│   ├── commands/
│   ├── mcp-servers/
│   ├── config/
│   │   ├── bumba-sandbox-config.json
│   │   ├── orchestrator-state.json
│   │   └── project-config.json  ← Triggers hook
│   ├── templates/
│   └── hooks/
├── apps/
│   └── sandbox_agent_working_dir/
│       ├── temp/
│       ├── logs/
│       └── code/
├── docs/
│   ├── e2b/
│   └── prd/
├── worktrees/
├── src/
├── tests/
├── .gitignore
├── .env.template
├── package.json  (if Node.js template)
└── README.md
```

### Notion Structure

1. **Duplicated Dashboard Page** (from template)
   - Contains linked database views:
     - Tasks Kanban (filtered by GitHub Repo)
     - Epics Table (filtered by GitHub Repo)
     - Sprints Table (filtered by GitHub Repo)
     - Ready Queue (filtered by GitHub Repo)

2. **Projects Master Entry**
   - Project Name: "my-awesome-app"
   - GitHub Repo: "https://github.com/username/my-awesome-app"
   - Start Date: Today's date
   - Status: "active"

3. **Automatic Filtering**
   - All linked database views show ONLY data for this project
   - Filtering based on GitHub Repo URL property
   - Works across all master databases

## Technical Details

### Notion API Methods

#### 1. Page Duplication

```javascript
async notionDuplicatePage(token, pageId, newTitle) {
  // 1. Get template page content
  const pageContent = await this.notionApiRequest(token, 'GET', `/v1/pages/${pageId}`);

  // 2. Create new page with same parent
  const newPage = await this.notionApiRequest(token, 'POST', '/v1/pages', {
    parent: pageContent.parent,
    properties: { title: { title: [{ text: { content: newTitle } }] } }
  });

  // 3. Copy blocks from template
  const templateBlocks = await this.notionApiRequest(token, 'GET', `/v1/blocks/${pageId}/children`);
  await this.notionApiRequest(token, 'PATCH', `/v1/blocks/${newPage.id}/children`, {
    children: templateBlocks.results.map(cleanBlock)
  });

  return newPage;
}
```

#### 2. Projects Database Entry

```javascript
async notionCreateProjectEntry(token, databaseId, projectName, githubRepo, pageId) {
  return await this.notionApiRequest(token, 'POST', '/v1/pages', {
    parent: { database_id: databaseId },
    properties: {
      'Project Name': { title: [{ text: { content: projectName } }] },
      'GitHub Repo': { url: githubRepo },
      'Start Date': { date: { start: new Date().toISOString().split('T')[0] } },
      'Status': { select: { name: 'active' } }
    }
  });
}
```

### Configuration Loading

The hook loads workspace configuration from:
```
~/.claude/plugins/bumba-notion/config/workspace-mapping.json
```

Required fields:
- `notionToken` - Notion API integration token
- `masterDatabases.projects` - Projects database ID
- `templatePageId` - Master template page ID

## Error Handling

### Graceful Degradation

If Notion integration fails, the E2B structure is still created:

```javascript
try {
  notionDashboardUrl = await this.createNotionDashboard(projectPath, config);
  results.steps.push({ name: 'create-notion-dashboard', success: true, url: notionDashboardUrl });
} catch (error) {
  results.errors.push(`Notion dashboard creation failed: ${error.message}`);
  results.steps.push({ name: 'create-notion-dashboard', success: false, error: error.message });
  // E2B structure still exists and is usable
}
```

### Common Errors

**1. Workspace Mapping Not Found**
```
Error: Notion workspace mapping not found. Run bumba-notion plugin setup first.
```

**Solution**: Ensure `~/.claude/plugins/bumba-notion/config/workspace-mapping.json` exists with valid credentials.

**2. Invalid GitHub Repo URL**
```
Error: GitHub repository URL is required for Notion dashboard creation
```

**Solution**: Provide a valid GitHub repo URL in the format `https://github.com/username/repo-name`.

**3. Notion API Error**
```
Error: Notion API error (401): Unauthorized
```

**Solution**: Check that your Notion integration token in `workspace-mapping.json` is valid and has access to the databases.

**4. Template Page Not Found**
```
Error: Notion API error (404): Could not find page with ID...
```

**Solution**: Verify the `templatePageId` in `workspace-mapping.json` points to an existing page.

## Verification

### Check Local Structure

```bash
# Verify E2B structure
ls -la .claude/config/
# Should see: bumba-sandbox-config.json, orchestrator-state.json, project-config.json

ls -la apps/sandbox_agent_working_dir/
# Should see: temp/, logs/, code/

# Check git initialization (if enabled)
git log
# Should see: "Initial commit - E2B Orchestrator project structure"
```

### Check Notion Dashboard

1. Open the dashboard URL provided in the success message
2. Verify the page title matches your project name
3. Check linked database views:
   - Tasks Kanban should be empty (filtered by your GitHub Repo)
   - Epics Table should be empty (filtered by your GitHub Repo)
   - Sprints Table should be empty (filtered by your GitHub Repo)
4. Open Projects Master database
5. Verify your project entry exists with:
   - Correct project name
   - Correct GitHub Repo URL
   - Today's start date
   - "active" status

## Troubleshooting

### Hook Not Triggering

**Symptoms**: E2B structure created but no Notion dashboard

**Debug Steps**:
```bash
# Check if hook is enabled
cat ~/.claude/hooks/on-project-init-complete.js | grep "enabled: true"

# Check hook logs (if logging enabled)
tail -f ~/.claude/logs/hooks.log
```

**Solution**: Restart Claude Code to reload hooks.

### Notion Integration Failing

**Debug Steps**:
```bash
# 1. Verify workspace mapping exists
cat ~/.claude/plugins/bumba-notion/config/workspace-mapping.json

# 2. Test Notion API token manually
curl -X GET https://api.notion.com/v1/users/me \
  -H "Authorization: Bearer ntn_..." \
  -H "Notion-Version: 2022-06-28"

# Expected: JSON response with user info
# Error: Check token validity
```

### Dashboard Created But Empty

**Symptoms**: Dashboard page exists but has no linked database views

**Cause**: Template page may not have linked databases set up correctly

**Solution**:
1. Verify template page has linked database views
2. Check that linked databases point to correct master databases
3. Ensure GitHub Repo property exists in all master databases

## Best Practices

### 1. Always Use GitHub Repo URL Format

✅ **Correct**:
```
https://github.com/username/repo-name
https://github.com/organization/project
```

❌ **Incorrect**:
```
github.com/username/repo-name  (missing https://)
git@github.com:username/repo.git  (SSH format)
username/repo-name  (incomplete)
```

### 2. Use Descriptive Project Names

- Use kebab-case: `my-awesome-app`
- Avoid special characters: `project-name` not `project!@#$name`
- Keep it concise: 2-4 words maximum

### 3. Initialize Git Early

Always enable "Git Init" feature to track changes from the beginning.

### 4. Verify Notion Setup First

Before running `/project-init` with Notion integration:
```bash
# Check plugin installation
ls ~/.claude/plugins/bumba-notion/

# Check workspace mapping
cat ~/.claude/plugins/bumba-notion/config/workspace-mapping.json
```

## Next Steps

After successful initialization:

### 1. Configure Environment
```bash
cp .env.template .env
# Edit .env with your API keys:
# - E2B_API_KEY
# - ANTHROPIC_API_KEY
# - GITHUB_TOKEN (if GitHub Integration enabled)
```

### 2. Create Product Requirements
```bash
/idea-requirements
# Creates PRD in docs/prd/
```

### 3. Plan Development Sprints
```bash
/spec-sprints
# Creates sprint plan from PRD
```

### 4. Sync GitHub Issues to Notion (Future)
```bash
/sync-github https://github.com/username/my-awesome-app
# Syncs existing GitHub issues to Notion tasks
```

### 5. Implement Features
```bash
/code-parallel #1 #2 #3
# Implements multiple features in parallel using E2B sandboxes
```

## Related Documentation

- **Plugin Overview**: `~/.claude/plugins/bumba-notion/README.md`
- **Schema Definitions**: `~/.claude/plugins/bumba-notion/config/schema-definitions.json`
- **Sync Rules**: `~/.claude/plugins/bumba-notion/config/sync-rules.json`
- **E2B Setup Guide**: `docs/e2b/SETUP.md` (created by /project-init)
- **E2B Commands**: `docs/e2b/COMMANDS.md` (created by /project-init)

## Support

For issues or questions:
1. Check this guide's troubleshooting section
2. Verify Phase 0 setup (manual Notion database creation)
3. Check hook logs for detailed error messages
4. Verify Notion API token permissions

---

**Last Updated**: January 15, 2026
**Plugin Version**: 1.0.0
**Integration Status**: Production Ready

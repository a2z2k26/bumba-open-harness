# Human Setup Guide - Phase 0

**Manual Notion Configuration Required Before Using Plugin**

## Overview

Before the bumba-notion plugin can create project dashboards automatically, you must complete Phase 0: manual creation of master databases and template page in Notion.

**Time Required**: 30-45 minutes
**Technical Level**: Beginner (no coding required)
**Prerequisites**: Notion account

## What You'll Create

Phase 0 establishes the foundation for all future projects:

1. **4 Master Databases** - Centralized data storage
   - Tasks Master (8 properties)
   - Epics Master (4 properties)
   - Sprints Master (5 properties)
   - Projects Master (4 properties)

2. **1 Template Page** - Blueprint for project dashboards
   - Contains 4 linked database views
   - Used by plugin to create new dashboards

3. **1 Integration** - API access for automation
   - Notion integration with API token
   - Connected to all databases

4. **1 Configuration File** - Stores IDs and credentials
   - `workspace-mapping.json`
   - Contains database IDs and API token

## Step-by-Step Instructions

### Step 1: Create Master Databases (15-20 minutes)

#### 1.1 Create Tasks Master Database

1. Open Notion
2. Click "+ New Page" in sidebar
3. Type: "Tasks Master"
4. Click "Database" → "Table - Full page"
5. Create 8 properties:

| Property Name | Type | Configuration |
|--------------|------|---------------|
| Task ID | Title | (default) |
| Status | Select | Options: backlog (gray), ready (blue), in_progress (yellow), review (purple), completed (green) |
| Sprint ID | Relation | Database: Sprints Master, Single property |
| Epic Name | Relation | Database: Epics Master, Single property |
| Priority | Number | Format: Number |
| GitHub Issue | URL | (default) |
| Started At | Date | (default) |
| Completed At | Date | (default) |

6. Create 2 views:
   - **Kanban**: Board view, group by Status, sort by Priority descending
   - **Ready Queue**: Table view, filter Status = ready, sort by Priority descending

#### 1.2 Create Epics Master Database

1. Click "+ New Page" in sidebar
2. Type: "Epics Master"
3. Click "Database" → "Table - Full page"
4. Create 4 properties:

| Property Name | Type | Configuration |
|--------------|------|---------------|
| Epic Name | Title | (default) |
| Status | Select | Options: planning (gray), in_progress (yellow), on_hold (orange), completed (green) |
| GitHub Repo | URL | (default) |
| Created At | Date | (default) |

5. Create 1 view:
   - **All Epics**: Table view, sort by Created At descending

#### 1.3 Create Sprints Master Database

1. Click "+ New Page" in sidebar
2. Type: "Sprints Master"
3. Click "Database" → "Table - Full page"
4. Create 5 properties:

| Property Name | Type | Configuration |
|--------------|------|---------------|
| Sprint ID | Title | (default) |
| Status | Select | Options: planned (gray), active (green), completed (blue) |
| Epic | Relation | Database: Epics Master, Single property |
| Start Date | Date | (default) |
| End Date | Date | (default) |

5. Create 2 views:
   - **All Sprints**: Table view, sort by Start Date descending
   - **Active Sprints**: Table view, filter Status = active, sort by Start Date ascending

#### 1.4 Create Projects Master Database

1. Click "+ New Page" in sidebar
2. Type: "Projects Master"
3. Click "Database" → "Table - Full page"
4. Create 4 properties:

| Property Name | Type | Configuration |
|--------------|------|---------------|
| Project Name | Title | (default) |
| GitHub Repo | URL | (default) |
| Start Date | Date | (default) |
| Status | Select | Options: ready (gray), active (green), complete (blue) |

5. Create 2 views:
   - **All Projects**: Table view, sort by Start Date descending
   - **Active Projects**: Table view, filter Status = active, sort by Start Date descending

### Step 2: Create Master Template Page (10-15 minutes)

#### 2.1 Create Template Page

1. Click "+ New Page" in sidebar
2. Type: "Project Dashboard Template"
3. Add content structure:

```
[Icon] [Title: Project Dashboard Template]

## Overview
This is the master template for project dashboards.

## Tasks
[Linked Database View → Tasks Master]
  - View: Kanban
  - Filter: GitHub Repo equals [This page's GitHub Repo property]

## Epics
[Linked Database View → Epics Master]
  - View: All Epics
  - Filter: GitHub Repo equals [This page's GitHub Repo property]

## Sprints
[Linked Database View → Sprints Master]
  - View: All Sprints
  - Filter: GitHub Repo equals [This page's GitHub Repo property]

## Ready Queue
[Linked Database View → Tasks Master]
  - View: Ready Queue
  - Filter: GitHub Repo equals [This page's GitHub Repo property]
```

#### 2.2 Add Linked Database Views

For each section:

1. Type `/linked` and press Enter
2. Select "Create linked database"
3. Choose the master database
4. Select the view type (Board for Tasks Kanban, Table for others)
5. Click "..." on the view → "Filter"
6. Add filter: GitHub Repo equals [current page property]

**Important**: The filters will be template variables. When the plugin duplicates this page, the filters will automatically reference the new project's GitHub Repo.

### Step 3: Create Notion Integration (5 minutes)

#### 3.1 Create Integration

1. Go to https://www.notion.so/my-integrations
2. Click "+ New integration"
3. Settings:
   - Name: "Bumba Notion Plugin"
   - Associated workspace: [Your workspace]
   - Type: Internal integration
   - Capabilities:
     - ✓ Read content
     - ✓ Update content
     - ✓ Insert content
4. Click "Submit"
5. Copy the "Internal Integration Token" (starts with `ntn_`)

#### 3.2 Connect Integration to Databases

For EACH of the 4 master databases and the template page:

1. Open the page/database
2. Click "..." menu (top right)
3. Click "Connections"
4. Click "+ Add connection"
5. Select "Bumba Notion Plugin"
6. Click "Confirm"

**Critical**: The integration must have access to all 5 items (4 databases + template page) or the plugin will fail.

### Step 4: Collect Database IDs (5 minutes)

#### 4.1 Get Database IDs

For each master database:

1. Open the database in Notion
2. Look at the URL in your browser:
   ```
   https://notion.so/12345678901234567890123456789012?v=...
                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                  This is the database ID (32 characters)
   ```
3. Copy the 32-character ID (before the `?v=` part)

Collect IDs for:
- Tasks Master → `tasks`
- Epics Master → `epics`
- Sprints Master → `sprints`
- Projects Master → `projects`

#### 4.2 Get Template Page ID

1. Open "Project Dashboard Template" page
2. Look at the URL:
   ```
   https://notion.so/Project-Dashboard-Template-12345678901234567890123456789012
                                                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                                 This is the page ID
   ```
3. Copy the 32-character ID

#### 4.3 Get Workspace ID (Optional)

1. Go to Settings & Members
2. Look at the URL:
   ```
   https://notion.so/settings/12345678901234567890123456789012
                               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                               This is the workspace ID
   ```
3. Copy the 32-character ID

### Step 5: Create Configuration File (5 minutes)

#### 5.1 Create workspace-mapping.json

Create a file with this structure:

```json
{
  "notionToken": "<notion-api-token>",
  "workspaceId": "YOUR_WORKSPACE_ID_HERE",
  "masterDatabases": {
    "tasks": "YOUR_TASKS_DB_ID_HERE",
    "epics": "YOUR_EPICS_DB_ID_HERE",
    "sprints": "YOUR_SPRINTS_DB_ID_HERE",
    "projects": "YOUR_PROJECTS_DB_ID_HERE"
  },
  "templatePageId": "YOUR_TEMPLATE_PAGE_ID_HERE"
}
```

#### 5.2 Fill In Values

Replace placeholders with actual values collected in Steps 3-4.

**Example** (with fake IDs):
```json
{
  "notionToken": "<notion-api-token>",
  "workspaceId": "2a60ab715bfa8022ad9dcc25b03de3c4",
  "masterDatabases": {
    "tasks": "b9e06ae0f6974be786641109e2962294",
    "epics": "9912c6eeff4f487b8bc2ea0f78ee6bc1",
    "sprints": "bb6ccdd0d1424ae5be842937c1431893",
    "projects": "2e90ab715bfa80bba454fb5feb118b4d"
  },
  "templatePageId": "97753a4eecb4489298cb8c8a17ec0155"
}
```

#### 5.3 Save Configuration

Save the file to:
```
~/.claude/plugins/bumba-notion/config/workspace-mapping.json
```

**Security Note**: This file contains your API token. Never commit it to version control. The plugin's `.gitignore` protects it automatically.

### Step 6: Verification (5 minutes)

#### 6.1 Check Database Structure

Open each master database and verify:
- ✓ Correct number of properties
- ✓ Correct property types
- ✓ Correct select options (with right colors)
- ✓ Relations point to correct databases
- ✓ Views exist with correct filters

#### 6.2 Check Template Page

Open template page and verify:
- ✓ Has 4 linked database views
- ✓ Each view shows correct database
- ✓ Filters are set (even if showing "empty")

#### 6.3 Check Integration Access

For each database and template page:
- ✓ Open page
- ✓ Check "..." → "Connections"
- ✓ Verify "Bumba Notion Plugin" is listed

#### 6.4 Test Configuration File

```bash
# Check file exists
cat ~/.claude/plugins/bumba-notion/config/workspace-mapping.json

# Verify JSON is valid
cat ~/.claude/plugins/bumba-notion/config/workspace-mapping.json | jq '.'

# Test API token
curl -X GET https://api.notion.com/v1/users/me \
  -H "Authorization: Bearer $(cat ~/.claude/plugins/bumba-notion/config/workspace-mapping.json | grep notionToken | cut -d'"' -f4)" \
  -H "Notion-Version: 2022-06-28"

# Expected: JSON with user info
# Error: Check token validity
```

## Phase 0 Checklist

Before proceeding to use the plugin:

- [ ] 4 master databases created with correct schemas
  - [ ] Tasks Master (8 properties, 2 views)
  - [ ] Epics Master (4 properties, 1 view)
  - [ ] Sprints Master (5 properties, 2 views)
  - [ ] Projects Master (4 properties, 2 views)
- [ ] Template page created with 4 linked database views
- [ ] Notion integration created
- [ ] Integration connected to all 4 databases and template page
- [ ] Database IDs collected
- [ ] Template page ID collected
- [ ] Workspace ID collected (optional)
- [ ] workspace-mapping.json created and saved to plugin config
- [ ] Configuration verified with curl test

## Common Mistakes

### 1. Wrong Property Types

**Problem**: Created "Status" as Text instead of Select

**Fix**: Delete property and recreate with correct type

### 2. Missing Relation Targets

**Problem**: Sprint ID relation created before Sprints database exists

**Fix**: Create target database first, then add relation

### 3. Filters Not Applied to Linked Views

**Problem**: Linked views show all data, not filtered

**Fix**: Click "..." on view → "Filter" → Add "GitHub Repo equals [page property]"

### 4. Integration Not Connected

**Problem**: Plugin fails with 401 Unauthorized

**Fix**: Go to each database → "..." → "Connections" → Add integration

### 5. Wrong Database ID Format

**Problem**: Copied full URL instead of just the ID

**Fix**: Extract only the 32-character ID (remove hyphens if present)

**Example**:
- ✅ Correct: `b9e06ae0f6974be786641109e2962294`
- ❌ Wrong: `https://notion.so/b9e06ae0-f697-4be7-8664-1109e2962294?v=...`
- ❌ Wrong: `b9e06ae0-f697-4be7-8664-1109e2962294`

## Next Steps

After completing Phase 0:

1. **Verify Setup**: Run the verification commands in Step 6.4
2. **Test Plugin**: Run `/project-init` with Notion Dashboard enabled
3. **Create First Project**: Follow the Quick Start guide
4. **Troubleshoot**: If issues occur, see TROUBLESHOOTING.md

## Detailed Setup Guides

For more comprehensive step-by-step guides with screenshots and detailed explanations, see:

```
/home/operator/Desktop/Bumba - Notion/01-MVP-EXECUTION/MANUAL-SETUP/
```

Available guides:
- `TASKS-DATABASE-SETUP.md` - Detailed Tasks Master setup
- `EPICS-DATABASE-SETUP.md` - Detailed Epics Master setup
- `SPRINTS-DATABASE-SETUP.md` - Detailed Sprints Master setup
- `PROJECTS-DATABASE-SETUP.md` - Detailed Projects Master setup
- `TEMPLATE-PAGE-SETUP.md` - Detailed template page creation
- `INTEGRATION-SETUP.md` - Detailed Notion integration setup
- `CONFIG-FILE-SETUP.md` - Detailed configuration file creation
- `VERIFICATION-CHECKLIST.md` - Comprehensive verification steps

## Time-Saving Tips

### Use Notion Templates

After creating the first database, you can duplicate it to save time:

1. Create Tasks Master fully
2. Duplicate it for Epics Master
3. Remove unneeded properties
4. Add new properties
5. Update select options

### Batch Connect Integration

Instead of connecting integration to each page individually:

1. Create integration first
2. Select all database pages in sidebar
3. Right-click → "Add connection" → Select integration
4. (Note: This may not work for all Notion plans)

### Keyboard Shortcuts

- `Cmd/Ctrl + N` - New page
- `Cmd/Ctrl + Shift + P` - Property settings
- `/linked` - Create linked database
- `/` - Command menu

## Support

If you encounter issues during Phase 0 setup:

1. **Re-read this guide** - Most issues are from missed steps
2. **Check Notion documentation** - https://notion.so/help/
3. **Verify with checklist** - Complete the Phase 0 Checklist above
4. **Test API access** - Run curl command in Step 6.4
5. **Review detailed guides** - See manual setup directory

---

**Phase 0 is complete when:**
- All verification checks pass ✓
- curl test returns user info ✓
- Checklist is 100% complete ✓

**Ready to proceed!** Continue with QUICK-START.md to use the plugin.

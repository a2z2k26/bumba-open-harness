---
name: notion/project
description: Create a Notion project dashboard linked to a GitHub repository
arguments:
  - name: action
    description: "Action to perform: create"
    required: true
  - name: repo
    description: "GitHub repo in owner/repo format"
    required: true
  - name: name
    description: "Project display name (defaults to repo name)"
    required: false
---

# /notion/project — Project Dashboard Management

Creates and manages Notion project dashboards linked to GitHub repositories.

## Usage

```
/notion/project create <owner/repo> [--name "Project Name"]
```

## Implementation

### Step 1: Parse Arguments

Extract from `$ARGUMENTS`:
- `action`: Required. Currently only `create` is supported.
- `repo`: Required. Format `owner/repo`.
- `--name`: Optional. Human-readable project name. Defaults to the repo name.

### Step 2: Load Configuration

Read the workspace config:
```
Read file: /opt/bumba-harness/agent-flat/agent/config/notion-bridge/workspace-config.json
```

### Step 3: Verify Repository Exists

Call `github:search_repositories` with query `repo:<owner>/<repo>` to confirm the repo exists and is accessible.

If not found, report error and stop.

### Step 4: Check for Existing Project

Call `Notion:notion-fetch` on the Projects database (`databases.projects` from config) and check if a project already exists for this repo.

If found, display existing project info and ask if user wants to proceed.

### Step 5: Create Project Entry

Call `Notion:notion-create-pages` with:
```
databaseId: <databases.projects from config>
properties:
  "Name": { "title": [{ "text": { "content": "<project-name>" } }] }
  "GitHub Repo": { "url": "https://github.com/<owner>/<repo>" }
  "Status": { "select": { "name": "active" } }
```

### Step 6: Verify Task Database Schema

Call `Notion:notion-fetch` on the Tasks database to check if required properties exist:
- GitHub Issue URL (URL type)
- GitHub Issue Number (Number type)
- GitHub Repo (URL type)

If any are missing, inform the user:
```
The Tasks database is missing required properties for GitHub sync:
  - <missing property> (<type>)

These properties need to be added to the Tasks Master database before syncing.
You can add them manually in Notion, or they may be created automatically on first sync
if the Notion integration has schema editing permissions.
```

### Step 7: Initialize Sync State

Read or create the sync state file. Add an entry for this repo:

```json
{
  "repos": {
    "<owner>/<repo>": {
      "lastSync": null,
      "notionProjectId": "<created-page-id>",
      "issues": {}
    }
  }
}
```

Write the updated sync state to the file path from config.

### Step 8: Display Result

```
Project Created: <project-name>

GitHub: https://github.com/<owner>/<repo>
Notion: <notion-page-url>
Database: Tasks Master (<databases.tasks>)

Next steps:
  1. Run /notion/sync <owner/repo> to sync existing issues
  2. Run /notion/status <owner/repo> to check sync state
```

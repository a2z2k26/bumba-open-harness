# Quick Start Guide

**Get up and running with bumba-notion integration in 5 minutes**

## Prerequisites

✅ **Before you begin, ensure you have:**

1. Completed Phase 0 manual setup:
   - ✓ Created 4 master databases in Notion (Tasks, Epics, Sprints, Projects)
   - ✓ Created master template page with linked database views
   - ✓ Created Notion integration and obtained API token
   - ✓ Saved configuration to `workspace-mapping.json`

2. Installed bumba-notion plugin:
   - ✓ Plugin directory exists at `~/.claude/plugins/bumba-notion/`
   - ✓ `workspace-mapping.json` copied to plugin config directory

## 30-Second Quick Start

```bash
# 1. Navigate to your project directory
cd ~/projects/my-new-project

# 2. Run project-init
/project-init

# 3. Answer prompts:
#    - Template: Node.js
#    - Features: ✓ Git Init, ✓ Notion Dashboard
#    - GitHub Repo: https://github.com/username/my-new-project
#    - Mode: Auto

# 4. Done! You now have:
#    - Complete E2B Orchestrator structure
#    - Notion project dashboard
#    - Git repository initialized
```

## Common Workflows

### Workflow 1: New Project with Notion

**Scenario**: Starting a brand new project

```bash
cd ~/projects/awesome-saas-app
/project-init

# Prompts:
# Name: awesome-saas-app (auto-detected from directory)
# Template: Node.js
# Features: Git Init, Auto-Sandbox, GitHub Integration, Notion Dashboard
# GitHub Repo: https://github.com/mycompany/awesome-saas-app
# Mode: Auto

# Result:
# ✅ Local structure created
# ✅ Git initialized
# ✅ Notion dashboard: https://notion.so/abc123...
```

### Workflow 2: Existing Project, Add Notion

**Scenario**: You have an existing project, want to add Notion tracking

```bash
cd ~/projects/existing-project

# Check if .claude/ exists
ls .claude/
# If exists, choose "Add E2B Structure" when prompted

/project-init

# Features: Notion Dashboard only
# GitHub Repo: https://github.com/username/existing-project

# Result:
# ✅ Notion dashboard created
# ✅ Existing files preserved
```

### Workflow 3: Multiple Projects Same Workspace

**Scenario**: Managing multiple projects in one Notion workspace

```bash
# Project 1
cd ~/projects/mobile-app
/project-init  # Enable Notion Dashboard
# GitHub: https://github.com/company/mobile-app

# Project 2
cd ~/projects/backend-api
/project-init  # Enable Notion Dashboard
# GitHub: https://github.com/company/backend-api

# Project 3
cd ~/projects/admin-portal
/project-init  # Enable Notion Dashboard
# GitHub: https://github.com/company/admin-portal

# Result:
# ✅ 3 separate dashboards in Notion
# ✅ All data in shared master databases
# ✅ Each dashboard filtered by its GitHub Repo
```

## Feature Selection Guide

### When to Enable Each Feature

**Git Init**
- ✅ Enable: New projects, want version control
- ❌ Skip: Existing git repos, monorepos

**Auto-Sandbox**
- ✅ Enable: Risky operations, production code
- ❌ Skip: Simple projects, rapid prototyping

**GitHub Integration**
- ✅ Enable: Team projects, CI/CD needed
- ❌ Skip: Personal projects, no GitHub

**Notion Dashboard**
- ✅ Enable: Project management needed
- ❌ Skip: Quick experiments, throwaway code

### Recommended Combinations

**Professional Team Project**
```
✓ Git Init
✓ Auto-Sandbox
✓ GitHub Integration
✓ Notion Dashboard
```

**Personal Side Project**
```
✓ Git Init
✓ Notion Dashboard
```

**Quick Experiment**
```
(none selected)
```

**Enterprise Production**
```
✓ Git Init
✓ Auto-Sandbox
✓ GitHub Integration
✓ Notion Dashboard
```

## Notion Dashboard Overview

### What You Get

After running `/project-init` with Notion Dashboard enabled, you get:

**1. Project Dashboard Page**
- Title: Your project name
- Location: Inside your Notion workspace
- Contains 4 linked database views

**2. Linked Database Views**

| View | Type | Shows |
|------|------|-------|
| Tasks Kanban | Board | Tasks grouped by status (backlog/ready/in_progress/review/completed) |
| Epics Table | Table | Features/epics for this project |
| Sprints Table | Table | Sprint planning and tracking |
| Ready Queue | Table | Tasks ready to start, sorted by priority |

**3. Projects Master Entry**
- Automatically created in Projects Master database
- Links to your dashboard page
- Tracks project metadata (name, repo, dates, status)

### How Filtering Works

All views show ONLY data for your project:
- Filter key: GitHub Repo URL
- Automatic: No manual filter setup needed
- Multiple projects: Each sees only its own data

**Example**: If you have 3 projects:
- Project A sees only Project A tasks/epics/sprints
- Project B sees only Project B tasks/epics/sprints
- Project C sees only Project C tasks/epics/sprints
- Master databases contain ALL data from all projects

## Verification Checklist

After running `/project-init`:

### Local Structure ✓

```bash
# Check directory structure
ls -la .claude/
# Expected: commands/, config/, hooks/, mcp-servers/, templates/

ls -la apps/sandbox_agent_working_dir/
# Expected: temp/, logs/, code/

# Check config files
cat .claude/config/project-config.json
# Expected: JSON with notionDashboard: true

# Check git (if enabled)
git status
# Expected: On branch main, nothing to commit, working tree clean
```

### Notion Dashboard ✓

1. **Open Dashboard URL** (from success message)
2. **Check Page Title** = Your project name
3. **Verify 4 Views Exist**:
   - ✓ Tasks Kanban (board view)
   - ✓ Epics Table (table view)
   - ✓ Sprints Table (table view)
   - ✓ Ready Queue (table view)
4. **Check Projects Database**:
   - ✓ Entry exists with your project name
   - ✓ GitHub Repo URL is correct
   - ✓ Start Date is today
   - ✓ Status is "active"

## Next Steps

### Immediate (Day 1)

```bash
# 1. Configure environment
cp .env.template .env
nano .env  # Add your API keys

# 2. Install dependencies (if Node.js)
npm install

# 3. Verify E2B setup
cat docs/e2b/SETUP.md
```

### Short-term (Week 1)

```bash
# 1. Create product requirements
/idea-requirements

# 2. Plan first sprint
/spec-sprints

# 3. Generate GitHub issues (if enabled)
/spec-issues

# 4. Start implementing
/code-parallel #1 #2
```

### Medium-term (Month 1)

```bash
# 1. Sync existing GitHub issues to Notion
/sync-github https://github.com/username/project

# 2. Track progress in Notion
# - Move tasks across Kanban board
# - Update epic status
# - Complete sprints

# 3. Iterate on features
# - Create tasks directly in Notion
# - Implement via /code-parallel
# - Track completion
```

## Common Questions

### Q: Can I disable Notion after project-init?

**A**: Yes. Notion dashboard remains accessible, but new data won't sync automatically. You can manually update or re-enable sync later.

### Q: Can I create multiple dashboards for one project?

**A**: Not recommended. Use one dashboard per GitHub repository for clean filtering. You can create views within the dashboard for different perspectives.

### Q: What if I don't have a GitHub repo yet?

**A**: Use a placeholder URL like `https://github.com/username/future-project-name`. Update it later in:
- `.claude/config/project-config.json`
- Notion Projects database entry

### Q: Can I use this without E2B Orchestrator?

**A**: Not currently. The integration is built into the `/project-init` command which creates E2B structure. Future versions may support standalone Notion project creation.

### Q: How do I update workspace configuration?

**A**: Edit `~/.claude/plugins/bumba-notion/config/workspace-mapping.json` and restart Claude Code.

### Q: What happens if Notion API is down?

**A**: E2B structure still gets created. Notion dashboard creation fails gracefully with error message. You can retry dashboard creation manually later.

## Troubleshooting Quick Fixes

### Issue: "Notion workspace mapping not found"

```bash
# Solution: Copy workspace-mapping.json to plugin
cp ~/Desktop/Bumba\ -\ Notion/workspace-mapping.json.json \
   ~/.claude/plugins/bumba-notion/config/workspace-mapping.json
```

### Issue: "Invalid GitHub repository URL"

```bash
# Solution: Use full HTTPS URL format
# ✅ Correct: https://github.com/username/repo-name
# ❌ Wrong: github.com/username/repo-name
# ❌ Wrong: git@github.com:username/repo.git
```

### Issue: Hook not triggering

```bash
# Solution: Restart Claude Code
# Then try again
/project-init
```

### Issue: Dashboard created but empty

```bash
# Solution: Check template page has linked databases
# 1. Open template page in Notion
# 2. Verify it has 4 linked database blocks
# 3. Ensure they point to correct master databases
```

## Resources

- **Full Integration Guide**: `PROJECT-INIT-INTEGRATION.md`
- **Plugin README**: `README.md`
- **Schema Reference**: `../config/schema-definitions.json`
- **Manual Setup**: `/home/operator/Desktop/Bumba - Notion/01-MVP-EXECUTION/MANUAL-SETUP/`

---

**Happy coding with integrated project management!** 🚀

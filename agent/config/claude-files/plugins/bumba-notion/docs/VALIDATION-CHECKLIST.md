# BUMBA-Notion Plugin Validation Checklist

Comprehensive validation checklist with 100 checks across all plugin features.

## Phase 1: Template Structure Validation (15 checks)

### Directory Structure
- [ ] 1. `.bumba-notion-plugin/` directory exists in project root
- [ ] 2. `.bumba-notion-plugin/config/` directory exists
- [ ] 3. `.bumba-notion-plugin/state/` directory exists
- [ ] 4. `.bumba-notion-plugin/logs/` directory exists
- [ ] 5. All directories have proper permissions (755)

### Configuration Files
- [ ] 6. `config/workspace-mapping.json` exists
- [ ] 7. `workspace-mapping.json` has valid JSON structure
- [ ] 8. `workspace-mapping.json` includes all required fields (notion_token, github_token, databases)
- [ ] 9. `config/schema-definitions.json` exists
- [ ] 10. `schema-definitions.json` matches expected schema structure

### Git Integration
- [ ] 11. `.gitignore` includes `.bumba-notion-plugin/` entries
- [ ] 12. `workspace-mapping.json` is in `.gitignore` (secrets protection)
- [ ] 13. `state/` directory is in `.gitignore` (ephemeral data)
- [ ] 14. `logs/` directory is in `.gitignore`
- [ ] 15. Git repository is properly initialized if using git

---

## Phase 2: Plugin Configuration Validation (15 checks)

### Plugin Manifest
- [ ] 16. `plugin.json` exists in plugin root
- [ ] 17. `plugin.json` has valid JSON structure
- [ ] 18. Plugin name is "bumba-notion"
- [ ] 19. Version follows semver format (e.g., "1.0.0")
- [ ] 20. Description is present and accurate

### Dependencies
- [ ] 21. Required MCP servers listed: "notion", "github", "bumba-memory"
- [ ] 22. Claude Code version requirement specified (>=2.0.0)
- [ ] 23. All required MCP servers are installed and enabled

### Commands
- [ ] 24. Commands array includes "commands/project-init.md"
- [ ] 25. Commands array includes "commands/sync-github.md"
- [ ] 26. Command files exist at specified paths
- [ ] 27. Command files have valid markdown structure
- [ ] 28. Command frontmatter includes required fields (name, description)

### Hooks
- [ ] 29. Hooks array includes session-start hook
- [ ] 30. Hooks array includes session-end hook

---

## Phase 3: Project Init Command Validation (15 checks)

### Command Execution
- [ ] 31. `/project-init` command is recognized by Claude Code
- [ ] 32. Command prompts for project name
- [ ] 33. Command prompts for GitHub repository URL
- [ ] 34. Command prompts for Notion workspace selection

### Template Creation
- [ ] 35. `.bumba-notion-plugin/` directory created successfully
- [ ] 36. `config/workspace-mapping.json` created with correct structure
- [ ] 37. Notion token stored correctly in workspace-mapping.json
- [ ] 38. GitHub token stored correctly in workspace-mapping.json
- [ ] 39. Database IDs populated correctly

### Notion Setup
- [ ] 40. Tasks Master database created in Notion
- [ ] 41. Epics Master database created in Notion
- [ ] 42. Sprints Master database created in Notion
- [ ] 43. Projects Master database created in Notion
- [ ] 44. All databases have correct properties (Title, Status, Relations)
- [ ] 45. All databases have correct views (Kanban, Ready Queue, etc.)

---

## Phase 4: GitHub Sync Command Validation (20 checks)

### Command Execution
- [ ] 46. `/sync-github` command is recognized by Claude Code
- [ ] 47. Command reads workspace-mapping.json successfully
- [ ] 48. Command connects to GitHub API successfully
- [ ] 49. Command connects to Notion API successfully
- [ ] 50. Command handles missing workspace-mapping.json gracefully

### Issue Fetching
- [ ] 51. All open issues fetched from GitHub repository
- [ ] 52. Issues with proper labels fetched (epic, milestone)
- [ ] 53. Issue body content parsed correctly
- [ ] 54. Issue metadata extracted (number, title, labels, state)
- [ ] 55. Closed issues excluded from sync

### Notion Creation
- [ ] 56. Epic pages created for issues with "epic" label
- [ ] 57. Sprint pages created for issues with "milestone" label
- [ ] 58. Task pages created for regular issues
- [ ] 59. All pages have correct properties populated
- [ ] 60. GitHub Issue URL stored in "GitHub Issue" property

### Status Mapping
- [ ] 61. Open issues → "backlog" status
- [ ] 62. In Progress issues → "in_progress" status
- [ ] 63. Review issues → "review" status
- [ ] 64. Closed issues → "completed" status
- [ ] 65. Custom status labels mapped correctly

### Sync State
- [ ] 66. `state/sync-state.json` created after sync
- [ ] 67. Sync state includes lastSync timestamp
- [ ] 68. Sync state includes projectName
- [ ] 69. Sync state includes totalIssuesCreated count
- [ ] 70. Sync state includes dashboardUrl

---

## Phase 5: Auto-Sync Hooks Validation (15 checks)

### Session Start Hook
- [ ] 71. `hooks/session-start.js` file exists
- [ ] 72. Hook registered in plugin.json with event "session-start"
- [ ] 73. Hook detects BUMBA-Notion projects (checks for `.bumba-notion-plugin/`)
- [ ] 74. Hook exits silently for non-BUMBA-Notion projects
- [ ] 75. Hook loads sync state from `state/sync-state.json`
- [ ] 76. Hook displays last sync timestamp
- [ ] 77. Hook displays tasks synced count
- [ ] 78. Hook displays project name
- [ ] 79. Hook detects stale sync (>1 hour old)
- [ ] 80. Hook displays warning for stale sync

### Session End Hook
- [ ] 81. `hooks/session-end.js` file exists
- [ ] 82. Hook registered in plugin.json with event "session-end"
- [ ] 83. Hook detects BUMBA-Notion projects
- [ ] 84. Hook exits silently for non-BUMBA-Notion projects
- [ ] 85. Hook displays final sync summary

---

## Phase 6: Dependency Parsing Validation (10 checks)

### Schema Updates
- [ ] 86. Dependencies property exists in Tasks Master schema
- [ ] 87. Dependencies property is relation type
- [ ] 88. Dependencies property references "tasks" database (self-relation)
- [ ] 89. Dependencies property allows multiple relations (single_property: false)

### Dependency Detection
- [ ] 90. Parser detects "Depends on #123" format
- [ ] 91. Parser detects "Blocked by #456" format
- [ ] 92. Parser detects "Requires #789" format
- [ ] 93. Parser extracts issue numbers correctly
- [ ] 94. Dependencies stored as relations in Notion

### Ready Queue Filter
- [ ] 95. Ready Queue view filters by Status = "ready"
- [ ] 96. Ready Queue checks if all dependency tasks are completed
- [ ] 97. Tasks with incomplete dependencies excluded from Ready Queue
- [ ] 98. Tasks with no dependencies appear in Ready Queue
- [ ] 99. Tasks with all dependencies completed appear in Ready Queue

---

## Phase 7: End-to-End Testing (1 check)

### Complete Workflow
- [ ] 100. Complete workflow from project init → sync → hooks → dependencies works seamlessly

---

## Validation Score

**Total Checks:** 100
**Passed:** ___
**Failed:** ___
**Skipped:** ___

**Pass Rate:** ____%

---

## Notes

Use this checklist during:
- Initial plugin setup validation
- After making changes to plugin code
- Before releasing new plugin versions
- When troubleshooting issues
- During code reviews

Each check should be marked as:
- ✅ Passed
- ❌ Failed (with reason in notes)
- ⏭️ Skipped (with reason in notes)

---

## Test Data Requirements

To properly validate all checks, you need:

1. **Test GitHub Repository**
   - At least 10 open issues
   - At least 2 issues with "epic" label
   - At least 2 issues with "milestone" label
   - At least 3 issues with dependency references in body

2. **Test Notion Workspace**
   - Empty workspace or dedicated test page
   - API token with full permissions
   - Ability to create databases and pages

3. **Test Project Directory**
   - Git repository (optional but recommended)
   - Write permissions
   - Space for `.bumba-notion-plugin/` directory

---

## Automation

Some checks can be automated with scripts:

```bash
# Check directory structure (checks 1-4)
test -d .bumba-notion-plugin && \
test -d .bumba-notion-plugin/config && \
test -d .bumba-notion-plugin/state && \
test -d .bumba-notion-plugin/logs && \
echo "✅ Directory structure valid"

# Check configuration files (checks 6, 9)
test -f .bumba-notion-plugin/config/workspace-mapping.json && \
test -f .bumba-notion-plugin/config/schema-definitions.json && \
echo "✅ Configuration files exist"

# Validate JSON structure (checks 7, 10, 17)
jq empty .bumba-notion-plugin/config/workspace-mapping.json && \
jq empty .bumba-notion-plugin/config/schema-definitions.json && \
jq empty plugin.json && \
echo "✅ All JSON files valid"

# Check .gitignore entries (checks 11-14)
grep -q ".bumba-notion-plugin/config/workspace-mapping.json" .gitignore && \
grep -q ".bumba-notion-plugin/state/" .gitignore && \
grep -q ".bumba-notion-plugin/logs/" .gitignore && \
echo "✅ .gitignore configured correctly"
```

---

## Manual Testing Scenarios

### Scenario 1: Fresh Project Init
1. Run `/project-init` in empty directory
2. Verify all databases created in Notion
3. Verify workspace-mapping.json populated
4. Run `/sync-github` to sync issues
5. Verify sync state created

### Scenario 2: Session Lifecycle
1. Start new Claude Code session in BUMBA-Notion project
2. Verify session-start hook displays sync status
3. Make changes (run sync, etc.)
4. End Claude Code session
5. Verify session-end hook displays summary

### Scenario 3: Dependency Parsing
1. Create GitHub issue with "Depends on #123" in body
2. Run `/sync-github`
3. Verify task created in Notion
4. Verify Dependencies relation populated
5. Verify Ready Queue excludes task if #123 not completed

### Scenario 4: Stale Sync Detection
1. Run `/sync-github`
2. Wait >1 hour (or manually edit sync-state.json timestamp)
3. Start new Claude Code session
4. Verify session-start hook displays stale sync warning
5. Run `/sync-github` to refresh

---

**Last Updated:** Auto-generated by autonomous development agent
**Version:** 1.0
**Plugin:** bumba-notion v1.0.0

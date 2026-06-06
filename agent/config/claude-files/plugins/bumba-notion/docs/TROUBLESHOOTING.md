# Troubleshooting Guide

**Quick diagnostics and solutions for common issues**

## Diagnostic Commands

Run these first to identify the issue:

```bash
# 1. Check plugin installation
ls -la ~/.claude/plugins/bumba-notion/

# 2. Verify workspace configuration exists
cat ~/.claude/plugins/bumba-notion/config/workspace-mapping.json

# 3. Check hook is present and enabled
grep "enabled: true" ~/.claude/hooks/on-project-init-complete.js

# 4. Verify Notion API token
curl -X GET https://api.notion.com/v1/users/me \
  -H "Authorization: Bearer $(cat ~/.claude/plugins/bumba-notion/config/workspace-mapping.json | grep notionToken | cut -d'"' -f4)" \
  -H "Notion-Version: 2022-06-28"
```

## Error Messages & Solutions

### 1. "Notion workspace mapping not found"

**Full Error**:
```
Error: Notion workspace mapping not found. Run bumba-notion plugin setup first.
```

**Cause**: The `workspace-mapping.json` file doesn't exist in the plugin config directory.

**Solution**:
```bash
# Copy workspace-mapping.json to plugin config
cp /home/operator/Desktop/Bumba\ -\ Notion/workspace-mapping.json.json \
   ~/.claude/plugins/bumba-notion/config/workspace-mapping.json

# Verify it exists
cat ~/.claude/plugins/bumba-notion/config/workspace-mapping.json
```

**Prevention**: Always ensure Phase 0 setup is complete before running `/project-init`.

---

### 2. "Invalid workspace mapping configuration"

**Full Error**:
```
Error: Invalid workspace mapping configuration
```

**Cause**: The `workspace-mapping.json` file is missing required fields.

**Solution**:
```bash
# Check current configuration
cat ~/.claude/plugins/bumba-notion/config/workspace-mapping.json

# Required fields:
# - notionToken
# - masterDatabases (with: tasks, epics, sprints, projects)
# - templatePageId

# Fix by editing the file or re-copying from source
nano ~/.claude/plugins/bumba-notion/config/workspace-mapping.json
```

**Valid Structure**:
```json
{
  "notionToken": "ntn_...",
  "workspaceId": "...",
  "masterDatabases": {
    "tasks": "...",
    "epics": "...",
    "sprints": "...",
    "projects": "..."
  },
  "templatePageId": "..."
}
```

---

### 3. "GitHub repository URL is required"

**Full Error**:
```
Error: GitHub repository URL is required for Notion dashboard creation
```

**Cause**: You enabled Notion Dashboard but didn't provide a GitHub repo URL.

**Solution**: The `/project-init` command should prompt for GitHub repo when Notion Dashboard is enabled. If it didn't:

```bash
# Edit project-config.json manually
nano .claude/config/project-config.json

# Add githubRepo field:
{
  "options": {
    "notionDashboard": true,
    "githubRepo": "https://github.com/username/repo-name"
  }
}

# Then manually trigger the hook
node ~/.claude/hooks/on-project-init-complete.js
```

---

### 4. "Notion API error (401): Unauthorized"

**Full Error**:
```
Error: Notion API error (401): Unauthorized
```

**Cause**: Notion API token is invalid or expired.

**Solution**:
```bash
# 1. Test token manually
curl -X GET https://api.notion.com/v1/users/me \
  -H "Authorization: Bearer <notion-api-token>" \
  -H "Notion-Version: 2022-06-28"

# If error, regenerate token:
# 1. Go to https://www.notion.so/my-integrations
# 2. Click on your integration
# 3. Click "Show" under Internal Integration Token
# 4. Copy the new token
# 5. Update workspace-mapping.json

nano ~/.claude/plugins/bumba-notion/config/workspace-mapping.json
# Update notionToken field
```

---

### 5. "Notion API error (404): Could not find page"

**Full Error**:
```
Error: Notion API error (404): Could not find page with ID...
```

**Cause**: The `templatePageId` in `workspace-mapping.json` doesn't exist or integration doesn't have access.

**Solution**:
```bash
# 1. Verify template page exists in Notion
# Open: https://notion.so/YOUR_TEMPLATE_PAGE_ID

# 2. Ensure integration has access to the page
# In Notion:
# - Open template page
# - Click "..." menu
# - Click "Connections"
# - Add your integration

# 3. Verify templatePageId in config
cat ~/.claude/plugins/bumba-notion/config/workspace-mapping.json | grep templatePageId

# 4. Update if incorrect
nano ~/.claude/plugins/bumba-notion/config/workspace-mapping.json
```

---

### 6. "Notion API error (400): Invalid property value"

**Full Error**:
```
Error: Notion API error (400): Invalid property value for 'Status'
```

**Cause**: Database schema doesn't match expected structure (e.g., "active" status doesn't exist in Projects database).

**Solution**:
```bash
# 1. Check Projects database schema in Notion
# Verify Status property has these options:
# - ready (gray)
# - active (green)
# - complete (blue)

# 2. If options are different, update the hook code or database
# Option A: Update database to match schema-definitions.json
# Option B: Update hook code to match your database

# To update hook:
nano ~/.claude/hooks/on-project-init-complete.js
# Find notionCreateProjectEntry method
# Change 'active' to match your database options
```

---

### 7. Hook not triggering at all

**Symptoms**: E2B structure created, but no Notion dashboard, no error message.

**Cause**: Hook may not be registered or enabled.

**Solution**:
```bash
# 1. Check hook file exists
ls -la ~/.claude/hooks/on-project-init-complete.js

# 2. Verify hook is enabled
grep "enabled: true" ~/.claude/hooks/on-project-init-complete.js

# 3. Check hook trigger
grep "watch:" ~/.claude/hooks/on-project-init-complete.js
# Should show: watch: '.claude/project-config.json'

# 4. Restart Claude Code to reload hooks
# (Use your IDE/CLI restart method)

# 5. Try again
cd ~/projects/test-project
/project-init
```

---

### 8. Dashboard created but views are empty

**Symptoms**: Dashboard page exists in Notion, but linked database views show no data.

**Cause 1**: Template page doesn't have linked database views set up.

**Solution**:
```bash
# 1. Open template page in Notion
# URL: https://notion.so/YOUR_TEMPLATE_PAGE_ID

# 2. Check for 4 linked database blocks:
#    - Tasks Kanban
#    - Epics Table
#    - Sprints Table
#    - Ready Queue

# 3. If missing, add linked database views:
#    - /linked (slash command in Notion)
#    - Select "Link to database"
#    - Choose master database
#    - Select view type (Board/Table)

# 4. Add filters to each view:
#    - Filter: GitHub Repo = [current page GitHub Repo property]
```

**Cause 2**: Master databases are empty.

**Solution**:
```bash
# This is expected for new projects
# Views will populate as you:
# - Create tasks in Notion
# - Sync GitHub issues with /sync-github
# - Work on the project
```

---

### 9. Multiple projects showing in one dashboard

**Symptoms**: Dashboard shows tasks/epics from other projects.

**Cause**: Linked database views don't have GitHub Repo filters applied.

**Solution**:
```bash
# In Notion, for each linked database view:
# 1. Click "..." menu on view
# 2. Click "Filter"
# 3. Add filter:
#    Property: GitHub Repo
#    Condition: equals
#    Value: [Your project's GitHub URL]

# Or recreate dashboard:
# 1. Delete incorrect dashboard
# 2. Delete Projects database entry
# 3. Run /project-init again
```

---

### 10. "Failed to parse Notion API response"

**Full Error**:
```
Error: Failed to parse Notion API response: Unexpected token...
```

**Cause**: Notion API returned non-JSON response (possibly HTML error page).

**Solution**:
```bash
# 1. Check Notion API status
curl https://status.notion.so/

# 2. Test API directly
curl -X GET https://api.notion.com/v1/users/me \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Notion-Version: 2022-06-28" \
  -v  # verbose output

# 3. Check if you're hitting rate limits
# Notion API limits:
# - 3 requests per second
# - Wait 5 seconds and retry

# 4. If API is down, wait and retry later
```

---

## Integration-Specific Issues

### Issue: Project-config.json missing notionDashboard field

**Solution**:
```bash
# Edit project-config.json
nano .claude/config/project-config.json

# Add to options:
{
  "options": {
    "notionDashboard": true,
    "githubRepo": "https://github.com/username/repo"
  }
}
```

---

### Issue: Hook runs but createNotionDashboard not called

**Debug**:
```bash
# Check config structure
cat .claude/config/project-config.json | jq '.options.notionDashboard'
# Should output: true

# Check hook logic
grep -A 5 "notionDashboard" ~/.claude/hooks/on-project-init-complete.js

# Expected:
# if (config.options?.notionDashboard) {
#   notionDashboardUrl = await this.createNotionDashboard(projectPath, config);
# }
```

---

### Issue: Dashboard URL not showing in success message

**Solution**:
```bash
# Check if notionDashboardUrl was returned
# Look for console.log in hook output

# Manual dashboard URL construction:
# Format: https://notion.so/{pageId without hyphens}

# Example:
# Page ID: 97753a4e-ecb4-4892-98cb-8c8a17ec0155
# URL: https://notion.so/97753a4eecb4489298cb8c8a17ec0155
```

---

## Prevention Best Practices

### 1. Verify Phase 0 Setup Before Starting

```bash
# Checklist:
[ ] 4 master databases created in Notion
[ ] Template page created with linked views
[ ] Notion integration created
[ ] API token obtained
[ ] workspace-mapping.json created
[ ] workspace-mapping.json copied to plugin config
```

### 2. Test Configuration Before Project Init

```bash
# Test Notion API access
curl -X GET https://api.notion.com/v1/users/me \
  -H "Authorization: Bearer $(cat ~/.claude/plugins/bumba-notion/config/workspace-mapping.json | grep notionToken | cut -d'"' -f4)" \
  -H "Notion-Version: 2022-06-28"

# Expected: JSON with user info
# Error: Fix token before proceeding
```

### 3. Use Valid GitHub URLs

```bash
# ✅ Valid formats:
https://github.com/username/repo-name
https://github.com/organization/project-name

# ❌ Invalid formats:
github.com/username/repo  (missing https://)
git@github.com:username/repo.git  (SSH format)
username/repo  (incomplete)
```

### 4. Keep workspace-mapping.json Updated

```bash
# When you:
# - Create new master databases
# - Change template page
# - Regenerate API token

# Update:
nano ~/.claude/plugins/bumba-notion/config/workspace-mapping.json
```

---

## Debugging Tools

### Enable Verbose Hook Logging

Edit `~/.claude/hooks/on-project-init-complete.js`:

```javascript
// Add at the start of execute() method
console.log('[DEBUG] Config:', JSON.stringify(config, null, 2));
console.log('[DEBUG] notionDashboard enabled:', config.options?.notionDashboard);
console.log('[DEBUG] githubRepo:', config.options?.githubRepo);
```

### Test Notion API Methods Directly

Create a test script:

```javascript
// test-notion-api.js
const fs = require('fs');
const path = require('path');

const workspaceMapping = JSON.parse(fs.readFileSync(
  path.join(process.env.HOME, '.claude/plugins/bumba-notion/config/workspace-mapping.json'),
  'utf8'
));

console.log('Notion Token:', workspaceMapping.notionToken.substring(0, 10) + '...');
console.log('Template Page ID:', workspaceMapping.templatePageId);
console.log('Projects DB ID:', workspaceMapping.masterDatabases.projects);

// Test API connection
const https = require('https');
const options = {
  hostname: 'api.notion.com',
  port: 443,
  path: '/v1/users/me',
  method: 'GET',
  headers: {
    'Authorization': `Bearer ${workspaceMapping.notionToken}`,
    'Notion-Version': '2022-06-28'
  }
};

https.request(options, (res) => {
  let data = '';
  res.on('data', (chunk) => { data += chunk; });
  res.on('end', () => {
    console.log('API Response:', JSON.parse(data));
  });
}).end();
```

Run:
```bash
node test-notion-api.js
```

---

## Getting Help

If issues persist:

1. **Collect diagnostic information**:
   ```bash
   # System info
   echo "OS: $(uname -s)"
   echo "Claude Code Version: $(claude --version)"

   # Configuration
   ls -la ~/.claude/plugins/bumba-notion/
   cat ~/.claude/plugins/bumba-notion/config/workspace-mapping.json | jq 'del(.notionToken)'

   # Hook status
   grep "enabled" ~/.claude/hooks/on-project-init-complete.js
   ```

2. **Check documentation**:
   - `PROJECT-INIT-INTEGRATION.md` - Full integration guide
   - `QUICK-START.md` - Usage examples
   - `README.md` - Plugin overview

3. **Review logs**:
   - Hook execution logs (if enabled)
   - Claude Code debug logs
   - Notion API response errors

4. **Manual verification**:
   - Test Notion API token with curl
   - Verify database IDs in Notion
   - Check template page structure

---

**Most issues are resolved by:**
1. Verifying Phase 0 setup is complete
2. Checking workspace-mapping.json is valid
3. Ensuring Notion integration has access to databases/pages
4. Using correct GitHub URL format
5. Restarting Claude Code to reload hooks

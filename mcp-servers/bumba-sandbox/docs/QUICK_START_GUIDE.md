# E2B Workflow - Quick Start Guide

**Get started with Bumba Sandbox multi-agent orchestration in 10 minutes**

---

## Prerequisites

- Node.js 18+ installed
- Claude Code installed
- GitHub account with repository access
- E2B account (free tier: 100 hours/month)
- Anthropic API key

---

## Step 1: Initial Setup (2 minutes)

### 1.1 Install Dependencies

```bash
cd /path/to/your/project
npm install
```

### 1.2 Configure Environment

Copy the environment template:

```bash
cp .env.example .env
```

Edit `.env` and add your credentials:

```bash
# Required
E2B_API_KEY=your_e2b_api_key_here
GITHUB_TOKEN=your_github_token_here
ANTHROPIC_API_KEY=your_anthropic_api_key_here

# Repository Configuration
GITHUB_REPO_OWNER=your-username
GITHUB_REPO_NAME=your-repo-name
```

**Getting API Keys**:
- **E2B API Key**: Sign up at [e2b.dev](https://e2b.dev) → Dashboard → API Keys
- **GitHub Token**: GitHub Settings → Developer Settings → Personal Access Tokens → Generate (needs `repo` scope)
- **Anthropic API Key**: [console.anthropic.com](https://console.anthropic.com) → API Keys

### 1.3 Build the Project

```bash
npm run build
```

### 1.4 Configure Claude Desktop

Add the MCP server to Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "bumba-sandbox": {
      "command": "node",
      "args": ["/path/to/your/project/dist/mcp-servers/bumba-sandbox.js"],
      "env": {
        "E2B_API_KEY": "your_e2b_api_key",
        "GITHUB_TOKEN": "your_github_token",
        "ANTHROPIC_API_KEY": "your_anthropic_api_key",
        "GITHUB_REPO_OWNER": "your-username",
        "GITHUB_REPO_NAME": "your-repo"
      }
    }
  }
}
```

Restart Claude Desktop.

---

## Step 2: Your First Feature (3 minutes)

### 2.1 Create a GitHub Issue

Create an issue in your repository:

```
Title: Add user authentication

Description:
Implement JWT-based authentication system

Acceptance Criteria:
- [ ] Login endpoint
- [ ] Token generation
- [ ] Token verification
- [ ] Logout endpoint

Labels: feature, backend
```

Note the issue number (e.g., #42)

### 2.2 Implement the Feature

In Claude Code, run:

```
/implement-feature #42 --local
```

**What happens**:
1. Creates git worktree for the feature
2. Analyzes issue requirements
3. Generates implementation plan
4. Implements the feature
5. Writes tests
6. Runs tests

**Time**: ~8 minutes for typical feature

### 2.3 Create Pull Request

```
/create-pull-request #42
```

**What happens**:
1. Runs pre-flight checks (tests, lint)
2. Generates PR title and description
3. Creates PR on GitHub

Done! Your first feature is complete.

---

## Step 3: Try Sandbox Mode (2 minutes)

Sandbox mode runs in isolated E2B environment for safety:

```
/implement-feature #43 --sandbox
```

**Benefits**:
- Complete isolation from your machine
- Reproducible environment
- Safe for untrusted code
- Automatic cleanup

**Cost**: ~$0.09 per feature (E2B free tier: first 100 hours free)

---

## Step 4: Parallel Implementation (3 minutes)

Implement multiple features at once:

```
/parallel-implement-features #44 #45 #46 #47 #48 --strategy max-speed
```

**What happens**:
1. Analyzes dependencies between issues
2. Plans resource allocation
3. Spawns agents in parallel
4. Auto-cascades dependent features
5. Monitors progress in real-time

**Speedup**: 4.7x faster than sequential for independent features

---

## Common Commands

### Feature Implementation
```bash
# Local mode (fast, uses your machine)
/implement-feature #42 --local

# Sandbox mode (isolated E2B environment)
/implement-feature #42 --sandbox

# Auto mode (system decides based on issue)
/implement-feature #42 --auto
```

### Monitoring
```bash
# Show status of all features
/show-status

# Show sandbox-specific status
/sandbox-status

# Show orchestration status
/orchestrator-status
```

### Testing
```bash
# Test specific feature
/test #42

# Test all active features
/test-all
```

### Cost Management
```bash
# View cost report
/cost-report today

# Check budget status
/config get budgetLimit
```

### Cleanup
```bash
# Cleanup idle sandboxes
/cleanup-sandboxes

# List templates
/list-sandbox-templates
```

---

## Quick Troubleshooting

### "E2B API key not found"
- Check `.env` file has `E2B_API_KEY`
- Restart Claude Desktop after editing config

### "GitHub token invalid"
- Verify token has `repo` scope
- Generate new token if expired

### "Rate limit exceeded"
- GitHub API: Wait 1 hour or use authenticated requests
- E2B: Check monthly quota (100 hours free)

### "Sandbox failed to start"
- Check E2B dashboard for quota
- Try local mode: `/implement-feature #42 --local`

### "Tests failing"
- Review test output
- Fix issues manually in worktree
- Re-run: `/test #42`

---

## Next Steps

1. **Read Workflows Guide**: See `WORKFLOW_TUTORIALS.md` for advanced patterns
2. **Set Up Templates**: Create custom templates for faster startup (see `TEMPLATE_GUIDE.md`)
3. **Configure Budget**: Set monthly limits (see `COST_MANAGEMENT.md`)
4. **Explore Commands**: See `COMMANDS_REFERENCE.md` for all 41 commands

---

## Pro Tips

### Use Templates for Speed
First time using Node.js stack:
```bash
/create-sandbox-template node-typescript
```

Then all future features start in 0.2s instead of 2 minutes!

### Monitor Costs
Check daily:
```bash
/cost-report today
```

### Parallel Everything
For related features, use dependencies:
```markdown
# Issue #45
Depends on #44

# Issue #46
Depends on #44, #45
```

Then:
```bash
/parallel-implement-features #44 #45 #46
```

System auto-cascades as dependencies complete!

### Set Budget Alerts
```bash
/config set budgetLimit 50.00
```

Get warnings at 80% and 90%, hard stop at 100%.

---

## Getting Help

- **Documentation**: `/path/to/project/docs/e2b/`
- **Command Help**: Type `/help` in Claude Code
- **Issues**: Report bugs at GitHub repo
- **Community**: Join Discord/Slack (if applicable)

---

**You're ready!** Start with local mode, experiment with sandbox mode, then scale with parallel execution.

**Time to First Feature**: ~15 minutes (including setup)
**Time per Feature**: ~8 minutes (local) or ~8.5 minutes (sandbox)
**Cost**: $0.09 per feature

Happy orchestrating! 🚀

# Bumba Sandbox Orchestrator Setup Guide

This guide will walk you through setting up the Bumba Sandbox multi-agent orchestration system for Claude Code.

## Prerequisites

- Node.js 18+ and npm
- Claude Code installed
- GitHub account
- E2B account (for sandbox features)
- Anthropic API key (for Claude API access)

## Step 1: Install Dependencies

From the project root directory:

```bash
npm install
```

This will install:
- `e2b` - E2B SDK for sandbox orchestration
- `@octokit/rest` - GitHub API client
- `@modelcontextprotocol/sdk` - Model Context Protocol SDK
- `dotenv` - Environment variable management
- `winston` - Logging infrastructure
- TypeScript and development dependencies

## Step 2: Obtain API Keys

### E2B API Key

1. Go to [https://e2b.dev/](https://e2b.dev/)
2. Sign up for an account (free tier available)
3. Navigate to your dashboard
4. Click "API Keys" in the sidebar
5. Create a new API key
6. Copy the key (starts with `e2b_`)

**Free Tier**: 100 hours/month of sandbox usage

### Anthropic API Key

1. Go to [https://console.anthropic.com/](https://console.anthropic.com/)
2. Sign in or create an account
3. Navigate to "API Keys"
4. Create a new API key
5. Copy the key (is provided by Anthropic)

**Note**: Claude API is used for agent operations. Costs vary by model used.

### GitHub Personal Access Token

1. Go to [https://github.com/settings/tokens](https://github.com/settings/tokens)
2. Click "Generate new token" → "Generate new token (classic)"
3. Give it a descriptive name (e.g., "Bumba Sandbox Orchestrator")
4. Select the following scopes:
   - ✅ `repo` (full control of private repositories)
   - ✅ `workflow` (if using GitHub Actions)
   - ✅ `read:org` (if working with organization repositories)
5. Click "Generate token"
6. Copy the token (is a GitHub token)

**Security**: Store this token securely. It provides access to your repositories.

## Step 3: Configure Environment Variables

1. Copy the template file:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and replace the placeholder values:

   ```bash
   # E2B API Key (required for sandbox features)
   E2B_API_KEY=<e2b-api-key>

   # Anthropic API Key (required for Claude agents)
   ANTHROPIC_API_KEY=<anthropic-api-key>

   # GitHub Token (required for issue/PR automation)
   GITHUB_TOKEN=<github-token>

   # GitHub Repository (required)
   GITHUB_REPO_OWNER=your_github_username
   GITHUB_REPO_NAME=your_repository_name
   ```

3. Verify your `.env` file is in `.gitignore`:
   ```bash
   grep -q "^.env$" .gitignore && echo "✓ .env is ignored" || echo "✗ Add .env to .gitignore!"
   ```

## Step 4: Configure E2B Settings

1. Review the default configuration:
   ```bash
   cat .claude/config/e2b-config.json
   ```

2. Key settings to adjust:

   - **`defaultMode`**: `"local"` | `"sandbox"` | `"auto"`
     - `local`: Features run locally by default (zero E2B costs)
     - `sandbox`: Features run in E2B sandboxes by default
     - `auto`: Intelligent mode selection based on issue analysis

   - **`maxConcurrent`**: Maximum parallel sandboxes (default: 10)
     - Free tier supports up to 100 sandboxes
     - Consider your budget and workload

   - **`budgetLimit`**: Monthly budget in USD (default: 100)
     - System will warn when approaching limit
     - Prevents runaway costs

   - **`autoCleanup`**: Automatic sandbox cleanup (default: true)
     - Destroys idle sandboxes after 1 hour
     - Reduces costs

3. Edit configuration:
   ```bash
   nano .claude/config/e2b-config.json
   ```

   Or use the `/config` command from Claude Code.

## Step 5: Build TypeScript

Compile the TypeScript code:

```bash
npm run build
```

This creates the `dist/` directory with compiled JavaScript.

## Step 6: Configure Claude Desktop for MCP Server

1. Locate your Claude desktop configuration:
   - **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
   - **Linux**: `~/.config/Claude/claude_desktop_config.json`

2. Add the MCP server configuration:

   ```json
   {
     "mcpServers": {
       "bumba-sandbox": {
         "command": "node",
         "args": [
           "/absolute/path/to/your/project/dist/mcp-servers/bumba-sandbox.js"
         ],
         "env": {
           "E2B_API_KEY": "<e2b-api-key>",
           "ANTHROPIC_API_KEY": "<anthropic-api-key>",
           "GITHUB_TOKEN": "<github-token>",
           "GITHUB_REPO_OWNER": "your_github_username",
           "GITHUB_REPO_NAME": "your_repository_name"
         }
       }
     }
   }
   ```

   **Important**: Use absolute paths, not relative paths.

3. Restart Claude Desktop

4. Verify the connection:
   - Open Claude Code
   - The MCP server should appear in the status bar
   - Try: `/sandbox-status` to verify it's working

## Step 7: Verify Installation

Run the verification script:

```bash
npm run verify-setup
```

This will check:
- ✓ Environment variables are set
- ✓ API keys are valid
- ✓ GitHub repository is accessible
- ✓ E2B connection works
- ✓ TypeScript compilation succeeds
- ✓ MCP server can start

## Step 8: Initialize Your First Project (Optional)

If starting a new project:

```bash
/initialize-project my-awesome-app
```

This creates:
- Worktree directory structure
- Git repository
- Initial configuration
- Documentation templates

## Troubleshooting

### "E2B_API_KEY is not set"

**Solution**: Verify your `.env` file exists and contains the key:
```bash
cat .env | grep E2B_API_KEY
```

### "GitHub API rate limit exceeded"

**Solution**:
- Ensure your `GITHUB_TOKEN` is set correctly
- Authenticated requests have a much higher rate limit (5,000/hour vs 60/hour)

### "Cannot find module 'e2b'"

**Solution**: Re-install dependencies:
```bash
rm -rf node_modules package-lock.json
npm install
```

### "MCP server not connecting"

**Solutions**:
1. Check the absolute path in `claude_desktop_config.json`
2. Ensure TypeScript is compiled: `npm run build`
3. Check Claude Desktop logs:
   - **macOS**: `~/Library/Logs/Claude/`
   - **Windows**: `%APPDATA%\Claude\logs\`

### "Permission denied" errors

**Solution**: The hook system blocks file operations outside `temp/` directory. This is by design for security. Use sandbox mode for operations requiring broader access.

## Next Steps

1. **Create Your First PRD**: `/create-product-requirements`
2. **Plan Sprints**: `/plan-development-sprints`
3. **Create Issues**: `/create-specifications`
4. **Implement Features**:
   - Local: `/implement-feature #1 --local`
   - Sandbox: `/implement-feature #1 --sandbox`
   - Auto: `/implement-feature #1` (intelligent selection)
5. **Monitor Progress**: `/show-status`
6. **View Costs**: `/cost-report`

## Usage Modes

### Baseline GitHub Workflow (No E2B Costs)

Set `defaultMode: "local"` in config, then:

```bash
/create-product-requirements
/plan-development-sprints
/create-specifications
/implement-feature #1 --local
/test #1
/create-pull-request #1
```

**Cost**: $0 for E2B (only Claude API costs)

### Elevated Sandbox Workflow

For backend, security-sensitive, or complex features:

```bash
/implement-feature #1 --sandbox
/sandbox-status
/test #1 --sandbox
/create-pull-request #1
/cleanup-sandboxes
```

**Cost**: E2B sandbox usage + Claude API costs

### Parallel Multi-Agent Orchestration

For maximum speed with dependency management:

```bash
/parallel-implement-features #1 #2 #3 #4 #5 --strategy balanced
```

The system automatically:
- Analyzes dependencies
- Allocates resources
- Spawns agents in parallel
- Auto-spawns dependent features when blockers complete

## Security Best Practices

1. **Never commit `.env` file** - It contains sensitive API keys
2. **Use local mode by default** - Only elevate to sandbox when needed
3. **Review sandbox costs regularly** - Use `/cost-report` weekly
4. **Set budget limits** - Configure `budgetLimit` in e2b-config.json
5. **Rotate API keys periodically** - Every 90 days is recommended

## Support

- **Documentation**: See `docs/e2b/COMMANDS.md` for command reference
- **Issues**: Report problems at your project's GitHub Issues
- **E2B Docs**: [https://e2b.dev/docs](https://e2b.dev/docs)
- **Claude Code**: [https://claude.com/claude-code](https://claude.com/claude-code)

---

**Setup Complete!** 🎉

You're now ready to use Bumba Sandbox orchestration with Claude Code. Start with local mode to get familiar with the workflow, then try sandbox mode when you need isolation or parallel execution.

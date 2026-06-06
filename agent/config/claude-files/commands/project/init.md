---
name: init
description: Initialize project structure and configuration
---

# /project-init - Initialize E2B Orchestrator Project

Initialize a new project with the complete E2B Orchestrator directory structure, configuration files, and agent-sandboxes patterns.

## Architecture

This command uses a **two-phase architecture** for reliability:

1. **Phase 1 (This Command)**: Interactive configuration - gather user preferences
2. **Phase 2 (Hook)**: Deterministic execution - `on-project-init-complete.js` handles all file operations

When you write `project-config.json`, the hook automatically:
- Creates all directories
- Copies config schemas
- Generates config files
- Applies language template
- Generates documentation
- Creates .gitignore and .env.template
- Generates README.md
- Verifies structure

## Usage

```
/project-init [name] [--template <template>]
```

---

## Step 1: Detect Project Context

Analyze the current project before prompting:

### Get Current Directory Name

```bash
basename "$(pwd)"
```

### Check for Existing Structure

```bash
# Check if .claude/ exists
[ -d .claude ] && echo "CLAUDE_EXISTS"

# Check if package.json exists
[ -f package.json ] && cat package.json | head -20

# Check for other project markers
[ -f pyproject.toml ] && echo "PYTHON_PROJECT"
[ -f go.mod ] && echo "GO_PROJECT"
[ -f Cargo.toml ] && echo "RUST_PROJECT"
```

---

## Step 2: Handle Existing .claude/

**If `.claude/` exists**, use AskUserQuestion:

**Question**: "A .claude/ directory already exists. What would you like to do?"

Options:
- **Add E2B Structure** - Keep existing files, add E2B Orchestrator structure
- **Reinitialize** - Backup existing and create fresh structure
- **Cancel** - Abort initialization

If **Reinitialize**:
```bash
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
mv .claude ".claude-backup-$TIMESTAMP"
```

If **Cancel**: Exit with message "Initialization cancelled."

---

## Step 3: Interactive Configuration

Use AskUserQuestion for each prompt. Record answers for project-config.json.

### Prompt 1: Project Name

If not provided as argument, use the current directory name.

Store as: `name`

### Prompt 2: Language/Template

**Question**: "Which language template would you like to use?"

Options:
- **Node.js** - TypeScript with Jest, ESLint, Prettier (Recommended)
- **Python** - Python 3.11+ with pytest, Black, mypy
- **Go** - Go modules with testing
- **Rust** - Cargo with standard structure
- **None** - No template, just directory structure

Store as: `template` (node | python | go | rust | none)

### Prompt 3: Features (multi-select)

**Question**: "Which features do you want to enable?"

Options:
- **Git Init** - Initialize git repository (Recommended)
- **Auto-Sandbox** - Automatically use sandboxes for risky operations
- **GitHub Integration** - Enable GitHub PR automation
- **Notion Dashboard** - Create Notion project management dashboard

Store as: `gitInit` (true | false), `autoSandbox` (true | false), `githubIntegration` (true | false), `notionDashboard` (true | false)

### Prompt 4: GitHub Repository (conditional)

**Question**: "What is the GitHub repository URL for this project?"

**Only show if**: `githubIntegration` OR `notionDashboard` is true

Store as: `githubRepo` (string)

If user doesn't have a repo yet, they can enter a placeholder like `https://github.com/username/project-name`

### Prompt 5: Execution Mode

**Question**: "What should be the default execution mode?"

Options:
- **Auto** - Intelligently choose between local and sandbox (Recommended)
- **Sandbox** - Always use E2B sandbox for execution
- **Local** - Always execute locally (less safe)

Store as: `defaultMode` (auto | sandbox | local)

---

## Step 4: Generate project-config.json

Build configuration from collected answers and write to `.claude/project-config.json`.

**CRITICAL**: Writing this file triggers the `on-project-init-complete` hook which handles all file system operations.

### Create .claude directory first

```bash
mkdir -p .claude
```

### Configuration Template

```json
{
  "version": "1.0.0",
  "project": {
    "name": "{{name}}",
    "template": "{{template}}",
    "createdAt": "{{ISO timestamp}}"
  },
  "options": {
    "gitInit": {{gitInit}},
    "autoSandbox": {{autoSandbox}},
    "githubIntegration": {{githubIntegration}},
    "notionDashboard": {{notionDashboard}},
    "githubRepo": "{{githubRepo}}",
    "defaultMode": "{{defaultMode}}"
  }
}
```

### Write project-config.json

Use the Write tool to create `.claude/project-config.json` with the built configuration.

**Important**: Use JSON.stringify with 2-space indentation.

---

## Step 5: Wait for Hook Completion

The `on-project-init-complete` hook automatically triggers when project-config.json is written.

It handles:
- Directory structure creation (`.claude/`, `apps/`, `docs/`, `worktrees/`)
- Config schema copying
- Language template application
- Documentation generation
- .gitignore and .env.template creation
- README.md generation
- Structure verification
- **Notion dashboard creation** (if `notionDashboard` is enabled)

The hook will:
1. Create E2B Orchestrator structure first
2. If `notionDashboard` is true, create Notion project dashboard:
   - Duplicate the master template page
   - Create entry in Projects Master database
   - Apply GitHub Repo filters to linked database views
   - Return Notion dashboard URL

Wait approximately 3-5 seconds for the hook to complete (longer if Notion integration is enabled).

---

## Step 6: Git Initialization (if enabled)

If `gitInit` is true:

```bash
git init
git add .
git commit -m "Initial commit - E2B Orchestrator project structure"
```

---

## Step 7: Verify and Report

### Verify Structure

```bash
ls -la .claude/
ls -la apps/sandbox_agent_working_dir/
```

### Display Success Message

```
E2B Orchestrator Project Initialized!
═══════════════════════════════════════════════

Project: {{name}}
Template: {{template}}
Location: {{pwd}}

Created structure:
   .claude/
   ├── commands/            # Slash commands
   ├── mcp-servers/         # MCP server code
   ├── config/              # Configuration
   │   ├── bumba-sandbox-config.json
   │   ├── bumba-sandbox-config.schema.json
   │   └── orchestrator-state.json
   ├── templates/           # Custom templates
   └── hooks/               # Hook scripts

   apps/
   └── sandbox_agent_working_dir/
       ├── temp/            # Hook-restricted local ops
       ├── logs/            # Per-agent logs
       └── code/            # Agent workspace

   docs/
   ├── e2b/                 # E2B documentation
   │   ├── SETUP.md
   │   ├── COMMANDS.md
   │   └── MCP_TOOLS_REFERENCE.md
   └── prd/                 # Product requirements

   worktrees/               # Git worktrees

Configuration:
   Mode: {{defaultMode}}
   Auto-Sandbox: {{autoSandbox}}
   GitHub: {{githubIntegration}}
   Notion Dashboard: {{notionDashboard}}
   {{if notionDashboard}}
   Notion URL: {{notionDashboardUrl}}
   {{endif}}

Quick Start:
   1. Configure API keys:
      cp .env.template .env
      # Edit .env with your keys

   2. Create a PRD:
      /idea-requirements

   3. Plan sprints:
      /spec-sprints

   4. Implement features:
      /code-parallel #1 #2 #3

Happy coding!
```

---

## Error Handling

### Directory Already Exists (and user chose Cancel)

```
Initialization cancelled.

To add E2B structure to existing project:
  /project-init --force
```

### Permission Errors

```
Error: Permission denied creating .claude/

Solutions:
1. Check permissions: ls -la ./
2. Grant write access: chmod u+w ./
```

### Hook Not Triggered

If structure incomplete after writing config:

```
Warning: Hook may not have triggered.

The PostToolUse hook may not be active. To complete setup manually:
  node ~/.claude/hooks/on-project-init-complete.js

Or restart Claude Code and try again.
```

---

## Related Commands

After initialization:
- `/idea-requirements` - Create PRD document
- `/spec-sprints` - Plan feature sprints
- `/spec-issues` - Generate GitHub issues from specs
- `/code-parallel` - Implement features in parallel
- `/sandbox-status` - View active sandboxes and status
- `/sandbox-start` - Start a new sandbox

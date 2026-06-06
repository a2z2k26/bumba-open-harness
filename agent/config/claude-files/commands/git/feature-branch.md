---
name: feature-branch
description: Create feature worktree for isolated development (Implementation stage)
---

# /implement-feature Command

Implements a GitHub issue feature using intelligent mode selection (local, Bumba Sandbox sandbox, or auto).

## Usage

```
/implement-feature #<issue-number> [--mode <local|sandbox|auto>]
```

## Parameters

- `#<issue-number>` (required): GitHub issue number to implement
- `--mode <mode>` (optional): Execution mode (default: auto)
  - `local`: Execute in local environment with hooks
  - `sandbox`: Execute in Bumba Sandbox sandbox with full isolation
  - `auto`: Automatically determine best mode based on issue analysis

## Workflow

### Step 1: Issue Validation & Dependency Check

First, I'll fetch and validate the GitHub issue:

1. Parse the issue number from your command
2. Fetch the issue details from GitHub using the repository configured in your environment
3. Extract the issue title, description, labels, and specification
4. Parse any dependencies from the issue body (looks for "Depends on #X" or "Blocked by #X")
5. Check if all dependencies are satisfied (completed issues)
6. If dependencies are not satisfied, I'll stop and inform you which issues need to be completed first

### Step 2: Mode Selection

If you specified `--mode`, I'll use that mode. Otherwise, in `auto` mode, I'll analyze the issue to determine the best execution environment:

**Indicators for Sandbox Mode**:
- Labels: `backend`, `database`, `infrastructure`, `security`, `service`
- Keywords in description: `database`, `API`, `service`, `deployment`, `security`, `authentication`
- Requires external services or dependencies
- Involves system-level changes
- Risk of affecting local development environment

**Indicators for Local Mode**:
- Labels: `frontend`, `ui`, `docs`, `simple`, `quick-fix`
- Keywords: `documentation`, `UI`, `styling`, `minor`, `typo`
- Simple changes to existing code
- No external dependencies
- Low risk to development environment

**Default**: When uncertain, I'll default to sandbox mode for safety and isolation.

### Step 3: Implementation (Local Mode)

If executing in **local mode**:

1. **Create Git Worktree**:
   - Create a new worktree in `worktrees/feature-<issue-number>/`
   - Create a feature branch: `feature/issue-<issue-number>`
   - Switch to the new worktree

2. **Enable Hooks for Security**:
   - Register PreToolUse hook to restrict operations to the worktree and temp/ directory
   - Register PostToolUse hook to log all tool usage
   - Register Stop hook to track time and token costs

3. **Create Implementation Plan**:
   - Analyze the issue requirements
   - Break down into concrete implementation steps
   - Identify files that need changes
   - Plan test coverage

4. **Execute Implementation**:
   - Make code changes according to the plan
   - Follow project conventions and style guides
   - Write or update tests as needed
   - Run tests to verify implementation

5. **Validation**:
   - Run test suite to ensure all tests pass
   - Run linter/formatter if configured
   - Verify no unintended side effects

### Step 4: Implementation (Sandbox Mode)

If executing in **sandbox mode**:

1. **Create Git Worktree** (same as local mode):
   - Create worktree in `worktrees/feature-<issue-number>/`
   - Create feature branch: `feature/issue-<issue-number>`

2. **Spawn Sandbox Agent**:
   - Call the `spawn_sandbox_agent` MCP tool
   - Pass the issue number and specification
   - Pass the worktree path for code upload
   - The MCP tool will:
     - Create a Bumba Sandbox sandbox with appropriate template
     - Upload worktree code to sandbox (excluding .git, node_modules)
     - Install dependencies in the sandbox
     - Register security hooks (PreToolUse for path restrictions)
     - Configure hybrid tool access (MCP tools + restricted local in temp/)
     - Generate system prompt with issue context

3. **Monitor Agent Progress**:
   - Query hook logs for agent activity
   - Display real-time progress updates
   - Show tool usage and decisions being made
   - Track costs and resource usage

4. **Sync Code Back**:
   - When implementation is complete, sync changes from sandbox to worktree
   - Verify all files are properly transferred
   - Ensure git history is clean

5. **Cleanup**:
   - Destroy the sandbox to save costs
   - Update orchestrator state
   - Log final metrics (time, cost, tokens used)

### Step 5: Final Steps (Both Modes)

1. **Review Changes**:
   - Display summary of files changed
   - Show test results
   - Report any warnings or issues

2. **Next Steps Guidance**:
   - Suggest running `/test #<issue>` if needed
   - Recommend `/create-pull-request` when ready
   - Consider using `/wf_plan_build` for future features (combines planning and execution)
   - Provide cost summary if sandbox mode was used

## Examples

### Example 1: Auto Mode (Default)
```
/implement-feature #42
```
I'll analyze issue #42 and automatically choose the best execution mode.

### Example 2: Force Local Mode
```
/implement-feature #43 --mode local
```
I'll implement issue #43 in your local environment with hook protections.

### Example 3: Force Sandbox Mode
```
/implement-feature #44 --mode sandbox
```
I'll implement issue #44 in an isolated E2B sandbox.

## Error Handling

- **Issue Not Found**: I'll inform you and stop execution
- **Unresolved Dependencies**: I'll list blocking issues and stop
- **Sandbox Creation Failure**: I'll retry once, then offer local mode fallback
- **Test Failures**: I'll report failures and ask how to proceed
- **Hook Violations**: Security hooks will block unsafe operations and log violations

## Cost Information

**Local Mode**:
- Only API costs for Claude requests
- Typically $0.10 - $0.50 per feature depending on complexity

**Sandbox Mode**:
- Sandbox costs: ~$0.02/hour
- API costs: $0.10 - $0.50 per feature
- Total: ~$0.15 - $0.75 per feature

**Auto Mode**:
- Chooses cost-effective option based on issue complexity

## Hook System Integration

This command leverages the hook system for security and observability:

- **PreToolUse Hook**: Prevents accidental changes outside worktree or temp/ directory
- **PostToolUse Hook**: Logs all tools used during implementation for audit trail
- **Stop Hook**: Tracks token usage and calculates costs
- **UserPromptSubmit Hook**: Logs decision points for debugging

All hook logs are stored in `apps/sandbox_agent_working_dir/logs/` for later analysis.

## Configuration

Set these environment variables:
- `GITHUB_TOKEN`: GitHub Personal Access Token with repo access
- `SANDBOX_API_KEY`: Sandbox API key (required for sandbox mode)
- `ANTHROPIC_API_KEY`: Anthropic API key for Claude requests

Configure defaults in `.claude/config/bumba-sandbox-config.json`:
- `defaultMode`: Set to "local", "sandbox", or "auto"
- `autoModeRules`: Customize label-based mode selection
- `maxConcurrent`: Maximum parallel sandboxes

## Notes

- Always review the generated plan before I begin implementation
- Sandbox mode provides full isolation but costs more
- Local mode is faster and cheaper but less isolated
- Auto mode balances cost, speed, and safety
- You can pause and resume sandbox implementations
- All activity is logged for troubleshooting and cost tracking
- For rapid development, use `/wf_plan_build` which combines planning and building in one command
- This command integrates with Phase 2 MCP tools: `spawn_sandbox_agent`, `monitor_agents`, `analyze_dependencies`

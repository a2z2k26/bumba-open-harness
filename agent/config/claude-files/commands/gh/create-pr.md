---
name: create-pr
description: Create pull request with AI-generated description (Deployment stage)
---

# /create-pull-request Command

Creates a GitHub Pull Request with pre-flight checks and automatic description generation.

## Usage

```
/create-pull-request [#<issue-number>]
```

## Parameters

- `#<issue-number>` (optional): Issue number to link in PR. If not provided, I'll detect it from the current branch name.

## Workflow

### Step 1: Detect Context

1. **Identify Current Branch**:
   - Get the current git branch name
   - Extract issue number from branch name (e.g., `feature/issue-42` → #42)
   - If issue number provided as parameter, use that instead

2. **Locate Worktree**:
   - Determine if we're in a worktree or main repository
   - Find the worktree path if applicable
   - Verify we're on a feature branch (not main/master)

### Step 2: Sync from Sandbox (If Applicable)

If this feature was implemented in sandbox mode:

1. **Check for Active Sandbox**:
   - Query orchestrator state for sandbox associated with this issue
   - If sandbox exists and contains changes, sync them first

2. **Sync Changes**:
   - Download all modified files from sandbox
   - Write changes to the worktree
   - Preserve file permissions and timestamps
   - Verify all files transferred successfully

3. **Cleanup Sandbox**:
   - Optionally destroy sandbox after sync (ask for confirmation)
   - Update orchestrator state
   - Log final sandbox metrics

### Step 3: Pre-Flight Checks

Before creating the PR, I'll verify everything is ready:

1. **Uncommitted Changes Check**:
   - Run `git status` to check for uncommitted changes
   - If found, ask if you want me to commit them
   - If yes, create a commit with a descriptive message

2. **Test Status Check**:
   - Check if tests exist for this project
   - If tests exist, ask if you want me to run them
   - If yes, run the test suite
   - If tests fail, ask how to proceed (abort, continue anyway, fix tests)

3. **Linting Check**:
   - Detect if linter is configured (eslint, prettier, black, etc.)
   - If found, run linter
   - If linting fails, ask how to proceed (abort, continue, fix issues)

4. **Branch Up-to-Date Check**:
   - Fetch latest main/master branch
   - Check if feature branch is behind main
   - If behind, recommend running `/synchronize-branch` first
   - Ask if you want to continue anyway

### Step 4: Generate PR Content

1. **Fetch Issue Details**:
   - If issue number is known, fetch issue from GitHub
   - Extract issue title, description, labels

2. **Analyze Changes**:
   - Run `git diff main...HEAD` to see all changes
   - Identify files modified, added, deleted
   - Count lines changed
   - Detect which areas of codebase were affected

3. **Generate PR Title**:
   - Format: `feat: <issue title>` or `fix: <issue title>` based on labels
   - Use conventional commit format when possible
   - Keep title concise (< 72 characters)

4. **Generate PR Description**:
   ```markdown
   ## Summary
   <Brief description of what this PR does>

   ## Changes
   - <List of key changes made>
   - <File-level changes summary>

   ## Testing
   <Description of tests added/updated>
   <Test results summary>

   ## Notes
   <Any additional context, breaking changes, or follow-up items>

   Closes #<issue-number>
   ```

### Step 5: Create Pull Request

1. **Push Branch**:
   - Push feature branch to remote: `git push origin <branch-name>`
   - If branch doesn't exist remotely, create it
   - Set upstream tracking

2. **Create PR via GitHub CLI**:
   - Use `gh pr create` command
   - Pass generated title and description
   - Auto-link to issue with "Closes #X"
   - Apply labels from issue to PR
   - Request reviewers if configured

3. **Display PR Details**:
   - Show PR number and URL
   - Show PR title and description
   - Provide link to view PR in browser

### Step 6: Next Steps Guidance

Provide recommendations based on PR status:

- If tests passed: "PR is ready for review"
- If no tests: "Consider adding tests before requesting review"
- If linting failed: "Consider fixing linting issues"
- Suggest using `/review-pull-request #<pr>` for self-review
- Suggest monitoring with `/show-status`

## Examples

### Example 1: Create PR for Current Branch
```
/create-pull-request
```
I'll detect the issue number from the branch name and create a PR.

### Example 2: Create PR for Specific Issue
```
/create-pull-request #42
```
I'll create a PR for issue #42, even if the branch name doesn't match.

### Example 3: Create PR After Sandbox Implementation
```
# After using /implement-feature #42 --mode sandbox
/create-pull-request #42
```
I'll sync code from the sandbox and create the PR.

## Pre-Flight Check Failures

### Uncommitted Changes
```
⚠️ You have uncommitted changes:
  M src/components/Feature.tsx
  M src/tests/feature.test.ts

Would you like me to:
1. Commit these changes with an auto-generated message
2. Let you commit them manually
3. Abort PR creation
```

### Tests Failing
```
❌ Tests failed (3 failures):
  ✗ Feature component renders correctly
  ✗ Feature handles edge cases
  ✗ Feature integrates with API

Would you like me to:
1. Continue creating PR anyway (mark as draft)
2. Abort and let you fix tests
3. Attempt to fix failing tests
```

### Branch Out of Date
```
⚠️ Your branch is 5 commits behind main:
  - feat: Add new API endpoint
  - fix: Security vulnerability
  - chore: Update dependencies
  - docs: Update README
  - test: Add integration tests

Recommendation: Run /synchronize-branch first

Would you like to:
1. Synchronize branch now
2. Continue creating PR anyway
3. Abort
```

## Error Handling

- **Not on Feature Branch**: I'll warn and confirm if you really want to create PR from current branch
- **No Remote Repository**: I'll inform you that git remote is not configured
- **GitHub CLI Not Installed**: I'll provide instructions to install `gh` CLI
- **GitHub Authentication Failed**: I'll guide you through authentication setup
- **PR Already Exists**: I'll show existing PR and ask if you want to update it

## Configuration

Set these environment variables:
- `GITHUB_TOKEN`: GitHub Personal Access Token (for API access)
- `GH_TOKEN`: Same as GITHUB_TOKEN (for gh CLI)

Configure defaults in `.claude/config/e2b-config.json`:
- `pr.autoCommit`: Auto-commit uncommitted changes (default: false)
- `pr.runTests`: Auto-run tests before PR (default: true)
- `pr.runLinter`: Auto-run linter before PR (default: true)
- `pr.checkUpToDate`: Check if branch is up-to-date (default: true)
- `pr.createDraft`: Create draft PRs by default (default: false)

## Hook System Integration

This command uses hooks for tracking:

- **PostToolUse Hook**: Logs PR creation action
- **Stop Hook**: Tracks time and costs for PR creation process

## Cost Information

- **Local operations**: Free (git, linting, testing)
- **API costs**: ~$0.05 - $0.15 for analysis and description generation
- **Sandbox sync** (if applicable): Already counted in implementation cost

## Notes

- PR descriptions are generated based on actual code changes
- You can edit the PR title and description before it's created
- Draft PRs are useful when tests are failing but you want early feedback
- The `Closes #X` keyword automatically links and closes the issue when PR merges
- All pre-flight checks can be skipped with flags (documented separately)

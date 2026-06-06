---
name: merge-pr
description: Merge approved PR and cleanup (Deployment stage)
---

# /merge-pull-request Command

Merges a pull request after validation and performs complete cleanup of the feature branch, worktree, and associated sandbox.

## Usage

```
/merge-pull-request <pr-number> [--strategy <squash|merge|rebase>] [--delete-branch]
```

## Parameters

- `<pr-number>` (required): Pull request number to merge
- `--strategy <strategy>` (optional): Merge strategy (default: squash)
  - `squash`: Squash all commits into one (clean history)
  - `merge`: Create merge commit (preserves history)
  - `rebase`: Rebase and merge (linear history)
- `--delete-branch` (optional): Delete feature branch after merge (default: true)
- `--yes` (optional): Skip confirmation prompts
- `--keep-sandbox` (optional): Keep sandbox running after merge

## Workflow

### Step 1: Fetch Pull Request Information

1. **Retrieve PR Details via GitHub API**:
   ```
   📋 Pull Request Information
   ═══════════════════════════════════════════════

   PR #42: Implement user authentication
   Author: @developer
   Created: 2 days ago
   Updated: 1 hour ago

   Branch: feature/42-user-authentication → main
   Status: Open
   Commits: 5
   Files Changed: 12
   +245 / -67

   Labels: backend, authentication, P0
   Assignees: @developer
   Reviewers: @reviewer1, @reviewer2
   ```

2. **Extract PR Metadata**:
   - PR number, title, description
   - Source branch (feature branch)
   - Target branch (usually main)
   - Associated issue number
   - Number of commits
   - Files changed
   - Current status

### Step 2: Pre-Merge Validation

1. **Check PR Approval Status**:
   ```
   ✅ Review Status
   ═══════════════════════════════════════════════

   Required Approvals: 2
   Received Approvals: 2
     ✓ @reviewer1 approved 1 hour ago
     ✓ @reviewer2 approved 30 minutes ago

   Changes Requested: 0
   Comments: 5 (all resolved)

   Status: ✓ Approved - ready to merge
   ```

2. **Check CI/CD Status**:
   ```
   🔧 CI/CD Status
   ═══════════════════════════════════════════════

   GitHub Actions:
     ✓ Build (passed) - 5 minutes ago
     ✓ Unit Tests (passed) - 5 minutes ago
     ✓ Integration Tests (passed) - 8 minutes ago
     ✓ Lint (passed) - 3 minutes ago
     ✓ Security Scan (passed) - 10 minutes ago

   All Checks: ✓ Passing (5/5)

   Status: ✓ All checks passed - safe to merge
   ```

3. **Check for Merge Conflicts**:
   ```
   🔍 Merge Conflict Check
   ═══════════════════════════════════════════════

   Base branch: main (up-to-date)
   Feature branch: feature/42-user-authentication

   Files changed in PR: 12
   Files changed in main (since branch): 3

   Overlap Analysis:
     No overlapping file changes
     ✓ No conflicts detected

   Status: ✓ Can be merged cleanly
   ```

4. **Handle Validation Failures**:

   **Insufficient Approvals**:
   ```
   ❌ Approval Required

   Required Approvals: 2
   Received Approvals: 1
     ✓ @reviewer1 approved 1 hour ago
     ⏳ @reviewer2 review pending

   Cannot merge until all approvals received.

   Options:
     1. Wait for review: Monitor PR status
     2. Request review: Notify @reviewer2
     3. Override: --force-merge (requires admin)
   ```

   **CI/CD Failures**:
   ```
   ❌ CI/CD Checks Failed

   GitHub Actions:
     ✓ Build (passed)
     ✓ Unit Tests (passed)
     ❌ Integration Tests (failed)
     ✓ Lint (passed)
     ⚠️  Security Scan (warning)

   Failed Checks: 1/5
   Warnings: 1/5

   Cannot merge with failing checks.

   View logs: gh run view <run-id>
   Fix issues and push to update PR.
   ```

   **Merge Conflicts**:
   ```
   ❌ Merge Conflicts Detected

   The following files conflict with main:
     - src/auth/login.ts
     - package.json

   Cannot auto-merge.

   Options:
     1. Sync branch: /synchronize-branch #42
     2. Resolve manually: Open PR and resolve conflicts
     3. Update from main: git pull origin main
   ```

5. **Display Validation Summary**:
   ```
   ✅ Pre-Merge Validation Complete
   ═══════════════════════════════════════════════

   PR Ready to Merge:
     ✓ Approvals: 2/2 received
     ✓ CI/CD: All checks passing
     ✓ Conflicts: None
     ✓ Branch: Up-to-date with main

   Merge Strategy: squash (recommended)
   Branch Cleanup: Yes (delete after merge)
   Sandbox Cleanup: Yes (destroy after merge)
   ```

### Step 3: Strategy Selection and Confirmation

1. **Display Strategy Comparison**:
   ```
   📊 Merge Strategy Comparison
   ═══════════════════════════════════════════════

   Your PR has 5 commits:
     - feat: implement OAuth login
     - test: add authentication tests
     - fix: handle edge cases
     - docs: update README
     - style: format code

                  Squash    Merge     Rebase
   ───────────────────────────────────────────────
   Final commits:   1         6         5
   History:         Clean     Full      Linear
   Revert:          Easy      Easy      Hard
   Traceability:    Low       High      Medium

   Recommended: squash
     Reason: Multiple small commits, clean history preferred
   ```

2. **Show Squash Commit Preview** (if squash):
   ```
   📝 Squash Commit Preview
   ═══════════════════════════════════════════════

   Title:
   Implement user authentication (#42)

   Description:
   - Implemented OAuth login with Google and GitHub
   - Added comprehensive authentication tests
   - Added session management and token refresh
   - Updated documentation

   Closes #42

   This commit includes:
     - feat: implement OAuth login
     - test: add authentication tests
     - fix: handle edge cases
     - docs: update README
     - style: format code

   Co-authored-by: @reviewer1
   Co-authored-by: @reviewer2
   ```

3. **User Confirmation**:
   ```
   ⚡ Ready to Merge PR #42
   ═══════════════════════════════════════════════

   PR: #42 - Implement user authentication
   Strategy: squash
   Commits: 5 → 1 (squashed)
   Files: 12 changed (+245/-67)

   This will:
     1. Squash 5 commits into 1 clean commit
     2. Merge into main branch
     3. Delete feature/42-user-authentication branch
     4. Delete worktrees/feature-42 worktree
     5. Destroy sandbox sbx_abc123xyz (if exists)
     6. Close issue #42 automatically

   Continue with merge? (yes/no/adjust)
   ```

### Step 4: Execute Merge

1. **Merge PR via GitHub API**:
   ```bash
   gh pr merge 42 --squash --delete-branch
   ```

2. **Display Merge Progress**:
   ```
   🚀 Merging PR #42
   ═══════════════════════════════════════════════

   [1/6] Validating final state...
         ✓ PR still mergeable
         ✓ No new conflicts

   [2/6] Squashing commits...
         ✓ 5 commits squashed into 1
         ✓ Commit message generated

   [3/6] Merging to main...
         ✓ Merged successfully
         ✓ Commit SHA: abc123def456

   [4/6] Deleting remote branch...
         ✓ Branch feature/42-user-authentication deleted

   [5/6] Updating local repository...
         ✓ Fetched latest main
         ✓ Local main updated

   [6/6] Closing issue #42...
         ✓ Issue closed automatically
   ```

### Step 5: Local Cleanup

1. **Update Main Worktree**:
   ```bash
   cd <main-worktree>
   git fetch origin main
   git merge origin/main
   ```

   ```
   📥 Updating Local Main Branch
   ═══════════════════════════════════════════════

   Fetching latest changes from origin/main...
   ✓ Fetched successfully

   Merging into local main...
   ✓ Fast-forward merge
   ✓ main is now up-to-date

   New commits in main:
     abc123def Implement user authentication (#42)
   ```

2. **Delete Feature Worktree**:
   ```bash
   git worktree remove worktrees/feature-42
   ```

   ```
   🗑️  Deleting Feature Worktree
   ═══════════════════════════════════════════════

   Worktree: worktrees/feature-42
   Branch: feature/42-user-authentication

   Removing worktree...
   ✓ Worktree removed from disk
   ✓ Git worktree reference removed

   Deleted: worktrees/feature-42/
   ```

3. **Delete Local Feature Branch**:
   ```bash
   git branch -d feature/42-user-authentication
   ```

   ```
   🗑️  Deleting Local Feature Branch
   ═══════════════════════════════════════════════

   Branch: feature/42-user-authentication
   Status: Merged to main ✓

   Deleting branch...
   ✓ Branch deleted locally

   Note: Remote branch already deleted by GitHub
   ```

### Step 6: Sandbox Cleanup

1. **Check for Associated Sandbox**:
   ```
   🏖️  Checking for Sandbox
   ═══════════════════════════════════════════════

   Issue: #42
   Searching for sandbox...

   Found: sbx_abc123xyz
     Created: 2 days ago
     Uptime: 1h 23m
     Status: Running (idle)
     Cost: $0.08
   ```

2. **Destroy Sandbox**:
   ```
   🗑️  Destroying Sandbox
   ═══════════════════════════════════════════════

   Sandbox: sbx_abc123xyz
   Issue: #42 (merged to main)

   Terminating sandbox...
   ✓ Sandbox terminated
   ✓ Resources freed

   Final Metrics:
     Uptime: 1h 23m
     Tools Used: 67
     Cost: $0.08

   Sandbox sbx_abc123xyz destroyed.
   ```

3. **Update Orchestrator State**:
   ```
   💾 Updating Orchestrator State
   ═══════════════════════════════════════════════

   Issue #42:
     Status: completed → merged
     Worktree: removed
     Sandbox: destroyed
     PR: #42 (merged)
     Merged At: 2025-11-18 14:32:15

   State saved to .claude/config/orchestrator-state.json
   ```

### Step 7: Final Summary

```
✅ Pull Request Merged Successfully!
═══════════════════════════════════════════════

PR #42: Implement user authentication

📊 Merge Summary
═══════════════════════════════════════════════

Merge Details:
  Strategy: squash
  Commits: 5 → 1
  Files: 12 changed (+245/-67)
  Merged By: @developer
  Merged At: 2025-11-18 14:32:15
  Commit SHA: abc123def456

Issue Status:
  #42: Implement user authentication
  Status: Open → Closed (by PR #42)
  Closed At: 2025-11-18 14:32:15

Cleanup Completed:
  ✓ Remote branch deleted (feature/42-user-authentication)
  ✓ Local branch deleted
  ✓ Worktree removed (worktrees/feature-42)
  ✓ Sandbox destroyed (sbx_abc123xyz)
  ✓ Main branch updated locally
  ✓ Orchestrator state updated

Cost Summary:
  Sandbox Runtime: $0.08
  API Costs: $0.45
  Total: $0.53

Next Steps:
  1. Verify feature in main branch
  2. Deploy to staging/production
  3. Start next feature: /implement-feature #43
  4. Monitor for issues

Main branch is now at:
  abc123def Implement user authentication (#42)
```

## Examples

### Example 1: Basic Merge
```
/merge-pull-request 42
```
Merges PR #42 with default settings (squash, delete branch).

### Example 2: Merge with Preserved History
```
/merge-pull-request 42 --strategy merge
```
Creates a merge commit preserving all individual commits.

### Example 3: Rebase and Merge
```
/merge-pull-request 42 --strategy rebase
```
Rebases commits onto main for linear history.

### Example 4: Keep Feature Branch
```
/merge-pull-request 42 --delete-branch=false
```
Merges PR but keeps the feature branch (not recommended).

### Example 5: Auto-Confirm
```
/merge-pull-request 42 --yes
```
Skips all confirmation prompts and merges immediately.

### Example 6: Keep Sandbox Running
```
/merge-pull-request 42 --keep-sandbox
```
Merges PR but leaves sandbox running for debugging.

## Merge Strategies

### Squash Strategy (Recommended)

**How it works**:
- Combines all commits into single commit
- Rewrites commit message
- Clean, linear history

**Best for**:
- Multiple small commits
- WIP commits
- Clean history requirements
- Most feature branches

**Example**:
```
Before:
  * feat: add login
  * wip: fix tests
  * wip: address review
  * fix: typo
  * style: format

After:
  * Implement user authentication (#42)
```

### Merge Strategy

**How it works**:
- Creates merge commit
- Preserves all individual commits
- Full history retained

**Best for**:
- Important feature milestones
- Multiple developers on branch
- Detailed history needed
- Regulatory requirements

**Example**:
```
Before:
  * feat: add login
  * test: add tests
  * docs: update

After:
  * Merge PR #42: Implement user authentication
  ├─ feat: add login
  ├─ test: add tests
  └─ docs: update
```

### Rebase Strategy

**How it works**:
- Replays commits on top of main
- Linear history without merge commit
- Commits appear as if written after main

**Best for**:
- Clean, linear history
- Few commits
- No concurrent development
- Experienced teams

**Example**:
```
Before (main):
  A -- B -- C (main)
        \
         D -- E (feature)

After:
  A -- B -- C -- D' -- E' (main)
```

## Error Handling

**PR Not Found**:
```
❌ Error: Pull request not found

PR #999 does not exist in this repository.

Verify the PR number and try again.
```

**PR Already Merged**:
```
ℹ️  PR Already Merged

PR #42 was merged 2 days ago.

Merged by: @developer
Merged at: 2025-11-16 10:23:45
Commit: abc123def456

No action needed.
```

**PR Closed Without Merge**:
```
⚠️  PR Closed (Not Merged)

PR #42 was closed without merging.

Closed by: @developer
Closed at: 2025-11-17 14:30:00
Reason: Duplicate of #40

Cannot merge a closed PR.
```

**Missing Approvals**:
```
❌ Cannot Merge - Approvals Required

Required Approvals: 2
Received Approvals: 1

Missing approval from: @reviewer2

Options:
  1. Wait for approval
  2. Request review: gh pr review 42 --request @reviewer2
  3. Override (requires admin): --force-merge
```

**CI/CD Failures**:
```
❌ Cannot Merge - CI/CD Checks Failing

Failed Checks:
  ✓ Build (passed)
  ❌ Tests (failed)
  ⚠️  Lint (warning)

Fix failing checks before merging.

View logs: gh run view <run-id>
```

**Merge Conflicts**:
```
❌ Cannot Merge - Conflicts Detected

Files with conflicts:
  - src/auth/login.ts
  - package.json

Resolve conflicts before merging:
  /synchronize-branch #42
```

## Cleanup Behavior

### Default Cleanup (--delete-branch)

**Remote Branch**:
- ✅ Deleted automatically by GitHub
- Prevents accidental reuse

**Local Branch**:
- ✅ Deleted from local repository
- Prevents stale branches

**Worktree**:
- ✅ Removed from disk
- Frees disk space

**Sandbox**:
- ✅ Destroyed via E2B API
- Stops runtime costs
- Frees resources

### Keep Branch (--delete-branch=false)

**Use Cases**:
- Future backports needed
- Reference implementation
- Documentation purposes

**Consequences**:
- Manual cleanup required later
- Potential confusion
- Stale branches accumulate

### Keep Sandbox (--keep-sandbox)

**Use Cases**:
- Post-merge testing needed
- Debugging production issues
- Performance analysis

**Consequences**:
- Continued runtime costs ($0.02/hr)
- Manual cleanup required
- Use `/cleanup-sandboxes` later

## Integration with Other Commands

**Before Merge**:
1. `/show-status` - Verify PR ready
2. `/test #42` - Run final tests
3. `/synchronize-branch #42` - Sync with main

**After Merge**:
1. `/show-status` - Verify cleanup
2. `/implement-feature #43` - Start next feature
3. `/cost-report` - Review costs

## Configuration

Configure in `.claude/config/bumba-sandbox-config.json`:

```json
{
  "merge": {
    "defaultStrategy": "squash",
    "deleteBranch": true,
    "destroySandbox": true,
    "requireApprovals": 2,
    "requireChecks": true,
    "autoUpdate": true
  }
}
```

**Options**:
- `defaultStrategy`: Default merge strategy
- `deleteBranch`: Delete branch after merge
- `destroySandbox`: Destroy sandbox after merge
- `requireApprovals`: Minimum approvals required
- `requireChecks`: Require passing CI/CD checks
- `autoUpdate`: Auto-update main worktree

## Notes

- Always verify PR is ready before merging
- Squash strategy is recommended for most cases
- Merge commits preserve detailed history
- Rebase creates cleanest history but rewrites commits
- Delete branches after merge to avoid clutter
- Destroy sandboxes after merge to save costs
- Update local main branch after merge
- Issue is automatically closed if PR description includes "Closes #X"
- Use `--keep-sandbox` sparingly - costs continue
- Force push is never required (merge happens on GitHub)
- Merged code is immediately available on main branch

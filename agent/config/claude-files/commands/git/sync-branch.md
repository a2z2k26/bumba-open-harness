---
name: sync-branch
description: Merge/rebase branch with main (Verification stage)
---

# /synchronize-branch Command

Synchronizes a feature branch with the latest changes from the main branch using merge or rebase strategies.

## Usage

```
/synchronize-branch [#<issue>] [--strategy <merge|rebase>] [--main-branch <branch>]
```

## Parameters

- `#<issue>` (optional): Issue number for the feature branch (default: current branch)
- `--strategy <strategy>` (optional): Sync strategy (default: merge)
  - `merge`: Merge main into feature branch (preserves history)
  - `rebase`: Rebase feature branch onto main (linear history)
- `--main-branch <branch>` (optional): Main branch name (default: main)
- `--auto-resolve` (optional): Automatically resolve simple conflicts
- `--dry-run` (optional): Preview changes without applying

## Workflow

### Step 1: Identify Target Branch

1. **Determine Feature Branch**:
   - If `#<issue>` provided, use `feature-{issue}` worktree
   - If no argument, use current git branch
   - Verify worktree/branch exists

2. **Display Branch Information**:
   ```
   🔄 Branch Synchronization
   ═══════════════════════════════════════════════

   Feature Branch: feature/42-user-authentication
   Main Branch: main
   Worktree: worktrees/feature-42
   Strategy: merge
   ```

3. **Validate Branch State**:
   - Check for uncommitted changes (warn if present)
   - Check if branch exists locally and remotely
   - Verify not currently on main branch

### Step 2: Fetch Latest Changes

1. **Update Main Branch**:
   ```bash
   git fetch origin main
   ```

2. **Compare Branches**:
   ```bash
   git rev-list --left-right --count origin/main...HEAD
   ```

3. **Display Comparison**:
   ```
   📊 Branch Comparison
   ═══════════════════════════════════════════════

   Your branch: feature/42-user-authentication
   Base branch: origin/main

   Status:
     ✓ 5 commits ahead of main
     ⚠️  12 commits behind main
     → Synchronization recommended

   Latest commits on main (not in your branch):
     abc1234 - fix: resolve security vulnerability (2 hours ago)
     def5678 - feat: add logging middleware (5 hours ago)
     ghi9012 - docs: update API documentation (1 day ago)
     ...

   Your commits (not in main):
     jkl3456 - feat: implement OAuth login (3 hours ago)
     mno7890 - test: add authentication tests (2 hours ago)
     pqr1234 - fix: handle edge cases (1 hour ago)
     ...
   ```

4. **Check for Conflicts**:
   - Analyze file changes in both branches
   - Predict potential conflicts
   - Warn if conflicts likely

   ```
   ⚠️  Potential Conflicts Detected

   Files changed in both branches:
     - src/auth/login.ts (modified on main and your branch)
     - package.json (modified on main and your branch)

   Likelihood: MEDIUM

   Review these files before proceeding.
   ```

### Step 3: Strategy Selection

1. **If Strategy Not Specified, Recommend**:
   ```
   💡 Strategy Recommendation
   ═══════════════════════════════════════════════

   Merge Strategy:
     Pros: Preserves full history, safer
     Cons: Creates merge commit, non-linear history
     Best for: Shared branches, completed features

   Rebase Strategy:
     Pros: Clean linear history, easier to read
     Cons: Rewrites history, can cause issues if pushed
     Best for: Personal branches, in-progress work

   Recommendation: merge
     Reason: Feature branch has been pushed to remote

   Proceed with merge? (yes/no/rebase)
   ```

2. **Get User Confirmation**:
   - Display strategy choice
   - Explain implications
   - Ask for confirmation

### Step 4: Execute Synchronization

#### Merge Strategy

1. **Merge Main into Feature**:
   ```bash
   git merge origin/main
   ```

2. **Display Merge Progress**:
   ```
   🔀 Merging origin/main into feature/42-user-authentication
   ═══════════════════════════════════════════════

   Applying changes from main...
   ✓ Auto-merging src/utils/helpers.ts
   ✓ Auto-merging package.json
   ✓ Auto-merging README.md
   ⚠️  CONFLICT (content): Merge conflict in src/auth/login.ts

   Merge Status: Conflicts detected (1 file)
   ```

3. **Handle Clean Merge**:
   ```
   ✅ Merge Successful (No Conflicts)
   ═══════════════════════════════════════════════

   Changes Applied:
     12 files changed
     +245 insertions
     -67 deletions

   Merge Commit: Created merge commit 'abc1234'
   Message: "Merge branch 'main' into feature/42-user-authentication"

   Branch Status:
     ✓ Up-to-date with main
     ✓ 5 commits ahead of main (your work)
     ✓ 0 commits behind main

   Next Steps:
     1. Run tests: /test #42
     2. Push changes: git push origin feature/42-user-authentication
   ```

#### Rebase Strategy

1. **Rebase onto Main**:
   ```bash
   git rebase origin/main
   ```

2. **Display Rebase Progress**:
   ```
   ⚡ Rebasing onto origin/main
   ═══════════════════════════════════════════════

   Rewinding head to replay your work on top of main...
   Applying: feat: implement OAuth login
     ✓ Applied successfully
   Applying: test: add authentication tests
     ✓ Applied successfully
   Applying: fix: handle edge cases
     ⚠️  CONFLICT: src/auth/login.ts

   Rebase Status: Paused (conflict in commit 3/5)
   ```

3. **Handle Clean Rebase**:
   ```
   ✅ Rebase Successful
   ═══════════════════════════════════════════════

   Your 5 commits have been replayed on top of main.

   New commit history:
     abc1234 (origin/main) - Latest on main
     def5678 - feat: implement OAuth login (rebased)
     ghi9012 - test: add authentication tests (rebased)
     jkl3456 - fix: handle edge cases (rebased)

   Branch Status:
     ✓ Up-to-date with main
     ✓ Linear history achieved
     ⚠️  History rewritten - force push required

   Next Steps:
     1. Run tests: /test #42
     2. Force push: git push --force-with-lease origin feature/42-user-authentication

   ⚠️  Warning: Only force push if you're the only one working on this branch
   ```

### Step 5: Conflict Resolution

1. **Detect Conflicts**:
   ```
   ⚠️  Conflicts Detected
   ═══════════════════════════════════════════════

   The following files have conflicts:
     1. src/auth/login.ts (3 conflict regions)
     2. package.json (1 conflict region)

   Total Conflicts: 4
   ```

2. **Analyze Conflicts**:
   For each conflicted file:
   - Read conflict markers
   - Parse HEAD and incoming changes
   - Categorize conflict type

3. **Display Conflict Details**:
   ```
   📝 Conflict 1/4: src/auth/login.ts (lines 23-35)
   ═══════════════════════════════════════════════

   Your Changes (HEAD):
   ───────────────────────────────────────────────
   23 | async function authenticateUser(credentials) {
   24 |   const token = await generateToken(credentials);
   25 |   return { token, user: credentials.username };
   26 | }

   Incoming Changes (origin/main):
   ───────────────────────────────────────────────
   23 | async function authenticateUser(credentials) {
   24 |   const validatedCreds = await validateCredentials(credentials);
   25 |   const token = await generateToken(validatedCreds);
   26 |   return { token, user: validatedCreds };
   27 | }

   Conflict Type: Both modified same function
   Recommendation: Keep incoming (adds validation)
   Auto-resolve: No (requires manual review)
   ```

4. **Auto-Resolve Simple Conflicts** (if --auto-resolve):
   - Package.json version conflicts → keep main's version
   - Import statement additions → merge both
   - Whitespace-only conflicts → keep either
   - Documentation conflicts → keep both with markers

   ```
   🤖 Auto-Resolving Simple Conflicts
   ═══════════════════════════════════════════════

   Conflict 2/4: package.json (version field)
     Type: Version number conflict
     Resolution: Keep main's version (1.2.3)
     ✓ Auto-resolved

   Conflicts Remaining: 1 (requires manual resolution)
   ```

5. **Guide Manual Resolution**:
   ```
   🔧 Manual Resolution Required
   ═══════════════════════════════════════════════

   Please resolve conflicts in:
     src/auth/login.ts (1 conflict region)

   Steps:
     1. Open src/auth/login.ts in your editor
     2. Look for conflict markers:
        <<<<<<< HEAD
        =======
        >>>>>>> origin/main
     3. Choose which changes to keep (or combine both)
     4. Remove conflict markers
     5. Save the file

   After resolving all conflicts:
     git add src/auth/login.ts
     git commit -m "Resolve merge conflicts"

   Or run this command to continue:
     /synchronize-branch #42 --continue
   ```

6. **Wait for Manual Resolution**:
   - Exit command
   - User resolves conflicts manually
   - User runs with --continue flag

7. **Validate Resolution**:
   ```bash
   git diff --check  # Check for conflict markers
   ```

   If conflict markers still present:
   ```
   ❌ Conflicts Not Fully Resolved

   The following files still have conflict markers:
     src/auth/login.ts (line 45)

   Please resolve all conflicts before continuing.
   ```

8. **Complete Merge/Rebase**:
   ```bash
   # For merge:
   git commit -m "Resolve merge conflicts"

   # For rebase:
   git rebase --continue
   ```

### Step 6: Post-Sync Testing

1. **Run Tests Automatically**:
   ```
   🧪 Running Post-Sync Tests
   ═══════════════════════════════════════════════

   Test Framework: Jest
   Environment: Local worktree

   Running: npm test

   Results:
     ✓ 42 tests passed
     ✗ 3 tests failed

   Failed Tests:
     - Auth › OAuth login › validates credentials
     - Auth › OAuth login › handles errors
     - Auth › Session › persists correctly

   ⚠️  Tests failing after sync

   This may indicate:
     1. Breaking changes introduced in main
     2. Conflict resolution issues
     3. Dependencies need updating

   Next Steps:
     1. Review failed tests
     2. Fix issues in feature branch
     3. Re-run tests: /test #42
   ```

2. **If Tests Pass**:
   ```
   ✅ All Tests Passing
   ═══════════════════════════════════════════════

   Test Results:
     ✓ 45 tests passed
     ○ 3 tests skipped
     ───────────────────
     Total: 48 tests

   ✓ Feature branch is healthy after sync

   Ready to push changes!
   ```

### Step 7: Push Changes

1. **Determine Push Strategy**:
   - Merge: Normal push
   - Rebase: Force push with lease

2. **Display Push Instructions**:
   ```
   📤 Push Synchronized Changes
   ═══════════════════════════════════════════════

   Strategy: merge
   Command: git push origin feature/42-user-authentication

   This will push:
     - 1 merge commit
     - 5 feature commits (your work)
     - 0 conflicts

   Branch will be:
     ✓ Up-to-date with main
     ✓ Ready for PR creation
     ✓ Safe to merge back to main

   Push now? (yes/no)
   ```

3. **Execute Push** (if confirmed):
   ```bash
   git push origin feature/42-user-authentication

   # Or for rebase:
   git push --force-with-lease origin feature/42-user-authentication
   ```

4. **Display Success**:
   ```
   ✅ Branch Synchronized Successfully!
   ═══════════════════════════════════════════════

   Summary:
     Branch: feature/42-user-authentication
     Strategy: merge
     Conflicts: 1 resolved
     Tests: ✓ Passing (45/45)
     Pushed: ✓ Yes

   Branch Status:
     ✓ Up-to-date with main
     ✓ 5 commits ahead (your work)
     ✓ 0 commits behind
     ✓ Ready for PR

   Next Steps:
     1. Create PR: /create-pull-request #42
     2. Request review from team
     3. Address feedback: /address-pull-request-feedback
   ```

## Examples

### Example 1: Sync Current Branch
```
/synchronize-branch
```
Synchronizes your current branch with main using merge strategy.

### Example 2: Sync Specific Feature
```
/synchronize-branch #42
```
Synchronizes feature branch for issue #42 with main.

### Example 3: Use Rebase Strategy
```
/synchronize-branch #42 --strategy rebase
```
Rebases feature branch onto main for linear history.

### Example 4: Preview Changes
```
/synchronize-branch #42 --dry-run
```
Shows what would happen without actually synchronizing.

### Example 5: Auto-Resolve Conflicts
```
/synchronize-branch #42 --auto-resolve
```
Automatically resolves simple conflicts (package.json, whitespace, etc.).

### Example 6: Custom Main Branch
```
/synchronize-branch #42 --main-branch develop
```
Synchronizes with 'develop' branch instead of 'main'.

## Strategy Comparison

### Merge Strategy

**Pros**:
- ✅ Preserves complete history
- ✅ Safer for shared branches
- ✅ No history rewriting
- ✅ Easy to understand and trace changes

**Cons**:
- ❌ Creates merge commits (clutters history)
- ❌ Non-linear history
- ❌ More complex git graph

**Best For**:
- Shared feature branches
- Branches pushed to remote
- When preserving exact history matters
- Teams unfamiliar with rebase

### Rebase Strategy

**Pros**:
- ✅ Clean, linear history
- ✅ Easier to read git log
- ✅ No merge commits
- ✅ Professional-looking history

**Cons**:
- ❌ Rewrites history (changes SHAs)
- ❌ Requires force push
- ❌ Dangerous if others are working on branch
- ❌ More complex conflict resolution

**Best For**:
- Personal feature branches
- Branches not yet pushed
- Clean history requirements
- Experienced git users

## Conflict Resolution Guide

### Common Conflict Types

**1. Both Modified Same Lines**:
```diff
<<<<<<< HEAD
const result = performActionOldWay();
=======
const result = performActionNewWay();
>>>>>>> origin/main
```
**Resolution**: Choose the better implementation or combine both

**2. Addition vs Modification**:
```diff
<<<<<<< HEAD
function newFeature() {
  // your implementation
}
=======
// Function moved to utils/
>>>>>>> origin/main
```
**Resolution**: Check if function moved, use new location

**3. Package.json Conflicts**:
```diff
<<<<<<< HEAD
"version": "1.2.0"
=======
"version": "1.3.0"
>>>>>>> origin/main
```
**Resolution**: Usually keep main's version

**4. Import Statement Conflicts**:
```diff
<<<<<<< HEAD
import { A, B } from './module';
=======
import { A, C } from './module';
>>>>>>> origin/main
```
**Resolution**: Merge both: `import { A, B, C } from './module';`

## Error Handling

**Uncommitted Changes**:
```
⚠️  Uncommitted Changes Detected

You have uncommitted changes in:
  src/auth/login.ts (modified)
  src/utils/helpers.ts (modified)

Options:
  1. Commit changes now
  2. Stash changes: git stash
  3. Discard changes: git reset --hard

Cannot proceed until working directory is clean.
```

**Already Up-to-Date**:
```
ℹ️  Branch Already Up-to-Date

Your branch is already synchronized with main.

Status:
  ✓ 0 commits behind main
  ✓ 5 commits ahead (your work)
  ✓ No synchronization needed

No action required.
```

**Rebase in Progress**:
```
⚠️  Rebase Already in Progress

A previous rebase is incomplete.

Options:
  1. Continue rebase: git rebase --continue
  2. Abort rebase: git rebase --abort
  3. Skip current commit: git rebase --skip

Run: /synchronize-branch --continue
```

**Force Push Warning**:
```
⚠️  FORCE PUSH REQUIRED

After rebasing, you must force push to update remote branch.

⚠️  WARNING: Only do this if:
  ✓ You're the only one working on this branch
  ✓ No one else has pulled your commits
  ✓ You understand the risks

Command: git push --force-with-lease origin feature/42

Proceed? (yes/no)
```

## Configuration

Configure in `.claude/config/bumba-sandbox-config.json`:

```json
{
  "sync": {
    "defaultStrategy": "merge",
    "mainBranch": "main",
    "autoResolve": false,
    "autoTest": true,
    "autoPush": false
  }
}
```

**Options**:
- `defaultStrategy`: Default sync strategy (merge/rebase)
- `mainBranch`: Default main branch name
- `autoResolve`: Auto-resolve simple conflicts
- `autoTest`: Run tests after sync
- `autoPush`: Automatically push after successful sync

## Integration with Other Commands

**Before Sync**:
- Check status: `/show-status`
- Commit work: `git commit -am "WIP"`

**After Sync**:
- Run tests: `/test #42`
- Create PR: `/create-pull-request #42`
- Merge PR: `/merge-pull-request`

## Notes

- Always sync before creating a pull request
- Merge strategy is safer for beginners
- Rebase strategy creates cleaner history but requires caution
- Test after every sync to catch breaking changes early
- Use --force-with-lease instead of --force for safety
- Never rebase public/shared branches
- Sync frequently to minimize conflicts
- Keep feature branches short-lived to reduce sync complexity
- Use --dry-run first if uncertain about changes
- Auto-resolve is conservative - manual review recommended for important conflicts

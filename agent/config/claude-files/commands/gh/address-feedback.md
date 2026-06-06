---
name: address-feedback
description: Address PR review comments (Verification stage)
---

# /address-pull-request-feedback Command

Automatically addresses review feedback from a pull request by fetching comments, prioritizing issues, implementing fixes, and updating the PR.

## Usage

```
/address-pull-request-feedback <pr-number> [--auto-commit] [--retest]
```

## Parameters

- `<pr-number>` (required): Pull request number
- `--auto-commit` (optional): Automatically commit fixes (default: false)
- `--retest` (optional): Run tests after each fix (default: true)
- `--push` (optional): Automatically push updates (default: false)

## Workflow

### Step 1: Fetch Review Comments

```
📋 Fetching PR Feedback
═══════════════════════════════════════════════

PR #42: Implement user authentication
Reviews: 2

Review 1 by @reviewer1 (Changes Requested):
  Status: Changes requested
  Posted: 2 hours ago
  Comments: 8

Review 2 by @reviewer2 (Comment):
  Status: Commented
  Posted: 1 hour ago
  Comments: 3

Total Comments: 11
  🔴 Critical: 2
  🟡 Important: 5
  🟢 Suggestions: 4
```

### Step 2: Organize and Prioritize Comments

```
🎯 Prioritized Feedback
═══════════════════════════════════════════════

CRITICAL Issues (2):

1. SQL Injection Vulnerability
   File: src/auth/login.ts:67
   Reviewer: @reviewer1
   Comment: "This query is vulnerable to SQL injection"
   Code:
     ```typescript
     const query = `SELECT * FROM users WHERE email = '${email}'`;
     ```
   Suggested Fix: Use parameterized queries
   Priority: 🔴 Critical

2. Hardcoded Secret
   File: src/auth/oauth.ts:12
   Reviewer: @reviewer1
   Comment: "Never commit secrets to repository"
   Code:
     ```typescript
     const CLIENT_SECRET = "abc123...";
     ```
   Suggested Fix: Use environment variables
   Priority: 🔴 Critical

IMPORTANT Issues (5):

3. Missing Input Validation
   File: src/auth/login.ts:34
   Reviewer: @reviewer1
   Priority: 🟡 Important

4. N+1 Query Problem
   File: src/auth/login.ts:145
   Reviewer: @reviewer2
   Priority: 🟡 Important

[3 more...]

SUGGESTIONS (4):

9. Extract Duplicated Logic
   File: Multiple files
   Reviewer: @reviewer2
   Priority: 🟢 Suggestion

[3 more...]
```

### Step 3: Implement Fixes

```
🔧 Addressing Feedback
═══════════════════════════════════════════════

[1/11] Fixing: SQL Injection Vulnerability
      File: src/auth/login.ts:67

      Old code:
      ```typescript
      const query = `SELECT * FROM users WHERE email = '${email}'`;
      const user = await db.query(query);
      ```

      New code:
      ```typescript
      const query = 'SELECT * FROM users WHERE email = ?';
      const user = await db.query(query, [email]);
      ```

      ✓ Fixed

[2/11] Fixing: Hardcoded Secret
      File: src/auth/oauth.ts:12

      Old code:
      ```typescript
      const CLIENT_SECRET = "abc123...";
      ```

      New code:
      ```typescript
      const CLIENT_SECRET = process.env.OAUTH_CLIENT_SECRET;
      if (!CLIENT_SECRET) {
        throw new Error('Missing OAUTH_CLIENT_SECRET environment variable');
      }
      ```

      ✓ Fixed
      ⚠️  Note: Added to .env.example

[3/11] Fixing: Missing Input Validation
      File: src/auth/login.ts:34

      Added Zod validation schema:
      ```typescript
      const loginSchema = z.object({
        email: z.string().email(),
        password: z.string().min(12)
      });

      const validated = loginSchema.parse(credentials);
      ```

      ✓ Fixed

[Continues for all 11 issues...]

✅ All Fixes Applied
═══════════════════════════════════════════════

Fixed: 11/11 issues
  Critical: 2/2
  Important: 5/5
  Suggestions: 4/4

Files Modified: 5
  src/auth/login.ts
  src/auth/oauth.ts
  src/middleware/auth.ts
  .env.example
  package.json
```

### Step 4: Test Changes

```
🧪 Running Tests
═══════════════════════════════════════════════

Test Framework: Jest

Running: npm test

Results:
  ✓ 48 tests passed
  ○ 3 tests skipped
  Total: 51 tests

Coverage:
  Statements: 91.2% (+3.7%)
  Branches: 87.5% (+5.4%)
  Functions: 93.8% (+2.5%)

✓ All tests passing after fixes
```

### Step 5: Commit and Push Updates

```
📝 Committing Changes
═══════════════════════════════════════════════

Creating commit...

Commit Message:
```
Address PR feedback from @reviewer1 and @reviewer2

Critical fixes:
- Fix SQL injection vulnerability in login.ts
- Remove hardcoded OAuth secret, use environment variable

Important fixes:
- Add input validation with Zod
- Fix N+1 query problem with JOIN
- Add rate limiting middleware
- Improve error handling
- Add CSRF protection

Improvements:
- Extract duplicated validation logic
- Add JSDoc comments
- Update dependencies
- Refactor long functions

Resolves all review comments on PR #42
```

Committed: abc123def456
✓ Changes committed

📤 Pushing to Remote
═══════════════════════════════════════════════

Pushing to origin/feature/42-user-authentication...
✓ Pushed successfully

PR #42 updated
```

### Step 6: Re-request Review

```
🔔 Notifying Reviewers
═══════════════════════════════════════════════

Comment posted to PR:
```
@reviewer1 @reviewer2 I've addressed all feedback:

✅ Critical Issues (2/2):
- Fixed SQL injection vulnerability
- Removed hardcoded secret

✅ Important Issues (5/5):
- Added input validation
- Fixed N+1 query problem
- Added rate limiting
- Improved error handling
- Added CSRF protection

✅ Suggestions (4/4):
- Extracted duplicated logic
- Added documentation
- Updated dependencies
- Refactored complex functions

All tests passing. Ready for re-review!
```

✓ Review re-requested
✓ Reviewers notified
```

## Examples

### Example 1: Address All Feedback
```
/address-pull-request-feedback 42
```

### Example 2: Auto-commit and Push
```
/address-pull-request-feedback 42 --auto-commit --push
```

### Example 3: Skip Testing
```
/address-pull-request-feedback 42 --retest=false
```

## Error Handling

### Common Errors

**PR Not Found**:
```
❌ Error: Pull request #99 not found

GitHub API Response: 404 Not Found

Possible causes:
  1. PR number incorrect
  2. PR is in a different repository
  3. PR was deleted or closed

Solutions:
  1. Check PR number: gh pr list
  2. Verify repository: gh repo view
  3. Use correct PR number

Available PRs:
  #42: Implement user authentication (Open)
  #45: Add real-time features (Open)
  #47: Implement search (Draft)
```

**No Review Comments**:
```
⚠️  Warning: No review comments found on PR #42

PR Status: Open
Reviews: 0
Comments: 0

Possible reasons:
  1. PR hasn't been reviewed yet
  2. Reviews were deleted
  3. Reviews are in "pending" state

Actions:
  1. Request review: gh pr review --request @reviewer1
  2. Wait for reviews to be posted
  3. Check pending reviews: gh pr checks

Nothing to address. Exiting.
```

**Test Failures After Fixes**:
```
❌ Error: Tests failing after applying fixes

Addressed: 8/11 issues
  ✓ Critical: 2/2
  ✓ Important: 4/5
  ✓ Suggestions: 2/4

Test Results:
  ❌ 3 tests failing
  ✓ 45 tests passing

Failing tests:
  1. auth.test.ts:67 - Login with SQL injection test
  2. auth.test.ts:89 - OAuth callback test
  3. middleware.test.ts:34 - Rate limiting test

Cause: Fixes introduced new test failures

Actions Taken:
  ✗ Changes NOT committed (tests must pass)
  ✓ Fixes preserved in working directory
  ✓ Test output saved to test-output.log

Next Steps:
  1. Review failing tests
  2. Fix test issues manually
  3. Run tests again: npm test
  4. Resume: /address-pull-request-feedback 42 --auto-commit

Files modified but not committed:
  src/auth/login.ts
  src/auth/oauth.ts
  src/middleware/auth.ts
```

**GitHub API Rate Limit**:
```
❌ Error: GitHub API rate limit exceeded

API calls remaining: 0/5000
Reset time: 45 minutes

Progress so far:
  ✓ Fetched PR details
  ✓ Fetched review comments (8/11)
  ❌ Cannot fetch remaining comments

Partial data available:
  Critical: 2 issues
  Important: 4 issues
  Suggestions: 2 issues (incomplete)

Solutions:
  1. Wait 45 minutes and retry
  2. Use GitHub Personal Access Token with higher limits
  3. Continue with partial data (may miss some feedback)

To continue with partial data:
  /address-pull-request-feedback 42 --partial

Note: Authenticated requests have 5000/hour limit
      Unauthenticated: 60/hour limit
```

**Merge Conflict During Fixes**:
```
❌ Error: Merge conflict detected

File: src/auth/login.ts
Conflict: Line 67 (attempting to fix SQL injection)

Current state:
  <<<<<<< HEAD
  const query = `SELECT * FROM users WHERE email = '${email}'`;
  =======
  const query = 'SELECT * FROM users WHERE email = ?';
  >>>>>>> feedback-fixes

Cause: Branch updated since PR was opened

Solutions:
  1. Synchronize branch first: /synchronize-branch
  2. Resolve conflicts manually
  3. Retry after sync: /address-pull-request-feedback 42

Recommended workflow:
  1. /synchronize-branch (fixes conflicts with main)
  2. /address-pull-request-feedback 42 (applies fixes)
  3. /test #42 (verifies everything works)

Aborting fixes to prevent data loss.
Working directory is clean.
```

**Permission Denied**:
```
❌ Error: Cannot push to remote repository

Git error: Permission denied (publickey)
Remote: git@github.com:user/repo.git

Cause: No push access or SSH key not configured

Solutions:
  1. Check repository permissions: gh repo view
  2. Verify SSH key: ssh -T git@github.com
  3. Use HTTPS instead: git remote set-url origin https://github.com/user/repo.git
  4. Check GitHub token: gh auth status

Fixes have been committed locally:
  Commit: abc123def456
  Branch: feature/42-user-authentication

Manual push:
  git push origin feature/42-user-authentication

Or fix auth and retry:
  /address-pull-request-feedback 42 --push
```

**Unable to Auto-Fix Issue**:
```
⚠️  Warning: Cannot automatically fix 3 issues

Addressed: 8/11 issues (73%)
  ✓ Critical: 2/2 (auto-fixed)
  ✓ Important: 4/5 (1 requires manual fix)
  ⚠️  Suggestions: 2/4 (2 require manual fix)

Issues requiring manual attention:

1. Refactor complex function (Important)
   File: src/auth/login.ts:145
   Comment: "This function is too complex. Break into smaller functions."
   Reason: Requires architectural decision
   Action: Review and refactor manually

2. Improve error messages (Suggestion)
   File: src/auth/oauth.ts:89
   Comment: "Error messages should be more user-friendly"
   Reason: Requires UX decision
   Action: Review and improve manually

3. Add more test cases (Suggestion)
   File: tests/auth.test.ts:12
   Comment: "Need edge case testing"
   Reason: Requires test design
   Action: Add tests manually

Auto-fixed issues have been committed.
Manual fixes needed for 100% completion.

Review TODO comments added to files for manual fixes.
```

### Recovery Actions

**Automatic Recovery**:
- Saves progress even if tests fail
- Commits successful fixes separately
- Preserves working directory state
- Adds TODO comments for manual fixes
- Provides detailed error messages with solutions

**Manual Recovery**:
```bash
# Check current state
git status

# See what was fixed
git diff

# Review failing tests
npm test

# Fix manually
vim src/auth/login.ts

# Resume automated process
/address-pull-request-feedback 42 --auto-commit --push
```

**Rollback if Needed**:
```bash
# Undo all changes
git reset --hard HEAD

# Or undo specific file
git checkout src/auth/login.ts

# Retry from scratch
/address-pull-request-feedback 42
```

## Notes

- Fetches all review comments from GitHub
- Prioritizes critical issues first
- Applies fixes automatically when possible
- Runs tests to verify fixes
- Commits with detailed message
- Notifies reviewers when complete
- Re-requests review automatically
- Will not commit if tests fail
- Adds TODO comments for issues that need manual fixes
- Preserves working directory state on errors
- Requires GitHub API access and push permissions

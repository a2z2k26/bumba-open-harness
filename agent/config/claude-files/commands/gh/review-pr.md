---
name: review-pr
description: AI-powered code review (Verification stage)
---

# /review-pull-request Command

Performs comprehensive AI-powered code review of a pull request, analyzing code quality, security, performance, and test coverage, then posts detailed feedback to GitHub.

## Usage

```
/review-pull-request <pr-number> [--post] [--severity <all|high|medium>]
```

## Parameters

- `<pr-number>` (required): Pull request number to review
- `--post` (optional): Post review comments to GitHub (default: preview only)
- `--severity <level>` (optional): Minimum severity to report (default: all)
  - `all`: Show all findings
  - `high`: Show only high-severity issues
  - `medium`: Show high and medium severity issues
- `--auto-approve` (optional): Auto-approve if no critical issues found
- `--focus <area>` (optional): Focus review on specific area
  - `security`: Security vulnerabilities only
  - `performance`: Performance issues only
  - `style`: Code style and conventions
  - `tests`: Test coverage and quality

## Workflow

### Step 1: Fetch Pull Request Data

1. **Retrieve PR Details**:
   ```
   📋 Pull Request Review
   ═══════════════════════════════════════════════

   PR #42: Implement user authentication
   Author: @developer
   Branch: feature/42-user-authentication → main

   Reviewers: @reviewer1, @reviewer2
   Status: Pending review
   Created: 2 days ago
   Last Updated: 1 hour ago
   ```

2. **Get Changed Files**:
   ```bash
   gh pr view 42 --json files
   ```

   ```
   📄 Files Changed: 12
   ═══════════════════════════════════════════════

   Backend (8 files):
     + src/auth/login.ts (+145 lines)
     + src/auth/oauth.ts (+89 lines)
     M src/auth/index.ts (+12 -3 lines)
     + src/middleware/auth.ts (+67 lines)
     M src/routes/index.ts (+8 -2 lines)
     + tests/auth/login.test.ts (+156 lines)
     + tests/auth/oauth.test.ts (+92 lines)
     M tests/setup.ts (+5 -1 lines)

   Frontend (2 files):
     + src/components/LoginButton.tsx (+45 lines)
     M src/App.tsx (+15 -3 lines)

   Documentation (2 files):
     M README.md (+23 -5 lines)
     + docs/authentication.md (+78 lines)

   Total Changes: +735 / -14 lines
   ```

3. **Download File Diffs**:
   ```bash
   gh pr diff 42
   ```

### Step 2: Code Quality Analysis

1. **Analyze Readability**:
   ```
   📖 Code Readability Analysis
   ═══════════════════════════════════════════════

   Overall Score: 8.5/10 (Good)

   Strengths:
     ✓ Clear function names (authenticateUser, generateToken)
     ✓ Consistent naming conventions
     ✓ Good use of TypeScript types
     ✓ Well-structured modules

   Areas for Improvement:
     ⚠️  Long function in src/auth/login.ts:45 (authenticateUser)
         Lines: 67 (recommended: <50)
         Suggestion: Extract token generation logic

     ⚠️  Complex conditional in src/auth/oauth.ts:89
         Nesting depth: 4 levels
         Suggestion: Use early returns to reduce nesting

     ⚠️  Magic numbers in src/middleware/auth.ts:34
         Values: 3600, 24
         Suggestion: Use named constants (TOKEN_EXPIRY, etc.)
   ```

2. **Analyze Code Conventions**:
   ```
   📏 Code Conventions
   ═══════════════════════════════════════════════

   Overall Compliance: 92%

   TypeScript:
     ✓ Strict mode enabled
     ✓ No implicit any
     ✓ Proper type annotations
     ⚠️  Missing return type in 2 functions

   Naming:
     ✓ camelCase for variables/functions
     ✓ PascalCase for classes/components
     ⚠️  Inconsistent interface naming (I prefix)

   Imports:
     ✓ Absolute imports used consistently
     ✓ Proper import ordering
     ✓ No circular dependencies

   Comments:
     ⚠️  Low comment density (5%)
         Recommendation: Add JSDoc for public APIs
   ```

3. **Detect Code Smells**:
   ```
   🔍 Code Smells Detected
   ═══════════════════════════════════════════════

   Medium Severity (3 issues):

   1. Duplicated Logic
      Location: src/auth/login.ts:45, src/auth/oauth.ts:67
      Pattern: Token validation logic duplicated
      Impact: Maintenance burden
      Suggestion: Extract to shared utility function

   2. Long Parameter List
      Location: src/auth/oauth.ts:23 (handleOAuthCallback)
      Parameters: 7
      Recommendation: Use options object pattern

   3. God Class
      Location: src/auth/login.ts (AuthService)
      Lines: 245
      Methods: 12
      Suggestion: Split into AuthService and TokenService

   Low Severity (5 issues):
     - Unused imports (2 occurrences)
     - TODO comments (3 occurrences)
   ```

### Step 3: Security Analysis

1. **Scan for Common Vulnerabilities**:
   ```
   🔒 Security Analysis
   ═══════════════════════════════════════════════

   Overall Security Score: 7/10 (Good with concerns)

   CRITICAL Issues (0):
     None found ✓

   HIGH Severity (2):

   1. Potential SQL Injection
      File: src/auth/login.ts
      Line: 67
      Code: `SELECT * FROM users WHERE email = '${email}'`
      Risk: SQL injection attack vector
      Fix: Use parameterized queries
      Example:
        ```typescript
        // Bad
        const query = `SELECT * FROM users WHERE email = '${email}'`;

        // Good
        const query = 'SELECT * FROM users WHERE email = ?';
        await db.query(query, [email]);
        ```

   2. Hardcoded Secret
      File: src/auth/oauth.ts
      Line: 12
      Code: const CLIENT_SECRET = "abc123...";
      Risk: Exposed credentials in version control
      Fix: Use environment variables
      Example:
        ```typescript
        const CLIENT_SECRET = process.env.OAUTH_CLIENT_SECRET;
        if (!CLIENT_SECRET) throw new Error('Missing secret');
        ```

   MEDIUM Severity (3):

   3. Missing Input Validation
      File: src/auth/login.ts
      Line: 34
      Risk: Unvalidated user input
      Suggestion: Add Zod or Joi validation schema

   4. Weak Password Requirements
      File: src/auth/login.ts
      Line: 89
      Current: Minimum 6 characters
      Recommendation: Minimum 12 characters + complexity

   5. Missing Rate Limiting
      File: src/routes/index.ts
      Risk: Brute force attacks
      Suggestion: Add express-rate-limit middleware
   ```

2. **Check for XSS Vulnerabilities**:
   ```
   🛡️  XSS Vulnerability Check
   ═══════════════════════════════════════════════

   Potential XSS Risks: 1

   1. Unsafe HTML Rendering
      File: src/components/LoginButton.tsx
      Line: 23
      Code: dangerouslySetInnerHTML={{__html: userMessage}}
      Risk: XSS if userMessage contains untrusted input
      Fix: Sanitize input or use safe React rendering
   ```

3. **Check Authentication/Authorization**:
   ```
   🔑 Authentication/Authorization Check
   ═══════════════════════════════════════════════

   ✓ JWT tokens used correctly
   ✓ Passwords hashed with bcrypt (rounds: 12)
   ✓ Session management implemented
   ⚠️  Token expiration: 24 hours (consider shorter)
   ⚠️  No token refresh mechanism
   ⚠️  Missing CSRF protection
   ```

### Step 4: Performance Analysis

1. **Identify Performance Issues**:
   ```
   ⚡ Performance Analysis
   ═══════════════════════════════════════════════

   Overall Performance: Good with improvements needed

   HIGH Impact (1):

   1. N+1 Query Problem
      File: src/auth/login.ts
      Line: 145
      Code:
        ```typescript
        const users = await getUsers();
        for (const user of users) {
          const profile = await getProfile(user.id); // N queries!
        }
        ```
      Impact: Database performance degradation
      Fix: Use JOIN or eager loading
      Example:
        ```typescript
        const users = await getUsersWithProfiles(); // 1 query
        ```

   MEDIUM Impact (2):

   2. Synchronous File Operations
      File: src/auth/oauth.ts
      Line: 67
      Code: fs.readFileSync('./config.json')
      Impact: Blocks event loop
      Fix: Use async fs.promises.readFile()

   3. Large Bundle Size
      File: src/components/LoginButton.tsx
      Import: lodash (entire library)
      Size: 70KB
      Fix: Import specific functions (lodash/pick)
   ```

2. **Memory Leak Detection**:
   ```
   💾 Memory Analysis
   ═══════════════════════════════════════════════

   Potential Memory Leaks: 1

   1. Event Listener Not Cleaned Up
      File: src/components/LoginButton.tsx
      Line: 34
      Code: useEffect(() => { window.addEventListener(...) })
      Risk: Memory leak if component unmounts
      Fix: Return cleanup function in useEffect
   ```

### Step 5: Test Coverage Analysis

1. **Analyze Test Quality**:
   ```
   🧪 Test Coverage Analysis
   ═══════════════════════════════════════════════

   Test Files: 2
   Total Tests: 47

   Coverage:
     Statements: 87.5% (245/280) ✓
     Branches: 82.1% (78/95) ⚠️
     Functions: 91.3% (42/46) ✓
     Lines: 88.2% (241/273) ✓

   Uncovered Areas:

   1. src/auth/login.ts (Lines 145-167)
      Function: handleFailedLogin
      Coverage: 0%
      Risk: Error handling path not tested
      Recommendation: Add test for failed login scenarios

   2. src/auth/oauth.ts (Lines 89-102)
      Function: refreshToken
      Coverage: 45%
      Risk: Token refresh edge cases not tested
      Recommendation: Add tests for expiration, invalid tokens

   3. src/middleware/auth.ts (Lines 34-42)
      Branch: Token validation error paths
      Coverage: 50%
      Risk: Error scenarios not fully tested
   ```

2. **Test Quality Assessment**:
   ```
   ✅ Test Quality
   ═══════════════════════════════════════════════

   Strengths:
     ✓ Good use of describe/it structure
     ✓ Proper mocking of dependencies
     ✓ Clear test names
     ✓ Tests are independent

   Improvements Needed:
     ⚠️  Missing edge case tests (3 scenarios)
     ⚠️  No integration tests for OAuth flow
     ⚠️  No tests for concurrent login attempts
     ⚠️  Missing negative test cases
   ```

### Step 6: Generate Review Comments

1. **Format Comments by File**:
   ```
   📝 Review Comments Generated
   ═══════════════════════════════════════════════

   Total Comments: 12
     Critical: 0
     High: 2
     Medium: 5
     Low: 5

   By File:
     src/auth/login.ts: 5 comments
     src/auth/oauth.ts: 3 comments
     src/middleware/auth.ts: 2 comments
     src/components/LoginButton.tsx: 2 comments
   ```

2. **Generate Summary Comment**:
   ```markdown
   ## Code Review Summary

   **Overall Assessment**: Request Changes ⚠️

   Thank you for this PR! The authentication implementation is well-structured and mostly follows best practices. However, there are **2 high-severity security issues** that must be addressed before merging.

   ### Strengths ✅
   - Clean, readable code with good TypeScript usage
   - Comprehensive test coverage (88%)
   - Well-documented API endpoints
   - Good error handling in most areas

   ### Critical Issues ❌
   1. **SQL Injection Vulnerability** (HIGH) - `src/auth/login.ts:67`
   2. **Hardcoded Secret** (HIGH) - `src/auth/oauth.ts:12`

   ### Improvements Needed ⚠️
   - Add input validation with Zod/Joi
   - Fix N+1 query problem in user loading
   - Add token refresh mechanism
   - Increase test coverage for error paths

   ### Optional Enhancements 💡
   - Extract duplicated token validation logic
   - Add rate limiting middleware
   - Consider shorter token expiration

   Please address the critical issues and I'll re-review. Great work overall!
   ```

### Step 7: Post Review to GitHub (if --post)

1. **Preview Mode** (default):
   ```
   📋 Review Preview (Not Posted)
   ═══════════════════════════════════════════════

   Review Status: REQUEST_CHANGES
   Comments: 12 inline + 1 summary

   This is a preview. Use --post to submit to GitHub.

   Inline Comments:

   [src/auth/login.ts:67]
   🔴 HIGH - SQL Injection Vulnerability
   ─────────────────────────────────────────────
   The query uses string interpolation which is vulnerable to SQL injection.

   ```suggestion
   const query = 'SELECT * FROM users WHERE email = ?';
   await db.query(query, [email]);
   ```

   [src/auth/oauth.ts:12]
   🔴 HIGH - Hardcoded Secret
   ─────────────────────────────────────────────
   Never commit secrets to version control.

   ```suggestion
   const CLIENT_SECRET = process.env.OAUTH_CLIENT_SECRET;
   if (!CLIENT_SECRET) throw new Error('Missing OAuth secret');
   ```

   ...
   ```

2. **Post to GitHub**:
   ```bash
   gh api repos/{owner}/{repo}/pulls/{pr}/reviews \
     --method POST \
     --field event="REQUEST_CHANGES" \
     --field body="<summary>" \
     --field comments='[...]'
   ```

   ```
   ✅ Review Posted to GitHub
   ═══════════════════════════════════════════════

   PR #42: Implement user authentication

   Review Status: Changes Requested
   Comments Posted: 12 inline + 1 summary

   Summary Comment: Posted ✓
   Inline Comments: Posted ✓

   View Review: https://github.com/owner/repo/pull/42#pullrequestreview-123456

   Notifications Sent:
     - @developer (PR author)
     - @reviewer1 (requested reviewer)
   ```

3. **Auto-Approve Option**:
   ```
   ✅ Auto-Approve Eligible
   ═══════════════════════════════════════════════

   Review completed with no critical issues found.

   Findings:
     Critical: 0
     High: 0
     Medium: 2 (acceptable)
     Low: 5 (acceptable)

   All checks passed:
     ✓ No security vulnerabilities
     ✓ Good test coverage (>80%)
     ✓ No performance issues
     ✓ Code quality acceptable

   Auto-approving PR #42...
   ✓ Approved with minor suggestions

   Status: APPROVED ✅
   ```

## Examples

### Example 1: Preview Review
```
/review-pull-request 42
```
Analyzes PR #42 and shows review without posting to GitHub.

### Example 2: Post Review
```
/review-pull-request 42 --post
```
Analyzes and posts review comments to GitHub.

### Example 3: Security Focus
```
/review-pull-request 42 --focus security --post
```
Reviews only security issues and posts findings.

### Example 4: High Severity Only
```
/review-pull-request 42 --severity high --post
```
Reports and posts only high-severity issues.

### Example 5: Auto-Approve
```
/review-pull-request 42 --post --auto-approve
```
Reviews PR and auto-approves if no critical issues found.

## Review Criteria

### Code Quality
- **Readability**: Clear variable names, proper structure
- **Maintainability**: DRY principle, modular design
- **Conventions**: Style guide compliance
- **Documentation**: Comments, JSDoc, README

### Security
- **Injection**: SQL, XSS, command injection
- **Authentication**: Proper auth implementation
- **Authorization**: Access control checks
- **Secrets**: No hardcoded credentials
- **Dependencies**: No known vulnerabilities

### Performance
- **Database**: Query optimization, N+1 problems
- **Algorithms**: Time/space complexity
- **Resources**: Memory leaks, file handles
- **Bundle Size**: Import optimization

### Testing
- **Coverage**: Line, branch, function coverage
- **Quality**: Edge cases, error paths
- **Integration**: End-to-end scenarios
- **Independence**: No test interdependencies

## Error Handling

**PR Not Found**:
```
❌ Error: Pull request not found

PR #999 does not exist.

Verify the PR number and try again.
```

**No Changes in PR**:
```
ℹ️  No Code Changes to Review

PR #42 only modifies documentation files.

No code review needed.
```

**GitHub API Error**:
```
❌ Error: GitHub API request failed

Status: 403 Forbidden
Message: API rate limit exceeded

Wait 15 minutes and try again, or use a different token.
```

**Review Already Posted**:
```
⚠️  Review Already Exists

You previously reviewed PR #42 1 hour ago.

Options:
  1. Update existing review (not supported by GitHub API)
  2. Post new review (will create separate review)
  3. Dismiss old review first: gh api repos/owner/repo/pulls/42/reviews/123 -X PUT -f event=DISMISS

Continue with new review? (yes/no)
```

## Configuration

Configure in `.claude/config/bumba-sandbox-config.json`:

```json
{
  "review": {
    "autoPost": false,
    "defaultSeverity": "all",
    "securityChecks": true,
    "performanceChecks": true,
    "testCoverageThreshold": 80,
    "autoApproveThreshold": "medium"
  }
}
```

**Options**:
- `autoPost`: Automatically post reviews (default: false)
- `defaultSeverity`: Default severity filter
- `securityChecks`: Enable security analysis
- `performanceChecks`: Enable performance analysis
- `testCoverageThreshold`: Minimum coverage percentage
- `autoApproveThreshold`: Auto-approve if no issues above this level

## Integration

**PR Review Workflow**:
1. Developer creates PR
2. `/review-pull-request 42` - Initial review
3. Developer fixes issues
4. `/review-pull-request 42 --post` - Final review
5. `/merge-pull-request 42` - Merge if approved

## Notes

- Review is AI-powered - always use human judgment
- Security findings should be verified manually
- Performance suggestions are heuristic-based
- Test coverage is calculated from code diffs
- Review focuses on changed code, not entire codebase
- Some issues may be false positives
- Use --focus to target specific concerns
- Reviews can be updated by dismissing old and posting new
- Auto-approve requires careful configuration
- Consider team review guidelines when configuring thresholds

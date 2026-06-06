---
name: test
description: Run tests in sandbox
---

# /sandbox-test Command

Runs tests exclusively in a Bumba Sandbox environment, providing isolated testing with full environment control.

## Usage

```
/sandbox-test #<issue> [--framework <framework>] [--coverage]
```

## Parameters

- `#<issue>` (required): Issue number to test
- `--framework <framework>` (optional): Test framework (jest, pytest, go test, cargo test)
- `--coverage` (optional): Generate coverage report
- `--watch` (optional): Run tests in watch mode
- `--parallel` (optional): Run tests in parallel
- `--verbose` (optional): Verbose output

## Workflow

```
🧪 Sandbox Test Runner
═══════════════════════════════════════════════

Issue: #42 - User Authentication
Sandbox: sbx_abc123xyz
Framework: Jest (auto-detected)

[1/5] Connecting to Sandbox
      ✓ Connected to sbx_abc123xyz
      Worktree: worktrees/feature-42-auth

[2/5] Detecting Test Framework
      ✓ Found package.json with jest
      ✓ Test command: npm test
      Test files: 8 found

[3/5] Running Tests in Sandbox

      Executing: npm test

      PASS  src/auth/login.test.ts
        ✓ should validate email format (23ms)
        ✓ should validate password strength (15ms)
        ✓ should prevent SQL injection (32ms)
        ✓ should handle invalid credentials (18ms)

      PASS  src/auth/oauth.test.ts
        ✓ should handle OAuth flow (45ms)
        ✓ should validate state parameter (12ms)
        ✓ should exchange code for token (38ms)

      PASS  src/middleware/auth.test.ts
        ✓ should verify JWT tokens (28ms)
        ✓ should handle expired tokens (15ms)
        ✓ should enforce rate limiting (42ms)

[4/5] Generating Coverage Report

      Coverage Summary:
      ─────────────────────────────────────────
      Statements   : 92.5% ( 148/160 )
      Branches     : 88.7% ( 71/80 )
      Functions    : 95.2% ( 40/42 )
      Lines        : 93.1% ( 135/145 )
      ─────────────────────────────────────────

      Uncovered files:
      • src/auth/legacy.ts (0% coverage)
      • src/auth/mfa.ts (45% coverage)

[5/5] Test Results

      ✅ All Tests Passed!
      ═══════════════════════════════════════════════

      Test Suite: #42 - User Authentication
      Tests Passed: 48/48 (100%)
      Duration: 2.3 seconds
      Coverage: 93.1%

      Sandbox: sbx_abc123xyz
      Status: Tests passed, sandbox kept running

      Coverage Report: coverage/lcov-report/index.html
```

## Examples

### Example 1: Basic Sandbox Testing
```
/sandbox-test #42
```

### Example 2: With Coverage
```
/sandbox-test #42 --coverage
```

### Example 3: Specific Framework
```
/sandbox-test #45 --framework pytest --verbose
```

### Example 4: Watch Mode
```
/sandbox-test #42 --watch
```

### Example 5: Parallel Execution
```
/sandbox-test #42 --parallel --coverage
```

## Advantages Over Regular /test

**Isolation**:
- Clean environment per test run
- No local dependency conflicts
- Consistent results

**Environment Control**:
- Test with different Node versions
- Test with different databases
- Test with specific system packages

**Resource Management**:
- Dedicated CPU/memory for tests
- No impact on local machine
- Parallel test execution without local resource limits

## Integration

- Uses `execute_command` MCP tool for test execution
- Accesses sandbox filesystem for coverage reports
- Integrates with `/sandbox-status` for monitoring
- Works with existing sandbox from `/implement-feature`

## Error Handling

### Common Errors

**Sandbox Not Found**:
```
❌ Error: No sandbox found for issue #42

Status: Issue #42 is in local mode

Cannot run sandbox tests for local mode features.

Solutions:
  1. Switch to sandbox mode:
     /implement-feature #42 --mode sandbox

  2. Use regular test command:
     /test #42

  3. Create sandbox manually:
     Create sandbox via MCP and retry

Note: /sandbox-test requires an active sandbox for the issue.
```

**Test Framework Not Detected**:
```
❌ Error: Cannot detect test framework

Sandbox: sbx_abc123xyz
Checked for: jest, pytest, go test, cargo test
Found: None

Possible causes:
  1. No test framework installed
  2. No test configuration file
  3. Tests not yet written

Solutions:
  1. Specify framework manually:
     /sandbox-test #42 --framework jest

  2. Install test framework in sandbox:
     /sandbox-exec sbx_abc123xyz "npm install --save-dev jest"

  3. Check test setup in repository

Manual test execution:
  /sandbox-exec sbx_abc123xyz "npm test"
```

**Test Failures**:
```
❌ Tests Failed

Issue: #42 - User Authentication
Failed: 3/48 tests

Failing Tests:
  1. src/auth/login.test.ts:67
     ✗ should prevent SQL injection
     Expected: Parameterized query
     Received: String concatenation

  2. src/auth/oauth.test.ts:45
     ✗ should validate state parameter
     Expected: State mismatch error
     Received: No error thrown

  3. src/middleware/auth.test.ts:89
     ✗ should enforce rate limiting
     Expected: 429 status code
     Received: 200 status code

Test Summary:
  ✓ Passed: 45/48 (93.75%)
  ✗ Failed: 3/48 (6.25%)

Sandbox preserved for debugging:
  /sandbox-debug sbx_abc123xyz

View full test output:
  /sandbox-exec sbx_abc123xyz "npm test -- --verbose"
```

**Coverage Tool Not Found**:
```
⚠️  Warning: Coverage tool not available

Framework: Jest
Coverage command: npm test -- --coverage
Error: coverage not configured

Test execution: Success (48/48 passed)
Coverage report: Not generated

To enable coverage:
  1. Configure coverage in package.json:
     "jest": { "collectCoverage": true }

  2. Install coverage tool:
     /sandbox-exec sbx_abc123xyz "npm install --save-dev @jest/coverage"

  3. Retry with coverage:
     /sandbox-test #42 --coverage

Tests passed without coverage report.
```

**Sandbox Connection Error**:
```
❌ Error: Cannot connect to sandbox

Sandbox ID: sbx_abc123xyz
Sandbox API Error: Sandbox not responding

Possible causes:
  1. Sandbox crashed
  2. Sandbox was terminated
  3. Network connectivity issues

Solutions:
  1. Check sandbox status:
     /sandbox-status

  2. Restart sandbox:
     /implement-feature #42 --mode sandbox

  3. Check sandbox service status

If sandbox is crashed, logs are preserved for debugging.
```

### Recovery Actions

**Automatic Recovery**:
- Preserves sandbox on test failures for debugging
- Saves test output to logs
- Generates partial coverage reports when possible
- Provides clear error messages with solutions

**Manual Recovery**:
```bash
# Check sandbox status
/sandbox-status

# View test logs
/sandbox-exec sbx_abc123xyz "cat test-output.log"

# Debug failing tests
/sandbox-debug sbx_abc123xyz

# Re-run specific test
/sandbox-exec sbx_abc123xyz "npm test -- src/auth/login.test.ts"

# Fix code and retry
/sandbox-test #42
```

## Notes

- Requires active sandbox for the issue
- Auto-detects test framework from project files
- Preserves sandbox on failures for debugging
- Coverage reports saved in sandbox filesystem
- Can be used with `/sandbox-debug` for interactive debugging
- Supports all major test frameworks (Jest, pytest, Go, Cargo)
- Test output streamed in real-time for long-running tests

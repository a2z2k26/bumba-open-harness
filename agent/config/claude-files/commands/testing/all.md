---
name: all
description: Run all tests in parallel (Verification stage)
---

# /test-all Command

Runs tests for all active features in parallel, providing comprehensive test coverage across the entire codebase.

## Usage

```
/test-all [--mode <mode>] [--coverage] [--fail-fast]
```

## Parameters

- `--mode <mode>` (optional): Test mode (all, local, sandbox) - default: all
- `--coverage` (optional): Generate coverage reports for all features
- `--fail-fast` (optional): Stop on first test failure
- `--parallel <n>` (optional): Maximum parallel test runs (default: 5)
- `--summary-only` (optional): Show only summary, hide individual test output

## Workflow

```
🧪 Test All Active Features
═══════════════════════════════════════════════

Discovering active features...

Active Features Found: 8
  Local Mode: 3 features
  Sandbox Mode: 5 features

Test Plan:
  #42: User Authentication (sandbox)
  #43: Database Migration (local)
  #45: Real-time Features (sandbox)
  #47: Search Feature (sandbox)
  #48: Documentation (local)
  #49: Performance Optimization (sandbox)
  #50: API Endpoints (sandbox)
  #51: UI Components (local)

───────────────────────────────────────────────

[1/8] Testing #42: User Authentication (sandbox)
      Framework: Jest
      Status: Running...
      ✓ 48/48 tests passed (2.3s)
      Coverage: 93.1%

[2/8] Testing #43: Database Migration (local)
      Framework: pytest
      Status: Running...
      ✓ 15/15 tests passed (1.1s)
      Coverage: 87.5%

[3/8] Testing #45: Real-time Features (sandbox)
      Framework: Jest
      Status: Running...
      ✓ 32/32 tests passed (3.8s)
      Coverage: 91.2%

[4/8] Testing #47: Search Feature (sandbox)
      Framework: Jest
      Status: Running...
      ✗ 2/28 tests failed (2.1s)
      Coverage: 78.9%

[5/8] Testing #48: Documentation (local)
      Framework: N/A
      Status: Skipped (no tests)

[6/8] Testing #49: Performance Optimization (sandbox)
      Framework: Jest
      Status: Running...
      ✓ 22/22 tests passed (4.2s)
      Coverage: 95.4%

[7/8] Testing #50: API Endpoints (sandbox)
      Framework: Jest
      Status: Running...
      ✓ 67/67 tests passed (5.1s)
      Coverage: 89.7%

[8/8] Testing #51: UI Components (local)
      Framework: Jest
      Status: Running...
      ✓ 54/54 tests passed (3.4s)
      Coverage: 92.3%

───────────────────────────────────────────────

✅ Test All Complete!
═══════════════════════════════════════════════

Overall Results:
  Total Features: 8
  Features Tested: 7
  Features Skipped: 1 (no tests)

Test Summary:
  Total Tests: 258
  ✓ Passed: 256 (99.2%)
  ✗ Failed: 2 (0.8%)
  Duration: 21.8 seconds

Coverage Summary:
  Average: 90.3%
  Highest: #49 Performance (95.4%)
  Lowest: #47 Search (78.9%)

Failed Features:
  #47: Search Feature (2 failures)
    • src/search/query.test.ts:34
    • src/search/index.test.ts:67

Recommendations:
  1. Fix failing tests in #47
  2. Add tests for #48 (Documentation)
  3. Improve coverage for #47 (78.9% → 90%+)

Next Steps:
  Fix failures: /test #47 --verbose
  Debug: /sandbox-debug sbx_search47
```

## Examples

### Example 1: Test Everything
```
/test-all
```

### Example 2: Only Sandbox Tests
```
/test-all --mode sandbox
```

### Example 3: With Coverage
```
/test-all --coverage
```

### Example 4: Fail Fast
```
/test-all --fail-fast
```

### Example 5: Summary Only
```
/test-all --summary-only --coverage
```

## Integration

- Discovers features from worktrees and sandboxes
- Uses `/test` for local features
- Uses `/sandbox-test` for sandbox features
- Aggregates results from all test runs
- Integrates with `/show-status` for feature discovery

## Error Handling

### Common Errors

**No Active Features**:
```
⚠️  Warning: No active features found

Worktrees: 0
Sandboxes: 0

Nothing to test.

To create features:
  /implement-feature #<issue>

To view all features:
  /show-status
```

**All Tests Failed**:
```
❌ Critical: All features have test failures

Features Tested: 5
All Failed: 5

This indicates a systemic issue.

Possible causes:
  1. Environment configuration error
  2. Shared dependency broken
  3. Database/service not running

Recommendations:
  1. Check base branch tests: git checkout main && npm test
  2. Check environment variables: cat .env
  3. Check service dependencies: docker ps
  4. Review recent changes

Individual feature results saved for debugging.
```

**Parallel Execution Limit**:
```
⚠️  Warning: Reducing parallel execution

Requested: 20 concurrent tests
System Limit: 10 concurrent processes
Actual: 10 concurrent tests

Features will be tested in batches of 10.

To increase limit:
  /config set parallel.maxConcurrent 20

Note: High parallelism may impact system performance.
```

### Recovery Actions

**Automatic Recovery**:
- Continues testing other features on individual failures
- Aggregates all results even with failures
- Preserves failed sandboxes for debugging
- Generates partial coverage reports

**Manual Recovery**:
```bash
# Re-test failed features only
/test #47 --verbose

# Debug specific failure
/sandbox-debug sbx_search47

# Re-run all tests
/test-all

# Check individual feature status
/show-status
```

## Notes

- Tests features in parallel for speed
- Supports both local and sandbox modes
- Provides aggregated coverage metrics
- Continues on individual failures unless --fail-fast
- Preserves failed sandboxes for debugging
- Useful for CI/CD integration
- Recommended before creating pull requests

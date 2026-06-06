---
name: feature
description: Run tests for single feature (Verification stage)
---

# /test Command

Runs tests for a feature in either local or sandbox environment.

## Usage

```
/test [#<issue-number>] [--mode <local|sandbox>] [--compare]
```

## Parameters

- `#<issue-number>` (optional): Issue number to test. If omitted, tests current worktree.
- `--mode <mode>` (optional): Where to run tests (default: auto-detect based on implementation mode)
  - `local`: Run tests in local worktree
  - `sandbox`: Run tests in E2B sandbox
- `--compare` (optional): Run tests in both environments and compare results

## Workflow

### Step 1: Context Detection

1. **Determine Target**:
   - If issue number provided, locate its worktree
   - If no issue number, use current working directory
   - Verify we're in a valid worktree or repository

2. **Detect Implementation Mode**:
   - Check orchestrator state for active sandbox for this issue
   - If sandbox exists and is active, default to sandbox mode
   - If no sandbox, default to local mode
   - User can override with --mode flag

### Step 2: Detect Test Framework

Automatically detect the test framework in use:

**JavaScript/TypeScript**:
- Jest: Check for `jest.config.js` or `"jest"` in package.json
- Mocha: Check for `.mocharc.*` or `"mocha"` in package.json
- Vitest: Check for `vitest.config.*` or `"vitest"` in package.json
- Ava: Check for `"ava"` in package.json

**Python**:
- pytest: Check for `pytest.ini` or `"pytest"` in pyproject.toml
- unittest: Check for `test_*.py` files
- nose: Check for `.noserc`

**Other Languages**:
- Go: `go test`
- Rust: `cargo test`
- Ruby: `rspec` or `minitest`
- Java: Maven (`mvn test`) or Gradle (`gradle test`)

### Step 3: Run Tests (Local Mode)

If running tests locally:

1. **Navigate to Worktree**:
   - Change to the worktree directory
   - Verify package.json/requirements.txt exists

2. **Install Dependencies** (if needed):
   - Check if dependencies are installed
   - If missing, ask to run `npm install` or equivalent
   - Show installation progress

3. **Execute Test Command**:
   - Run the detected test command (e.g., `npm test`, `pytest`)
   - Stream output in real-time
   - Capture exit code

4. **Parse Test Results**:
   - Extract test counts (passed, failed, skipped)
   - Identify failed test names
   - Capture error messages and stack traces
   - Calculate coverage percentage if available

### Step 4: Run Tests (Sandbox Mode)

If running tests in sandbox:

1. **Verify Sandbox is Active**:
   - Check orchestrator state for sandbox ID
   - If sandbox doesn't exist, offer to create one
   - Connect to existing sandbox

2. **Sync Latest Code** (if needed):
   - Check if sandbox code is up-to-date with worktree
   - If not, upload latest changes from worktree
   - Verify sync completed successfully

3. **Execute Test Command via MCP**:
   - Call `execute_command` MCP tool
   - Pass test command with appropriate parameters
   - Set working directory to repository root
   - Set reasonable timeout (default: 300 seconds)

4. **Stream Results**:
   - Display stdout and stderr in real-time
   - Parse test framework output
   - Extract test results

### Step 5: Format and Display Results

Generate formatted test report:

#### Success Case
```
✅ Tests Passed

Test Results for Issue #42:
═══════════════════════════════════════════════

Test Framework:  Jest
Environment:     Local worktree
Duration:        12.3s

Results:
  ✓ 45 tests passed
  ○ 3 tests skipped
  ───────────────────
  Total: 48 tests

Coverage:
  Statements:   87.5% (245/280)
  Branches:     82.1% (78/95)
  Functions:    91.3% (42/46)
  Lines:        88.2% (241/273)

All tests passed! ✓
Ready to create PR.
```

#### Failure Case
```
❌ Tests Failed

Test Results for Issue #42:
═══════════════════════════════════════════════

Test Framework:  Jest
Environment:     E2B Sandbox (sbx_abc123)
Duration:        15.7s

Results:
  ✓ 42 tests passed
  ✗ 3 tests failed
  ○ 3 tests skipped
  ───────────────────
  Total: 48 tests

Failed Tests:
  1. Feature › renders correctly
     Error: Expected <div class="feature"> but got <div class="featur">
     File: src/components/Feature.test.tsx:45

  2. Feature › handles edge cases
     Error: TypeError: Cannot read property 'length' of undefined
     File: src/components/Feature.test.tsx:67

  3. Feature › integrates with API
     Error: Network request failed: 404 Not Found
     File: src/components/Feature.test.tsx:89

Coverage:
  Statements:   72.1% (202/280)
  Branches:     65.8% (63/95)
  Functions:    80.4% (37/46)
  Lines:        73.5% (201/273)

❌ Tests must pass before creating PR.

Suggestions:
  1. Review failed tests and fix implementation
  2. Run /test #42 again after fixes
  3. Use /sandbox-debug #42 for interactive debugging
```

### Step 6: Comparison Mode (--compare)

When `--compare` flag is used:

1. **Run Tests Locally**:
   - Execute tests in local worktree
   - Capture results

2. **Run Tests in Sandbox**:
   - Execute same tests in E2B sandbox
   - Capture results

3. **Compare Results**:
   ```
   📊 Test Comparison: Local vs Sandbox
   ═══════════════════════════════════════════════

   Results:
                    Local       Sandbox     Difference
   ─────────────────────────────────────────────────
   Passed:          42          45          +3
   Failed:          3           0           -3
   Skipped:         3           3           0
   Duration:        12.3s       15.7s       +3.4s
   Coverage:        87.5%       91.2%       +3.7%

   Analysis:
   ✓ All local failures fixed in sandbox
   ⚠ Sandbox is 3.4s slower (acceptable)
   ✓ Coverage improved in sandbox environment

   Recommendation: Use sandbox results
   ```

4. **Identify Discrepancies**:
   - Tests passing locally but failing in sandbox → environment issue
   - Tests failing locally but passing in sandbox → dependency issue
   - Provide recommendations based on differences

## Examples

### Example 1: Test Current Feature
```
/test
```
Runs tests for the current worktree in the appropriate environment.

### Example 2: Test Specific Issue in Sandbox
```
/test #42 --mode sandbox
```
Runs tests for issue #42 in its E2B sandbox.

### Example 3: Compare Local vs Sandbox
```
/test #42 --compare
```
Runs tests in both environments and compares results.

## Test Framework Commands

The following test commands are auto-detected and used:

| Framework | Command |
|-----------|---------|
| Jest | `npm test` or `npx jest` |
| Mocha | `npm test` or `npx mocha` |
| pytest | `pytest` or `python -m pytest` |
| Go | `go test ./...` |
| Rust | `cargo test` |
| Maven | `mvn test` |
| Gradle | `gradle test` |

## Error Handling

- **No Tests Found**: I'll inform you and suggest adding tests
- **Test Framework Not Detected**: I'll ask which framework to use
- **Dependencies Missing**: I'll offer to install dependencies
- **Timeout**: Tests taking > 5 minutes will timeout (configurable)
- **Sandbox Not Found**: I'll offer to create sandbox or run locally

## Configuration

Configure test behavior in `.claude/config/e2b-config.json`:
- `test.defaultTimeout`: Default timeout in seconds (default: 300)
- `test.autoInstallDeps`: Auto-install missing dependencies (default: true)
- `test.showCoverage`: Show coverage reports (default: true)
- `test.failOnCoverageBelow`: Minimum coverage threshold (default: null)
- `test.frameworks`: Custom test framework commands

## Hook System Integration

Test execution is logged via hooks:
- **PostToolUse Hook**: Logs test command execution
- **Stop Hook**: Tracks time and costs for test runs

## Cost Information

**Local Mode**:
- Free (runs on your machine)
- Only API costs if I need to analyze failures (~$0.01)

**Sandbox Mode**:
- Bumba Sandbox runtime: Already running (no additional cost)
- Command execution: Included in sandbox cost
- API costs for analysis: ~$0.01 - $0.05

**Comparison Mode**:
- Combines local (free) + sandbox (included) + analysis (~$0.05)

## Notes

- Tests should be run before creating pull requests
- Sandbox tests are more isolated and may catch environment-specific issues
- Local tests are faster and free
- Coverage reports help identify untested code
- Failed tests block PR creation by default (can be overridden)
- Test results are logged for historical tracking
- This command uses MCP tool `execute_command` for sandbox test execution

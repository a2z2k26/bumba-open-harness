---
name: matrix
description: Multi-environment cross-platform testing (Verification stage)
---

# /test-matrix Command

Runs tests across multiple environments (Node versions, Python versions, OS, databases) to ensure cross-platform compatibility and catch environment-specific bugs.

## Usage

```
/test-matrix #<issue> [--environments <envs>] [options]
```

## Parameters

- `#<issue>` (required): Issue number to test
- `--environments <envs>` (optional): Comma-separated environments (node16,node18,node20)
- `--matrix-file <file>` (optional): Path to matrix configuration file
- `--fail-fast` (optional): Stop on first environment failure
- `--parallel <n>` (optional): Maximum parallel test runs (default: 3)
- `--keep-on-failure` (optional): Keep failed sandboxes for debugging
- `--coverage` (optional): Generate coverage reports for each environment
- `--compare` (optional): Generate comparison report across environments

## Workflow

### Step 1: Matrix Configuration

```
🧪 Multi-Environment Test Matrix
═══════════════════════════════════════════════

Issue: #42 - User Authentication
Matrix Source: Auto-detected from project

Detected Project Type: Node.js
Available Matrices:
  [1] Node.js versions (16.x, 18.x, 20.x)
  [2] Python versions (3.9, 3.10, 3.11, 3.12)
  [3] Custom matrix from file
  [4] Manual selection

Select matrix (1-4): 1

Selected Test Matrix: Node.js versions
Environments:
  • Node.js 16.x (LTS Gallium)
  • Node.js 18.x (LTS Hydrogen)
  • Node.js 20.x (LTS Iron)

Configuration:
  Parallel runs: 3 (all at once)
  Fail-fast: disabled
  Coverage: enabled
  Keep on failure: enabled

Estimated Time: 8-12 minutes
Estimated Cost: $0.45 (3 sandboxes × ~3min each)

Confirm matrix test? (yes/no): yes
```

### Step 2: Environment Preparation

```
📦 Preparing Test Environments
═══════════════════════════════════════════════

[Env 1/3] Node.js 16.x
      Creating sandbox with template...
      ✓ Sandbox: sbx_node16_abc123
      ✓ Template: node-16-lts
      Uploading code from worktree...
      ✓ 1,247 files uploaded
      Installing dependencies...
      ✓ npm install completed (47 packages)
      Status: Ready for testing

[Env 2/3] Node.js 18.x
      Creating sandbox with template...
      ✓ Sandbox: sbx_node18_def456
      ✓ Template: node-18-lts
      Uploading code from worktree...
      ✓ 1,247 files uploaded
      Installing dependencies...
      ✓ npm install completed (47 packages)
      Status: Ready for testing

[Env 3/3] Node.js 20.x
      Creating sandbox with template...
      ✓ Sandbox: sbx_node20_ghi789
      ✓ Template: node-20-lts
      Uploading code from worktree...
      ✓ 1,247 files uploaded
      Installing dependencies...
      ✓ npm install completed (47 packages)
      Status: Ready for testing

All environments ready. Starting parallel test execution...
```

### Step 3: Parallel Test Execution

```
🧪 Running Tests Across Environments
═══════════════════════════════════════════════

[Node.js 16.x] Running...
  Framework: Jest
  Command: npm test
  Output: Streaming...

  PASS  src/auth/login.test.ts
  PASS  src/auth/oauth.test.ts
  PASS  src/middleware/auth.test.ts
  PASS  src/utils/crypto.test.ts

  ✓ 48/48 tests passed
  Coverage: 92.8%
  Duration: 2.4s
  Status: ✅ PASSED

[Node.js 18.x] Running...
  Framework: Jest
  Command: npm test
  Output: Streaming...

  PASS  src/auth/login.test.ts
  PASS  src/auth/oauth.test.ts
  PASS  src/middleware/auth.test.ts
  FAIL  src/utils/crypto.test.ts
    ✗ should generate secure random bytes
      Expected: Buffer of random bytes
      Received: TypeError: crypto.randomBytes is not a function

  ✗ 46/48 tests passed (2 failures)
  Coverage: 91.2%
  Duration: 2.3s
  Status: ❌ FAILED

[Node.js 20.x] Running...
  Framework: Jest
  Command: npm test
  Output: Streaming...

  PASS  src/auth/login.test.ts
  PASS  src/auth/oauth.test.ts
  PASS  src/middleware/auth.test.ts
  PASS  src/utils/crypto.test.ts

  ✓ 48/48 tests passed
  Coverage: 93.4%
  Duration: 2.1s
  Status: ✅ PASSED
```

### Step 4: Results Analysis & Comparison

```
📊 Test Matrix Results
═══════════════════════════════════════════════

Overall Status: ⚠️  PARTIAL PASS (2/3 environments)

Environment Comparison:

Environment    | Tests        | Coverage | Duration | Status
---------------|--------------|----------|----------|----------
Node.js 16.x   | 48/48 (100%) | 92.8%    | 2.4s     | ✅ PASSED
Node.js 18.x   | 46/48 (96%)  | 91.2%    | 2.3s     | ❌ FAILED
Node.js 20.x   | 48/48 (100%) | 93.4%    | 2.1s     | ✅ PASSED

───────────────────────────────────────────────

⚠️  Compatibility Issues Detected

Node.js 18.x Failures (2):

1. src/utils/crypto.test.ts:34
   Test: should generate secure random bytes
   Error: TypeError: crypto.randomBytes is not a function

   Root Cause: Node.js 18 changed crypto module imports
   Breaking Change: crypto.randomBytes requires explicit import

   Fix Required:
   ```javascript
   // Old (works in 16.x, 20.x)
   const crypto = require('crypto');
   crypto.randomBytes(32);

   // New (required in 18.x)
   const { randomBytes } = require('crypto');
   randomBytes(32);
   ```

2. src/utils/buffer.test.ts:67
   Test: should handle buffer concatenation
   Error: Buffer behavior differs in Node.js 18

   Root Cause: Buffer.concat behavior changed
   Breaking Change: Stricter type checking in v18

   Fix Required: Update buffer handling for v18 compatibility

───────────────────────────────────────────────

Coverage Comparison:

File                      | 16.x  | 18.x  | 20.x  | Variance
--------------------------|-------|-------|-------|----------
src/auth/login.ts         | 94%   | 94%   | 95%   | 1%
src/auth/oauth.ts         | 91%   | 90%   | 92%   | 2%
src/middleware/auth.ts    | 93%   | 92%   | 94%   | 2%
src/utils/crypto.ts       | 92%   | 89%   | 93%   | 4% ⚠️

High variance files may have environment-specific code paths.

───────────────────────────────────────────────

Performance Comparison:

Test Suite                | 16.x  | 18.x  | 20.x  | Fastest
--------------------------|-------|-------|-------|----------
auth/login.test.ts        | 0.8s  | 0.7s  | 0.6s  | 20.x
auth/oauth.test.ts        | 0.9s  | 0.9s  | 0.8s  | 20.x
middleware/auth.test.ts   | 0.5s  | 0.5s  | 0.5s  | All tied
utils/crypto.test.ts      | 0.2s  | 0.2s  | 0.2s  | All tied

Node.js 20.x shows best overall performance (12% faster average).

───────────────────────────────────────────────

💡 Recommendations

1. Critical: Fix Node.js 18.x compatibility issues
   - Update crypto module imports
   - Update buffer handling
   - Estimated effort: 30 minutes

2. Consider: Target Node.js 18.x minimum version
   - Drop Node.js 16.x support (EOL: 2024-09-11)
   - Focus on 18.x and 20.x compatibility
   - Update package.json engines field

3. Performance: Consider Node.js 20.x for production
   - 12% faster test execution
   - Better overall performance
   - Latest LTS with long-term support

───────────────────────────────────────────────

Sandbox Status:

sbx_node16_abc123: Destroyed (tests passed)
sbx_node18_def456: Preserved (--keep-on-failure)
sbx_node20_ghi789: Destroyed (tests passed)

To debug Node.js 18.x issues:
  /sandbox-debug sbx_node18_def456

To re-run specific environment:
  /test-matrix #42 --environments node18

To apply fixes and retest:
  1. Fix code in worktree
  2. /test-matrix #42 --environments node18
  3. Verify all environments: /test-matrix #42
```

## Examples

### Example 1: Default Matrix (Auto-detect)
```
/test-matrix #42
```

### Example 2: Specific Node Versions
```
/test-matrix #42 --environments node16,node18,node20
```

### Example 3: Python Version Matrix
```
/test-matrix #43 --environments python3.9,python3.10,python3.11,python3.12
```

### Example 4: Custom Matrix from File
```
/test-matrix #42 --matrix-file .github/test-matrix.json
```

Example matrix file:
```json
{
  "environments": [
    {
      "name": "Node.js 16 + PostgreSQL 14",
      "template": "node16-postgres14",
      "env": {
        "DATABASE_URL": "postgresql://localhost:5432/test"
      }
    },
    {
      "name": "Node.js 18 + PostgreSQL 15",
      "template": "node18-postgres15",
      "env": {
        "DATABASE_URL": "postgresql://localhost:5432/test"
      }
    }
  ]
}
```

### Example 5: Fail-Fast Mode
```
/test-matrix #42 --fail-fast
```

### Example 6: With Coverage and Comparison
```
/test-matrix #42 --coverage --compare
```

### Example 7: Database Version Matrix
```
/test-matrix #45 --environments postgres14,postgres15,postgres16
```

### Example 8: Operating System Matrix
```
/test-matrix #42 --environments ubuntu22,ubuntu24,debian12
```

## Matrix Configuration Files

**Format**: JSON with environment specifications

```json
{
  "name": "Full Compatibility Matrix",
  "environments": [
    {
      "name": "Production (Node 20 + Postgres 16)",
      "template": "prod-stack",
      "parallel": true,
      "env": {
        "NODE_ENV": "production",
        "DATABASE_URL": "postgresql://localhost:5432/prod"
      }
    },
    {
      "name": "Legacy (Node 16 + Postgres 14)",
      "template": "legacy-stack",
      "parallel": true,
      "env": {
        "NODE_ENV": "production",
        "DATABASE_URL": "postgresql://localhost:5432/legacy"
      }
    }
  ],
  "options": {
    "fail_fast": false,
    "keep_on_failure": true,
    "coverage": true,
    "max_parallel": 2
  }
}
```

## Supported Environment Types

### Node.js Versions
- `node14`: Node.js 14.x (EOL 2023-04-30)
- `node16`: Node.js 16.x (LTS until 2024-09-11)
- `node18`: Node.js 18.x (LTS until 2025-04-30)
- `node20`: Node.js 20.x (LTS until 2026-04-30)
- `node21`: Node.js 21.x (Current)

### Python Versions
- `python3.8`: Python 3.8.x
- `python3.9`: Python 3.9.x
- `python3.10`: Python 3.10.x
- `python3.11`: Python 3.11.x
- `python3.12`: Python 3.12.x

### Go Versions
- `go1.19`: Go 1.19.x
- `go1.20`: Go 1.20.x
- `go1.21`: Go 1.21.x
- `go1.22`: Go 1.22.x

### Rust Versions
- `rust1.70`: Rust 1.70.x
- `rust1.71`: Rust 1.71.x
- `rust1.72`: Rust 1.72.x
- `rust1.73`: Rust 1.73.x (latest stable)

### Database Versions
- `postgres14`: PostgreSQL 14.x
- `postgres15`: PostgreSQL 15.x
- `postgres16`: PostgreSQL 16.x
- `mysql8.0`: MySQL 8.0.x
- `mysql8.1`: MySQL 8.1.x
- `redis7`: Redis 7.x

### Operating Systems
- `ubuntu22`: Ubuntu 22.04 LTS
- `ubuntu24`: Ubuntu 24.04 LTS
- `debian11`: Debian 11 (Bullseye)
- `debian12`: Debian 12 (Bookworm)
- `alpine3.18`: Alpine Linux 3.18

## Integration

- Creates separate sandbox for each environment using Bumba Sandbox templates
- Uses `spawn_sandbox_agent` MCP tool for parallel execution
- Parallelizes environment testing (default: 3 concurrent)
- Aggregates results across all environments
- Generates detailed comparison reports
- Integrates with `/sandbox-debug` for failed environment investigation
- Works with custom Bumba Sandbox templates for specialized environments

## Error Handling

### Common Errors

**Environment Not Supported**:
```
❌ Error: Environment not supported

Environment: node22

Requested: node22
Status: Not available

Supported Node.js environments:
  - node14 (EOL 2023-04-30)
  - node16 (LTS until 2024-09-11)
  - node18 (LTS until 2025-04-30)
  - node20 (LTS until 2026-04-30)
  - node21 (Current release)

Supported Python environments:
  - python3.8, python3.9, python3.10, python3.11, python3.12

Supported Go environments:
  - go1.19, go1.20, go1.21, go1.22

Supported Rust environments:
  - rust1.70, rust1.71, rust1.72, rust1.73

To add custom environment:
  1. Create Bumba Sandbox template with desired version:
     /create-sandbox-template my-custom-env

  2. Use custom template:
     /test-matrix #42 --template my-custom-env

  3. Or specify in matrix file:
     "template": "my-custom-env"
```

**All Environments Failed**:
```
❌ Critical: Tests failed in ALL environments

Issue: #42 - User Authentication

Results:
  ❌ Node.js 16.x: 0/48 tests passed (compilation error)
  ❌ Node.js 18.x: 0/48 tests passed (compilation error)
  ❌ Node.js 20.x: 0/48 tests passed (compilation error)

Common Error:
  SyntaxError: Unexpected token '?'
  at Module._compile (internal/modules/cjs/loader.js:891:18)

Root Cause Analysis:
  Code uses ES2020 features (optional chaining '?.')
  TypeScript not configured or not transpiling
  Target version too low in tsconfig.json

This indicates a systemic issue, not environment-specific.

Recommended Actions:
  1. Check TypeScript configuration:
     cat tsconfig.json

  2. Verify compilation:
     npm run build

  3. Check package.json scripts:
     cat package.json

  4. Fix configuration and retry:
     /test-matrix #42

All sandboxes preserved for debugging:
  /sandbox-debug sbx_node16_abc123
  /sandbox-debug sbx_node18_def456
  /sandbox-debug sbx_node20_ghi789
```

**Matrix File Not Found**:
```
❌ Error: Matrix configuration file not found

File: .github/test-matrix.json
Path: /home/developer/project/.github/test-matrix.json

File does not exist.

Solutions:
  1. Create matrix file:
     mkdir -p .github
     cat > .github/test-matrix.json << 'EOF'
     {
       "environments": [
         {"name": "Node 18", "template": "node18"},
         {"name": "Node 20", "template": "node20"}
       ]
     }
     EOF

  2. Use different file:
     /test-matrix #42 --matrix-file path/to/matrix.json

  3. Use command-line environments:
     /test-matrix #42 --environments node18,node20

  4. Use auto-detection:
     /test-matrix #42
```

**Invalid Matrix File Format**:
```
❌ Error: Invalid matrix file format

File: .github/test-matrix.json
Error: Unexpected token in JSON at position 145

JSON parsing failed. Matrix file must be valid JSON.

Common issues:
  1. Trailing commas (not allowed in JSON)
  2. Missing quotes around keys
  3. Comments (not allowed in JSON)

To validate JSON:
  cat .github/test-matrix.json | jq .

Example valid format:
  {
    "environments": [
      {"name": "Node 18", "template": "node18"},
      {"name": "Node 20", "template": "node20"}
    ]
  }

Fix JSON and retry:
  /test-matrix #42 --matrix-file .github/test-matrix.json
```

**Sandbox Creation Failed**:
```
❌ Error: Failed to create sandbox for environment

Environment: Node.js 18.x
Template: node18-lts
Sandbox API Error: Template not found

Cause: Sandbox template 'node18-lts' does not exist

Solutions:
  1. Create template first:
     /create-sandbox-template node18-lts --runtime node

  2. Use system template:
     /test-matrix #42 --environments node18

  3. Check available templates:
     /list-sandbox-templates

  4. Use default template:
     Remove --template flag to use default

Other environments were not tested due to --fail-fast mode.
To test remaining environments:
  /test-matrix #42 --environments node16,node20
```

**Parallel Limit Exceeded**:
```
⚠️  Warning: Reducing parallel execution

Requested: 10 concurrent environments
Account Limit: 5 concurrent sandboxes (Free tier)
Actual: 5 concurrent environments

Environments will be tested in 2 batches:
  Batch 1: node14, node16, node18, node20, node21 (5 parallel)
  Batch 2: python3.9, python3.10, python3.11, python3.12, python3.13 (5 parallel)

This will take approximately 2x longer than full parallelization.

To increase limit:
  1. Upgrade to Pro tier (20 concurrent sandboxes)
  2. Reduce environments in matrix
  3. Run sequentially: /test-matrix #42 --parallel 1

Continuing with 5 parallel...
```

**Resource Exhaustion**:
```
❌ Error: Insufficient resources for matrix testing

Requested: 5 environments × 2GB RAM = 10GB total
Account Limit: 8GB RAM (Free tier)
Available: 8GB RAM

Cannot create all environments simultaneously.

Solutions:
  1. Reduce parallelization:
     /test-matrix #42 --parallel 3
     (3 environments × 2GB = 6GB, within limit)

  2. Test in batches:
     /test-matrix #42 --environments node16,node18
     /test-matrix #42 --environments node20

  3. Upgrade account:
     Pro tier: 32GB RAM limit

  4. Reduce memory per sandbox:
     Use lighter templates or configurations

Recommendation: Use --parallel 3 for your account tier.
```

**Timeout During Test Execution**:
```
❌ Error: Test execution timeout

Environment: Node.js 18.x
Timeout: 10 minutes (default)
Sandbox: sbx_node18_def456

Test execution exceeded maximum allowed time.

Possible causes:
  1. Tests are hanging (infinite loops, deadlocks)
  2. Tests are legitimately slow
  3. Sandbox performance issues

Last output (before timeout):
  PASS  src/auth/login.test.ts
  PASS  src/auth/oauth.test.ts
  Running src/performance/stress.test.ts... (hung here)

Solutions:
  1. Increase timeout:
     /test-matrix #42 --timeout 30

  2. Debug hanging test:
     /sandbox-debug sbx_node18_def456

  3. Check test logs:
     /sandbox-exec sbx_node18_def456 "cat test-output.log"

  4. Skip slow tests in matrix:
     npm test -- --testPathIgnorePatterns=stress

Sandbox preserved for debugging.
```

**Dependency Installation Failed**:
```
❌ Error: Dependency installation failed in environment

Environment: Python 3.11
Sandbox: sbx_python311_abc
Command: pip install -r requirements.txt
Exit Code: 1

Error Output:
  ERROR: Could not find a version that satisfies the requirement numpy==1.24.0
  ERROR: No matching distribution found for numpy==1.24.0

Cause: numpy 1.24.0 not available for Python 3.11

This is an environment-specific dependency issue.

Solutions:
  1. Update requirements.txt for Python 3.11 compatibility:
     numpy>=1.23.0,<2.0.0  # Use version range

  2. Use environment-specific requirements:
     requirements-py311.txt

  3. Skip incompatible environment:
     /test-matrix #43 --environments python3.9,python3.10

  4. Fix dependencies and retry:
     /test-matrix #43

Other environments may have succeeded. Check full results above.
```

### Recovery Actions

**Automatic Recovery**:
- Preserves failed sandboxes when `--keep-on-failure` is set
- Continues testing other environments unless `--fail-fast`
- Saves all test outputs and logs
- Generates detailed comparison reports
- Provides specific fix recommendations for failures
- Cleans up successful sandboxes to save resources

**Manual Recovery**:
```bash
# Debug specific failed environment
/sandbox-debug sbx_node18_def456

# View test output
/sandbox-exec sbx_node18_def456 "cat test-output.log"

# Check environment details
/sandbox-exec sbx_node18_def456 "node --version"
/sandbox-exec sbx_node18_def456 "npm --version"

# Re-run failed tests
/sandbox-exec sbx_node18_def456 "npm test -- --verbose"

# Fix code in worktree
vim src/utils/crypto.ts

# Re-test specific environment
/test-matrix #42 --environments node18

# Re-test all environments
/test-matrix #42
```

**Cleanup After Failures**:
```bash
# List all sandboxes
/sandbox-status

# Manually cleanup specific sandbox
/cleanup-sandboxes --sandbox sbx_node18_def456

# Cleanup all failed matrix sandboxes
/cleanup-sandboxes --filter failed --yes
```

## Use Cases

**Library/Package Development**:
- Test across multiple Node.js versions for npm packages
- Test across multiple Python versions for PyPI packages
- Ensure compatibility with LTS and current versions

**Cross-Platform Applications**:
- Test on different operating systems
- Verify database compatibility across versions
- Check Redis/cache behavior across versions

**Migration Planning**:
- Test code before upgrading runtime versions
- Identify breaking changes in advance
- Plan migration path based on test results

**CI/CD Integration**:
- Replicate GitHub Actions matrix locally
- Debug matrix failures before pushing
- Validate matrix configuration changes

**Performance Comparison**:
- Compare test execution speed across versions
- Identify performance regressions
- Choose optimal production environment

## Notes

- Useful for library/package development and cross-platform apps
- Ensures compatibility across multiple runtime versions
- Can test database versions, OS differences, and service versions
- Creates separate sandboxes per environment for isolation
- Cleans up successful sandboxes automatically
- Preserves failed sandboxes with `--keep-on-failure` for debugging
- Supports custom matrix configurations via JSON files
- Parallelizes up to account limits for faster results
- Generates detailed comparison reports with variance analysis
- Provides actionable fix recommendations for failures
- Integrates with `/sandbox-debug` for interactive troubleshooting
- Free tier: 5 concurrent sandboxes, Pro tier: 20 concurrent
- Recommended for pre-release compatibility testing

---
name: exec
description: Execute command in sandbox
---

# /sandbox-exec Command

Executes arbitrary commands in a sandbox without entering interactive mode. Ideal for quick operations, automation, CI/CD integration, and running commands that don't require user interaction.

## Usage

```
/sandbox-exec <sandbox-id|#issue> "<command>" [options]
```

## Parameters

- `<sandbox-id|#issue>` (required): Sandbox ID (e.g., `sbx_abc123xyz`) or issue number (e.g., `#42`)
- `"<command>"` (required): Command to execute (quoted string)
- `--timeout <seconds>` (optional): Command timeout - default: 300 seconds (5 minutes)
- `--capture-output` (optional): Capture and return output - default: true
- `--stream` (optional): Stream output in real-time - default: false
- `--cwd <directory>` (optional): Working directory - default: `/workspace`
- `--env <KEY=VALUE>` (optional): Set environment variables (repeatable)
- `--silent` (optional): Suppress output, only show exit code - default: false
- `--force` (optional): Force execution even if sandbox is busy - default: false

## Workflow

### Step 1: Command Validation and Preparation

```
⚙️ Sandbox Command Execution
═══════════════════════════════════════════════

Validating request...
  Issue: #42 - Add User Authentication
  Sandbox: sbx_abc123xyz (active)
  Command: npm test -- src/auth/login.test.ts
  Timeout: 300 seconds

Checking sandbox state...
  ✓ Sandbox running
  ✓ Network accessible
  ✓ No conflicting operations
  ✓ Sufficient resources (CPU: 12%, Memory: 34%)

Preparing execution environment...
  Working Directory: /workspace
  Shell: /bin/bash
  Environment Variables: 0 custom

───────────────────────────────────────────────
```

### Step 2: Command Execution

```
Executing command...
  Started at: 2025-01-18 10:23:45 UTC
  PID: 8472

Output (Real-time):
───────────────────────────────────────────────
> test
> jest src/auth/login.test.ts

 PASS  src/auth/login.test.ts
  Login Authentication
    ✓ should prevent SQL injection (18ms)
    ✓ should hash passwords (11ms)
    ✓ should validate email format (7ms)
    ✓ should reject invalid credentials (9ms)

Tests: 4 passed, 4 total
Snapshots: 0 total
Time: 2.341s
Ran all test suites matching /src\/auth\/login.test.ts/i.

───────────────────────────────────────────────
```

### Step 3: Execution Summary

```
✅ Command Completed Successfully
═══════════════════════════════════════════════

Execution Details:
  Sandbox: sbx_abc123xyz
  Issue: #42 - Add User Authentication
  Command: npm test -- src/auth/login.test.ts
  Exit Code: 0 (Success)
  Duration: 2.4s

Output Summary:
  Lines: 12
  Stdout: 12 lines
  Stderr: 0 lines

Test Results:
  Tests Passed: 4
  Tests Failed: 0
  Total Tests: 4

Next Steps:
  • Continue development in sandbox
  • Run full test suite: /test #42
  • Debug interactively: /sandbox-debug #42
  • Sync changes: /sync-sandbox-code #42
```

## Examples

### Example 1: Run Specific Tests
```
/sandbox-exec #42 "npm test -- src/auth/login.test.ts"
```

**Use Case**: Run specific test file to verify recent changes without full test suite.

**Output**:
```
⚙️ Sandbox Command Execution
═══════════════════════════════════════════════

Executing: npm test -- src/auth/login.test.ts

 PASS  src/auth/login.test.ts
  ✓ should prevent SQL injection (18ms)
  ✓ should hash passwords (11ms)
  ✓ should validate email format (7ms)

✅ Tests passed (4/4)
Exit Code: 0
Duration: 2.4s
```

### Example 2: Install Package
```
/sandbox-exec #42 "npm install lodash@latest"
```

**Use Case**: Install a new dependency in sandbox for testing before adding to project.

**Output**:
```
⚙️ Sandbox Command Execution
═══════════════════════════════════════════════

Executing: npm install lodash@latest

added 1 package, and audited 487 packages in 3s

52 packages are looking for funding
  run `npm fund` for details

found 0 vulnerabilities

✅ Package installed successfully
Exit Code: 0
Duration: 3.2s
```

### Example 3: Check Environment
```
/sandbox-exec #42 "node --version && npm --version"
```

**Use Case**: Verify Node.js and npm versions in sandbox environment.

**Output**:
```
⚙️ Sandbox Command Execution
═══════════════════════════════════════════════

Executing: node --version && npm --version

v18.19.0
10.2.3

✅ Environment check complete
Exit Code: 0
Duration: 0.1s
```

### Example 4: Build Project
```
/sandbox-exec #42 "npm run build" --timeout 600
```

**Use Case**: Build project with extended timeout for larger projects.

**Output**:
```
⚙️ Sandbox Command Execution
═══════════════════════════════════════════════

Executing: npm run build
Timeout: 600 seconds

> build
> tsc && vite build

vite v5.0.11 building for production...
✓ 127 modules transformed.
dist/index.html                   0.45 kB │ gzip:  0.29 kB
dist/assets/index-a3b4c5d6.css    2.14 kB │ gzip:  0.87 kB
dist/assets/index-e7f8g9h0.js   142.35 kB │ gzip: 45.89 kB
✓ built in 12.43s

✅ Build complete
Exit Code: 0
Duration: 12.4s
```

### Example 5: Run Linter
```
/sandbox-exec #42 "npm run lint"
```

**Use Case**: Run ESLint to check code quality before syncing changes.

**Output**:
```
⚙️ Sandbox Command Execution
═══════════════════════════════════════════════

Executing: npm run lint

> lint
> eslint src --ext .ts,.tsx

src/auth/login.ts
  15:7   warning  Unused variable 'user'        @typescript-eslint/no-unused-vars
  23:12  error    'password' is never reassigned. Use 'const' instead  prefer-const

✖ 2 problems (1 error, 1 warning)
  1 error and 0 warnings potentially fixable with the `--fix` option.

❌ Linting failed
Exit Code: 1
Duration: 1.8s

To fix automatically:
  /sandbox-exec #42 "npm run lint -- --fix"
```

### Example 6: Git Operations
```
/sandbox-exec #42 "git status && git diff --stat"
```

**Use Case**: Check git status and see file changes without interactive session.

**Output**:
```
⚙️ Sandbox Command Execution
═══════════════════════════════════════════════

Executing: git status && git diff --stat

On branch feature/issue-42-auth
Changes not staged for commit:
  modified:   src/auth/login.ts
  modified:   src/auth/session.ts

no changes added to commit

 src/auth/login.ts   | 12 ++++++------
 src/auth/session.ts | 25 +++++++++++++++++--------
 2 files changed, 23 insertions(+), 14 deletions(-)

✅ Git status retrieved
Exit Code: 0
Duration: 0.3s
```

### Example 7: Database Migration
```
/sandbox-exec #42 "npm run db:migrate" --env DATABASE_URL=postgresql://localhost/test
```

**Use Case**: Run database migrations with specific database URL.

**Output**:
```
⚙️ Sandbox Command Execution
═══════════════════════════════════════════════

Environment Variables:
  DATABASE_URL=postgresql://localhost/test

Executing: npm run db:migrate

> db:migrate
> knex migrate:latest

Batch 1 run: 3 migrations
  20250115_create_users_table.js
  20250116_create_sessions_table.js
  20250117_add_user_roles.js

✅ Migrations complete
Exit Code: 0
Duration: 4.7s
```

### Example 8: Generate Code Coverage
```
/sandbox-exec #42 "npm run test:coverage" --timeout 600
```

**Use Case**: Generate full code coverage report.

**Output**:
```
⚙️ Sandbox Command Execution
═══════════════════════════════════════════════

Executing: npm run test:coverage
Timeout: 600 seconds

> test:coverage
> jest --coverage

 PASS  src/auth/login.test.ts
 PASS  src/auth/register.test.ts
 PASS  src/auth/session.test.ts
 PASS  src/db/users.test.ts

Test Suites: 4 passed, 4 total
Tests:       42 passed, 42 total
Snapshots:   0 total
Time:        8.341s

──────────────────────────────────────────────
File                | % Stmts | % Branch | % Funcs | % Lines | Uncovered Line #s
All files           |   94.23 |    87.50 |   91.67 |   94.12 |
 src/auth           |   96.15 |    90.00 |   95.00 |   96.00 |
  login.ts          |   98.00 |    92.31 |  100.00 |   98.00 | 42
  register.ts       |   95.00 |    88.89 |   90.00 |   95.00 | 67-68
  session.ts        |   95.45 |    88.89 |   95.00 |   95.24 | 89
 src/db             |   90.00 |    82.35 |   85.71 |   90.00 |
  users.ts          |   90.00 |    82.35 |   85.71 |   90.00 | 23,45-47
──────────────────────────────────────────────

✅ Coverage report generated
Exit Code: 0
Duration: 8.4s

Coverage files: .coverage/lcov-report/index.html
```

### Example 9: Multiple Chained Commands
```
/sandbox-exec #42 "npm install && npm run build && npm test"
```

**Use Case**: Install dependencies, build, and test in one command.

**Output**:
```
⚙️ Sandbox Command Execution
═══════════════════════════════════════════════

Executing: npm install && npm run build && npm test

[1/3] Installing dependencies...
added 487 packages in 12s

[2/3] Building project...
✓ built in 8.4s

[3/3] Running tests...
Tests: 42 passed, 42 total

✅ All operations complete
Exit Code: 0
Duration: 23.8s
```

### Example 10: Silent Execution (Exit Code Only)
```
/sandbox-exec #42 "npm test" --silent
```

**Use Case**: Check if tests pass without seeing output (useful for CI/CD checks).

**Output**:
```
⚙️ Sandbox Command Execution
═══════════════════════════════════════════════

Executing: npm test (silent mode)

✅ Command completed
Exit Code: 0
Duration: 2.4s
```

### Example 11: Stream Output in Real-Time
```
/sandbox-exec #42 "npm run build" --stream
```

**Use Case**: Watch build progress in real-time for long-running commands.

**Output**:
```
⚙️ Sandbox Command Execution
═══════════════════════════════════════════════

Streaming output...

> build
> tsc && vite build

[tsc] Compiling TypeScript...
[tsc] src/auth/login.ts
[tsc] src/auth/register.ts
[tsc] src/auth/session.ts
[tsc] Compilation complete (no errors)

[vite] Building for production...
[vite] ✓ 15 modules transformed
[vite] ✓ 32 modules transformed
[vite] ✓ 67 modules transformed
[vite] ✓ 127 modules transformed
[vite] ✓ built in 12.43s

✅ Build complete
```

### Example 12: Custom Working Directory
```
/sandbox-exec #42 "npm test" --cwd /workspace/packages/auth
```

**Use Case**: Run tests in a specific subdirectory for monorepo projects.

**Output**:
```
⚙️ Sandbox Command Execution
═══════════════════════════════════════════════

Working Directory: /workspace/packages/auth
Executing: npm test

 PASS  src/login.test.ts
 PASS  src/register.test.ts

Tests: 12 passed, 12 total

✅ Tests passed
Exit Code: 0
Duration: 1.8s
```

## Common Command Patterns

### Pattern 1: Test Before Commit
```bash
# Run tests and linter before committing
/sandbox-exec #42 "npm run lint && npm test"

# If successful, commit changes
/sandbox-exec #42 "git add . && git commit -m 'Add authentication'"
```

### Pattern 2: Install and Test New Dependency
```bash
# Install package
/sandbox-exec #42 "npm install axios"

# Test with new package
/sandbox-exec #42 "npm test"

# If tests pass, sync to worktree
/sync-sandbox-code #42
```

### Pattern 3: Build and Deploy Pipeline
```bash
# Install production dependencies
/sandbox-exec #42 "npm ci --production"

# Build for production
/sandbox-exec #42 "npm run build" --timeout 600

# Run production tests
/sandbox-exec #42 "npm run test:prod"

# Deploy (if all passed)
/sandbox-exec #42 "npm run deploy"
```

### Pattern 4: Database Setup and Seed
```bash
# Create database
/sandbox-exec #42 "npm run db:create" --env DATABASE_URL=postgresql://localhost/test

# Run migrations
/sandbox-exec #42 "npm run db:migrate"

# Seed test data
/sandbox-exec #42 "npm run db:seed"

# Verify
/sandbox-exec #42 "npm run db:verify"
```

### Pattern 5: Performance Profiling
```bash
# Install profiling tools
/sandbox-exec #42 "npm install --save-dev clinic"

# Run profiler
/sandbox-exec #42 "clinic doctor -- node src/server.js" --timeout 600

# Analyze results
/sandbox-exec #42 "cat .clinic/doctor.txt"
```

## Error Handling

### Error 1: Command Execution Failed

```
❌ Error: Command execution failed

Execution Details:
  Sandbox: sbx_abc123xyz
  Issue: #42 - Add User Authentication
  Command: npm test
  Exit Code: 1
  Duration: 2.8s

Error Output:
───────────────────────────────────────────────
 FAIL  src/auth/login.test.ts
  Login Authentication
    ✗ should prevent SQL injection (42ms)

  ● Login Authentication › should prevent SQL injection

    Expected parameterized query but found string concatenation

    at Object.<anonymous> (tests/auth/login.test.ts:23:5)

Tests: 1 failed, 2 passed, 3 total
───────────────────────────────────────────────

Automatic Recovery Actions:
  ⟳ Analyzing failure...
  ✓ Error type: Test failure
  ✓ Failed test: src/auth/login.test.ts
  ✓ Error location: Line 23

Manual Recovery Options:

  Option 1: Debug Interactively
  ───────────────────────────────────────
    /sandbox-debug #42

  Open interactive shell to:
    • Inspect failing test
    • Review implementation
    • Make fixes in real-time
    • Re-run tests

  Option 2: View Test Output
  ───────────────────────────────────────
    /sandbox-exec #42 "npm test -- src/auth/login.test.ts --verbose"

  Get detailed test output with stack traces

  Option 3: Check File Contents
  ───────────────────────────────────────
    /sandbox-exec #42 "cat src/auth/login.ts"

  Review implementation to identify issue

  Option 4: Run Single Test
  ───────────────────────────────────────
    /sandbox-exec #42 "npm test -- src/auth/login.test.ts -t 'should prevent SQL injection'"

  Focus on specific failing test

Recommendation: Option 1 (interactive debug) for complex failures
```

### Error 2: Command Timeout

```
❌ Error: Command timeout

Execution Details:
  Sandbox: sbx_abc123xyz
  Command: npm run build
  Timeout: 300 seconds (5 minutes)
  Elapsed: 300 seconds
  Status: Killed (SIGTERM)

Output Before Timeout:
───────────────────────────────────────────────
> build
> tsc && vite build

[tsc] Compiling TypeScript...
[tsc] src/auth/login.ts
[tsc] src/auth/register.ts
...
[tsc] Compilation complete (no errors)

[vite] Building for production...
[vite] ✓ 15 modules transformed
[vite] ✓ 32 modules transformed
[vite] ✓ 67 modules transformed
[Command terminated]
───────────────────────────────────────────────

Possible Causes:
  1. Build process too slow for default timeout
  2. Large project requiring more time
  3. Performance issues in sandbox
  4. Infinite loop or hung process

Automatic Recovery Actions:
  ⟳ Checking sandbox resources...
  ✓ CPU: 78% (high but not maxed)
  ✓ Memory: 62% (within limits)
  ⟳ Analyzing build process...
  ⚠ Large number of files (>1000)

Manual Recovery Options:

  Option 1: Increase Timeout
  ───────────────────────────────────────
    /sandbox-exec #42 "npm run build" --timeout 600

  Try with 10 minute timeout (600 seconds)

  Option 2: Optimize Build
  ───────────────────────────────────────
  In interactive session:
    /sandbox-debug #42
    sandbox$ npm run build -- --profile
    [Analyze what's slow]

  Option 3: Build in Parts
  ───────────────────────────────────────
    /sandbox-exec #42 "tsc" --timeout 300
    /sandbox-exec #42 "vite build" --timeout 300

  Split TypeScript compilation and bundling

  Option 4: Check for Hung Process
  ───────────────────────────────────────
    /sandbox-exec #42 "ps aux | grep node"
    /sandbox-exec #42 "killall node" --force

  Kill any stuck processes

Recommendation: Option 1 (increase timeout) for large projects
```

### Error 3: Sandbox Not Running

```
❌ Error: Sandbox not running

Sandbox Resolution:
  Issue: #42 - Add User Authentication
  Expected Sandbox: sbx_abc123xyz
  Actual Status: Terminated
  Terminated At: 2025-01-18 09:15:23 UTC
  Reason: Idle timeout (2 hours)

Cannot execute command in terminated sandbox.

Automatic Recovery Actions:
  ✓ Checked for active sandboxes: None found
  ✓ Checked worktree sync: Last sync 30 minutes ago
  ✓ Latest changes preserved in worktree

Manual Recovery Options:

  Option 1: Create New Sandbox
  ───────────────────────────────────────
    /implement-feature #42 --mode sandbox

  This will:
    • Create fresh sandbox from worktree
    • Reinstall dependencies
    • Ready for commands in ~2 minutes

  Option 2: Use Worktree Directly
  ───────────────────────────────────────
  Run command in worktree instead:
    cd $(claude worktree path #42)
    npm test

  This will:
    • Execute in local environment
    • No sandbox overhead
    • Direct file system access

  Option 3: Restore from Snapshot
  ───────────────────────────────────────
  If you have a recent snapshot:
    /sandbox-restore sbx_abc123xyz --snapshot snap_xyz

  Then retry command

Recommendation: Option 1 (create new sandbox) for isolated environment
```

### Error 4: Permission Denied

```
❌ Error: Permission denied

Execution Details:
  Sandbox: sbx_abc123xyz
  Command: npm install --global typescript
  Exit Code: 1

Error Output:
───────────────────────────────────────────────
npm ERR! code EACCES
npm ERR! syscall mkdir
npm ERR! path /usr/local/lib/node_modules/typescript
npm ERR! errno -13
npm ERR! Error: EACCES: permission denied, mkdir '/usr/local/lib/node_modules/typescript'
npm ERR!  [Error: EACCES: permission denied, mkdir '/usr/local/lib/node_modules/typescript'] {
npm ERR!   errno: -13,
npm ERR!   code: 'EACCES',
npm ERR!   syscall: 'mkdir',
npm ERR!   path: '/usr/local/lib/node_modules/typescript'
npm ERR! }
───────────────────────────────────────────────

Permission Issue Detected:
  Operation: Global package install
  Required: Root/sudo privileges
  Current User: sandbox (non-root)

Automatic Recovery Actions:
  ⟳ Analyzing permission requirements...
  ⚠ Global install not recommended
  ✓ Alternative solution available

Manual Recovery Options:

  Option 1: Install Locally (Recommended)
  ───────────────────────────────────────
    /sandbox-exec #42 "npm install --save-dev typescript"

  Install as dev dependency instead of globally

  Option 2: Use sudo
  ───────────────────────────────────────
    /sandbox-exec #42 "sudo npm install --global typescript"

  Use sudo for global install (not recommended)

  Option 3: Use npx
  ───────────────────────────────────────
    /sandbox-exec #42 "npx tsc --version"

  Use npx to run without installing globally

  Option 4: Add to package.json
  ───────────────────────────────────────
  Add typescript to package.json devDependencies:
    /sandbox-exec #42 "npm install --save-dev typescript"

  Then use: npm run tsc or npx tsc

Recommendation: Option 1 (local install) for better project reproducibility
```

### Error 5: Network Connectivity Issue

```
❌ Error: Network connectivity issue

Execution Details:
  Sandbox: sbx_abc123xyz
  Command: npm install
  Exit Code: 1
  Duration: 30.0s (timeout)

Error Output:
───────────────────────────────────────────────
npm ERR! code ETIMEDOUT
npm ERR! errno ETIMEDOUT
npm ERR! network request to https://registry.npmjs.org/express failed, reason: connect ETIMEDOUT 104.16.23.35:443
npm ERR! network This is a problem related to network connectivity.
npm ERR! network In most cases you are behind a proxy or have bad network settings.
───────────────────────────────────────────────

Network Diagnostic:
  ✓ Sandbox online
  ✗ NPM registry unreachable
  ⚠ Possible causes:
    • NPM registry down
    • Network firewall/proxy
    • DNS resolution issue
    • Temporary connectivity problem

Automatic Recovery Actions:
  ⟳ Retrying with exponential backoff...
  Attempt 1/3: Failed (30s timeout)
  Attempt 2/3: Failed (30s timeout)
  Attempt 3/3: Failed (30s timeout)
  ✗ Auto-recovery failed

Manual Recovery Options:

  Option 1: Retry After Delay
  ───────────────────────────────────────
  Wait 1-2 minutes, then retry:
    /sandbox-exec #42 "npm install"

  Network issues often resolve quickly

  Option 2: Check NPM Status
  ───────────────────────────────────────
  Visit: https://status.npmjs.org

  Verify npm registry is operational

  Option 3: Use Alternative Registry
  ───────────────────────────────────────
    /sandbox-exec #42 "npm install --registry https://registry.npmmirror.com"

  Use mirror registry (China users)

  Option 4: Clear NPM Cache
  ───────────────────────────────────────
    /sandbox-exec #42 "npm cache clean --force && npm install"

  Clear cache and retry

  Option 5: Check Proxy Settings
  ───────────────────────────────────────
    /sandbox-exec #42 "npm config get proxy"
    /sandbox-exec #42 "npm config get https-proxy"

  Verify proxy configuration

Recommendation: Option 1 (retry) for transient issues, Option 2 to check status
```

### Error 6: Out of Memory

```
❌ Error: Out of memory

Execution Details:
  Sandbox: sbx_abc123xyz
  Command: npm run build
  Exit Code: 137 (SIGKILL - Out of Memory)
  Duration: 45.2s

Error Output:
───────────────────────────────────────────────
> build
> tsc && vite build

[tsc] Compiling TypeScript...

<--- JS stacktrace --->

FATAL ERROR: Reached heap limit Allocation failed - JavaScript heap out of memory
───────────────────────────────────────────────

Resource Status:
  Memory Limit: 2 GB
  Memory Used: 2.1 GB (105%)
  CPU Usage: 89%

Memory Consumption Breakdown:
  Node.js heap: 1.8 GB
  System: 0.3 GB
  Available: 0 GB

Automatic Recovery Actions:
  ⟳ Analyzing memory usage...
  ✓ Identified large TypeScript compilation
  ⚠ Sandbox memory limit reached

Manual Recovery Options:

  Option 1: Increase Node Memory
  ───────────────────────────────────────
    /sandbox-exec #42 "NODE_OPTIONS='--max-old-space-size=4096' npm run build"

  Increase Node.js heap to 4 GB

  Option 2: Build in Incremental Mode
  ───────────────────────────────────────
  Update tsconfig.json to use incremental builds:
    /sandbox-debug #42
    sandbox$ vim tsconfig.json
    [Add "incremental": true]

  Option 3: Split Build Process
  ───────────────────────────────────────
    /sandbox-exec #42 "tsc --build src/part1"
    /sandbox-exec #42 "tsc --build src/part2"
    /sandbox-exec #42 "vite build"

  Build in smaller chunks

  Option 4: Optimize Dependencies
  ───────────────────────────────────────
    /sandbox-exec #42 "npm prune"
    /sandbox-exec #42 "npm dedupe"

  Remove unnecessary dependencies

  Option 5: Use Larger Sandbox
  ───────────────────────────────────────
  Modify .e2b/config to increase memory:
    {
      "memory_mb": 4096
    }

  Then recreate sandbox:
    /implement-feature #42 --mode sandbox --force

Recommendation: Option 1 (increase Node memory) for immediate fix
```

### Error 7: Command Not Found

```
❌ Error: Command not found

Execution Details:
  Sandbox: sbx_abc123xyz
  Command: yarn install
  Exit Code: 127

Error Output:
───────────────────────────────────────────────
bash: yarn: command not found
───────────────────────────────────────────────

Command Analysis:
  Requested: yarn
  Status: Not installed
  Available Package Managers:
    ✓ npm (v10.2.3)
    ✗ yarn (not installed)
    ✗ pnpm (not installed)

Automatic Recovery Actions:
  ⟳ Searching for alternative...
  ✓ Found equivalent: npm install

Manual Recovery Options:

  Option 1: Use NPM Instead
  ───────────────────────────────────────
    /sandbox-exec #42 "npm install"

  Use npm (already installed)

  Option 2: Install Yarn
  ───────────────────────────────────────
    /sandbox-exec #42 "npm install --global yarn"
    /sandbox-exec #42 "yarn install"

  Install yarn first, then use it

  Option 3: Use Corepack (Node 16.10+)
  ───────────────────────────────────────
    /sandbox-exec #42 "corepack enable"
    /sandbox-exec #42 "corepack prepare yarn@stable --activate"
    /sandbox-exec #42 "yarn install"

  Enable and use corepack for yarn

  Option 4: Add to Sandbox Template
  ───────────────────────────────────────
  Edit .e2b/Dockerfile:
    RUN npm install --global yarn

  Then recreate sandbox:
    /implement-feature #42 --mode sandbox --force

Recommendation: Option 1 (use npm) for quickest solution
```

### Error 8: Disk Space Exhausted

```
❌ Error: Disk space exhausted

Execution Details:
  Sandbox: sbx_abc123xyz
  Command: npm install
  Exit Code: 1

Error Output:
───────────────────────────────────────────────
npm ERR! code ENOSPC
npm ERR! syscall write
npm ERR! errno -28
npm ERR! Error: ENOSPC: no space left on device, write
───────────────────────────────────────────────

Disk Usage:
  Total: 10 GB
  Used: 10.0 GB (100%)
  Available: 0 bytes

Storage Breakdown:
  /workspace/node_modules: 4.2 GB (42%)
  /workspace/.git: 2.8 GB (28%)
  /workspace/build: 1.9 GB (19%)
  /tmp: 892 MB (9%)
  Other: 208 MB (2%)

Automatic Recovery Actions:
  ⟳ Attempting cleanup...
  ✓ Cleared /tmp: freed 892 MB
  ✓ Cleared npm cache: freed 156 MB
  ⚠ Still 98% full (insufficient)

Manual Recovery Options:

  Option 1: Clean Build Artifacts
  ───────────────────────────────────────
    /sandbox-exec #42 "rm -rf build dist .next .cache"

  Expected to free: ~2 GB

  Option 2: Remove Dependencies and Reinstall
  ───────────────────────────────────────
    /sandbox-exec #42 "rm -rf node_modules"
    /sandbox-exec #42 "npm install --production"

  Install only production dependencies

  Option 3: Git Garbage Collection
  ───────────────────────────────────────
    /sandbox-exec #42 "git gc --aggressive --prune=now"

  Compress git repository

  Option 4: Create New Sandbox
  ───────────────────────────────────────
    /implement-feature #42 --mode sandbox --force

  Fresh sandbox with clean state

Recommendation: Option 1 + Option 3, then retry install
```

## Integration

### Integration with Bumba Sandbox SDK
- Uses `sandbox.commands.run()` API
- Supports both synchronous and streaming execution
- Automatic environment setup
- Resource monitoring and limits
- Exit code and signal handling

### Integration with MCP Tools
- Wraps `execute_command` MCP tool
- Provides enhanced error handling
- Adds timeout management
- Streams output formatting
- Integrates with issue tracking

### Integration with CI/CD
```bash
# Example GitHub Actions workflow
- name: Run Tests in Sandbox
  run: |
    claude /sandbox-exec #${{ github.event.issue.number }} "npm test"

- name: Build Project
  run: |
    claude /sandbox-exec #${{ github.event.issue.number }} "npm run build"

- name: Deploy if Tests Pass
  if: success()
  run: |
    claude /sandbox-exec #${{ github.event.issue.number }} "npm run deploy"
```

### Integration with Other Commands
- `/sandbox-debug #42`: For interactive debugging
- `/test #42`: For comprehensive test execution
- `/sync-sandbox-code #42`: To bring changes to worktree
- `/sandbox-status`: To check sandbox health before execution

## Use Cases

### Use Case 1: Quick Test Execution
**Scenario**: Verify specific functionality after making changes

**Commands**:
```bash
/sandbox-exec #42 "npm test -- src/auth/login.test.ts"
/sandbox-exec #42 "npm run lint -- src/auth"
```

### Use Case 2: Dependency Management
**Scenario**: Test new package before adding to project

**Commands**:
```bash
/sandbox-exec #42 "npm install axios@latest"
/sandbox-exec #42 "npm test"
# If successful, sync to worktree
/sync-sandbox-code #42
```

### Use Case 3: Build Verification
**Scenario**: Ensure project builds successfully

**Commands**:
```bash
/sandbox-exec #42 "npm run build" --timeout 600
/sandbox-exec #42 "npm run test:prod"
```

### Use Case 4: Code Quality Checks
**Scenario**: Run linting and formatting checks

**Commands**:
```bash
/sandbox-exec #42 "npm run lint"
/sandbox-exec #42 "npm run format"
/sandbox-exec #42 "npm run type-check"
```

### Use Case 5: Database Operations
**Scenario**: Run migrations and seed data

**Commands**:
```bash
/sandbox-exec #42 "npm run db:migrate"
/sandbox-exec #42 "npm run db:seed"
/sandbox-exec #42 "npm run db:verify"
```

## Performance Considerations

### Command Execution Speed
- Non-interactive commands are faster than interactive sessions
- Network latency affects remote sandboxes
- Large output can slow down response
- Use `--stream` for long-running commands to see progress

### Resource Efficiency
- Commands run in existing sandbox (no startup overhead)
- Multiple commands can share sandbox session
- Timeout prevents resource exhaustion
- Automatic cleanup after execution

### Optimization Tips
- Chain related commands with `&&` to reduce overhead
- Use `--silent` when output not needed
- Set appropriate timeouts for long operations
- Stream output for real-time feedback on builds

## Security Considerations

### Command Injection Prevention
- Commands must be quoted properly
- Shell metacharacters are escaped
- Environment variables validated
- No arbitrary code execution outside sandbox

### Sandbox Isolation
- Commands execute in isolated sandbox
- No access to host filesystem
- Network access controlled by sandbox
- Resource limits enforced

### Credential Safety
- Never pass credentials in commands
- Use `--env` for sensitive environment variables
- Environment variables not logged
- Output sanitized for secrets

## Notes

- **Non-Interactive**: Best for automation and quick operations
- **Timeout Default**: 300 seconds (5 minutes), configurable
- **Output Capture**: Stdout and stderr captured by default
- **Exit Codes**: Preserved from command execution
- **Streaming**: Available for long-running commands
- **Chaining**: Supports `&&`, `||`, and `;` operators
- **Environment**: Custom env vars supported via `--env`
- **Working Directory**: Configurable via `--cwd`
- **Resource Limits**: Enforced by Bumba Sandbox
- **Error Recovery**: Automatic retry for transient failures
- **CI/CD Ready**: Perfect for automated pipelines
- **Complements /sandbox-debug**: Use exec for automation, debug for exploration

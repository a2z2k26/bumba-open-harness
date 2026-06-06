---
name: debug
description: Debug sandbox environment
---

# /sandbox-debug Command

Opens an interactive shell session in a sandbox for real-time debugging, code inspection, and live modification. Provides full access to the sandbox environment for investigating issues, running tests, and making fixes.

## Usage

```
/sandbox-debug <sandbox-id|#issue> [options]
```

## Parameters

- `<sandbox-id|#issue>` (required): Sandbox ID (e.g., `sbx_abc123xyz`) or issue number (e.g., `#42`)
- `--shell <shell>` (optional): Shell to use - options: `bash` (default), `zsh`, `sh`, `fish`
- `--cwd <directory>` (optional): Starting directory - default: `/workspace`
- `--timeout <minutes>` (optional): Session timeout in minutes - default: 60
- `--env <KEY=VALUE>` (optional): Set environment variables (repeatable)

## Workflow

### Step 1: Sandbox Connection

```
🐛 Interactive Sandbox Debugger
═══════════════════════════════════════════════

Resolving target...
  Issue: #42 - Fix SQL Injection Vulnerability
  Sandbox: sbx_abc123xyz (active)
  Uptime: 3h 27m

Validating sandbox state...
  ✓ Sandbox running
  ✓ Network accessible
  ✓ Shell available: /bin/bash

Establishing connection...
  Connecting to sbx_abc123xyz...
  Initializing terminal session...
  Setting up environment...

───────────────────────────────────────────────
```

### Step 2: Interactive Shell Session

```
✅ Connected to Sandbox

Environment Information:
  Sandbox ID: sbx_abc123xyz
  Issue: #42 - Fix SQL Injection Vulnerability
  Working Dir: /workspace
  Shell: /bin/bash
  User: sandbox
  Timeout: 60 minutes

Available Commands:
  • Standard shell commands (ls, cd, cat, vim, etc.)
  • Git commands (git status, git diff, etc.)
  • Package managers (npm, pip, cargo, go, etc.)
  • Test runners (npm test, pytest, cargo test, etc.)
  • Debugging tools (gdb, lldb, node --inspect, etc.)

Tips:
  • Type 'exit' or Ctrl+D to end session
  • Changes persist in sandbox until destroyed
  • Use /sync-sandbox-code to bring changes back
  • Session auto-saves on exit

───────────────────────────────────────────────

sandbox@sbx_abc123xyz:/workspace$
```

### Step 3: Debugging Workflow

```
sandbox$ ls -la
total 48
drwxr-xr-x 8 sandbox sandbox 4096 Jan 18 10:23 .
drwxr-xr-x 3 sandbox sandbox 4096 Jan 18 07:15 ..
drwxr-xr-x 8 sandbox sandbox 4096 Jan 18 10:23 .git
-rw-r--r-- 1 sandbox sandbox  312 Jan 18 07:15 .gitignore
drwxr-xr-x 3 sandbox sandbox 4096 Jan 18 07:15 node_modules
-rw-r--r-- 1 sandbox sandbox 1247 Jan 18 07:15 package.json
drwxr-xr-x 4 sandbox sandbox 4096 Jan 18 10:22 src
drwxr-xr-x 3 sandbox sandbox 4096 Jan 18 10:23 tests

sandbox$ npm test -- src/auth/login.test.ts
> test
> jest src/auth/login.test.ts

 FAIL  src/auth/login.test.ts
  Login Authentication
    ✗ should prevent SQL injection (42ms)
    ✓ should hash passwords (12ms)
    ✓ should validate email format (8ms)

  ● Login Authentication › should prevent SQL injection

    Expected parameterized query but found string concatenation

    Received:
      const query = `SELECT * FROM users WHERE email = '${email}'`;

    Expected:
      const query = 'SELECT * FROM users WHERE email = ?';

    at Object.<anonymous> (tests/auth/login.test.ts:23:5)

Tests: 1 failed, 2 passed, 3 total
Time:  2.341s

sandbox$ cat src/auth/login.ts
import { db } from '../db';
import { hash } from '../utils/crypto';

export async function login(email: string, password: string) {
  // ⚠️ VULNERABILITY: SQL Injection
  const query = `SELECT * FROM users WHERE email = '${email}'`;
  const user = await db.query(query);

  if (!user) {
    throw new Error('Invalid credentials');
  }

  const passwordHash = hash(password);
  if (user.password !== passwordHash) {
    throw new Error('Invalid credentials');
  }

  return user;
}

sandbox$ vim src/auth/login.ts
[Opening vim editor...]
[Fixing SQL injection by using parameterized queries...]

sandbox$ cat src/auth/login.ts
import { db } from '../db';
import { hash } from '../utils/crypto';

export async function login(email: string, password: string) {
  // ✅ FIXED: Using parameterized query
  const query = 'SELECT * FROM users WHERE email = ?';
  const user = await db.query(query, [email]);

  if (!user) {
    throw new Error('Invalid credentials');
  }

  const passwordHash = hash(password);
  if (user.password !== passwordHash) {
    throw new Error('Invalid credentials');
  }

  return user;
}

sandbox$ npm test -- src/auth/login.test.ts
> test
> jest src/auth/login.test.ts

 PASS  src/auth/login.test.ts
  Login Authentication
    ✓ should prevent SQL injection (18ms)
    ✓ should hash passwords (11ms)
    ✓ should validate email format (7ms)

Tests: 3 passed, 3 total
Time:  1.892s

sandbox$ git status
On branch feature/issue-42-sql-injection
Changes not staged for commit:
  modified:   src/auth/login.ts

sandbox$ git diff src/auth/login.ts
diff --git a/src/auth/login.ts b/src/auth/login.ts
index a3f2c1d..b8e4f7a 100644
--- a/src/auth/login.ts
+++ b/src/auth/login.ts
@@ -2,8 +2,8 @@ import { db } from '../db';
 import { hash } from '../utils/crypto';

 export async function login(email: string, password: string) {
-  // ⚠️ VULNERABILITY: SQL Injection
-  const query = `SELECT * FROM users WHERE email = '${email}'`;
-  const user = await db.query(query);
+  // ✅ FIXED: Using parameterized query
+  const query = 'SELECT * FROM users WHERE email = ?';
+  const user = await db.query(query, [email]);

   if (!user) {
     throw new Error('Invalid credentials');

sandbox$ exit
logout

───────────────────────────────────────────────
```

### Step 4: Session Summary

```
✅ Debug Session Complete
═══════════════════════════════════════════════

Session Details:
  Sandbox: sbx_abc123xyz
  Issue: #42 - Fix SQL Injection Vulnerability
  Duration: 7m 43s
  Commands Executed: 12

File Changes Detected:
  Modified Files (1):
    • src/auth/login.ts (+2, -2)

Test Results:
  Previous: 1 failed, 2 passed
  Current: 3 passed
  Status: ✅ All tests passing

Git Status:
  Branch: feature/issue-42-sql-injection
  Uncommitted Changes: 1 file

Next Steps:
  1. Review changes in sandbox:
     /sandbox-exec sbx_abc123xyz "git diff"

  2. Sync changes to worktree:
     /sync-sandbox-code #42

  3. Run full test suite:
     /test #42

  4. Commit and push:
     git add src/auth/login.ts
     git commit -m "Fix SQL injection in login"
     git push origin feature/issue-42-sql-injection

  5. Create pull request:
     /implement-feature #42 --mode pr

Session saved to: .claude/debug-sessions/sbx_abc123xyz_20250118_102347.log
```

## Examples

### Example 1: Debug by Issue Number
```
/sandbox-debug #42
```

**Use Case**: Quick access using issue number when sandbox is already associated with the issue.

**Output**:
```
🐛 Interactive Sandbox Debugger
═══════════════════════════════════════════════

Resolving issue #42...
  Found sandbox: sbx_abc123xyz
  Status: Active

Connecting to sbx_abc123xyz...

✅ Connected to Sandbox
sandbox@sbx_abc123xyz:/workspace$
```

### Example 2: Debug by Sandbox ID
```
/sandbox-debug sbx_abc123xyz
```

**Use Case**: Direct sandbox access when you know the exact sandbox ID.

**Output**:
```
🐛 Interactive Sandbox Debugger
═══════════════════════════════════════════════

Validating sandbox sbx_abc123xyz...
  ✓ Sandbox exists
  ✓ Sandbox running

Connecting to sbx_abc123xyz...

✅ Connected to Sandbox
sandbox@sbx_abc123xyz:/workspace$
```

### Example 3: Use Specific Shell
```
/sandbox-debug #42 --shell zsh
```

**Use Case**: Use zsh when you need specific shell features or have custom zsh configurations.

**Output**:
```
🐛 Interactive Sandbox Debugger
═══════════════════════════════════════════════

Shell: /bin/zsh (requested)
Checking shell availability...
  ✓ Zsh installed: /bin/zsh (version 5.8)

✅ Connected to Sandbox
sandbox@sbx_abc123xyz:/workspace %
```

### Example 4: Start in Specific Directory
```
/sandbox-debug #42 --cwd /workspace/src/auth
```

**Use Case**: Jump directly to the directory where you need to debug.

**Output**:
```
✅ Connected to Sandbox
Working Directory: /workspace/src/auth

sandbox@sbx_abc123xyz:/workspace/src/auth$ ls
login.ts  register.ts  password-reset.ts  session.ts
```

### Example 5: Set Environment Variables
```
/sandbox-debug #42 --env DEBUG=* --env NODE_ENV=development
```

**Use Case**: Enable debugging output or set specific environment configurations.

**Output**:
```
✅ Connected to Sandbox
Environment Variables Set:
  DEBUG=*
  NODE_ENV=development

sandbox@sbx_abc123xyz:/workspace$ echo $DEBUG
*
sandbox@sbx_abc123xyz:/workspace$ echo $NODE_ENV
development
```

### Example 6: Extended Session Timeout
```
/sandbox-debug #42 --timeout 120
```

**Use Case**: Complex debugging sessions that need more than the default 60 minutes.

**Output**:
```
✅ Connected to Sandbox
Session timeout: 120 minutes

sandbox@sbx_abc123xyz:/workspace$
```

### Example 7: Python Debugging with IPython
```
/sandbox-debug #42 --shell bash
```

**Session**:
```
sandbox$ ipython
Python 3.11.0 (main, Oct 24 2022, 18:26:48)
IPython 8.12.0 -- An enhanced Interactive Python.

In [1]: from src.data_processor import process_data

In [2]: %debug
> /workspace/src/data_processor.py(42)process_data()
     40     def process_data(df):
     41         # Debug breakpoint
---> 42         import pdb; pdb.set_trace()
     43         return df.groupby('category').sum()

ipdb> df.head()
   category  value
0  A         100
1  B         200
2  A         150
```

### Example 8: Go Debugging with Delve
```
/sandbox-debug #42
```

**Session**:
```
sandbox$ dlv test ./pkg/calculator
Type 'help' for list of commands.
(dlv) break calculator.go:42
Breakpoint 1 set at 0x10a4f20 for main.Calculate()
(dlv) continue
> main.Calculate() ./pkg/calculator/calculator.go:42
    42:         result := a + b
(dlv) print a
10
(dlv) print b
20
```

## Advanced Debugging Workflows

### Workflow 1: Test-Driven Debug Loop

```
# 1. Run failing test
sandbox$ npm test -- src/auth/login.test.ts
[See failure]

# 2. Identify issue
sandbox$ cat src/auth/login.ts | grep -A10 "login"
[Spot SQL injection]

# 3. Fix code
sandbox$ vim src/auth/login.ts
[Make fix]

# 4. Verify fix
sandbox$ npm test -- src/auth/login.test.ts
[Tests pass]

# 5. Run full suite
sandbox$ npm test
[All tests pass]

# 6. Check coverage
sandbox$ npm run test:coverage
[Coverage maintained]

# 7. Exit and sync
sandbox$ exit
```

### Workflow 2: Performance Profiling

```
# 1. Install profiling tools
sandbox$ npm install --save-dev clinic

# 2. Run profiler
sandbox$ clinic doctor -- node src/server.js
[Server starts with profiling]

# 3. Generate load (in another terminal via /sandbox-exec)
[Load testing]

# 4. Stop and analyze
^C
Analysing data...
Generated report: .clinic/doctor.html

# 5. View results
sandbox$ cat .clinic/doctor.html
[Review performance bottlenecks]

# 6. Make optimizations
sandbox$ vim src/slow-function.ts
[Optimize code]

# 7. Re-profile
sandbox$ clinic doctor -- node src/server.js
[Verify improvements]
```

### Workflow 3: Dependency Investigation

```
# 1. Check installed versions
sandbox$ npm list
├── express@4.18.2
├── lodash@4.17.21
└── typescript@5.3.3

# 2. Identify outdated packages
sandbox$ npm outdated
Package      Current  Wanted  Latest
express      4.18.2   4.18.2  4.19.2
lodash       4.17.21  4.17.21  4.17.21
typescript   5.3.3    5.3.3   5.6.3

# 3. Test upgrade in sandbox
sandbox$ npm install express@latest
[Install new version]

# 4. Run tests
sandbox$ npm test
[Check for compatibility issues]

# 5. If successful, document change
sandbox$ echo "Upgraded express to 4.19.2" > .changes.txt
```

### Workflow 4: Git History Investigation

```
# 1. Find when bug was introduced
sandbox$ git log --oneline --all | head -20
[Review recent commits]

# 2. Use git bisect
sandbox$ git bisect start
sandbox$ git bisect bad HEAD
sandbox$ git bisect good v1.2.0

# 3. Test each commit
sandbox$ npm test
[Mark good/bad]

# 4. Find culprit commit
sandbox$ git bisect bad
Bisecting: 0 revisions left to test
abc123f Refactor authentication logic

# 5. Review the bad commit
sandbox$ git show abc123f
[Identify exact change that broke tests]

# 6. Reset bisect
sandbox$ git bisect reset
```

## Error Handling

### Error 1: Sandbox Not Running

```
❌ Error: Sandbox not running

Sandbox Resolution:
  Issue: #42 - Fix SQL Injection
  Expected Sandbox: sbx_abc123xyz
  Actual Status: Terminated
  Terminated At: 2025-01-18 09:15:23 UTC
  Reason: Timeout (2 hours idle)

Cannot establish connection to terminated sandbox.

Automatic Recovery Actions:
  ✓ Checked for snapshots: None available
  ✓ Checked for backup: Worktree sync 45 minutes ago
  ✓ Latest changes synced to worktree

Manual Recovery Options:

  Option 1: Create New Sandbox
  ───────────────────────────────────────
  Start fresh sandbox for this issue:
    /implement-feature #42 --mode sandbox

  This will:
    • Create new sandbox from worktree
    • Reinstall dependencies
    • Ready for debugging in ~2 minutes

  Option 2: Use Worktree Directly
  ───────────────────────────────────────
  Debug in local worktree instead:
    cd $(claude worktree path #42)
    npm test

  This will:
    • Work with latest synced code
    • No sandbox overhead
    • Local development environment

  Option 3: Restore from Snapshot
  ───────────────────────────────────────
  If you have a recent snapshot:
    /sandbox-restore sbx_abc123xyz --snapshot snap_xyz

  This will:
    • Restore exact sandbox state
    • Include all files and state
    • Resume where you left off

Recommendation: Option 1 (create new sandbox) for clean state
```

### Error 2: Connection Timeout

```
❌ Error: Connection timeout

Connection Details:
  Sandbox: sbx_abc123xyz
  Status: Running (verified)
  Timeout After: 30 seconds
  Connection Attempts: 3
  Last Attempt: 2025-01-18 10:23:47 UTC

Diagnostic Information:
  Sandbox Health Check:
    ✓ Sandbox exists
    ✓ Status is 'running'
    ⚠ Network ping: timeout
    ⚠ Shell socket: not responding

  Bumba Sandbox Service Status:
    ✓ API accessible
    ✓ Authentication valid
    ⚠ Elevated latency detected (>2000ms)

  Local Network:
    ✓ Internet connectivity
    ✓ DNS resolution
    ⚠ High latency to E2B endpoint (2847ms)

Possible Causes:
  1. Sandbox resource exhaustion (CPU/memory)
  2. Network connectivity issues
  3. E2B service degradation
  4. Firewall blocking websocket connection

Automatic Recovery Actions:
  ⟳ Retrying connection with exponential backoff...
  Attempt 1/5: Failed (30s timeout)
  Attempt 2/5: Failed (30s timeout)
  Attempt 3/5: Failed (30s timeout)

  ✗ Auto-recovery failed

Manual Recovery Options:

  Option 1: Check Sandbox Resources
  ───────────────────────────────────────
    /sandbox-status sbx_abc123xyz

  Look for:
    • CPU usage > 90%
    • Memory usage > 90%
    • Disk usage > 95%

  If high resource usage:
    /sandbox-exec sbx_abc123xyz "killall node" --force
    Wait 30 seconds, then retry connection

  Option 2: Restart Sandbox
  ───────────────────────────────────────
    # Destroy and recreate
    /implement-feature #42 --mode sandbox --force

  This will:
    • Terminate current sandbox
    • Create fresh sandbox
    • Restore from latest worktree sync

  Option 3: Check Bumba Sandbox Service Status
  ───────────────────────────────────────
    Visit: https://status.e2b.dev

  If service issues detected:
    • Wait for resolution
    • Use worktree for debugging
    • Monitor status page

  Option 4: Use Local Worktree
  ───────────────────────────────────────
    cd $(claude worktree path #42)

  Continue debugging locally while investigating
  sandbox connectivity issues.

Recommendation: Option 1 (check resources) first, then Option 2 if needed
```

### Error 3: Shell Not Available

```
❌ Error: Shell not available

Shell Configuration:
  Requested Shell: zsh
  Shell Path: /bin/zsh
  Sandbox: sbx_abc123xyz

Shell Detection:
  ✗ /bin/zsh: not found
  ✓ /bin/bash: available
  ✓ /bin/sh: available
  ✗ /usr/bin/fish: not found

Available shells in sandbox:
  • /bin/bash (recommended)
  • /bin/sh

Automatic Recovery Actions:
  ⟳ Falling back to default shell...
  ✓ Switched to /bin/bash

Manual Recovery Options:

  Option 1: Install Requested Shell
  ───────────────────────────────────────
    /sandbox-exec sbx_abc123xyz "apt-get update && apt-get install -y zsh"

  Then retry:
    /sandbox-debug #42 --shell zsh

  Option 2: Use Available Shell
  ───────────────────────────────────────
    /sandbox-debug #42 --shell bash

  Bash is fully compatible for debugging tasks.

  Option 3: Customize Sandbox Template
  ───────────────────────────────────────
  Add to .bumba/Dockerfile:
    RUN apt-get update && apt-get install -y zsh

  Then recreate sandbox:
    /implement-feature #42 --mode sandbox --force

Recommendation: Option 2 (use bash) for immediate debugging
```

### Error 4: Permission Denied

```
❌ Error: Permission denied

Access Attempt:
  File: /workspace/src/auth/secrets.enc
  Operation: read
  User: sandbox
  Required Permissions: -rw-------
  Actual Permissions: -rw------- (owner: root)

Permission Check:
  ✗ User 'sandbox' cannot read file
  ✗ File owned by 'root'
  ✓ File exists

Automatic Recovery Actions:
  ⟳ Attempting permission fix...
  ✗ Cannot change ownership (insufficient privileges)
  ✗ Cannot change permissions (insufficient privileges)

Manual Recovery Options:

  Option 1: Fix Ownership
  ───────────────────────────────────────
    /sandbox-exec sbx_abc123xyz "sudo chown sandbox:sandbox /workspace/src/auth/secrets.enc"

  Then retry access in debug session.

  Option 2: Fix Permissions
  ───────────────────────────────────────
    /sandbox-exec sbx_abc123xyz "sudo chmod 644 /workspace/src/auth/secrets.enc"

  Makes file readable by all users.

  Option 3: Investigate File Origin
  ───────────────────────────────────────
  Check why file has wrong ownership:
    /sandbox-exec sbx_abc123xyz "ls -la /workspace/src/auth/secrets.enc"
    /sandbox-exec sbx_abc123xyz "git log --follow -- src/auth/secrets.enc"

  May need to fix build/setup script.

Security Warning:
  ⚠ secrets.enc appears to contain sensitive data
  ⚠ Verify this file should be in version control
  ⚠ Consider using environment variables instead

Recommendation: Option 3 (investigate) to prevent recurrence
```

### Error 5: Disk Space Exhausted

```
❌ Error: Disk space exhausted

Disk Usage:
  Sandbox: sbx_abc123xyz
  Total Space: 10 GB
  Used Space: 10.0 GB (100%)
  Available: 0 bytes

Breakdown:
  /workspace/node_modules: 4.2 GB (42%)
  /workspace/.git: 2.8 GB (28%)
  /workspace/build: 1.9 GB (19%)
  /tmp: 892 MB (9%)
  Other: 208 MB (2%)

Automatic Recovery Actions:
  ⟳ Attempting cleanup...
  ✓ Cleared /tmp: freed 892 MB
  ✓ Cleared npm cache: freed 156 MB
  ✓ Remaining: 98% full (insufficient)

Manual Recovery Options:

  Option 1: Clean Build Artifacts
  ───────────────────────────────────────
    /sandbox-exec sbx_abc123xyz "rm -rf build dist .next"

  Expected to free: ~2 GB

  Option 2: Clean Dependencies
  ───────────────────────────────────────
    /sandbox-exec sbx_abc123xyz "rm -rf node_modules && npm install --production"

  Expected to free: ~2-3 GB (removes dev dependencies)

  Option 3: Git Garbage Collection
  ───────────────────────────────────────
    /sandbox-exec sbx_abc123xyz "git gc --aggressive --prune=now"

  Expected to free: ~500 MB - 1 GB

  Option 4: Create New Sandbox
  ───────────────────────────────────────
    /implement-feature #42 --mode sandbox --force

  Fresh sandbox with only necessary files.

  Option 5: Increase Sandbox Size
  ───────────────────────────────────────
  Modify .bumba/config:
    {
      "disk_size_gb": 20
    }

  Then recreate sandbox.

Recommendation: Option 1 + Option 3, then retry. If issue persists, use Option 4.
```

### Error 6: Environment Variable Missing

```
❌ Error: Required environment variable not set

Missing Variable:
  Name: DATABASE_URL
  Required By: src/db/connection.ts:12
  Sandbox: sbx_abc123xyz

Environment Check:
  ✗ DATABASE_URL: not set
  ✓ NODE_ENV: development
  ✓ PORT: 3000
  ✗ API_KEY: not set

Automatic Recovery Actions:
  ⟳ Checking for .env file...
  ✓ Found: /workspace/.env.example
  ✗ Not found: /workspace/.env

Manual Recovery Options:

  Option 1: Create .env File
  ───────────────────────────────────────
    /sandbox-exec sbx_abc123xyz "cp .env.example .env"

  Then edit with appropriate values:
    /sandbox-debug #42
    sandbox$ vim .env

  Option 2: Set Variable Inline
  ───────────────────────────────────────
    /sandbox-debug #42 --env DATABASE_URL=postgresql://localhost/testdb

  Or in debug session:
    sandbox$ export DATABASE_URL=postgresql://localhost/testdb

  Option 3: Add to E2B Config
  ───────────────────────────────────────
  Edit .e2b/config:
    {
      "env": {
        "DATABASE_URL": "postgresql://localhost/testdb",
        "API_KEY": "test-key-123"
      }
    }

  Then recreate sandbox:
    /implement-feature #42 --mode sandbox --force

Recommendation: Option 1 for temporary debugging, Option 3 for permanent fix
```

### Error 7: Port Already in Use

```
❌ Error: Port already in use

Port Conflict:
  Port: 3000
  Requested By: npm run dev
  Currently Used By: node src/old-server.js (PID: 1234)
  Sandbox: sbx_abc123xyz

Process Information:
  PID: 1234
  Command: node src/old-server.js
  Started: 2025-01-18 08:30:15 UTC
  Duration: 2h 15m
  CPU: 0.1%
  Memory: 89 MB

Automatic Recovery Actions:
  ⟳ Checking if process can be terminated safely...
  ⚠ Process running for >2 hours, may be important
  ✗ Auto-termination skipped (requires manual confirmation)

Manual Recovery Options:

  Option 1: Kill Existing Process
  ───────────────────────────────────────
  In debug session:
    sandbox$ kill 1234

  Or forcefully:
    sandbox$ kill -9 1234

  Then retry:
    sandbox$ npm run dev

  Option 2: Use Different Port
  ───────────────────────────────────────
  In debug session:
    sandbox$ PORT=3001 npm run dev

  Or modify package.json to use different default port.

  Option 3: Investigate Process
  ───────────────────────────────────────
  Check what the process is:
    sandbox$ ps aux | grep 1234
    sandbox$ lsof -p 1234

  Determine if it's needed before killing.

  Option 4: Check All Port Usage
  ───────────────────────────────────────
    sandbox$ netstat -tlnp
    sandbox$ lsof -i :3000

  See all processes using network ports.

Recommendation: Option 3 (investigate) to avoid killing important processes
```

### Error 8: Command Not Found

```
❌ Error: Command not found

Command Execution:
  Command: dlv debug
  Shell: /bin/bash
  Sandbox: sbx_abc123xyz

Command Check:
  ✗ dlv: command not found
  ⟳ Searching in PATH...
    /usr/local/bin: not found
    /usr/bin: not found
    /bin: not found
  ✗ Package 'delve' not installed

Common Debugging Tools Status:
  ✓ gdb: available
  ✓ node: available (v18.19.0)
  ✗ dlv: not installed
  ✗ lldb: not installed
  ✓ python: available (3.11.0)
  ✓ ipdb: available

Automatic Recovery Actions:
  ⟳ Detecting package manager...
  ✓ Found: apt-get
  ⟳ Searching repositories...
  ✓ Package 'delve' available

Manual Recovery Options:

  Option 1: Install via Package Manager
  ───────────────────────────────────────
  In debug session:
    sandbox$ sudo apt-get update
    sandbox$ sudo apt-get install -y delve

  Then retry command:
    sandbox$ dlv debug

  Option 2: Install via Go
  ───────────────────────────────────────
  If Go is available:
    sandbox$ go install github.com/go-delve/delve/cmd/dlv@latest
    sandbox$ export PATH=$PATH:$(go env GOPATH)/bin
    sandbox$ dlv debug

  Option 3: Use Alternative Tool
  ───────────────────────────────────────
  Use gdb instead:
    sandbox$ gdb ./myprogram

  Or for Go specifically:
    sandbox$ go run -gcflags="-N -l" main.go

  Option 4: Add to Sandbox Template
  ───────────────────────────────────────
  Edit .e2b/Dockerfile:
    RUN apt-get update && apt-get install -y delve

  Then recreate sandbox:
    /implement-feature #42 --mode sandbox --force

Recommendation: Option 1 for immediate use, Option 4 for permanent availability
```

### Error 9: Session Timeout

```
❌ Error: Session timeout

Session Information:
  Sandbox: sbx_abc123xyz
  Started: 2025-01-18 10:00:00 UTC
  Ended: 2025-01-18 11:00:00 UTC
  Duration: 60 minutes (timeout limit)
  Timeout Reason: Maximum session duration exceeded

Session State:
  Commands Executed: 47
  Files Modified: 3
  Uncommitted Changes: Yes
  Test Results: Last run passed (15 minutes ago)

Automatic Recovery Actions:
  ✓ Session log saved: .claude/debug-sessions/sbx_abc123xyz_20250118_100000.log
  ✓ File changes preserved in sandbox
  ✓ Git state preserved
  ⚠ Shell session terminated

Manual Recovery Options:

  Option 1: Resume Session
  ───────────────────────────────────────
    /sandbox-debug #42

  This will:
    • Reconnect to same sandbox
    • Restore working directory
    • Access all previous changes
    • Continue where you left off

  Option 2: Extend Timeout Next Time
  ───────────────────────────────────────
    /sandbox-debug #42 --timeout 120

  Set longer timeout for complex debugging (max: 240 minutes)

  Option 3: Review Session Log
  ───────────────────────────────────────
    cat .claude/debug-sessions/sbx_abc123xyz_20250118_100000.log

  Review all commands and output from session.

  Option 4: Sync Changes
  ───────────────────────────────────────
  If done debugging:
    /sync-sandbox-code #42

  Brings changes back to worktree.

Files Modified (Preserved):
  • src/auth/login.ts (+12, -8)
  • src/auth/session.ts (+25, -10)
  • tests/auth/login.test.ts (+5, -2)

Recommendation: Option 1 (resume session) to continue debugging
```

### Error 10: Git Conflict Detected

```
❌ Error: Git conflict detected

Conflict Information:
  Sandbox: sbx_abc123xyz
  Branch: feature/issue-42-sql-injection
  Conflicted Files: 2

Conflict Details:
  File 1: src/auth/login.ts
  ───────────────────────────────────────
  Conflict: Lines 15-23
  Ours: Parameterized query implementation
  Theirs: Different parameterization approach

  File 2: package.json
  ───────────────────────────────────────
  Conflict: Line 42
  Ours: "pg": "^8.11.0"
  Theirs: "pg": "^8.12.0"

Git Status:
  Unmerged paths:
    both modified:   src/auth/login.ts
    both modified:   package.json

  Changes not staged:
    modified:   tests/auth/login.test.ts

Automatic Recovery Actions:
  ⟳ Analyzing conflicts...
  ✓ Conflicts are resolvable
  ✗ Auto-merge skipped (requires manual review)

Manual Recovery Options:

  Option 1: Resolve in Debug Session
  ───────────────────────────────────────
  In current or new session:
    sandbox$ git status
    sandbox$ vim src/auth/login.ts
    [Resolve conflict markers]
    sandbox$ git add src/auth/login.ts
    sandbox$ vim package.json
    [Resolve conflict markers]
    sandbox$ git add package.json
    sandbox$ git commit -m "Resolve merge conflicts"

  Option 2: Use Merge Tool
  ───────────────────────────────────────
    sandbox$ git mergetool

  If vimdiff available:
    [Visual merge interface]

  Option 3: Abort and Restart
  ───────────────────────────────────────
    sandbox$ git merge --abort
    sandbox$ git pull --rebase origin main

  Try rebase instead of merge.

  Option 4: View Conflict Details
  ───────────────────────────────────────
    sandbox$ git diff --name-only --diff-filter=U
    sandbox$ git show :1:src/auth/login.ts  # common ancestor
    sandbox$ git show :2:src/auth/login.ts  # ours
    sandbox$ git show :3:src/auth/login.ts  # theirs

Conflict Resolution Helper:
  For src/auth/login.ts:
    Both versions use parameterized queries
    Difference is in error handling approach
    Recommendation: Keep 'ours' (more robust)

  For package.json:
    Version bump: pg 8.11.0 → 8.12.0
    Recommendation: Use newer version (theirs)

Recommendation: Option 1 with helper guidance above
```

## Use Cases

### Use Case 1: Debugging Test Failures
**Scenario**: Tests fail in CI but pass locally; need to debug in clean environment

**Workflow**:
```
/sandbox-debug #42
sandbox$ npm test -- src/auth/login.test.ts
[Reproduce failure]
sandbox$ npm test -- src/auth/login.test.ts --verbose
[Get detailed output]
sandbox$ cat src/auth/login.ts | grep -A10 "problematic-function"
[Identify issue]
sandbox$ vim src/auth/login.ts
[Fix code]
sandbox$ npm test -- src/auth/login.test.ts
[Verify fix]
sandbox$ exit
```

### Use Case 2: Exploring Dependencies
**Scenario**: Need to understand third-party library behavior

**Workflow**:
```
/sandbox-debug #42
sandbox$ npm list lodash
[Check version]
sandbox$ node
> const _ = require('lodash')
> _.chunk([1,2,3,4,5], 2)
[Experiment with library]
> .exit
sandbox$ cat node_modules/lodash/package.json
[Check metadata]
sandbox$ exit
```

### Use Case 3: Performance Investigation
**Scenario**: Function is slow; need to profile and optimize

**Workflow**:
```
/sandbox-debug #42
sandbox$ npm install --save-dev clinic
sandbox$ clinic doctor -- node src/server.js
[Profile application]
^C
sandbox$ cat .clinic/doctor.html
[Review results]
sandbox$ vim src/slow-function.ts
[Optimize based on profiling]
sandbox$ clinic doctor -- node src/server.js
[Verify improvement]
sandbox$ exit
```

### Use Case 4: Interactive Debugging
**Scenario**: Complex bug requires step-by-step inspection

**Workflow**:
```
/sandbox-debug #42
sandbox$ node inspect src/app.js
< Debugger listening on ws://...
< For help, see: https://nodejs.org/en/docs/inspector
break in src/app.js:1
> 1 const express = require('express');
  2 const app = express();
debug> sb(42)
[Set breakpoint at line 42]
debug> c
[Continue to breakpoint]
debug> repl
[Interactive REPL at breakpoint]
sandbox$ exit
```

### Use Case 5: Database Debugging
**Scenario**: SQL query returns unexpected results

**Workflow**:
```
/sandbox-debug #42 --env DATABASE_URL=postgresql://localhost/test
sandbox$ psql $DATABASE_URL
psql> SELECT * FROM users WHERE email = 'test@example.com';
[Inspect data]
psql> EXPLAIN ANALYZE SELECT * FROM users WHERE email = 'test@example.com';
[Check query plan]
psql> \q
sandbox$ vim src/db/queries.ts
[Fix query]
sandbox$ npm test -- src/db/queries.test.ts
[Verify fix]
sandbox$ exit
```

## Integration

### Integration with Bumba Sandbox
- Uses Bumba Sandbox interactive terminal API
- Maintains persistent connection to sandbox
- Full access to sandbox filesystem
- Changes persist until sandbox destroyed
- Session state preserved during connection

### Integration with Git
- Full git command access
- Can commit, branch, merge in sandbox
- View diffs and history
- Changes stay in sandbox until synced
- Git hooks execute in sandbox environment

### Integration with Package Managers
- npm, yarn, pnpm for Node.js
- pip, poetry for Python
- cargo for Rust
- go modules for Go
- All package manager commands available

### Integration with Test Frameworks
- Jest, Mocha, Vitest for JavaScript
- pytest for Python
- cargo test for Rust
- go test for Go
- Can run tests interactively with full output

### Integration with Debugging Tools
- Node.js inspector (--inspect)
- Python debugger (pdb, ipdb)
- GDB for C/C++
- Delve for Go
- LLDB for native code
- Browser DevTools for Node.js

### Integration with Sync Commands
- `/sync-sandbox-code #42`: Bring changes back to worktree
- Changes made in debug session preserved
- Can sync at any time
- Selective file syncing available

## Session Management

### Session Logging
All debug sessions automatically logged to:
```
.claude/debug-sessions/<sandbox-id>_<timestamp>.log
```

Log includes:
- All commands executed
- Command output
- Timestamps
- File modifications
- Session duration

### Session Recovery
If session disconnects unexpectedly:
- Sandbox state preserved
- Can reconnect with `/sandbox-debug <sandbox-id>`
- Previous changes still available
- Working directory preserved

### Session Timeout Handling
Default timeout: 60 minutes
- Warning at 55 minutes
- Auto-save session state
- Can extend with `--timeout` parameter
- Maximum timeout: 240 minutes (4 hours)

## Security Considerations

### Sandbox Isolation
- Debug session isolated to specific sandbox
- No access to other sandboxes
- No access to host system
- Network access controlled by E2B

### Credential Safety
- Never commit credentials in debug session
- Use environment variables for secrets
- Review changes before syncing to worktree
- Session logs may contain sensitive data

### Code Review
- All changes made in sandbox should be reviewed
- Use `/sync-sandbox-code` to bring changes to worktree
- Run tests before merging
- Security-sensitive changes require extra scrutiny

## Performance Considerations

### Resource Usage
- Debug sessions use sandbox CPU/memory
- Long-running commands may exhaust resources
- Monitor with `top`, `htop` in session
- Kill runaway processes if needed

### Network Performance
- Interactive shell has network latency
- Large file operations may be slow
- Consider using `/sandbox-exec` for non-interactive tasks
- Terminal responsiveness depends on connection quality

### Optimization Tips
- Use command history (↑/↓ arrows) for repeated commands
- Leverage shell aliases for common operations
- Use tab completion to reduce typing
- Keep sessions focused and time-limited

## Tips and Tricks

### Efficient Navigation
```bash
# Use z or autojump for quick directory navigation
sandbox$ cd src/auth
sandbox$ cd ../../tests
sandbox$ cd -  # Return to previous directory
```

### Command History
```bash
# Search command history
sandbox$ Ctrl+R
(reverse-i-search): npm test

# Re-run previous command
sandbox$ !!

# Re-run command by number
sandbox$ !42
```

### Multiple Commands
```bash
# Chain commands
sandbox$ npm test && npm run build && npm run deploy

# Run in background
sandbox$ npm start &
sandbox$ npm test
sandbox$ fg  # Bring back to foreground
```

### Output Inspection
```bash
# Less for large output
sandbox$ npm test | less

# Grep for specific lines
sandbox$ npm test 2>&1 | grep -A5 "FAIL"

# Save output to file
sandbox$ npm test > test-results.txt 2>&1
```

### File Editing
```bash
# Quick edits with sed
sandbox$ sed -i 's/old/new/g' src/file.ts

# Multiple file edits
sandbox$ find src -name "*.ts" -exec sed -i 's/old/new/g' {} \;

# Backup before editing
sandbox$ cp src/important.ts src/important.ts.bak
sandbox$ vim src/important.ts
```

### Process Management
```bash
# See all processes
sandbox$ ps aux

# Kill by name
sandbox$ pkill -f "node server"

# Monitor resources
sandbox$ top -d 1  # Update every second
```

## Notes

- **Interactive Shell**: Full terminal access with bidirectional communication
- **Persistent State**: Changes persist in sandbox until destroyed
- **Git Integration**: Full git access for version control operations
- **Tool Access**: All sandbox tools and commands available
- **Session Logs**: Automatically saved for audit and recovery
- **Timeout Management**: Configurable timeout with warnings
- **Shell Selection**: Choose bash, zsh, sh, or fish
- **Environment Customization**: Set env vars per session
- **Sync to Worktree**: Use `/sync-sandbox-code` to bring changes back
- **Resource Monitoring**: Use standard Unix tools (top, df, etc.)
- **Security**: Sandbox isolated, but review changes before syncing
- **Performance**: Network latency affects responsiveness
- **Best for**: Interactive debugging, exploration, live fixes
- **Not for**: Long-running tasks (use `/sandbox-exec` instead)

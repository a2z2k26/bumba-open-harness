---
name: hotfix-branch
description: Fast-track critical bug fix (Implementation stage)
---

# /emergency-hotfix Command

Fast-track critical bug fixes and security patches with expedited workflow that bypasses normal development processes while maintaining safety guardrails. Automatically creates hotfix branch, implements fix in isolated sandbox, runs critical tests, and creates emergency pull request with appropriate urgency labels.

## Usage

```
/emergency-hotfix <description> [options]
```

## Parameters

- `<description>` (required): Brief description of the critical issue to fix
- `--severity <level>` (optional): Severity level (critical, high, medium) - default: critical
- `--issue <number>` (optional): Related GitHub issue number
- `--base-branch <branch>` (optional): Base branch for hotfix - default: main
- `--skip-tests <tests>` (optional): Skip non-critical tests (e.g., "e2e,integration") - default: none
- `--auto-merge` (optional): Auto-merge if all checks pass - default: false
- `--notify <channels>` (optional): Notification channels (slack, email, pagerduty) - default: slack
- `--rollback-plan` (optional): Automatic rollback if deployment fails - default: true

## Workflow

### Step 1: Emergency Assessment

```
🚨 Emergency Hotfix Workflow
═══════════════════════════════════════════════

Assessing emergency...
  Issue: Production API returning 500 errors
  Severity: Critical
  Impact: 100% of users affected
  Started: 2025-01-18T14:35:00Z

Validation:
  ✓ Severity: critical (expedited workflow approved)
  ✓ Base branch: main (production)
  ✓ Repository: Clean state
  ✓ CI/CD: Operational

Emergency Classification:
  Type: Production Outage
  Priority: P0 (Immediate)
  SLA: 30 minutes to resolution

Affected Systems:
  • Production API (api.example.com)
  • User authentication endpoints
  • Database connection pool

Impact Analysis:
  Users Affected: ~10,000 active users
  Revenue Impact: $500/minute downtime
  Support Tickets: 47 (last 10 minutes)

───────────────────────────────────────────────
```

### Step 2: Hotfix Branch Creation

```
Creating emergency hotfix branch...

Git Operations:
  ✓ Fetching latest from main
  ✓ Checking out main branch
  ✓ Pulling latest changes

Branch Creation:
  Base: main (commit abc123def)
  Hotfix Branch: hotfix/prod-api-500-errors
  Convention: hotfix/<description>

  ✓ Branch created: hotfix/prod-api-500-errors
  ✓ Pushed to remote
  ✓ Branch protection: Bypassed (emergency)

Notification Sent:
  📢 Slack: #incidents
  Message: "🚨 Emergency hotfix started: Production API 500 errors
            Branch: hotfix/prod-api-500-errors
            ETA: 30 minutes"

───────────────────────────────────────────────
```

### Step 3: Isolated Sandbox Provisioning

```
Provisioning emergency hotfix sandbox...

Sandbox Configuration:
  Template: Production mirror (exact production environment)
  Resources: Priority allocation (4 vCPU, 16 GB RAM)
  Priority: Emergency (preempts other sandboxes if needed)

Provisioning:
  ⟳ Creating sandbox...
  ✓ Sandbox: sbx_hotfix_emergency_xyz
  ✓ Production configuration cloned
  ✓ Environment variables loaded
  ✓ Database snapshot restored (latest)

Repository Setup:
  ✓ Repository cloned
  ✓ Hotfix branch checked out
  ✓ Dependencies installed (npm ci)
  ✓ Build completed (production mode)

Database State:
  ✓ Production data snapshot (anonymized)
  ✓ Schema version: v2.45.3 (latest production)
  ✓ Test data seeded

Environment Verification:
  ✓ Node.js: v18.17.0 (matches production)
  ✓ PostgreSQL: v14.8 (matches production)
  ✓ Redis: v7.0.12 (matches production)
  ✓ All dependencies match production

Ready for debugging in 42 seconds

───────────────────────────────────────────────
```

### Step 4: Interactive Debugging Session

```
Starting interactive debugging session...

Issue Reproduction:
  ⟳ Attempting to reproduce error...

  Request: GET /api/v1/users/profile
  Expected: 200 OK
  Actual: 500 Internal Server Error

  ✓ Error reproduced successfully

Error Analysis:
  Stack Trace:
    TypeError: Cannot read property 'id' of undefined
    at UserController.getProfile (controllers/user.js:42)
    at Layer.handle (express/lib/router/layer.js:95)
    at next (express/lib/router/route.js:144)

  Root Cause:
    Database connection pool exhausted
    → Connection not released after query
    → Subsequent requests fail

  Affected Code:
    File: src/controllers/user.js
    Line: 42
    Issue: Missing connection.release() in finally block

Suggested Fix:
  ```javascript
  // BEFORE (buggy)
  async getProfile(req, res) {
    const connection = await pool.getConnection();
    try {
      const user = await connection.query('SELECT * FROM users WHERE id = ?', [req.user.id]);
      res.json(user);
    } catch (error) {
      res.status(500).json({ error: error.message });
    }
    // ❌ Connection never released if error occurs
  }

  // AFTER (fixed)
  async getProfile(req, res) {
    const connection = await pool.getConnection();
    try {
      const user = await connection.query('SELECT * FROM users WHERE id = ?', [req.user.id]);
      res.json(user);
    } catch (error) {
      res.status(500).json({ error: error.message });
    } finally {
      connection.release(); // ✓ Always release connection
    }
  }
  ```

Apply fix? (yes/no): yes

Applying fix...
  ✓ File updated: src/controllers/user.js
  ✓ Fix applied at line 42

───────────────────────────────────────────────
```

### Step 5: Emergency Testing

```
Running critical tests...

Test Strategy:
  ⚠️ Emergency mode: Focus on critical tests only
  Skipped: E2E tests (20 minutes)
  Skipped: Full integration suite (15 minutes)
  Running: Critical API tests (3 minutes)

Unit Tests (Critical Only):
  ⟳ Running user controller tests...
  ✓ UserController.getProfile() - Success (PASS)
  ✓ UserController.getProfile() - Error handling (PASS)
  ✓ UserController.getProfile() - Connection release (PASS)

  Tests: 3 passed, 0 failed
  Duration: 1.2 seconds

Integration Tests (Critical API Endpoints):
  ⟳ Testing affected endpoints...
  ✓ GET /api/v1/users/profile (200 OK)
  ✓ GET /api/v1/users/profile (with error) (500 → 500, connection released)
  ✓ Connection pool health (no exhaustion)
  ✓ Concurrent requests (10 parallel) (all 200 OK)

  Tests: 4 passed, 0 failed
  Duration: 2.8 seconds

Smoke Tests (Production Scenarios):
  ⟳ Simulating production load...
  ✓ 100 concurrent requests (all successful)
  ✓ Connection pool: 100% healthy
  ✓ No memory leaks detected
  ✓ Response times: avg 45ms (baseline: 42ms)

  Tests: 4 passed, 0 failed
  Duration: 3.5 seconds

✅ All Critical Tests Passed
Total Duration: 7.5 seconds

Skipped (Non-Critical):
  ⚠️ E2E tests (20 minutes) - Run after deployment
  ⚠️ Full integration suite (15 minutes) - Run after deployment
  ⚠️ Performance benchmarks (10 minutes) - Run after deployment

───────────────────────────────────────────────
```

### Step 6: Emergency Pull Request Creation

```
Creating emergency pull request...

Commit:
  ✓ Staged changes: src/controllers/user.js
  ✓ Commit message:
    "🚨 HOTFIX: Fix connection pool exhaustion in user profile endpoint

     Root Cause:
     - Database connections not released on error
     - Connection pool exhausted after ~20 errors
     - All subsequent requests fail with 500 errors

     Fix:
     - Add finally block to always release connection
     - Ensures connection cleanup even on error path

     Impact:
     - Fixes production API 500 errors
     - Restores service for 10,000 users
     - Revenue impact: $500/min

     Testing:
     - ✓ Unit tests: 3/3 passed
     - ✓ Integration tests: 4/4 passed
     - ✓ Smoke tests: 4/4 passed
     - ⚠️ E2E tests: Skipped (emergency)

     Deployment:
     - Target: Production (main branch)
     - Rollback plan: Revert commit + redeploy
     - Estimated downtime: 0 (zero-downtime deployment)

     🤖 Generated with Claude Code (Emergency Hotfix)"

  ✓ Committed to hotfix/prod-api-500-errors
  ✓ Pushed to remote

Pull Request:
  Creating emergency PR...

  Title: 🚨 HOTFIX: Fix production API 500 errors (connection pool exhaustion)

  Labels:
    • hotfix
    • critical
    • production
    • bug
    • security (if applicable)

  Reviewers:
    • @on-call-engineer (required)
    • @tech-lead (optional, notify only)

  Checks:
    ✓ CI: Running (3 minutes estimated)
    ⚠️ Code review: Expedited (1 reviewer required)
    ⚠️ QA approval: Skipped (emergency)

  ✓ PR created: #247
  URL: https://github.com/user/repo/pull/247

Notifications:
  📢 Slack: #incidents
    "🚨 Emergency PR ready for review
     PR: #247
     Issue: Production API 500 errors
     Fix: Connection pool cleanup
     Tests: ✓ Passed
     Reviewer: @on-call-engineer
     Merge ETA: 5-10 minutes"

  📧 Email: incidents@example.com
  📟 PagerDuty: On-call engineer notified

───────────────────────────────────────────────
```

### Step 7: Deployment Preparation

```
Preparing emergency deployment...

Rollback Plan:
  ✓ Current production commit: abc123def456
  ✓ Rollback commit prepared
  ✓ Rollback script: scripts/rollback.sh
  ✓ Estimated rollback time: <2 minutes

Deployment Checklist:
  ✓ All critical tests passed
  ✓ PR created and labeled
  ✓ Reviewers notified
  ✓ Rollback plan ready
  ✓ Monitoring alerts configured
  ⚠️ Code review pending

Waiting for approval...
  ⏳ PR #247: Pending review
  Reviewer: @on-call-engineer
  Auto-merge: Disabled (requires manual approval)

Monitor PR status:
  /pr-status 247

Auto-deploy when approved:
  /deploy-hotfix 247 --auto-rollback

───────────────────────────────────────────────
```

### Step 8: Post-Deployment Verification

```
✅ Emergency Hotfix Deployed
═══════════════════════════════════════════════

Deployment Details:
  PR: #247
  Branch: hotfix/prod-api-500-errors
  Commit: def789ghi012
  Deployed: 2025-01-18T15:05:00Z
  Duration: 30 minutes (from incident start)

Fix Verification:
  ⟳ Running production smoke tests...

  API Health:
    ✓ GET /api/v1/users/profile: 200 OK
    ✓ Connection pool: Healthy (0% exhaustion)
    ✓ Error rate: 0% (was 100%)
    ✓ Response time: 42ms avg (normal)

  User Impact:
    ✓ All users restored
    ✓ Support tickets: Stopped (47 → 0 new)
    ✓ Revenue: Restored ($500/min saved)

Monitoring (First 15 minutes):
  ✓ Error rate: 0% (target: <0.1%)
  ✓ Response time: 42ms avg (target: <100ms)
  ✓ Connection pool: 15% usage (healthy)
  ✓ Memory: Stable (no leaks)
  ✓ CPU: 25% (normal)

Incident Resolution:
  Started: 14:35:00Z
  Resolved: 15:05:00Z
  Total Duration: 30 minutes ✓ (SLA: 30 min)

Post-Mortem:
  ✓ Incident logged: INC-2025-01-18-001
  ✓ Root cause: Connection pool exhaustion
  ✓ Resolution: Added finally block for cleanup
  ⏳ Post-mortem meeting: Scheduled (2025-01-19T10:00:00Z)

Follow-Up Actions:
  1. Run full test suite (E2E, integration)
     /run-full-tests

  2. Merge hotfix to develop branch
     /merge-hotfix hotfix/prod-api-500-errors develop

  3. Write post-mortem document
     /create-postmortem INC-2025-01-18-001

  4. Add monitoring for connection pool exhaustion
     /add-monitoring "connection_pool_usage" --alert-threshold 80%

───────────────────────────────────────────────
```

## Examples

### Example 1: Critical Production Bug

```
/emergency-hotfix "Production API returning 500 errors" --severity critical
```

**Output**:
```
🚨 Emergency Hotfix

Issue: Production API 500 errors
Severity: Critical
Impact: 100% of users

⟳ Creating hotfix branch...
✓ Branch: hotfix/prod-api-500-errors

⟳ Provisioning sandbox...
✓ Sandbox: sbx_hotfix_emergency_xyz

⟳ Reproducing error...
✓ Error reproduced

Root Cause: Connection pool exhaustion
Fix: Add finally block for cleanup

⟳ Running critical tests...
✓ All tests passed (7.5s)

⟳ Creating PR...
✓ PR #247 created

Waiting for review...
ETA: 30 minutes total
```

### Example 2: Security Vulnerability

```
/emergency-hotfix "SQL injection vulnerability in search endpoint" --severity critical --issue 123
```

**Output**:
```
🚨 Security Hotfix

Issue: #123 - SQL injection in search
Severity: Critical (Security)
Impact: Data breach risk

🔒 Security Mode: Enabled
  • Anonymized logs
  • Restricted access
  • Security team notified

⟳ Creating hotfix branch...
✓ Branch: hotfix/security-sql-injection

⟳ Provisioning sandbox...
✓ Sandbox: sbx_hotfix_security_xyz

Root Cause: Unsanitized user input
Fix: Use parameterized queries

⟳ Security tests...
✓ SQL injection attempts blocked
✓ All tests passed

⟳ Creating PR...
✓ PR #248 (security-sensitive)

Security Review Required:
  Reviewer: @security-team
  ETA: 15 minutes

⚠️ Do not discuss publicly until patched
```

### Example 3: Performance Degradation

```
/emergency-hotfix "API response time 10x slower" --severity high
```

**Output**:
```
🚨 Performance Hotfix

Issue: API response time degradation
Severity: High
Impact: 50% performance drop

⟳ Creating hotfix branch...
✓ Branch: hotfix/perf-slow-api

⟳ Profiling...
Root Cause: N+1 query in recent code change
Fix: Add eager loading

⟳ Performance tests...
Before: 450ms avg
After: 42ms avg (-90%)
✓ Performance restored

⟳ Creating PR...
✓ PR #249 created

ETA: 20 minutes
```

### Example 4: Data Corruption Hotfix

```
/emergency-hotfix "User data corruption in profile update" --severity critical --auto-merge=false
```

**Output**:
```
🚨 Data Integrity Hotfix

Issue: User profile data corruption
Severity: Critical
Impact: Data loss risk

⚠️ Data Integrity Issue Detected
  Additional safeguards applied:
  • Database backup before deploy
  • Manual merge required (no auto-merge)
  • Data validation tests required

⟳ Creating hotfix branch...
✓ Branch: hotfix/data-corruption-profile

Root Cause: Missing validation on update
Fix: Add input validation + data migration

⟳ Tests...
✓ Validation working
✓ No data loss
✓ Migration script ready

⟳ Creating PR...
✓ PR #250 created

Manual Review Required:
  • Database backup: ✓ Complete
  • Data migration: ✓ Tested
  • Rollback plan: ✓ Ready

Requires: DBA approval + manual merge
```

### Example 5: Rollback Previous Hotfix

```
/emergency-hotfix "Rollback hotfix #247 - causing new issues" --severity high --rollback-plan
```

**Output**:
```
🚨 Emergency Rollback

Issue: Hotfix #247 causing new problems
Severity: High
Action: Rollback to previous version

⟳ Preparing rollback...
Previous Commit: abc123def456
Rollback Commit: ghi789jkl012

⟳ Creating rollback PR...
✓ PR #251 (revert #247)

Rollback Safety:
  ✓ Database compatible
  ✓ No data loss risk
  ✓ Config compatible

⟳ Fast-track approval...
✓ Approved (emergency rollback)

⟳ Deploying rollback...
✓ Rolled back to abc123def456

✅ Rollback Complete
Previous hotfix reverted
Service restored to stable state

Post-Rollback:
  • Investigate root cause of new issues
  • Fix original issue + new issues
  • Redeploy with comprehensive testing
```

### Example 6: Bypass Tests (Extreme Emergency)

```
/emergency-hotfix "Critical security patch" --severity critical --skip-tests all --notify "slack,email,pagerduty"
```

**Output**:
```
🚨 EXTREME EMERGENCY MODE

Issue: Critical security patch
Severity: Critical
Mode: Bypass all tests (DANGEROUS)

⚠️ WARNING: Skipping all tests
This is EXTREMELY RISKY and should only be used
for critical security patches where delay is unacceptable.

Confirmation Required:
  Type "EMERGENCY" to proceed: EMERGENCY

⟳ Creating hotfix branch...
✓ Branch: hotfix/critical-security-patch

⟳ Applying patch...
✓ Patch applied

⚠️ TESTS SKIPPED (emergency override)

⟳ Creating PR...
✓ PR #252 (EMERGENCY - TESTS SKIPPED)

⚠️ Manual Verification Required:
  • No automated testing performed
  • Manual smoke test REQUIRED before merge
  • Increased rollback risk

Notifications:
  📢 Slack: All channels
  📧 Email: All engineers
  📟 PagerDuty: All on-call

Proceed with extreme caution.
```

## Error Handling

### Error 1: Not an Emergency

```
❌ Error: Issue does not qualify as emergency

Description: "Add new feature to dashboard"
Severity: Medium
Assessment: Not emergency-worthy

Emergency criteria NOT met:
  ✗ No production outage
  ✗ No security vulnerability
  ✗ No data loss risk
  ✗ No critical bug affecting users

This appears to be a normal feature request.

Use Regular Workflow:
  /parallel-implement-features --issue <number>

Emergency Hotfix Reserved For:
  • Production outages (P0/P1)
  • Critical security vulnerabilities
  • Data corruption/loss
  • Severe performance degradation
  • Compliance violations

If you believe this IS an emergency:
  /emergency-hotfix "description" --severity critical --override
```

### Error 2: Hotfix Already in Progress

```
❌ Error: Emergency hotfix already in progress

Current Hotfix:
  Branch: hotfix/prod-api-500-errors
  Issue: Production API errors
  Started: 14:35:00Z (15 minutes ago)
  Status: PR under review (#247)
  ETA: 15 minutes

Cannot start multiple emergency hotfixes simultaneously.

Recovery Options:

  Option 1: Wait for Current Hotfix
  ───────────────────────────────────────
    Monitor: /pr-status 247
    ETA: 15 minutes

  Option 2: Escalate Priority
  ───────────────────────────────────────
    If your issue is MORE critical:
    /escalate-hotfix "new issue description"

    Pauses current hotfix, starts new one

  Option 3: Work on Current Hotfix
  ───────────────────────────────────────
    Collaborate on existing hotfix:
    /join-hotfix hotfix/prod-api-500-errors

Recommendation: Option 1 unless your issue is more critical
```

### Error 3: CI/CD System Down

```
❌ Error: CI/CD system unavailable

Status: Jenkins/GitHub Actions down
Reason: Cannot run automated tests

Emergency hotfix requires CI/CD for safety.

Recovery Options:

  Option 1: Wait for CI/CD Restore
  ───────────────────────────────────────
    Status: https://status.github.com
    ETA: Unknown

  Option 2: Manual Testing (RISKY)
  ───────────────────────────────────────
    /emergency-hotfix "issue" --manual-testing

    ⚠️ Requires manual test verification
    ⚠️ Higher risk of introducing bugs

  Option 3: Rollback + Wait
  ───────────────────────────────────────
    If production is down:
      1. Rollback to last known good version
      2. Wait for CI/CD restoration
      3. Deploy proper hotfix

Recommendation: Option 3 for production outages
                Option 1 for non-outage emergencies
```

### Error 4: Insufficient Permissions

```
❌ Error: Insufficient permissions for emergency hotfix

User: @developer
Required: @senior-engineer or @on-call

Emergency hotfixes require elevated permissions.

Your Permissions:
  ✓ Create branches
  ✗ Bypass branch protection
  ✗ Force push to main
  ✗ Emergency deploy

Recovery Options:

  Option 1: Contact On-Call Engineer
  ───────────────────────────────────────
    Slack: #incidents
    PagerDuty: Trigger alert
    Phone: Check on-call rotation

  Option 2: Request Permission Elevation
  ───────────────────────────────────────
    /request-emergency-access "reason"

    Temporary permission elevation
    Requires approval from @tech-lead

  Option 3: Create Regular PR
  ───────────────────────────────────────
    /create-pr "fix description"

    Uses normal workflow (slower)

Recommendation: Option 1 for true emergencies
```

### Error 5: Sandbox Provisioning Failed

```
❌ Error: Emergency sandbox provisioning failed

Reason: Resource capacity exceeded
Available: 0 emergency sandboxes
Capacity: 2/2 in use

Cannot provision sandbox for hotfix.

Recovery Options:

  Option 1: Terminate Non-Critical Sandboxes
  ───────────────────────────────────────
    /list-sandboxes --active
    /terminate-sandbox <non-critical_id>

    Frees capacity for emergency

  Option 2: Use Existing Sandbox
  ───────────────────────────────────────
    /emergency-hotfix "issue" --sandbox <existing_id>

    Reuses existing sandbox (risky)
    ⚠️ May have conflicting state

  Option 3: Local Development (RISKY)
  ───────────────────────────────────────
    /emergency-hotfix "issue" --local

    ⚠️ No isolated environment
    ⚠️ Higher risk

Recommendation: Option 1 to ensure isolated environment
```

## Integration

### Integration with Git Workflow
- Creates hotfix branch from main/production
- Bypasses normal branch protection
- Follows gitflow hotfix conventions
- Enables fast-track merging

### Integration with CI/CD
- Triggers emergency CI pipeline
- Runs critical tests only
- Bypasses optional checks
- Enables zero-downtime deployment

### Integration with Sandbox System
- Provisions priority sandbox
- Mirrors production environment
- Enables isolated debugging
- Supports rapid iteration

### Integration with Monitoring
- Tracks hotfix progress
- Monitors deployment health
- Alerts on issues
- Enables rollback triggers

### Integration with Incident Management
- Logs incident timeline
- Notifies stakeholders
- Tracks SLA compliance
- Enables post-mortem analysis

## Use Cases

### Use Case 1: Production API Outage
**Scenario**: Production API returning 500 errors, all users affected.

**Command**:
```bash
/emergency-hotfix "Production API 500 errors" --severity critical
```

**Result**: Hotfix deployed in 30 minutes, service restored.

### Use Case 2: Security Vulnerability
**Scenario**: SQL injection discovered in production.

**Command**:
```bash
/emergency-hotfix "SQL injection in search" --severity critical
```

**Result**: Security patch deployed within 15 minutes.

### Use Case 3: Data Corruption
**Scenario**: Bug causing user data corruption.

**Command**:
```bash
/emergency-hotfix "User data corruption" --severity critical --auto-merge=false
```

**Result**: Fix deployed with manual approval, data integrity verified.

### Use Case 4: Performance Degradation
**Scenario**: API response time 10x slower after deploy.

**Command**:
```bash
/emergency-hotfix "Performance degradation" --severity high
```

**Result**: Performance issue fixed, response times restored.

### Use Case 5: Rollback Bad Hotfix
**Scenario**: Previous hotfix causing new issues.

**Command**:
```bash
/emergency-hotfix "Rollback hotfix #247" --rollback-plan
```

**Result**: Reverted to stable state within 10 minutes.

## Performance Considerations

### Hotfix Speed
- Assessment: <1 minute
- Branch creation: <30 seconds
- Sandbox provisioning: 1-2 minutes
- Debugging: Variable (5-20 minutes)
- Testing: 5-10 minutes
- PR creation: <1 minute
- Deployment: 2-5 minutes
- **Total: 15-30 minutes typical**

### Resource Priority
- Emergency sandboxes: Highest priority
- Can preempt non-critical workloads
- Dedicated resource pool (if configured)

### Automation Benefits
- Manual process: 60-120 minutes
- Automated (this tool): 15-30 minutes
- **Time savings: 70-80%**

## Notes

- **Emergency Only**: Reserved for production-critical issues
- **Fast-Track**: Bypasses normal development processes
- **Safety Guardrails**: Critical tests still required
- **Isolated Environment**: Dedicated emergency sandbox
- **Rollback Ready**: Automatic rollback on failure
- **Notification**: Stakeholders automatically notified
- **Audit Trail**: Complete incident timeline logged
- **Post-Mortem**: Automated post-mortem creation
- **SLA Tracking**: Monitors resolution time
- **Security Aware**: Special handling for security issues
- **Permission Gated**: Requires elevated permissions
- **Manual Override**: Can bypass tests in extreme cases (dangerous)

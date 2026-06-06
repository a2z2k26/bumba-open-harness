---
name: optimize
description: Analyze and optimize sandbox allocation
---

# /optimize-sandboxes Command

Analyzes current sandbox allocation and provides optimization recommendations to reduce costs and improve resource utilization.

## Usage

```
/optimize-sandboxes [--apply] [--aggressive]
```

## Parameters

- `--apply` (optional): Automatically apply recommended optimizations
- `--aggressive` (optional): More aggressive optimization (higher savings, more risk)
- `--dry-run` (optional): Preview optimizations without applying

## Workflow

```
🔍 Analyzing Sandbox Allocation
═══════════════════════════════════════════════

Calling optimize_resources MCP tool...

Current State:
  Active Sandboxes: 5
  Idle Sandboxes: 2
  Total Cost/Hour: $0.14
  Monthly Projection: $100.80

Analysis complete.

───────────────────────────────────────────────

💡 Optimization Opportunities
═══════════════════════════════════════════════

IMMEDIATE SAVINGS (High Impact):

1. Terminate Idle Sandboxes
   Sandboxes: sbx_abc123 (idle 2h), sbx_def456 (idle 3h)
   Current Cost: $0.04/hour
   Potential Savings: $28.80/month
   Risk: Low (no active work)
   Action: Destroy idle sandboxes

2. Consolidate Similar Features
   Issues: #45, #47 (both frontend work)
   Current: 2 sandboxes
   Recommendation: Use 1 sandbox
   Savings: $14.40/month
   Risk: Medium (requires coordination)
   Action: Combine work in single sandbox

3. Convert to Local Mode
   Issues: #48 (documentation)
   Current: Sandbox
   Recommendation: Local worktree
   Savings: $14.40/month
   Risk: Low (no environment requirements)
   Action: Migrate to local mode

MEDIUM SAVINGS (Moderate Impact):

4. Use Existing Templates
   Sandboxes: 3 without templates
   Template Available: node-typescript
   Time Saved: ~6 minutes/sandbox
   Cost Impact: Minimal
   Action: Configure default template

5. Reduce Concurrent Limit
   Current: max 10 concurrent
   Actual Peak: 5 concurrent
   Recommendation: max 7 concurrent
   Savings: Prevents overallocation
   Risk: Low
   Action: Update config

LONG-TERM OPTIMIZATIONS:

6. Implement Auto-Cleanup
   Current: Manual cleanup
   Recommendation: Auto-cleanup after 1h idle
   Savings: $43.20/month
   Risk: Low (with proper thresholds)
   Action: Enable auto-cleanup

7. Strategy Adjustment
   Current: 60% balanced, 40% max-speed
   Recommendation: 80% balanced, 20% max-speed
   Savings: $8.64/month
   Risk: Low (minimal time impact)
   Action: Update default strategy

───────────────────────────────────────────────

💰 Total Potential Savings
═══════════════════════════════════════════════

Immediate Actions:
  Monthly Savings: $57.60 (57% reduction)
  Implementation Time: < 5 minutes

Medium-Term Actions:
  Additional Savings: $8.64 (9% reduction)
  Implementation Time: 10-15 minutes

Total Potential Savings: $66.24/month (66% reduction)

Current: $100.80/month
Optimized: $34.56/month
Savings: $66.24/month

───────────────────────────────────────────────

📊 Optimization Plan
═══════════════════════════════════════════════

Phase 1 (Immediate):
  1. Run /cleanup-sandboxes (saves $28.80/month)
  2. Migrate #48 to local mode (saves $14.40/month)
  3. Configure default template (saves startup time)

Phase 2 (This Week):
  1. Enable auto-cleanup (saves $43.20/month)
  2. Adjust strategy defaults (saves $8.64/month)
  3. Reduce concurrent limit to 7

Phase 3 (Ongoing):
  1. Monitor sandbox usage weekly
  2. Review allocation strategy monthly
  3. Optimize templates as needed

───────────────────────────────────────────────

⚠️  Recommendations
═══════════════════════════════════════════════

Conservative Approach (Recommended):
  - Apply Phase 1 optimizations now
  - Implement Phase 2 over next week
  - Monitor for 2 weeks before adjusting further
  - Expected Savings: ~$50/month

Aggressive Approach (Higher Risk):
  - Apply all optimizations immediately
  - Set aggressive auto-cleanup (30m idle)
  - Force cost-optimized strategy
  - Expected Savings: ~$75/month
  - Risk: Possible workflow disruption

Balanced Approach:
  - Phase 1 + Phase 2 optimizations
  - Conservative auto-cleanup (2h idle)
  - Balanced strategy default
  - Expected Savings: ~$66/month
  - Risk: Minimal

───────────────────────────────────────────────

Apply Optimizations? (yes/no/customize)
```

## Examples

### Example 1: Analyze Only
```
/optimize-sandboxes
```

### Example 2: Apply Recommendations
```
/optimize-sandboxes --apply
```

### Example 3: Aggressive Optimization
```
/optimize-sandboxes --aggressive --apply
```

## Optimization Actions

When `--apply` is used:

1. **Destroys idle sandboxes**
2. **Updates configuration** (strategies, limits)
3. **Enables auto-cleanup** if recommended
4. **Migrates features** to local mode if applicable
5. **Configures templates** for faster startups

## Integration

- Uses `optimize_resources` MCP tool
- Updates `bumba-sandbox-config.json` automatically
- Works with `/cost-report` for tracking savings
- Complements `/cleanup-sandboxes`

## Error Handling

### Common Errors

**No Active Sandboxes**:
```
⚠️  Warning: No active sandboxes to optimize

Current State:
  Active Sandboxes: 0
  Idle Sandboxes: 0
  Total Cost/Hour: $0.00

Possible reasons:
  1. All features implemented in local mode
  2. All sandboxes already cleaned up
  3. No features currently in progress

Nothing to optimize.

To see overall efficiency:
  /cost-report --period month
```

**Optimize Resources Tool Unavailable**:
```
❌ Error: Cannot call optimize_resources MCP tool

MCP Error: Tool 'optimize_resources' not found

Cause: MCP server not running or tool not registered

Solutions:
  1. Check MCP server status
  2. Restart Claude Desktop
  3. Verify MCP configuration in claude_desktop_config.json
  4. Check MCP server logs

Manual optimization:
  1. List sandboxes: /sandbox-status
  2. Identify idle sandboxes
  3. Clean up manually: /cleanup-sandboxes

MCP server required for automatic optimization analysis.
```

**Sandbox API Error**:
```
❌ Error: Cannot fetch sandbox data

API Error: 503 Service Unavailable
Endpoint: https://sandbox-api.example.com/sandboxes

Cannot perform optimization without current sandbox data.

Troubleshooting:
  1. Check sandbox service status
  2. Verify SANDBOX_API_KEY: echo $SANDBOX_API_KEY
  3. Test API manually:
     curl -H "Authorization: Bearer $SANDBOX_API_KEY" \
          https://sandbox-api.example.com/sandboxes
  4. Retry in a few minutes

Partial optimization available from cached data (may be outdated).
Continue with cached data? (yes/no): _
```

**Apply Flag Without --yes Confirmation**:
```
⚠️  Warning: Optimizations will be applied automatically

You used --apply flag without reviewing recommendations.

Optimizations to apply:
  1. Terminate 2 idle sandboxes (saves $28.80/month)
  2. Update concurrent limit to 7 (from 10)
  3. Enable auto-cleanup with 2h threshold
  4. Set default strategy to balanced

Estimated impact:
  Monthly savings: $57.60
  Risk level: Low-Medium

This will:
  ✓ Destroy idle sandboxes
  ✓ Update e2b-config.json
  ✓ Cannot be easily undone

Confirm optimizations? (yes/no): _

Note: Use --yes flag to skip this confirmation (not recommended).
```

**Aggressive Mode Warning**:
```
⚠️  WARNING: Aggressive optimization mode

You selected --aggressive flag. This mode applies more aggressive
optimizations that may impact your workflow:

Aggressive actions:
  1. Force cost-optimized strategy (slower execution)
  2. Auto-cleanup after 30m idle (may kill active work)
  3. Reduce max concurrent to 5 (limits parallelism)
  4. Migrate ALL features to local mode where possible

Potential risks:
  ⚠️  Active work may be terminated
  ⚠️  Reduced development speed
  ⚠️  Less isolation (local mode)

Expected savings: ~$75/month (vs ~$50 conservative)

Risk-benefit assessment:
  Savings: +50% over conservative
  Workflow disruption: Medium-High

Recommended: Try conservative mode first, monitor for 1-2 weeks

Continue with aggressive mode? (yes/no): _
```

**Insufficient Permissions**:
```
❌ Error: Cannot update configuration

File: .claude/config/bumba-sandbox-config.json
Error: EACCES: permission denied

Optimizations identified but cannot be applied.

Optimizations found:
  ✓ Analysis complete
  ❌ Cannot update config file

Solutions:
  1. Fix permissions:
     chmod 644 .claude/config/bumba-sandbox-config.json

  2. Run with sudo (not recommended):
     sudo /optimize-sandboxes --apply

  3. Apply manually:
     /config set parallel.maxConcurrent 7
     /config set sandboxDefaults.cleanupDelay 7200
     /cleanup-sandboxes

View recommendations without applying:
  /optimize-sandboxes (without --apply flag)
```

**Sandbox Kill Failure**:
```
❌ Error: Cannot terminate idle sandbox

Sandbox ID: sbx_abc123xyz
E2B Error: 400 Bad Request - Sandbox has active processes

Optimizations partial:
  ✓ Config updated
  ✓ 1 sandbox terminated
  ❌ 1 sandbox failed to terminate

Failed sandbox:
  ID: sbx_abc123xyz
  Issue: #47
  Status: Active (has running process)
  Idle time: 2.5 hours

Cause: Sandbox has active background process preventing termination

Solutions:
  1. Connect to sandbox and stop processes:
     /sandbox-debug sbx_abc123xyz
     # Then kill processes manually

  2. Force kill (may lose unsaved work):
     e2b sandbox kill sbx_abc123xyz --force

  3. Wait for process to complete

Note: Sandbox with active processes is NOT considered idle.
Optimization will skip active sandboxes.
```

**Conflicting Configuration**:
```
❌ Error: Optimization conflicts with current configuration

Optimization: Set maxConcurrent to 7
Current config: User explicitly set maxConcurrent to 15

Detected: User preference overrides optimization

Conflict resolution:
  [1] Keep user setting (15 concurrent)
  [2] Apply optimization (7 concurrent, save $12/month)
  [3] Compromise (10 concurrent, save $6/month)
  [4] Cancel optimization

Select option (1-4): _

Note: Optimizations respect user preferences. Manual config changes
take precedence over automatic optimizations.
```

### Recovery Actions

**Automatic Recovery**:
- Validates all changes before applying
- Skips optimizations that would break system
- Preserves failed sandboxes for debugging
- Creates config backup before changes
- Provides rollback options

**Manual Recovery**:
```bash
# Undo config changes
cp .claude/config/bumba-sandbox-config.json.backup .claude/config/bumba-sandbox-config.json

# Or reset specific settings
/config reset parallel.maxConcurrent
/config reset sandboxDefaults.cleanupDelay

# Restore terminated sandboxes (if snapshot exists)
/sandbox-restore sbx_abc123xyz

# Review what changed
git diff .claude/config/bumba-sandbox-config.json
```

**Rollback Optimizations**:
```bash
# View optimization history
cat .claude/config/optimization-history.json

# Rollback last optimization
/rollback-optimization --last

# Or manually revert
/config set parallel.maxConcurrent 10
/config set costManagement.budgetLimit 100
/config set sandboxDefaults.autoCleanup false
```

## Integration

- Uses `optimize_resources` MCP tool
- Updates `bumba-sandbox-config.json` automatically
- Works with `/cost-report` for tracking savings
- Complements `/cleanup-sandboxes`

## Notes

- Run weekly for best results
- Conservative approach recommended initially
- Monitor savings with `/cost-report`
- Aggressive mode may impact workflow
- All changes are reversible via `/config`
- Creates config backup before applying changes
- Validates optimizations before applying
- Respects user preferences in configuration
- Provides detailed impact analysis before changes

---
name: cost-report
description: Generate cost breakdown report
---

# /cost-report Command

Generates comprehensive cost reports from hook logs with breakdowns by period, issue, sandbox, and cost optimization recommendations.

## Usage

```
/cost-report [--period <period>] [--format <table|json|csv>]
```

## Parameters

- `--period <period>` (optional): Reporting period (default: month)
  - `today`: Today's costs
  - `week`: Last 7 days
  - `month`: Current month
  - `all`: All time
  - `custom`: Custom date range (prompts for dates)
- `--format <format>` (optional): Output format (default: table)
- `--export <file>` (optional): Export to file

## Workflow

### Step 1: Load Cost Data from Hook Logs

```
📊 Cost Report Generator
═══════════════════════════════════════════════

Period: November 2025 (Nov 1 - Nov 18)
Loading cost data from Stop hooks...

Sources:
  ✓ Hook logs: 247 Stop hook entries
  ✓ Sandbox API: 15 sandbox sessions
  ✓ Orchestrator state: 12 issues

Data loaded successfully.
```

### Step 2: Calculate and Display Costs

```
💰 Cost Report - November 2025
═══════════════════════════════════════════════

TOTAL COSTS: $45.32
  Sandbox Runtime: $12.80 (28%)
  API Costs: $32.52 (72%)

Budget Status:
  Monthly Limit: $100.00
  Used: $45.32 (45%)
  Remaining: $54.68 (55%)
  Status: ✓ Within budget

───────────────────────────────────────────────

📈 Cost Breakdown by Type
═══════════════════════════════════════════════

Sandbox Costs: $12.80
  Sandbox Runtime: 640 hours @ $0.02/hr
  Templates: $2.00 (5 custom templates)

API Costs: $32.52
  Input Tokens: 2.45M @ $3/M = $7.35
  Output Tokens: 1.68M @ $15/M = $25.17
  Model: Claude Sonnet 4.5

───────────────────────────────────────────────

📊 Cost Breakdown by Issue
═══════════════════════════════════════════════

Top 10 Most Expensive Issues:

#42: User Authentication - $4.25
  Sandbox: $0.45 (22.5 hrs)
  API: $3.80 (165K in, 112K out)
  Status: Completed, PR merged

#45: Real-time Features - $3.87
  Sandbox: $0.82 (41 hrs)
  API: $3.05 (134K in, 89K out)
  Status: Completed, PR merged

#47: Search Feature - $3.45
  Sandbox: $0.52 (26 hrs)
  API: $2.93 (128K in, 85K out)
  Status: In progress

#43: Database Migration - $2.98
  Sandbox: $0.00 (local)
  API: $2.98 (145K in, 67K out)
  Status: Completed, PR merged

[6 more issues...]

Total Across All Issues: $45.32

───────────────────────────────────────────────

🏖️  Cost Breakdown by Sandbox
═══════════════════════════════════════════════

sbx_abc123xyz (#42): $4.25
  Created: Nov 5, 14:32
  Destroyed: Nov 5, 18:15
  Uptime: 3h 43m
  Cost: $0.45 (sandbox) + $3.80 (API)

sbx_def456uvw (#45): $3.87
  Created: Nov 8, 09:15
  Destroyed: Nov 9, 02:30
  Uptime: 17h 15m
  Cost: $0.82 (sandbox) + $3.05 (API)

[13 more sandboxes...]

Average Sandbox Cost: $3.02
Most Expensive: sbx_abc123xyz ($4.25)
Least Expensive: sbx_quick789 ($0.45)

───────────────────────────────────────────────

📅 Cost Breakdown by Day
═══════════════════════════════════════════════

Nov 1:  █████░░░░░ $2.15
Nov 2:  ███████░░░ $3.45
Nov 3:  ████░░░░░░ $1.98
Nov 4:  ██████████ $4.87 ← Peak day
Nov 5:  ████████░░ $3.92
Nov 6:  ██░░░░░░░░ $0.85
Nov 7:  ███░░░░░░░ $1.23
Nov 8:  ████████░░ $3.67
Nov 9:  ██████░░░░ $2.54
Nov 10: ████░░░░░░ $1.89
Nov 11: ███████░░░ $3.21
Nov 12: █████░░░░░ $2.34
Nov 13: ██████░░░░ $2.89
Nov 14: ████████░░ $3.78
Nov 15: ███████░░░ $3.12
Nov 16: █████░░░░░ $2.45
Nov 17: ████░░░░░░ $1.76
Nov 18: ██░░░░░░░░ $0.97 (partial)

Daily Average: $2.52
Peak Day: Nov 4 ($4.87)

───────────────────────────────────────────────

📊 Cost Trends
═══════════════════════════════════════════════

Week 1 (Nov 1-7):   $18.45 (41%)
Week 2 (Nov 8-14):  $17.92 (40%)
Week 3 (Nov 15-18): $8.95  (19%)

Trend: ↓ Decreasing (Week 3 pace: $15.66/week)

Projection:
  If current pace continues...
  Month-End Estimate: $52.25
  Budget Utilization: 52%
  Status: ✓ Under budget

───────────────────────────────────────────────

💡 Cost Optimization Recommendations
═══════════════════════════════════════════════

Immediate Savings Opportunities:

1. Clean Up Idle Sandboxes
   Current: 2 sandboxes idle >1 hour
   Potential Savings: $0.96/day ($28.80/month)
   Action: Run /cleanup-sandboxes

2. Use Templates More
   Current: 40% of sandboxes use templates
   Potential: 60% could use templates
   Time Saved: ~2 hours/day
   Cost Impact: Minimal direct savings
   Action: Create more templates

3. Optimize Token Usage
   Current: Average 245K tokens/issue
   Industry Average: 180K tokens/issue
   Potential Savings: ~$8/month
   Actions:
     - Use more concise prompts
     - Leverage caching
     - Reduce context window

4. Use Local Mode More
   Current: 60% sandbox, 40% local
   Recommendation: 40% sandbox, 60% local
   Potential Savings: ~$4/month
   Trade-off: Less isolation
   Best For: Simple features, docs

5. Parallel Execution Strategy
   Current: Mostly balanced strategy
   Recommendation: Cost-optimized for non-urgent
   Potential Savings: ~$5/month
   Trade-off: Longer completion time

Total Potential Monthly Savings: ~$46

───────────────────────────────────────────────

📈 Historical Comparison
═══════════════════════════════════════════════

October 2025: $38.67
November 2025: $45.32 (projected: $52.25)
Change: +35% ↑

Factors:
  ✓ More parallel execution (+$8)
  ✓ Larger features (+$5)
  ⚠️ Free tier exhausted (+$10)

───────────────────────────────────────────────

✅ Cost Report Summary
═══════════════════════════════════════════════

Period: November 2025 (18 days)
Total Cost: $45.32
Daily Average: $2.52
Issues Completed: 12
Cost per Issue: $3.78

Budget: $54.68 remaining (55%)
Free Tier: Exhausted (Nov 8)
Trend: Decreasing
Status: ✓ Healthy spending

Export: cost-report-2025-11.csv
```

## Examples

### Example 1: Monthly Report
```
/cost-report
```

### Example 2: Weekly Report
```
/cost-report --period week
```

### Example 3: Export to CSV
```
/cost-report --export costs.csv
```

## Integration

- Uses Stop hook logs for accurate API costs
- Uses E2B API for sandbox runtime costs
- Uses orchestrator state for issue mapping
- Updates cost tracking in real-time

## Error Handling

### Common Errors

**Missing Hook Logs**:
```
❌ Error: Insufficient cost data

Stop hook logs found: 0 entries
E2B API data: Available
Orchestrator state: Available

Cause: Hook system not enabled or no Stop hooks captured

Solutions:
  1. Enable Stop hooks: /config set hookConfig.enabled PreToolUse,PostToolUse,Stop
  2. Verify hooks are working: Check logs/agent-*.log files
  3. Run at least one feature to generate hook data
  4. Check hook configuration in e2b-config.json

Note: Cost reports require Stop hook data for accurate API cost tracking.
For sandbox-only costs, partial report will be generated from E2B API.
```

**Sandbox API Connection Error**:
```
❌ Error: Cannot fetch sandbox costs

API Error: 503 Service Unavailable
Endpoint: https://sandbox-api.example.com/sandboxes

Partial Cost Report Available:
  ✓ API costs from Stop hooks: $32.52
  ❌ Sandbox runtime costs: Unavailable

Estimated Total: $32.52 (API only)

Note: Sandbox costs will be included when Sandbox API is available.
Retry in a few minutes.

Troubleshooting:
  1. Check sandbox service status
  2. Verify SANDBOX_API_KEY is valid
  3. Check internet connection
  4. Retry: /cost-report --period month
```

**Invalid Period**:
```
❌ Error: Invalid period specified

You entered: --period yesterday

Valid periods:
  - today: Today's costs
  - week: Last 7 days
  - month: Current month (default)
  - all: All time
  - custom: Prompts for custom date range

Examples:
  /cost-report --period week
  /cost-report --period custom

Retry with a valid period.
```

**No Data for Period**:
```
⚠️  Warning: No cost data for specified period

Period: Last 7 days (Nov 12-18, 2025)
Issues completed: 0
Sandbox sessions: 0
API calls: 0

Total cost: $0.00

Possible causes:
  1. No features implemented in this period
  2. All work done in local mode
  3. Hook logs from this period were deleted
  4. Orchestrator state was reset

To see costs from other periods:
  /cost-report --period month
  /cost-report --period all
```

**Export File Error**:
```
❌ Error: Cannot write export file

File: /protected/costs.csv
Error: EACCES: permission denied

Cause: No write permission for specified path

Solutions:
  1. Use a different path: /cost-report --export ~/costs.csv
  2. Check directory permissions: ls -l /protected/
  3. Export to default location: /cost-report --export costs.csv
     (Saves to current directory)

Default export locations:
  - CSV: ./cost-report-YYYY-MM.csv
  - JSON: ./cost-report-YYYY-MM.json
```

**Budget Calculation Error**:
```
❌ Error: Budget limit not configured

Current configuration:
  budgetLimit: null

Cannot calculate budget utilization or generate projections.

Solutions:
  1. Set budget limit: /config set costManagement.budgetLimit 100
  2. View costs without budget analysis: /cost-report (will skip budget section)
  3. Reset to default budget: /config reset costManagement.budgetLimit

Recommended budget limits:
  - Personal projects: $50-100/month
  - Small teams: $200-500/month
  - Production use: $1000+/month
```

**Corrupted State File**:
```
❌ Error: Cannot read orchestrator state

File: .claude/config/orchestrator-state.json
Error: Unexpected token in JSON at position 234

Partial Cost Report Available:
  ✓ Hook logs: Readable
  ❌ Issue mapping: Unavailable
  ❌ Session data: Unavailable

Cost breakdown by issue will be unavailable.
Total costs can still be calculated.

Recovery:
  1. Check state file for corruption: cat .claude/config/orchestrator-state.json
  2. Restore from backup if available
  3. Reset state: /config reset orchestrator.stateFile
     (Warning: Loses current session data)

Generating simplified report without issue breakdown...
```

### Recovery Actions

**Automatic Recovery**:
- Falls back to E2B API if hook logs unavailable
- Generates partial reports when data sources are incomplete
- Skips budget analysis if budget not configured
- Provides helpful error messages with solutions

**Manual Recovery**:
```bash
# Verify hook system is working
cat apps/sandbox_agent_working_dir/logs/agent-*.log | grep "Stop hook"

# Check Sandbox API manually
curl -H "Authorization: Bearer $SANDBOX_API_KEY" https://sandbox-api.example.com/sandboxes

# Repair corrupted state
cp .claude/config/orchestrator-state.json.backup .claude/config/orchestrator-state.json

# Or reset state (loses current session)
/config reset orchestrator.stateFile

# Re-enable hooks if disabled
/config set hookConfig.enabled PreToolUse,PostToolUse,Stop
```

## Integration

- Uses Stop hook logs for accurate API costs
- Uses E2B API for sandbox runtime costs
- Uses orchestrator state for issue mapping
- Updates cost tracking in real-time

## Notes

- Stop hooks provide precise token usage
- Costs calculated using Anthropic pricing
- Sandbox costs: $0.02/hour
- Reports include optimization recommendations
- Export formats: table, JSON, CSV
- Requires Stop hooks enabled for accurate API cost tracking
- Falls back to Sandbox API only if hook logs unavailable
- Budget limits must be configured for projections and alerts

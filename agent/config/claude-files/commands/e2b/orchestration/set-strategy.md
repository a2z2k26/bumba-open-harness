---
name: set-strategy
description: Set orchestration strategy
---

# /set-orchestration-strategy Command

Changes the orchestration strategy for the active session mid-flight, allowing you to dynamically adjust parallelism, resource usage, and cost optimization based on changing priorities or constraints.

## Usage

```
/set-orchestration-strategy <strategy> [options]
```

## Parameters

- `<strategy>` (required): New strategy - options: `aggressive`, `balanced`, `conservative`
- `--apply-now` (optional): Apply to active agents immediately (requires pause/resume) - default: false
- `--dry-run` (optional): Show impact without making changes - default: false
- `--force` (optional): Skip confirmation prompt - default: false

## Strategies

### aggressive
**Maximum Speed**: Prioritizes completion time over cost.
- Max concurrent agents: 10-15
- Auto-spawn: Enabled for all queued features
- Resource allocation: High
- Use case: Tight deadlines, sprints, urgent work

### balanced
**Optimal Balance**: Balances speed and cost efficiently.
- Max concurrent agents: 5-7
- Auto-spawn: Enabled with throttling
- Resource allocation: Moderate
- Use case: Normal development, sustainable pace

### conservative
**Cost Optimization**: Minimizes cost, accepts longer completion time.
- Max concurrent agents: 2-3
- Auto-spawn: Disabled or very limited
- Resource allocation: Minimal
- Use case: Budget constraints, non-urgent work

## Workflow

### Step 1: Strategy Analysis

```
⚙️  Change Orchestration Strategy
═══════════════════════════════════════════════

Current Configuration:
  Strategy: balanced
  Max Agents: 5
  Active Agents: 5
  Queued Features: 3
  Auto-Spawn: Enabled

Requested Strategy: aggressive
  Max Agents: 10
  Auto-Spawn: Aggressive
  Resource Allocation: High

───────────────────────────────────────────────
```

### Step 2: Impact Projection

```
Impact Analysis:

Current State (balanced):
  Active Agents: 5
  Queued Features: 3
  Estimated Completion: 3h 45m
  Estimated Cost: $18.75
  Resource Usage: 60%

Projected State (aggressive):
  Active Agents: 5 (will continue)
  New Spawns: +3 (for queued features)
  Peak Agents: 8
  Estimated Completion: 2h 15m (-1h 30m)
  Estimated Cost: $24.50 (+$5.75)
  Resource Usage: 85%

Trade-offs:
  ⏱️  Time Savings: 1h 30m (40% faster)
  💰 Cost Increase: +$5.75 (31% more expensive)
  📊 Resource Impact: +25% utilization

Confirmation required to proceed.

───────────────────────────────────────────────
```

### Step 3: Strategy Application

```
Applying strategy change...
  ✓ Strategy updated: aggressive
  ✓ Max agents increased: 5 → 10
  ✓ Auto-spawn enabled: aggressive mode
  ✓ Resource reservations updated

Auto-spawning queued features...
  ⟳ Spawning agent for #51...
  ⟳ Spawning agent for #52...
  ⟳ Spawning agent for #53...
  ✓ 3 new agents spawned

Current State:
  Active Agents: 8 (5 original + 3 new)
  Strategy: aggressive
  Available Slots: 2
  Next spawn: Immediate when slot available

───────────────────────────────────────────────
```

### Step 4: Confirmation

```
✅ Strategy Changed Successfully
═══════════════════════════════════════════════

New Configuration:
  Strategy: aggressive
  Max Concurrent Agents: 10
  Active Agents: 8
  Queued Features: 0 (all spawned)

Impact:
  Estimated Completion: 2h 15m (was 3h 45m)
  Estimated Cost: $24.50 (was $18.75)
  Savings: -1h 30m completion time

Monitoring:
  View status: /orchestrator-status
  View events: /orchestrator-events --follow
  Adjust again: /set-orchestration-strategy balanced

Strategy change logged to audit trail.
```

## Examples

### Example 1: Switch to Aggressive
```
/set-orchestration-strategy aggressive
```

**Output**:
```
⚙️  Change to Aggressive Strategy

Current: balanced (5 max agents)
New: aggressive (10 max agents)

Impact:
  Time: 3h 45m → 2h 15m (-40%)
  Cost: $18.75 → $24.50 (+31%)

Auto-spawning 3 queued features...

✅ Strategy: aggressive
Active Agents: 8
```

### Example 2: Switch to Conservative
```
/set-orchestration-strategy conservative
```

**Output**:
```
⚙️  Change to Conservative Strategy

Current: balanced (5 max agents)
New: conservative (2 max agents)

Impact:
  Time: 3h 45m → 6h 30m (+73%)
  Cost: $18.75 → $12.25 (-35%)

Active agents will complete.
New spawns limited to 2 concurrent.

✅ Strategy: conservative
Note: No new agents until slots available
```

### Example 3: Dry Run Analysis
```
/set-orchestration-strategy aggressive --dry-run
```

**Output**:
```
⚙️  Strategy Change Analysis (Dry Run)

Proposed Change: balanced → aggressive

Impact Projection:
  Max Agents: 5 → 10
  Queued to Spawn: 3 features
  Completion Time: 3h 45m → 2h 15m
  Cost: $18.75 → $24.50

Resource Check:
  ✓ CPU capacity available
  ✓ Memory capacity available
  ✓ Disk capacity available
  ⚠️ Will use 85% of resources

Recommendation: Proceed with caution
  Current resource usage: 60%
  Projected usage: 85%
  Headroom: 15%

No changes made (dry run).

To apply:
  /set-orchestration-strategy aggressive
```

### Example 4: Apply to Active Agents
```
/set-orchestration-strategy conservative --apply-now
```

**Output**:
```
⚙️  Apply Strategy to Active Agents

⚠️  This requires pause/resume cycle

Current: balanced (5 active agents)
New: conservative (2 max agents)

Active agents exceed new limit (5 > 2).

Actions:
  1. Pause orchestration
  2. Apply conservative strategy
  3. Resume with 2 agents
  4. Remaining 3 agents queued

Impact:
  Paused agents: 3 (#47, #49, #50)
  Will resume as slots available

Proceed with pause/resume? (yes/no): yes

⏸️  Pausing orchestration...
⚙️  Applying strategy...
▶️  Resuming with 2 agents...

✅ Strategy Applied
Active: 2 agents (#42, #45)
Queued: 3 agents (will resume sequentially)
```

### Example 5: Force Without Confirmation
```
/set-orchestration-strategy balanced --force
```

**Output**:
```
⚙️  Strategy Changed (No Confirmation)

Current: aggressive
New: balanced

Impact:
  Max Agents: 10 → 5
  Active Agents: 8 (will complete)
  New spawns limited to 5 concurrent

✅ Strategy: balanced
```

## Strategy Comparison

### Performance Characteristics

| Aspect | Aggressive | Balanced | Conservative |
|--------|-----------|----------|--------------|
| Max Agents | 10-15 | 5-7 | 2-3 |
| Auto-Spawn | Immediate | Throttled | Limited |
| Cost | Highest | Medium | Lowest |
| Speed | Fastest | Medium | Slowest |
| Resource Use | 80-95% | 50-70% | 25-40% |
| Best For | Deadlines | Normal work | Budget limits |

### Cost vs Time Trade-offs

**Aggressive**:
- 40-50% faster than balanced
- 25-35% more expensive than balanced
- Best when time is critical

**Balanced**:
- Baseline for comparison
- Optimal cost/time ratio
- Recommended default

**Conservative**:
- 60-80% slower than balanced
- 30-40% cheaper than balanced
- Best when budget constrained

## Error Handling

### Error 1: Invalid Strategy

```
❌ Error: Invalid strategy

Requested Strategy: "super-fast"

Valid Strategies:
  aggressive  - Maximum speed, high cost
  balanced    - Optimal balance (recommended)
  conservative - Minimum cost, slower

Did you mean:
  /set-orchestration-strategy aggressive

Usage:
  /set-orchestration-strategy <strategy>
```

### Error 2: No Active Orchestration

```
❌ Error: No active orchestration

Cannot change strategy without active orchestration session.

Available Actions:
  Start orchestration:
    /parallel-implement-features #42 #45 #47

  View status:
    /orchestrator-status
```

### Error 3: Resource Constraints

```
❌ Error: Insufficient resources for strategy

Requested Strategy: aggressive
Max Agents: 10

Resource Check:
  Current Usage: 75%
  Projected Usage: 95%
  ⚠️ Exceeds safe threshold (85%)

Impact:
  Risk: Performance degradation
  Recommendation: Use balanced strategy

Available Options:
  1. Use balanced strategy:
     /set-orchestration-strategy balanced

  2. Clean up resources first:
     /cleanup-sandboxes --aggressive
     /set-orchestration-strategy aggressive

  3. Force anyway (not recommended):
     /set-orchestration-strategy aggressive --force

Recommendation: Option 1 or Option 2
```

## Integration

### Integration with Orchestrator
- Updates orchestration state immediately
- Affects agent spawn decisions
- Persists across pause/resume
- Logged to event system

### Integration with Resource Manager
- Validates resource availability
- Updates resource reservations
- Adjusts allocation limits
- Monitors capacity

### Integration with Cost Tracking
- Recalculates cost projections
- Updates budget estimates
- Tracks strategy changes
- Enables cost optimization

### Integration with Queue Management
- Controls auto-spawn behavior
- Adjusts parallelism limits
- Manages agent priorities
- Optimizes throughput

## Use Cases

### Use Case 1: Sprint Crunch Time
**Scenario**: Sprint deadline approaching; need maximum speed.

**Command**:
```bash
/set-orchestration-strategy aggressive
```

**Result**: All queued features spawn immediately, maximum parallelism.

### Use Case 2: Budget Running Low
**Scenario**: Approaching budget limit; need to slow down spending.

**Command**:
```bash
/set-orchestration-strategy conservative
```

**Result**: Reduced parallelism, lower hourly cost.

### Use Case 3: Performance Issues
**Scenario**: Server under heavy load; need to reduce resource usage.

**Command**:
```bash
/set-orchestration-strategy conservative
```

**Result**: Fewer concurrent agents, less resource pressure.

### Use Case 4: Optimize for Long Run
**Scenario**: Large backlog, no deadline; want optimal cost/time balance.

**Command**:
```bash
/set-orchestration-strategy balanced
```

**Result**: Sustainable pace with good cost efficiency.

### Use Case 5: Test Strategy Impact
**Scenario**: Want to see impact before committing.

**Command**:
```bash
/set-orchestration-strategy aggressive --dry-run
```

**Result**: Projected impact shown, no changes made.

## Performance Considerations

### Strategy Change Speed
- Immediate for future spawns
- Active agents unaffected (unless --apply-now)
- Queue reprocessed instantly
- New agents spawn within seconds

### Resource Impact
- Aggressive: High resource usage (80-95%)
- Balanced: Moderate usage (50-70%)
- Conservative: Low usage (25-40%)
- Monitor with `/orchestrator-status`

### Cost Impact
- Strategy changes affect hourly cost
- Active agents continue at current cost
- New spawns use new strategy cost model
- Track with `/cost-report`

## Best Practices

### When to Use Aggressive
- Sprint deadlines
- Production emergencies
- Critical feature delivery
- Abundant budget available

### When to Use Balanced
- Normal development pace
- Sustainable workload
- No specific deadline pressure
- Recommended default

### When to Use Conservative
- Budget constraints
- Non-urgent backlog work
- Resource limitations
- Long-term projects

### Strategy Switching Tips
- Use `--dry-run` to preview impact
- Monitor resource usage after changes
- Switch back if issues arise
- Log strategy changes for analysis

## Notes

- **Immediate Effect**: Strategy applies to future spawns instantly
- **Active Agents**: Continue unchanged unless `--apply-now` used
- **Reversible**: Can change strategy multiple times
- **Persistent**: Strategy persists across pause/resume
- **Logged**: All changes logged to audit trail
- **Cost Impact**: Significant effect on total cost
- **Time Impact**: Significant effect on completion time
- **Resource Aware**: Validates capacity before applying
- **Flexible**: Change anytime based on priorities
- **Dry Run**: Preview impact before committing

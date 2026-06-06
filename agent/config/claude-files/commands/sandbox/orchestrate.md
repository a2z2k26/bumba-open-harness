---
name: sandbox/orchestrate
description: Plan multi-issue parallel sandbox execution from GitHub issues
arguments:
  - name: repo
    description: "GitHub repo in owner/repo format"
    required: true
  - name: issues
    description: "Comma-separated issue numbers (e.g., 1,2,3)"
    required: true
  - name: strategy
    description: "Allocation strategy: balanced, max-speed, cost-optimized (default: balanced)"
    required: false
---

# /sandbox/orchestrate — Multi-Issue Parallel Execution Planning

Analyzes GitHub issue dependencies and plans sandbox allocation for parallel execution.

**Note:** Actual agent spawning is a placeholder — this command produces an execution plan only.

## Usage

```
/sandbox/orchestrate <owner/repo> --issues 1,2,3 [--strategy balanced|max-speed|cost-optimized]
```

## Implementation

When the user runs this command, execute the following steps:

### Step 1: Parse Arguments

Extract from `$ARGUMENTS`:
- `repo`: Required. Format `owner/repo`.
- `--issues`: Required. Comma-separated issue numbers, parsed to number array.
- `--strategy`: Optional. One of `balanced`, `max-speed`, `cost-optimized`. Default: `balanced`.

### Step 2: Analyze Dependencies

Call `bumba-sandbox:analyze_dependencies` with:
- `owner`: extracted from repo
- `repo`: extracted from repo
- `issueNumbers`: parsed number array

### Step 3: Plan Allocation

Call `bumba-sandbox:plan_sandbox_allocation` with:
- `dependencyGraph`: the result from step 2
- `strategy`: the parsed strategy
- `maxConcurrent`: 5 (default)

### Step 4: Display Execution Plan

```
Orchestration Plan: <owner/repo>
Strategy: <strategy>
Issues: <count>

Dependency Graph:
  <issue#> → depends on: [<issue#>, ...]
  <issue#> → no dependencies

Execution Phases:
  Phase 1 (parallel): [<issue#>, <issue#>]  — no dependencies
  Phase 2 (parallel): [<issue#>]            — after phase 1
  Phase 3 (sequential): [<issue#>]          — depends on <issue#>

Estimated:
  Sandboxes needed: <n>
  Max concurrent:   <n>
  Estimated cost:   <cost info if available>

Note: Agent spawning is not yet implemented.
      Use this plan to manually create sandboxes per phase.
```

### Step 5: Handle Errors

If dependency analysis fails:
- Verify the issue numbers exist in the repository
- Check GitHub API connectivity via `github:list_issues`

If issues have circular dependencies:
- Flag the cycle and suggest breaking it

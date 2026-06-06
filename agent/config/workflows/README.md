# Zone 4 Workflow YAML Schema

Workflows are declarative pipelines that compose Zone 4 department invocations,
built-in actions, and operator gates.  They are defined as YAML files in this
directory and loaded at runtime via `WorkflowRegistry`.

## Default Workflows

| File | Trigger | Departments | One-liner |
|------|---------|-------------|-----------|
| `example.yaml` | `explicit` | strategy, ops, board | Demonstrates every step type — parallel department fan-out, operator gate, action publish, and on-failure compensation. |
| `pr-ship-decision.yaml` | `webhook` (`github.pull_request.opened`) | qa, strategy, board | Reviews an opened PR through QA and Strategy in parallel, asks Board for a ship/hold/iterate verdict with confidence, and gates a Discord-approval step when the board confidence drops below 0.7 before posting the decision back to GitHub. |
| `weekly-ceo-review.yaml` | `schedule` (`cron:0 8 * * 1`) | strategy, ops, board | Pulls Strategy signals and Ops health each Monday morning, hands them to Board for a "What's Working / What's Next / Risks to Watch" digest, and publishes the result to the operator's Discord channel. |

Operators interact via `/workflows`:

| Command | Effect |
|---------|--------|
| `/workflows` | List every loaded workflow with trigger / step count / budget. |
| `/workflows <name>` | Show full detail for a single workflow + its recent runs. |
| `/workflows trigger <name>` | Manually dispatch a workflow (returns the run id). |
| `/workflows cancel <run_id>` | Cancel an active run. |
| `/workflows reload` | Reload every YAML from disk after edits. |

## File Layout

```
config/workflows/
  _schema.py           — Pydantic models (WorkflowConfig, WorkflowStep subtypes)
  README.md            — This file
  example.yaml         — Demonstrates all schema features
  weekly-ceo-review.yaml
  pr-ship-decision.yaml
```

## Top-Level Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Unique kebab-case identifier |
| `trigger` | `explicit` \| `schedule` \| `webhook` | yes | How the workflow is initiated |
| `schedule` | string | when trigger=schedule | Cron expression: `cron:0 8 * * 1` |
| `webhook` | string | when trigger=webhook | Event name: `github.pull_request.opened` |
| `budget.max_cost_usd` | float | no (default 5.0) | Aggregate USD cap across all steps |
| `budget.max_duration_seconds` | int | no (default 600) | Wall-clock timeout |
| `steps` | list | yes | Ordered list of step definitions |

## Step Types

### Department Step

Invokes a Zone 4 department with a natural-language intent.

```yaml
- name: gather-signals
  department: strategy        # strategy | ops | board | qa | design
  intent: "Describe the task — may reference {context_keys}"
  inputs: [key1, key2]       # Context keys injected into the prompt
  outputs: [result_key]      # Keys written to shared context after the step
  parallel_with: other-step  # Optional: run concurrently with another step
  cost_limit_usd: 1.0        # Optional per-step cap
  on_failure: [rollback-step] # Compensating steps run in reverse on failure
```

### Gate Step

Pauses the workflow and waits for operator approval via Discord.

```yaml
- name: operator-gate
  gate: operator
  timeout_seconds: 3600
  message: "Ready to publish: {digest}. Approve?"
  condition: "{confidence} < 0.7"  # Optional: skip gate when false
  on_failure: [cleanup-step]
```

Operator responds with `/approve <run_id>` or `/reject <run_id> <reason>`.

### Action Step

Executes a built-in primitive.

```yaml
- name: publish
  action: publish_discord        # publish_discord | publish_github_comment
  channel: operator              # For publish_discord
  target: pr                     # For publish_github_comment
  message: "{digest}"
```

## Context Passing

Steps share a mutable context dictionary.  A step's `outputs` list declares
which keys it writes; subsequent steps reference them in `inputs` and in
template strings via `{key}` placeholders.

## Failure Compensation

If a step raises an unhandled exception, the engine:
1. Marks the run as `failed`
2. Iterates steps that have already completed in **reverse order**
3. For each completed step with a non-empty `on_failure` list, runs those
   named compensating steps

Compensating steps are looked up by name in the same workflow definition.

## Budget Enforcement

Before dispatching each step, the engine checks:

```
sum(completed_step_costs) + next_step.cost_limit_usd > budget.max_cost_usd
```

If the check fails, the engine halts with `z4.workflow.budget_exceeded`.

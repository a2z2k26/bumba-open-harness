---
name: cross-department-workflows
description: Pre-defined multi-department workflows for common engineering scenarios. Use when a task requires coordination across multiple Zone 4 departments.
---

# Cross-Department Workflows

## Full Feature Workflow
**When:** Building a new feature from concept to deployment.
**Departments:** Strategy -> Design -> Engineering (Zone 3) -> QA -> Ops

```
1. STRATEGY: Define requirements
   escalate(department="strategy", task="Create PRD for [feature]")
   Output: PRD with requirements, acceptance criteria

2. DESIGN: Create specifications
   escalate(department="design", task="Design specs for [feature]",
            context_files=["specs/requirements/[prd].md"])
   Output: Design specs, component designs, interaction patterns

3. ENGINEERING: Implement (Zone 3 subagents)
   Delegate to engineering-chief with PRD + design specs as context
   Output: Working implementation

4. QA: Validate
   escalate(department="qa", task="Full QA review of [feature]",
            context_files=["specs/requirements/[prd].md"])
   Output: QA assessment, issues found, coverage report

5. OPS: Deploy
   escalate(department="ops", task="Deployment review for [feature]")
   Output: Deployment plan, infrastructure requirements
```

## Security Audit Workflow
**When:** Proactive security review or incident response.
**Departments:** QA -> Engineering -> QA -> Ops

```
1. QA: Identify vulnerabilities
   escalate(department="qa", task="Security audit of [scope]")

2. ENGINEERING: Fix issues (Zone 3)
   engineering-chief coordinates fixes based on QA findings

3. QA: Verify fixes
   escalate(department="qa", task="Verify security fixes for [scope]",
            context_files=[audit_report, fix_commits])

4. OPS: Deploy patches
   escalate(department="ops", task="Deploy security patches")
```

## New Product Evaluation
**When:** Evaluating a new business idea or product concept.
**Departments:** Board -> Strategy -> Design -> Engineering

```
1. BOARD: Ideate and validate
   escalate(department="board", brief="[structured brief with business idea]")
   Output: Board memo with go/no-go, validation experiment

2. STRATEGY: Create PRD (if GO)
   escalate(department="strategy", task="Create PRD based on board memo",
            context_files=[board_memo])

3. DESIGN: Prototype
   escalate(department="design", task="Rapid prototype for [concept]",
            context_files=[prd])

4. ENGINEERING: Technical feasibility
   engineering-chief assesses buildability and architecture fit
```

## Architecture Decision
**When:** Major technical decision with business implications.
**Departments:** Board (with tech focus) -> Engineering

```
1. BOARD: Multi-perspective analysis
   escalate(department="board", brief="[architectural decision brief]")
   Include technical details in the brief for the Technical Architect member

2. ENGINEERING: Implementation plan
   engineering-chief creates implementation plan based on board recommendation
```

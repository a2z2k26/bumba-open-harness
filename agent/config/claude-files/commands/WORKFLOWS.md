# Project Management Workflows

**Quick Reference Guide for Workflow-Based Command Discovery**

This guide organizes commands by development workflow stage, helping you find the right command for where you are in the development lifecycle.

---

## Complete Workflow: Idea → Ship

```
1. IDEATION → 2. SPECIFICATION → 3. IMPLEMENTATION → 4. VERIFICATION → 5. DEPLOYMENT
```

---

## Phase 1: IDEATION

**Goal:** Generate and document feature ideas

### Commands

| Command | Location | Description |
|---------|----------|-------------|
| `/brainstorm` | `orc/` | AI-powered feature ideation with RICE scoring |
| `/requirements` | `orc/` | Create structured PRD from idea |

### Typical Flow

```bash
/brainstorm "improve user engagement"
  → Generates 10 ranked ideas

/requirements
  → Creates PRD: docs/prd/[feature].md
```

---

## Phase 2: SPECIFICATION

**Goal:** Review, plan, and break down features

### Commands

| Command | Location | Description |
|---------|----------|-------------|
| `/review-spec` | `orc/` | Validate PRD completeness and feasibility |
| `/plan-sprints` | `orc/` | Break PRD into sprint-sized chunks |
| `/create-issues` | `gh/` | Create GitHub issues from sprint plan |

### Typical Flow

```bash
/review-spec
  → Validates PRD, identifies gaps

/plan-sprints
  → Creates sprint plan: docs/specs/sprint-plan.md

/create-issues
  → Creates GitHub issues #42, #43, #44
```

---

## Phase 3: IMPLEMENTATION

**Goal:** Build features with isolation and planning

### Commands

| Command | Location | Description |
|---------|----------|-------------|
| `/plan-feature` | `orc/` | Generate step-by-step implementation plan |
| `/feature-branch` | `git/` | Create feature worktree |
| `/parallel` | `orc/` | Multi-feature parallel execution (E2B sandboxes) |
| `/quick` | `orc/` | Plan + build in single command |
| `/hotfix-branch` | `git/` | Fast-track critical bug fix |
| `/execute` | `code/` | Execute pre-generated plan |

### Typical Flows

**Single Feature (Local)**
```bash
/plan-feature #42
  → Creates .plans/issue-42.md

/feature-branch #42
  → Creates worktree, implements feature

/execute
  → Executes plan from /plan-feature
```

**Parallel Features (Sandboxes)**
```bash
/parallel #42 #43 #44
  → Spawns 3 E2B sandboxes
  → Implements all features in parallel
  → Tracks via orchestrator
```

**Quick Implementation**
```bash
/quick "Add dark mode toggle"
  → Plans and builds in one command
```

**Emergency Fix**
```bash
/hotfix-branch "Fix auth bypass"
  → Fast-track critical security fix
```

---

## Phase 4: VERIFICATION

**Goal:** Test, review, and validate

### Commands

| Command | Location | Description |
|---------|----------|-------------|
| `/feature` | `testing/` | Run tests for single feature |
| `/all` | `testing/` | Run all tests in parallel |
| `/matrix` | `testing/` | Multi-environment cross-platform testing |
| `/review-pr` | `gh/` | AI-powered code review |
| `/address-feedback` | `gh/` | Address PR review comments |
| `/sync-branch` | `git/` | Merge/rebase branch with main |

### Typical Flows

**Test First**
```bash
/feature #42
  → Runs tests for feature #42

/all
  → Runs all tests in parallel

/matrix
  → Cross-platform/environment testing
```

**Code Review**
```bash
/review-pr #42
  → AI review: security, performance, best practices

/address-feedback #42
  → Addresses PR comments
```

**Sync with Main**
```bash
/sync-branch #42
  → Merges/rebases with main
  → Resolves conflicts
```

---

## Phase 5: DEPLOYMENT

**Goal:** Create PR, merge, and export metrics

### Commands

| Command | Location | Description |
|---------|----------|-------------|
| `/create-pr` | `gh/` | Create pull request with AI description |
| `/merge-pr` | `gh/` | Merge approved PR and cleanup |
| `/export` | `orc/` | Export session data and metrics |

### Typical Flow

```bash
/create-pr #42
  → Pre-flight checks (tests, linting, sync)
  → AI-generated description
  → Creates GitHub PR

/merge-pr #42
  → Merges approved PR
  → Cleans up worktrees
  → Destroys sandboxes
  → Updates orchestrator state

/export
  → Cost reports
  → Time metrics
  → Success analytics
```

---

## Sandbox Management (E2B)

**Goal:** Manage isolated development environments

### Management

| Command | Location | Description |
|---------|----------|-------------|
| `/status` | `e2b/management/` | Check sandbox status |
| `/start` | `e2b/management/` | Start new sandbox |
| `/debug` | `e2b/management/` | Debug sandbox environment |
| `/exec` | `e2b/management/` | Execute command in sandbox |
| `/test` | `e2b/management/` | Run tests in sandbox |
| `/snapshot` | `e2b/management/` | Create snapshot |
| `/restore` | `e2b/management/` | Restore from snapshot |
| `/cleanup` | `e2b/management/` | Cleanup idle sandboxes |

### Templates

| Command | Location | Description |
|---------|----------|-------------|
| `/create-template` | `e2b/templates/` | Create custom sandbox template |
| `/list-templates` | `e2b/templates/` | List available templates |

### Orchestration

| Command | Location | Description |
|---------|----------|-------------|
| `/status` | `e2b/orchestration/` | Check orchestrator status |
| `/events` | `e2b/orchestration/` | View orchestrator events |
| `/set-strategy` | `e2b/orchestration/` | Set orchestration strategy |
| `/pause-all` | `e2b/orchestration/` | Pause all orchestration |
| `/resume-all` | `e2b/orchestration/` | Resume orchestration |
| `/pause-feature` | `e2b/orchestration/` | Pause specific feature |
| `/resume-feature` | `e2b/orchestration/` | Resume specific feature |

### Cost Management

| Command | Location | Description |
|---------|----------|-------------|
| `/cost-report` | `e2b/` | Generate cost breakdown |
| `/optimize` | `e2b/` | Optimize sandbox allocation |

### Typical Flow

```bash
/parallel #10 #11 #12 #13 #14
  → Starts parallel work

/status (e2b/orchestration/)
  → Shows all 5 agents, progress, costs

/status (e2b/management/) sandbox-abc123
  → Detailed sandbox metrics

/pause-feature #14
  → Pauses sandbox, saves state

/cost-report
  → Breakdown by sandbox

/optimize
  → Analyzes and suggests optimizations

/cleanup
  → Terminates idle sandboxes
```

---

## Project Configuration

| Command | Location | Description |
|---------|----------|-------------|
| `/init` | `project/` | Initialize project structure |
| `/config` | `project/` | Manage project configuration |
| `/status` | `project/` | View project status |

### Typical Flow

```bash
/init
  → Creates directory structure
  → Generates config files
  → Sets up templates

/config
  → Update bumba-sandbox-config.json
  → Adjust orchestrator settings

/status (project/)
  → View project metrics
  → Budget tracking
  → Feature completion
```

---

## Command Discovery Patterns

### By Tool/Platform

```bash
# GitHub operations
/help | grep "(user:gh)"
  → /create-issues, /create-pr, /merge-pr, /review-pr, /address-feedback

# Git/Worktree operations
/help | grep "(user:git)"
  → /feature-branch, /sync-branch, /hotfix-branch

# E2B Sandboxes
/help | grep "(user:e2b)"
  → All 20 E2B commands (management, templates, orchestration, cost)

# Testing
/help | grep "(user:testing)"
  → /feature, /all, /matrix

# Orchestration (Multi-tool)
/help | grep "(user:orc)"
  → /brainstorm, /requirements, /review-spec, /plan-sprints, /plan-feature, /parallel, /quick, /export
```

### By Workflow Stage

Use this guide to find commands by workflow stage, then invoke directly.

---

## Common Workflow Patterns

### Pattern 1: Full Feature Development (Idea → Ship)

```bash
# 1. Ideation
/brainstorm "user engagement"
/requirements

# 2. Specification
/review-spec
/plan-sprints
/create-issues

# 3. Implementation (Parallel)
/parallel #42 #43 #44

# 4. Verification
/all
/review-pr #42

# 5. Deployment
/create-pr #42
/merge-pr #42
/export
```

### Pattern 2: Quick Single Feature

```bash
# 1-step ideation/spec (manual)
# 2. Quick implementation
/quick "Add dark mode toggle"

# 3. Test
/feature

# 4. Ship
/create-pr
```

### Pattern 3: Emergency Hotfix

```bash
# Fast-track critical fix
/hotfix-branch "Fix authentication bypass"

# Quick test
/feature --critical

# Ship immediately
/create-pr --priority critical
```

### Pattern 4: Sandbox-Heavy Development

```bash
# Start parallel work
/parallel #10 #11 #12 #13 #14

# Monitor
/status (e2b/orchestration/)

# Manage costs
/pause-feature #14
/optimize
/cleanup

# Resume when budget allows
/resume-feature #14
```

---

## Tips for Discovery

1. **Think tool-first:** "I need GitHub" → look in `gh/`
2. **Think action-second:** "I need to create something" → `/create-*`
3. **Context labels help:** Multiple `/status` commands? Context shows which one
4. **Use this guide:** Map workflow stage → commands
5. **Tab completion:** `/create-<tab>` shows all create commands

---

**Related Documentation:**
- PROJECT-MANAGEMENT-COMMAND-SYSTEM.md - Complete system overview
- TOOL-PLATFORM-COMMAND-REORGANIZATION.md - Reorganization details

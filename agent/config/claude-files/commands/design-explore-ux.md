---
name: design-explore-ux
description: Generate four divergent UX design directions using specialized design agents in parallel E2B sandboxes
version: 5.0.0
---

# IMMEDIATE EXECUTION - DO NOT JUST EXPLAIN

When this command is invoked, IMMEDIATELY execute the following workflow. DO NOT explain what you're going to do. DO NOT wait for permission. START EXECUTING NOW.

## Step 1: Setup and Validation

Create todo list:
```
1. Validate environment and detect framework
2. Create 4 E2B sandboxes with design-ux-template
3. Create git worktrees for each direction
4. Spawn Phase 1 agents (design-interaction-designer)
5. Monitor and spawn Phase 2 agents (design-prototyper)
6. Sync files to worktrees
7. Present results
```

Check environment:
- Run `git status --porcelain` (inform if uncommitted changes, but continue)
- Read package.json to detect framework (default: React 18)
- Check for `.design/componentRegistry.json` (note if available)
- Verify E2B_API_KEY exists (stop if missing)

## Step 2: Prepare Design System (if available)

If `.design/componentRegistry.json` exists, read design system files:
- Read `.design/componentRegistry.json`
- Read `.design/tokens/*.json` (all token files)
- Read `.design/STYLES.md` if exists
- Store all content in memory for upload

If design system NOT available:
- Set design_system_available = false
- Agents will use generic UX principles

## Step 3: Create Sandboxes and Upload Design System

Call mcp__bumba-sandbox__sandbox_create FOUR TIMES IN PARALLEL:
- Direction 1: conventional, template: "design-ux-template"
- Direction 2: refined, template: "design-ux-template"
- Direction 3: progressive, template: "design-ux-template"
- Direction 4: experimental, template: "design-ux-template"

Store sandbox IDs: sandbox_conventional, sandbox_refined, sandbox_progressive, sandbox_experimental

**Immediately after each sandbox is created**, if design system available, upload files:
```
For each sandbox_id:
  mcp__bumba-sandbox__files_write(sandbox_id, "/tmp/design-system/componentRegistry.json", registry_content)
  mcp__bumba-sandbox__files_write(sandbox_id, "/tmp/design-system/tokens.json", tokens_content)
  mcp__bumba-sandbox__files_write(sandbox_id, "/tmp/design-system/STYLES.md", styles_content)
```

This makes design system available at `/tmp/design-system/` in each sandbox.

## Step 3: Create Git Worktrees

Run bash command:
```bash
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
git worktree add worktrees/ux-conventional -b ux-conventional-$TIMESTAMP
git worktree add worktrees/ux-refined -b ux-refined-$TIMESTAMP
git worktree add worktrees/ux-progressive -b ux-progressive-$TIMESTAMP
git worktree add worktrees/ux-experimental -b ux-experimental-$TIMESTAMP
```

## Step 4: Spawn Phase 1 Agents

Use Task tool to spawn 4 design-interaction-designer agents IN PARALLEL (run_in_background: true).

For EACH direction, use this prompt template (replace {DIRECTION}, {SANDBOX_ID}, {FRAMEWORK}, {USER_REQUEST}):

```
You are exploring the {DIRECTION} UX direction for: {USER_REQUEST}

Context:
- Sandbox ID: {SANDBOX_ID}
- Framework: {FRAMEWORK}
- Template: design-ux-template (includes mermaid-cli, graphviz, pa11y)
- User Request: {USER_REQUEST}
- Design System: {DESIGN_SYSTEM_STATUS}

Design System Access:
{IF_DESIGN_SYSTEM_AVAILABLE}
- Component Registry: /tmp/design-system/componentRegistry.json
- Design Tokens: /tmp/design-system/tokens.json
- Style Guide: /tmp/design-system/STYLES.md

IMPORTANT: Read these files first using mcp__bumba-sandbox__files_read to understand:
1. Available components and their interaction capabilities
2. Existing navigation patterns
3. Design constraints and brand guidelines

Build your UX spec by EXTENDING these components and patterns for the {DIRECTION} direction.
{ELSE_NO_DESIGN_SYSTEM}
No design system available. Design UX patterns from first principles for the {DIRECTION} direction.
{END_IF}

Phase 1 Task:
1. {IF_AVAILABLE} Read design system files to understand existing components
2. Explore {DIRECTION} UX approach (navigation, flows, interaction patterns)
3. Create flow diagrams using mermaid-cli if appropriate
4. Create /tmp/flow-spec.json with format:
   {
     "direction": "{DIRECTION}",
     "navigation": {"type": "...", "pattern": "...", "structure": "..."},
     "flows": [{"name": "...", "steps": [...], "branching": "..."}],
     "interactions": [{"action": "...", "pattern": "...", "feedback": "..."}],
     "information_architecture": {"categories": [...], "depth": N},
     "mental_model": "description"
   }
4. Write /tmp/phase1_complete.md when done

Direction Guidance for {DIRECTION}:
[See design-explore-ux skill for full guidance - read it now and insert appropriate section]

Use mcp__bumba-sandbox__files_write to create files in your sandbox {SANDBOX_ID}.
```

## Step 5: Monitor and Spawn Phase 2

Poll every 30 seconds using mcp__bumba-sandbox__file_exists to check for /tmp/phase1_complete.md in each sandbox.

When detected, spawn Phase 2 agent (design-prototyper) for that direction:

```
You are implementing the {DIRECTION} UX for: {USER_REQUEST}

Context:
- Sandbox ID: {SANDBOX_ID}
- Framework: {FRAMEWORK}
- Phase 1 Complete: /tmp/flow-spec.json available
- Template: design-ux-template (includes mermaid-cli, graphviz, pa11y for testing)

Phase 2 Task:
1. Read /tmp/flow-spec.json using mcp__bumba-sandbox__files_read
2. Implement production-grade {FRAMEWORK} code following the UX spec
3. Output all files to /tmp/output/ directory
4. Create any necessary flow diagrams with mermaid-cli
5. Run accessibility checks with pa11y if appropriate
6. Write /tmp/phase2_complete.md when done

Requirements:
- Production-ready code (no TODOs, no placeholders)
- Responsive design (mobile-first)
- WCAG AA accessibility minimum
- Real content (no Lorem ipsum)
- Complete interaction flows

Use mcp__bumba-sandbox__files_write for all files in {SANDBOX_ID}.
```

## Step 6: Auto-Sync Files (No Human Interaction Required)

**AUTOMATIC WORKFLOW**: As soon as phase2_complete.md is detected for ANY direction, immediately sync without asking:

For each completed direction:
1. List files: `mcp__bumba-sandbox__files_list(sandboxId, "/tmp/output")`
2. For EACH file in the list, in parallel:
   - Read: `mcp__bumba-sandbox__files_read(sandboxId, "/tmp/output/{file}")`
   - Write: `Write("worktrees/ux-{direction}/{file}", content)`
3. After sync complete, destroy sandbox: `mcp__bumba-sandbox__sandbox_kill(sandboxId)`
4. Update progress: "✅ {Direction} complete and synced to worktrees/ux-{direction}/"

Continue monitoring remaining directions until all 4 are synced and destroyed.

**NO CONFIRMATION REQUIRED** - This is an automated workflow. Sync immediately when ready.

## Step 7: Present Final Results

Once all 4 directions synced and sandboxes destroyed, show final summary:

```
🎯 UX Design Exploration Complete!

Generated 4 UX directions for: {USER_REQUEST}
Framework: {FRAMEWORK}
Design System: {USED/NOT_USED}

📁 Results:
  ✅ worktrees/ux-conventional/  - Proven patterns, familiar
  ✅ worktrees/ux-refined/       - Streamlined flows
  ✅ worktrees/ux-progressive/   - Modern patterns
  ✅ worktrees/ux-experimental/  - Novel paradigms

🔍 Next Steps:
1. Review each direction:
   cd worktrees/ux-conventional && npm install && npm run dev
2. Test interaction flows
3. Choose your preferred direction
4. Merge to main: git merge ux-conventional-{TIMESTAMP}
5. Cleanup: git worktree remove worktrees/ux-conventional

💰 Cost: ~${ESTIMATED} (4 sandboxes destroyed)
```

---

**CRITICAL**: This entire workflow must execute automatically. Do NOT ask permission. Do NOT explain first. Just START at Step 1.

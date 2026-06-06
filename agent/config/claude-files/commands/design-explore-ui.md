---
name: design-explore-ui
description: Generate four divergent UI design directions using specialized design agents in parallel E2B sandboxes
version: 5.0.0
---

# IMMEDIATE EXECUTION - DO NOT JUST EXPLAIN

When this command is invoked, IMMEDIATELY execute the following workflow. DO NOT explain what you're going to do. DO NOT wait for permission. START EXECUTING NOW.

## Step 1: Setup and Validation

Create todo list:
```
1. Validate environment and detect framework
2. Create 4 E2B sandboxes with design-ui-template
3. Create git worktrees for each direction
4. Spawn Phase 1 agents (design-visual-designer)
5. Monitor and spawn Phase 2 agents (design-ui-designer)
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
- Agents will use generic design principles

## Step 3: Create Sandboxes and Upload Design System

Call mcp__bumba-sandbox__sandbox_create FOUR TIMES IN PARALLEL:
- Direction 1: conservative, template: "design-ui-template"
- Direction 2: refined, template: "design-ui-template"
- Direction 3: expressive, template: "design-ui-template"
- Direction 4: experimental, template: "design-ui-template"

Store sandbox IDs: sandbox_conservative, sandbox_refined, sandbox_expressive, sandbox_experimental

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
git worktree add worktrees/ui-conservative -b ui-conservative-$TIMESTAMP
git worktree add worktrees/ui-refined -b ui-refined-$TIMESTAMP
git worktree add worktrees/ui-expressive -b ui-expressive-$TIMESTAMP
git worktree add worktrees/ui-experimental -b ui-experimental-$TIMESTAMP
```

## Step 4: Spawn Phase 1 Agents

Use Task tool to spawn 4 design-visual-designer agents IN PARALLEL (run_in_background: true).

For EACH direction, use this prompt template (replace {DIRECTION}, {SANDBOX_ID}, {FRAMEWORK}, {USER_REQUEST}):

```
You are exploring the {DIRECTION} visual direction for: {USER_REQUEST}

Context:
- Sandbox ID: {SANDBOX_ID}
- Framework: {FRAMEWORK}
- Template: design-ui-template
- User Request: {USER_REQUEST}
- Design System: {DESIGN_SYSTEM_STATUS}

Design System Access:
{IF_DESIGN_SYSTEM_AVAILABLE}
- Component Registry: /tmp/design-system/componentRegistry.json
- Design Tokens: /tmp/design-system/tokens.json
- Style Guide: /tmp/design-system/STYLES.md

IMPORTANT: Read these files first using mcp__bumba-sandbox__files_read to understand:
1. Available components and their variants
2. Design tokens (colors, spacing, typography, shadows)
3. Brand guidelines and visual principles

Build your design spec by EXTENDING and INTERPRETING these tokens for the {DIRECTION} direction.
Use existing components where appropriate, but feel free to suggest variations.
{ELSE_NO_DESIGN_SYSTEM}
No design system available. Create design decisions from first principles for the {DIRECTION} direction.
{END_IF}

Phase 1 Task:
1. {IF_AVAILABLE} Read design system files to understand existing patterns
2. Explore {DIRECTION} visual treatment (typography, color, spacing, atmosphere)
3. Create /tmp/design-spec.json with format:
   {
     "direction": "{DIRECTION}",
     "typography": {"primary": "font-name", "scale": [12,14,16,20,24,32,48], "weights": [400,600,700]},
     "colors": {"primary": "#hex", "accent": "#hex", "background": "#hex", "text": "#hex"},
     "spacing": {"base": 8, "scale": [4,8,16,24,32,48,64]},
     "shadows": ["0 1px 3px rgba(0,0,0,0.1)", ...],
     "atmosphere": "description",
     "design_system_used": true/false,
     "component_suggestions": ["component names from registry that fit this direction"]
   }
4. Write /tmp/phase1_complete.md when done

Direction Guidance for {DIRECTION}:
[See design-explore-ui skill for full guidance - read it now and insert appropriate section]

Use mcp__bumba-sandbox__files_write and files_read to work with files in sandbox {SANDBOX_ID}.
```

## Step 5: Monitor and Spawn Phase 2

Poll every 30 seconds using mcp__bumba-sandbox__file_exists to check for /tmp/phase1_complete.md in each sandbox.

When detected, spawn Phase 2 agent (design-ui-designer) for that direction:

```
You are implementing the {DIRECTION} UI for: {USER_REQUEST}

Context:
- Sandbox ID: {SANDBOX_ID}
- Framework: {FRAMEWORK}
- Phase 1 Complete: /tmp/design-spec.json available

Phase 2 Task:
1. Read /tmp/design-spec.json using mcp__bumba-sandbox__files_read
2. Implement production-grade {FRAMEWORK} code following the design spec
3. Output all files to /tmp/output/ directory
4. Write /tmp/phase2_complete.md when done

Requirements:
- Production-ready code (no TODOs, no placeholders)
- Responsive design (mobile-first)
- WCAG AA accessibility
- Real content (no Lorem ipsum)

Use mcp__bumba-sandbox__files_write for all files in {SANDBOX_ID}.
```

## Step 6: Auto-Sync Files (No Human Interaction Required)

**AUTOMATIC WORKFLOW**: As soon as phase2_complete.md is detected for ANY direction, immediately sync without asking:

For each completed direction:
1. List files: `mcp__bumba-sandbox__files_list(sandboxId, "/tmp/output")`
2. For EACH file in the list, in parallel:
   - Read: `mcp__bumba-sandbox__files_read(sandboxId, "/tmp/output/{file}")`
   - Write: `Write("worktrees/ui-{direction}/{file}", content)`
3. After sync complete, destroy sandbox: `mcp__bumba-sandbox__sandbox_kill(sandboxId)`
4. Update progress: "✅ {Direction} complete and synced to worktrees/ui-{direction}/"

Continue monitoring remaining directions until all 4 are synced and destroyed.

**NO CONFIRMATION REQUIRED** - This is an automated workflow. Sync immediately when ready.

## Step 7: Present Final Results

Once all 4 directions synced and sandboxes destroyed, show final summary:

```
🎨 UI Design Exploration Complete!

Generated 4 design directions for: {USER_REQUEST}
Framework: {FRAMEWORK}
Design System: {USED/NOT_USED}

📁 Results:
  ✅ worktrees/ui-conservative/  - Standard patterns, WCAG AA
  ✅ worktrees/ui-refined/       - Polished, elevated
  ✅ worktrees/ui-expressive/    - Bold personality
  ✅ worktrees/ui-experimental/  - Boundary-pushing

🔍 Next Steps:
1. Review each direction:
   cd worktrees/ui-conservative && npm install && npm run dev
2. Choose your preferred direction
3. Merge to main: git merge ui-conservative-{TIMESTAMP}
4. Cleanup: git worktree remove worktrees/ui-conservative

💰 Cost: ~${ESTIMATED} (4 sandboxes destroyed)
```

---

**CRITICAL**: This entire workflow must execute automatically. Do NOT ask permission. Do NOT explain first. Just START at Step 1.

---
description: Iteratively refine layout code using Ralph loops until 98%+ visual parity achieved
skill: design-layout-refine
autoInvoke: false
---

# Design Layout Refine

**YOU MUST EXECUTE THIS SKILL BY RUNNING THE EXECUTOR SCRIPT. DO NOT JUST DESCRIBE WHAT WILL HAPPEN.**

Iteratively refine layout code using Ralph loops with Playwright-based visual parity testing until achieving 98%+ visual similarity with Figma designs.

## Operating Modes

### 1. Handoff Mode (Recommended)
Automatically inherits context from `design-layout-to-*` skills after they complete.

**Trigger**: Run after `design-layout-to-*` when `.design/.refine-handoff.json` exists

**Usage**:
```bash
/design-layout-refine
```

### 2. Standalone Mode
Manual invocation with explicit parameters.

**Usage**:
```bash
/design-layout-refine --layout pricing-page --framework react --baseline .design/layouts/pricing-page/screenshot.png
```

## Workflow

This skill orchestrates the following process:

1. **Mode Detection**: Check for `.design/.refine-handoff.json` (handoff) or parse CLI args (standalone)
2. **Git Worktree**: Create isolated worktree at `worktrees/refine-<layout>-<timestamp>`
3. **Dev Server**: Auto-start framework-specific server (Next.js, Vite, or static)
4. **Ralph Loop**: Invoke `/ralph-loop` with refinement prompt
5. **Iteration**: Ralph continuously refines code, checking parity each iteration
6. **Completion**: When 98%+ parity achieved, Ralph outputs completion promise
7. **Commit**: Final commit on `refine/<layout>` branch with parity info
8. **Cleanup**: Stop dev server, return to main workspace
9. **Review**: User manually reviews worktree and merges if satisfied

## EXECUTION INSTRUCTIONS

**WHEN THIS SKILL IS INVOKED, YOU MUST:**

1. **Run the executor script immediately**:
   ```bash
   node server/design-layout-refine-executor.js [--layout=<name>] [--framework=<framework>] [--baseline=<path>] [--max-iterations=<n>]
   ```

2. **The executor will**:
   - Detect mode (handoff vs standalone)
   - Create git worktree
   - Start dev server
   - Generate Playwright test
   - Output the Ralph prompt

3. **After the executor completes, invoke Ralph loop**:
   - The executor will print the complete Ralph prompt
   - Copy the prompt and invoke: `/ralph-loop "<prompt>" --max-iterations N --completion-promise "VISUAL_PARITY_ACHIEVED"`

4. **Ralph will iteratively refine** until parity >= 98%

5. **After Ralph completes**:
   - Create final commit in worktree
   - Stop dev server
   - Inform user of merge instructions

**DO NOT skip the executor script. DO NOT manually implement the workflow. RUN THE SCRIPT.**

## What Claude Will Do

When you invoke this skill, Claude will:

### Phase 1: Setup (Automatic)
- Detect mode and load context
- Validate prerequisites (baseline exists, code exists, framework detected)
- Create git worktree: `worktrees/refine-<layout>-<timestamp>`
- Create and checkout branch: `refine/<layout>`
- Navigate into worktree
- Start dev server (Next.js on :3000, Vite on :5173, or static on :8080)

### Phase 2: Ralph Refinement Loop (Iterative)
Claude will be given this prompt by Ralph:

```
Refine layout code to achieve 98%+ visual parity with Figma baseline.

**Context**:
- Layout: <layout-name>
- Framework: <framework>
- Baseline Screenshot: <path-to-figma-screenshot>
- Generated Code: <path-to-code>
- Dev Server: http://localhost:<port>

**Iteration Workflow**:
1. Generate Playwright test for screenshot capture (headed mode)
2. Run Playwright test → capture current state screenshot
3. Compare current screenshot with Figma baseline
4. Calculate parity percentage using maxDiffPixelRatio: 0.02
5. If parity >= 98%: OUTPUT <promise>VISUAL_PARITY_ACHIEVED</promise>
6. If parity < 98%:
   - Analyze diff image to identify specific issues (spacing, alignment, colors, sizing)
   - Apply targeted fix to code
   - Update iteration notes
   - Continue to next iteration

**Critical Rules**:
- ONLY output the completion promise when parity is GENUINELY >= 98%
- Use Playwright in headed mode (visible browser) for real-time monitoring
- Make incremental, targeted fixes based on diff analysis
- Track iteration progress in `.design/.refine-session.json`
- Focus on visual accuracy, not code elegance

**Success Criteria**:
Visual parity >= 98% (maxDiffPixelRatio <= 0.02)
```

Ralph will loop this prompt until:
- Completion promise detected (`<promise>VISUAL_PARITY_ACHIEVED</promise>`), OR
- Max iterations reached (default: 15)

### Phase 3: Finalization (Automatic)
- Create final commit: `"Refined <layout> layout - <parity>% parity achieved"`
- Stop dev server and cleanup PID file
- Navigate back to main workspace
- Display completion message with worktree path and merge instructions

## User Responsibilities

After refinement completes:

1. **Review the Worktree**:
   ```bash
   cd worktrees/refine-<layout>-<timestamp>
   # Inspect the refined code
   # Check the parity report in .design/.refine-session.json
   ```

2. **Test the Refined Layout** (optional):
   ```bash
   # Start server manually if needed
   npm run dev
   # Verify visual appearance
   ```

3. **Merge to Main** (if satisfied):
   ```bash
   cd ../.. # Back to main workspace
   git checkout main
   git merge refine/<layout>
   ```

4. **Discard** (if not satisfied):
   ```bash
   git worktree remove worktrees/refine-<layout>-<timestamp>
   git branch -D refine/<layout>
   ```

## Technical Details

### State Files Created

1. **`.design/.refine-handoff.json`** (main workspace)
   - Created by `on-layout-transform-complete.js` hook
   - Contains layout name, framework, baseline path, current parity

2. **`worktrees/refine-<layout>/.design/.dev-server.json`** (in worktree)
   - Dev server PID, port, URL
   - Managed by `server/dev-server-manager.js`

3. **`worktrees/refine-<layout>/.design/.refine-session.json`** (in worktree)
   - Iteration history with parity progression
   - Final parity achieved, total time
   - Worktree path and branch name

4. **`.claude/ralph-loop.local.md`** (in worktree)
   - Ralph loop state (iteration counter, prompt, max iterations)
   - Managed by ralph-loop plugin

### Generated Playwright Tests

Location: `worktrees/refine-<layout>/.design/refinement-screenshots/`

Files:
- `<layout>-parity-check.spec.ts` - Playwright test
- `playwright.config.ts` - Test configuration
- `baseline.png` - Expected screenshot (copied from Figma)
- `test-results.json` - Playwright results (parsed for parity %)

### Framework Support

| Framework | Config File | Command | Port |
|-----------|-------------|---------|------|
| Next.js | next.config.js | npm run dev | 3000 |
| Vite | vite.config.js | npm run dev | 5173 |
| Static | *.html | npx http-server | 8080 |

Auto-detected by `server/dev-server-manager.js`

## Parameters

### Handoff Mode (no parameters needed)
```bash
/design-layout-refine
```

### Standalone Mode
```bash
/design-layout-refine \
  --layout <layout-name> \
  --framework <nextjs|vite|static> \
  --baseline <path-to-figma-screenshot> \
  [--max-iterations <number>] \
  [--route <url-route>]
```

**Parameters**:
- `--layout`: Layout name (e.g., "pricing-page")
- `--framework`: Target framework (auto-detected if not specified)
- `--baseline`: Path to Figma baseline screenshot
- `--max-iterations`: Max Ralph iterations (default: 15)
- `--route`: Dev server route (default: `/layouts/<layout-name>`)

## Examples

### Example 1: Handoff from design-layout-to-jsx
```bash
# Step 1: Transform layout (may not achieve perfect parity)
/design-layout-to-jsx --layout pricing-page

# Output: ⚠️ Parity: 92% | Run: /design-layout-refine

# Step 2: Refine with Ralph
/design-layout-refine

# Ralph iterates 5 times, achieves 98.4% parity
# Output: ✓ Refinement complete! Review in: worktrees/refine-pricing-page-20260111-143022

# Step 3: Review and merge
cd worktrees/refine-pricing-page-20260111-143022
git diff main  # Review changes
cd ../..
git merge refine/pricing-page
```

### Example 2: Standalone refinement
```bash
/design-layout-refine \
  --layout checkout-flow \
  --framework vite \
  --baseline .design/layouts/checkout-flow/screenshot.png \
  --max-iterations 20
```

### Example 3: Parallel refinements
```bash
# Terminal 1
/design-layout-refine --layout pricing-page

# Terminal 2 (simultaneously)
/design-layout-refine --layout dashboard

# Each runs in isolated worktree - no conflicts
```

## Troubleshooting

### Dev server fails to start
- Check if port is already in use: `lsof -i :<port>`
- Verify framework config exists (next.config.js, vite.config.js)
- Check npm dependencies installed: `npm install`

### Playwright tests fail
- Install dependencies: `npx playwright install chromium`
- Check route is accessible: `curl http://localhost:<port>/layouts/<layout>`
- Verify baseline screenshot exists

### Parity stuck below 98%
- Review diff image: `.design/refinement-screenshots/baseline.png-diff.png`
- Check iteration notes in `.design/.refine-session.json`
- Consider manual refinement if Ralph max iterations reached

### Worktree conflicts
- List worktrees: `git worktree list`
- Remove stale worktree: `git worktree remove <path>`
- Prune: `git worktree prune`

## Integration with design-layout-to-* Skills

The `on-layout-transform-complete.js` hook automatically offers Ralph refinement when `design-layout-to-*` skills complete with parity < 100%.

Hook watches: `.design/layouts/**/validation-report.json`

When triggered:
1. Extracts parity from validation report
2. If parity < 100%, creates `.design/.refine-handoff.json`
3. Displays: "⚠️ Parity: X% | Run: /design-layout-refine"

This creates a seamless handoff from initial transformation to iterative refinement.

## Performance Notes

- **Headed mode**: Browser visible for real-time monitoring (slightly slower)
- **Dev server**: Starts once, persists across iterations (efficient)
- **Playwright**: Screenshot comparison ~1-2 seconds per iteration
- **Typical iterations**: 3-8 iterations to reach 98% parity
- **Total time**: Usually 5-15 minutes depending on complexity

## See Also

- `/ralph-loop` - Underlying loop mechanism
- `/cancel-ralph` - Stop active Ralph loop
- `/design-layout-to-*` - Initial layout transformation skills
- `server/dev-server-manager.js` - Dev server lifecycle
- `server/parity-calculator.js` - Parity calculation

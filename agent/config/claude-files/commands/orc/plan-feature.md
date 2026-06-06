---
name: plan-feature
description: Generate step-by-step implementation plan (Implementation stage)
---

# /plan Command

Generates a detailed step-by-step implementation plan from a user prompt or issue specification.

**Pattern Source**: Adapted from agent-sandboxes `/plan` command

## Usage

```
/plan [<prompt>] [--issue <number>] [--save <filename>]
```

## Parameters

- `<prompt>` (optional): Free-form description of what to implement
- `--issue <number>` (optional): GitHub issue number to plan from
- `--save <filename>` (optional): Save plan to file (default: auto-generate)

## Workflow

### Step 1: Gather Requirements

1. **From User Prompt**:
   - If prompt provided, use it directly
   - Ask clarifying questions if needed
   - Extract key requirements and constraints

2. **From GitHub Issue**:
   - If `--issue` provided, fetch issue from GitHub
   - Extract title, description, acceptance criteria
   - Parse technical requirements

3. **Interactive Mode**:
   - If no prompt or issue, enter interactive mode
   - Ask: "What would you like to implement?"
   - Gather additional context through Q&A

### Step 2: Analyze Context

1. **Understand Codebase**:
   - Identify relevant files and modules
   - Detect framework and patterns in use
   - Identify existing similar implementations
   - Note coding conventions

2. **Identify Dependencies**:
   - External libraries needed
   - Internal modules that will be affected
   - API integrations required
   - Database schema changes

3. **Assess Complexity**:
   - Estimate implementation time
   - Identify potential challenges
   - Note areas requiring research

### Step 3: Generate Implementation Plan

Create detailed, numbered step-by-step plan:

```markdown
# Implementation Plan: [Feature Name]

**Issue**: #[number] (if applicable)
**Created**: [timestamp]
**Estimated Time**: [X hours/days]
**Complexity**: [Low/Medium/High]

---

## Overview

[2-3 sentence summary of what we're implementing and why]

---

## Prerequisites

- [ ] [Dependency 1]
- [ ] [Dependency 2]
- [ ] [Tool/library 3]

---

## Step-by-Step Implementation

### Phase 1: Setup & Preparation

#### Step 1: [Action]
**Goal**: [What this step achieves]
**Files**: [Files to modify/create]
**Commands**:
```bash
[commands to run]
```
**Expected Output**: [What success looks like]

#### Step 2: [Action]
**Goal**: [What this step achieves]
**Files**: [Files to modify/create]
**Code Changes**:
```typescript
// Add to src/example.ts
function example() {
  // implementation
}
```
**Expected Output**: [What success looks like]

[Continue with all steps...]

### Phase 2: Core Implementation

#### Step 3: [Action]
[Same structure as above]

#### Step 4: [Action]
[Same structure as above]

[Continue...]

### Phase 3: Testing & Validation

#### Step 10: Write Unit Tests
**Goal**: Ensure core functionality works correctly
**Files**: Create `src/__tests__/feature.test.ts`
**Test Cases**:
- [ ] Test case 1: [description]
- [ ] Test case 2: [description]
- [ ] Test case 3: [description]

#### Step 11: Write Integration Tests
**Goal**: Verify feature integrates with existing system
**Files**: Create `src/__tests__/integration/feature.test.ts`
**Test Scenarios**:
- [ ] Scenario 1: [description]
- [ ] Scenario 2: [description]

#### Step 12: Manual Testing
**Goal**: Verify user-facing functionality
**Test Steps**:
1. [Action to perform]
2. [Expected result]
3. [Action to perform]
4. [Expected result]

### Phase 4: Documentation & Cleanup

#### Step 13: Update Documentation
**Files**: Update `README.md`, `docs/api.md`
**Documentation Updates**:
- [ ] API documentation
- [ ] Usage examples
- [ ] Configuration options

#### Step 14: Code Review Prep
**Actions**:
- [ ] Run linter: `npm run lint`
- [ ] Format code: `npm run format`
- [ ] Verify tests pass: `npm test`
- [ ] Update CHANGELOG.md

---

## Acceptance Criteria

- [ ] [Criterion 1 from requirements]
- [ ] [Criterion 2 from requirements]
- [ ] [Criterion 3 from requirements]
- [ ] All tests pass
- [ ] Code is linted and formatted
- [ ] Documentation is updated

---

## Potential Challenges

### Challenge 1: [Description]
**Risk**: [Low/Medium/High]
**Mitigation**: [How to address]

### Challenge 2: [Description]
**Risk**: [Low/Medium/High]
**Mitigation**: [How to address]

---

## Alternative Approaches

### Approach 1: [Name]
**Pros**: [Advantages]
**Cons**: [Disadvantages]
**Verdict**: [Not selected because...]

### Approach 2: [Name]
**Pros**: [Advantages]
**Cons**: [Disadvantages]
**Verdict**: [Selected because...]

---

## Resources

- [Link to relevant documentation]
- [Link to similar implementation]
- [Link to API reference]

---

## Estimated Timeline

- Phase 1: [X hours]
- Phase 2: [Y hours]
- Phase 3: [Z hours]
- Phase 4: [W hours]
**Total**: [Sum hours]

---

## Next Steps

After completing this plan:
1. Review plan and make adjustments
2. Run `/build <plan-file>` to execute the plan
3. Or run `/wf_plan_build` to combine planning and execution
```

### Step 4: Save Plan

1. **Generate Filename**:
   - Default: `specs/plan-<issue>-<timestamp>.md`
   - Or use `--save` parameter value
   - Create `specs/` directory if needed

2. **Save to File**:
   - Write plan to specified location
   - Add to git (uncommitted)

3. **Display Summary**:
   ```
   ✅ Implementation Plan Created!

   📄 Plan Details:
     File:        specs/plan-42-20251118-143022.md
     Steps:       14 steps across 4 phases
     Estimated:   6-8 hours
     Complexity:  Medium

   📋 Next Steps:
     1. Review the plan and adjust as needed
     2. Run `/build specs/plan-42-20251118-143022.md` to execute
     3. Or combine: `/wf_plan_build <your-prompt>` for plan + build

   💡 Tips:
     - Plans are starting points - adjust as you learn
     - Break down large steps if needed
     - Add steps for edge cases you discover
   ```

## Examples

### Example 1: Plan from Prompt
```
/plan Add user authentication with OAuth2
```
Generates plan for implementing OAuth2 authentication.

### Example 2: Plan from GitHub Issue
```
/plan --issue 42
```
Creates plan based on GitHub issue #42 requirements.

### Example 3: Plan with Custom Save Location
```
/plan Implement caching layer --save docs/cache-plan.md
```
Saves plan to specified file.

### Example 4: Interactive Planning
```
/plan
```
Enters interactive mode to gather requirements.

## Plan Structure

Plans follow this consistent structure:
1. **Overview**: Summary and context
2. **Prerequisites**: Setup requirements
3. **Phases**: Logical groupings of steps
4. **Steps**: Detailed, actionable items with:
   - Goal
   - Files affected
   - Commands or code changes
   - Expected outcomes
5. **Testing**: Comprehensive test coverage
6. **Documentation**: Updates needed
7. **Challenges**: Risks and mitigations
8. **Alternatives**: Other approaches considered

## Plan Quality Guidelines

Good plans have:
- **Specific Steps**: Each step is clear and actionable
- **Reasonable Scope**: Steps take 15-60 minutes each
- **Clear Goals**: Each step has a defined outcome
- **Test Coverage**: Testing is integrated throughout
- **Error Handling**: Edge cases are considered
- **Documentation**: Updates are planned

## Use with /build Command

Plans are designed to be executed with `/build`:

```bash
# Create plan
/plan --issue 42

# Review and execute
/build specs/plan-42-20251118-143022.md
```

Or combine both:
```bash
/wf_plan_build Add user authentication
```

## Configuration

Configure in `.claude/config/bumba-sandbox-config.json`:
- `plan.defaultSaveDir`: Default directory for plans (default: `specs/`)
- `plan.includeAlternatives`: Include alternative approaches (default: true)
- `plan.includeTimeline`: Include time estimates (default: true)
- `plan.detailLevel`: Step detail level (concise/standard/detailed)

## Notes

- Plans are living documents - update as you learn
- Good plans reduce implementation time and bugs
- Break complex features into multiple smaller plans
- Reference existing code patterns in your plan
- Plans can be version controlled for future reference
- Use plans to communicate approach before implementation
- Combine with `/build` for plan-driven development

---
name: create-issues
description: Create GitHub issues from sprint plan (Specification stage)
---

# /create-specifications Command

Creates GitHub issues from sprint plan or PRD, automatically detecting dependencies and applying appropriate labels.

## Usage

```
/create-specifications [--source <file>] [--dry-run] [--batch-size <n>]
```

## Parameters

- `--source <file>` (optional): Source file to parse (default: `docs/prd/sprints.md`)
- `--dry-run` (optional): Preview issues without creating them
- `--batch-size <n>` (optional): Create N issues at a time (default: all)

## Workflow

### Step 1: Read Sprint Plan

1. **Locate Source Document**:
   - Default: `docs/prd/sprints.md`
   - Alternative: PRD file specified with --source
   - Verify file exists and is readable

2. **Parse Sprint Structure**:
   - Identify sprint sections (Sprint 1, Sprint 2, etc.)
   - Extract sprint objectives and timeline
   - Identify features/stories within each sprint
   - Parse feature descriptions and requirements

Expected sprint plan format:
```markdown
# Development Sprint Plan

## Sprint 1: Foundation (Week 1-2)

### Feature 1.1: User Authentication
**Description**: Implement OAuth2 authentication with Google and GitHub providers.

**Requirements**:
- Support Google OAuth2 login
- Support GitHub OAuth2 login
- Store user sessions securely
- Handle token refresh

**Acceptance Criteria**:
- [ ] Users can login with Google
- [ ] Users can login with GitHub
- [ ] Sessions persist across page refreshes
- [ ] Tokens refresh automatically before expiration

**Estimated Effort**: 8 story points
**Labels**: backend, authentication, P0

### Feature 1.2: User Profile
**Description**: Basic user profile page showing user information.

**Dependencies**: Feature 1.1 (User Authentication must be complete)

**Requirements**:
- Display user name and email
- Display user avatar
- Allow user to logout

**Acceptance Criteria**:
- [ ] Profile page shows correct user data
- [ ] Avatar displays correctly
- [ ] Logout button works

**Estimated Effort**: 3 story points
**Labels**: frontend, ui, P1
```

### Step 2: Extract Feature Information

For each feature, I'll extract:

1. **Basic Information**:
   - Feature number (e.g., 1.1, 1.2)
   - Feature title
   - Description
   - Sprint assignment

2. **Requirements**:
   - Functional requirements
   - Non-functional requirements
   - Technical constraints

3. **Acceptance Criteria**:
   - Specific, testable conditions
   - User-facing validation points

4. **Dependencies**:
   - Look for "Depends on Feature X.Y" or "Blocked by Feature X.Y"
   - Look for "Requires #X" (existing issue numbers)
   - Extract dependency relationships

5. **Metadata**:
   - Story points or complexity estimate
   - Labels (auto-detect from content + explicit labels)
   - Priority (P0, P1, P2)
   - Assignee (if specified)

### Step 3: Auto-Detect Additional Metadata

I'll analyze feature content to auto-apply labels:

**Label Detection Rules**:
- Contains "database", "migration", "schema" → `database`
- Contains "API", "endpoint", "REST" → `backend`, `api`
- Contains "UI", "component", "styling" → `frontend`, `ui`
- Contains "test", "coverage" → `testing`
- Contains "docs", "documentation" → `documentation`
- Contains "security", "authentication", "authorization" → `security`
- Contains "performance", "optimization" → `performance`
- Contains "bug", "fix" → `bug`
- Contains "refactor" → `refactoring`

**Priority Detection**:
- Marked "P0" or "critical" or "must-have" → `P0`
- Marked "P1" or "important" or "should-have" → `P1`
- Marked "P2" or "nice-to-have" → `P2`
- Default: `P1`

**Complexity Estimation**:
- Story points < 3 → "Small"
- Story points 3-8 → "Medium"
- Story points 9-13 → "Large"
- Story points > 13 → "Extra Large"

### Step 4: Build Dependency Graph

1. **Parse Dependencies**:
   - Extract all "Depends on" statements
   - Map feature numbers to issue numbers (after creation)
   - Build dependency graph

2. **Detect Circular Dependencies**:
   - Run cycle detection algorithm
   - If circular dependencies found, warn user and abort
   - Display circular dependency chain

3. **Calculate Creation Order**:
   - Topological sort of dependency graph
   - Create issues in dependency order
   - Ensures dependency issue numbers exist before referencing them

### Step 5: Preview Issues (Dry-Run or Confirmation)

Before creating, show preview:

```
📋 Issue Creation Preview
═══════════════════════════════════════════════

Total Features: 12
Total Sprints: 3

Sprint 1 (6 features):
  ✓ #1: User Authentication [P0, backend, auth] (8 pts)
  ✓ #2: User Profile [P1, frontend, ui] (3 pts) → Depends on #1
  ✓ #3: Database Schema [P0, database] (5 pts)
  ✓ #4: API Endpoints [P0, backend, api] (8 pts) → Depends on #1, #3
  ✓ #5: Frontend Components [P1, frontend, ui] (5 pts)
  ✓ #6: Integration Tests [P1, testing] (3 pts) → Depends on #4, #5

Sprint 2 (4 features):
  ✓ #7: Advanced Search [P1, backend, api] (8 pts)
  ✓ #8: Search UI [P1, frontend, ui] (5 pts) → Depends on #7
  ✓ #9: Performance Optimization [P2, performance] (5 pts)
  ✓ #10: Documentation [P2, docs] (3 pts)

Sprint 3 (2 features):
  ✓ #11: Analytics Dashboard [P1, frontend, ui] (13 pts)
  ✓ #12: Admin Panel [P2, frontend, backend] (13 pts)

Labels to be created:
  - backend
  - frontend
  - database
  - api
  - ui
  - testing
  - performance
  - documentation
  - P0, P1, P2
  - auth

Dependency Graph:
  #1 (no deps)
  #2 → #1
  #3 (no deps)
  #4 → #1, #3
  #5 (no deps)
  #6 → #4, #5
  #7 (no deps)
  #8 → #7
  #9 (no deps)
  #10 (no deps)
  #11 (no deps)
  #12 (no deps)

Ready to create? (yes/no)
```

### Step 6: Create GitHub Issues

1. **Create Issues in Dependency Order**:
   - Process features in topological order
   - For each feature:
     - Format issue title: `[Sprint X.Y] Feature Title`
     - Format issue body with all sections
     - Apply labels
     - Add dependencies in body as "Depends on #X"
     - Create issue via GitHub API
     - Store mapping of feature number → issue number

2. **Issue Body Format**:
   ```markdown
   ## Description
   [Feature description]

   ## Requirements
   - [Requirement 1]
   - [Requirement 2]

   ## Acceptance Criteria
   - [ ] [Criterion 1]
   - [ ] [Criterion 2]

   ## Dependencies
   Depends on #X, #Y

   ## Sprint
   Sprint N: [Sprint objective] (Week X-Y)

   ## Estimated Effort
   [Story points] story points ([Complexity])

   ## Technical Notes
   [Any technical notes from PRD]

   ---
   *Auto-generated from PRD by E2B Orchestrator*
   ```

3. **Handle Failures**:
   - If issue creation fails, retry once
   - If still fails, log error and continue
   - Report failures at the end
   - Save partial progress (issues created so far)

### Step 7: Update Issues with Dependencies

After all issues are created:

1. **Update Dependency References**:
   - For each issue with dependencies
   - Update issue body with actual issue numbers
   - Use GitHub API to update issue

2. **Create Issue Links** (if GitHub supports it):
   - Use GitHub's issue linking feature
   - Create "blocks" relationships

### Step 8: Generate Summary Report

```
✅ Specifications Created Successfully!

📊 Summary:
═══════════════════════════════════════════════

Total Issues Created: 12
Total Sprints: 3
Total Story Points: 85

Issues by Sprint:
  Sprint 1: 6 issues (32 story points)
  Sprint 2: 4 issues (21 story points)
  Sprint 3: 2 issues (26 story points)

Issues by Priority:
  P0: 4 issues
  P1: 6 issues
  P2: 2 issues

Issues by Label:
  backend: 5 issues
  frontend: 6 issues
  database: 1 issue
  testing: 1 issue

Dependency Relationships: 4 dependencies created

📋 Next Steps:
  1. Review issues on GitHub: https://github.com/owner/repo/issues
  2. Use /implement-feature #1 to start first issue
  3. Use /parallel-implement-features #1 #3 #5 for parallel work
  4. Use /show-status to monitor progress

💡 Ready to Start:
  These issues have no dependencies and can start immediately:
    #1: User Authentication
    #3: Database Schema
    #5: Frontend Components
    #7: Advanced Search
    #9: Performance Optimization
    #10: Documentation
    #11: Analytics Dashboard
    #12: Admin Panel

⏳ Blocked Issues:
  These issues are waiting on dependencies:
    #2: User Profile (blocked by #1)
    #4: API Endpoints (blocked by #1, #3)
    #6: Integration Tests (blocked by #4, #5)
    #8: Search UI (blocked by #7)
```

## Examples

### Example 1: Create from Default Sprint Plan
```
/create-specifications
```
Reads `docs/prd/sprints.md` and creates issues.

### Example 2: Preview Without Creating
```
/create-specifications --dry-run
```
Shows what would be created without actually creating issues.

### Example 3: Create from Custom File
```
/create-specifications --source docs/features.md
```
Creates issues from specified file.

### Example 4: Create in Batches
```
/create-specifications --batch-size 5
```
Creates 5 issues, waits for confirmation, then continues.

## Error Handling

- **File Not Found**: I'll ask for the correct file path
- **Parse Error**: I'll show which section failed to parse
- **Circular Dependencies**: I'll show the cycle and abort
- **GitHub API Error**: I'll retry and report failures
- **Rate Limit**: I'll wait and retry automatically

## Configuration

Configure in `.claude/config/bumba-sandbox-config.json`:
- `specs.defaultSource`: Default source file
- `specs.autoLabels`: Enable/disable auto-label detection
- `specs.createDraft`: Create issues as drafts
- `specs.defaultPriority`: Default priority if not specified

## GitHub API Requirements

Requires GitHub Personal Access Token with permissions:
- `repo` - Create issues
- `write:discussion` - Add labels and assignees

Set via environment variable:
```bash
export GITHUB_TOKEN="<github-token>"
```

**Integration**: This command uses the GitHub API wrapper from Phase 2 (`/home/operator/Bumba-Sandbox-MCP/src/mcp-servers/github.ts`) and can optionally call `analyze_dependencies` MCP tool to validate the dependency graph after issue creation.

## Notes

- Issues are created in dependency order to ensure proper references
- Circular dependencies will block creation - fix them first
- Auto-detected labels may need review/refinement
- Issue numbers are sequential, so dependencies reference correct issues
- Use `--dry-run` first to preview before creating
- Created issues are immediately ready for `/implement-feature`
- The dependency graph enables `/parallel-implement-features` orchestration

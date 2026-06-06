---
name: plan-sprints
description: Break PRD into sprint-sized chunks (Specification stage)
---

# /plan-development-sprints Command

Automatically generates a structured sprint plan from a Product Requirements Document (PRD), organizing features into time-boxed sprints with proper prioritization and dependencies.

## Usage

```
/plan-development-sprints [--source <file>] [--sprint-length <weeks>] [--team-size <n>]
```

## Parameters

- `--source <file>` (optional): Path to PRD file (default: `docs/prd/main.md`)
- `--sprint-length <weeks>` (optional): Sprint duration in weeks (default: 2)
- `--team-size <n>` (optional): Team size for velocity calculation (default: 3)
- `--output <file>` (optional): Output file path (default: `docs/prd/sprints.md`)
- `--interactive` (optional): Enable interactive mode for manual adjustments

## Workflow

### Step 1: Read and Parse PRD

1. **Locate PRD File**:
   - Default location: `docs/prd/main.md`
   - Can be overridden with --source flag
   - Verify file exists and is readable

2. **Parse PRD Structure**:
   - Extract product vision and goals
   - Identify high-level features from PRD sections
   - Parse feature descriptions and requirements
   - Extract user stories if present
   - Identify success metrics

**Expected PRD Format**:
```markdown
# Product Requirements Document

## Product Vision
[Vision statement]

## Goals
- Goal 1
- Goal 2

## Features

### Feature 1: User Authentication
**Description**: Comprehensive auth system with OAuth support

**Requirements**:
- Google OAuth2 integration
- GitHub OAuth2 integration
- Session management
- Token refresh mechanism

**User Stories**:
- As a user, I want to login with Google
- As a user, I want to login with GitHub

**Success Metrics**:
- 90%+ of users can authenticate successfully
- Average login time < 3 seconds

### Feature 2: User Profile Management
**Description**: User profile page with editable fields

**Depends On**: Feature 1 (User Authentication)

**Requirements**:
- Display user information
- Avatar upload
- Profile editing
- Privacy settings
```

3. **Extract Feature Information**:
   For each feature, extract:
   - Feature title and description
   - Requirements list
   - User stories
   - Dependencies ("Depends On" statements)
   - Success metrics
   - Complexity indicators (length, technical terms)

### Step 2: Analyze and Estimate Complexity

1. **Estimate Story Points**:
   Use heuristics to estimate complexity (1-13 point scale):

   **Complexity Indicators**:
   - Number of requirements: +1-3 points
   - Number of user stories: +1-2 points
   - Technical keywords: +1-5 points
     - "authentication", "security" → +2 points
     - "real-time", "websockets" → +3 points
     - "database", "migration" → +2 points
     - "API", "integration" → +1 point
     - "UI", "component" → +1 point
   - Dependencies: +1 point per dependency
   - Description length: +1-2 points

   **Story Point Scale**:
   - 1-2 points: Trivial (< 4 hours)
   - 3-5 points: Small (1-2 days)
   - 8 points: Medium (3-5 days)
   - 13 points: Large (1-2 weeks)
   - 20+ points: Too large, needs splitting

2. **Display Complexity Analysis**:
   ```
   📊 Feature Complexity Analysis
   ═══════════════════════════════════════════════

   Feature 1: User Authentication
     Requirements: 4 → +2 points
     Keywords: auth, security, OAuth → +3 points
     Description: detailed → +2 points
     Dependencies: 0 → +0 points
     ───────────────────────
     Estimated: 8 story points (Medium)

   Feature 2: User Profile Management
     Requirements: 4 → +2 points
     Keywords: UI, profile → +2 points
     Description: moderate → +1 point
     Dependencies: 1 → +1 point
     ───────────────────────
     Estimated: 5 story points (Small)

   ...

   Total Features: 12
   Total Story Points: 89
   ```

3. **Identify Features Needing Splitting**:
   - Features > 13 points should be split
   - Suggest logical split points
   - Ask user if they want to split automatically

   ```
   ⚠️  Large Features Detected

   Feature 5: Analytics Dashboard (21 points)
     This feature is too large for a single sprint.

   Suggested Split:
     Feature 5a: Analytics Data Collection (8 points)
     Feature 5b: Analytics Dashboard UI (8 points)
     Feature 5c: Analytics Reports (5 points)

   Accept suggested split? (yes/no)
   ```

### Step 3: Identify and Validate Dependencies

1. **Extract Dependencies**:
   - Parse "Depends On" statements in PRD
   - Parse "Requires" statements
   - Parse "Blocked By" statements
   - Build dependency graph

2. **Validate Dependencies**:
   - Ensure all referenced features exist
   - Detect circular dependencies
   - Warn about missing features

   ```
   🔗 Dependency Validation
   ═══════════════════════════════════════════════

   ✓ Feature 2 depends on Feature 1 (valid)
   ✓ Feature 4 depends on Feature 1, Feature 3 (valid)
   ✓ Feature 6 depends on Feature 4 (valid)

   ⚠️  Feature 8 depends on "Email Service"
       Warning: "Email Service" not found in PRD
       Create Feature 7.5: Email Service? (yes/no)

   ✓ All dependencies validated
   ✓ No circular dependencies detected
   ```

3. **Topological Sort**:
   - Order features by dependencies
   - Features with no dependencies first
   - Dependent features after their prerequisites
   - Multiple valid orderings possible

### Step 4: Calculate Sprint Capacity

1. **Determine Velocity**:
   ```
   📈 Sprint Capacity Calculation
   ═══════════════════════════════════════════════

   Team Size: 3 developers
   Sprint Length: 2 weeks (10 working days)
   Estimated Velocity: 24 story points per sprint

   Calculation:
     Base velocity per dev: 8 points/sprint
     Team velocity: 3 devs × 8 = 24 points/sprint

   Note: First sprint often has lower velocity (16-20 points)
         due to setup and onboarding.
   ```

2. **Adjust for Risk and Overhead**:
   - Subtract 15% for meetings, code review, etc.
   - Subtract 10% for unexpected issues
   - Round down to nearest story point

   ```
   Adjusted Velocity:
     Base: 24 points
     Meetings/overhead (-15%): -3.6 points
     Risk buffer (-10%): -2.4 points
     ─────────────────────────
     Final: 18 points per sprint
   ```

### Step 5: Organize Features into Sprints

1. **Prioritization Rules**:
   - **P0 (Critical)**: Must be in earliest sprints
   - **Dependencies**: Prerequisite features first
   - **Foundation First**: Infrastructure before features
   - **Value Stream**: Group related features together
   - **Risk**: High-risk features early for validation

2. **Sprint Assignment Algorithm**:
   ```
   Sprint Planning Algorithm:
   ─────────────────────────────────────────────────

   For each sprint:
     1. Start with capacity: 18 points
     2. Select highest-priority feature with satisfied dependencies
     3. Add to sprint if it fits capacity
     4. Reduce remaining capacity
     5. Repeat until capacity exhausted or no features fit
     6. Move to next sprint

   Special Rules:
     - Foundation features (auth, db) → Sprint 1
     - P0 features → earliest possible sprint
     - Related features → same or adjacent sprints
     - Large features → dedicated sprint if needed
   ```

3. **Generate Sprint Plan**:
   ```
   📅 Sprint Plan
   ═══════════════════════════════════════════════

   Sprint 1: Foundation (Weeks 1-2)
   ─────────────────────────────────────────────────
   Capacity: 18 points | Allocated: 17 points (94%)

   1.1 Feature 1: User Authentication (8 pts) [P0]
   1.2 Feature 3: Database Schema (5 pts) [P0]
   1.3 Feature 5: API Foundation (4 pts) [P0]

   Goal: Establish core authentication and data infrastructure
   Dependencies: None (foundation sprint)
   Deliverables: Working auth, database, basic API

   Sprint 2: Core Features (Weeks 3-4)
   ─────────────────────────────────────────────────
   Capacity: 18 points | Allocated: 18 points (100%)

   2.1 Feature 2: User Profile (5 pts) [P1] → depends on 1.1
   2.2 Feature 4: API Endpoints (8 pts) [P0] → depends on 1.1, 1.2
   2.3 Feature 7: Frontend Components (5 pts) [P1]

   Goal: Build core user-facing features
   Dependencies: Sprint 1 complete
   Deliverables: Profile pages, API endpoints, UI components

   Sprint 3: Integration (Weeks 5-6)
   ─────────────────────────────────────────────────
   Capacity: 18 points | Allocated: 16 points (89%)

   3.1 Feature 6: Integration Tests (3 pts) [P1] → depends on 2.1, 2.2
   3.2 Feature 8: Search Feature (8 pts) [P1]
   3.3 Feature 9: Email Notifications (5 pts) [P2]

   Goal: Integrate features and add search capabilities
   Dependencies: Sprint 2 complete for 3.1
   Deliverables: E2E tests, search, notifications

   ...

   Total Sprints: 5
   Total Duration: 10 weeks
   Total Story Points: 89
   ```

### Step 6: Add Sprint Details

For each sprint, generate:

1. **Sprint Objective**: High-level goal
2. **Feature Details**: Requirements, acceptance criteria
3. **Dependencies**: What must be complete first
4. **Deliverables**: What will be delivered
5. **Risks**: Potential blockers or challenges
6. **Success Criteria**: How to measure sprint success

**Example Sprint Detail**:
```markdown
## Sprint 1: Foundation (Weeks 1-2)

**Objective**: Establish core authentication and data infrastructure to enable all subsequent features.

**Capacity**: 18 story points | **Allocated**: 17 points (94%)

---

### Feature 1.1: User Authentication (8 story points) [P0]

**Description**: Implement comprehensive OAuth2 authentication with Google and GitHub providers, session management, and token refresh mechanisms.

**Requirements**:
- Support Google OAuth2 login flow
- Support GitHub OAuth2 login flow
- Store user sessions securely in database
- Implement token refresh before expiration
- Handle authentication errors gracefully

**Acceptance Criteria**:
- [ ] Users can successfully login with Google
- [ ] Users can successfully login with GitHub
- [ ] Sessions persist across page refreshes
- [ ] Tokens refresh automatically before expiration
- [ ] Clear error messages for authentication failures
- [ ] 90%+ success rate for authentication attempts

**Estimated Effort**: 8 story points (3-5 days)

**Dependencies**: None

**Labels**: backend, authentication, security, P0

**Technical Notes**:
- Use Passport.js for OAuth integration
- Store sessions in Redis for performance
- Implement JWT for API authentication
- Add rate limiting to prevent abuse

**Risks**:
- OAuth provider rate limits
- Token refresh edge cases
- Session storage scalability

---

### Feature 1.2: Database Schema (5 story points) [P0]

**Description**: Design and implement core database schema for users, sessions, and application data with proper indexing and relationships.

...
```

### Step 7: Generate Output File

1. **Create Sprint Plan Document**:
   - Write to `docs/prd/sprints.md` (or --output path)
   - Include table of contents
   - Include timeline visualization
   - Include dependency diagram
   - Include risk assessment

2. **Add Executive Summary**:
   ```markdown
   # Development Sprint Plan

   **Generated**: 2025-11-18
   **Based On**: docs/prd/main.md
   **Team Size**: 3 developers
   **Sprint Length**: 2 weeks
   **Total Sprints**: 5
   **Total Duration**: 10 weeks
   **Total Story Points**: 89

   ## Quick Summary

   | Sprint | Dates | Features | Points | Focus Area |
   |--------|-------|----------|--------|------------|
   | Sprint 1 | Weeks 1-2 | 3 | 17 | Foundation |
   | Sprint 2 | Weeks 3-4 | 3 | 18 | Core Features |
   | Sprint 3 | Weeks 5-6 | 3 | 16 | Integration |
   | Sprint 4 | Weeks 7-8 | 2 | 18 | Advanced Features |
   | Sprint 5 | Weeks 9-10 | 1 | 20 | Polish & Launch |

   ## Dependency Flow

   ```
   Sprint 1: [1.1] [1.2] [1.3]
                ↓     ↓     ↓
   Sprint 2: [2.1] [2.2] [2.3]
                ↓  ↙
   Sprint 3: [3.1] [3.2] [3.3]
   ...
   ```

   ## Risk Assessment

   - **High Risk**: Feature 1.1 (authentication) - critical path
   - **Medium Risk**: Feature 4.1 (real-time features) - technical complexity
   - **Low Risk**: Feature 5.1 (polish) - optional enhancements
   ```

3. **Display Completion Message**:
   ```
   ✅ Sprint Plan Generated!

   📄 Output: docs/prd/sprints.md
   📊 Summary:
   ═══════════════════════════════════════════════

   Total Features: 12
   Total Sprints: 5
   Total Duration: 10 weeks
   Total Story Points: 89

   Sprint Breakdown:
     Sprint 1 (Foundation): 17 points, 3 features
     Sprint 2 (Core Features): 18 points, 3 features
     Sprint 3 (Integration): 16 points, 3 features
     Sprint 4 (Advanced): 18 points, 2 features
     Sprint 5 (Launch): 20 points, 1 feature

   Next Steps:
     1. Review sprint plan in docs/prd/sprints.md
     2. Adjust sprint assignments if needed
     3. Run /create-specifications to create GitHub issues
     4. Run /parallel-implement-features to start implementation
   ```

## Examples

### Example 1: Basic Sprint Planning
```
/plan-development-sprints
```
Reads `docs/prd/main.md` and generates sprint plan with default settings (2-week sprints, 3-person team).

### Example 2: Custom PRD Location
```
/plan-development-sprints --source docs/product-spec.md
```
Reads custom PRD file and generates sprint plan.

### Example 3: Shorter Sprints
```
/plan-development-sprints --sprint-length 1
```
Generates plan with 1-week sprints (more frequent milestones).

### Example 4: Larger Team
```
/plan-development-sprints --team-size 5
```
Adjusts velocity calculation for 5-person team (~40 points/sprint).

### Example 5: Interactive Mode
```
/plan-development-sprints --interactive
```
Allows manual adjustments to sprint assignments before saving.

## Sprint Planning Best Practices

### Sprint Length Guidelines

**1-Week Sprints**:
- Pros: Frequent feedback, faster iteration
- Cons: Higher overhead, less time for complex features
- Best for: Small teams, early-stage projects

**2-Week Sprints** (Recommended):
- Pros: Balanced overhead and progress
- Cons: None significant
- Best for: Most projects

**3-Week+ Sprints**:
- Pros: More time for complex features
- Cons: Less frequent feedback, risk of scope creep
- Best for: Highly technical projects

### Capacity Planning

**Conservative Approach** (Recommended):
- Use 70-80% of theoretical velocity
- Accounts for unknowns and interruptions
- Reduces sprint failure rate

**Aggressive Approach**:
- Use 90-100% of theoretical velocity
- Higher risk of incomplete sprints
- Only for experienced teams

### Feature Prioritization

**P0 (Critical)**:
- Must-have for MVP
- Foundation features
- Security and compliance

**P1 (Important)**:
- Should-have for good user experience
- Competitive features
- Performance and quality

**P2 (Nice-to-have)**:
- Could be deferred to v2
- Polish and enhancements
- Advanced features

## Error Handling

**PRD File Not Found**:
```
❌ Error: PRD file not found

Path: docs/prd/main.md

Please create a PRD first using /create-product-requirements
```

**Empty or Invalid PRD**:
```
❌ Error: No features found in PRD

The PRD must contain feature descriptions.
Minimum format:

## Features
### Feature 1: Title
Description...
```

**Circular Dependencies**:
```
❌ Error: Circular dependency detected

Dependency chain:
  Feature 1 depends on Feature 2
  Feature 2 depends on Feature 3
  Feature 3 depends on Feature 1

Fix dependencies in PRD before planning sprints.
```

**Excessive Features**:
```
⚠️  Warning: Large project detected

Total Features: 45
Total Story Points: 320
Estimated Duration: 36 weeks (9 months)

Consider:
  1. Splitting into phases (MVP, v1.1, v2.0)
  2. Reducing scope to core features only
  3. Increasing team size

Continue anyway? (yes/no)
```

## Configuration

Configure in `.claude/config/bumba-sandbox-config.json`:

```json
{
  "sprints": {
    "defaultLength": 2,
    "defaultTeamSize": 3,
    "velocityPerDev": 8,
    "overheadFactor": 0.15,
    "riskBuffer": 0.10,
    "autoSplit": true,
    "splitThreshold": 13
  }
}
```

**Options**:
- `defaultLength`: Default sprint length in weeks
- `defaultTeamSize`: Default team size
- `velocityPerDev`: Story points per developer per sprint
- `overheadFactor`: Percentage reduction for overhead
- `riskBuffer`: Percentage reduction for risk
- `autoSplit`: Automatically split large features
- `splitThreshold`: Story point threshold for splitting

## Integration

**Before Sprint Planning**:
1. `/create-product-requirements` - Create comprehensive PRD

**After Sprint Planning**:
1. `/create-specifications` - Create GitHub issues from sprint plan
2. `/parallel-implement-features` - Implement sprint features
3. `/show-status` - Monitor sprint progress

## Notes

- Sprint planning is iterative - adjust as you learn
- Velocity improves over time as team matures
- First sprint often has lower velocity due to setup
- Dependencies can shift sprint timelines
- Buffer time is critical for realistic planning
- Story point estimation improves with practice
- Consider team availability (vacations, holidays)
- Review and adjust plan after each sprint (retrospective)
- Sprint plan is a living document - update as needed
- Use interactive mode for fine-tuning sprint assignments

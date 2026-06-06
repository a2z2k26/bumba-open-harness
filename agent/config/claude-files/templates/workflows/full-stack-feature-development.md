# Workflow: Full-Stack Feature Development

End-to-end workflow from requirements to deployed feature.

## Phase 1: Planning & Design (Product Strategy + Design)

### 1. Feature Specification
```bash
/design-director:vision
```
Interactive prompts for feature vision and requirements.

**Output**: `product-overview.md`

### 2. Requirements Gathering
```bash
/orc:requirements
```
Multi-agent requirements from product, user, and technical perspectives.

**Output**: `requirements.md`

### 3. UI/UX Design
```bash
/design-explore-ui
```
Generates 4 UI directions in parallel E2B sandboxes.
Select preferred direction for implementation.

**Output**: 4 git worktrees with implementations

## Phase 2: Development (Engineering)

### 4. Backend Architecture
```javascript
Task({
  subagent_type: "engineering-backend-architect",
  description: "Design authentication API",
  prompt: "Design authentication system with JWT. Requirements: [list from requirements.md]"
})
```

**Output**: Architecture design document

### 5. API Implementation
```bash
/code:execute
```
Implements backend based on architecture design.

**Output**: Backend code in `src/api/`

### 6. Frontend Implementation
Already completed from design phase (design-explore-ui).
Merge selected UI direction:
```bash
cd worktrees/ui-[selected-direction]
git merge [branch-name]
```

### 7. Integration
Connect frontend to backend API.
Update API endpoints in frontend code.

## Phase 3: Quality Assurance (QA/Testing)

### 8. Comprehensive Testing
```bash
/testing:feature
```
Runs unit, integration, and E2E tests for the feature.

**Duration**: Depends on feature complexity

### 9. Code Review
```bash
/gh:create-pr
```
Creates PR with AI-generated description from commits.

```bash
/gh:review-pr
```
Multi-agent code review (security, performance, best practices).

**Output**: Review comments in PR

### 10. Address Feedback
```bash
/gh:address-feedback
```
Systematically addresses all PR review comments.

## Phase 4: Deployment (Operations)

### 11. Merge & Deploy
```bash
/gh:merge-pr
```
Merges to main and triggers CI/CD pipeline (via GitHub Actions).

### 12. Monitor Deployment
```bash
/project:status
```
Check deployment metrics and health.

## Full Workflow Duration

- **Planning & Design**: 20-30 minutes
- **Development**: 1-3 hours (depends on complexity)
- **QA & Review**: 15-30 minutes
- **Deployment**: 5-10 minutes

**Total**: 2-4 hours for complete feature (vs. 2-5 days manual)

## Cross-Department Handoffs

```
Product Strategy → Design → Engineering → QA → Operations
     ↓              ↓           ↓         ↓        ↓
  Vision      UI Design    Code Impl  Testing  Deploy
```

## Artifacts Created

1. `product-overview.md` (Product)
2. `requirements.md` (Product)
3. 4 UI implementations (Design)
4. Architecture doc (Engineering)
5. Backend code (Engineering)
6. Frontend code (Design/Engineering)
7. Test results (QA)
8. PR with review (QA/Engineering)
9. Deployment logs (Operations)

## Common Issues

**Issue**: UI direction doesn't match requirements
**Fix**: Review requirements.md before design-explore-ui, provide context

**Issue**: Backend/frontend integration issues
**Fix**: Use /orc:plan-feature first for upfront alignment

**Issue**: Tests failing
**Fix**: Run /testing:feature earlier in development, not just at end

## Related Workflows

- [Backend API Development](./backend-api-development.md)
- [Frontend Component Development](./frontend-component-development.md)
- [Design Exploration](./design-figma-to-react.md)

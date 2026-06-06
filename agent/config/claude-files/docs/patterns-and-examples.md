# Patterns and Examples: Claude Code Multi-Tier System

**Version**: 1.1.0
**Last Updated**: December 2025
**Purpose**: Real-world examples and common patterns for using the multi-tier complexity system

---

## Table of Contents

1. [Tier 1 Examples](#tier-1-examples-claude-direct)
2. [Tier 2 Examples](#tier-2-examples-managerspecialist)
3. [Tier 3 Examples](#tier-3-examples-multi-agent-orchestration)
4. [Specialist Creation Examples](#specialist-creation-examples)
5. [Common Patterns](#common-patterns)
6. [Before/After Comparisons](#beforeafter-comparisons)
7. [Integration Examples](#integration-examples)

---

## Tier 1 Examples (Claude Direct)

### Example 1: Bug Fix

**Scenario**: Button is enabled when form is invalid

**Request**:
```
"The submit button in LoginForm.tsx is enabled even when the email
field is empty. It should be disabled until both email and password
are filled."
```

**Claude's Approach**:
- Complexity: 0/10 (single file, no dependencies)
- Action: Direct fix without manager

**Response**:
```typescript
// Before
<button type="submit">Login</button>

// After
<button type="submit" disabled={!email || !password}>
  Login
</button>
```

**Execution**: Uses Edit tool directly

**Time**: 10 seconds

---

### Example 2: Copy Change

**Request**:
```
"Change the page title from 'Dashboard - Analytics' to
'Analytics Dashboard'"
```

**Claude's Approach**:
- Complexity: 0/10
- Action: Direct update

**Time**: 5 seconds

---

### Example 3: Simple Styling

**Request**:
```
"Increase the padding on all buttons by 4px and change the
border radius from 4px to 6px"
```

**Claude's Approach**:
- Complexity: 1/10 (multiple components might be affected)
- Action: Direct CSS/Tailwind update

**Response** (if using Tailwind):
```tsx
// Before
className="px-4 py-2 rounded"

// After
className="px-5 py-3 rounded-md"
```

**Time**: 15 seconds

---

### Example 4: Add Logging

**Request**:
```
"Add console.log statements in the checkout flow to debug
the payment processing issue. Log at:
1. Start of handleCheckout
2. Before calling processPayment
3. After payment success/failure"
```

**Claude's Approach**:
- Complexity: 0/10
- Action: Add logs directly

**Response**:
```typescript
async function handleCheckout(orderData) {
  console.log('[Checkout] Starting checkout process', { orderData });

  try {
    console.log('[Checkout] Calling processPayment...');
    const result = await processPayment(orderData);
    console.log('[Checkout] Payment successful', { result });
    return result;
  } catch (error) {
    console.error('[Checkout] Payment failed', { error });
    throw error;
  }
}
```

**Time**: 20 seconds

---

## Tier 2 Examples (Manager/Specialist)

### Example 1: REST API Endpoint

**Scenario**: Add CRUD endpoints for products

**Request**:
```
"Add REST API endpoints for products:
- GET /api/products (list all, with pagination)
- GET /api/products/:id (get single)
- POST /api/products (create, requires auth)
- PUT /api/products/:id (update, requires auth)
- DELETE /api/products/:id (delete, requires admin)

Include validation, error handling, and tests."
```

**Claude's Approach**:
- Complexity: 6/10 (scope=2, dependencies=1, scale=1, risk=1)
- Action: Use Engineering Manager
- Additional: Use QA Manager for test strategy

**Response**:
```
[Reads .claude/managers/engineering-manager.md]
[Reads .claude/managers/qa-manager.md]

I'll implement the products API following SOLID principles and the
Test Pyramid approach.

**1. Routes** (routes/products.ts):
[Complete Express router code with validation]

**2. Controller** (controllers/productController.ts):
[Controller code with error handling]

**3. Service** (services/productService.ts):
[Business logic layer]

**4. Validation** (validators/productSchema.ts):
[Zod schemas]

**5. Tests**:
**Unit Tests** (70%):
[Service and validation tests]

**Integration Tests** (20%):
[API endpoint tests with test database]

**E2E Tests** (10%):
[Happy path tests]

This follows the Test Pyramid (70/20/10) and SOLID principles.
```

**Time**: 2-3 minutes

**Files Created**:
- routes/products.ts
- controllers/productController.ts
- services/productService.ts
- validators/productSchema.ts
- tests/unit/productService.test.ts
- tests/integration/products.test.ts
- tests/e2e/products.e2e.test.ts

---

### Example 2: React Component with State Management

**Scenario**: Add shopping cart component

**Request**:
```
"Create a shopping cart component that:
- Shows list of items with quantity
- Allows quantity updates (+ / -)
- Shows subtotal, tax, and total
- Has 'Checkout' button
- Syncs with backend API
- Handles loading and error states
- Includes unit tests"
```

**Claude's Approach**:
- Complexity: 5/10 (scope=1, dependencies=1, scale=1, risk=1)
- Action: Use Engineering Manager

**Response**:
```
[Reads .claude/managers/engineering-manager.md]

I'll create the shopping cart following React best practices and SOLID principles.

**1. Component** (components/ShoppingCart.tsx):
[Complete React component with hooks]

**2. Custom Hook** (hooks/useCart.ts):
[Custom hook for cart logic]

**3. API Service** (services/cartService.ts):
[API integration]

**4. Types** (types/cart.ts):
[TypeScript interfaces]

**5. Tests** (components/ShoppingCart.test.tsx):
[Jest + Testing Library tests]

**State Management**:
- Uses React Query for server state
- Local state for optimistic updates
- Error boundaries for error handling
```

**Time**: 2-3 minutes

---

### Example 3: Database Migration

**Scenario**: Add user roles system

**Request**:
```
"Add a roles system to the users table:
- Add 'role' column (enum: 'user', 'moderator', 'admin')
- Default to 'user'
- Update existing users to 'user'
- Add index on role for filtering
- Update all queries that read users
- Provide up/down migration scripts
- Zero downtime deployment plan"
```

**Claude's Approach**:
- Complexity: 6/10 (scope=2, dependencies=1, risk=2)
- Action: Use Engineering + Operations Managers

**Response**:
```
[Reads .claude/managers/engineering-manager.md]
[Reads .claude/managers/operations-manager.md]

**Migration Strategy** (zero downtime):

**Phase 1: Add column (nullable)**:
ALTER TABLE users ADD COLUMN role VARCHAR(20);
CREATE INDEX idx_users_role ON users(role);

**Phase 2: Backfill data**:
UPDATE users SET role = 'user' WHERE role IS NULL;

**Phase 3: Make NOT NULL**:
ALTER TABLE users ALTER COLUMN role SET NOT NULL;
ALTER TABLE users ALTER COLUMN role SET DEFAULT 'user';

**Migration Up** (migrations/20250113_add_user_roles.up.sql):
[Complete migration SQL]

**Migration Down** (migrations/20250113_add_user_roles.down.sql):
[Rollback SQL]

**Updated Queries**:
[Shows all affected queries with role column]

**Deployment Plan**:
1. Run Phase 1-3 migrations (no app changes yet)
2. Verify data integrity
3. Deploy app code using role column
4. Monitor for errors
5. Rollback: Revert code, keep column for retry

**Monitoring**:
- Track query performance on new index
- Alert if backfill takes >5 minutes
```

**Time**: 3-4 minutes

---

### Example 4: Using Project Specialist

**Scenario**: Add authentication endpoint (with auth specialist)

**Setup**:
```markdown
# .claude/agents/auth-specialist.md exists with:
- Custom AuthProvider context
- useAuth hook pattern
- JWT storage in httpOnly cookies
- Refresh token rotation
```

**Request**:
```
"Add a password reset endpoint that sends a reset email"
```

**Claude's Approach**:
- Complexity: 4/10
- Action: Check for auth specialist → Found!
- Uses: auth-specialist.md patterns

**Response**:
```
[Reads .claude/agents/auth-specialist.md]

I'll implement password reset following your auth patterns.

**1. API Endpoint** (routes/auth.ts):
POST /api/auth/reset-password-request

[Uses your custom auth middleware and error patterns]

**2. Service** (services/authService.ts):
[Uses your token generation pattern]

**3. Email Template** (templates/password-reset.html):
[Uses your email service pattern]

**4. Frontend Hook** (hooks/usePasswordReset.ts):
[Uses your useAuth hook pattern]

This follows your auth patterns:
- httpOnly cookies for security
- Custom AuthProvider integration
- Your error handling format
```

**Key Difference**:
- **Without specialist**: Generic JWT, standard localStorage
- **With specialist**: Your httpOnly cookies, AuthProvider, custom patterns

**Time**: 2 minutes

---

## Tier 3 Examples (Multi-Agent Orchestration)

### Example 1: SaaS Product Launch

**Request**:
```
"Launch a new SaaS product for team collaboration (Slack competitor).

Features:
- Real-time messaging (WebSocket)
- Channels and direct messages
- File sharing (images, documents)
- User authentication (OAuth + email)
- Team management (invite, roles)
- Search (messages, files, users)
- Notifications (email, push, in-app)
- Admin dashboard (analytics, billing)

Technical:
- React frontend (mobile-first)
- Node.js backend
- PostgreSQL database
- Redis for caching
- S3 for file storage
- Stripe for billing
- SendGrid for email

Scale:
- 10,000 users at launch
- 1M messages/day expected
- 99.9% uptime SLA

Timeline: 3 months
Budget: $250k
Team: 5 developers"
```

**Claude's Approach**:
- Complexity: 10/10
  - Scope: 2 (full product lifecycle)
  - Dependencies: 2 (OAuth, Stripe, SendGrid, S3)
  - Novelty: 1 (real-time messaging)
  - Scale: 2 (10K users, 1M messages/day)
  - Risk: 2 (business-critical, SLA requirement)
- Action: Recommend multi-agent orchestration

**Response**:
```
This is a comprehensive product launch scoring 10/10 on complexity:

Scope: 2 (strategy → design → engineering → QA → operations)
Dependencies: 2 (OAuth, Stripe, SendGrid, S3, Redis)
Novelty: 1 (real-time messaging at scale)
Scale: 2 (10K users, 1M messages/day, 99.9% SLA)
Risk: 2 (business-critical, revenue-generating)

I recommend multi-agent orchestration for this task. Use /code-parallel
to spawn specialized agents for each department:

/code-parallel --departments strategy,design,engineering,qa,operations \
  "launch team collaboration SaaS product (Slack competitor)
  with real-time messaging (WebSocket), channels, direct messages, file
  sharing (S3), OAuth + email auth, team management, search (ElasticSearch),
  notifications (email/push/in-app), admin dashboard (analytics, billing).
  Tech stack: React, Node.js, PostgreSQL, Redis, S3, Stripe, SendGrid.
  Scale: 10K users, 1M messages/day, 99.9% uptime SLA. Timeline: 3 months,
  Budget: $250k, Team: 5 developers"

Multi-agent orchestration will coordinate all 5 departments:

Strategy Manager:
- Market research (competitor analysis)
- Pricing model ($10-50/user/month tiered)
- Go-to-market strategy
- Success metrics (user acquisition, retention)

Design Manager:
- User research and personas
- Information architecture (20+ screens)
- UI/UX design (mobile-first)
- Design system and component library

Engineering Manager:
- System architecture (microservices vs monolith decision)
- Real-time messaging infrastructure (WebSocket + Redis pub/sub)
- Database design (message partitioning strategy)
- API design (REST + WebSocket)
- Frontend implementation (React + TypeScript)
- File upload/storage system
- Search implementation (ElasticSearch)

QA Manager:
- Test strategy (unit, integration, E2E)
- Load testing (1M messages/day simulation)
- Security audit (OWASP Top 10)
- Penetration testing
- Performance testing (message latency <100ms)

Operations Manager:
- AWS infrastructure (ECS + RDS + ElastiCache)
- CI/CD pipeline (GitHub Actions)
- Monitoring and alerting (Datadog)
- Logging (CloudWatch)
- Deployment strategy (blue-green)
- Disaster recovery plan
- 99.9% SLA implementation

This ensures comprehensive, coordinated execution across all phases.
```

**What You Do**:
```bash
# Run the multi-agent orchestration command
/code-parallel --departments strategy,design,engineering,qa,operations \
  "launch team collaboration SaaS product..."

# Orchestration coordinates the work
# Takes hours to days depending on scope

# Review deliverables from each agent
```

**Expected Deliverables** (from orchestration):
- Market research report
- Product requirements document (PRD)
- Design files (Figma) + component library
- Complete codebase (frontend + backend)
- Database schema + migrations
- Test suite (unit + integration + E2E)
- CI/CD pipeline configuration
- AWS infrastructure (Terraform)
- Monitoring dashboards
- Documentation (user guides, API docs, runbooks)

**Time**: Multi-agent orchestration takes 4-8 hours for coordination + planning
**Cost**: Higher token usage than single-agent (Tier 2) approaches

---

### Example 2: Microservices Migration

**Request**:
```
"Migrate our monolithic Rails app to microservices architecture.

Current:
- Rails monolith (200K lines of code)
- PostgreSQL database
- 100K daily active users
- 50 developers

Target:
- 8 microservices (User, Product, Order, Payment, Shipping, Notification, Search, Analytics)
- API Gateway (Kong)
- Service mesh (Istio)
- Kubernetes deployment
- Zero downtime migration
- Rollback plan

Timeline: 6 months
Risk: Critical (can't disrupt production)"
```

**Claude's Approach**:
- Complexity: 10/10
  - Scope: 2 (8 services + infrastructure)
  - Dependencies: 2 (multiple databases, message queues)
  - Novelty: 1 (microservices patterns established)
  - Scale: 2 (100K DAU, 50 developers)
  - Risk: 2 (production migration, zero downtime requirement)

**Response**:
```
This platform migration scores 10/10 - requires multi-agent orchestration:

/code-parallel --departments strategy,engineering,qa,operations \
  "migrate Rails monolith (200K LOC) to microservices
  architecture with 8 services (User, Product, Order, Payment, Shipping,
  Notification, Search, Analytics), API Gateway (Kong), service mesh
  (Istio), Kubernetes deployment, separate databases per service,
  event-driven communication (RabbitMQ), distributed tracing (Jaeger),
  centralized logging (ELK), monitoring (Prometheus/Grafana), zero
  downtime migration with gradual traffic shift, comprehensive rollback
  plan. 100K DAU, 50 developers, 6-month timeline"

Multi-agent orchestration coordinates:

Strategy Manager:
- Migration roadmap (service decomposition order)
- Risk mitigation strategy
- Communication plan (50 developers)
- Success criteria

Engineering Manager:
- Service boundary design
- Data migration strategy
- API contract design
- Service implementation
- Strangler pattern for gradual migration

QA Manager:
- Migration testing strategy
- Contract testing (Pact)
- Load testing (production traffic simulation)
- Rollback validation

Operations Manager:
- Kubernetes cluster setup
- Service mesh configuration
- Gradual traffic shift (1% → 10% → 50% → 100%)
- Monitoring and alerting
- Incident response plan
- Rollback automation

This ensures safe, coordinated migration with zero downtime.
```

**Time**: Multi-agent orchestration takes 6-10 hours
**Deliverables**: Migration plan, 8 service codebases, infrastructure, runbooks

---

## Specialist Creation Examples

### Example 1: API Specialist (After 10+ Endpoints)

**Scenario**: You've built 10 API endpoints following consistent patterns

**Step 1: Identify Patterns**

After building endpoints, you notice:
```
1. All use custom requireAuth middleware
2. All use Zod validation schemas in routes/validators/
3. All follow Controller → Service → Repository pattern
4. All use custom ApiError class
5. All have OpenAPI documentation
```

**Step 2: Create Specialist**

```bash
cp .claude/docs/PROJECT-SPECIALIST-TEMPLATE.md .claude/agents/api-specialist.md
```

**Step 3: Fill Template**

```markdown
# API Specialist

## PROJECT CONTEXT
Express backend with custom auth middleware, Zod validation, and three-tier architecture (Controller → Service → Repository).

## PROJECT-SPECIFIC PATTERNS

### Authentication
```typescript
// All protected routes use:
router.use(requireAuth);

// Admin routes use:
router.use(requireAuth, requireAdmin);
```

### Validation
```typescript
// Validators in routes/validators/
// Applied as middleware
router.post('/users', validateRequest(createUserSchema), createUser);
```

### Error Handling
```typescript
// Custom ApiError class
throw new ApiError(400, 'Invalid input', { field: 'email' });

// Centralized error handler catches all
app.use(errorHandler);
```

### Three-Tier Architecture
```
routes/ → Define endpoints and apply middleware
controllers/ → Handle request/response, call services
services/ → Business logic
repositories/ → Data access (database queries)
```

## PROJECT CONVENTIONS
- Routes organized by resource (routes/users.ts, routes/products.ts)
- One controller per resource (controllers/userController.ts)
- Services contain business logic only
- Repositories handle all database access
- No business logic in controllers or repositories

## PROJECT TOOLS & LIBRARIES
- Express 4.18
- Zod for validation
- JWT (jsonwebtoken)
- PostgreSQL (node-postgres)
- OpenAPI (swagger-jsdoc)

## COMMON TASKS
- Add new CRUD endpoint
- Add auth to existing endpoint
- Update validation schema
- Add pagination to list endpoint

## GOTCHAS & PITFALLS
❌ DON'T put business logic in controllers
❌ DON'T catch errors in controllers (let errorHandler catch)
❌ DON'T use raw SQL in controllers (use repositories)
✅ DO validate all input with Zod
✅ DO use transactions for multi-table operations
✅ DO document with OpenAPI comments

## RELATED DOCUMENTATION
- API conventions: docs/api-conventions.md
- Error codes: docs/error-codes.md
- OpenAPI spec: swagger.json
```

**Step 4: Test**

```
"Add a new /api/orders endpoint with CRUD operations"
```

Claude should now use your patterns!

---

### Example 2: Component Specialist (Design System)

**Scenario**: You have a design system with 20+ components

**Create**: `.claude/agents/component-specialist.md`

```markdown
# Component Specialist

## PROJECT CONTEXT
React design system using Radix UI primitives, Tailwind CSS, and CVA for variants.

## PROJECT-SPECIFIC PATTERNS

### Component Structure
```tsx
// All components follow this structure:
components/
  ui/
    Button/
      Button.tsx      // Component
      Button.test.tsx // Tests
      Button.stories.tsx // Storybook
      index.ts        // Exports
```

### Variants with CVA
```tsx
import { cva } from 'class-variance-authority';

const buttonVariants = cva('base-classes', {
  variants: {
    variant: { default: '...', destructive: '...', outline: '...' },
    size: { default: '...', sm: '...', lg: '...' },
  },
  defaultVariants: { variant: 'default', size: 'default' },
});
```

### Composition Pattern
```tsx
// Components compose from Radix primitives
import * as Dialog from '@radix-ui/react-dialog';

export const Modal = ({ children, ...props }) => (
  <Dialog.Root {...props}>
    <Dialog.Portal>
      <Dialog.Overlay className="..." />
      <Dialog.Content className="...">{children}</Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>
);
```

## PROJECT CONVENTIONS
- All UI components in components/ui/
- Use Radix UI for accessibility
- Variants managed with CVA
- Tailwind for all styling (no CSS modules)
- Full TypeScript types
- Storybook for all components

## PROJECT TOOLS & LIBRARIES
- React 18
- Radix UI
- Tailwind CSS 3
- CVA (class-variance-authority)
- Storybook 7

## COMMON TASKS
- Add new component to design system
- Add variant to existing component
- Update component styling

## GOTCHAS & PITFALLS
❌ DON'T use inline styles
❌ DON'T bypass Radix primitives for complex components
❌ DON'T forget to export from components/ui/index.ts
✅ DO use CVA for variants
✅ DO compose from Radix primitives
✅ DO add Storybook stories

## RELATED DOCUMENTATION
- Design system: docs/design-system.md
- Component API: storybook static site
```

---

## Common Patterns

### Pattern 1: Feature Branch Workflow

**Scenario**: Standard feature development

**Workflow**:
```
1. Create feature branch
2. Develop with Claude (Tier 1-2)
3. Test locally
4. Create PR
5. Use Claude to review own code
6. Address feedback
7. Merge
```

**Example**:
```bash
# 1. Create branch
git checkout -b feature/add-favorites

# 2. Develop
> "Add favorites feature with backend, frontend, and tests"
[Claude uses Engineering + QA Managers]

# 3. Test
npm test

# 4. Create PR
gh pr create --title "Add favorites feature"

# 5. Review
> "Review the favorites feature for potential issues"
[Claude uses QA Manager to review]

# 6. Address feedback
[Make fixes]

# 7. Merge
gh pr merge
```

---

### Pattern 2: Refactoring Legacy Code

**Scenario**: Large refactor with tests

**Workflow**:
```
1. Understand current code
2. Write tests for current behavior
3. Refactor in small steps
4. Verify tests still pass
```

**Example**:
```
> "Review the UserService class and identify code smells"
[Claude uses Engineering Manager - SOLID principles]

> "Write comprehensive tests for UserService before refactoring"
[Claude uses QA Manager - Test Pyramid]

> "Refactor UserService to follow Single Responsibility Principle"
[Claude uses Engineering Manager - SOLID]

> "Run tests to verify behavior unchanged"
[Verify tests pass]
```

---

### Pattern 3: Performance Optimization

**Scenario**: Slow page load

**Workflow**:
```
1. Measure current performance
2. Identify bottlenecks
3. Optimize systematically
4. Measure improvements
```

**Example**:
```
> "Analyze the dashboard page performance - current load time is 5s"
[Claude uses QA Manager - performance testing]

> "The main bottlenecks are:
   - Unoptimized images (2s)
   - Large bundle size (1.5s)
   - Slow API calls (1.5s)

   Let's optimize images first..."

> "Implement image optimization with next/image"
[Claude uses Engineering Manager]

> "Measure the improvement"
[Load time now 3s]

> "Now optimize bundle size with code splitting"
[Continue systematically]
```

---

### Pattern 4: Security Audit → Fix

**Scenario**: Security review required

**Workflow**:
```
1. Run security audit
2. Prioritize findings
3. Fix critical issues
4. Verify fixes
```

**Example**:
```
> "Conduct security audit of our API"
[Claude uses QA Manager - OWASP Top 10]

> "Found 2 critical, 5 high severity issues.

   CRITICAL #1: SQL injection in /api/search
   [Details and fix]

   CRITICAL #2: Missing rate limiting on /api/auth/login
   [Details and fix]

   Recommendation: Fix critical issues immediately."

> "Implement the SQL injection fix"
[Claude implements parameterized queries]

> "Implement rate limiting on auth endpoints"
[Claude implements express-rate-limit]

> "Re-run security audit to verify fixes"
[Verify issues resolved]
```

---

## Before/After Comparisons

### Comparison 1: Without vs With Specialist

**Scenario**: Adding authentication

**WITHOUT Specialist** (using Engineering Manager):
```typescript
// Generic JWT implementation
const token = jwt.sign({ userId: user.id }, JWT_SECRET);
localStorage.setItem('token', token);
```

**WITH auth-specialist.md**:
```typescript
// Your project's pattern: httpOnly cookies + refresh tokens
res.cookie('accessToken', generateAccessToken(user), {
  httpOnly: true,
  secure: process.env.NODE_ENV === 'production',
  sameSite: 'strict',
  maxAge: 15 * 60 * 1000, // 15 minutes
});

res.cookie('refreshToken', generateRefreshToken(user), {
  httpOnly: true,
  secure: process.env.NODE_ENV === 'production',
  sameSite: 'strict',
  maxAge: 7 * 24 * 60 * 60 * 1000, // 7 days
});
```

**Key Difference**: Specialist ensures Claude follows YOUR security pattern, not generic approach.

---

### Comparison 2: Tier 1 vs Tier 2 Decision

**Request**: "Add error handling to the API"

**If Simple (Tier 1)**:
```
Scope: Single endpoint needs try/catch
Claude handles directly
```

**If Complex (Tier 2)**:
```
Scope: Comprehensive error handling across all endpoints
- Centralized error handler middleware
- Custom error classes
- Error logging to monitoring service
- User-friendly error responses

Claude uses Engineering Manager for architecture
```

---

### Comparison 3: Tier 2 vs Tier 3 Decision

**Request**: "Build user authentication"

**Tier 2 (4-5/10)**:
```
"Add JWT authentication with login and registration"

Claude uses Engineering Manager:
- Login/registration endpoints
- JWT generation/verification
- Protected route middleware
- Basic tests
```

**Tier 3 (9/10)**:
```
"Build complete auth system with OAuth (Google, GitHub), MFA,
SSO (SAML), RBAC with 20 roles and 100 permissions, audit logging,
session management, and SOC 2 compliance"

Claude recommends multi-agent orchestration:
- Strategy: Security architecture design
- Engineering: OAuth integration, MFA, SSO, RBAC
- QA: Security testing, penetration testing
- Operations: Audit logging, session management
```

---

## Integration Examples

### Integration 1: CI/CD + Testing

**Scenario**: Set up comprehensive CI/CD

**Request**:
```
"Set up GitHub Actions CI/CD with:
- Linting (ESLint)
- Type checking (TypeScript)
- Unit tests (Jest)
- Integration tests (Supertest)
- E2E tests (Playwright)
- Security scanning (npm audit)
- Deploy to staging on PR
- Deploy to production on merge to main (manual approval)"
```

**Claude's Approach**:
- Complexity: 6/10
- Uses: QA Manager (test strategy) + Operations Manager (CI/CD)

**Result**: Complete GitHub Actions workflows following best practices

---

### Integration 2: Design → Implementation

**Scenario**: Implement design from Figma

**Step 1: Export from Figma**
```
> "I have a Figma design for a new dashboard. What do I need to export?"
[Claude explains: colors, typography, spacing, components]
```

**Step 2: Implement Design System**
```
> "Create Tailwind config from these design tokens: [paste tokens]"
[Claude uses Design Manager - creates tailwind.config.js]
```

**Step 3: Build Components**
```
> "Build the dashboard layout from the Figma design"
[Claude uses Design Manager - implements with accessibility]
```

---

### Integration 3: Database → API → Frontend

**Scenario**: Full-stack feature

**Step 1: Database**
```
> "Design database schema for a blog with posts, authors, tags, and comments"
[Claude uses Engineering Manager - provides normalized schema]
```

**Step 2: API**
```
> "Build REST API for the blog schema"
[Claude uses Engineering Manager - CRUD endpoints]
```

**Step 3: Frontend**
```
> "Build blog UI with post list, single post view, and comments"
[Claude uses Engineering + Design Managers]
```

**Step 4: Tests**
```
> "Add comprehensive tests for the blog feature"
[Claude uses QA Manager - Test Pyramid approach]
```

---

## Advanced Use Cases

### Use Case 1: Gradual Specialist Introduction

**Timeline**: 3 months

**Month 1**: No specialists, use managers
```
Week 1-2: Ship 5 features using Engineering Manager
Week 3-4: Identify patterns (similar auth flows, similar API endpoints)
```

**Month 2**: Create first specialists
```
Week 5: Create auth-specialist.md (pattern emerged)
Week 6-8: Use auth specialist for 3 auth tasks
```

**Month 3**: Expand specialists
```
Week 9: Create api-specialist.md
Week 10: Create component-specialist.md
Week 11-12: Use all 3 specialists regularly
```

**Result**: Specialists created based on actual patterns, not speculation

---

### Use Case 2: Team Onboarding with Specialists

**Scenario**: New developer joins team

**Day 1: Setup**
```
1. Clone repo (includes .claude/ with 3 specialists)
2. Read .claude/README.md
3. Read .claude/docs/USER-GUIDE.md
```

**Day 2: First Task (with specialist guidance)**
```
Task: "Add new API endpoint for user profiles"

Claude automatically uses api-specialist.md
Developer sees exactly how team builds APIs
No need to read 10 wiki pages
```

**Day 3-5: More Tasks**
```
Each task uses relevant specialist
Developer learns patterns organically
Code reviews smoother (follows patterns)
```

**Result**: New developer productive immediately, following team patterns

---

### Use Case 3: Major Refactoring with Multi-Agent Orchestration

**Scenario**: Major codebase modernization

**Request**:
```
"Modernize our codebase:
- Migrate from JavaScript to TypeScript (50K LOC)
- Update from React 16 to React 18
- Migrate from REST to GraphQL
- Update testing from Enzyme to Testing Library
- Migrate from Webpack to Vite
- Update all dependencies
- Zero downtime deployment
Timeline: 2 months"
```

**Claude's Response**:
```
This modernization scores 10/10 on complexity:

/code-parallel --departments strategy,engineering,qa,operations \
  "modernize codebase: JavaScript to TypeScript (50K LOC),
  React 16 to React 18, REST to GraphQL, Enzyme to Testing Library,
  Webpack to Vite, update dependencies, zero downtime deployment, 2-month
  timeline"

Multi-agent orchestration will coordinate:
- Strategy: Migration roadmap, risk assessment
- Engineering: TypeScript migration, React 18 updates, GraphQL, Vite
- QA: Test migration, regression testing
- Operations: Gradual deployment, rollback strategy
```

**Result**: Coordinated modernization across all layers

---

## Summary

### Quick Reference: Which Tier?

```
Single file, low risk → Tier 1 (direct)
Multiple files, moderate complexity → Tier 2 (manager/specialist)
Cross-cutting, high scale/risk → Tier 3 (multi-agent orchestration)
```

### Quick Reference: When to Create Specialist?

```
Have done similar task 10+ times? → Create specialist
Unique project pattern? → Create specialist
Generic industry pattern? → Use manager
```

### Quick Reference: Common Workflows

```
Simple fix → Ask Claude → Done (Tier 1)
Feature → Ask Claude → Uses managers → Review → Done (Tier 2)
Initiative → Ask Claude → Run /code-parallel → Review (Tier 3)
```

---

**Version**: 1.1.0
**Last Updated**: December 2025

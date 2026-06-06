# Testing Framework: Claude Code Multi-Tier System

**Version**: 1.0.0
**Last Updated**: January 2025
**Purpose**: Validate the three-tier hybrid system functions correctly across all complexity levels

---

## Overview

This document defines test scenarios, validation criteria, and expected behaviors for all three tiers of the hybrid system:

- **Tier 1 (0-2)**: Claude handles directly without manager/specialist
- **Tier 2 (3-8)**: Claude invokes manager or project specialist
- **Tier 3 (9-10)**: Claude suggests multi-agent orchestration

**Testing Philosophy**: Test the decision-making logic, not implementation. Verify correct tier selection based on complexity scoring.

---

## Sprint 12: Tier 1 Testing (Complexity 0-2)

### Test Objective

Validate that Claude Code:
1. Correctly identifies simple tasks (complexity 0-2)
2. Handles tasks directly without unnecessary manager invocation
3. Produces quality output without specialist guidance
4. Completes tasks efficiently (minimal context, fast response)

### Complexity Profile: Tier 1

**Scoring Characteristics** (must score 0-2 total):
```
Scope:        0-1 (single file or 2-3 related files)
Dependencies: 0   (no external services)
Novelty:      0   (established patterns)
Scale:        0   (dev/small scale)
Risk:         0-1 (low risk, easily reversible)
```

**Task Types**:
- Bug fixes in single file
- Text/copy updates
- Simple validation logic
- CSS/styling tweaks
- Log statement additions
- TypeScript type fixes
- Configuration updates (non-critical)

---

### Test Scenarios: Tier 1

#### TS1.1: Fix TypeScript Type Error

**Complexity Score**: 0/10
- Scope: 0 (single file)
- Dependencies: 0 (no external systems)
- Novelty: 0 (standard TypeScript)
- Scale: 0 (affects dev only)
- Risk: 0 (low risk, easy to revert)

**Test Prompt**:
```
"Fix the TypeScript error in src/components/UserProfile.tsx where
the 'age' property is missing from the User interface."
```

**Expected Behavior**:
✅ Claude analyzes the file
✅ Identifies the missing property
✅ Adds the property to the interface
✅ No manager invocation
✅ No complexity analysis mentioned to user
✅ Direct, concise response

**Validation Checklist**:
- [ ] No `.claude/managers/` files read
- [ ] Single file edited
- [ ] Type error resolved
- [ ] Response time < 10 seconds
- [ ] No unnecessary explanation of tier system

**Example Expected Output**:
```typescript
// Before
interface User {
  name: string;
  email: string;
}

// After
interface User {
  name: string;
  email: string;
  age: number;
}
```

**Anti-Pattern** (what NOT to do):
```
❌ "This task scores 0/10 on the complexity rubric, so I'll handle it
    directly without invoking the Engineering Manager..."
```

**Correct Pattern**:
```
✅ "I'll fix the TypeScript error in the User interface."
   [Uses Edit tool]
   "Fixed - added the age property to the User interface."
```

---

#### TS1.2: Update Copy Text

**Complexity Score**: 0/10
- Scope: 0 (single file)
- Dependencies: 0 (no external systems)
- Novelty: 0 (text change)
- Scale: 0 (UI only)
- Risk: 0 (easy to revert)

**Test Prompt**:
```
"Change the heading on the login page from 'Welcome Back' to
'Sign In to Your Account'"
```

**Expected Behavior**:
✅ Claude identifies the file (e.g., `LoginPage.tsx`)
✅ Updates the text
✅ No design manager invocation
✅ Simple, direct response

**Validation Checklist**:
- [ ] No manager files read
- [ ] Text updated correctly
- [ ] No unnecessary design analysis
- [ ] Response clear and concise

---

#### TS1.3: Add Simple Validation

**Complexity Score**: 1/10
- Scope: 0 (single file)
- Dependencies: 0 (no external systems)
- Novelty: 0 (standard regex)
- Scale: 0 (form validation)
- Risk: 1 (moderate - affects UX, but easily testable)

**Test Prompt**:
```
"Add email validation to the registration form - must contain @
and at least one dot"
```

**Expected Behavior**:
✅ Claude adds regex validation
✅ Provides clear error message
✅ No QA manager for simple validation
✅ Includes basic test suggestion (optional)

**Validation Checklist**:
- [ ] Validation regex correct
- [ ] Error message user-friendly
- [ ] No manager invocation for simple validation
- [ ] Code follows existing patterns in file

**Example Expected Code**:
```typescript
const validateEmail = (email: string): boolean => {
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return emailRegex.test(email);
};

// Usage
if (!validateEmail(formData.email)) {
  setError('Please enter a valid email address');
  return;
}
```

---

#### TS1.4: CSS Styling Update

**Complexity Score**: 0/10
- Scope: 0 (single file or component)
- Dependencies: 0 (no external services)
- Novelty: 0 (standard CSS)
- Scale: 0 (UI only)
- Risk: 0 (easy to revert)

**Test Prompt**:
```
"Change the button background color from blue to green and
increase padding by 4px"
```

**Expected Behavior**:
✅ Claude updates CSS/Tailwind classes
✅ Maintains accessibility (contrast)
✅ No design manager for simple styling
✅ Direct implementation

**Validation Checklist**:
- [ ] Color updated correctly
- [ ] Padding increased as requested
- [ ] No manager invocation
- [ ] Maintains existing style patterns

---

#### TS1.5: Add Log Statement

**Complexity Score**: 0/10
- Scope: 0 (single file)
- Dependencies: 0 (no external systems)
- Novelty: 0 (standard logging)
- Scale: 0 (debugging aid)
- Risk: 0 (no production impact)

**Test Prompt**:
```
"Add a console log statement in the handleSubmit function to log
the form data before submission"
```

**Expected Behavior**:
✅ Claude adds log statement
✅ Includes relevant context in log
✅ No manager invocation
✅ Follows project logging patterns

**Validation Checklist**:
- [ ] Log statement added in correct location
- [ ] Log message is descriptive
- [ ] No manager files accessed
- [ ] Follows existing logging format

**Example Expected Code**:
```typescript
const handleSubmit = (formData: FormData) => {
  console.log('Form submission:', formData);
  // ... rest of function
};
```

---

#### TS1.6: Fix Import Path

**Complexity Score**: 0/10
- Scope: 0 (single file)
- Dependencies: 0 (internal import)
- Novelty: 0 (standard import)
- Scale: 0 (build fix)
- Risk: 0 (easy to verify)

**Test Prompt**:
```
"Fix the import path for the Button component - it should be
'@/components/Button' not './Button'"
```

**Expected Behavior**:
✅ Claude updates import path
✅ Verifies file structure if needed
✅ No manager for simple import fix
✅ Quick, direct fix

**Validation Checklist**:
- [ ] Import path corrected
- [ ] Follows project alias convention
- [ ] No unnecessary file reads
- [ ] No manager invocation

---

#### TS1.7: Update Configuration Value

**Complexity Score**: 1/10
- Scope: 0 (single config file)
- Dependencies: 0 (no external impact)
- Novelty: 0 (standard config)
- Scale: 0 (dev environment)
- Risk: 1 (config changes can affect behavior, but dev only)

**Test Prompt**:
```
"Change the API timeout in the development config from 5000ms
to 10000ms"
```

**Expected Behavior**:
✅ Claude updates config value
✅ Confirms environment (dev only)
✅ No operations manager for dev config
✅ May warn if production config

**Validation Checklist**:
- [ ] Config value updated correctly
- [ ] Correct environment file
- [ ] No manager invocation for dev config
- [ ] Warning if production impact

---

#### TS1.8: Add Comment Documentation

**Complexity Score**: 0/10
- Scope: 0 (single file)
- Dependencies: 0 (no external systems)
- Novelty: 0 (standard comments)
- Scale: 0 (documentation)
- Risk: 0 (no code change)

**Test Prompt**:
```
"Add JSDoc comments to the calculateTotal function explaining
its parameters and return value"
```

**Expected Behavior**:
✅ Claude adds JSDoc comments
✅ Includes parameter descriptions
✅ Documents return type
✅ No manager for documentation

**Validation Checklist**:
- [ ] JSDoc format correct
- [ ] All parameters documented
- [ ] Return value documented
- [ ] No manager invocation

**Example Expected Code**:
```typescript
/**
 * Calculates the total price including tax and shipping
 * @param subtotal - The sum of all item prices before tax
 * @param taxRate - Tax rate as decimal (e.g., 0.08 for 8%)
 * @param shipping - Shipping cost in dollars
 * @returns Total price including all charges
 */
function calculateTotal(
  subtotal: number,
  taxRate: number,
  shipping: number
): number {
  return subtotal * (1 + taxRate) + shipping;
}
```

---

### Tier 1 Validation Criteria

**For a test to PASS, Claude must**:

✅ **Identify simple task** without explicit complexity scoring shown to user
✅ **Handle directly** without reading manager/specialist files
✅ **Produce correct output** that solves the problem
✅ **Use appropriate tools** (Edit for changes, Read if needed)
✅ **Respond quickly** (< 15 seconds for typical Tier 1 tasks)
✅ **Keep context minimal** (< 5,000 tokens consumed)

**Red Flags (test FAILS if)**:

❌ Reads `.claude/managers/` files unnecessarily
❌ Mentions complexity rubric or tier system to user
❌ Asks user if they want to invoke manager/specialist
❌ Over-engineers simple solution
❌ Takes excessive time (> 30 seconds) for trivial task
❌ Creates new files when editing existing file would suffice

---

### Test Execution Guide

**Step 1: Setup**
- Ensure `.claude/` directory exists with all managers
- Create test files if needed (e.g., sample TypeScript components)
- Clear Claude Code context if testing fresh session

**Step 2: Run Test**
- Input test prompt exactly as written
- Observe Claude's behavior (file reads, tool usage)
- Note response time and token usage

**Step 3: Validate**
- Check validation checklist for each test
- Verify output correctness
- Confirm no manager files accessed
- Review user-facing response quality

**Step 4: Document Results**
- Record pass/fail for each scenario
- Note any unexpected behaviors
- Capture edge cases discovered
- Update test scenarios if needed

---

### Tier 1 Success Metrics

**Target Performance**:
- ✅ **Accuracy**: 100% of Tier 1 tasks handled correctly
- ✅ **Efficiency**: 0% manager invocations for Tier 1 tasks
- ✅ **Speed**: Average response time < 10 seconds
- ✅ **Context**: Average token usage < 3,000 tokens
- ✅ **User Experience**: Clear, concise responses without system internals

**Benchmark Results** (to be filled during testing):

| Test ID | Task | Pass/Fail | Manager Invoked? | Response Time | Tokens Used | Notes |
|---------|------|-----------|------------------|---------------|-------------|-------|
| TS1.1 | Fix TypeScript Error | ⬜ | ⬜ | - | - | - |
| TS1.2 | Update Copy Text | ⬜ | ⬜ | - | - | - |
| TS1.3 | Add Simple Validation | ⬜ | ⬜ | - | - | - |
| TS1.4 | CSS Styling Update | ⬜ | ⬜ | - | - | - |
| TS1.5 | Add Log Statement | ⬜ | ⬜ | - | - | - |
| TS1.6 | Fix Import Path | ⬜ | ⬜ | - | - | - |
| TS1.7 | Update Config Value | ⬜ | ⬜ | - | - | - |
| TS1.8 | Add Comment Documentation | ⬜ | ⬜ | - | - | - |

---

### Edge Cases & Boundary Testing

**Boundary: Tier 1 → Tier 2 (Score 2-3)**

These tasks are at the boundary and may legitimately go either way:

**Edge Case 1: Multi-File CSS Update**
```
"Update button styles across 3 component files to use consistent colors"
```
- **Complexity**: 2-3 (scope = 1, all else = 0)
- **Acceptable**: Tier 1 (direct) OR Tier 2 (design manager for consistency)
- **Key**: Should maintain consistency, regardless of tier

**Edge Case 2: Add Validation + Error Handling**
```
"Add email validation and show error message on invalid input"
```
- **Complexity**: 1-2 (scope = 0-1, risk = 0-1)
- **Acceptable**: Tier 1 if straightforward, Tier 2 if complex error handling
- **Key**: Quality of validation and error messages

**Edge Case 3: Config Update (Production)**
```
"Change the production API timeout from 5000ms to 10000ms"
```
- **Complexity**: 2-3 (risk increases to 1-2 for production)
- **Acceptable**: Tier 1 with caution, OR Tier 2 (operations manager for production changes)
- **Key**: Should warn about production impact

**Validation for Edge Cases**:
- If handled as Tier 1: Must include appropriate warnings/considerations
- If escalated to Tier 2: Should explain reason (complexity, risk, consistency)
- Either choice is acceptable if executed well

---

### Common Failure Patterns

**Pattern 1: Over-Engineering**
```
User: "Change the button color to red"

❌ Claude: "I'll invoke the Design Manager to ensure this color
    change maintains brand consistency and accessibility standards..."

✅ Claude: "I'll change the button color to red."
    [Uses Edit tool]
```

**Pattern 2: Unnecessary Analysis**
```
User: "Fix the typo in the heading"

❌ Claude: "This is a simple task scoring 0/10 on the complexity
    rubric (Scope: 0, Dependencies: 0...)"

✅ Claude: "I'll fix the typo in the heading."
    [Uses Edit tool]
```

**Pattern 3: Manager Invocation for Simple Tasks**
```
User: "Add a console log statement"

❌ Claude: [Reads engineering-manager.md]
    "The Engineering Manager recommends..."

✅ Claude: "I'll add the console log statement."
    [Uses Edit tool directly]
```

---

### Test Results Documentation

After running all Tier 1 tests, document results here:

**Test Date**: [To be filled]
**Claude Code Version**: [To be filled]
**Tester**: [To be filled]

**Summary**:
- Tests Passed: __/8
- Tests Failed: __/8
- Manager Invocations: __/8 (should be 0)
- Average Response Time: __ seconds
- Average Token Usage: __ tokens

**Issues Discovered**:
1. [Issue description]
2. [Issue description]

**Recommendations**:
1. [Recommendation]
2. [Recommendation]

---

## Sprint 13: Tier 3 Testing (Complexity 9-10)

### Test Objective

Validate that Claude Code:
1. Correctly identifies highly complex tasks (complexity 9-10)
2. Recognizes when task exceeds single-manager capability
3. Suggests multi-agent orchestration invocation with proper command syntax
4. Provides clear rationale for multi-agent orchestration recommendation
5. Does NOT attempt to handle task directly or with single manager

### Complexity Profile: Tier 3

**Scoring Characteristics** (must score 9-10 total):
```
Typical Pattern:
Scope:        2 (cross-cutting, multiple systems)
Dependencies: 2 (3-4+ external services)
Novelty:      1-2 (new patterns or experimental)
Scale:        2 (high scale, millions of users)
Risk:         2 (critical system, high impact)
───────────────────────────
TOTAL:        9-10/10
```

**Task Types**:
- Full product launches (strategy → design → build → test → deploy)
- Microservices architecture (8+ services, orchestration)
- Platform migrations (database, infrastructure, zero downtime)
- Real-time collaborative systems (WebSocket, CRDT, high concurrency)
- Security compliance programs (SOC 2, HIPAA, multi-department)
- Performance overhauls (database → backend → frontend → CDN)

---

### Test Scenarios: Tier 3

#### TS3.1: Full Product Launch

**Complexity Score**: 10/10
- Scope: 2 (strategy → design → engineering → QA → operations)
- Dependencies: 2 (multiple APIs, payment, email, analytics, CDN)
- Novelty: 1 (established patterns, but comprehensive)
- Scale: 2 (production, thousands of users)
- Risk: 2 (business-critical, revenue impact)

**Test Prompt**:
```
"We need to launch a new SaaS product for project management.
This includes:
- Market research and competitive analysis
- Product positioning and pricing strategy
- Full UI/UX design (20+ screens)
- Backend API (REST + WebSocket for real-time)
- Frontend web app (React)
- Authentication and authorization (OAuth + RBAC)
- Payment integration (Stripe)
- Email notifications
- Analytics dashboard
- DevOps setup (CI/CD, monitoring, logging)
- Security audit (OWASP compliance)
- Load testing (1000+ concurrent users)
- Documentation (user guides, API docs)
- Go-to-market plan

Timeline: 3 months. Budget: $200k."
```

**Expected Behavior**:
✅ Claude recognizes complexity 10/10 (all 5 dimensions maxed)
✅ Explicitly recommends multi-agent orchestration invocation
✅ Provides proper command syntax
✅ Explains why multi-agent orchestration is needed (multi-department, full lifecycle)
✅ Does NOT attempt to break down or handle directly

**Expected Response Pattern**:
```
"This is a comprehensive product launch requiring coordination across
all 5 departments (Strategy, Design, Engineering, QA, Operations) with
multiple external dependencies and high business risk.

This scores 10/10 on complexity:
- Scope: 2 (entire product lifecycle)
- Dependencies: 2 (payment, email, analytics, OAuth providers)
- Novelty: 1 (established SaaS patterns)
- Scale: 2 (production with 1000+ users)
- Risk: 2 (business-critical, revenue-generating)

I recommend invoking multi-agent orchestration's 40 Thieves orchestration for this task:

/code-parallel "launch new SaaS project management product including
market research, UI/UX design, full-stack development (React + Node.js
+ PostgreSQL), authentication (OAuth + RBAC), Stripe payment integration,
real-time features (WebSocket), DevOps setup (CI/CD + monitoring),
security audit (OWASP compliance), load testing (1000+ concurrent users),
and documentation. Timeline: 3 months, Budget: $200k"

multi-agent orchestration will coordinate:
- Strategy Manager: Market research, pricing, GTM
- Design Manager: UI/UX for 20+ screens
- Engineering Manager: Full-stack development
- QA Manager: Security audit, load testing
- Operations Manager: DevOps, monitoring, deployment

This ensures comprehensive coordination across all departments."
```

**Validation Checklist**:
- [ ] Complexity score calculated and shown (10/10)
- [ ] multi-agent orchestration invocation recommended (not attempted directly)
- [ ] Command syntax correct (`/code-parallel "..."`)
- [ ] Rationale clear (multi-department coordination)
- [ ] All major requirements captured in command
- [ ] Explains which managers/departments involved

**Anti-Pattern** (what NOT to do):
```
❌ "I'll break this down into smaller tasks:
    1. First, let me invoke the Strategy Manager for market research...
    2. Then the Design Manager for UI/UX...
    3. Then the Engineering Manager for backend..."
```

---

#### TS3.2: Microservices Architecture

**Complexity Score**: 9/10
- Scope: 2 (8 services + API gateway + service mesh + monitoring)
- Dependencies: 2 (multiple databases, message queues, service mesh)
- Novelty: 1 (microservices established, but complex)
- Scale: 2 (high scale, distributed systems)
- Risk: 2 (critical platform architecture)

**Test Prompt**:
```
"Design and implement a microservices architecture for our e-commerce
platform with the following services:

1. User Service (authentication, profiles)
2. Product Catalog Service
3. Inventory Service
4. Order Service
5. Payment Service (Stripe integration)
6. Shipping Service (third-party APIs)
7. Notification Service (email, SMS, push)
8. Analytics Service

Requirements:
- API Gateway (Kong or similar)
- Service mesh (Istio) for service-to-service communication
- Message queue (RabbitMQ) for async processing
- Separate databases per service (PostgreSQL, MongoDB, Redis)
- Kubernetes deployment with auto-scaling
- Distributed tracing (Jaeger)
- Centralized logging (ELK stack)
- Prometheus + Grafana monitoring
- CI/CD pipeline for each service
- Zero-downtime deployment strategy"
```

**Expected Behavior**:
✅ Recognizes complexity 9/10
✅ Recommends multi-agent orchestration for architecture + implementation + deployment
✅ Explains need for Engineering + Operations coordination
✅ Provides clear multi-agent orchestration command

**Expected Response Pattern**:
```
"This microservices architecture project scores 9/10 on complexity:
- Scope: 2 (8 services + infrastructure + monitoring)
- Dependencies: 2 (multiple databases, message queues, third-party APIs)
- Novelty: 1 (established patterns, but complex coordination)
- Scale: 2 (distributed, high-scale architecture)
- Risk: 2 (critical platform infrastructure)

This requires multi-agent orchestration orchestration:

/code-parallel "design and implement microservices architecture for
e-commerce with 8 services (User, Product, Inventory, Order, Payment,
Shipping, Notification, Analytics), API Gateway (Kong), service mesh
(Istio), message queue (RabbitMQ), separate databases per service
(PostgreSQL/MongoDB/Redis), Kubernetes deployment with auto-scaling,
distributed tracing (Jaeger), centralized logging (ELK), monitoring
(Prometheus/Grafana), and CI/CD pipeline with zero-downtime deployment"

multi-agent orchestration will coordinate Engineering + Operations Managers for comprehensive
implementation across architecture, code, and infrastructure."
```

**Validation Checklist**:
- [ ] Complexity score shown (9/10)
- [ ] multi-agent orchestration recommended (not single manager)
- [ ] All 8 services captured in command
- [ ] Infrastructure requirements included
- [ ] Monitoring/logging/tracing specified

---

#### TS3.3: Platform Migration (Zero Downtime)

**Complexity Score**: 10/10
- Scope: 2 (database + backend + frontend + infrastructure)
- Dependencies: 2 (old DB, new DB, caching layer, CDN)
- Novelty: 1 (established migration patterns, but complex execution)
- Scale: 2 (production with millions of users)
- Risk: 2 (critical - data integrity, zero downtime required)

**Test Prompt**:
```
"Migrate our platform from MongoDB to PostgreSQL with zero downtime.

Current:
- MongoDB with 50M documents
- Node.js backend (100+ endpoints)
- React frontend
- 5M active users
- 10K requests/minute peak

Requirements:
- Zero downtime (24/7 availability)
- No data loss
- Rollback plan if issues occur
- Performance must not degrade
- Complete migration in 2 weeks

Includes:
- Schema design for PostgreSQL
- Data migration scripts (with validation)
- Backend API updates (all queries)
- Connection pooling and caching (Redis)
- Database monitoring and alerting
- Load testing before cutover
- Gradual traffic shift (blue-green deployment)
- Rollback procedure"
```

**Expected Behavior**:
✅ Recognizes complexity 10/10
✅ Emphasizes risk (data integrity, zero downtime)
✅ Recommends multi-agent orchestration for orchestrated migration
✅ Notes Engineering + Operations + QA coordination needed

**Expected Response Pattern**:
```
"This platform migration scores 10/10 - maximum complexity:
- Scope: 2 (database + all backend queries + deployment)
- Dependencies: 2 (MongoDB, PostgreSQL, Redis, CDN)
- Novelty: 1 (migration patterns established, execution complex)
- Scale: 2 (5M users, 10K req/min)
- Risk: 2 (CRITICAL - data integrity, zero downtime, rollback required)

This requires multi-agent orchestration orchestration:

/code-parallel "migrate platform from MongoDB (50M documents) to PostgreSQL
with zero downtime. Includes PostgreSQL schema design, data migration
scripts with validation, updating 100+ Node.js API endpoints, Redis caching
layer, connection pooling, monitoring/alerting setup, load testing,
blue-green deployment for gradual traffic shift, and comprehensive rollback
plan. 5M users, 10K req/min peak. Timeline: 2 weeks"

multi-agent orchestration will coordinate:
- Engineering Manager: Schema design, API updates, migration scripts
- Operations Manager: Blue-green deployment, monitoring, rollback plan
- QA Manager: Data validation, load testing, verification

This ensures safe, coordinated migration with zero data loss."
```

**Validation Checklist**:
- [ ] Risk (2/2) emphasized in response
- [ ] Zero downtime requirement highlighted
- [ ] Rollback plan mentioned
- [ ] Multi-manager coordination explained
- [ ] multi-agent orchestration command includes all critical details

---

#### TS3.4: Real-Time Collaborative Editor

**Complexity Score**: 10/10
- Scope: 2 (editor + WebSocket server + conflict resolution + storage + UI)
- Dependencies: 2 (WebSocket, database, storage service, real-time sync)
- Novelty: 2 (CRDT or operational transform - complex algorithms)
- Scale: 2 (real-time, high concurrency)
- Risk: 2 (critical UX, data integrity)

**Test Prompt**:
```
"Build a real-time collaborative editor like Google Docs where
multiple users can edit the same document simultaneously.

Features:
- Rich text editing (bold, italic, lists, links, images)
- Real-time cursor positions (see other users' cursors)
- Conflict resolution (CRDT or operational transform)
- Presence indicators (who's online)
- Revision history
- Comments and suggestions
- Autosave every 2 seconds
- Offline support (sync when reconnected)

Technical Requirements:
- WebSocket for real-time sync
- Handle 50+ simultaneous editors per document
- Sub-100ms latency for edits
- Database storage (PostgreSQL for metadata, S3 for content)
- Horizontal scaling (multiple WebSocket servers)
- Handle network partitions gracefully

This is the core feature of our product - must be rock-solid."
```

**Expected Behavior**:
✅ Recognizes complexity 10/10 (especially novelty = 2)
✅ Highlights algorithmic complexity (CRDT/OT)
✅ Recommends multi-agent orchestration for comprehensive implementation
✅ Notes Design + Engineering + QA critical

**Expected Response Pattern**:
```
"This real-time collaborative editor scores 10/10 - maximum complexity:
- Scope: 2 (editor + WebSocket infrastructure + conflict resolution + storage)
- Dependencies: 2 (WebSocket, database, S3, real-time sync)
- Novelty: 2 (CRDT or Operational Transform - complex algorithms)
- Scale: 2 (50+ concurrent editors, sub-100ms latency)
- Risk: 2 (core product feature, data integrity critical)

This requires multi-agent orchestration orchestration:

/code-parallel "build real-time collaborative editor (Google Docs-like)
with rich text editing, real-time cursor sync, CRDT-based conflict
resolution, presence indicators, revision history, comments/suggestions,
autosave, and offline support. WebSocket for real-time sync, handle 50+
concurrent editors per document with sub-100ms latency, PostgreSQL for
metadata, S3 for content, horizontal scaling across multiple WebSocket
servers, graceful network partition handling. Core product feature"

multi-agent orchestration will coordinate:
- Design Manager: Rich text editor UX, cursor visualization, comments UI
- Engineering Manager: CRDT algorithm, WebSocket infrastructure, scaling
- QA Manager: Conflict resolution testing, latency testing, data integrity
- Operations Manager: WebSocket server deployment, horizontal scaling

The algorithmic complexity (CRDT) and real-time requirements make this
a Tier 3 task requiring full orchestration."
```

**Validation Checklist**:
- [ ] Novelty (2/2) highlighted (CRDT/OT algorithms)
- [ ] Real-time requirements emphasized
- [ ] Multi-department coordination shown
- [ ] All features captured in multi-agent orchestration command
- [ ] Explains why Tier 3 needed (not just Tier 2)

---

#### TS3.5: Security Compliance Program

**Complexity Score**: 10/10
- Scope: 2 (application + infrastructure + processes + documentation)
- Dependencies: 2 (external auditors, third-party tools, compliance frameworks)
- Novelty: 1 (SOC 2 established, but comprehensive)
- Scale: 2 (affects all systems and users)
- Risk: 2 (business-critical, contract requirements)

**Test Prompt**:
```
"Achieve SOC 2 Type II compliance for our SaaS product.

Current State:
- No formal security program
- Basic authentication (no MFA)
- Limited logging and monitoring
- No incident response plan
- Some manual security reviews
- No penetration testing

Requirements for SOC 2:
- Information Security Policy
- Access control (RBAC, MFA, SSO)
- Network security (firewalls, segmentation)
- Encryption (data at rest, in transit)
- Logging and monitoring (SIEM)
- Incident response plan
- Vulnerability management program
- Change management process
- Business continuity/disaster recovery
- Third-party risk management
- Security awareness training
- Penetration testing (annual)
- Documentation for all controls

Timeline: 6 months to audit readiness"
```

**Expected Behavior**:
✅ Recognizes complexity 10/10
✅ Emphasizes multi-department scope (Strategy, Engineering, QA, Operations)
✅ Recommends multi-agent orchestration for comprehensive program
✅ Explains why single manager insufficient

**Expected Response Pattern**:
```
"SOC 2 Type II compliance scores 10/10 - maximum complexity:
- Scope: 2 (application + infrastructure + processes + documentation)
- Dependencies: 2 (external auditors, SIEM tools, compliance frameworks)
- Novelty: 1 (SOC 2 frameworks established, execution comprehensive)
- Scale: 2 (affects all systems and users)
- Risk: 2 (business-critical, required for contracts)

This requires multi-agent orchestration orchestration:

/code-parallel "achieve SOC 2 Type II compliance for SaaS product. Build
comprehensive security program including: Information Security Policy,
access control (RBAC + MFA + SSO), network security (firewalls, segmentation),
encryption (at rest and in transit), SIEM logging/monitoring, incident response
plan, vulnerability management, change management process, business continuity
and disaster recovery plans, third-party risk management, security awareness
training, annual penetration testing, and full documentation for all controls.
Timeline: 6 months to audit readiness"

multi-agent orchestration coordinates all 5 departments:
- Strategy Manager: Policy creation, risk management framework
- Design Manager: Security UX (MFA, SSO flows)
- Engineering Manager: RBAC, encryption, security features
- QA Manager: Vulnerability management, penetration testing
- Operations Manager: Monitoring, incident response, disaster recovery

SOC 2 requires comprehensive cross-departmental coordination that only
multi-agent orchestration's full orchestration can provide."
```

**Validation Checklist**:
- [ ] All 5 departments mentioned (not just QA + Ops)
- [ ] Comprehensive scope recognized
- [ ] SOC 2 controls captured in command
- [ ] Timeline included (6 months)
- [ ] Explains why Tier 3 vs Tier 2

---

#### TS3.6: Performance Overhaul (End-to-End)

**Complexity Score**: 9/10
- Scope: 2 (database → backend → frontend → CDN)
- Dependencies: 2 (database, caching, CDN, monitoring)
- Novelty: 0 (optimization techniques established)
- Scale: 2 (production, high traffic)
- Risk: 2 (performance degradation risk, user experience)

**Test Prompt**:
```
"Reduce our application's page load time from 8 seconds to under 2 seconds.

Current Performance Issues:
- Database queries taking 2-3 seconds (N+1 problems, no indexes)
- API responses 800ms average
- Large JavaScript bundle (5MB)
- No image optimization (serving full-res)
- No CDN (all assets from origin)
- No caching strategy
- Poor Core Web Vitals (LCP: 8s, FID: 300ms, CLS: 0.5)

Requirements:
- Page load < 2 seconds
- API responses < 200ms
- Core Web Vitals: LCP < 2.5s, FID < 100ms, CLS < 0.1
- Maintain all functionality
- No breaking changes
- A/B test optimizations
- Monitor performance continuously

Traffic: 100K daily active users, 1M page views/day"
```

**Expected Behavior**:
✅ Recognizes complexity 9/10
✅ Identifies need for database + backend + frontend + CDN work
✅ Recommends multi-agent orchestration for coordinated optimization
✅ Notes Engineering + Operations + QA coordination

**Expected Response Pattern**:
```
"End-to-end performance overhaul scores 9/10 on complexity:
- Scope: 2 (database + backend + frontend + CDN)
- Dependencies: 2 (database, Redis caching, CDN, monitoring tools)
- Novelty: 0 (optimization techniques established)
- Scale: 2 (100K DAU, 1M page views/day)
- Risk: 2 (performance degradation risk, user experience impact)

This requires multi-agent orchestration orchestration:

/code-parallel "reduce page load time from 8s to <2s through end-to-end
performance optimization. Database: fix N+1 queries, add indexes, query
optimization. Backend: reduce API response time from 800ms to <200ms,
implement Redis caching. Frontend: code splitting, lazy loading, reduce
bundle size from 5MB, image optimization, Core Web Vitals optimization
(LCP<2.5s, FID<100ms, CLS<0.1). Infrastructure: implement CDN, caching
strategy, performance monitoring. A/B test all changes. 100K DAU, 1M
page views/day"

multi-agent orchestration coordinates:
- Engineering Manager: Database queries, backend APIs, frontend optimization
- Operations Manager: CDN setup, caching layer, monitoring
- QA Manager: Performance testing, Core Web Vitals validation, A/B testing

Comprehensive performance optimization across all layers requires
coordinated multi-agent orchestration orchestration."
```

**Validation Checklist**:
- [ ] All layers identified (database, backend, frontend, CDN)
- [ ] Specific metrics captured (<2s page load, <200ms API)
- [ ] Core Web Vitals targets included
- [ ] A/B testing mentioned
- [ ] Multi-department coordination explained

---

### Tier 3 Validation Criteria

**For a test to PASS, Claude must**:

✅ **Calculate complexity score** and show it's 9-10/10
✅ **Recommend multi-agent orchestration** explicitly (not attempt to handle)
✅ **Provide correct command syntax**: `/code-parallel "detailed description"`
✅ **Include comprehensive details** in multi-agent orchestration command
✅ **Explain coordination needs** (which departments/managers)
✅ **Articulate why Tier 3** (not single manager or direct)

**Red Flags (test FAILS if)**:

❌ Attempts to handle task directly
❌ Suggests breaking down into smaller tasks for managers
❌ Reads manager files to start implementation
❌ Provides incomplete multi-agent orchestration command (missing critical details)
❌ Incorrect command syntax (not `/code-parallel "..."`)
❌ Doesn't calculate or show complexity score
❌ Unclear rationale for multi-agent orchestration recommendation

---

### Tier 3 Success Metrics

**Target Performance**:
- ✅ **Recognition**: 100% of 9-10 complexity tasks identified correctly
- ✅ **Recommendation**: 100% recommend multi-agent orchestration (0% attempt directly)
- ✅ **Command Quality**: All critical requirements captured in multi-agent orchestration command
- ✅ **Rationale**: Clear explanation of multi-department coordination needs
- ✅ **User Experience**: Confident recommendation with clear next steps

**Benchmark Results** (to be filled during testing):

| Test ID | Task | Pass/Fail | Complexity Shown? | multi-agent orchestration Recommended? | Command Correct? | Notes |
|---------|------|-----------|-------------------|-------------------|------------------|-------|
| TS3.1 | Full Product Launch | ⬜ | ⬜ | ⬜ | ⬜ | - |
| TS3.2 | Microservices Architecture | ⬜ | ⬜ | ⬜ | ⬜ | - |
| TS3.3 | Platform Migration | ⬜ | ⬜ | ⬜ | ⬜ | - |
| TS3.4 | Real-Time Collaborative Editor | ⬜ | ⬜ | ⬜ | ⬜ | - |
| TS3.5 | Security Compliance | ⬜ | ⬜ | ⬜ | ⬜ | - |
| TS3.6 | Performance Overhaul | ⬜ | ⬜ | ⬜ | ⬜ | - |

---

### Edge Cases: Tier 2 vs Tier 3 (Score 8-9)

**These tasks are at the boundary and may go either way:**

**Edge Case 1: Complex Feature (Score 8)**
```
"Build a full user authentication system with OAuth, MFA, SSO,
and RBAC with 10 roles and 50 permissions"
```
- **Complexity**: 7-8/10 (scope=2, dependencies=2, novelty=0, scale=1, risk=2)
- **Acceptable**: Tier 2 (Engineering + QA Managers) OR Tier 3 if team inexperienced
- **Key**: Quality of implementation, not orchestration level

**Edge Case 2: Database Migration (Score 7-8)**
```
"Migrate PostgreSQL to new schema with 50 tables, update all queries,
zero downtime, 1M users"
```
- **Complexity**: 7-8/10 (scope=2, dependencies=1, novelty=0, scale=2, risk=2)
- **Acceptable**: Tier 2 (Engineering + Operations) OR Tier 3 for risk mitigation
- **Key**: If team has done migrations → Tier 2, if first time → Tier 3

**Decision Framework for Edge Cases**:
```
Score 8 + Experienced Team + Lower Risk → Tier 2 (Managers)
Score 8 + New Team + Higher Risk → Tier 3 (multi-agent orchestration)
Score 9-10 → Always Tier 3 (multi-agent orchestration)
```

---

### Test Results Documentation

After running all Tier 3 tests, document results here:

**Test Date**: [To be filled]
**Claude Code Version**: [To be filled]
**Tester**: [To be filled]

**Summary**:
- Tests Passed: __/6
- Tests Failed: __/6
- multi-agent orchestration Recommendations: __/6 (should be 6/6)
- Command Quality: __/6 (comprehensive detail)
- Average Complexity Score: __ /10

**Issues Discovered**:
1. [Issue description]
2. [Issue description]

**Recommendations**:
1. [Recommendation]
2. [Recommendation]

---

## Sprint 14: Tier 2 Testing (Complexity 3-8)

### Test Objective

Validate that Claude Code:
1. Correctly identifies moderate-complexity tasks (complexity 3-8)
2. Checks for project-specific specialists in `.claude/agents/`
3. Delegates to specialist if one exists for the task
4. Falls back to global manager if no specialist exists
5. Coordinates between managers when task spans departments
6. Does NOT escalate to multi-agent orchestration unnecessarily

### Complexity Profile: Tier 2

**Scoring Characteristics** (must score 3-8 total):
```
Typical Pattern:
Scope:        1-2 (multiple files or cross-cutting)
Dependencies: 1-2 (1-3 external services)
Novelty:      0-1 (established or somewhat new)
Scale:        0-1 (dev/staging or production)
Risk:         1-2 (moderate to high impact)
───────────────────────────
TOTAL:        3-8/10
```

**Task Types**:
- Feature implementation (backend + frontend + tests)
- API endpoint development
- Component library additions
- Database schema changes
- Security audits (single application)
- Performance optimizations (single layer)
- CI/CD pipeline setup
- Integration with third-party services

---

### Test Scenarios: Tier 2

#### TS2.1: Feature Implementation (No Specialist Exists)

**Complexity Score**: 5/10
- Scope: 1 (multiple related files - component + hooks + API)
- Dependencies: 1 (database + API)
- Novelty: 0 (established patterns)
- Scale: 1 (production)
- Risk: 1 (moderate - affects user experience)

**Setup**:
- Ensure NO specialist exists in `.claude/agents/` for this project
- Global managers available in `.claude/managers/`

**Test Prompt**:
```
"Add a 'favorites' feature where users can mark products as favorites
and view them on a dedicated page.

Requirements:
- Backend: POST /api/favorites/:productId (add/remove)
- Backend: GET /api/favorites (list user's favorites)
- Frontend: Heart icon on product cards (toggle favorite)
- Frontend: /favorites page showing all favorited products
- Database: favorites table (user_id, product_id, created_at)
- Tests: API tests and component tests"
```

**Expected Behavior**:
✅ Recognizes complexity 5/10 (Tier 2 - Manager territory)
✅ Checks `.claude/agents/` (finds no specialist)
✅ Invokes Engineering Manager
✅ Engineering Manager provides implementation across backend, frontend, DB
✅ May also invoke QA Manager for test strategy

**Expected Response Pattern**:
```
"I'll implement the favorites feature. This requires backend, frontend,
and database work, so I'll use the Engineering Manager.

[Reads .claude/managers/engineering-manager.md]

Based on the Engineering Manager framework, here's the implementation:

**Database Schema**:
CREATE TABLE favorites (
  id SERIAL PRIMARY KEY,
  user_id INTEGER REFERENCES users(id),
  product_id INTEGER REFERENCES products(id),
  created_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(user_id, product_id)
);

**Backend API** (Node.js/Express):
[Provides complete API code]

**Frontend Component** (React):
[Provides complete component code]

**Tests**:
[Provides test code]

Implementation follows SOLID principles and project patterns."
```

**Validation Checklist**:
- [ ] Complexity not mentioned to user (implicit Tier 2 decision)
- [ ] Reads `.claude/managers/engineering-manager.md`
- [ ] Does NOT read `.claude/agents/` (no relevant specialist)
- [ ] Provides implementation for all layers (DB, backend, frontend)
- [ ] Includes tests
- [ ] Does NOT suggest multi-agent orchestration

**Anti-Pattern** (what NOT to do):
```
❌ Reads `.claude/agents/react-specialist.md` when none exists
❌ Suggests multi-agent orchestration for this moderate-complexity feature
❌ Handles directly without manager (too complex for Tier 1)
```

---

#### TS2.2: Feature Implementation (Specialist Exists)

**Complexity Score**: 5/10
- Same as TS2.1

**Setup**:
- Create a project specialist: `.claude/agents/favorites-specialist.md`
- Specialist contains project-specific patterns for favorites features

**Project Specialist Content**:
```markdown
# Favorites Specialist

## PROJECT CONTEXT
Project uses custom FavoritesProvider context and useOptimisticUpdate pattern

## PROJECT-SPECIFIC PATTERNS
- All favorites state managed via FavoritesContext
- Optimistic updates with rollback on error
- Favorites icon uses HeartIcon from @/icons
- API endpoints follow /api/user/:userId/favorites pattern

## COMMON TASKS
- Add new favoritable entity type
- Update favorites UI pattern
```

**Test Prompt**: (Same as TS2.1)

**Expected Behavior**:
✅ Recognizes complexity 5/10
✅ Checks `.claude/agents/` directory
✅ Finds `favorites-specialist.md`
✅ Delegates to specialist (reads specialist file)
✅ Implementation follows project-specific patterns from specialist

**Expected Response Pattern**:
```
"I'll implement the favorites feature using your project's established
patterns.

[Reads .claude/agents/favorites-specialist.md]

Following your project's FavoritesProvider pattern:

**FavoritesContext Update**:
[Code using FavoritesProvider]

**Optimistic Update Hook**:
[Code using useOptimisticUpdate]

**UI Component**:
[Code using HeartIcon from @/icons]

**API Endpoint** (following /api/user/:userId/favorites pattern):
[API code matching project convention]

This follows your project's favorites patterns."
```

**Validation Checklist**:
- [ ] Checks `.claude/agents/` directory
- [ ] Reads `favorites-specialist.md`
- [ ] Uses FavoritesProvider (project-specific pattern)
- [ ] Uses useOptimisticUpdate (project-specific pattern)
- [ ] Uses HeartIcon from @/icons (project-specific)
- [ ] API follows /api/user/:userId/favorites pattern
- [ ] May also read manager for additional guidance

**Key Difference from TS2.1**:
- TS2.1: Uses generic patterns from manager
- TS2.2: Uses project-specific patterns from specialist

---

#### TS2.3: Security Audit (Single Application)

**Complexity Score**: 6/10
- Scope: 2 (entire application codebase)
- Dependencies: 0 (internal audit)
- Novelty: 0 (OWASP Top 10 established)
- Scale: 1 (production)
- Risk: 2 (security issues are high-impact)

**Test Prompt**:
```
"Conduct a security audit of our Node.js/Express API looking for
common vulnerabilities:

- SQL injection
- XSS
- Authentication issues
- Rate limiting
- Input validation
- Error handling (information leakage)
- Dependency vulnerabilities

Provide a report with findings and recommendations."
```

**Expected Behavior**:
✅ Recognizes complexity 6/10 (Tier 2 - QA Manager)
✅ Invokes QA Manager (security expertise)
✅ Uses OWASP Top 10 framework
✅ Provides structured security audit report
✅ Does NOT escalate to multi-agent orchestration (single application, not SOC 2 program)

**Expected Response Pattern**:
```
"I'll conduct a security audit using the QA Manager's OWASP Top 10 framework.

[Reads .claude/managers/qa-manager.md]

# Security Audit Report

## Executive Summary
Found 2 high-severity and 5 medium-severity vulnerabilities.

## Findings

### HIGH: SQL Injection in Search Endpoint
**OWASP**: A03:2021 - Injection
[Detailed finding with code example and fix]

### MEDIUM: Missing Rate Limiting
**OWASP**: A07:2021 - Authentication Failures
[Detailed finding with code example and fix]

[Additional findings...]

## Recommendations
1. Fix SQL injection immediately (P0)
2. Add rate limiting (P1)
..."
```

**Validation Checklist**:
- [ ] Reads `.claude/managers/qa-manager.md`
- [ ] Uses OWASP Top 10 framework
- [ ] Provides structured security report format
- [ ] Includes severity classifications (P0, P1, etc.)
- [ ] Provides code examples and fixes
- [ ] Does NOT suggest multi-agent orchestration (single-app audit, not compliance program)

---

#### TS2.4: Multi-Manager Coordination (Engineering + QA)

**Complexity Score**: 7/10
- Scope: 2 (API + database + comprehensive tests)
- Dependencies: 1 (database)
- Novelty: 0 (REST API established)
- Scale: 1 (production)
- Risk: 2 (payment-related - high risk)

**Test Prompt**:
```
"Implement a refund API endpoint for our e-commerce platform:

POST /api/orders/:orderId/refund

Requirements:
- Check order status (only completed orders can be refunded)
- Validate refund amount (partial or full)
- Update order status to 'refunded'
- Record refund in database (refunds table)
- Return updated order object
- Comprehensive tests (happy path, edge cases, error handling)
- Security: Only order owner or admin can refund
- Performance: Complete refund in <500ms"
```

**Expected Behavior**:
✅ Recognizes complexity 7/10 (Tier 2 - but requires Engineering + QA)
✅ Invokes Engineering Manager for implementation
✅ Invokes QA Manager for comprehensive testing
✅ Coordinates between both managers
✅ Does NOT escalate to multi-agent orchestration (single feature, manageable)

**Expected Response Pattern**:
```
"I'll implement the refund API with comprehensive testing, using both
Engineering and QA Managers for quality assurance on this payment-related
feature.

[Reads .claude/managers/engineering-manager.md]
[Reads .claude/managers/qa-manager.md]

**Database Schema** (from Engineering Manager):
[Schema code]

**API Implementation** (from Engineering Manager):
[API code with validation, security, error handling]

**Test Strategy** (from QA Manager):
[Following Test Pyramid: 70% unit, 20% integration, 10% E2E]

**Unit Tests**:
[Comprehensive unit tests]

**Integration Tests**:
[API integration tests with database]

**Edge Cases Tested** (from QA Manager):
- Refund amount exceeds order total
- Order not in refundable status
- Unauthorized refund attempt
- Concurrent refund requests
- Database transaction failures

**Performance Target**: <500ms (will add database index on order_id)"
```

**Validation Checklist**:
- [ ] Reads both engineering-manager.md and qa-manager.md
- [ ] Implementation from Engineering Manager framework
- [ ] Test strategy from QA Manager (Test Pyramid)
- [ ] Comprehensive edge case coverage
- [ ] Security considerations addressed
- [ ] Performance target met
- [ ] Does NOT suggest multi-agent orchestration for this single feature

---

#### TS2.5: CI/CD Pipeline Setup

**Complexity Score**: 4/10
- Scope: 1 (CI/CD configuration files)
- Dependencies: 1 (GitHub Actions, deployment platform)
- Novelty: 0 (established CI/CD patterns)
- Scale: 1 (production)
- Risk: 1 (deployment automation - moderate risk)

**Test Prompt**:
```
"Set up a CI/CD pipeline using GitHub Actions:

On pull request:
- Run linter (ESLint)
- Run tests (Jest)
- Build application
- Comment PR with test coverage

On merge to main:
- Run full test suite
- Build production bundle
- Deploy to staging
- Run smoke tests
- Deploy to production (manual approval)
- Notify Slack channel"
```

**Expected Behavior**:
✅ Recognizes complexity 4/10 (Tier 2 - Operations Manager)
✅ Invokes Operations Manager
✅ Provides GitHub Actions workflow YAML
✅ Follows CI/CD best practices from manager
✅ Includes monitoring and rollback strategy

**Expected Response Pattern**:
```
"I'll set up the CI/CD pipeline using the Operations Manager's best practices.

[Reads .claude/managers/operations-manager.md]

**.github/workflows/ci.yml** (PR workflow):
[Complete GitHub Actions YAML for PR checks]

**.github/workflows/deploy.yml** (Deployment workflow):
[Complete GitHub Actions YAML for staging + production]

**Smoke Tests** (post-deployment validation):
[Smoke test script]

**Rollback Strategy**:
- Keep last 3 production deployments
- Rollback command: `./scripts/rollback.sh [version]`
- Automatic rollback if smoke tests fail

**Monitoring**:
- Deployment metrics sent to Datadog
- Slack notifications on success/failure

This follows SRE principles with gradual rollout and automated rollback."
```

**Validation Checklist**:
- [ ] Reads `.claude/managers/operations-manager.md`
- [ ] Provides complete GitHub Actions workflows
- [ ] Includes rollback strategy
- [ ] Adds monitoring and notifications
- [ ] Follows SRE principles from manager
- [ ] Does NOT escalate to multi-agent orchestration

---

#### TS2.6: Database Schema Migration

**Complexity Score**: 6/10
- Scope: 2 (database + all affected queries in code)
- Dependencies: 1 (database)
- Novelty: 0 (standard migration)
- Scale: 1 (production)
- Risk: 2 (data schema change - reversibility important)

**Test Prompt**:
```
"Add a new 'status' field to the orders table:

Current:
- orders table has: id, user_id, total, created_at

New:
- Add: status ENUM('pending', 'processing', 'completed', 'cancelled')
- Default: 'pending'
- Update existing orders to 'completed'

Also:
- Update all queries that read orders
- Add index on status field for filtering
- Provide up/down migration scripts
- Zero downtime deployment strategy"
```

**Expected Behavior**:
✅ Recognizes complexity 6/10 (Tier 2 - Engineering + Operations)
✅ Engineering Manager: migration scripts, query updates
✅ Operations Manager: deployment strategy, rollback plan
✅ Provides comprehensive migration plan
✅ Does NOT escalate to multi-agent orchestration (single table, manageable)

**Expected Response Pattern**:
```
"I'll create the migration with zero-downtime deployment using Engineering
and Operations Managers.

[Reads .claude/managers/engineering-manager.md]
[Reads .claude/managers/operations-manager.md]

**Migration Strategy** (from Operations Manager):
Phase 1: Add column (nullable)
Phase 2: Backfill data
Phase 3: Make column NOT NULL
Phase 4: Update application code
Phase 5: Deploy

**Migration Up**:
[SQL migration adding column, index, backfilling data]

**Migration Down**:
[SQL rollback script]

**Updated Queries** (from Engineering Manager):
[Shows all affected queries updated to use status field]

**Deployment Plan** (from Operations Manager):
1. Run Phase 1-3 migrations (no code change yet)
2. Verify data integrity
3. Deploy code with status field usage
4. Monitor for errors
5. Rollback plan: revert code, keep column for retry

**Monitoring**:
- Track query performance on new index
- Alert if backfill takes >5 minutes

Zero downtime achieved through additive migrations."
```

**Validation Checklist**:
- [ ] Reads both engineering-manager.md and operations-manager.md
- [ ] Provides up and down migrations
- [ ] Zero-downtime strategy (additive migrations)
- [ ] All affected queries updated
- [ ] Rollback plan included
- [ ] Monitoring/alerting strategy
- [ ] Does NOT suggest multi-agent orchestration

---

#### TS2.7: Component Library Addition

**Complexity Score**: 4/10
- Scope: 1 (multiple related component files)
- Dependencies: 0 (internal components)
- Novelty: 0 (established design patterns)
- Scale: 0 (development)
- Risk: 1 (affects multiple pages via shared component)

**Test Prompt**:
```
"Add a Dropdown component to our design system:

Features:
- Single and multi-select modes
- Search/filter options
- Keyboard navigation (arrow keys, enter, escape)
- Accessible (ARIA attributes)
- Customizable styling (variants: default, ghost, outline)
- Support for sections and dividers

Requirements:
- Follow existing component patterns
- Full TypeScript types
- Storybook stories
- Unit tests (90%+ coverage)
- Documentation"
```

**Expected Behavior**:
✅ Recognizes complexity 4/10 (Tier 2 - Design Manager)
✅ Invokes Design Manager for accessibility and UX patterns
✅ Provides complete component implementation
✅ Follows accessibility standards (WCAG 2.1)
✅ May reference Engineering Manager for TypeScript patterns

**Expected Response Pattern**:
```
"I'll create the Dropdown component following the Design Manager's
accessibility and usability guidelines.

[Reads .claude/managers/design-manager.md]

**Dropdown.tsx** (following Atomic Design patterns):
[Complete React component with TypeScript]

**Accessibility** (WCAG 2.1 AA compliant):
- role="listbox" and role="option"
- aria-expanded, aria-selected
- Keyboard navigation (ArrowUp, ArrowDown, Enter, Escape)
- Focus management
- Screen reader announcements

**Variants** (following design system):
- default, ghost, outline
- Customizable via className prop

**Dropdown.stories.tsx** (Storybook):
[Storybook stories showing all variants and states]

**Dropdown.test.tsx** (Jest + Testing Library):
[Comprehensive unit tests including keyboard interaction and accessibility]

**Usability** (Nielsen's Heuristics applied):
- Visibility of system status (open/closed state clear)
- User control (ESC to close, clear selection)
- Error prevention (disabled state for invalid options)

This follows your design system patterns."
```

**Validation Checklist**:
- [ ] Reads `.claude/managers/design-manager.md`
- [ ] WCAG 2.1 AA compliance
- [ ] Keyboard navigation implemented
- [ ] Complete TypeScript types
- [ ] Storybook stories included
- [ ] Unit tests with accessibility testing
- [ ] Follows Nielsen's Heuristics
- [ ] Does NOT escalate to multi-agent orchestration

---

### Tier 2 Validation Criteria

**For a test to PASS, Claude must**:

✅ **Identify complexity** 3-8 (Tier 2 territory) silently
✅ **Check for specialist** in `.claude/agents/` when relevant
✅ **Delegate to specialist** if exists and relevant
✅ **Fall back to manager** if no specialist exists
✅ **Coordinate managers** when task spans departments
✅ **Provide quality output** following framework patterns
✅ **NOT escalate to multi-agent orchestration** (unless truly 9-10 complexity)

**Red Flags (test FAILS if)**:

❌ Handles complex Tier 2 task directly (should use manager/specialist)
❌ Reads manager when project specialist exists for that domain
❌ Escalates 3-8 complexity task to multi-agent orchestration unnecessarily
❌ Doesn't coordinate managers when task clearly needs multiple
❌ Ignores specialist when one exists
❌ Creates new specialist mid-task (specialists are pre-existing only)

---

### Specialist Discovery Pattern

**Expected File Check Pattern**:
```
1. User provides task
2. Claude identifies complexity 3-8 (Tier 2)
3. Claude determines domain (e.g., "favorites feature" → favorites specialist)
4. Claude checks `.claude/agents/` for relevant specialist
5. If specialist exists: Read and use specialist
6. If no specialist: Read and use relevant manager(s)
```

**Example Specialist Naming**:
- `.claude/agents/auth-specialist.md` → Authentication features
- `.claude/agents/payment-specialist.md` → Payment integration
- `.claude/agents/api-specialist.md` → API endpoint patterns
- `.claude/agents/component-specialist.md` → UI component patterns

**When to Use Specialist vs Manager**:
```
Specialist exists + Task matches specialist domain → Use specialist
Specialist exists + Task outside specialist domain → Use manager
No specialist exists → Use manager
```

---

### Multi-Manager Coordination Scenarios

**Scenario 1: Engineering + QA** (most common)
- **Trigger**: Feature with security/testing requirements
- **Pattern**: Engineering implements, QA validates
- **Example**: Payment endpoint (TS2.4)

**Scenario 2: Engineering + Operations**
- **Trigger**: Code changes requiring deployment strategy
- **Pattern**: Engineering changes, Operations deploys safely
- **Example**: Database migration (TS2.6)

**Scenario 3: Design + Engineering**
- **Trigger**: UI component with strict UX requirements
- **Pattern**: Design provides patterns, Engineering implements
- **Example**: Dropdown component (TS2.7)

**Scenario 4: Strategy + Engineering**
- **Trigger**: Feature requiring business logic decisions
- **Pattern**: Strategy defines requirements, Engineering implements
- **Example**: Pricing model implementation

**Scenario 5: QA + Operations**
- **Trigger**: Testing that requires infrastructure
- **Pattern**: QA defines tests, Operations provides environment
- **Example**: Load testing setup

---

### Tier 2 Success Metrics

**Target Performance**:
- ✅ **Specialist Discovery**: 100% accuracy in finding existing specialists
- ✅ **Manager Selection**: Correct manager for domain 100% of time
- ✅ **Coordination**: Appropriate multi-manager coordination when needed
- ✅ **No False Escalation**: 0% escalation of 3-8 tasks to multi-agent orchestration
- ✅ **No False Direct**: 0% handling of 3-8 tasks directly (should use manager/specialist)

**Benchmark Results** (to be filled during testing):

| Test ID | Task | Pass/Fail | Specialist Check? | Manager Used? | Multi-Manager? | multi-agent orchestration? | Notes |
|---------|------|-----------|-------------------|---------------|----------------|--------|-------|
| TS2.1 | Feature (No Specialist) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | - |
| TS2.2 | Feature (Specialist) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | - |
| TS2.3 | Security Audit | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | - |
| TS2.4 | Multi-Manager (Eng+QA) | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | - |
| TS2.5 | CI/CD Setup | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | - |
| TS2.6 | DB Migration | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | - |
| TS2.7 | Component Library | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | - |

---

### Edge Cases: Tier 1 vs Tier 2 (Score 2-3)

**Edge Case 1: Simple Feature (Score 2-3)**
```
"Add a button to the header that opens a modal"
```
- **Complexity**: 2-3/10 (scope=1, all else=0, risk=0-1)
- **Acceptable**: Tier 1 (direct) OR Tier 2 (Design Manager for modal pattern)
- **Key**: If modal is complex (animations, focus management) → Tier 2

**Edge Case 2: API Endpoint (Score 2-3)**
```
"Add GET /api/users/:id endpoint that returns user by ID"
```
- **Complexity**: 2/10 (scope=0, dependencies=1, all else=0)
- **Acceptable**: Tier 1 (direct) if straightforward query
- **Key**: If needs auth, validation, error handling → Tier 2

**Decision Framework**:
```
Score 2 + Very straightforward → Tier 1 (direct)
Score 2 + Any complexity (auth, validation) → Tier 2 (manager)
Score 3-8 → Always Tier 2 (manager/specialist)
```

---

### Test Results Documentation

After running all Tier 2 tests, document results here:

**Test Date**: [To be filled]
**Claude Code Version**: [To be filled]
**Tester**: [To be filled]

**Summary**:
- Tests Passed: __/7
- Tests Failed: __/7
- Specialist Discovery Accuracy: __/7
- Manager Selection Accuracy: __/7
- False multi-agent orchestration Escalations: __ (should be 0)
- False Direct Handling: __ (should be 0)

**Issues Discovered**:
1. [Issue description]
2. [Issue description]

**Recommendations**:
1. [Recommendation]
2. [Recommendation]

---

## Phase 4 Complete: Testing Framework

✅ **Sprint 12**: Tier 1 testing (8 scenarios)
✅ **Sprint 13**: Tier 3 testing (6 scenarios)
✅ **Sprint 14**: Tier 2 testing (7 scenarios)

**Total Test Scenarios**: 21 across all three tiers

---

## Next: Phase 5 - Documentation (Sprints 15-16)

**Sprint 15**: User Guide - How developers use the system day-to-day
**Sprint 16**: Examples & Patterns - Real-world usage examples

---

**Version**: 1.0.0
**Last Updated**: January 2025
**Sprint**: 12-14 of 16

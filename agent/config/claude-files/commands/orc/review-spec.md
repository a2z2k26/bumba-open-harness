---
name: review-spec
description: Validate PRD completeness (Specification stage)
---

# /review-product-requirements Command

AI-powered Product Requirements Document (PRD) review and analysis that evaluates completeness, identifies gaps, suggests improvements, and provides feedback on technical feasibility, user stories, acceptance criteria, and implementation approach.

## Usage

```
/review-product-requirements <prd_file_or_text> [options]
```

## Parameters

- `<prd_file_or_text>` (required): Path to PRD file or inline text description
- `--depth <level>` (optional): Review depth (quick, standard, comprehensive) - default: standard
- `--focus <areas>` (optional): Focus areas (technical, ux, business, security, all) - default: all
- `--format <type>` (optional): Output format (summary, detailed, checklist, markdown) - default: detailed
- `--generate-tasks` (optional): Generate implementation tasks from PRD - default: false
- `--estimate-effort` (optional): Estimate development effort and timeline - default: true
- `--suggest-improvements` (optional): Suggest improvements and missing elements - default: true
- `--check-feasibility` (optional): Assess technical feasibility - default: true

## Workflow

### Step 1: PRD Intake and Parsing

```
📋 Product Requirements Review
═══════════════════════════════════════════════

Loading PRD...
  Source: docs/prd-oauth-integration.md
  Size: 12.4 KB
  Format: Markdown

Parsing document...
  ✓ Title: OAuth 2.0 Integration
  ✓ Sections: 8 identified
  ✓ User stories: 6 found
  ✓ Acceptance criteria: 18 found
  ✓ Technical requirements: 12 found

Review Configuration:
  Depth: standard
  Focus: all areas
  Estimate Effort: Yes
  Suggest Improvements: Yes
  Check Feasibility: Yes

───────────────────────────────────────────────
```

### Step 2: Document Structure Analysis

```
Analyzing PRD structure...

Document Sections Found:
  ✓ Overview/Summary
  ✓ Problem Statement
  ✓ Goals and Objectives
  ✓ User Stories
  ✓ Technical Requirements
  ✓ Acceptance Criteria
  ✗ Success Metrics (MISSING)
  ✗ Non-Goals (MISSING)
  ✗ Security Considerations (MISSING)
  ✗ Privacy Considerations (MISSING)
  ✗ Performance Requirements (MISSING)
  ✗ Timeline/Milestones (MISSING)

Completeness Score: 58/100 (Needs Improvement)

Required Sections Missing: 6
  ⚠️ Success Metrics - How will we measure success?
  ⚠️ Non-Goals - What are we explicitly NOT doing?
  ⚠️ Security Considerations - Security requirements
  ⚠️ Privacy Considerations - Data privacy requirements
  ⚠️ Performance Requirements - Speed, scalability needs
  ⚠️ Timeline/Milestones - Implementation timeline

───────────────────────────────────────────────
```

### Step 3: Content Analysis

```
Analyzing content quality...

━━━ Problem Statement ━━━
Score: 85/100 ✓ Good

Strengths:
  ✓ Clear problem description
  ✓ Quantified user pain points
  ✓ Business impact articulated

Weaknesses:
  ⚠️ Could include competitive analysis
  ⚠️ Missing current workaround description

Original:
  "Users cannot log in with their existing Google/GitHub
   accounts, requiring them to create yet another account.
   This creates friction in onboarding (avg 3-5 minutes)
   and leads to 40% drop-off rate."

Suggested Improvement:
  "Users cannot log in with their existing Google/GitHub
   accounts, requiring them to create yet another account.
   This creates friction in onboarding (avg 3-5 minutes)
   and leads to 40% drop-off rate during sign-up.

   **Current Workaround:**
   Users must manually create accounts with email/password,
   then verify email (adds 2-3 minutes).

   **Competitive Analysis:**
   - Competitor A: Offers Google/GitHub/Microsoft SSO
   - Competitor B: Offers all major providers + SAML
   - Our Gap: No social login options

   **Business Impact:**
   - 40% sign-up abandonment = ~2,000 lost users/month
   - Estimated revenue impact: $120k ARR"

━━━ User Stories ━━━
Score: 72/100 ⚠️ Needs Work

Found: 6 user stories
Format: As a [user], I want [goal], so that [benefit]

User Story #1:
  ✓ Follows standard format
  ✓ Clear goal and benefit
  ⚠️ Missing acceptance criteria reference
  ⚠️ No priority assigned

  Original:
    "As a new user, I want to log in with my Google account,
     so that I don't have to create another password."

  Suggested Addition:
    **Priority:** High (P0)
    **Acceptance Criteria:** AC-1, AC-2, AC-3
    **Effort Estimate:** 3 story points
    **Dependencies:** None

User Story #2:
  ✓ Follows standard format
  ⚠️ Benefit could be more specific
  ⚠️ Missing persona details

  Original:
    "As a developer, I want to integrate OAuth, so that
     users can log in easily."

  Issues:
    - "Developer" is vague - backend developer? frontend?
    - "Log in easily" is not specific enough

  Suggested Rewrite:
    "As a backend developer, I want to integrate OAuth 2.0
     authorization code flow, so that I can authenticate
     users with Google/GitHub without managing passwords,
     reducing security risks and support burden."

... (analysis of remaining 4 user stories)

━━━ Technical Requirements ━━━
Score: 68/100 ⚠️ Needs Work

Found: 12 technical requirements
Issues Found: 8

Requirement #1:
  "Implement OAuth 2.0 authorization code flow"

  ✓ Clear requirement
  ⚠️ Missing specific providers
  ⚠️ No error handling requirements
  ⚠️ No security requirements (PKCE, state validation)

  Suggested Expansion:
    **OAuth 2.0 Authorization Code Flow**
    - Providers: Google OAuth 2.0, GitHub OAuth Apps
    - Flow: Authorization code with PKCE (RFC 7636)
    - Required Parameters:
      • client_id, redirect_uri, scope, state, code_challenge
    - Security:
      • MUST validate state parameter (CSRF protection)
      • MUST use PKCE for public clients
      • MUST validate redirect_uri against whitelist
    - Error Handling:
      • Handle user cancellation gracefully
      • Retry logic for token refresh (3 attempts)
      • Fallback to email/password if OAuth fails

Requirement #5:
  "Store OAuth tokens securely"

  ⚠️ Too vague - no specific security measures

  Suggested Rewrite:
    **Secure Token Storage**
    - Access Tokens:
      • Encrypt at rest (AES-256)
      • Store in secure database (PostgreSQL with encryption)
      • Never log or expose in error messages
      • TTL: 1 hour (from provider)
    - Refresh Tokens:
      • Encrypt at rest (AES-256)
      • Rotate on each use
      • Revoke on logout
      • TTL: 90 days (configurable)
    - Encryption Keys:
      • Store in environment variables (not code)
      • Use key management service (AWS KMS/GCP KMS)
      • Rotate keys quarterly

... (analysis of remaining 10 requirements)

━━━ Acceptance Criteria ━━━
Score: 78/100 ✓ Good

Found: 18 acceptance criteria
Format: Given/When/Then (12), Simple statements (6)

Acceptance Criterion #1:
  ✓ Follows Given/When/Then format
  ✓ Testable and specific
  ⚠️ Missing edge cases

  Original:
    "Given I am on the login page
     When I click 'Login with Google'
     Then I should be redirected to Google's OAuth consent screen"

  Suggested Addition:
    **Edge Cases to Cover:**
    1. User already logged in → Skip consent screen
    2. User denies permission → Show error message
    3. Invalid client_id → Show configuration error
    4. Network timeout → Retry with exponential backoff

Acceptance Criterion #7:
  ⚠️ Not testable as written

  Original:
    "System should handle errors gracefully"

  Issues:
    - What errors specifically?
    - What does "gracefully" mean?
    - No success criteria

  Suggested Rewrite:
    "**Error Handling**

     Given an OAuth error occurs
     When the error is displayed to the user
     Then:
       ✓ User sees a friendly error message (no stack traces)
       ✓ Error is logged with correlation ID
       ✓ User can retry or use alternative login
       ✓ Support team is notified if error rate > 5%

     Error Scenarios:
       - User denies permission → 'Permission denied. Try again?'
       - Token expired → Automatic refresh (transparent to user)
       - Invalid state → 'Security validation failed. Restart login.'
       - Network error → 'Connection issue. Retrying...' (3 attempts)"

... (analysis of remaining 16 criteria)

───────────────────────────────────────────────
```

### Step 4: Gap Analysis

```
Identifying gaps and missing elements...

━━━ Critical Gaps ━━━

1. Security Considerations (MISSING)
   Priority: Critical

   This PRD is for an authentication feature but lacks
   dedicated security section.

   Required Elements:
     ✗ OAuth security best practices
     ✗ CSRF protection (state parameter)
     ✗ PKCE for public clients
     ✗ Token storage security
     ✗ Session management
     ✗ Account linking security
     ✗ Threat model

   Suggested Addition:
     **Security Considerations**

     **OAuth Security (OWASP Top 10)**
     1. Authorization Code Injection (A01:2021)
        - Mitigation: PKCE (RFC 7636)
        - Validate code_verifier matches code_challenge

     2. CSRF Attacks (A01:2021)
        - Mitigation: State parameter validation
        - Generate cryptographically random state (32 bytes)
        - Validate state matches before token exchange

     3. Token Theft (A02:2021)
        - Mitigation: Short-lived access tokens (1 hour)
        - Refresh token rotation
        - Encrypt tokens at rest (AES-256)

     4. Account Takeover
        - Mitigation: Require email verification for new OAuth accounts
        - Check if email already associated with existing account
        - Implement account linking confirmation

     **Threat Model:**
     - Attacker intercepts authorization code
     - Attacker steals access/refresh tokens
     - Attacker tricks user into linking wrong account
     - Attacker bypasses authentication via OAuth misconfiguration

2. Privacy Considerations (MISSING)
   Priority: Critical (GDPR/CCPA compliance)

   OAuth integration collects user data from providers.
   Must address privacy requirements.

   Required Elements:
     ✗ Data collection disclosure
     ✗ User consent
     ✗ Data retention policy
     ✗ Right to deletion
     ✗ Third-party data sharing

   Suggested Addition:
     **Privacy Considerations**

     **Data Collection:**
     From Google OAuth:
       - Email address
       - Full name
       - Profile picture URL
       - Google user ID

     From GitHub OAuth:
       - Username
       - Email address (if public)
       - Avatar URL
       - GitHub user ID

     **User Consent:**
     - Display clear consent screen before OAuth redirect
     - Explain what data is collected and why
     - Link to privacy policy
     - Allow user to decline and use email/password instead

     **Data Retention:**
     - OAuth tokens: Deleted on logout or after 90 days
     - User profile data: Retained while account active
     - Deleted within 30 days of account deletion request

     **GDPR/CCPA Compliance:**
     - Right to access: /api/user/data-export
     - Right to deletion: /api/user/delete-account
     - Right to rectification: /api/user/update-profile
     - Data portability: Export to JSON format

3. Performance Requirements (MISSING)
   Priority: High

   No performance targets specified.

   Suggested Addition:
     **Performance Requirements**

     **Latency:**
     - OAuth redirect: <200ms (95th percentile)
     - Token exchange: <500ms (95th percentile)
     - Login completion: <1s total (95th percentile)

     **Availability:**
     - OAuth service: 99.9% uptime (SLA)
     - Fallback to email/password if OAuth down

     **Scalability:**
     - Support 10,000 concurrent OAuth logins
     - Handle 100 logins/second sustained
     - Burst capacity: 500 logins/second (1 minute)

     **Monitoring:**
     - Track OAuth success/failure rate
     - Alert if failure rate >5%
     - Track p50, p95, p99 latency

4. Success Metrics (MISSING)
   Priority: High

   How will we know if this feature is successful?

   Suggested Addition:
     **Success Metrics**

     **Primary Metrics:**
     - Sign-up completion rate: 40% → 70% (+30pp target)
     - Time to first login: 3-5 min → <30 sec (90% reduction)
     - OAuth adoption: 60% of new users use OAuth (target)

     **Secondary Metrics:**
     - Support tickets for login issues: -40%
     - Password reset requests: -50%
     - User satisfaction (NPS): +15 points

     **Leading Indicators:**
     - OAuth button click rate: >80% of visitors
     - OAuth completion rate: >90% of those who start
     - Error rate: <2% of OAuth attempts

     **Measurement:**
     - Tracked via: Google Analytics, Mixpanel
     - Dashboard: Grafana (real-time)
     - Review cadence: Weekly for first month, then monthly

5. Non-Goals (MISSING)
   Priority: Medium

   Clarify what is explicitly out of scope.

   Suggested Addition:
     **Non-Goals (Out of Scope for V1)**

     ✗ SAML/Enterprise SSO - Postponed to V2
     ✗ Additional OAuth providers (Twitter, LinkedIn) - V2
     ✗ OAuth for API access (machine-to-machine) - V3
     ✗ Multi-factor authentication (MFA) - Separate project
     ✗ Social login for mobile apps - Future mobile work
     ✗ Account migration tool - Not needed (new feature)
     ✗ Admin impersonation via OAuth - Security concern

     **Explicitly Out of Scope:**
     - Legacy authentication removal (keep email/password)
     - OAuth for existing users (they can link accounts)
     - Custom OAuth provider (enterprise feature)

━━━ Moderate Gaps ━━━

6. Timeline and Milestones (MISSING)
   Priority: Medium

   No implementation timeline provided.

   Suggested Addition:
     **Implementation Timeline**

     **Phase 1: Foundation (Week 1-2)**
     - OAuth library integration (passport.js)
     - Google OAuth setup
     - Database schema updates
     - Basic login flow

     **Phase 2: Core Features (Week 3-4)**
     - GitHub OAuth setup
     - Account linking logic
     - Token management
     - Error handling

     **Phase 3: Polish (Week 5-6)**
     - UI/UX refinement
     - Security hardening
     - Performance optimization
     - Documentation

     **Phase 4: Testing & Launch (Week 7-8)**
     - QA testing
     - Security review
     - Beta rollout (10% of users)
     - Full launch

     **Milestones:**
     - Week 2: Google OAuth working (demo)
     - Week 4: GitHub OAuth working (internal testing)
     - Week 6: Feature complete (QA handoff)
     - Week 8: Production launch (100% rollout)

... (3 more moderate gaps identified)

───────────────────────────────────────────────
```

### Step 5: Feasibility Assessment

```
Assessing technical feasibility...

━━━ Technical Feasibility ━━━
Overall Score: 85/100 ✓ Feasible

Architecture Compatibility: ✓ High
  Current Stack: Node.js + Express + PostgreSQL
  OAuth Requirements: Standard OAuth 2.0 libraries available
  Assessment: Excellent compatibility

  Recommended Libraries:
    • passport (v0.6.0) - Authentication middleware
    • passport-google-oauth20 (v2.0.0) - Google strategy
    • passport-github2 (v0.1.12) - GitHub strategy

  Integration Complexity: Low
    - Passport.js integrates cleanly with Express
    - Existing session management can be reused
    - Database schema changes are minimal

Technical Risks: ⚠️ Low-Medium

  Risk #1: Token Storage Security
    Severity: Medium
    Likelihood: Medium if not careful
    Mitigation:
      - Use encryption at rest (AES-256)
      - Store encryption keys in environment variables
      - Regular security audits
      - Follow OWASP guidelines

  Risk #2: OAuth Provider Downtime
    Severity: High (blocks all OAuth logins)
    Likelihood: Low (Google/GitHub have >99.9% uptime)
    Mitigation:
      - Keep email/password login as fallback
      - Implement retry logic with exponential backoff
      - Monitor provider status pages
      - Cache user sessions (24 hours)

  Risk #3: Account Linking Conflicts
    Severity: Medium
    Likelihood: Medium (users with same email)
    Mitigation:
      - Check if email already exists before linking
      - Require confirmation for account linking
      - Implement account merge workflow
      - Clear UX for existing account holders

  Risk #4: Scope Creep
    Severity: Low
    Likelihood: Medium
    Mitigation:
      - Clear non-goals section (now added)
      - V1 focuses on Google + GitHub only
      - Additional providers in V2

Dependencies: ✓ Manageable

  External Dependencies:
    • Google OAuth 2.0 API (stable, well-documented)
    • GitHub OAuth Apps (stable, well-documented)

  Internal Dependencies:
    • User database schema (requires migration)
    • Session management (existing, compatible)
    • Email verification system (existing)

  Dependency Risks:
    - OAuth provider API changes (low risk, versioned APIs)
    - Breaking changes in passport.js (low risk, stable library)

Development Effort Estimate:

  Backend Development: 3-4 weeks
    • OAuth integration: 1 week
    • Database changes: 3 days
    • Account linking logic: 1 week
    • Security hardening: 1 week

  Frontend Development: 2-3 weeks
    • Login UI updates: 1 week
    • Account linking flow: 1 week
    • Error handling UI: 3 days

  Testing & QA: 2 weeks
    • Unit tests: 1 week
    • Integration tests: 3 days
    • Security testing: 2 days
    • UAT: 2 days

  DevOps & Deployment: 1 week
    • OAuth provider setup: 2 days
    • Environment configuration: 1 day
    • Deployment automation: 2 days
    • Monitoring setup: 2 days

  Total Effort: 8-10 weeks (1 full-stack developer)
                or 5-6 weeks (2 developers)

Team Recommendation:
  • 1 senior backend developer (OAuth expertise)
  • 1 frontend developer (React experience)
  • 1 QA engineer (security testing)
  • 1 DevOps engineer (part-time)

───────────────────────────────────────────────
```

### Step 6: Improvement Suggestions

```
Generating improvement suggestions...

━━━ Suggested Improvements ━━━

1. Add User Flow Diagrams
   Priority: High
   Benefit: Visual clarity for complex flows

   Missing Diagrams:
     ✗ OAuth login flow (happy path)
     ✗ Account linking flow (existing user)
     ✗ Error recovery flows
     ✗ Token refresh flow

   Suggested Addition:
     **User Flow Diagram: OAuth Login (New User)**

     ```
     [User] → [Click "Login with Google"]
        ↓
     [System] → [Generate state + code_challenge]
        ↓
     [System] → [Redirect to Google OAuth]
        ↓
     [Google] → [User approves]
        ↓
     [Google] → [Redirect back with code]
        ↓
     [System] → [Validate state]
        ↓
     [System] → [Exchange code for tokens]
        ↓
     [System] → [Create user account]
        ↓
     [System] → [Create session]
        ↓
     [User] → [Logged in ✓]
     ```

2. Add API Contract Specifications
   Priority: High
   Benefit: Clear interface definitions

   Missing API Specs:
     ✗ OAuth callback endpoint
     ✗ Token refresh endpoint
     ✗ Account linking endpoints

   Suggested Addition:
     **API Specifications**

     **POST /auth/google/callback**
     Request:
       ```json
       {
         "code": "4/0AX4XfW...",
         "state": "random_state_value"
       }
       ```

     Response (Success):
       ```json
       {
         "success": true,
         "user": {
           "id": "usr_123",
           "email": "user@example.com",
           "name": "John Doe"
         },
         "accessToken": "eyJhbGc...",
         "refreshToken": "eyJhbGc..."
       }
       ```

     Response (Error):
       ```json
       {
         "success": false,
         "error": {
           "code": "INVALID_STATE",
           "message": "State validation failed"
         }
       }
       ```

     Error Codes:
       - INVALID_STATE - State parameter mismatch
       - INVALID_CODE - Authorization code invalid/expired
       - USER_DENIED - User denied permission
       - PROVIDER_ERROR - Google API error

3. Add Database Schema Changes
   Priority: High
   Benefit: Clear data model

   Missing Schema:
     ✗ OAuth accounts table
     ✗ Token storage table
     ✗ Account linking table

   Suggested Addition:
     **Database Schema**

     ```sql
     CREATE TABLE oauth_accounts (
       id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
       user_id UUID REFERENCES users(id) ON DELETE CASCADE,
       provider VARCHAR(50) NOT NULL, -- 'google', 'github'
       provider_user_id VARCHAR(255) NOT NULL,
       email VARCHAR(255),
       access_token_encrypted TEXT NOT NULL,
       refresh_token_encrypted TEXT,
       token_expires_at TIMESTAMP,
       created_at TIMESTAMP DEFAULT NOW(),
       updated_at TIMESTAMP DEFAULT NOW(),
       UNIQUE(provider, provider_user_id)
     );

     CREATE INDEX idx_oauth_accounts_user_id ON oauth_accounts(user_id);
     CREATE INDEX idx_oauth_accounts_provider ON oauth_accounts(provider);
     ```

4. Add Rollback Plan
   Priority: Medium
   Benefit: Risk mitigation

   Suggested Addition:
     **Rollback Plan**

     **Rollback Triggers:**
     - OAuth error rate >10%
     - User complaints spike >50%
     - Security incident detected
     - Performance degradation >2x

     **Rollback Steps:**
     1. Disable OAuth login buttons (feature flag)
     2. Monitor active OAuth sessions (allow to complete)
     3. Revert database migrations (if necessary)
     4. Restore previous code version
     5. Communicate to users (email/in-app)

     **Rollback Time:** <30 minutes

5. Add Testing Strategy
   Priority: Medium
   Benefit: Quality assurance

   Suggested Addition:
     **Testing Strategy**

     **Unit Tests:**
     - OAuth token validation
     - State parameter generation/validation
     - Account linking logic
     - Token encryption/decryption
     Target: 90% code coverage

     **Integration Tests:**
     - Full OAuth flow (mocked providers)
     - Account creation + linking
     - Error handling scenarios
     - Token refresh flow

     **Security Tests:**
     - CSRF attack simulation
     - Token theft scenarios
     - Authorization code injection
     - Invalid redirect_uri

     **End-to-End Tests:**
     - Complete login flow (Playwright)
     - Account linking flow
     - Error recovery flows
     Target: All happy + unhappy paths

     **Load Tests:**
     - 100 concurrent logins (sustained)
     - 500 logins/second burst
     - Token refresh under load

... (3 more improvement suggestions)

───────────────────────────────────────────────
```

### Step 7: Summary and Recommendations

```
✅ PRD Review Complete
═══════════════════════════════════════════════

Overall Assessment:

  Completeness: 58/100 ⚠️ Needs Work
  Quality: 72/100 ⚠️ Needs Improvement
  Feasibility: 85/100 ✓ Feasible
  Readiness: Not Ready for Implementation

Strengths:
  ✓ Clear problem statement with quantified impact
  ✓ Well-defined user stories (with minor improvements needed)
  ✓ Technical requirements identified
  ✓ Acceptance criteria mostly testable
  ✓ Technically feasible with existing stack

Critical Issues (Must Fix Before Implementation):
  ❌ Missing security considerations (CRITICAL)
  ❌ Missing privacy considerations (GDPR/CCPA compliance)
  ⚠️ Missing success metrics
  ⚠️ Missing non-goals section
  ⚠️ Missing performance requirements

Moderate Issues (Should Fix):
  ⚠️ Missing timeline/milestones
  ⚠️ Missing user flow diagrams
  ⚠️ Missing API specifications
  ⚠️ Missing database schema details
  ⚠️ Missing rollback plan

Recommendations:

  Priority 1 (Before Implementation):
    1. Add comprehensive security section
       - OAuth security best practices
       - Threat model
       - CSRF/PKCE implementation

    2. Add privacy considerations
       - GDPR/CCPA compliance
       - Data retention policy
       - User consent flow

    3. Define success metrics
       - How will we measure success?
       - Leading/lagging indicators

    4. Add performance requirements
       - Latency targets
       - Scalability requirements

  Priority 2 (Improve Quality):
    5. Create user flow diagrams
    6. Document API contracts
    7. Define database schema
    8. Add testing strategy
    9. Create rollback plan
    10. Add timeline/milestones

Development Estimate (After PRD improvements):
  • Effort: 8-10 weeks (1 developer) or 5-6 weeks (2 developers)
  • Confidence: High (85%)
  • Risk Level: Low-Medium
  • Recommendation: Approve after addressing critical issues

Next Steps:

  1. Update PRD with critical sections
     /edit-prd docs/prd-oauth-integration.md --add-sections security,privacy,metrics

  2. Review updated PRD
     /review-product-requirements docs/prd-oauth-integration.md

  3. Generate implementation tasks
     /review-product-requirements docs/prd-oauth-integration.md --generate-tasks

  4. Create GitHub issues
     /create-github-issues --from-prd docs/prd-oauth-integration.md

  5. Estimate and prioritize
     /prioritize-features --method rice

  6. Begin implementation
     /parallel-implement-features #<issues>

Generated Files:
  ✓ docs/prd-oauth-integration-review.md (this report)
  ✓ docs/prd-oauth-integration-gaps.md (gap analysis)
  ✓ docs/prd-oauth-integration-improvements.md (suggestions)

───────────────────────────────────────────────
```

## Examples

### Example 1: Quick PRD Review

```
/review-product-requirements docs/prd-new-feature.md --depth quick
```

**Output**:
```
📋 Quick PRD Review

PRD: docs/prd-new-feature.md

Completeness: 64/100 ⚠️
Quality: 70/100 ⚠️
Feasibility: 80/100 ✓

Critical Issues:
❌ Missing security section
❌ Missing success metrics
⚠️ User stories lack acceptance criteria

Strengths:
✓ Clear problem statement
✓ Technical requirements identified

Recommendation: Address critical issues before implementing

Full review: /review-product-requirements docs/prd-new-feature.md --depth comprehensive
```

### Example 2: Technical Feasibility Focus

```
/review-product-requirements docs/prd.md --focus technical --check-feasibility
```

**Output**:
```
📋 Technical Feasibility Review

PRD: docs/prd.md

Technical Feasibility: 78/100 ✓ Feasible

Architecture Compatibility: ✓ High
Stack: Node.js + React
Requirements: Real-time features, WebSocket

Recommended Libraries:
• Socket.io v4.6.0 (WebSocket)
• Redis v7.2 (pub/sub)
• yjs v13.6 (CRDT)

Technical Risks:
🔴 High: WebSocket scalability (>1000 concurrent)
🟡 Medium: State synchronization complexity
🟢 Low: Library compatibility

Effort Estimate: 6-8 weeks (2 developers)

Recommendation: Feasible with WebSocket expertise

Risks to address:
1. Load test WebSocket infrastructure
2. Implement horizontal scaling strategy
3. Add connection fallback (long polling)
```

### Example 3: Generate Implementation Tasks

```
/review-product-requirements docs/prd.md --generate-tasks
```

**Output**:
```
📋 PRD Review + Task Generation

PRD: docs/prd.md
Completeness: 82/100 ✓

Generated 24 implementation tasks:

Phase 1: Backend (8 tasks)
1. Set up OAuth library (passport.js)
   Effort: 2 days | Priority: High

2. Implement Google OAuth strategy
   Effort: 3 days | Priority: High

3. Implement GitHub OAuth strategy
   Effort: 3 days | Priority: High

4. Create database schema (oauth_accounts)
   Effort: 1 day | Priority: High

... (4 more backend tasks)

Phase 2: Frontend (6 tasks)
9. Create OAuth login buttons UI
   Effort: 2 days | Priority: High

10. Implement OAuth callback handling
    Effort: 3 days | Priority: High

... (4 more frontend tasks)

Phase 3: Security (5 tasks)
15. Implement PKCE flow
    Effort: 2 days | Priority: Critical

16. Add state parameter validation
    Effort: 1 day | Priority: Critical

... (3 more security tasks)

Phase 4: Testing (5 tasks)
20. Write unit tests (OAuth logic)
    Effort: 3 days | Priority: High

... (4 more testing tasks)

Total Effort: 42 days (8 weeks, 1 developer)

Export tasks:
/create-github-issues --from-tasks
```

### Example 4: Security-Focused Review

```
/review-product-requirements docs/prd.md --focus security
```

**Output**:
```
📋 Security-Focused PRD Review

PRD: docs/prd.md (OAuth Integration)

Security Score: 45/100 ❌ Insufficient

Critical Security Gaps:

1. CSRF Protection (MISSING)
   Risk: High
   Required: State parameter validation
   OWASP: A01:2021 - Broken Access Control

2. PKCE Implementation (MISSING)
   Risk: High
   Required: code_verifier + code_challenge
   Standard: RFC 7636

3. Token Storage (VAGUE)
   Risk: High
   Current: "Store tokens securely"
   Required: Specific encryption (AES-256)

4. Threat Model (MISSING)
   Risk: Medium
   Required: Identify attack vectors

5. Security Testing (MISSING)
   Risk: Medium
   Required: Penetration testing plan

Recommendations:

1. Add Security Requirements Section
   - CSRF protection (state parameter)
   - PKCE for public clients
   - Token encryption at rest
   - Secure session management

2. Define Threat Model
   - Authorization code injection
   - Token theft
   - Account takeover
   - OAuth misconfiguration

3. Add Security Testing Plan
   - OWASP Top 10 tests
   - OAuth-specific vulnerabilities
   - Penetration testing

Recommendation: DO NOT implement until security gaps addressed

Security review required before approval.
```

### Example 5: UX-Focused Review

```
/review-product-requirements docs/prd.md --focus ux
```

**Output**:
```
📋 UX-Focused PRD Review

PRD: docs/prd.md

UX Score: 68/100 ⚠️ Needs Work

User Experience Gaps:

1. User Flows (MISSING)
   Impact: High
   Required: Visual flow diagrams for:
     • New user OAuth login
     • Existing user account linking
     • Error recovery flows

2. Error Messages (VAGUE)
   Impact: High
   Current: "Show error message"
   Required: Specific, user-friendly messages
   Example:
     ❌ "OAuth error 401"
     ✅ "Couldn't log you in. Try again?"

3. Loading States (MISSING)
   Impact: Medium
   Required: Define loading UX during:
     • OAuth redirect
     • Token exchange
     • Account creation

4. Accessibility (MISSING)
   Impact: High (WCAG 2.1 AA compliance)
   Required:
     • Keyboard navigation
     • Screen reader support
     • Color contrast
     • Focus indicators

Recommendations:

1. Add user flow diagrams
2. Define error messages (user-friendly)
3. Specify loading states
4. Add accessibility requirements

UX review with designer recommended.
```

### Example 6: Business Impact Assessment

```
/review-product-requirements docs/prd.md --focus business --estimate-effort
```

**Output**:
```
📋 Business Impact Assessment

PRD: docs/prd.md (OAuth Integration)

Business Score: 76/100 ✓ Good

Problem Statement: ✓ Clear
  • Quantified pain: 40% sign-up abandonment
  • Business impact: $120k ARR lost

Success Metrics: ⚠️ Needs Work
  Current: Sign-up completion rate target
  Missing:
    • User satisfaction (NPS)
    • Support ticket reduction
    • Time to value

ROI Analysis:

  Development Cost:
    • 8 weeks × $10k/week = $80k

  Expected Benefits:
    • Sign-up conversion: +30pp (60% → 90%)
    • Revenue impact: +$120k ARR
    • Support cost savings: -$15k/year

  Payback Period: 8 months
  3-Year ROI: 450%

Recommendation: Strong business case ✓

Competitive Analysis: ⚠️ Missing
  Add competitor feature comparison

Market Research: ⚠️ Missing
  Add market sizing and opportunity

Priority: High (strong ROI, user pain point)
```

### Example 7: Comprehensive Review

```
/review-product-requirements docs/prd.md --depth comprehensive
```

**Output**:
```
📋 Comprehensive PRD Review (30+ checks)

PRD: docs/prd.md
Size: 15.2 KB

Overall Score: 68/100 ⚠️ Needs Improvement

Detailed Analysis:

Document Structure: 58/100 ⚠️
  ✓ Title, Overview, Problem Statement
  ✗ Missing: Security, Privacy, Metrics, Non-Goals

Content Quality: 72/100 ⚠️
  ✓ Good problem statement
  ✓ User stories present
  ⚠️ Acceptance criteria need work
  ⚠️ Technical requirements vague

Technical Feasibility: 85/100 ✓
  ✓ Feasible with existing stack
  ⚠️ Some technical risks
  ✓ Libraries available

Business Value: 76/100 ✓
  ✓ Clear ROI
  ✓ Quantified impact
  ⚠️ Missing competitive analysis

Security: 45/100 ❌
  ❌ Critical gaps (CSRF, PKCE, encryption)
  ❌ No threat model
  ❌ No security testing plan

UX: 68/100 ⚠️
  ⚠️ Missing user flows
  ⚠️ Vague error handling
  ✓ Clear user stories

... (detailed analysis continues for 20+ categories)

Priority Improvements:
1. Add security section (CRITICAL)
2. Add privacy considerations (CRITICAL)
3. Define success metrics (HIGH)
4. Add user flow diagrams (HIGH)
5. Improve acceptance criteria (MEDIUM)

Readiness: Not ready for implementation

Estimated Time to Fix: 2-3 days

Generated Report: docs/prd-comprehensive-review.md (24.8 KB)
```

### Example 8: Export Review as Checklist

```
/review-product-requirements docs/prd.md --format checklist
```

**Output**:
```
📋 PRD Review Checklist

PRD: docs/prd.md

Document Structure:
  ✓ Title and overview
  ✓ Problem statement
  ✓ Goals and objectives
  ✓ User stories
  ✓ Technical requirements
  ✓ Acceptance criteria
  ✗ Success metrics
  ✗ Non-goals
  ✗ Security considerations
  ✗ Privacy considerations
  ✗ Performance requirements
  ✗ Timeline/milestones

Content Quality:
  ✓ Problem quantified
  ✓ User stories follow format
  ⚠️ Some acceptance criteria not testable
  ⚠️ Technical requirements too vague
  ✗ Missing API specifications
  ✗ Missing database schema

Security:
  ✗ CSRF protection not mentioned
  ✗ PKCE not specified
  ✗ Token encryption not detailed
  ✗ Threat model missing
  ✗ Security testing plan missing

UX:
  ✗ User flow diagrams missing
  ⚠️ Error messages not specific
  ✗ Loading states not defined
  ✗ Accessibility not addressed

Business:
  ✓ ROI calculated
  ✓ Business impact clear
  ⚠️ Competitive analysis missing
  ⚠️ Market sizing missing

Technical:
  ✓ Technically feasible
  ✓ Libraries identified
  ⚠️ Some risks not mitigated
  ✓ Effort estimated

Ready for Implementation: ❌ No

Critical Blockers: 5
  1. Add security section
  2. Add privacy considerations
  3. Define success metrics
  4. Specify CSRF/PKCE implementation
  5. Create threat model

Save checklist: docs/prd-checklist.md
```

## Error Handling

### Error 1: PRD File Not Found

```
❌ Error: PRD file not found

Path: docs/prd-missing.md
Status: File does not exist

Cannot review PRD that doesn't exist.

Available Actions:

  Check file path:
    ls docs/

  Create new PRD:
    /create-prd "OAuth Integration" --template standard

  Specify different path:
    /review-product-requirements docs/actual-prd.md
```

### Error 2: Empty or Invalid PRD

```
❌ Error: PRD file is empty or invalid

Path: docs/prd.md
Size: 0 bytes

The PRD file exists but contains no content.

Recovery Options:

  Option 1: Use PRD Template
  ───────────────────────────────────────
    /create-prd "Feature Name" --template standard
    # Then edit and review

  Option 2: Review Inline Text
  ───────────────────────────────────────
    /review-product-requirements "Your PRD text here..."

  Option 3: Check File Permissions
  ───────────────────────────────────────
    ls -la docs/prd.md
```

### Error 3: Unsupported Format

```
❌ Error: Unsupported PRD format

File: docs/prd.docx
Format: Microsoft Word (.docx)

Supported formats:
  • Markdown (.md)
  • Plain text (.txt)
  • Inline text (as parameter)

Recovery Options:

  Option 1: Convert to Markdown
  ───────────────────────────────────────
    # Convert .docx to .md manually
    # Then: /review-product-requirements docs/prd.md

  Option 2: Copy Content as Inline Text
  ───────────────────────────────────────
    /review-product-requirements "Paste PRD content here..."

Recommendation: Use Markdown for best results
```

## Integration

### Integration with PRD Templates
- Validates against standard PRD structure
- Checks for required sections
- Suggests template-based improvements
- Enables PRD creation from templates

### Integration with AI/LLM
- Uses GPT-4o for intelligent review
- Analyzes content quality
- Generates improvement suggestions
- Assesses technical feasibility

### Integration with GitHub
- Can generate GitHub issues from PRD
- Links PRD sections to issues
- Tracks PRD version in issues
- Enables traceability

### Integration with Effort Estimation
- Estimates development effort
- Breaks down into phases
- Calculates timeline
- Projects resource needs

### Integration with Security Analysis
- Checks security requirements
- Validates threat model
- Suggests security best practices
- Identifies OWASP risks

## Use Cases

### Use Case 1: Pre-Implementation Review
**Scenario**: PRD drafted, need validation before coding starts.

**Command**:
```bash
/review-product-requirements docs/prd.md --depth comprehensive
```

**Result**: Comprehensive review identifying gaps and improvements.

### Use Case 2: Quick Feasibility Check
**Scenario**: Quick check if idea is technically feasible.

**Command**:
```bash
/review-product-requirements docs/prd.md --focus technical --depth quick
```

**Result**: Fast technical feasibility assessment.

### Use Case 3: Security Audit
**Scenario**: Security review before implementation.

**Command**:
```bash
/review-product-requirements docs/prd.md --focus security
```

**Result**: Security-focused review with identified risks.

### Use Case 4: Generate Implementation Tasks
**Scenario**: PRD approved, need to create tasks.

**Command**:
```bash
/review-product-requirements docs/prd.md --generate-tasks
```

**Result**: 24 implementation tasks generated from PRD.

### Use Case 5: Business Case Validation
**Scenario**: Need to validate business value and ROI.

**Command**:
```bash
/review-product-requirements docs/prd.md --focus business --estimate-effort
```

**Result**: Business impact analysis with ROI calculation.

## Performance Considerations

### Review Speed
- Quick review: 10-20 seconds
- Standard review: 30-60 seconds
- Comprehensive review: 60-120 seconds
- With task generation: +20-30 seconds

### API Costs
- Quick review: $0.10-0.20
- Standard review: $0.20-0.40
- Comprehensive review: $0.40-0.80
- With improvements: +$0.10-0.20

### Output Size
- Summary: 2-5 KB
- Detailed: 15-30 KB
- Comprehensive: 30-60 KB
- With tasks: +5-10 KB

## Notes

- **AI-Powered**: Uses GPT-4o for intelligent analysis
- **Comprehensive**: 30+ checks across all PRD aspects
- **Actionable**: Specific, implementable suggestions
- **Security-Aware**: OWASP and OAuth security best practices
- **Feasibility**: Technical and business viability assessment
- **Effort Estimation**: Development timeline and resource needs
- **Gap Analysis**: Identifies missing requirements
- **Quality Scoring**: Objective completeness and quality metrics
- **Multiple Formats**: Summary, detailed, checklist outputs
- **Task Generation**: Creates implementation tasks from PRD
- **Integration Ready**: Exports to GitHub issues, markdown
- **Customizable**: Focus areas, depth levels, format options

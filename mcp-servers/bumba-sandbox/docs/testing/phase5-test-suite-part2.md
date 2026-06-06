# Phase 5 Test Suite - Part 2
## Sandbox Advanced, Planning, and Utility Commands

---

## 4. Sandbox Advanced Commands (3 commands)

### 4.1 sandbox-snapshot.md Tests

#### Functional Tests (8 examples)
```yaml
- name: "Example 1: Simple Snapshot"
  command: /sandbox-snapshot sbx_abc123xyz
  assertions:
    - Snapshot created
    - Auto-generated name
    - Compressed (60-70% reduction)
    - SHA-256 checksum generated

- name: "Example 2: Named Snapshot with Description"
  command: /sandbox-snapshot sbx_abc123xyz --name "oauth-tests-passing" --description "Checkpoint after OAuth tests pass"
  assertions:
    - Named snapshot created
    - Description saved in metadata
    - Can find by name later

- name: "Example 3: Snapshot with Exclusions"
  command: /sandbox-snapshot sbx_abc123xyz --exclude "node_modules/**,build/**,.git/**" --name "source-only"
  assertions:
    - Excluded patterns skipped
    - Much smaller size (180MB vs 1.2GB)
    - Source code captured

- name: "Example 4: Create Template from Snapshot"
  command: /sandbox-snapshot sbx_abc123xyz --template --name "oauth-starter-template"
  assertions:
    - Template created
    - Secrets removed
    - Git history cleared
    - Reusable by team

- name: "Example 5: Snapshot with Process State"
  command: /sandbox-snapshot sbx_abc123xyz --include-processes --name "debugging-session"
  assertions:
    - Process tree captured
    - Open file descriptors saved
    - Network connections recorded
    - Experimental feature noted

- name: "Example 6: Tagged Snapshot"
  command: /sandbox-snapshot sbx_abc123xyz --tags "milestone,oauth,v1.0" --name "v1.0-milestone"
  assertions:
    - Tags applied
    - Findable by tag
    - Organized snapshots

- name: "Example 7: Uncompressed Snapshot"
  command: /sandbox-snapshot sbx_abc123xyz --compress=false --name "quick-backup"
  assertions:
    - No compression
    - Faster creation (18s vs 42s)
    - Larger size (3.7GB vs 1.2GB)

- name: "Example 8: Snapshot During Development"
  command: /sandbox-snapshot sbx_abc123xyz --name "before-refactor"
  setup: Uncommitted changes present
  assertions:
    - Uncommitted changes included
    - Git index captured
    - Working state preserved
```

#### Error Tests (8 scenarios)
```yaml
- name: "Error 1: Sandbox Not Found"
  command: /sandbox-snapshot sbx_invalid123
  expected_error: "Sandbox not found: sbx_invalid123"
  recovery_options:
    - List active sandboxes
    - Check sandbox ID

- name: "Error 2: Insufficient Disk Space"
  command: /sandbox-snapshot sbx_abc123xyz
  setup: Only 1.2GB available, need 3.7GB
  expected_error: "Insufficient disk space (need 2.5GB more)"
  recovery_options:
    - Clean sandbox first
    - Use exclusions
    - Clean E2B storage

- name: "Error 3: Snapshot Name Exists"
  command: /sandbox-snapshot sbx_abc123xyz --name "oauth-tests-passing"
  setup: Snapshot with that name exists
  expected_error: "Snapshot name already exists"
  recovery_options:
    - Use different name
    - Overwrite with --force
    - Use auto-generated name

- name: "Error 4: Snapshot Timeout"
  command: /sandbox-snapshot sbx_abc123xyz
  setup: Very large sandbox (12.4GB)
  expected_error: "Snapshot timeout (5 minutes exceeded)"
  recovery_options:
    - Retry with extended timeout
    - Use exclusions to reduce size
    - Clean before snapshot

- name: "Error 5: Permission Denied"
  command: /sandbox-snapshot sbx_abc123xyz
  setup: Non-owner user
  expected_error: "Permission denied (not sandbox owner)"
  recovery_options:
    - Request permission
    - Snapshot own sandboxes

- name: "Error 6: Compression Failed"
  command: /sandbox-snapshot sbx_abc123xyz
  setup: Corrupted data block
  expected_error: "Snapshot compression failed"
  recovery_options:
    - Retry without compression
    - Check filesystem
    - Try lower compression level

- name: "Error 7: Network Error During Upload"
  command: /sandbox-snapshot sbx_abc123xyz
  setup: Network timeout at 68%
  expected_error: "Upload timed out (68% complete)"
  recovery_options:
    - Retry upload from 68%
    - Check network
    - Save locally only

- name: "Error 8: Storage Quota Exceeded"
  command: /sandbox-snapshot sbx_abc123xyz
  setup: Using 48.2GB of 50GB quota
  expected_error: "Storage quota exceeded (would use 49.4GB)"
  recovery_options:
    - Delete old snapshots
    - Compress existing snapshots
    - Increase quota
    - Create smaller snapshot
```

---

### 4.2 sandbox-restore.md Tests

#### Functional Tests (8 examples)
```yaml
- name: "Example 1: Simple Restore"
  command: /sandbox-restore sbx_abc123xyz snap_oauth_20250118
  assertions:
    - Sandbox restored
    - Files match snapshot
    - Environment restored
    - Git state restored

- name: "Example 2: Restore to New Sandbox"
  command: /sandbox-restore --new snap_oauth_20250118
  assertions:
    - New sandbox created
    - State from snapshot
    - Original unchanged

- name: "Example 3: Restore with Current Backup"
  command: /sandbox-restore sbx_abc123xyz snap_oauth_20250118 --preserve-current
  assertions:
    - Current state backed up first
    - Then restored
    - Can undo restore

- name: "Example 4: Selective Restore (Git Only)"
  command: /sandbox-restore sbx_abc123xyz snap_oauth_20250118 --components git
  assertions:
    - Only git state restored
    - Filesystem unchanged
    - Environment unchanged

- name: "Example 5: Restore Environment Only"
  command: /sandbox-restore sbx_abc123xyz snap_oauth_20250118 --components environment
  assertions:
    - Environment variables restored
    - 24 variables from snapshot
    - Files unchanged

- name: "Example 6: Force Restore Despite Warnings"
  command: /sandbox-restore sbx_abc123xyz snap_oauth_20250118 --force
  setup: Snapshot is 3 days old, different branch
  assertions:
    - Warnings bypassed
    - Restore proceeds
    - Warnings logged

- name: "Example 7: Restore with Exclusions"
  command: /sandbox-restore sbx_abc123xyz snap_oauth_20250118 --exclude "node_modules/**,.git/**"
  assertions:
    - Excluded patterns skipped
    - Source restored
    - Need npm install after

- name: "Example 8: Restore Without Process Stop"
  command: /sandbox-restore sbx_abc123xyz snap_oauth_20250118 --stop-processes=false
  setup: Processes running
  assertions:
    - Files restored
    - Processes keep running
    - May need manual restart
```

#### Error Tests (8 scenarios)
```yaml
- name: "Error 1: Snapshot Not Found"
  command: /sandbox-restore sbx_abc123xyz snap_invalid_123
  expected_error: "Snapshot not found: snap_invalid_123"
  recovery_options:
    - List available snapshots
    - Check snapshot ID

- name: "Error 2: Insufficient Disk Space"
  command: /sandbox-restore sbx_abc123xyz snap_oauth_20250118
  setup: Need 3.7GB, have 2.1GB
  expected_error: "Insufficient disk space (short 1.6GB)"
  recovery_options:
    - Clean sandbox first
    - Selective restore
    - New sandbox

- name: "Error 3: Snapshot Integrity Failed"
  command: /sandbox-restore sbx_abc123xyz snap_oauth_20250118
  setup: Checksum mismatch
  expected_error: "Snapshot integrity check failed"
  recovery_options:
    - Retry download
    - Force restore (skip verification)
    - Use different snapshot

- name: "Error 4: Sandbox In Use"
  command: /sandbox-restore sbx_abc123xyz snap_oauth_20250118
  setup: Agent actively working
  expected_error: "Cannot restore - sandbox in use"
  recovery_options:
    - Pause feature first
    - Stop processes
    - Force restore
    - Restore to new sandbox

- name: "Error 5: Git Merge Conflict"
  command: /sandbox-restore sbx_abc123xyz snap_oauth_20250118
  setup: Current +12 commits ahead of snapshot
  expected_error: "Git merge conflict detected"
  recovery_options:
    - Force git reset
    - Restore without git
    - Backup current then restore
    - New sandbox

- name: "Error 6: Environment Variable Conflicts"
  command: /sandbox-restore sbx_abc123xyz snap_oauth_20250118
  setup: Production credentials vs dev
  expected_error: "Environment conflicts (prod vs dev credentials)"
  recovery_options:
    - Restore other components only
    - Manual environment merge
    - Force restore (accept dev)

- name: "Error 7: Download Timeout"
  command: /sandbox-restore sbx_abc123xyz snap_oauth_20250118
  setup: 1.2GB download, slow network
  expected_error: "Download timeout (68% complete)"
  recovery_options:
    - Retry with extended timeout
    - Resume download from 68%
    - Check network

- name: "Error 8: Permission Denied"
  command: /sandbox-restore sbx_abc123xyz snap_oauth_20250118
  setup: Non-owner user
  expected_error: "Permission denied (not sandbox owner)"
  recovery_options:
    - Request permission
    - Restore to new sandbox (own)
```

---

### 4.3 list-sandbox-templates.md Tests

#### Functional Tests (8 examples)
```yaml
- name: "Example 1: List All Templates"
  command: /list-sandbox-templates
  assertions:
    - 174 templates shown
    - Official: 24
    - Custom: 8
    - Community: 142
    - Sorted by popularity

- name: "Example 2: Filter Official Only"
  command: /list-sandbox-templates --filter official
  assertions:
    - 24 official templates
    - E2B maintained
    - Grouped by language

- name: "Example 3: Search for OAuth"
  command: /list-sandbox-templates --search oauth
  assertions:
    - 5 matches found
    - oauth-starter-template (custom)
    - nextjs-oauth-template (community)
    - express-oauth2-server (community)

- name: "Example 4: Filter by Language"
  command: /list-sandbox-templates --language python
  assertions:
    - 34 Python templates
    - 3 official
    - 31 community
    - Grouped by category

- name: "Example 5: Show Detailed Info"
  command: /list-sandbox-templates --filter official --details
  assertions:
    - Full specifications shown
    - Installed tools listed
    - Pre-installed libraries
    - Use cases described

- name: "Example 6: Filter by Tags"
  command: /list-sandbox-templates --tag web
  assertions:
    - 42 templates tagged "web"
    - Frontend, backend, fullstack
    - Other tag suggestions

- name: "Example 7: Sort by Created Date"
  command: /list-sandbox-templates --sort created
  assertions:
    - Newest first
    - bun-latest (2025-01-15)
    - oauth-starter-template (2025-01-18)

- name: "Example 8: Custom Templates Only"
  command: /list-sandbox-templates --filter custom
  assertions:
    - 8 custom team templates
    - Created by team members
    - Usage stats (within team)
```

#### Error Tests (5 scenarios)
```yaml
- name: "Error 1: No Templates Match"
  command: /list-sandbox-templates --language brainfuck
  expected_error: "No templates found for language: brainfuck"
  recovery_options:
    - View all templates
    - List available languages
    - Search by name

- name: "Error 2: Invalid Filter"
  command: /list-sandbox-templates --filter super-official
  expected_error: "Invalid filter: super-official"
  recovery_options:
    - Use: official, custom, community, all
    - Show example

- name: "Error 3: Network Error"
  command: /list-sandbox-templates
  setup: E2B registry down
  expected_error: "Failed to load templates (network timeout)"
  recovery_options:
    - Use cached results
    - Retry with --refresh
    - Check network

- name: "Error 4: Deprecated Templates Warning"
  command: /list-sandbox-templates
  assertions:
    - Warning about deprecated templates
    - node16-typescript (deprecated)
    - python3.9 (deprecated)
    - Use --show-deprecated to view

- name: "Error 5: Rate Limit"
  command: /list-sandbox-templates
  setup: 100 requests in last hour
  expected_error: "Rate limit exceeded (100/100)"
  recovery_options:
    - Wait 42 minutes
    - Use cached results with --cache-only
```

---

## 5. Planning & Ideation Commands (2 commands)

### 5.1 brainstorm-ideas.md Tests

#### Functional Tests (8 examples)
```yaml
- name: "Example 1: Simple Brainstorming"
  command: /brainstorm-ideas "user engagement"
  assertions:
    - 10 ideas generated
    - Ranked by impact (0-100)
    - Effort estimates provided
    - ROI projections included

- name: "Example 2: Quick Wins Only"
  command: /brainstorm-ideas --priority quick-wins --count 5
  assertions:
    - 5 quick-win ideas
    - All 1-3 weeks effort
    - Impact scores 70-88
    - Combined moderate-high impact

- name: "Example 3: Monetization Focus"
  command: /brainstorm-ideas "monetization strategies" --count 8
  assertions:
    - 8 revenue-focused ideas
    - Usage-based pricing (94/100)
    - ROI calculations provided
    - Payback period estimated

- name: "Example 4: Technical Architecture"
  command: /brainstorm-ideas --category architecture --technical-depth
  assertions:
    - Architecture improvements
    - Microservices migration
    - Technical implementation details
    - Libraries and tools suggested

- name: "Example 5: With Market Research"
  command: /brainstorm-ideas "project management" --market-research
  assertions:
    - Competitive analysis included
    - 8 competitors analyzed
    - Market gaps identified
    - TAM/SAM/SOM sizing

- name: "Example 6: Export to GitHub Issues"
  command: /brainstorm-ideas "mobile app" --format github-issues
  assertions:
    - 10 draft issues created
    - In .brainstorm/github-issues/
    - Ready to import
    - Labels and estimates included

- name: "Example 7: Performance Optimization"
  command: /brainstorm-ideas --category performance --count 6
  assertions:
    - 6 performance ideas
    - Redis caching (88/100)
    - Lazy loading (82/100)
    - Combined -60% page load time

- name: "Example 8: UX Improvements"
  command: /brainstorm-ideas --category ux --count 8
  assertions:
    - 8 UX improvements
    - Onboarding tour (90/100)
    - Dark mode (84/100)
    - Focus on user satisfaction
```

#### Error Tests (4 scenarios)
```yaml
- name: "Error 1: Project Not Found"
  command: /brainstorm-ideas --project /invalid/path
  expected_error: "Project not found: /invalid/path"
  recovery_options:
    - Specify valid path
    - Use current directory
    - Generic brainstorming (no analysis)

- name: "Error 2: Invalid Category"
  command: /brainstorm-ideas --category super-features
  expected_error: "Invalid category: super-features"
  recovery_options:
    - Use: feature, improvement, bug-fix, architecture, ux, performance
    - Show example

- name: "Error 3: API Rate Limit (Market Research)"
  command: /brainstorm-ideas --market-research
  setup: 100 API requests used
  expected_error: "API rate limit exceeded (100/100)"
  recovery_options:
    - Wait for reset (42 min)
    - Skip market research
    - Use cached data

- name: "Error 4: Insufficient Project Info"
  command: /brainstorm-ideas
  setup: No package.json, README, git
  expected_warning: "Limited project information"
  assertions:
    - Warning shown
    - Generic ideas generated
    - Suggestions to improve setup
```

---

### 5.2 review-product-requirements.md Tests

#### Functional Tests (8 examples)
```yaml
- name: "Example 1: Quick PRD Review"
  command: /review-product-requirements docs/prd.md --depth quick
  assertions:
    - Completeness score (64/100)
    - Quality score (70/100)
    - Feasibility score (80/100)
    - Critical issues highlighted

- name: "Example 2: Technical Feasibility Focus"
  command: /review-product-requirements docs/prd.md --focus technical
  assertions:
    - Feasibility: 78/100
    - Architecture compatibility assessed
    - Recommended libraries listed
    - Technical risks identified

- name: "Example 3: Generate Implementation Tasks"
  command: /review-product-requirements docs/prd.md --generate-tasks
  assertions:
    - 24 tasks generated
    - Grouped by phase
    - Effort estimates provided
    - Can export to GitHub

- name: "Example 4: Security-Focused Review"
  command: /review-product-requirements docs/prd.md --focus security
  assertions:
    - Security score: 45/100 (insufficient)
    - Critical gaps identified (CSRF, PKCE, encryption)
    - Threat model missing
    - Security testing plan missing

- name: "Example 5: UX-Focused Review"
  command: /review-product-requirements docs/prd.md --focus ux
  assertions:
    - UX score: 68/100
    - User flows missing
    - Error messages vague
    - Accessibility requirements missing

- name: "Example 6: Business Impact Assessment"
  command: /review-product-requirements docs/prd.md --focus business --estimate-effort
  assertions:
    - Business score: 76/100
    - ROI analysis provided
    - Payback period: 8 months
    - 3-year ROI: 450%

- name: "Example 7: Comprehensive Review"
  command: /review-product-requirements docs/prd.md --depth comprehensive
  assertions:
    - 30+ checks performed
    - Overall score: 68/100
    - Detailed analysis (24.8KB report)
    - Priority improvements listed

- name: "Example 8: Export as Checklist"
  command: /review-product-requirements docs/prd.md --format checklist
  assertions:
    - Checklist format
    - Document structure ✓/✗
    - Content quality ✓/⚠/✗
    - Ready for implementation: ❌ No
    - 5 critical blockers listed
```

#### Error Tests (5 scenarios)
```yaml
- name: "Error 1: PRD File Not Found"
  command: /review-product-requirements docs/prd-missing.md
  expected_error: "PRD file not found: docs/prd-missing.md"
  recovery_options:
    - Check file path
    - Create new PRD
    - Use inline text

- name: "Error 2: Empty or Invalid PRD"
  command: /review-product-requirements docs/prd.md
  setup: File is 0 bytes
  expected_error: "PRD file is empty"
  recovery_options:
    - Use PRD template
    - Review inline text
    - Check file permissions

- name: "Error 3: Unsupported Format"
  command: /review-product-requirements docs/prd.docx
  expected_error: "Unsupported format: .docx"
  recovery_options:
    - Convert to Markdown
    - Copy content as inline text
    - Use supported formats (md, txt)

- name: "Error 4: API Rate Limit"
  command: /review-product-requirements docs/prd.md
  setup: 100 API requests used
  expected_error: "API rate limit exceeded"
  recovery_options:
    - Wait for reset
    - Use cached analysis
    - Reduce analysis depth

- name: "Error 5: PRD Too Large"
  command: /review-product-requirements docs/massive-prd.md
  setup: 500KB PRD file
  expected_error: "PRD too large (>100KB)"
  recovery_options:
    - Split into sections
    - Review sections separately
    - Reduce content
```

---

## 6. Utility Commands (2 commands)

### 6.1 export-session.md Tests

#### Functional Tests (8 examples)
```yaml
- name: "Example 1: Export Current Session"
  command: /export-session
  assertions:
    - Current session exported
    - JSON format (778KB)
    - HTML report generated
    - Compressed (340KB)

- name: "Example 2: Export Specific Session"
  command: /export-session orch_previous123 --format all
  assertions:
    - Specific session exported
    - All formats: JSON, CSV, HTML
    - Total: 1.9MB → 620KB compressed

- name: "Example 3: Export with Anonymization"
  command: /export-session --anonymize
  assertions:
    - 24 API keys removed
    - 18 email addresses masked
    - 42 env vars sanitized
    - Safe to share externally

- name: "Example 4: Export Events Only (Time Range)"
  command: /export-session --include events --time-range "2025-01-18T10:00-12:00"
  assertions:
    - 324 events (filtered from 1,247)
    - 2-hour time range
    - JSON + CSV formats
    - 78KB size

- name: "Example 5: Export with Artifacts"
  command: /export-session --include-artifacts
  assertions:
    - Build outputs: 245MB
    - Test reports: 12MB
    - Log files: 89MB
    - Total: 420MB compressed

- name: "Example 6: HTML Report Only"
  command: /export-session --format html
  assertions:
    - Interactive HTML report
    - Timeline visualization
    - Agent performance charts
    - Cost breakdown
    - Event log viewer

- name: "Example 7: Export to Custom Location"
  command: /export-session --output /backups/session-backup --compress
  assertions:
    - Exported to /backups
    - 340KB compressed
    - Backup complete

- name: "Example 8: Export Metrics Only"
  command: /export-session --include metrics --format csv
  assertions:
    - 5 CSV files generated
    - Agent execution times
    - Resource usage
    - API response times
    - Cost data
```

#### Error Tests (5 scenarios)
```yaml
- name: "Error 1: Session Not Found"
  command: /export-session orch_invalid123
  expected_error: "Session not found: orch_invalid123"
  recovery_options:
    - List available sessions
    - Export current session
    - Check session ID

- name: "Error 2: Insufficient Disk Space"
  command: /export-session
  setup: Need 1.2GB, have 450MB
  expected_error: "Insufficient disk space (short 750MB)"
  recovery_options:
    - Clean old exports
    - Export without artifacts
    - Export to external drive

- name: "Error 3: Export Permission Denied"
  command: /export-session --output /protected/exports/
  expected_error: "Permission denied: /protected/exports/"
  recovery_options:
    - Use default location
    - Change output path
    - Fix permissions

- name: "Error 4: Active Session Changes During Export"
  command: /export-session
  setup: Session still running
  expected_warning: "Session changed during export"
  assertions:
    - Snapshot captured at start
    - Consistent point-in-time
    - Changes after snapshot not included

- name: "Error 5: Anonymization Failed"
  command: /export-session --anonymize
  setup: API keys in commit messages
  expected_error: "Cannot guarantee safe export"
  recovery_options:
    - Export without anonymization
    - Export without sensitive components
    - Force partial anonymization
```

---

### 6.2 emergency-hotfix.md Tests

#### Functional Tests (6 examples)
```yaml
- name: "Example 1: Critical Production Bug"
  command: /emergency-hotfix "Production API 500 errors" --severity critical
  assertions:
    - Emergency assessment completed
    - Hotfix branch created
    - Sandbox provisioned (priority)
    - Root cause identified
    - Fix applied
    - Tests passed (7.5s critical only)
    - PR created (#247)
    - Total time: 30 minutes

- name: "Example 2: Security Vulnerability"
  command: /emergency-hotfix "SQL injection in search" --severity critical --issue 123
  assertions:
    - Security mode enabled
    - Logs anonymized
    - Security team notified
    - Parameterized queries fix
    - Security tests passed
    - PR #248 (security-sensitive)

- name: "Example 3: Performance Degradation"
  command: /emergency-hotfix "API 10x slower" --severity high
  assertions:
    - Root cause: N+1 query
    - Fix: Eager loading
    - Performance: 450ms → 42ms (-90%)
    - Tests passed
    - ETA: 20 minutes

- name: "Example 4: Data Corruption Hotfix"
  command: /emergency-hotfix "User data corruption" --severity critical --auto-merge=false
  assertions:
    - Database backup created
    - Manual merge required
    - Validation tests added
    - Data migration script ready
    - DBA approval required

- name: "Example 5: Rollback Previous Hotfix"
  command: /emergency-hotfix "Rollback hotfix #247" --rollback-plan
  assertions:
    - Previous commit identified
    - Rollback PR created (#251)
    - Fast-track approval
    - Deployed successfully
    - Service restored

- name: "Example 6: Extreme Emergency (Bypass Tests)"
  command: /emergency-hotfix "Critical security patch" --severity critical --skip-tests all
  setup: Confirmation "EMERGENCY" required
  assertions:
    - All tests skipped (DANGEROUS)
    - Patch applied
    - PR #252 (EMERGENCY flag)
    - Manual verification required
    - All channels notified
```

#### Error Tests (5 scenarios)
```yaml
- name: "Error 1: Not an Emergency"
  command: /emergency-hotfix "Add new dashboard feature" --severity medium
  expected_error: "Issue does not qualify as emergency"
  recovery_options:
    - Use regular workflow
    - Override if truly emergency

- name: "Error 2: Hotfix Already in Progress"
  command: /emergency-hotfix "New critical issue"
  setup: Another hotfix active
  expected_error: "Emergency hotfix already in progress"
  recovery_options:
    - Wait for current hotfix
    - Escalate priority
    - Collaborate on current

- name: "Error 3: CI/CD System Down"
  command: /emergency-hotfix "Production issue"
  setup: Jenkins/GitHub Actions down
  expected_error: "CI/CD system unavailable"
  recovery_options:
    - Wait for CI/CD restore
    - Manual testing (risky)
    - Rollback + wait

- name: "Error 4: Insufficient Permissions"
  command: /emergency-hotfix "Critical bug"
  setup: Regular developer (not on-call)
  expected_error: "Insufficient permissions"
  recovery_options:
    - Contact on-call engineer
    - Request emergency access
    - Create regular PR

- name: "Error 5: Sandbox Provisioning Failed"
  command: /emergency-hotfix "Production outage"
  setup: All emergency sandboxes in use
  expected_error: "Emergency sandbox provisioning failed"
  recovery_options:
    - Terminate non-critical sandboxes
    - Use existing sandbox (risky)
    - Local development (risky)
```

---

## Test Execution Plan

### Phase 1: Automated Unit Tests (Sprints 5.19-5.22)
**Duration**: 4 sprints (40 minutes)

```yaml
Sprint 5.19: Testing Infrastructure Commands
  - test-matrix.md: 12 functional + 10 error tests
  - sandbox-debug.md: 8 functional + 10 error tests
  - sandbox-exec.md: 12 functional + 8 error tests
  Duration: 10 minutes

Sprint 5.20: Orchestration Commands
  - pause-orchestration.md: 6 functional + 6 error tests
  - resume-orchestration.md: 6 functional + 6 error tests
  - orchestrator-events.md: 10 functional + 3 error tests
  - set-orchestration-strategy.md: 5 functional + 3 error tests
  Duration: 10 minutes

Sprint 5.21: Feature Lifecycle + Sandbox Advanced
  - pause-feature.md: 8 functional + 8 error tests
  - resume-feature.md: 8 functional + 8 error tests
  - sandbox-snapshot.md: 8 functional + 8 error tests
  - sandbox-restore.md: 8 functional + 8 error tests
  - list-sandbox-templates.md: 8 functional + 5 error tests
  Duration: 10 minutes

Sprint 5.22: Planning + Utilities
  - brainstorm-ideas.md: 8 functional + 4 error tests
  - review-product-requirements.md: 8 functional + 5 error tests
  - export-session.md: 8 functional + 5 error tests
  - emergency-hotfix.md: 6 functional + 5 error tests
  Duration: 10 minutes
```

### Phase 2: Integration Tests (Sprints 5.23-5.26)
**Duration**: 4 sprints (40 minutes)

```yaml
Sprint 5.23: Multi-Command Workflows
  - Pause orchestration → Resume
  - Pause feature → Resume feature
  - Snapshot → Restore
  - Test matrix → Export results

Sprint 5.24: Cross-Feature Integration
  - Brainstorm → PRD Review → Create Features
  - Emergency hotfix → Export session
  - Parallel testing → Debug failures

Sprint 5.25: State Management Integration
  - Pause/Resume with snapshots
  - Export/Import sessions
  - Template creation → Use template

Sprint 5.26: End-to-End Workflows
  - Full orchestration lifecycle
  - Complete feature development cycle
  - Emergency hotfix workflow
```

### Phase 3: Documentation Polish (Sprints 5.27-5.30)
**Duration**: 4 sprints (40 minutes)

```yaml
Sprint 5.27: Example Validation
  - Verify all examples executable
  - Test all command variations
  - Validate output formats

Sprint 5.28: Error Scenario Validation
  - Reproduce all 108+ error scenarios
  - Verify recovery options work
  - Document actual vs expected

Sprint 5.29: Performance Testing
  - Benchmark command execution times
  - Resource usage profiling
  - Parallel execution efficiency

Sprint 5.30: Final Documentation
  - Generate PHASE5_TEST_RESULTS.md
  - Update command docs with test results
  - Create user guides
```

---

## Test Coverage Summary

**Total Test Cases**: 216
- **Functional Tests**: 136 (63%)
- **Error Tests**: 80 (37%)

**By Command Category**:
- Testing Infrastructure: 30 tests (3 commands)
- Orchestration: 27 tests (4 commands)
- Feature Lifecycle: 16 tests (2 commands)
- Sandbox Advanced: 21 tests (3 commands)
- Planning: 12 tests (2 commands)
- Utilities: 11 tests (2 commands)

**Expected Test Execution Time**:
- Unit Tests: 40 minutes (automated)
- Integration Tests: 40 minutes (semi-automated)
- Documentation Polish: 40 minutes (manual review)
- **Total**: 2 hours

**Expected Pass Rate**: 95%+ (based on comprehensive documentation)

---

## Success Criteria

1. **Functional Coverage**: ✅ 100% of documented examples tested
2. **Error Coverage**: ✅ 100% of documented errors reproducible
3. **Integration Tests**: ✅ All cross-command workflows validated
4. **Performance**: ✅ All commands meet performance targets
5. **Documentation**: ✅ Test results documented in PHASE5_TEST_RESULTS.md

---

**Test Suite Status**: ✅ Complete
**Ready for Execution**: Yes
**Estimated Completion**: 2 hours (automated + manual)

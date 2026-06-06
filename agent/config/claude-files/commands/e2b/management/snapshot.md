---
name: snapshot
description: Create sandbox snapshot
---

# /sandbox-snapshot Command

Creates a point-in-time snapshot of a sandbox's complete state including filesystem, environment variables, running processes, and git state. Enables rollback, debugging, template creation, and state preservation for long-running development workflows.

## Usage

```
/sandbox-snapshot <sandbox_id> [options]
```

## Parameters

- `<sandbox_id>` (required): Bumba Sandbox ID to snapshot
- `--name <snapshot_name>` (optional): Custom name for snapshot - default: auto-generated
- `--description <text>` (optional): Description of snapshot purpose
- `--compress` (optional): Compress snapshot data to save space - default: true
- `--exclude <patterns>` (optional): Glob patterns to exclude (comma-separated)
- `--include-processes` (optional): Snapshot running processes state - default: false
- `--template` (optional): Create reusable template from snapshot - default: false
- `--tags <tag1,tag2>` (optional): Tags for organizing snapshots

## Workflow

### Step 1: Snapshot Request Validation

```
📸 Create Sandbox Snapshot
═══════════════════════════════════════════════

Validating request...
  Sandbox ID: sbx_abc123xyz
  Issue: #47 - Add OAuth Integration
  Status: Active (paused)

Sandbox Details:
  Template: node18-typescript
  Age: 2h 15m
  Uptime: 2h 15m
  CPU Usage: 2% (idle)
  Memory: 1.2 GB / 4 GB (30%)
  Disk: 3.8 GB used

Git State:
  Repository: github.com/user/project
  Branch: feature/oauth-integration
  Commits: 12 ahead of main
  Uncommitted Changes: 0
  Untracked Files: 0

Snapshot Configuration:
  Name: Auto-generated
  Compression: Enabled
  Include Processes: No
  Create Template: No

───────────────────────────────────────────────
```

### Step 2: Filesystem Analysis

```
Analyzing filesystem...
  Working Directory: /workspace
  Total Size: 3.8 GB

Directory Breakdown:
  /workspace/node_modules: 1.8 GB (47%)
  /workspace/.git: 892 MB (23%)
  /workspace/build: 456 MB (12%)
  /workspace/src: 234 MB (6%)
  /workspace/tests: 178 MB (5%)
  /tmp: 89 MB (2%)
  Other: 153 MB (5%)

Files to Snapshot:
  Total Files: 15,420
  Total Directories: 2,340

Exclusion Patterns (Default):
  - **/*.log
  - **/tmp/*
  - **/.cache/*
  - **/coverage/*

Applying exclusions...
  ✓ Excluded: 234 files (89 MB)

Final Snapshot Size:
  Estimated: 3.7 GB (before compression)
  Compressed: ~1.2 GB (67% reduction)

───────────────────────────────────────────────
```

### Step 3: State Capture

```
Capturing sandbox state...

Filesystem Snapshot:
  ⟳ Creating filesystem image...
  [████████████████████] 100% - 3.7 GB captured
  ✓ Filesystem snapshot complete

Environment Variables:
  ✓ Captured: 24 variables
    NODE_ENV=development
    DATABASE_URL=postgresql://...
    API_KEY=***
    ... (21 more)

Git Repository:
  ✓ Branch: feature/oauth-integration
  ✓ HEAD: commit abc123def456
  ✓ Stash entries: 0
  ✓ Submodules: 0
  ✓ Worktree state: Clean

Package Dependencies:
  ✓ package.json: Captured
  ✓ package-lock.json: Captured
  ✓ node_modules: Included in filesystem

Configuration Files:
  ✓ tsconfig.json
  ✓ .env (secrets masked)
  ✓ .eslintrc.js
  ✓ jest.config.js
  ✓ 12 config files total

Build Artifacts:
  ✓ /build directory: 456 MB
  ✓ TypeScript compiled output
  ✓ Source maps included

───────────────────────────────────────────────
```

### Step 4: Compression and Storage

```
Compressing snapshot...
  Algorithm: zstd (level 3)
  ⟳ Compressing 3.7 GB...

  Progress:
    [████████████████████] 100%

  Compression Results:
    Original: 3.7 GB
    Compressed: 1.2 GB
    Ratio: 67% reduction
    Duration: 42 seconds

Storing snapshot...
  ⟳ Uploading to Bumba Sandbox storage...
  [████████████████████] 100% - 1.2 GB uploaded
  ✓ Upload complete

Generating metadata...
  ✓ Snapshot manifest created
  ✓ Checksum: sha256:abc123...
  ✓ Metadata: 4.2 KB

───────────────────────────────────────────────
```

### Step 5: Snapshot Confirmation

```
✅ Snapshot Created Successfully
═══════════════════════════════════════════════

Snapshot Details:
  ID: snap_oauth_20250118_104530
  Name: oauth-integration-checkpoint
  Created: 2025-01-18T10:45:30Z
  Size: 1.2 GB (compressed from 3.7 GB)

Sandbox State:
  Sandbox: sbx_abc123xyz
  Issue: #47 - Add OAuth Integration
  Branch: feature/oauth-integration
  Commit: abc123def456
  Progress: 68%

Contents:
  Files: 15,186 (234 excluded)
  Directories: 2,340
  Environment Variables: 24
  Build Artifacts: Yes
  Git Repository: Complete

Metadata:
  Checksum: sha256:abc123def456...
  Compression: zstd level 3 (67% reduction)
  Duration: 42 seconds

Restore Options:
  Restore to same sandbox:
    /sandbox-restore sbx_abc123xyz snap_oauth_20250118_104530

  Restore to new sandbox:
    /sandbox-restore --new snap_oauth_20250118_104530

  List all snapshots:
    /list-snapshots sbx_abc123xyz

Storage Location:
  Provider: Bumba Sandbox Cloud Storage
  Region: us-east-1
  Retention: 30 days (default)

───────────────────────────────────────────────
```

## Examples

### Example 1: Simple Snapshot

```
/sandbox-snapshot sbx_abc123xyz
```

**Output**:
```
📸 Create Snapshot

Sandbox: sbx_abc123xyz
Size: 3.7 GB

⟳ Capturing state...
✓ Filesystem: 3.7 GB
✓ Environment: 24 vars
✓ Git: feature/oauth-integration

⟳ Compressing...
✓ Compressed to 1.2 GB (67% reduction)

✅ Snapshot Created
ID: snap_20250118_104530
Size: 1.2 GB
Duration: 42s

Restore: /sandbox-restore sbx_abc123xyz snap_20250118_104530
```

### Example 2: Named Snapshot with Description

```
/sandbox-snapshot sbx_abc123xyz --name "oauth-tests-passing" --description "Checkpoint after all OAuth tests passing - before PR creation"
```

**Output**:
```
📸 Create Named Snapshot

Name: oauth-tests-passing
Description: Checkpoint after all OAuth tests passing
             - before PR creation

Sandbox: sbx_abc123xyz (3.7 GB)

⟳ Capturing state...
✓ Complete

⟳ Compressing...
✓ 1.2 GB

✅ Snapshot Created
ID: snap_oauth_tests_passing_20250118
Name: oauth-tests-passing
Size: 1.2 GB

Use Case: Rollback point before PR creation
Restore: /sandbox-restore sbx_abc123xyz snap_oauth_tests_passing_20250118
```

### Example 3: Snapshot with Exclusions

```
/sandbox-snapshot sbx_abc123xyz --exclude "node_modules/**,build/**,.git/**" --name "source-only"
```

**Output**:
```
📸 Create Snapshot (Minimal)

Exclusions:
  - node_modules/** (1.8 GB excluded)
  - build/** (456 MB excluded)
  - .git/** (892 MB excluded)

Original Size: 3.7 GB
Excluded: 3.1 GB (84%)
Snapshot Size: 600 MB (source code only)

⟳ Capturing state...
  Files: 2,340 (13,080 excluded)
  ✓ Source code captured

⟳ Compressing...
✓ Compressed to 180 MB (70% reduction)

✅ Minimal Snapshot Created
ID: snap_source_only_20250118
Size: 180 MB
Contents: Source code only (no dependencies)

Note: Restore will require npm install
Restore: /sandbox-restore sbx_abc123xyz snap_source_only_20250118
```

### Example 4: Create Template from Snapshot

```
/sandbox-snapshot sbx_abc123xyz --template --name "oauth-starter-template" --description "Pre-configured OAuth integration starter"
```

**Output**:
```
📸 Create Template from Snapshot

Template Name: oauth-starter-template
Description: Pre-configured OAuth integration starter

⟳ Capturing state...
✓ Filesystem: 3.7 GB
✓ Environment: 24 vars (secrets removed)
✓ Git: Reset to clean state
✓ Config: Sanitized

⟳ Template Processing...
  🔒 Removing secrets from .env
  🗑️ Clearing git history
  ✓ Removing user-specific data
  ✓ Generalizing configuration

⟳ Compressing...
✓ Compressed to 1.1 GB

✅ Template Created
ID: tmpl_oauth_starter_20250118
Name: oauth-starter-template
Size: 1.1 GB
Type: Reusable template

Use Template:
  Create new sandbox:
    /create-sandbox --template tmpl_oauth_starter_20250118

  List templates:
    /list-sandbox-templates

Template ready for team use!
```

### Example 5: Snapshot with Process State

```
/sandbox-snapshot sbx_abc123xyz --include-processes --name "debugging-session"
```

**Output**:
```
📸 Create Snapshot with Process State

⟳ Capturing running processes...

Active Processes:
  PID  Command               CPU   Memory
  ───  ───────────────────  ────  ──────
  1234 node server.js       12%   340 MB
  5678 npm run test:watch   5%    180 MB
  9012 tail -f logs/app.log 0.1%  2 MB

Process State:
  ✓ Process tree captured
  ✓ Open file descriptors: 42
  ✓ Network connections: 3
  ✓ Environment per process

⚠️ Note: Process state capture is experimental
         Restore may not resume all processes

⟳ Capturing filesystem...
✓ Complete (3.7 GB)

⟳ Compressing...
✓ 1.3 GB (includes process metadata)

✅ Snapshot with Processes Created
ID: snap_debugging_session_20250118
Size: 1.3 GB
Processes: 3 captured

Restore: /sandbox-restore sbx_abc123xyz snap_debugging_session_20250118
Note: May need to manually restart processes
```

### Example 6: Tagged Snapshot for Organization

```
/sandbox-snapshot sbx_abc123xyz --tags "milestone,oauth,v1.0" --name "v1.0-milestone"
```

**Output**:
```
📸 Create Tagged Snapshot

Name: v1.0-milestone
Tags: milestone, oauth, v1.0

⟳ Capturing state...
✓ Complete

⟳ Compressing...
✓ 1.2 GB

✅ Snapshot Created
ID: snap_v1_0_milestone_20250118
Tags: #milestone #oauth #v1.0
Size: 1.2 GB

Find by Tag:
  /list-snapshots --tag milestone
  /list-snapshots --tag oauth
  /list-snapshots --tag v1.0

Organization:
  Tags help find related snapshots
  Use for: milestones, features, versions
```

### Example 7: Rapid Snapshot (No Compression)

```
/sandbox-snapshot sbx_abc123xyz --compress=false --name "quick-backup"
```

**Output**:
```
📸 Create Snapshot (Uncompressed)

⚠️ Compression disabled (faster but larger)

⟳ Capturing state...
✓ Filesystem: 3.7 GB
✓ Environment: 24 vars

⟳ Storing (no compression)...
[████████████████████] 100% - 3.7 GB

✅ Snapshot Created (Uncompressed)
ID: snap_quick_backup_20250118
Size: 3.7 GB (no compression)
Duration: 18s (faster than compressed)

Trade-off:
  Speed: 42s → 18s (58% faster)
  Size: 1.2 GB → 3.7 GB (3x larger)

Use Case: Quick backup when storage not constrained
Restore: /sandbox-restore sbx_abc123xyz snap_quick_backup_20250118
```

### Example 8: Snapshot During Active Development

```
/sandbox-snapshot sbx_abc123xyz --name "before-refactor" --description "Stable state before major refactoring of auth module"
```

**Output**:
```
📸 Create Safety Checkpoint

Name: before-refactor
Purpose: Stable state before major refactoring

⚠️ Sandbox is active (development in progress)
⚠️ Uncommitted changes detected: 3 files

Uncommitted Changes:
  M src/auth/oauth.ts
  M src/auth/oauth.test.ts
  M package.json

Options:
  1. Snapshot with uncommitted changes (current state)
  2. Commit changes first, then snapshot
  3. Cancel

Selected: Option 1 (snapshot current state)

⟳ Capturing state with uncommitted changes...
✓ Working directory state preserved
✓ Git index included

⟳ Compressing...
✓ 1.2 GB

✅ Development Checkpoint Created
ID: snap_before_refactor_20250118
Uncommitted Changes: Included
Size: 1.2 GB

Safety Net:
  If refactoring breaks things:
    /sandbox-restore sbx_abc123xyz snap_before_refactor_20250118

  This will restore exact working state including:
    ✓ Uncommitted changes
    ✓ Git index
    ✓ Environment
```

## Error Handling

### Error 1: Sandbox Not Found

```
❌ Error: Sandbox not found

Sandbox ID: sbx_invalid123
Status: Not found

The specified sandbox does not exist or has been terminated.

Active Sandboxes:
  sbx_abc123xyz - Issue #47 (active)
  sbx_def456uvw - Issue #45 (active)
  sbx_ghi789jkl - Issue #49 (paused)

Available Actions:

  List all sandboxes:
    /list-sandboxes

  Snapshot active sandbox:
    /sandbox-snapshot sbx_abc123xyz

Troubleshooting:
  - Check sandbox ID spelling
  - Verify sandbox still exists
  - Use /list-sandboxes to see all available
```

### Error 2: Insufficient Disk Space

```
❌ Error: Insufficient disk space for snapshot

Sandbox: sbx_abc123xyz
Required Space: 3.7 GB (uncompressed)
Available Space: 1.2 GB
Shortfall: 2.5 GB

Disk Usage:
  Total: 10 GB
  Used: 8.8 GB (88%)
  Available: 1.2 GB (12%)

Cannot create snapshot - not enough storage.

Recovery Options:

  Option 1: Clean Sandbox First
  ───────────────────────────────────────
    /sandbox-exec sbx_abc123xyz "npm run clean"
    /sandbox-snapshot sbx_abc123xyz

  Expected Cleanup: ~800MB-1.5GB
  Then retry snapshot

  Option 2: Snapshot with Exclusions
  ───────────────────────────────────────
    /sandbox-snapshot sbx_abc123xyz \
      --exclude "node_modules/**,build/**"

  Reduces size by ~60% (2.2 GB saved)
  Note: Restore will need npm install

  Option 3: Clean Bumba Sandbox Storage
  ───────────────────────────────────────
    /list-snapshots --all
    /delete-snapshot <old_snapshot_id>

  Delete old snapshots to free space

  Option 4: Increase Storage Quota
  ───────────────────────────────────────
    Contact Bumba Sandbox support to increase quota

Recommendation: Try Option 1, then Option 2
```

### Error 3: Snapshot Already Exists

```
❌ Error: Snapshot name already exists

Sandbox: sbx_abc123xyz
Name: oauth-tests-passing
Existing Snapshot: snap_oauth_tests_passing_20250117

A snapshot with this name already exists.

Existing Snapshot Details:
  ID: snap_oauth_tests_passing_20250117
  Created: 2025-01-17T15:30:00Z (18 hours ago)
  Size: 1.1 GB
  Branch: feature/oauth-integration
  Commit: old123abc456

Recovery Options:

  Option 1: Use Different Name
  ───────────────────────────────────────
    /sandbox-snapshot sbx_abc123xyz \
      --name "oauth-tests-passing-v2"

  Creates new snapshot with unique name

  Option 2: Overwrite Existing
  ───────────────────────────────────────
    /sandbox-snapshot sbx_abc123xyz \
      --name "oauth-tests-passing" --force

  ⚠️ Deletes old snapshot, creates new one

  Option 3: Use Auto-Generated Name
  ───────────────────────────────────────
    /sandbox-snapshot sbx_abc123xyz

  Let system generate unique name
  Format: snap_YYYYMMDD_HHMMSS

Recommendation: Option 1 or Option 3 to preserve history
```

### Error 4: Snapshot Timeout

```
❌ Error: Snapshot operation timed out

Sandbox: sbx_abc123xyz
Size: 12.4 GB (large)
Timeout: 300 seconds (5 minutes)
Elapsed: 305 seconds

Operation timed out while capturing filesystem.

Progress:
  Captured: 8.2 GB (66%)
  Remaining: 4.2 GB (34%)
  Rate: ~27 MB/s

Large Sandbox Detected:
  Your sandbox is significantly larger than typical
  Default timeout insufficient

Recovery Options:

  Option 1: Retry with Extended Timeout
  ───────────────────────────────────────
    /sandbox-snapshot sbx_abc123xyz \
      --timeout 900

  Extends timeout to 15 minutes
  Estimated time: ~7-8 minutes

  Option 2: Snapshot with Exclusions
  ───────────────────────────────────────
    /sandbox-snapshot sbx_abc123xyz \
      --exclude "node_modules/**,build/**"

  Reduce size to ~4 GB (faster)
  Estimated time: ~2-3 minutes

  Option 3: Clean Before Snapshot
  ───────────────────────────────────────
    /sandbox-exec sbx_abc123xyz "npm run clean"
    /sandbox-snapshot sbx_abc123xyz

  Remove build artifacts first
  Then create smaller snapshot

Recommendation: Option 2 for fastest result
```

### Error 5: Permission Denied

```
❌ Error: Permission denied

Sandbox: sbx_abc123xyz
Owner: @lead-developer
Current User: @developer
Operation: Create snapshot

You do not have permission to snapshot this sandbox.

Permission Details:
  Sandbox Owner: @lead-developer
  Your Role: contributor
  Required: owner or admin

Sandboxes You Can Snapshot:
  sbx_def456uvw - Issue #45 (your sandbox)
  sbx_mno789pqr - Issue #52 (your sandbox)

Recovery Options:

  Option 1: Request Permission
  ───────────────────────────────────────
    Contact @lead-developer to:
    - Grant snapshot permission
    - Create snapshot on your behalf

  Option 2: Snapshot Your Own Sandboxes
  ───────────────────────────────────────
    /sandbox-snapshot sbx_def456uvw

  Option 3: Admin Override (If Admin)
  ───────────────────────────────────────
    /sandbox-snapshot sbx_abc123xyz --admin

  ⚠️ Requires admin privileges

Recommendation: Option 1 or Option 2
```

### Error 6: Compression Failed

```
❌ Error: Snapshot compression failed

Sandbox: sbx_abc123xyz
Size: 3.7 GB (uncompressed)
Compression: zstd level 3

Compression Error:
  Code: COMPRESSION_ALGORITHM_ERROR
  Message: zstd compression failed
  Reason: Corrupted data block detected

Potential Causes:
  - Filesystem corruption
  - Memory pressure during compression
  - Hardware error

Recovery Options:

  Option 1: Retry Without Compression
  ───────────────────────────────────────
    /sandbox-snapshot sbx_abc123xyz \
      --compress=false

  Skips compression (faster, larger)
  Size: 3.7 GB (no reduction)
  Duration: ~18s

  Option 2: Check Filesystem Health
  ───────────────────────────────────────
    /sandbox-debug sbx_abc123xyz
    Run: fsck -n /workspace

  Check for filesystem corruption
  Fix if needed, then retry

  Option 3: Try Different Compression
  ───────────────────────────────────────
    /sandbox-snapshot sbx_abc123xyz \
      --compression-level 1

  Use lower compression (faster, less efficient)
  May avoid corrupted blocks

Recommendation: Try Option 1 first for immediate backup
```

### Error 7: Network Error During Upload

```
❌ Error: Network error during snapshot upload

Sandbox: sbx_abc123xyz
Snapshot Size: 1.2 GB (compressed)
Upload Progress: 68% (820 MB / 1.2 GB)

Network Error:
  Code: CONNECTION_TIMEOUT
  Message: Upload timed out after 60 seconds
  Uploaded: 820 MB (68%)
  Remaining: 380 MB

The snapshot was created locally but upload to storage failed.

Recovery Options:

  Option 1: Retry Upload
  ───────────────────────────────────────
    /sandbox-snapshot sbx_abc123xyz \
      --retry-upload snap_20250118_104530

  Resumes upload from 68% (820 MB)
  Only uploads remaining 380 MB

  Option 2: Check Network and Retry
  ───────────────────────────────────────
    # Check network connectivity
    ping storage.e2b.dev

    # Retry full operation
    /sandbox-snapshot sbx_abc123xyz

  Option 3: Save Locally Only
  ───────────────────────────────────────
    /sandbox-snapshot sbx_abc123xyz --local-only

  Saves snapshot to local disk
  Upload later when network stable

Local Snapshot Location:
  Path: /tmp/snapshots/snap_20250118_104530.tar.zst
  Size: 1.2 GB
  Valid for: 24 hours

Recommendation: Option 1 to resume upload
```

### Error 8: Snapshot Quota Exceeded

```
❌ Error: Snapshot storage quota exceeded

Account: your-account
Current Usage: 48.2 GB / 50 GB (96%)
New Snapshot Size: 1.2 GB
Required Space: 49.4 GB
Quota: 50 GB
Overage: Would exceed by 0.6 GB

Cannot create snapshot - would exceed storage quota.

Current Snapshots:
  snap_oauth_20250115: 3.2 GB (3 days old)
  snap_auth_20250116: 2.8 GB (2 days old)
  snap_payment_20250117: 4.1 GB (1 day old)
  ... (12 more snapshots, 38.1 GB total)

Recovery Options:

  Option 1: Delete Old Snapshots
  ───────────────────────────────────────
    /list-snapshots --sort-by age --limit 5
    /delete-snapshot <old_snapshot_id>

  Delete older snapshots to free space
  Target: Free ~2 GB

  Option 2: Compress Existing Snapshots
  ───────────────────────────────────────
    /compress-snapshot snap_oauth_20250115

  Re-compress old snapshots with better ratio
  Potential Savings: ~10-20%

  Option 3: Increase Storage Quota
  ───────────────────────────────────────
    Contact E2B support
    Upgrade to higher tier: 50 GB → 100 GB

  Option 4: Create Smaller Snapshot
  ───────────────────────────────────────
    /sandbox-snapshot sbx_abc123xyz \
      --exclude "node_modules/**,build/**"

  Create minimal snapshot (~400 MB instead of 1.2 GB)

Recommendation: Option 1 to clean up old snapshots
```

## Integration

### Integration with Sandbox Management
- Validates sandbox exists and is accessible
- Captures complete sandbox filesystem state
- Preserves sandbox metadata and configuration
- Enables exact sandbox restoration
- Updates sandbox snapshot registry

### Integration with Git Worktree
- Captures git repository state
- Preserves branch, commit, and stash entries
- Includes uncommitted changes if present
- Stores git configuration
- Enables rollback to exact git state

### Integration with Environment Management
- Captures all environment variables
- Masks secrets in template mode
- Preserves .env files
- Stores process-specific environments
- Enables environment restoration

### Integration with Storage System
- Uploads to Bumba Sandbox cloud storage
- Implements compression for efficiency
- Validates checksums for integrity
- Manages storage quotas
- Supports local caching

### Integration with Template System
- Can create reusable templates from snapshots
- Sanitizes user-specific data
- Removes secrets from templates
- Enables team-wide template sharing
- Integrates with template registry

## Use Cases

### Use Case 1: Pre-Deployment Checkpoint
**Scenario**: Create safety checkpoint before deploying feature to production.

**Command**:
```bash
/sandbox-snapshot sbx_abc123xyz --name "pre-deploy-v1.0" --tags "milestone,deploy"
```

**Result**: Snapshot created as rollback point if deployment issues arise.

### Use Case 2: Debugging Session Preservation
**Scenario**: Preserve exact state during active debugging session.

**Command**:
```bash
/sandbox-snapshot sbx_abc123xyz --name "debugging-oauth-cors" --include-processes
```

**Result**: Complete state snapshot including running processes for later analysis.

### Use Case 3: Create Reusable Template
**Scenario**: Create template for team to use with pre-configured OAuth setup.

**Command**:
```bash
/sandbox-snapshot sbx_abc123xyz --template --name "oauth-starter"
```

**Result**: Reusable template created, available via /list-sandbox-templates.

### Use Case 4: Minimal Source Backup
**Scenario**: Quick backup of source code only, excluding dependencies.

**Command**:
```bash
/sandbox-snapshot sbx_abc123xyz --exclude "node_modules/**,build/**,.git/**" --name "source-only"
```

**Result**: Small (180 MB) snapshot of source code only.

### Use Case 5: Milestone Documentation
**Scenario**: Preserve state at major project milestone.

**Command**:
```bash
/sandbox-snapshot sbx_abc123xyz --name "v1.0-release" --tags "release,v1.0" --description "Final state for v1.0 release"
```

**Result**: Tagged milestone snapshot for historical reference.

## Performance Considerations

### Snapshot Speed
- Small sandboxes (<1 GB): 10-20 seconds
- Medium sandboxes (1-5 GB): 30-90 seconds
- Large sandboxes (5-15 GB): 2-5 minutes
- Very large (>15 GB): 5-15 minutes

### Compression Impact
- Compression ratio: 60-70% typical
- Time overhead: +30-50% for compression
- Storage savings: ~2-3x

### Storage Requirements
- Compressed: ~30-40% of original size
- Uncompressed: 100% of sandbox size
- Metadata: <5 KB per snapshot

## Notes

- **Point-in-Time**: Snapshot captures exact state at creation time
- **Complete State**: Includes filesystem, environment, git state
- **Compression Default**: Enabled for storage efficiency
- **Exclusions**: Can exclude patterns to reduce size
- **Template Mode**: Removes secrets and user data for sharing
- **Process State**: Experimental, may not fully restore processes
- **Restoration**: Use /sandbox-restore to restore snapshot
- **Storage Quota**: Subject to account storage limits
- **Retention**: Default 30 days, configurable
- **Tags**: Organize snapshots with tags
- **Checksums**: Validated for integrity
- **Cloud Storage**: Uploaded to Bumba Sandbox for durability

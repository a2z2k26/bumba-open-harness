---
name: restore
description: Restore from snapshot
---

# /sandbox-restore Command

Restores a sandbox to a previous state from a snapshot, enabling rollback after failed changes, debugging with known-good state, or creating new sandboxes from templates. Supports full restoration or selective component restoration (filesystem only, environment only, etc.).

## Usage

```
/sandbox-restore <sandbox_id_or_new> <snapshot_id> [options]
```

## Parameters

- `<sandbox_id_or_new>` (required): Target sandbox ID or "--new" to create new sandbox
- `<snapshot_id>` (required): Snapshot ID to restore from
- `--components <list>` (optional): Components to restore (filesystem,environment,git,config) - default: all
- `--exclude <patterns>` (optional): Patterns to exclude during restore
- `--preserve-current` (optional): Backup current state before restore - default: false
- `--verify` (optional): Verify snapshot integrity before restore - default: true
- `--stop-processes` (optional): Stop running processes before restore - default: true
- `--force` (optional): Force restore even if validation fails - default: false

## Workflow

### Step 1: Restore Request Validation

```
🔄 Restore Sandbox from Snapshot
═══════════════════════════════════════════════

Validating request...
  Target: sbx_abc123xyz (existing sandbox)
  Snapshot: snap_oauth_20250118_104530
  Operation: Full restore

Target Sandbox Details:
  ID: sbx_abc123xyz
  Issue: #47 - Add OAuth Integration
  Status: Active (paused)
  Current State:
    Branch: feature/oauth-integration
    Commit: def789ghi012 (12 commits ahead)
    Size: 4.2 GB
    Uptime: 3h 45m

Snapshot Details:
  ID: snap_oauth_20250118_104530
  Name: oauth-tests-passing
  Created: 2025-01-18T10:45:30Z (2 hours ago)
  Size: 1.2 GB (compressed from 3.7 GB)
  Source: sbx_abc123xyz (same sandbox)

Snapshot Contents:
  Files: 15,186
  Directories: 2,340
  Environment Variables: 24
  Git Branch: feature/oauth-integration
  Git Commit: abc123def456
  Build Artifacts: Yes

───────────────────────────────────────────────
```

### Step 2: Pre-Restore Preparation

```
Preparing for restore...

Current State Backup (--preserve-current):
  ⚠️ Current state will be backed up before restore

  Creating backup snapshot...
  📸 Snapshot: snap_backup_pre_restore_20250118
  ✓ Current state preserved (safety backup)

Validation Checks:
  ✓ Snapshot exists
  ✓ Snapshot integrity verified (checksum valid)
  ✓ Target sandbox accessible
  ✓ Sufficient disk space (4.5 GB available > 3.7 GB needed)
  ✓ No conflicting operations

Impact Analysis:
  Changes to Revert:
    - 5 files modified since snapshot
    - 2 files added
    - 0 files deleted
    - 4 commits will be lost (can reapply from backup)

  Environment Changes:
    - 3 new environment variables (will be removed)
    - 2 modified values (will revert)

Stopping Processes:
  Active Processes:
    PID  Command
    ───  ────────────────
    1234 node server.js
    5678 npm run watch

  ⏸️ Stopping processes...
  ✓ All processes stopped gracefully

───────────────────────────────────────────────
```

### Step 3: Snapshot Restoration

```
Restoring snapshot...

Downloading Snapshot:
  Source: Bumba Sandbox Cloud Storage
  Size: 1.2 GB (compressed)
  ⟳ Downloading...
  [████████████████████] 100% - 1.2 GB downloaded
  ✓ Download complete (28 seconds)

Decompressing:
  Algorithm: zstd level 3
  ⟳ Decompressing...
  [████████████████████] 100% - 3.7 GB extracted
  ✓ Decompression complete (18 seconds)

Filesystem Restoration:
  ⟳ Restoring 15,186 files...
  [████████████████████] 100%

  Restored:
    /workspace/src: 234 MB (1,240 files)
    /workspace/node_modules: 1.8 GB (12,340 files)
    /workspace/build: 456 MB (890 files)
    /workspace/.git: 892 MB (1,650 files)
    Other: 320 MB (66 files)

  ✓ Filesystem restored (3.7 GB)

Environment Restoration:
  ✓ 24 environment variables restored
  ✓ .env file restored
  ✓ Shell configuration restored

Git State Restoration:
  ✓ Branch: feature/oauth-integration (checked out)
  ✓ HEAD: abc123def456 (snapshot commit)
  ✓ Working directory: Clean
  ✓ Stash entries: 0

Configuration Restoration:
  ✓ package.json restored
  ✓ tsconfig.json restored
  ✓ .eslintrc.js restored
  ✓ 12 config files total

───────────────────────────────────────────────
```

### Step 4: Post-Restore Verification

```
Verifying restored state...

Filesystem Verification:
  ✓ File count: 15,186 (matches snapshot)
  ✓ Total size: 3.7 GB (matches snapshot)
  ✓ Checksums: All valid
  ✓ Permissions: Correct

Git Verification:
  ✓ Branch: feature/oauth-integration
  ✓ Commit: abc123def456
  ✓ Remote tracking: origin/feature/oauth-integration
  ✓ Working directory: Clean
  ✓ No uncommitted changes

Environment Verification:
  ✓ All 24 variables present
  ✓ Values match snapshot
  ✓ No extra variables

Build Verification:
  ⟳ Running build verification...
  ✓ TypeScript compiles successfully
  ✓ Dependencies intact
  ✓ Build artifacts valid

Test Verification (optional):
  ⟳ Running test suite...
  ✓ All 30 tests passing
  ✓ No test failures

───────────────────────────────────────────────
```

### Step 5: Restore Confirmation

```
✅ Sandbox Restored Successfully
═══════════════════════════════════════════════

Restored Sandbox:
  ID: sbx_abc123xyz
  Snapshot: snap_oauth_20250118_104530
  Restored At: 2025-01-18T13:15:00Z

Restored State:
  Git Branch: feature/oauth-integration
  Git Commit: abc123def456
  Files: 15,186 (3.7 GB)
  Environment: 24 variables
  Build: Valid (456 MB artifacts)

State Changes:
  Reverted:
    - 5 modified files
    - 2 added files
    - 4 commits
    - 3 environment variables

  Restored To:
    - Snapshot time: 2025-01-18T10:45:30Z
    - 2 hours 30 minutes ago
    - State: "All OAuth tests passing"

Backup Created:
  Pre-restore backup: snap_backup_pre_restore_20250118
  Contains: State before restore (4.2 GB)
  Restore backup: /sandbox-restore sbx_abc123xyz snap_backup_pre_restore_20250118

Performance:
  Download: 28s
  Decompress: 18s
  Restore: 34s
  Verify: 12s
  Total: 92s (1m 32s)

Next Steps:
  - Sandbox ready to use
  - Resume development from snapshot point
  - Previous commits available in backup snapshot

───────────────────────────────────────────────
```

## Examples

### Example 1: Simple Restore to Existing Sandbox

```
/sandbox-restore sbx_abc123xyz snap_oauth_20250118_104530
```

**Output**:
```
🔄 Restore Snapshot

Target: sbx_abc123xyz
Snapshot: snap_oauth_20250118_104530
Size: 3.7 GB (from 1.2 GB compressed)

⟳ Downloading...
✓ Downloaded (28s)

⟳ Restoring...
✓ Filesystem: 15,186 files
✓ Environment: 24 vars
✓ Git: abc123def456

⟳ Verifying...
✓ All checks passed

✅ Restored Successfully
Duration: 1m 32s
State: oauth-tests-passing (2h ago)
```

### Example 2: Restore to New Sandbox

```
/sandbox-restore --new snap_oauth_20250118_104530
```

**Output**:
```
🔄 Restore Snapshot to New Sandbox

Snapshot: snap_oauth_20250118_104530 (3.7 GB)

Creating new sandbox...
  🏗️ Template: node18-typescript
  ⟳ Provisioning...
  ✓ Sandbox created: sbx_new789xyz

Restoring snapshot to new sandbox...
  ⟳ Downloading...
  ✓ Downloaded (28s)

  ⟳ Restoring...
  ✓ Complete (3.7 GB)

  ⟳ Verifying...
  ✓ All checks passed

✅ New Sandbox Created from Snapshot
New Sandbox: sbx_new789xyz
State: oauth-tests-passing
Size: 3.7 GB

Original Sandbox: sbx_abc123xyz (unchanged)
Use: /sandbox-debug sbx_new789xyz
```

### Example 3: Restore with Current State Backup

```
/sandbox-restore sbx_abc123xyz snap_oauth_20250118_104530 --preserve-current
```

**Output**:
```
🔄 Restore with Safety Backup

⚠️ Creating backup of current state first...

📸 Backing up current state...
  ✓ Backup: snap_backup_pre_restore_20250118
  Size: 1.3 GB
  Purpose: Safety backup before restore

⟳ Restoring snapshot...
✓ Complete

✅ Restored Successfully
Snapshot: snap_oauth_20250118_104530
Backup: snap_backup_pre_restore_20250118

Undo Restore:
  /sandbox-restore sbx_abc123xyz snap_backup_pre_restore_20250118
```

### Example 4: Selective Component Restore (Git Only)

```
/sandbox-restore sbx_abc123xyz snap_oauth_20250118_104530 --components git
```

**Output**:
```
🔄 Selective Restore (Git Only)

Components: git (filesystem, environment skipped)

Restoring Git State:
  ⟳ Checking out branch...
  ✓ Branch: feature/oauth-integration

  ⟳ Resetting to commit...
  ✓ Commit: abc123def456

  ⟳ Cleaning working directory...
  ✓ Working directory: Clean

✅ Git State Restored
Branch: feature/oauth-integration
Commit: abc123def456

Unchanged:
  - Filesystem (current files preserved)
  - Environment (current vars preserved)
  - Configuration (current config preserved)

Use Case: Rollback git history without affecting files
```

### Example 5: Restore Environment Variables Only

```
/sandbox-restore sbx_abc123xyz snap_oauth_20250118_104530 --components environment
```

**Output**:
```
🔄 Selective Restore (Environment Only)

Components: environment

Restoring Environment:
  Current: 27 variables
  Snapshot: 24 variables

  Changes:
    - Remove: 3 new variables (added after snapshot)
    - Update: 2 modified values
    - Restore: 24 original variables

  ✓ Environment restored

✅ Environment Variables Restored
Variables: 24 (from snapshot)
Removed: 3 (added after snapshot)
Updated: 2 (modified values)

Unchanged:
  - Filesystem
  - Git state
  - Configuration

Verify: printenv | grep NODE_ENV
```

### Example 6: Force Restore Despite Warnings

```
/sandbox-restore sbx_abc123xyz snap_oauth_20250118_104530 --force
```

**Output**:
```
🔄 Force Restore

⚠️ Validation warnings detected:

Warnings:
  ⚠️ Snapshot is 3 days old
  ⚠️ Different branch: main (current) vs feature/oauth (snapshot)
  ⚠️ Target sandbox has uncommitted changes

Force restore requested - proceeding despite warnings

⟳ Restoring...
  ⚠️ Discarding uncommitted changes
  ⚠️ Switching branches: main → feature/oauth
  ✓ Restored

✅ Force Restore Complete
⚠️ Warnings were bypassed
Review changes: git status
```

### Example 7: Restore with Exclusions

```
/sandbox-restore sbx_abc123xyz snap_oauth_20250118_104530 --exclude "node_modules/**,.git/**"
```

**Output**:
```
🔄 Selective Restore (With Exclusions)

Exclusions:
  - node_modules/** (1.8 GB skipped)
  - .git/** (892 MB skipped)

Restoring:
  Included: 1.0 GB (source, config, build)
  Excluded: 2.7 GB (dependencies, git)

  ⟳ Restoring included files...
  ✓ Complete (1.0 GB)

✅ Partial Restore Complete
Restored: Source code, config, build artifacts
Excluded: Dependencies, git history

Next Steps:
  npm install  # Reinstall dependencies
  git fetch    # Sync git repository

Use Case: Faster restore when dependencies can be reinstalled
```

### Example 8: Restore Without Process Stop

```
/sandbox-restore sbx_abc123xyz snap_oauth_20250118_104530 --stop-processes=false
```

**Output**:
```
🔄 Restore (Keep Processes Running)

⚠️ Warning: Restoring while processes running

Active Processes:
  PID  Command
  ───  ────────────────
  1234 node server.js  (keep running)
  5678 npm run watch   (keep running)

⚠️ Restoring files while processes active may cause:
  - File conflicts
  - Process crashes
  - Inconsistent state

⟳ Restoring...
  ✓ Files restored

⚠️ Processes may need restart:
  pkill -9 node && npm start

✅ Restored (Processes Not Stopped)
⚠️ Manual process restart may be needed
```

## Error Handling

### Error 1: Snapshot Not Found

```
❌ Error: Snapshot not found

Snapshot ID: snap_invalid_123
Status: Not found

The specified snapshot does not exist.

Available Snapshots for sbx_abc123xyz:
  snap_oauth_20250118_104530 (2h ago) - oauth-tests-passing
  snap_auth_20250117_153000 (1d ago) - authentication-complete
  snap_base_20250116_090000 (2d ago) - initial-setup

Available Actions:

  List all snapshots:
    /list-snapshots sbx_abc123xyz

  Restore from available snapshot:
    /sandbox-restore sbx_abc123xyz snap_oauth_20250118_104530

Troubleshooting:
  - Check snapshot ID spelling
  - Verify snapshot hasn't been deleted
  - Snapshots expire after retention period (default 30 days)
```

### Error 2: Insufficient Disk Space

```
❌ Error: Insufficient disk space for restore

Target: sbx_abc123xyz
Snapshot Size: 3.7 GB (decompressed)
Available Space: 2.1 GB
Shortfall: 1.6 GB

Current Disk Usage:
  Total: 10 GB
  Used: 7.9 GB (79%)
  Available: 2.1 GB (21%)

Cannot restore - not enough disk space.

Recovery Options:

  Option 1: Clean Sandbox First
  ───────────────────────────────────────
    /sandbox-exec sbx_abc123xyz "npm run clean"
    /sandbox-restore sbx_abc123xyz snap_oauth_20250118_104530

  Expected Cleanup: ~1-2 GB
  Then retry restore

  Option 2: Selective Restore
  ───────────────────────────────────────
    /sandbox-restore sbx_abc123xyz snap_oauth_20250118_104530 \
      --exclude "node_modules/**"

  Restore source only (~1 GB)
  Run npm install after restore

  Option 3: Restore to New Sandbox
  ───────────────────────────────────────
    /sandbox-restore --new snap_oauth_20250118_104530

  Creates clean sandbox with enough space

Recommendation: Option 1 if current sandbox valuable,
                Option 3 for clean start
```

### Error 3: Snapshot Integrity Failed

```
❌ Error: Snapshot integrity verification failed

Snapshot: snap_oauth_20250118_104530
Checksum: Failed

Integrity Check Results:
  Expected: sha256:abc123def456...
  Actual: sha256:xyz789ghi012...
  Status: ❌ Mismatch

The snapshot appears corrupted or incomplete.

Details:
  Download Size: 1.2 GB
  Expected Size: 1.2 GB (matches)
  Checksum: Mismatch (data corruption)

Possible Causes:
  - Network errors during download
  - Storage corruption
  - Incomplete upload

Recovery Options:

  Option 1: Retry Download
  ───────────────────────────────────────
    /sandbox-restore sbx_abc123xyz snap_oauth_20250118_104530 \
      --retry

  Re-downloads snapshot from storage
  May fix temporary network errors

  Option 2: Force Restore (Skip Verification)
  ───────────────────────────────────────
    /sandbox-restore sbx_abc123xyz snap_oauth_20250118_104530 \
      --verify=false --force

  ⚠️ Skips integrity check
  ⚠️ May result in corrupted state

  Option 3: Use Different Snapshot
  ───────────────────────────────────────
    /list-snapshots sbx_abc123xyz
    /sandbox-restore sbx_abc123xyz <other_snapshot>

  Restore from different, valid snapshot

Recommendation: Try Option 1 first
                Option 3 if retry fails
```

### Error 4: Sandbox Already in Use

```
❌ Error: Cannot restore - sandbox in use

Sandbox: sbx_abc123xyz
Status: Active (in use)
Issue: #47 - Add OAuth Integration

Conflicts Detected:
  - Agent actively working on issue #47
  - Build process running (PID 1234)
  - Open SSH connections: 2

Cannot restore while sandbox is actively being used.

Recovery Options:

  Option 1: Pause Feature First
  ───────────────────────────────────────
    /pause-feature 47
    /sandbox-restore sbx_abc123xyz snap_oauth_20250118_104530
    /resume-feature 47

  Safely pause, restore, then resume

  Option 2: Stop Processes
  ───────────────────────────────────────
    /sandbox-exec sbx_abc123xyz "pkill -9 node"
    /sandbox-restore sbx_abc123xyz snap_oauth_20250118_104530

  Manually stop processes first

  Option 3: Force Restore
  ───────────────────────────────────────
    /sandbox-restore sbx_abc123xyz snap_oauth_20250118_104530 \
      --force

  ⚠️ Interrupts active work
  ⚠️ May lose unsaved changes

  Option 4: Restore to New Sandbox
  ───────────────────────────────────────
    /sandbox-restore --new snap_oauth_20250118_104530

  Creates separate sandbox from snapshot
  Original sandbox continues working

Recommendation: Option 1 for safe approach
                Option 4 to avoid interruption
```

### Error 5: Git Merge Conflict

```
❌ Error: Git merge conflict detected

Sandbox: sbx_abc123xyz
Current Branch: feature/oauth-integration
Current Commit: def789ghi012
Snapshot Branch: feature/oauth-integration
Snapshot Commit: abc123def456

Conflict:
  Attempting to restore git state would create conflicts

  Current state has diverged from snapshot:
    +12 commits ahead
    -0 commits behind
    4 files modified both places

Modified Files (Both):
  src/auth/oauth.ts
  src/auth/oauth.test.ts
  package.json
  README.md

Recovery Options:

  Option 1: Force Git Reset
  ───────────────────────────────────────
    /sandbox-restore sbx_abc123xyz snap_oauth_20250118_104530 \
      --components git --force

  ⚠️ Discards current commits (12 lost)
  ⚠️ Resets to snapshot state

  Option 2: Restore Without Git
  ───────────────────────────────────────
    /sandbox-restore sbx_abc123xyz snap_oauth_20250118_104530 \
      --components filesystem,environment

  Restores files/env, keeps current git state
  Manually merge if needed

  Option 3: Backup Current State First
  ───────────────────────────────────────
    /sandbox-snapshot sbx_abc123xyz --name "before-restore"
    /sandbox-restore sbx_abc123xyz snap_oauth_20250118_104530 \
      --force

  Creates backup of current state
  Then force restore

  Option 4: Restore to New Sandbox
  ───────────────────────────────────────
    /sandbox-restore --new snap_oauth_20250118_104530

  Avoids conflicts entirely

Recommendation: Option 3 to preserve current work
```

### Error 6: Environment Variable Conflicts

```
❌ Error: Environment variable conflicts detected

Sandbox: sbx_abc123xyz
Snapshot: snap_oauth_20250118_104530

Conflicts:
  Current environment has production credentials
  Snapshot environment has development credentials

Variable Conflicts:
  DATABASE_URL
    Current:  postgresql://prod.db.com/prod_db (production)
    Snapshot: postgresql://localhost/dev_db (development)

  API_KEY
    Current:  sk_live_xyz789... (production key)
    Snapshot: sk_test_abc123... (test key)

  NODE_ENV
    Current:  production
    Snapshot: development

⚠️ Restoring would replace production credentials with dev

Recovery Options:

  Option 1: Restore Other Components Only
  ───────────────────────────────────────
    /sandbox-restore sbx_abc123xyz snap_oauth_20250118_104530 \
      --components filesystem,git

  Skip environment restoration
  Keep current credentials

  Option 2: Manual Environment Merge
  ───────────────────────────────────────
    /sandbox-restore sbx_abc123xyz snap_oauth_20250118_104530
    # Then manually fix environment:
    /sandbox-exec sbx_abc123xyz "export DATABASE_URL=..."

  Restore all, then fix environment manually

  Option 3: Force Restore (Accept Dev Credentials)
  ───────────────────────────────────────
    /sandbox-restore sbx_abc123xyz snap_oauth_20250118_104530 \
      --force

  ⚠️ Replaces prod credentials with dev
  Use only if sandbox is for development

Recommendation: Option 1 to preserve production credentials
```

### Error 7: Download Timeout

```
❌ Error: Snapshot download timed out

Snapshot: snap_oauth_20250118_104530
Size: 1.2 GB (compressed)
Downloaded: 820 MB (68%)
Timeout: 300 seconds (5 minutes)

Download timed out before completion.

Network Status:
  Speed: ~4.5 MB/s (slow)
  Expected Time: ~4.5 minutes
  Actual Time: >5 minutes (timeout)

Recovery Options:

  Option 1: Retry with Extended Timeout
  ───────────────────────────────────────
    /sandbox-restore sbx_abc123xyz snap_oauth_20250118_104530 \
      --timeout 900

  Extends timeout to 15 minutes
  Use if network is slow but stable

  Option 2: Resume Download
  ───────────────────────────────────────
    /sandbox-restore sbx_abc123xyz snap_oauth_20250118_104530 \
      --resume

  Resumes from 68% (820 MB)
  Downloads remaining 380 MB only

  Option 3: Check Network
  ───────────────────────────────────────
    # Check connectivity
    ping storage.bumba.sandbox

    # Retry when network stable
    /sandbox-restore sbx_abc123xyz snap_oauth_20250118_104530

Recommendation: Try Option 2 to resume download
```

### Error 8: Permission Denied

```
❌ Error: Permission denied

Sandbox: sbx_abc123xyz
Owner: @lead-developer
Current User: @developer
Operation: Restore snapshot

You do not have permission to restore this sandbox.

Permission Details:
  Sandbox Owner: @lead-developer
  Your Role: contributor
  Required: owner or admin

Available Actions:

  Option 1: Request Permission
  ───────────────────────────────────────
    Contact @lead-developer to:
    - Grant restore permission
    - Restore snapshot on your behalf

  Option 2: Restore to New Sandbox
  ───────────────────────────────────────
    /sandbox-restore --new snap_oauth_20250118_104530

  Creates your own sandbox from snapshot
  No permission needed for new sandbox

  Option 3: Admin Override (If Admin)
  ───────────────────────────────────────
    /sandbox-restore sbx_abc123xyz snap_oauth_20250118_104530 \
      --admin

  ⚠️ Requires admin privileges

Recommendation: Option 2 to create your own sandbox
```

## Integration

### Integration with Snapshot System
- Validates snapshot exists and is accessible
- Downloads snapshot from Bumba Sandbox cloud storage
- Verifies snapshot integrity via checksums
- Decompresses snapshot data
- Manages snapshot metadata

### Integration with Sandbox Management
- Validates target sandbox availability
- Stops running processes if requested
- Applies filesystem restoration
- Restarts processes if needed
- Updates sandbox metadata

### Integration with Git Worktree
- Restores git repository state
- Checks out correct branch
- Resets to snapshot commit
- Handles merge conflicts
- Preserves git configuration

### Integration with Environment Management
- Restores environment variables
- Applies .env file contents
- Validates variable values
- Handles credential conflicts
- Updates process environments

### Integration with Backup System
- Can create pre-restore backup
- Enables restore undo operation
- Maintains backup metadata
- Integrates with snapshot system

## Use Cases

### Use Case 1: Rollback After Failed Change
**Scenario**: Recent refactoring broke tests; need to rollback.

**Command**:
```bash
/sandbox-restore sbx_abc123xyz snap_oauth_20250118_104530 --preserve-current
```

**Result**: Sandbox restored to working state, current state backed up.

### Use Case 2: Debug with Known-Good State
**Scenario**: Need to debug issue using known-good baseline.

**Command**:
```bash
/sandbox-restore --new snap_oauth_20250118_104530
```

**Result**: New sandbox created from snapshot for isolated debugging.

### Use Case 3: Restore Environment Only
**Scenario**: Environment variables corrupted; need to fix without changing code.

**Command**:
```bash
/sandbox-restore sbx_abc123xyz snap_oauth_20250118_104530 --components environment
```

**Result**: Environment variables restored, code unchanged.

### Use Case 4: Clone Sandbox State
**Scenario**: Create identical sandbox for parallel testing.

**Command**:
```bash
/sandbox-restore --new snap_oauth_20250118_104530
```

**Result**: New sandbox with identical state to snapshot.

### Use Case 5: Recover from Corruption
**Scenario**: Sandbox filesystem corrupted; need full restoration.

**Command**:
```bash
/sandbox-restore sbx_abc123xyz snap_oauth_20250118_104530 --force
```

**Result**: Complete sandbox restoration despite corruption warnings.

## Performance Considerations

### Restore Speed
- Download: 20-60 seconds (depends on size and network)
- Decompress: 10-30 seconds
- Filesystem restore: 20-60 seconds
- Total: 1-3 minutes typical

### Network Impact
- Download size: Compressed snapshot size (30-40% of original)
- Bandwidth: ~10-50 MB/s typical
- Resumable: Yes (can resume failed downloads)

### Disk Impact
- Temporary space: 2x snapshot size during restore
- Final size: Original snapshot size (uncompressed)

## Notes

- **Backup First**: Use `--preserve-current` for safety
- **Selective Restore**: Use `--components` to restore specific parts
- **New Sandbox**: Use `--new` to create from snapshot without modifying existing
- **Force Option**: Use cautiously, can cause data loss
- **Verification**: Always enabled by default for safety
- **Process Stop**: Recommended to avoid conflicts
- **Git State**: Handles branch switching and commit reset
- **Environment**: Can selectively restore or exclude
- **Rollback**: Can undo restore using pre-restore backup
- **Integrity**: Checksums verified before restore
- **Atomic**: Restore is all-or-nothing for safety

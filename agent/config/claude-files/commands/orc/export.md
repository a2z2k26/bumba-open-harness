---
name: export
description: Export session data and metrics (Deployment stage)
---

# /export-session Command

Exports complete orchestration session data including agent states, event logs, performance metrics, sandbox configurations, and git states to various formats (JSON, CSV, HTML report, ZIP archive). Enables session archival, audit trails, debugging, and knowledge sharing.

## Usage

```
/export-session [session_id] [options]
```

## Parameters

- `[session_id]` (optional): Session ID to export - default: current active session
- `--format <type>` (optional): Export format (json, csv, html, zip, all) - default: json
- `--include <components>` (optional): Components to include (agents,events,metrics,sandboxes,git,all) - default: all
- `--output <path>` (optional): Output file path - default: .bumba/exports/session_<id>_<timestamp>
- `--compress` (optional): Compress export (gzip) - default: true
- `--anonymize` (optional): Remove sensitive data (API keys, tokens) - default: false
- `--time-range <start>-<end>` (optional): Filter events by time range
- `--include-artifacts` (optional): Include sandbox artifacts (builds, logs) - default: false

## Workflow

### Step 1: Session Identification

```
📦 Export Orchestration Session
═══════════════════════════════════════════════

Identifying session...
  Session ID: orch_abc123xyz (current active session)
  Started: 2025-01-18T08:00:00Z
  Duration: 5h 30m (still running)
  Status: Active

Session Summary:
  Total Agents: 8 (5 completed, 2 active, 1 failed)
  Features Implemented: #42, #45, #47, #49, #50
  Active Features: #51, #52
  Failed Features: #53
  Total Events: 1,247
  Sandboxes Used: 8
  Strategy: balanced

Export Configuration:
  Format: JSON (compressed)
  Include: All components
  Output: .bumba/exports/session_orch_abc123xyz_20250118_133000/
  Compress: Yes
  Anonymize: No

───────────────────────────────────────────────
```

### Step 2: Data Collection

```
Collecting session data...

Agent States (8 agents):
  ⟳ Collecting agent metadata...
  ✓ Agent #42: Completed (OAuth Integration)
  ✓ Agent #45: Completed (Payment Integration)
  ✓ Agent #47: Completed (Email Notifications)
  ✓ Agent #49: Completed (File Upload)
  ✓ Agent #50: Completed (Search Functionality)
  ✓ Agent #51: Active (Dashboard Redesign)
  ✓ Agent #52: Active (API v2)
  ✓ Agent #53: Failed (Real-time Chat)

  Collected:
    • Agent configurations
    • Progress checkpoints
    • Operation history
    • Error logs
    • Resource usage

Event Logs (1,247 events):
  ⟳ Exporting event stream...
  ✓ Spawn events: 8
  ✓ Progress events: 324
  ✓ Completion events: 5
  ✓ Error events: 12
  ✓ State changes: 45
  ✓ User actions: 83
  ✓ System events: 770

  Event Types:
    • SPAWN, COMPLETE, FAIL
    • PAUSE, RESUME
    • STATE_CHANGE
    • ERROR, WARNING, INFO
    • USER_ACTION

Performance Metrics:
  ⟳ Collecting performance data...
  ✓ Agent execution times
  ✓ Sandbox resource usage
  ✓ API response times
  ✓ Build/test durations
  ✓ Cost tracking data

  Metrics Collected:
    • Total execution time: 5h 30m
    • Average agent completion: 42 minutes
    • Success rate: 83% (5/6 completed)
    • Total cost: $45.60
    • Average cost per feature: $9.12

Sandbox Configurations (8 sandboxes):
  ⟳ Exporting sandbox data...
  ✓ Sandbox metadata
  ✓ Resource allocations
  ✓ Environment variables (sanitized)
  ✓ Git repository states
  ✓ Filesystem snapshots (metadata)

Git States (8 repositories):
  ⟳ Collecting git information...
  ✓ Branch names
  ✓ Commit SHAs
  ✓ Diff statistics
  ✓ Pull request links
  ✓ Merge status

───────────────────────────────────────────────
```

### Step 3: Data Formatting

```
Formatting export data...

JSON Export:
  ⟳ Generating JSON structure...
  ✓ session_metadata.json (8.2 KB)
  ✓ agents.json (124 KB)
  ✓ events.json (456 KB)
  ✓ metrics.json (89 KB)
  ✓ sandboxes.json (67 KB)
  ✓ git_states.json (34 KB)

Total JSON Size: 778 KB

CSV Exports:
  ⟳ Converting to CSV format...
  ✓ agents.csv (45 KB)
  ✓ events.csv (234 KB)
  ✓ metrics.csv (56 KB)

HTML Report:
  ⟳ Generating interactive HTML report...
  ✓ index.html (main report)
  ✓ Timeline visualization
  ✓ Agent details pages
  ✓ Event log viewer
  ✓ Performance charts
  ✓ Cost breakdown

───────────────────────────────────────────────
```

### Step 4: Compression and Finalization

```
Finalizing export...

Compressing files:
  ⟳ Creating archive...
  Original Size: 1.2 MB
  Compressed Size: 340 KB (72% reduction)
  Format: ZIP with gzip compression

Archive Contents:
  session_orch_abc123xyz_20250118/
    ├── session_metadata.json
    ├── agents/
    │   ├── agent_42.json
    │   ├── agent_45.json
    │   ├── ... (6 more)
    ├── events/
    │   ├── events.json
    │   ├── events.csv
    ├── metrics/
    │   ├── performance.json
    │   ├── costs.json
    │   ├── resource_usage.json
    ├── sandboxes/
    │   ├── sandbox_configs.json
    │   ├── sandbox_metadata.json
    ├── git/
    │   ├── repository_states.json
    │   ├── commits.json
    ├── reports/
    │   ├── index.html
    │   ├── timeline.html
    │   ├── performance.html
    │   ├── costs.html
    └── README.md

Generating checksums:
  ✓ SHA-256: abc123def456...
  ✓ Checksum file: SHA256SUMS

───────────────────────────────────────────────
```

### Step 5: Export Confirmation

```
✅ Session Export Complete
═══════════════════════════════════════════════

Export Details:
  Session: orch_abc123xyz
  Duration: 5h 30m (08:00 - 13:30)
  Status: Active (exported snapshot)

Exported Data:
  Agents: 8 (5 completed, 2 active, 1 failed)
  Events: 1,247
  Sandboxes: 8
  Size: 340 KB (compressed from 1.2 MB)

Output Location:
  .bumba/exports/session_orch_abc123xyz_20250118_133000.zip

Archive Contents:
  ✓ Session metadata
  ✓ Agent states and history
  ✓ Complete event log
  ✓ Performance metrics
  ✓ Sandbox configurations
  ✓ Git repository states
  ✓ HTML reports
  ✓ CSV data files

Checksum:
  SHA-256: abc123def456789...
  Verify: sha256sum -c SHA256SUMS

View Report:
  unzip session_orch_abc123xyz_20250118_133000.zip
  open session_orch_abc123xyz_20250118/reports/index.html

Import Session (Future):
  /import-session .bumba/exports/session_orch_abc123xyz_20250118_133000.zip

Share:
  Compressed size suitable for email/Slack
  No sensitive data (use --anonymize for extra safety)

───────────────────────────────────────────────
```

## Examples

### Example 1: Export Current Session (Default)

```
/export-session
```

**Output**:
```
📦 Export Current Session

Session: orch_abc123xyz (active)
Duration: 5h 30m

⟳ Collecting data...
✓ Agents: 8
✓ Events: 1,247
✓ Metrics: Complete

⟳ Generating export...
✓ JSON: 778 KB
✓ HTML Report: Generated
✓ Compressed: 340 KB

✅ Exported to:
.bumba/exports/session_orch_abc123xyz_20250118.zip

View: open .bumba/exports/session_orch_abc123xyz_20250118/reports/index.html
```

### Example 2: Export Specific Session

```
/export-session orch_previous123 --format all
```

**Output**:
```
📦 Export Specific Session

Session: orch_previous123 (completed)
Completed: 2025-01-17T18:00:00Z
Duration: 8h 15m

⟳ Collecting data...
✓ Agents: 12 (all completed)
✓ Events: 2,456
✓ Metrics: Complete

⟳ Generating all formats...
✓ JSON: 1.2 MB
✓ CSV: 456 KB
✓ HTML: 234 KB

✅ Exported (all formats)
Size: 1.9 MB → 620 KB (compressed)

Output:
.bumba/exports/session_orch_previous123_20250118/
```

### Example 3: Export with Anonymization

```
/export-session --anonymize
```

**Output**:
```
📦 Export Session (Anonymized)

Session: orch_abc123xyz

🔒 Anonymizing sensitive data...
✓ API keys removed
✓ Access tokens removed
✓ Email addresses masked
✓ IP addresses removed
✓ Environment variables sanitized

Anonymization Summary:
  Removed: 24 API keys
  Masked: 18 email addresses
  Sanitized: 42 environment variables

⟳ Exporting...
✓ Safe for sharing

✅ Exported (anonymized)
.bumba/exports/session_orch_abc123xyz_anonymized_20250118.zip

Safe to share externally ✓
```

### Example 4: Export Events Only (Time Range)

```
/export-session --include events --time-range "2025-01-18T10:00:00Z-2025-01-18T12:00:00Z"
```

**Output**:
```
📦 Export Events (Time Range)

Session: orch_abc123xyz
Time Range: 10:00 - 12:00 (2 hours)

⟳ Filtering events...
Total Events: 1,247
Filtered: 324 (in time range)

Event Types:
  SPAWN: 3
  PROGRESS: 142
  COMPLETE: 2
  ERROR: 4
  INFO: 173

⟳ Exporting...
✓ events_20250118_1000-1200.json (78 KB)
✓ events_20250118_1000-1200.csv (45 KB)

✅ Exported (events only)
.bumba/exports/events_20250118_1000-1200.zip
```

### Example 5: Export with Artifacts

```
/export-session --include-artifacts
```

**Output**:
```
📦 Export Session with Artifacts

Session: orch_abc123xyz

⚠️ Warning: Including artifacts will significantly increase export size

⟳ Collecting artifacts...
  Build Outputs: 245 MB
  Test Reports: 12 MB
  Log Files: 89 MB
  Screenshots: 34 MB
  Total: 380 MB

⟳ Compressing...
Original: 1.2 GB (with artifacts)
Compressed: 420 MB (65% reduction)

✅ Exported with Artifacts
Size: 420 MB

⚠️ Large file - consider uploading to cloud storage

Output: .bumba/exports/session_orch_abc123xyz_full_20250118.zip
```

### Example 6: HTML Report Only

```
/export-session --format html
```

**Output**:
```
📦 Export HTML Report

Session: orch_abc123xyz

⟳ Generating interactive report...
✓ Timeline visualization
✓ Agent performance charts
✓ Cost breakdown
✓ Event log viewer

Report Pages:
  • index.html - Overview
  • timeline.html - Event timeline
  • agents.html - Agent details
  • performance.html - Performance metrics
  • costs.html - Cost analysis

✅ HTML Report Generated
Open: .bumba/exports/session_orch_abc123xyz_report_20250118/index.html

Interactive Features:
  • Filterable event log
  • Sortable agent table
  • Interactive charts
  • Exportable data
```

### Example 7: Export to Custom Location

```
/export-session --output /backups/session-backup --format json --compress
```

**Output**:
```
📦 Export to Custom Location

Session: orch_abc123xyz
Output: /backups/session-backup

⟳ Exporting...
✓ JSON: 778 KB
✓ Compressed: 340 KB

✅ Exported
Location: /backups/session-backup.zip

Backup complete ✓
```

### Example 8: Export Metrics Only

```
/export-session --include metrics --format csv
```

**Output**:
```
📦 Export Metrics (CSV)

Session: orch_abc123xyz

⟳ Collecting metrics...
✓ Agent execution times
✓ Resource usage
✓ API response times
✓ Cost data

CSV Files Generated:
  • agent_execution_times.csv
  • resource_usage.csv
  • api_response_times.csv
  • costs.csv
  • summary.csv

✅ Metrics Exported (CSV)
.bumba/exports/metrics_20250118/

Import to Excel/Sheets for analysis
```

## Error Handling

### Error 1: Session Not Found

```
❌ Error: Session not found

Session ID: orch_invalid123
Status: Not found

The specified session does not exist.

Available Sessions:
  orch_abc123xyz (active) - 5h 30m ago
  orch_previous123 (completed) - 1 day ago
  orch_old456 (completed) - 3 days ago

Available Actions:

  List all sessions:
    /list-sessions

  Export current session:
    /export-session

  Export specific session:
    /export-session orch_abc123xyz
```

### Error 2: Insufficient Disk Space

```
❌ Error: Insufficient disk space

Export Size: 1.2 GB (estimated)
Available Space: 450 MB
Shortfall: 750 MB

Cannot create export - not enough disk space.

Recovery Options:

  Option 1: Clean Old Exports
  ───────────────────────────────────────
    ls .bumba/exports/
    rm -rf .bumba/exports/old_session_*

  Expected Cleanup: ~800MB-1.5GB

  Option 2: Export Without Artifacts
  ───────────────────────────────────────
    /export-session --include-artifacts=false

  Reduces size by ~80% (1.2GB → 240MB)

  Option 3: Export to External Drive
  ───────────────────────────────────────
    /export-session --output /Volumes/External/backup

Recommendation: Option 2 for most cases
```

### Error 3: Export Permission Denied

```
❌ Error: Permission denied

Output Path: /protected/exports/
Reason: Insufficient write permissions

Cannot write to specified output directory.

Recovery Options:

  Option 1: Use Default Location
  ───────────────────────────────────────
    /export-session

  Exports to .bumba/exports/ (user writable)

  Option 2: Change Output Path
  ───────────────────────────────────────
    /export-session --output ~/exports/

  Option 3: Fix Permissions
  ───────────────────────────────────────
    sudo chmod 755 /protected/exports/

Recommendation: Option 1 or Option 2
```

### Error 4: Active Session Changes During Export

```
⚠️ Warning: Session changed during export

Session: orch_abc123xyz
Status: Active (still running)

Changes detected during export:
  • Agent #53 completed (was active)
  • New events: 42 (during export)
  • Metrics updated

Export Snapshot:
  Captured: 2025-01-18T13:30:00Z
  Current Time: 2025-01-18T13:32:45Z
  Lag: 2m 45s

Recovery Options:

  Option 1: Use Exported Snapshot
  ───────────────────────────────────────
    Export completed successfully
    Reflects state at 13:30:00Z
    Consistent snapshot ✓

  Option 2: Re-export Current State
  ───────────────────────────────────────
    /export-session

  Captures latest state (with #53 completed)

Recommendation: Option 1 (snapshot is consistent)
Note: Export captures point-in-time state
```

### Error 5: Anonymization Failed

```
❌ Error: Anonymization failed

Reason: Unable to sanitize all sensitive data

Issues Found:
  ⚠️ API keys embedded in error messages
  ⚠️ Credentials in git commit messages
  ⚠️ Secrets in environment variable names

Cannot guarantee safe export with --anonymize.

Recovery Options:

  Option 1: Manual Review
  ───────────────────────────────────────
    /export-session --anonymize=false
    # Manually review and redact sensitive data

  Option 2: Export Without Sensitive Components
  ───────────────────────────────────────
    /export-session --include agents,events,metrics

  Excludes sandboxes (which contain sensitive data)

  Option 3: Force Anonymization (Partial)
  ───────────────────────────────────────
    /export-session --anonymize --force

  ⚠️ Some sensitive data may remain

Recommendation: Option 2 for safe sharing
                Option 1 for complete data
```

## Integration

### Integration with Orchestration System
- Exports complete orchestration state
- Captures all agent configurations
- Preserves event timeline
- Enables session replay and analysis

### Integration with Monitoring System
- Exports performance metrics
- Includes resource usage data
- Tracks cost information
- Provides audit trail

### Integration with Reporting System
- Generates HTML reports
- Creates visualizations
- Exports to CSV for analysis
- Enables data-driven insights

### Integration with Archive System
- Compresses exports for storage
- Generates checksums for integrity
- Supports long-term archival
- Enables version control

### Integration with Security System
- Anonymizes sensitive data
- Removes API keys and tokens
- Sanitizes environment variables
- Enables safe sharing

## Use Cases

### Use Case 1: Session Archival
**Scenario**: Completed session, want to archive for records.

**Command**:
```bash
/export-session orch_completed123 --compress
```

**Result**: Compressed archive of complete session (340 KB).

### Use Case 2: Debugging Failed Session
**Scenario**: Session failed, need detailed logs for debugging.

**Command**:
```bash
/export-session --include events,metrics --include-artifacts
```

**Result**: Complete event logs and metrics with build artifacts.

### Use Case 3: Sharing with Team
**Scenario**: Want to share session results with team (anonymized).

**Command**:
```bash
/export-session --anonymize --format html
```

**Result**: Anonymized HTML report safe for sharing.

### Use Case 4: Cost Analysis
**Scenario**: Need cost breakdown for billing/reporting.

**Command**:
```bash
/export-session --include metrics --format csv
```

**Result**: CSV files with detailed cost data.

### Use Case 5: Audit Trail
**Scenario**: Compliance requirement for session audit trail.

**Command**:
```bash
/export-session --format all --compress
```

**Result**: Complete session export in all formats with checksums.

## Performance Considerations

### Export Speed
- Small session (<100 events): 5-10 seconds
- Medium session (100-1000 events): 10-30 seconds
- Large session (1000+ events): 30-90 seconds
- With artifacts: +2-10 minutes

### Export Size
- Minimal (events only): 50-200 KB
- Standard (all data): 200-800 KB
- With artifacts: 200-500 MB
- Compressed: 30-70% reduction

### Resource Usage
- Memory: <100 MB typical
- Disk: 2x export size temporarily
- CPU: Low (compression phase)

## Notes

- **Point-in-Time**: Export captures snapshot at export time
- **Compression**: Enabled by default, 60-70% size reduction
- **Anonymization**: Removes API keys, tokens, sensitive data
- **Multiple Formats**: JSON, CSV, HTML, or all
- **Selective Export**: Can export specific components
- **Artifacts Optional**: Build outputs, logs (large files)
- **Checksums**: SHA-256 for integrity verification
- **Time Ranges**: Filter events by time period
- **Active Sessions**: Can export while session running
- **HTML Reports**: Interactive visualizations and charts
- **Safe Sharing**: Anonymization for external sharing
- **Import Support**: Exported sessions can be re-imported (future)

# Enhancement Tools & Utilities

Tools to enhance your Claude Code workflow, created during the documentation audit.

## Quick Search Tool

**Location**: `/opt/bumba-harness/.claude/scripts/search-docs.sh`

Search across all documentation quickly.

### Usage
```bash
# Basic search
~/.claude/scripts/search-docs.sh "design system"

# Search for commands
~/.claude/scripts/search-docs.sh "/design-"

# Search for agents
~/.claude/scripts/search-docs.sh "backend-architect"

# Page through results
~/.claude/scripts/search-docs.sh "authentication" | less
```

### What It Searches
- All inventory documents (agents, commands, skills, hooks, plugins)
- Department quick references
- Framework documentation
- Workflow templates

### Output
Shows matches from each document type with line numbers and context.

---

## Feature Usage Tracker

**Location**: `/opt/bumba-harness/.claude/scripts/feature-usage-tracker.sh`

Analyzes your history to show which features you actually use.

### Usage
```bash
~/.claude/scripts/feature-usage-tracker.sh
```

### What It Shows
- **Top 20 Commands**: Most frequently used slash commands
- **Top 20 Agents**: Most invoked agents
- **Top 20 Skills**: Most used skills

### Output Files
- **Terminal**: Live top 20 lists
- **Report**: `/opt/bumba-harness/.claude/docs/feature-usage-report.md`

### Benefits
- **Identify core features**: Focus documentation and optimization on what you use
- **Find unused features**: Candidates for archival or better docs
- **Usage patterns**: Understand your workflow habits

### Recommendations
Run monthly to track trends.

---

## Directory Cleanup Tool

**Location**: `/opt/bumba-harness/.claude/scripts/cleanup-claude-dir.sh`

Safe cleanup with automatic archival. Can save ~300 MB.

### Usage
```bash
# Dry run (see what would be cleaned)
~/.claude/scripts/cleanup-claude-dir.sh

# Execute cleanup
~/.claude/scripts/cleanup-claude-dir.sh --execute
```

### What It Cleans

| Directory | Retention | Archive | Expected Savings |
|-----------|-----------|---------|------------------|
| `debug/` | 30 days | Yes | 200-250 MB |
| `shell-snapshots/` | 60 days | Yes | 40-50 MB |
| `file-history/` | 90 days | Yes | 15-20 MB |
| `paste-cache/` | 7 days | No | 300-400 KB |
| `session-env/` | 7 days | No | Varies |

### Archives Location
`/opt/bumba-harness/.claude/archive/`

Archives are compressed `.tar.gz` files named by date (e.g., `debug-202601.tar.gz`).

### Safety
- **Dry run by default**: Won't delete anything without `--execute` flag
- **Archives created first**: Old files archived before deletion
- **Keeps recent files**: Only cleans files older than retention period

### Recommendations
- Run monthly for best results
- Review archives after 6 months (safe to delete old archives)
- Check archive directory size periodically

---

## Workflow Templates

**Location**: `/opt/bumba-harness/.claude/templates/workflows/`

Pre-built workflows for common scenarios.

### Available Workflows

#### 1. Figma to React
**File**: `design-figma-to-react.md`
**Duration**: 15 min (first time), 5 min (subsequent)
**Steps**: 7 steps from design-init to production deployment

#### 2. Quarterly Planning
**File**: `product-quarterly-planning.md`
**Duration**: 25 min (vs. 4-8 hours manual)
**Steps**: Market research → brainstorm → roadmap → GitHub issues

#### 3. Full-Stack Feature
**File**: `full-stack-feature-development.md`
**Duration**: 2-4 hours (vs. 2-5 days manual)
**Phases**: Planning → Design → Development → QA → Deployment

### Usage
1. Open workflow file
2. Copy commands/agent invocations
3. Replace placeholders with your context
4. Follow steps sequentially
5. Save artifacts for reference

### Creating Custom Workflows
See `workflows/README.md` for template structure.

---

## Setup & Installation

All tools are already installed and ready to use.

### Make Scripts Executable (if needed)
```bash
chmod +x ~/.claude/scripts/search-docs.sh
chmod +x ~/.claude/scripts/feature-usage-tracker.sh
chmod +x ~/.claude/scripts/cleanup-claude-dir.sh
```

### Add to PATH (optional)
Add to your `~/.zshrc` or `~/.bashrc`:
```bash
export PATH="$PATH:$HOME/.claude/scripts"
```

Then use commands directly:
```bash
search-docs.sh "authentication"
feature-usage-tracker.sh
cleanup-claude-dir.sh
```

---

## Maintenance Recommendations

### Daily
- Use `search-docs.sh` when you can't remember a feature name

### Weekly
- Review workflow templates before starting major tasks

### Monthly
- Run `feature-usage-tracker.sh` to see usage trends
- Run `cleanup-claude-dir.sh --execute` to free disk space
- Review `feature-usage-report.md` for optimization opportunities

### Quarterly
- Archive old debug files and snapshots
- Review unused features (candidates for removal or better docs)
- Update workflow templates based on new patterns

---

## Future Enhancements

Potential additions based on audit findings:

1. **Auto-completion**: Shell completion for commands and agents
2. **Workflow Recorder**: Record your command sequences as reusable workflows
3. **Feature Recommender**: Suggest relevant features based on current task
4. **Usage Dashboard**: Visual dashboard of feature usage over time
5. **Dependency Analyzer**: Show which features depend on each other

---

**Created**: 2026-01-15
**Purpose**: Enhance productivity discovered during documentation audit
**Tools**: 3 scripts + workflow templates
**Potential Impact**: ~300 MB disk savings + faster feature discovery

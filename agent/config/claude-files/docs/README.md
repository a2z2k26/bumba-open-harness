# Claude Code Feature Documentation

Welcome to the comprehensive documentation of your Claude Code custom features. This directory contains detailed inventories of all agents, commands, skills, hooks, and plugins you've built over the past year.

## Quick Navigation

### By Feature Type
- **[Agents Inventory](./inventory-agents.md)** - 40 specialized AI agents
- **[Commands Inventory](./inventory-commands.md)** - 81 slash commands
- **[Skills Inventory](./inventory-skills.md)** - 51 knowledge modules
- **[Hooks Inventory](./inventory-hooks.md)** - 23 event-driven automations
- **[Plugins Inventory](./inventory-plugins.md)** - 8 feature bundles

### By Department
- **[Product Strategy](./dept-product-strategy.md)** - Vision, roadmaps, requirements (7 agents, 18 commands)
- **[Design](./dept-design.md)** - UI/UX, design systems, design-to-code (8 agents, 25 commands, 6 plugins)
- **[Engineering](./dept-engineering.md)** - Backend, frontend, APIs, code quality (7 agents, 12 commands, 18 skills)
- **[Operations](./dept-operations.md)** - Infrastructure, deployment, monitoring (7 agents, 22 commands)
- **[QA/Testing](./dept-qa-testing.md)** - Test automation, quality assurance (6 agents, 5 commands)

## Summary Statistics

| Category | Count | Location |
|----------|-------|----------|
| **Agents** | 40 | `~/.claude/agents/` |
| **Commands** | 81 | `~/.claude/commands/` |
| **Skills** | 51 | `~/.claude/skills/` |
| **Hooks** | 23 | `~/.claude/hooks/` |
| **Plugins** | 8 | `~/.claude/plugins/` |
| **Total Features** | 203 | - |

## Feature Categories

### Design & UI
Your most extensive category with complete design-to-code workflows:

- **8 Design Agents**: UI Designer, Visual Designer, UX Researcher, Accessibility Specialist, etc.
- **25 Design Commands**: Layout transformation, token transformation, design exploration
- **12 Design Skills**: Design Bridge integration, framework transformations, design exploration
- **14 Design Hooks**: Component lifecycle, layout transformation, token management
- **6 Design Plugins**: Design sync, design exploration, NLP design

**Key Capabilities**:
- Figma → Code transformation (React, Vue, Angular, Svelte, Flutter, SwiftUI, Jetpack Compose)
- 4-direction design exploration (Conservative, Refined, Expressive, Experimental)
- Design system management via Design Bridge
- Automated component and layout generation
- Real-time design sync from Figma

### Engineering & Development
Comprehensive backend and frontend development support:

- **7 Engineering Agents**: Backend Architect, Frontend Developer, API Engineer, Code Reviewer, etc.
- **Development Pattern Skills**: Architecture patterns, async Python, error handling, SQL optimization
- **Framework Skills**: FastAPI, React modernization, LangChain, Node.js patterns

**Key Capabilities**:
- Multi-language backend architecture (Python, Node.js, Java, Go, C#, PHP, Rust)
- REST/GraphQL API design
- Database optimization
- Performance engineering
- Code review automation

### Quality Assurance
Robust testing and quality workflows:

- **6 QA Agents**: QA Engineer, Automation Engineer, Performance Tester, Security Auditor, etc.
- **3 Testing Commands**: All tests, feature tests, matrix testing
- **1 Testing Skill**: Web app testing with Playwright

**Key Capabilities**:
- Comprehensive test automation
- Performance testing
- Security audits
- Accessibility testing
- API testing

### Operations & Infrastructure
Complete DevOps and infrastructure automation:

- **7 Ops Agents**: Cloud Architect, Kubernetes Engineer, SRE, Network Engineer, etc.
- **18 E2B Commands**: Sandbox management, cost optimization, orchestration
- **Operations Skills**: Distributed tracing, Git workflows, GitHub Actions

**Key Capabilities**:
- Multi-cloud architecture (AWS, Azure, GCP)
- Kubernetes orchestration
- CI/CD automation
- Monitoring and observability
- Cost management

### Product Strategy
Strategic planning and analysis:

- **7 Strategy Agents**: Product Metrics Analyst, Business Analyst, Market Researcher, etc.
- **8 Orchestration Commands**: Requirements, planning, brainstorming, sprint planning

**Key Capabilities**:
- Product roadmapping
- Requirements engineering
- Competitive analysis
- User behavior analysis
- Multi-agent collaboration

### Integration & Automation
Powerful integration and automation capabilities:

- **4 Notion Skills**: Knowledge capture, meeting intelligence, research documentation, spec implementation
- **3 Memory Hooks**: Session management, context preservation
- **Git/GitHub Workflows**: Feature branches, PR automation, code review

## Directory Structure

```
~/.claude/
├── agents/              # 40 specialized AI agents
├── commands/            # 81 slash commands
│   ├── design-director/ # Product specification workflow
│   ├── e2b/            # E2B sandbox management
│   ├── gh/             # GitHub workflows
│   ├── git/            # Git workflows
│   ├── orc/            # Orchestration commands
│   ├── project/        # Project management
│   └── testing/        # Testing workflows
├── skills/             # 51 knowledge modules
├── hooks/              # 23 event-driven automations
├── plugins/            # 8 feature bundles
├── docs/               # This documentation (NEW)
├── config/             # Configuration files
├── templates/          # Code templates
├── scripts/            # Utility scripts
├── instructions/       # Global instructions
├── rules/              # Complexity assessment rules
└── projects/           # Project-specific configs
```

## Most Used Features

Based on your workflow, these are likely your most valuable features:

### Design Workflows
1. `/design-init` - Initialize Design Bridge system
2. `/design-explore-ui` - Generate 4 UI directions in parallel
3. `/design-layout-to-jsx` - Transform Figma layouts to React
4. `design-ui-designer` agent - Production UI implementation

### Development Workflows
1. `engineering-backend-architect` agent - System design
2. `engineering-frontend-developer` agent - Frontend implementation
3. `/code:execute` - Execute implementation plans

### GitHub Workflows
1. `/gh:create-pr` - Auto-generate PRs with descriptions
2. `/gh:review-pr` - AI-powered code review
3. `/gh:create-issues` - Convert plans to issues

### E2B Management
1. `/e2b:cost-report` - Track sandbox costs
2. `/e2b:management:cleanup` - Remove stale sandboxes
3. `/e2b:optimize` - Reduce costs

## Enhancement Tools

To further enhance your workflow, a suite of utility scripts and workflow templates has been created:

### Quick Search Tool
**Location**: `~/.claude/scripts/search-docs.sh`

Search across all documentation quickly:
```bash
~/.claude/scripts/search-docs.sh "authentication"
~/.claude/scripts/search-docs.sh "/design-"
~/.claude/scripts/search-docs.sh "backend-architect"
```

### Feature Usage Tracker
**Location**: `~/.claude/scripts/feature-usage-tracker.sh`

Analyze your history to see which features you actually use:
```bash
~/.claude/scripts/feature-usage-tracker.sh
```

Shows top 20 commands, agents, and skills. Generates `feature-usage-report.md`.

### Directory Cleanup Tool
**Location**: `~/.claude/scripts/cleanup-claude-dir.sh`

Safe cleanup with automatic archival (can save ~300 MB):
```bash
# Dry run (see what would be cleaned)
~/.claude/scripts/cleanup-claude-dir.sh

# Execute cleanup
~/.claude/scripts/cleanup-claude-dir.sh --execute
```

### Workflow Templates
**Location**: `~/.claude/templates/workflows/`

Pre-built workflows for common scenarios:
- **[Figma to React](../templates/workflows/design-figma-to-react.md)** - ~15 min first time, ~5 min after
- **[Quarterly Planning](../templates/workflows/product-quarterly-planning.md)** - ~25 min (vs. 4-8 hours manual)
- **[Full-Stack Feature](../templates/workflows/full-stack-feature-development.md)** - 2-4 hours (vs. 2-5 days manual)

**Full Guide**: See [Enhancement Tools](./enhancement-tools.md) for complete documentation.

## Feature Frameworks

### Forty Thieves Framework
All agents follow the "Forty Thieves" naming convention, creating a cohesive team of specialized assistants:
- Design Thieves (red)
- Engineering Thieves (green)
- QA Thieves (yellow)
- Operations Thieves (blue)
- Strategy Thieves (purple)
- Chiefs (elite leaders)

### Design Bridge System
Complete design-to-code pipeline:
1. **Extract**: Pull designs from Figma
2. **Transform**: Convert to framework code
3. **Validate**: Visual comparison
4. **Sync**: Real-time updates
5. **Iterate**: Refinement loops

### E2B Orchestration
Multi-sandbox parallel execution:
1. **Spawn**: Create sandboxes with templates
2. **Execute**: Run phases (Phase 1: Design, Phase 2: Implementation)
3. **Sync**: Auto-transfer results to git worktrees
4. **Cleanup**: Destroy sandboxes to save costs

## Getting Started

### Finding Features
Use the search tools you built:

```bash
# Search across all inventories
grep -r "authentication" docs/

# List all design commands
cat docs/inventory-commands.md | grep "### /" | grep design

# Find relevant agents
cat docs/inventory-agents.md | grep "When to Use"
```

### Using Features

**Invoke Commands**:
```
/design-explore-ui
/gh:create-pr
/project:init
```

**Invoke Agents**:
```javascript
Task({
  subagent_type: "engineering-backend-architect",
  prompt: "Design authentication system..."
})
```

**Invoke Skills**:
```
Skill({
  skill: "architecture-patterns"
})
```

## Maintenance Recommendations

See [Directory Organization](./directory-organization.md) for cleanup suggestions and organizational improvements.

## Documentation Updates

These inventory documents are living documentation. Update them when you:
- Add new agents, commands, skills, hooks, or plugins
- Modify existing features
- Deprecate or remove features
- Change workflows or best practices

## Version History

- **2026-01-15**: Initial comprehensive documentation created
  - Cataloged all 203 features
  - Created category-specific inventories
  - Documented all workflows and integrations
  - Added enhancement tools (3 scripts + workflow templates)

---

**Last Updated**: 2026-01-15
**Total Features**: 203
**Enhancement Tools**: 3 scripts + workflow templates
**Documentation Status**: ✅ Complete

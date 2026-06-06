# Product Strategy Department - Quick Reference

Quick reference for Product Strategy features in Claude Code.

## Overview

Product Strategy handles vision, roadmapping, requirements, market research, and cross-functional planning.

## Agents (7)

| Agent | Purpose |
|-------|---------|
| **strategy-product-chief** | Product strategy leadership and major initiatives |
| **strategy-roadmap-strategist** | Roadmap creation and feature prioritization |
| **strategy-requirement-engineer** | Requirements gathering and user stories |
| **strategy-market-researcher** | Market trends and customer insights |
| **strategy-competitive-intelligence-analyst** | Competitive analysis and positioning |
| **strategy-user-analyst** | User behavior and journey mapping |
| **strategy-business-analyst** | Business case development and analysis |
| **strategy-product-metrics-analyst** | Analytics, KPIs, and metrics tracking |

## Commands (18)

### Design Director (Product Specs)
- `/design-director:init` - Initialize Design Director
- `/design-director:run` - Complete spec workflow
- `/design-director:vision` - Define product vision
- `/design-director:roadmap` - Create roadmap structure
- `/design-director:data-model` - Define entities and relationships
- `/design-director:section-spec` - Detail section requirements
- `/design-director:screen-spec` - Screen specifications
- `/design-director:sample-data` - Generate sample data
- `/design-director:shell-spec` - App shell and navigation
- `/design-director:export` - Export specification package

### Orchestration (Planning & Collaboration)
- `/orc:brainstorm` - Multi-agent feature ideation
- `/orc:requirements` - Gather requirements with agents
- `/orc:plan-feature` - Plan feature implementation
- `/orc:plan-sprints` - Sprint planning with breakdown
- `/orc:review-spec` - Multi-perspective spec review
- `/orc:parallel` - Parallel task execution
- `/orc:quick` - Quick orchestrated workflow
- `/orc:export` - Export orchestration results

### GitHub Integration
- `/gh:create-issues` - Convert plans to GitHub issues

### Memory
- `/memory-action` - Store/recall strategic decisions

## Skills (6)

| Skill | Purpose |
|-------|---------|
| **notion-spec-to-implementation** | Convert Notion specs to tasks |
| **notion-research-documentation** | Create research reports in Notion |
| **notion-knowledge-capture** | Document conversations in Notion |
| **notion-meeting-intelligence** | Prepare meeting materials from Notion |
| **prompt-engineering-patterns** | Advanced LLM prompt techniques |
| **swarm-orchestration** | Multi-agent coordination |
| **swarm-advanced** | Advanced orchestration patterns |

## Hooks (3)

| Hook | Event | Purpose |
|------|-------|---------|
| **memory-session-start.sh** | Session start | Load strategic context |
| **memory-session-stop.sh** | Session end | Save decisions and context |
| **memory-subagent-stop.sh** | Subagent complete | Capture agent learnings |

## Plugins (0)

Product Strategy primarily uses commands and agents rather than dedicated plugins.

## Common Workflows

1. **Quarterly Planning**: brainstorm → roadmap → create issues
2. **Feature PRD**: vision → requirements → section-spec → export
3. **Market Research**: market-researcher agent → research-documentation skill
4. **Sprint Planning**: plan-sprints → create issues

## Related Departments

- **Design**: Hands off specs for UX/UI design
- **Engineering**: Provides requirements and GitHub issues
- **QA**: Defines acceptance criteria for testing
- **Operations**: Identifies infrastructure needs

---

→ See [Full Agents Inventory](./inventory-agents.md#strategy-agents) for detailed agent specs
→ See [Full Commands Inventory](./inventory-commands.md) for command details
→ See [Strategy Framework](./strategy-framework.md) for methodologies

**Last Updated**: 2026-01-15

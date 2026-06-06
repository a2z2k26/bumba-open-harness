# Operations Department - Quick Reference

Quick reference for Operations features in Claude Code.

## Overview

Operations handles infrastructure, deployment, monitoring, and operational excellence.

## Agents (7)

| Agent | Purpose |
|-------|---------|
| **ops-chief** | Infrastructure and operations leadership |
| **ops-cloud-architect** | Multi-cloud architecture (AWS/Azure/GCP) |
| **ops-kubernetes-engineer** | Container orchestration and K8s |
| **ops-database-admin** | Database administration and data integrity |
| **ops-network-engineer** | Network design and security |
| **ops-monitoring-specialist** | Observability and alerting |
| **ops-sre-engineer** | Site reliability and SLO/SLI |
| **ops-devops-specialist** | CI/CD and deployment automation |

## Commands (22)

### E2B Sandbox Management
- `/e2b:management:status` - Show sandbox status
- `/e2b:management:start` - Start new sandbox
- `/e2b:management:cleanup` - Remove stale sandboxes
- `/e2b:management:exec` - Execute commands in sandbox
- `/e2b:management:debug` - Debug sandbox issues
- `/e2b:management:snapshot` - Create sandbox snapshot
- `/e2b:management:restore` - Restore from snapshot
- `/e2b:management:test` - Test sandbox connectivity

### E2B Cost & Optimization
- `/e2b:cost-report` - Generate cost report
- `/e2b:optimize` - Optimize resource usage

### E2B Orchestration
- `/e2b:orchestration:status` - View orchestration status
- `/e2b:orchestration:events` - View event log
- `/e2b:orchestration:pause-all` - Pause all orchestration
- `/e2b:orchestration:resume-all` - Resume all orchestration
- `/e2b:orchestration:pause-feature` - Pause specific feature
- `/e2b:orchestration:resume-feature` - Resume specific feature
- `/e2b:orchestration:set-strategy` - Set strategy (aggressive/balanced/conservative)

### E2B Templates
- `/e2b:templates:list-templates` - List available templates
- `/e2b:templates:create-template` - Create new template

### Project Management
- `/project:init` - Initialize project structure
- `/project:status` - View project metrics
- `/project:config` - Configure project settings

### GitHub (Deployment)
- `/gh:merge-pr` - Merge and deploy

## Skills (4)

| Skill | Purpose |
|-------|---------|
| **distributed-tracing** | Jaeger/Tempo for microservices |
| **github-actions-templates** | CI/CD automation |
| **git-advanced-workflows** | Complex git operations |
| **sql-optimization-patterns** | Database performance |

## Hooks (1)

| Hook | Event | Purpose |
|------|-------|---------|
| **on-project-init-complete.js** | Project init | Infrastructure setup |

## Plugins (1)

| Plugin | Purpose |
|--------|---------|
| **e2b-design-orchestrator** | E2B sandbox orchestration for design |

## Common Workflows

1. **Infrastructure Setup**: project:init → cloud-architect agent → implementation
2. **Deployment**: gh:merge-pr → CI/CD triggers → monitoring
3. **Cost Management**: e2b:cost-report → e2b:optimize → cleanup stale resources
4. **Monitoring**: monitoring-specialist agent → distributed-tracing → alerting setup
5. **E2B Orchestration**: set-strategy → start sandboxes → monitor → cleanup

## Related Departments

- **Product Strategy**: Receives infrastructure requirements
- **Engineering**: Collaborates on CI/CD and deployment
- **QA**: Provides test environments
- **Design**: Manages E2B sandboxes for design exploration

---

→ See [Full Agents Inventory](./inventory-agents.md#ops-agents) for detailed agent specs
→ See [Full Commands Inventory](./inventory-commands.md) for command details
→ See [Operations Framework](./operations-framework.md) for methodologies

**Last Updated**: 2026-01-15

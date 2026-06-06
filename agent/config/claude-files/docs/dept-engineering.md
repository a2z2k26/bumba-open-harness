# Engineering Department - Quick Reference

Quick reference for Engineering features in Claude Code.

## Overview

Engineering handles backend/frontend development, API design, code quality, and infrastructure.

## Agents (7)

| Agent | Purpose |
|-------|---------|
| **engineering-chief** | Technical architecture and leadership |
| **engineering-backend-architect** | Backend system design (multi-language) |
| **engineering-frontend-developer** | Frontend implementation (React/Vue/Angular/Svelte) |
| **engineering-api-engineer** | API design and documentation |
| **engineering-code-reviewer** | Code quality and security review |
| **engineering-database-specialist** | Database design and optimization |
| **engineering-devops-engineer** | CI/CD and deployment automation |
| **engineering-performance-engineer** | Performance optimization |

## Commands (12)

### Code Execution
- `/code:execute` - Execute implementation plan

### Git Workflows
- `/git:feature-branch` - Create feature branch
- `/git:hotfix-branch` - Create hotfix branch
- `/git:sync-branch` - Sync with main/master

### GitHub Workflows
- `/gh:create-pr` - Create PR with AI description
- `/gh:review-pr` - AI-powered code review
- `/gh:address-feedback` - Address PR comments
- `/gh:merge-pr` - Merge and cleanup

### Testing
- `/testing:all` - Run complete test suite
- `/testing:feature` - Test specific feature
- `/testing:matrix` - Cross-environment testing

### E2B Management
- Various `/e2b:management:*` commands for sandboxes

## Skills (18)

### Architecture & Patterns
| Skill | Purpose |
|-------|---------|
| **architecture-patterns** | Clean/Hexagonal/DDD patterns |
| **async-python-patterns** | Python asyncio and concurrency |
| **error-handling-patterns** | Production error handling |
| **debugging-strategies** | Systematic debugging techniques |
| **code-review-excellence** | Effective code review practices |
| **sql-optimization-patterns** | Query optimization and indexing |
| **distributed-tracing** | Jaeger/Tempo distributed tracing |
| **git-advanced-workflows** | Advanced Git operations |
| **nodejs-backend-patterns** | Node.js/Express/Fastify patterns |

### Frameworks & Tools
| Skill | Purpose |
|-------|---------|
| **fastapi-templates** | FastAPI project templates |
| **github-actions-templates** | CI/CD workflow templates |
| **langchain-architecture** | LangChain application design |
| **react-modernization** | React upgrade and hooks migration |
| **python-packaging** | Python package distribution |
| **uv-package-manager** | Fast Python dependency management |
| **stripe-integration** | Stripe payment processing |
| **rag-implementation** | RAG systems with vector databases |
| **webapp-testing** | Playwright web testing |
| **prompt-engineering-patterns** | LLM prompt optimization |

## Hooks (1)

| Hook | Event | Purpose |
|------|-------|---------|
| **on-project-init-complete.js** | Project init done | Setup structure |

## Plugins (0)

Engineering primarily uses skills and commands rather than dedicated plugins.

## Common Workflows

1. **Feature Development**: plan-feature → code:execute → testing:feature → gh:create-pr
2. **Code Review**: gh:review-pr → address-feedback → merge-pr
3. **API Development**: backend-architect agent → api-engineer agent → testing
4. **Full-Stack**: design-layout-to-jsx → backend implementation → integration → testing

## Related Departments

- **Product Strategy**: Receives requirements and GitHub issues
- **Design**: Receives design code for implementation
- **QA**: Collaborates on testing strategies
- **Operations**: Coordinates on deployment and infrastructure

---

→ See [Full Agents Inventory](./inventory-agents.md#engineering-agents) for detailed agent specs
→ See [Full Commands Inventory](./inventory-commands.md) for command details
→ See [Engineering Framework](./engineering-framework.md) for methodologies

**Last Updated**: 2026-01-15

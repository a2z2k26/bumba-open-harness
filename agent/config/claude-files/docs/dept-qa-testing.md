# QA/Testing Department - Quick Reference

Quick reference for QA and Testing features in Claude Code.

## Overview

QA/Testing handles test strategy, automation, performance, accessibility, security, and quality assurance.

## Agents (6)

| Agent | Purpose |
|-------|---------|
| **qa-chief** | Quality strategy and testing leadership |
| **qa-engineer** | Test planning and comprehensive testing |
| **qa-automation-engineer** | Test automation frameworks and CI/CD |
| **qa-performance-tester** | Load testing and performance benchmarking |
| **qa-accessibility-tester** | WCAG compliance and assistive technology |
| **qa-security-auditor** | Security audits and penetration testing |
| **qa-api-tester** | API contract and integration testing |
| **qa-mobile-tester** | iOS and Android testing |

## Commands (5)

### Testing
- `/testing:all` - Run complete test suite (unit/integration/E2E/performance)
- `/testing:feature` - Test specific feature comprehensively
- `/testing:matrix` - Run tests across multiple environments/configurations

### GitHub (Quality Gates)
- `/gh:review-pr` - AI-powered code review (includes QA perspective)
- `/gh:address-feedback` - Address review feedback systematically

## Skills (2)

| Skill | Purpose |
|-------|---------|
| **webapp-testing** | Playwright web testing toolkit |
| **github-actions-templates** | CI/CD test integration |

## Hooks (1)

| Hook | Event | Purpose |
|------|-------|---------|
| **on-project-init-complete.js** | Project init | Test framework setup |

## Plugins (0)

QA/Testing primarily uses commands and agents rather than dedicated plugins.

## Common Workflows

1. **Test Strategy**: qa-engineer agent → test plan → automation setup
2. **Automated Testing**: automation-engineer agent → testing:all → CI/CD integration
3. **Performance Testing**: performance-tester agent → testing:matrix → optimization
4. **Accessibility Testing**: accessibility-tester agent → WCAG validation → fixes
5. **Security Testing**: security-auditor agent → penetration test → vulnerability fixes
6. **API Testing**: api-tester agent → contract validation → integration tests
7. **Code Review**: gh:review-pr → qa-engineer feedback → address-feedback

## Test Types Supported

| Type | Agent | Command | Focus |
|------|-------|---------|-------|
| **Unit** | qa-automation-engineer | /testing:all | Individual components |
| **Integration** | qa-automation-engineer | /testing:feature | Component interaction |
| **E2E** | qa-automation-engineer | webapp-testing skill | Full user flows |
| **Performance** | qa-performance-tester | /testing:matrix | Load and stress |
| **Accessibility** | qa-accessibility-tester | Manual + automated | WCAG AA/AAA |
| **Security** | qa-security-auditor | /gh:review-pr | Vulnerabilities |
| **API** | qa-api-tester | /testing:feature | API contracts |
| **Mobile** | qa-mobile-tester | /testing:matrix | iOS/Android |

## Quality Gates

1. **Pre-commit**: Code review (qa-code-reviewer feedback)
2. **Pre-merge**: All tests passing (/testing:all)
3. **Pre-deploy**: Performance validation (/testing:matrix)
4. **Post-deploy**: Monitoring and smoke tests

## Related Departments

- **Product Strategy**: Validates acceptance criteria
- **Design**: Tests accessibility and visual regression
- **Engineering**: Collaborates on test automation
- **Operations**: Coordinates on test environments

---

→ See [Full Agents Inventory](./inventory-agents.md#qa-agents) for detailed agent specs
→ See [Full Commands Inventory](./inventory-commands.md) for command details
→ See [QA Testing Framework](./qa-testing-framework.md) for methodologies

**Last Updated**: 2026-01-15

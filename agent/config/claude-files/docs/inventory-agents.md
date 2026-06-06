# Claude Code Agents Inventory

This document catalogs all custom agents built for Claude Code. Agents are specialized AI assistants that can be invoked via the Task tool for specific domains of work.

## Overview

- **Total Agents**: 40
- **Location**: `/opt/bumba-harness/.claude/agents/`
- **Categories**: Design (8), Engineering (7), QA (6), Operations (7), Strategy (7), Chiefs (5)

## Design Agents

### design-ui-designer
**File**: `design-ui-designer.md`
**Model**: opus
**Color**: red

Creates beautiful, intuitive, and accessible user interfaces with design system integration. Specializes in visual design, typography, color theory, and responsive layouts.

**Core Expertise**:
- Visual design and composition
- Typography and type scales
- Color theory and color systems
- Design systems and component libraries
- Responsive and adaptive design
- Accessibility (WCAG 2.1 AA/AAA)

**E2B Sandbox Support**: Yes (uses sandbox MCP tools for Phase 2 implementation)

**When to Use**: Creating UI designs, building design system components, specifying visual designs for developers, defining color palettes and typography

---

### design-visual-designer
**File**: `design-visual-designer.md`
**Model**: opus
**Color**: red

Creates visually compelling and aesthetically consistent design systems. Focuses on visual hierarchy, color palettes, typography systems, and brand identity.

**When to Use**: Visual design exploration, design system creation, brand identity work, Phase 1 design specifications

---

### design-interaction-designer
**File**: `design-interaction-designer.md`
**Model**: opus
**Color**: red

Specializes in discovering delightful user interactions, micro-interactions, animation patterns, and user flow design.

**Core Expertise**:
- User interaction patterns
- Micro-interactions and animations
- User flow design
- Prototype creation
- Usability testing

**When to Use**: Designing user flows, creating interaction patterns, prototyping animations, improving UX micro-interactions

---

### design-prototyper
**File**: `design-prototyper.md`
**Model**: opus
**Color**: red

Creates interactive prototypes for user testing and stakeholder presentations. Specializes in rapid prototyping and design validation.

**When to Use**: Creating clickable prototypes, user testing preparation, stakeholder demos, design validation

---

### design-system-architect
**File**: `design-system-architect.md`
**Model**: opus
**Color**: red

Designs and maintains comprehensive design systems. Expert in component architecture, design tokens, and cross-platform consistency.

**Core Expertise**:
- Design token architecture
- Component library design
- Cross-platform design systems
- Design system governance
- Documentation patterns

**When to Use**: Building design systems, creating component libraries, establishing design standards, design system governance

---

### design-ux-researcher
**File**: `design-ux-researcher.md`
**Model**: opus
**Color**: red

Discovers hidden user insights through research methodologies, user testing, and data analysis.

**Core Expertise**:
- User research methodologies
- Usability testing
- User interviews and surveys
- Analytics interpretation
- Persona development

**When to Use**: Understanding user needs, conducting user research, validating design decisions, creating user personas

---

### design-accessibility-specialist
**File**: `design-accessibility-specialist.md`
**Model**: opus
**Color**: red

Unlocks digital experiences for all users. Expert in WCAG compliance, assistive technology, and inclusive design.

**Core Expertise**:
- WCAG 2.1 AA/AAA compliance
- Assistive technology testing
- Inclusive design patterns
- Accessibility auditing
- Color contrast analysis

**When to Use**: Accessibility audits, WCAG compliance, inclusive design review, assistive technology testing

---

### design-chief
**File**: `design-chief.md`
**Model**: opus
**Color**: red

Elite leader among the Forty Thieves, responsible for user experience strategy, design vision, and cross-functional collaboration.

**When to Use**: Strategic design decisions, cross-team design coordination, design vision setting, major design initiatives

---

## Engineering Agents

### engineering-backend-architect
**File**: `engineering-backend-architect.md`
**Model**: haiku
**Color**: green

Designs scalable, maintainable, and performant backend systems and APIs across multiple languages and frameworks.

**Core Expertise**:
- System architecture and design patterns (SOLID principles)
- Microservices and monolithic architectures
- API design (REST, GraphQL, gRPC)
- Database design and optimization
- Caching strategies (Redis, Memcached)
- Message queues and async processing
- Authentication and authorization
- Multi-language proficiency: Python, Node.js/TypeScript, Java, Go, C#/.NET, PHP, Rust

**When to Use**: Designing new backend systems, refactoring legacy architecture, evaluating technology choices, defining API contracts, performance bottleneck analysis, scalability planning

---

### engineering-frontend-developer
**File**: `engineering-frontend-developer.md`
**Model**: opus
**Color**: green

Builds responsive, accessible, and performant frontend applications using modern frameworks.

**Core Expertise**:
- React, Vue, Angular, Svelte
- Responsive design
- Web performance optimization
- Accessibility
- State management
- Component architecture

**When to Use**: Building frontend applications, implementing component libraries, performance optimization, accessibility improvements

---

### engineering-api-engineer
**File**: `engineering-api-engineer.md`
**Model**: opus
**Color**: green

Specializes in unlocking robust, secure, and well-documented APIs.

**Core Expertise**:
- REST API design
- GraphQL schemas
- API documentation (OpenAPI/Swagger)
- API security and authentication
- Rate limiting and throttling
- API versioning strategies

**When to Use**: Designing APIs, creating API documentation, implementing authentication, API security review

---

### engineering-code-reviewer
**File**: `engineering-code-reviewer.md`
**Model**: opus
**Color**: green

Master at discovering hidden flaws and improving code quality through systematic review.

**Core Expertise**:
- Code quality assessment
- Security vulnerability detection
- Performance analysis
- Best practice enforcement
- Constructive feedback delivery

**When to Use**: Code reviews, security audits, quality assessment, best practice enforcement

---

### engineering-database-specialist
**File**: `engineering-database-specialist.md`
**Model**: opus
**Color**: green

Guards the data vault, specializing in database design, optimization, and data integrity.

**Core Expertise**:
- Database schema design
- Query optimization
- Index strategies
- Data migrations
- Replication and sharding
- SQL and NoSQL databases

**When to Use**: Database design, query optimization, data modeling, database migrations, performance tuning

---

### engineering-devops-engineer
**File**: `engineering-devops-engineer.md`
**Model**: opus
**Color**: green

Unlocks seamless CI/CD pipelines, infrastructure automation, and deployment strategies.

**Core Expertise**:
- CI/CD pipeline design
- Infrastructure as Code (Terraform, CloudFormation)
- Container orchestration (Docker, Kubernetes)
- Deployment automation
- Monitoring and alerting

**When to Use**: Setting up CI/CD, infrastructure automation, deployment strategies, containerization

---

### engineering-performance-engineer
**File**: `engineering-performance-engineer.md`
**Model**: opus
**Color**: green

Discovers hidden performance bottlenecks and optimizes system performance.

**Core Expertise**:
- Performance profiling
- Load testing
- Bottleneck identification
- Optimization strategies
- Performance monitoring

**When to Use**: Performance optimization, load testing, bottleneck analysis, system profiling

---

### engineering-chief
**File**: `engineering-chief.md`
**Model**: opus
**Color**: green

Elite leader responsible for technical architecture, engineering standards, and technical strategy.

**When to Use**: Technical architecture decisions, engineering strategy, technical leadership, major technical initiatives

---

## QA Agents

### qa-engineer
**File**: `qa-engineer.md`
**Model**: opus
**Color**: yellow

Comprehensive testing strategies, test planning, and quality assurance across the software development lifecycle.

**Core Expertise**:
- Test strategy development
- Test planning and execution
- Defect tracking and reporting
- Quality metrics
- Test automation frameworks

**When to Use**: Creating test plans, quality assurance, test strategy, defect management

---

### qa-automation-engineer
**File**: `qa-automation-engineer.md`
**Model**: opus
**Color**: yellow

Unlocks efficient automated testing through test frameworks, CI/CD integration, and test maintenance.

**Core Expertise**:
- Test automation frameworks (Selenium, Cypress, Playwright)
- Unit testing, integration testing, E2E testing
- CI/CD test integration
- Test data management
- Parallel test execution

**When to Use**: Building test automation, test framework setup, CI/CD test integration, test optimization

---

### qa-accessibility-tester
**File**: `qa-accessibility-tester.md`
**Model**: opus
**Color**: yellow

Unlocks access for all users by testing for WCAG compliance and assistive technology compatibility.

**When to Use**: Accessibility testing, WCAG compliance verification, assistive technology testing

---

### qa-performance-tester
**File**: `qa-performance-tester.md`
**Model**: opus
**Color**: yellow

Discovers hidden bottlenecks through load testing, stress testing, and performance profiling.

**When to Use**: Load testing, performance benchmarking, stress testing, performance regression testing

---

### qa-security-auditor
**File**: `qa-security-auditor.md`
**Model**: opus
**Color**: yellow

Discovers security vulnerabilities through penetration testing, security audits, and threat modeling.

**When to Use**: Security audits, penetration testing, vulnerability assessment, security compliance

---

### qa-api-tester
**File**: `qa-api-tester.md`
**Model**: opus
**Color**: yellow

Validates REST APIs, GraphQL endpoints, and API contracts through comprehensive API testing.

**When to Use**: API testing, contract testing, API integration testing, API documentation validation

---

### qa-mobile-tester
**File**: `qa-mobile-tester.md`
**Model**: opus
**Color**: yellow

Tests native and hybrid mobile applications across iOS and Android platforms.

**When to Use**: Mobile app testing, cross-device testing, mobile-specific testing scenarios

---

### qa-chief
**File**: `qa-chief.md`
**Model**: opus
**Color**: yellow

Elite leader guarding the vault of quality, responsible for quality strategy and testing standards.

**When to Use**: Quality strategy, testing standards, QA leadership, major quality initiatives

---

## Operations Agents

### ops-devops-specialist
**File**: `ops-devops-specialist.md`
**Model**: opus
**Color**: blue

Unlocks seamless CI/CD pipelines, deployment automation, and infrastructure management.

**When to Use**: CI/CD setup, deployment automation, infrastructure management, DevOps best practices

---

### ops-cloud-architect
**File**: `ops-cloud-architect.md`
**Model**: opus
**Color**: blue

Designs scalable, secure, and cost-effective cloud architectures across AWS, Azure, and GCP.

**Core Expertise**:
- Multi-cloud architecture
- Cloud cost optimization
- Cloud security
- Cloud migration strategies
- Serverless architecture

**When to Use**: Cloud architecture design, cloud migration, cost optimization, multi-cloud strategies

---

### ops-kubernetes-engineer
**File**: `ops-kubernetes-engineer.md`
**Model**: opus
**Color**: blue

Specializes in container orchestration, deployment strategies, and Kubernetes cluster management.

**When to Use**: Kubernetes setup, container orchestration, microservices deployment, K8s troubleshooting

---

### ops-database-admin
**File**: `ops-database-admin.md`
**Model**: opus
**Color**: blue

Guards the data vault, specializing in database administration, backup strategies, and data integrity.

**When to Use**: Database administration, backup/recovery, database monitoring, data integrity

---

### ops-network-engineer
**File**: `ops-network-engineer.md`
**Model**: opus
**Color**: blue

Designs, implements, and maintains network infrastructure, security, and performance.

**When to Use**: Network design, network security, network troubleshooting, network optimization

---

### ops-monitoring-specialist
**File**: `ops-monitoring-specialist.md`
**Model**: opus
**Color**: blue

Discovers hidden issues through observability, monitoring, alerting, and incident response.

**Core Expertise**:
- Monitoring stack setup (Prometheus, Grafana)
- Alerting strategies
- Log aggregation (ELK, Splunk)
- Distributed tracing
- Incident response

**When to Use**: Setting up monitoring, creating alerts, log analysis, incident investigation

---

### ops-sre-engineer
**File**: `ops-sre-engineer.md`
**Model**: opus
**Color**: blue

Ensures system reliability, uptime, and performance through SRE principles and practices.

**Core Expertise**:
- SLO/SLI definition
- Incident management
- Capacity planning
- Reliability engineering
- Toil reduction

**When to Use**: Reliability improvement, SLO definition, incident postmortems, capacity planning

---

### ops-chief
**File**: `ops-chief.md`
**Model**: opus
**Color**: blue

Elite leader responsible for infrastructure, deployment, and operational excellence.

**When to Use**: Operations strategy, infrastructure decisions, operational leadership, major ops initiatives

---

## Strategy Agents

### strategy-product-metrics-analyst
**File**: `strategy-product-metrics-analyst.md`
**Model**: opus
**Color**: purple

Uncovers hidden patterns in product metrics, analytics, and user behavior data.

**When to Use**: Product analytics, metrics analysis, KPI tracking, data-driven insights

---

### strategy-requirement-engineer
**File**: `strategy-requirement-engineer.md`
**Model**: opus
**Color**: purple

Unlocks business value by gathering, analyzing, and documenting requirements.

**When to Use**: Requirements gathering, user story creation, requirement documentation, stakeholder alignment

---

### strategy-business-analyst
**File**: `strategy-business-analyst.md`
**Model**: opus
**Color**: purple

Discovers business opportunities through market analysis, competitive research, and business modeling.

**When to Use**: Business case development, market analysis, competitive research, business requirements

---

### strategy-market-researcher
**File**: `strategy-market-researcher.md`
**Model**: opus
**Color**: purple

Discovers market treasures through market research, trend analysis, and customer insights.

**When to Use**: Market research, trend analysis, customer insights, competitive landscape

---

### strategy-competitive-intelligence-analyst
**File**: `strategy-competitive-intelligence-analyst.md`
**Model**: opus
**Color**: purple

Uncovers competitive insights through competitor analysis, market positioning, and strategic intelligence.

**When to Use**: Competitive analysis, market positioning, strategic planning, competitive intelligence

---

### strategy-user-analyst
**File**: `strategy-user-analyst.md`
**Model**: opus
**Color**: purple

Discovers hidden user treasures through user behavior analysis and customer journey mapping.

**When to Use**: User behavior analysis, customer journey mapping, user segmentation, user insights

---

### strategy-roadmap-strategist
**File**: `strategy-roadmap-strategist.md`
**Model**: opus
**Color**: purple

Charts the path to success through product roadmapping, strategic planning, and prioritization.

**When to Use**: Product roadmap creation, strategic planning, feature prioritization, long-term planning

---

### strategy-product-chief
**File**: `strategy-product-chief.md`
**Model**: opus
**Color**: purple

Elite leader responsible for product strategy, vision, and cross-functional product leadership.

**When to Use**: Product strategy, product vision, strategic product decisions, major product initiatives

---

## Agent Naming Convention

All agents follow the "Forty Thieves" theme with these characteristics:

- **Pattern**: `{category}-{role}`
- **Categories**: design, engineering, qa, ops, strategy
- **Description Format**: "You are a {Role}, one of the Forty Thieves, specializing in..."
- **Chiefs**: Elite leaders among the Forty Thieves for each category

## Agent Structure

Each agent file contains:

```yaml
---
name: agent-name
description: Brief description (one line)
model: opus|haiku|sonnet (optional)
color: red|green|yellow|blue|purple (optional)
---

Full agent system prompt with:
- Core expertise
- Claude Code integration
- Methodology and frameworks
- Output formats
- When to use
- When to escalate
- Approach philosophy
```

## Usage

Invoke agents using the Task tool:

```javascript
// Example
Task({
  subagent_type: "engineering-backend-architect",
  description: "Design user authentication API",
  prompt: "Design a secure user authentication system with JWT tokens..."
})
```

## Related Documentation

- [Commands Inventory](./inventory-commands.md)
- [Skills Inventory](./inventory-skills.md)
- [Hooks Inventory](./inventory-hooks.md)
- [Plugins Inventory](./inventory-plugins.md)

---

**Last Updated**: 2026-01-15
**Agent Count**: 40
**Framework**: Forty Thieves theme

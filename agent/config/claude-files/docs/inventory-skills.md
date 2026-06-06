# Claude Code Skills Inventory

This document catalogs all custom skills built for Claude Code. Skills are reusable knowledge modules that can be invoked to provide specialized expertise and workflows.

## Overview

- **Total Skills**: 46 (directories) + 5 standalone files
- **Location**: `/opt/bumba-harness/.claude/skills/`
- **Categories**: Plugin Development (4), Design (12), Development Patterns (10), Testing (1), Notion Integration (4), Framework Specific (8), Memory (2), Other (5)

---

## Plugin Development Skills

### agent-identifier
**Directory**: `agent-identifier/`

Guidance on creating agents for Claude Code plugins. Covers agent structure, system prompts, triggering conditions, and agent development best practices.

**When to Use**: Creating agents, understanding agent frontmatter, agent examples, agent tools, agent colors, autonomous agents

---

### command-development
**Directory**: `command-development/`

Complete guide for creating slash commands including structure, YAML frontmatter, dynamic arguments, bash execution, user interaction patterns, and command development best practices.

**When to Use**: Creating slash commands, adding commands, defining command arguments, using command frontmatter, organizing commands, interactive commands

---

### command-name (Plugin Architecture)
**Directory**: `command-name/`

Understanding plugin structure, scaffolding plugins, organizing plugin components, setting up plugin.json, using ${CLAUDE_PLUGIN_ROOT}, adding commands/agents/skills/hooks, configuring auto-discovery.

**When to Use**: Creating plugins, scaffolding plugins, understanding plugin structure, organizing plugin components, plugin architecture best practices

---

### hook-development
**Directory**: `hook-development/`

Comprehensive guidance for creating and implementing Claude Code plugin hooks. Covers PreToolUse, PostToolUse, Stop hooks, prompt-based hooks API, and event-driven automation.

**When to Use**: Creating hooks, implementing event-driven automation, validating tool use, blocking dangerous commands, using ${CLAUDE_PLUGIN_ROOT}

**Hook Events**: PreToolUse, PostToolUse, Stop, SubagentStop, SessionStart, SessionEnd, UserPromptSubmit, PreCompact, Notification

---

### rule-identifier
**Directory**: `rule-identifier/`

Creating hookify rules, writing hook rules, configuring hookify, understanding hookify rule syntax and patterns.

**When to Use**: Creating hookify rules, configuring hookify, understanding hook rule syntax

---

### configured-agent
**Directory**: `configured-agent/`

Using .local.md files for plugin-specific configuration with YAML frontmatter. Covers plugin settings, storing plugin configuration, user-configurable plugins, plugin state files.

**When to Use**: Plugin settings, storing plugin configuration, making plugins configurable per-project, reading YAML frontmatter

---

### mcp-integration
**Directory**: `mcp-integration/`

Comprehensive guide for integrating Model Context Protocol (MCP) servers into Claude Code plugins. Covers .mcp.json configuration, MCP server types (SSE, stdio, HTTP, WebSocket), and external service integration.

**When to Use**: Adding MCP server, integrating MCP, configuring MCP in plugin, using .mcp.json, setting up Model Context Protocol, connecting external services

---

## Design Skills

### design-explore-ui
**File**: `design-explore-ui.md`

Generate four divergent UI design directions in parallel E2B sandboxes using design-ui-template. Creates distinctive visual designs across conservative, refined, expressive, and experimental directions with Design Bridge system integration.

**Directions**:
1. **Conservative**: Standard patterns, WCAG AA, semantic HTML
2. **Refined**: Polished micro-interactions, elevated but predictable
3. **Expressive**: Bold typography, dynamic spacing, strong personality
4. **Experimental**: Boundary-pushing layouts, dramatic effects

**E2B Template**: design-ui-template (7k5wtd8ecoxz9bpvwa3l)

**Agents Used**: design-visual-designer (Phase 1), design-ui-designer (Phase 2)

---

### design-explore-ux
**File**: `design-explore-ux.md`

Similar to design-explore-ui but focuses on UX patterns, user flows, and interaction design rather than visual aesthetics.

**E2B Template**: design-ux-template

---

### design (Directory)
**Directory**: `design/`

Core design system skills and patterns.

---

### design-bridge-shared
**Directory**: `design-bridge-shared/`

Shared utilities and patterns for Design Bridge integration.

---

### design-figma-sketch
**Directory**: `design-figma-sketch/`

Bidirectional chat with Figma plugin for design creation.

**When to Use**: Creating designs in Figma via Claude Code, syncing design changes

---

### bumba-design-director-frontend
**Directory**: `bumba-design-director-frontend/`

Create distinctive, production-grade frontend interfaces with high design quality. Generates creative, polished code that avoids generic AI aesthetics.

**When to Use**: Building web components, pages, applications with high design standards

---

### Extract Skills

#### extract-design.md
**File**: `extract-design.md`

Extract design components and patterns from existing designs.

---

#### extract-figma-mcp.md
**File**: `extract-figma-mcp.md`

Extract components from Figma using MCP integration.

---

#### extract-nlp-prompt.md
**File**: `extract-nlp-prompt.md`

Generate design components from natural language descriptions.

---

#### extract-shadcn.md
**File**: `extract-shadcn.md`

Extract and integrate ShadCN components into Design Bridge.

---

## Framework Transformation Skills

### transform-react
**Directory**: `transform-react/`

Transform design tokens into React/TypeScript with styled-components, theme provider, and automatic batch processing.

---

### transform-vue
**Directory**: `transform-vue/`

Transform design tokens into Vue 3 composables with Composition API and scoped styles.

---

### transform-angular
**Directory**: `transform-angular/`

Transform design tokens into Angular services with injectable theme and SCSS utilities.

---

### transform-svelte
**Directory**: `transform-svelte/`

Transform design tokens into Svelte stores with writable theme state and actions.

---

### transform-react-native
**Directory**: `transform-react-native/`

Transform design tokens into React Native StyleSheet definitions and theme provider.

---

### transform-flutter
**Directory**: `transform-flutter/`

Transform design tokens into Flutter/Dart ThemeData classes and color schemes.

---

### transform-jetpack-compose
**Directory**: `transform-jetpack-compose/`

Transform design tokens into Kotlin/Jetpack Compose Material 3 theme composables.

---

### transform-swiftui
**Directory**: `transform-swiftui/`

Transform design tokens into SwiftUI Color extensions and view modifiers.

---

## Development Pattern Skills

### architecture-patterns
**Directory**: `architecture-patterns/`

Proven backend architecture patterns including Clean Architecture, Hexagonal Architecture, and Domain-Driven Design. For architecting complex backend systems or refactoring for maintainability.

**Patterns**: Clean Architecture, Hexagonal, DDD, CQRS, Event Sourcing

---

### async-python-patterns
**Directory**: `async-python-patterns/`

Master Python asyncio, concurrent programming, and async/await patterns for high-performance applications.

**When to Use**: Building async APIs, concurrent systems, I/O-bound applications requiring non-blocking operations

---

### error-handling-patterns
**Directory**: `error-handling-patterns/`

Error handling patterns across languages including exceptions, Result types, error propagation, and graceful degradation.

**When to Use**: Implementing error handling, designing APIs, improving application reliability

---

### prompt-engineering-patterns
**Directory**: `prompt-engineering-patterns/`

Advanced prompt engineering techniques to maximize LLM performance, reliability, and controllability in production.

**When to Use**: Optimizing prompts, improving LLM outputs, designing production prompt templates

---

### debugging-strategies
**Directory**: `debugging-strategies/`

Systematic debugging techniques, profiling tools, and root cause analysis to efficiently track down bugs.

**When to Use**: Investigating bugs, performance issues, unexpected behavior

---

### code-review-excellence
**Directory**: `code-review-excellence/`

Effective code review practices to provide constructive feedback, catch bugs early, and foster knowledge sharing.

**When to Use**: Reviewing pull requests, establishing review standards, mentoring developers

---

### sql-optimization-patterns
**Directory**: `sql-optimization-patterns/`

SQL query optimization, indexing strategies, and EXPLAIN analysis to improve database performance.

**When to Use**: Debugging slow queries, designing database schemas, optimizing application performance

---

### distributed-tracing
**Directory**: `distributed-tracing/`

Implement distributed tracing with Jaeger and Tempo to track requests across microservices.

**When to Use**: Debugging microservices, analyzing request flows, implementing observability

---

### git-advanced-workflows
**Directory**: `git-advanced-workflows/`

Advanced Git workflows including rebasing, cherry-picking, bisect, worktrees, and reflog.

**When to Use**: Managing complex Git histories, collaborating on feature branches, troubleshooting repository issues

---

### nodejs-backend-patterns
**Directory**: `nodejs-backend-patterns/`

Production-ready Node.js backend services with Express/Fastify, middleware patterns, error handling, authentication, database integration, and API design.

**When to Use**: Creating Node.js servers, REST APIs, GraphQL backends, microservices architectures

---

## Framework & Tool Skills

### fastapi-templates
**Directory**: `fastapi-templates/`

Create production-ready FastAPI projects with async patterns, dependency injection, and comprehensive error handling.

**When to Use**: Building FastAPI applications, setting up backend API projects

---

### github-actions-templates
**Directory**: `github-actions-templates/`

Production-ready GitHub Actions workflows for automated testing, building, and deploying applications.

**When to Use**: Setting up CI/CD with GitHub Actions, automating development workflows

---

### langchain-architecture
**Directory**: `langchain-architecture/`

Design LLM applications using LangChain framework with agents, memory, and tool integration patterns.

**When to Use**: Building LangChain applications, implementing AI agents, creating complex LLM workflows

---

### react-modernization
**Directory**: `react-modernization/`

Upgrade React applications to latest versions, migrate from class components to hooks, and adopt concurrent features.

**When to Use**: Modernizing React codebases, migrating to React Hooks, upgrading React versions

---

### python-packaging
**Directory**: `python-packaging/`

Create distributable Python packages with proper project structure, setup.py/pyproject.toml, and publishing to PyPI.

**When to Use**: Packaging Python libraries, creating CLI tools, distributing Python code

---

### uv-package-manager
**Directory**: `uv-package-manager/`

Master the uv package manager for fast Python dependency management, virtual environments, and modern Python project workflows.

**When to Use**: Setting up Python projects, managing dependencies, optimizing Python development workflows

---

### stripe-integration
**Directory**: `stripe-integration/`

Implement Stripe payment processing for robust, PCI-compliant payment flows including checkout, subscriptions, and webhooks.

**When to Use**: Integrating Stripe payments, building subscription systems, implementing secure checkout flows

---

### rag-implementation
**Directory**: `rag-implementation/`

Build Retrieval-Augmented Generation (RAG) systems for LLM applications with vector databases and semantic search.

**When to Use**: Implementing knowledge-grounded AI, building document Q&A systems, integrating LLMs with external knowledge

---

## Orchestration Skills

### swarm-orchestration
**Directory**: `swarm-orchestration/`

Orchestrate multi-agent swarms with agentic-flow for parallel task execution, dynamic topology, and intelligent coordination.

**When to Use**: Scaling beyond single agents, implementing complex workflows, building distributed AI systems

---

### swarm-advanced
**Directory**: `swarm-advanced/`

Advanced swarm orchestration patterns for research, development, testing, and complex distributed workflows.

**When to Use**: Complex multi-agent coordination, research workflows, advanced orchestration patterns

---

## Testing Skills

### webapp-testing
**Directory**: `webapp-testing/`

Toolkit for interacting with and testing local web applications using Playwright. Supports verifying frontend functionality, debugging UI behavior, capturing screenshots, and viewing browser logs.

**When to Use**: Testing web applications, debugging frontend, capturing UI state, end-to-end testing

---

## Notion Integration Skills

### notion-knowledge-capture
**Directory**: `notion-knowledge-capture/`

Transform conversations and discussions into structured documentation pages in Notion. Captures insights, decisions, and knowledge from chat context.

**When to Use**: Documenting conversations, capturing decisions, creating knowledge base entries

---

### notion-meeting-intelligence
**Directory**: `notion-meeting-intelligence/`

Prepare meeting materials by gathering context from Notion, enriching with Claude research, and creating both internal pre-read and external agenda saved to Notion.

**When to Use**: Meeting preparation, creating agendas, gathering meeting context

---

### notion-research-documentation
**Directory**: `notion-research-documentation/`

Search across Notion workspace, synthesize findings from multiple pages, and create comprehensive research documentation saved as new Notion pages.

**When to Use**: Conducting research, synthesizing information, creating research reports

---

### notion-spec-to-implementation
**Directory**: `notion-spec-to-implementation/`

Turn product or tech specs into concrete Notion tasks that Claude Code can implement. Breaks down spec pages into detailed implementation plans.

**When to Use**: Converting specs to tasks, creating implementation plans, breaking down requirements

---

## Memory Skills

### memory-agent-protocol.md
**File**: `memory-agent-protocol.md`

Protocol for agents to interact with the Bumba Memory system.

---

### memory-awareness.md
**File**: `memory-awareness.md`

Understanding how to work with Bumba Memory across sessions.

---

## Migration Skills

### claude-opus-4-5-migration
**Directory**: `claude-opus-4-5-migration/`

Migrate prompts and code from Claude Sonnet 4.0, Sonnet 4.5, or Opus 4.1 to Opus 4.5. Handles model string updates and prompt adjustments for known Opus 4.5 behavioral differences.

**When to Use**: Updating codebase to Opus 4.5, migrating prompts, updating API calls

**Note**: Does NOT migrate Haiku 4.5

---

## Meta Skills

### using-superpowers
**Directory**: `using-superpowers/`

Establishes mandatory workflows for finding and using skills. Includes using Skill tool before announcing usage, following brainstorming before coding, and creating TodoWrite todos for checklists.

**When to Use**: Starting any conversation, understanding Claude Code workflows

---

### design-bridge-skills-readme.md
**File**: `design-bridge-skills-readme.md`

Overview and usage guide for Design Bridge related skills.

---

## Skill Structure

Skills can be:

1. **Directory-based**: Contains multiple files with comprehensive documentation
2. **File-based**: Single markdown file with focused guidance

Directory-based skills typically contain:
```
skill-name/
├── README.md          # Main skill documentation
├── examples/          # Usage examples
├── templates/         # Code templates
└── reference/         # Reference materials
```

File-based skills use YAML frontmatter:
```yaml
---
name: skill-name
description: Brief description
license: Complete terms in LICENSE.txt
---

Skill content
```

## Skill Invocation

Skills are invoked using the Skill tool:

```javascript
// Invoke a skill
Skill({
  skill: "architecture-patterns"
})

// Invoke with arguments
Skill({
  skill: "rag-implementation",
  args: "vector-db=pinecone"
})
```

Or using slash commands:
```
/design-explore-ui
/stripe-integration
```

## Skill Categories

- **Plugin Development**: Tools for building Claude Code extensions
- **Design**: UI/UX design and Design Bridge integration
- **Development Patterns**: Software architecture and coding patterns
- **Framework Specific**: Technology-specific implementation guides
- **Testing**: Testing strategies and tools
- **Orchestration**: Multi-agent coordination
- **Notion Integration**: Notion workspace integration
- **Memory**: Memory system integration
- **Migration**: Upgrading between Claude models

## Related Documentation

- [Agents Inventory](./inventory-agents.md)
- [Commands Inventory](./inventory-commands.md)
- [Hooks Inventory](./inventory-hooks.md)
- [Plugins Inventory](./inventory-plugins.md)

---

**Last Updated**: 2026-01-15
**Skill Count**: 51 (46 directories + 5 standalone files)
**Categories**: 9

# Claude Code Commands Inventory

This document catalogs all custom commands built for Claude Code. Commands are slash commands that can be invoked directly by the user to trigger specific workflows.

## Overview

- **Total Commands**: 81
- **Location**: `/opt/bumba-harness/.claude/commands/`
- **Categories**: Design (25), GitHub Workflows (5), Git Workflows (3), E2B Management (18), Orchestration (8), Project Management (3), Testing (3), Code Execution (1), Memory (1), Voice (1), Workflows (1)

---

## Voice Commands

### /bumba
**File**: `bumba.md`

Start a voice conversation using the Bumba MCP server.

**Usage**: Simply type `/bumba` to initiate a voice conversation.

---

## Design Commands

### Design Initialization & Setup

#### /design-init
**File**: `design-init.md`
**Version**: Latest

Initialize the standardized Design Bridge folder structure with tokens, components, layouts, and Storybook configuration.

**Creates**:
- `.design/` directory structure
- Component registry
- Design tokens
- Layout specifications
- Storybook integration

---

#### /design-bridge
**File**: `design-bridge.md`

Control the Bumba Design server for Figma plugin connectivity (start, stop, status, restart).

**Operations**: start | stop | status | restart

---

### Design Exploration

#### /design-explore-ui
**File**: `design-explore-ui.md`
**Version**: 5.0.0

Generate four divergent UI design directions using specialized design agents in parallel E2B sandboxes.

**Workflow**:
1. Creates 4 E2B sandboxes (conservative, refined, expressive, experimental)
2. Spawns Phase 1 agents (design-visual-designer) for design specs
3. Spawns Phase 2 agents (design-ui-designer) for implementation
4. Auto-syncs results to git worktrees
5. Presents all 4 directions for user selection

**Output**: 4 git worktrees with complete implementations

---

#### /design-explore-ux
**File**: `design-explore-ux.md`

Generate four divergent UX design directions using specialized design agents in parallel E2B sandboxes.

**Similar workflow to design-explore-ui** but focuses on UX patterns and user flows.

---

### Layout Transformation

#### /design-layout-to-jsx
**File**: `design-layout-to-jsx.md`
**Version**: Latest

Transform Figma layouts to React/JSX components with proper component structure and styling.

---

#### /design-layout-to-vue
**File**: `design-layout-to-vue.md`

Transform Figma layouts to Vue 3 SFC with scoped styles, Composition API, and flexbox/grid layouts.

**Framework Integration**:
- Vue 3 Composition API
- Scoped styles
- Responsive design
- Component-based architecture

---

#### /design-layout-to-compose
**File**: `design-layout-to-compose.md`

Transform Figma layouts to Jetpack Compose with Column/Row, Arrangement.spacedBy, and Modifier chains.

**Target**: Android (Kotlin + Jetpack Compose)

---

#### /design-layout-to-flutter
**File**: `design-layout-to-flutter.md`

Transform Figma layouts to Flutter widgets with Column/Row, SizedBox spacing, and const constructors.

**Target**: Flutter (Dart)

---

#### /design-layout-to-swiftui
**File**: `design-layout-to-swiftui.md`

Transform Figma layouts to SwiftUI views with VStack/HStack, spacing, and modifiers.

**Target**: iOS (SwiftUI)

---

#### /design-layout-to-tailwind
**File**: `design-layout-to-tailwind.md`

Transform Figma layouts to Tailwind CSS with utility classes, mobile-first responsive design, and gap utilities.

**Target**: Web (Tailwind CSS)

---

#### /design-layout-to-html
**File**: `design-layout-to-html.md`

Transform Figma layouts to semantic HTML with CSS.

**Target**: Web (HTML + CSS)

---

### Design Token Transformation

#### /design-transform-react
**File**: `design-transform-react.md`

Transform design tokens and components into production-ready React code with automatic batch processing.

**Features**:
- Batch processing
- TypeScript support
- Styled-components integration
- Theme provider setup

---

#### /design-transform-vue
**File**: `design-transform-vue.md`

Transform design tokens into Vue 3 composables with Composition API and scoped styles.

---

#### /design-transform-angular
**File**: `design-transform-angular.md`

Transform design tokens into Angular services with injectable theme and SCSS utilities.

---

#### /design-transform-svelte
**File**: `design-transform-svelte.md`

Transform design tokens into Svelte stores with writable theme state and actions.

---

#### /design-transform-react-native
**File**: `design-transform-react-native.md`

Transform design tokens into React Native StyleSheet definitions and theme provider.

---

#### /design-transform-flutter
**File**: `design-transform-flutter.md`

Transform design tokens into Flutter/Dart ThemeData classes and color schemes.

---

#### /design-transform-jetpack-compose
**File**: `design-transform-jetpack-compose.md`

Transform design tokens into Kotlin/Jetpack Compose Material 3 theme composables.

---

#### /design-transform-swiftui
**File**: `design-transform-swiftui.md`

Transform design tokens into SwiftUI Color extensions and view modifiers.

---

#### /design-transform-web-components
**File**: `design-transform-web-components.md`

Transform design tokens into Custom Elements with Shadow DOM and CSS custom properties.

---

### Design Utilities

#### /design-layout-refine
**File**: `design-layout-refine.md`

Iteratively refine layout code using Ralph loops until 98%+ visual parity achieved.

**Process**: Uses visual comparison to iteratively improve layout implementation.

---

#### /design-generate-styles
**File**: `design-generate-styles.md`

Generate STYLES.md brand guide from design tokens and components.

---

#### /design-promote
**File**: `design-promote.md`

Promote staged components and layouts from staging to production source directory.

**Workflow**: staging → production with validation

---

#### /design-search
**File**: `design-search.md`

Search for design tokens, components, and layouts using natural language queries.

---

#### /design-nlp
**File**: `design-nlp.md`

Generate design components from natural language descriptions with creative interpretation.

---

#### /design-sync-monitor
**File**: `design-sync-monitor.md`

Monitor design changes from Figma and automatically update registries.

**Features**: Watches for Figma changes and syncs to Design Bridge

---

## Design Director Commands

Design Director is a comprehensive product specification system.

### /design-director:init
**File**: `design-director/design-director-init.md`

Initialize Bumba Design Director for product planning specifications.

---

### /design-director:run
**File**: `design-director/design-director-run.md`

Complete guided workflow for creating product specifications from vision to export.

**Full Workflow**: Vision → Roadmap → Data Model → Sections → Export

---

### /design-director:vision
**File**: `design-director/design-director-vision.md`

Define product vision, problems, and key features.

---

### /design-director:roadmap
**File**: `design-director/design-director-roadmap.md`

Break product into 3-5 development sections with dependencies and milestones.

---

### /design-director:data-model
**File**: `design-director/design-director-data-model.md`

Define core entities, attributes, and relationships for the product.

---

### /design-director:section-spec
**File**: `design-director/design-director-section-spec.md`

Define user flows, UI requirements, and data for a specific section.

---

### /design-director:screen-spec
**File**: `design-director/design-director-screen-spec.md`

Add detailed screen specifications to a section with component breakdowns.

---

### /design-director:sample-data
**File**: `design-director/design-director-sample-data.md`

Generate sample data and TypeScript types for a section.

---

### /design-director:shell-spec
**File**: `design-director/design-director-shell-spec.md`

Define application shell and navigation structure.

---

### /design-director:export
**File**: `design-director/design-director-export.md`

Export complete specification package for implementation with all artifacts.

---

## GitHub Workflow Commands

### /gh:create-issues
**File**: `gh/create-issues.md`
**Stage**: Specification

Create GitHub issues from sprint plan.

**Usage**: Converts planning documents into trackable GitHub issues.

---

### /gh:create-pr
**File**: `gh/create-pr.md`
**Stage**: Deployment

Create pull request with AI-generated description.

**Features**:
- Auto-generated PR description from commits
- Changelog generation
- Testing checklist

---

### /gh:review-pr
**File**: `gh/review-pr.md`
**Stage**: Verification

AI-powered code review using specialized agents.

**Review Areas**:
- Code quality
- Security vulnerabilities
- Performance issues
- Best practices

---

### /gh:address-feedback
**File**: `gh/address-feedback.md`
**Stage**: Verification

Address PR review comments systematically.

---

### /gh:merge-pr
**File**: `gh/merge-pr.md`
**Stage**: Deployment

Merge approved PR and cleanup branches.

---

## Git Workflow Commands

### /git:feature-branch
**File**: `git/feature-branch.md`

Create feature branch following git-flow conventions.

**Pattern**: `feature/{feature-name}`

---

### /git:hotfix-branch
**File**: `git/hotfix-branch.md`

Create hotfix branch for production issues.

**Pattern**: `hotfix/{issue-description}`

---

### /git:sync-branch
**File**: `git/sync-branch.md`

Sync current branch with main/master and resolve conflicts.

---

## E2B Sandbox Management

### Core Management

#### /e2b:management:status
**File**: `e2b/management/status.md`

Show status of all E2B sandboxes including cost and resource usage.

---

#### /e2b:management:start
**File**: `e2b/management/start.md`

Start new E2B sandbox with specified template.

---

#### /e2b:management:cleanup
**File**: `e2b/management/cleanup.md`

Cleanup old/stale E2B sandboxes to reduce costs.

---

#### /e2b:management:exec
**File**: `e2b/management/exec.md`

Execute command in running E2B sandbox.

---

#### /e2b:management:debug
**File**: `e2b/management/debug.md`

Debug E2B sandbox issues with detailed diagnostics.

---

#### /e2b:management:snapshot
**File**: `e2b/management/snapshot.md`

Create snapshot of running E2B sandbox state.

---

#### /e2b:management:restore
**File**: `e2b/management/restore.md`

Restore E2B sandbox from snapshot.

---

#### /e2b:management:test
**File**: `e2b/management/test.md`

Test E2B sandbox connectivity and functionality.

---

### Cost & Optimization

#### /e2b:cost-report
**File**: `e2b/cost-report.md`

Generate detailed E2B cost report and usage analytics.

**Metrics**:
- Total cost
- Cost per feature
- Resource usage
- Optimization opportunities

---

#### /e2b:optimize
**File**: `e2b/optimize.md`

Optimize E2B sandbox usage to reduce costs.

**Strategies**:
- Identify idle sandboxes
- Right-size resources
- Batch operations
- Cleanup recommendations

---

### Orchestration

#### /e2b:orchestration:status
**File**: `e2b/orchestration/status.md`

View E2B orchestration status across all features.

---

#### /e2b:orchestration:events
**File**: `e2b/orchestration/events.md`

View E2B orchestration event log and history.

---

#### /e2b:orchestration:pause-all
**File**: `e2b/orchestration/pause-all.md`

Pause all E2B orchestration to stop costs.

---

#### /e2b:orchestration:resume-all
**File**: `e2b/orchestration/resume-all.md`

Resume all paused E2B orchestration.

---

#### /e2b:orchestration:pause-feature
**File**: `e2b/orchestration/pause-feature.md`

Pause specific feature's E2B orchestration.

---

#### /e2b:orchestration:resume-feature
**File**: `e2b/orchestration/resume-feature.md`

Resume specific feature's E2B orchestration.

---

#### /e2b:orchestration:set-strategy
**File**: `e2b/orchestration/set-strategy.md`

Set orchestration strategy (aggressive, balanced, conservative).

**Strategies**:
- **Aggressive**: Maximum parallelization, higher cost
- **Balanced**: Moderate parallelization, balanced cost
- **Conservative**: Sequential execution, lowest cost

---

### Template Management

#### /e2b:templates:list-templates
**File**: `e2b/templates/list-templates.md`

List all available E2B templates.

---

#### /e2b:templates:create-template
**File**: `e2b/templates/create-template.md`

Create new E2B template from specification.

---

## Orchestration Commands

### /orc:brainstorm
**File**: `orc/brainstorm.md`

Brainstorm feature ideas using multi-agent collaboration.

**Agents Used**: Product strategist, designer, engineer perspectives

---

### /orc:requirements
**File**: `orc/requirements.md`

Gather and document requirements using orchestrated agents.

---

### /orc:plan-feature
**File**: `orc/plan-feature.md`

Plan feature implementation using multi-agent orchestration.

**Outputs**: Technical spec, design spec, implementation plan

---

### /orc:plan-sprints
**File**: `orc/plan-sprints.md`

Plan sprint schedule with task breakdown and estimates.

---

### /orc:review-spec
**File**: `orc/review-spec.md`

Review specification using multi-agent perspectives.

**Review Perspectives**: Engineering, design, QA, product

---

### /orc:parallel
**File**: `orc/parallel.md`

Execute multiple tasks in parallel using orchestration.

---

### /orc:quick
**File**: `orc/quick.md`

Quick orchestrated workflow for common tasks.

---

### /orc:export
**File**: `orc/export.md`

Export orchestration results and artifacts.

---

## Project Management

### /project:init
**File**: `project/init.md`

Initialize project structure and configuration.

**Creates**:
- Project config
- Directory structure
- CI/CD templates
- Documentation templates

---

### /project:status
**File**: `project/status.md`

View project status and metrics.

**Metrics**:
- Progress tracking
- Code quality
- Test coverage
- Performance

---

### /project:config
**File**: `project/config.md`

Configure project settings and preferences.

---

## Testing Commands

### /testing:all
**File**: `testing/all.md`

Run complete test suite across all test types.

**Test Types**: Unit, integration, E2E, performance

---

### /testing:feature
**File**: `testing/feature.md`

Test specific feature with comprehensive coverage.

---

### /testing:matrix
**File**: `testing/matrix.md`

Run tests across multiple environments/configurations.

**Matrix Dimensions**: OS, browser, device, framework version

---

## Code Execution

### /code:execute
**File**: `code/execute.md`
**Stage**: Implementation

Execute pre-generated implementation plan.

**Usage**: Runs through implementation steps from planning phase

---

## Memory Commands

### /memory-action
**File**: `memory-action.md`

Natural language interface for Bumba Memory - store, recall, and query memories.

**Operations**: store | recall | search | forget

---

## Workflows

### /WORKFLOWS
**File**: `WORKFLOWS.md`

Project Management Workflows documentation and templates.

---

## Command Structure

Commands use YAML frontmatter:

```yaml
---
name: command-name
description: Brief description
version: 1.0.0 (optional)
---

Command implementation details
```

## Command Naming Conventions

- **Namespace format**: `category:action` (e.g., `/gh:create-pr`)
- **Hyphenated names**: For multi-word commands (e.g., `/design-explore-ui`)
- **Hierarchical structure**: Organized by category in subdirectories

## Usage

Invoke commands by typing the slash command:

```
/design-explore-ui
/gh:create-pr
/project:init
```

## Related Documentation

- [Agents Inventory](./inventory-agents.md)
- [Skills Inventory](./inventory-skills.md)
- [Hooks Inventory](./inventory-hooks.md)
- [Plugins Inventory](./inventory-plugins.md)

---

**Last Updated**: 2026-01-15
**Command Count**: 81
**Categories**: 12

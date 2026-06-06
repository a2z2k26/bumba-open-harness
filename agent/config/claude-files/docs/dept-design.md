# Design Department - Quick Reference

Quick reference for Design features in Claude Code.

## Overview

Design handles UI/UX design, design systems, design-to-code automation, and accessibility.

## Agents (8)

| Agent | Purpose |
|-------|---------|
| **design-chief** | Design strategy and leadership |
| **design-ui-designer** | Visual design and component creation |
| **design-visual-designer** | Design systems and aesthetics |
| **design-interaction-designer** | UX micro-interactions and flows |
| **design-prototyper** | Interactive prototyping |
| **design-system-architect** | Component libraries and design tokens |
| **design-ux-researcher** | User research and testing |
| **design-accessibility-specialist** | WCAG compliance and inclusive design |

## Commands (25)

### Design Initialization
- `/design-init` - Initialize Design Bridge structure
- `/design-bridge` - Control Design server (start/stop/status)

### Design Exploration
- `/design-explore-ui` - Generate 4 UI directions (E2B sandboxes)
- `/design-explore-ux` - Generate 4 UX directions (E2B sandboxes)
- `/design-nlp` - Create components from natural language

### Layout Transformation
- `/design-layout-to-jsx` - Figma → React/JSX
- `/design-layout-to-vue` - Figma → Vue 3 SFC
- `/design-layout-to-tailwind` - Figma → Tailwind CSS
- `/design-layout-to-compose` - Figma → Jetpack Compose
- `/design-layout-to-flutter` - Figma → Flutter
- `/design-layout-to-swiftui` - Figma → SwiftUI
- `/design-layout-to-html` - Figma → HTML+CSS
- `/design-layout-refine` - Iterative visual parity refinement

### Design Token Transformation
- `/design-transform-react` - Tokens → React code
- `/design-transform-vue` - Tokens → Vue composables
- `/design-transform-angular` - Tokens → Angular services
- `/design-transform-svelte` - Tokens → Svelte stores
- `/design-transform-react-native` - Tokens → React Native
- `/design-transform-flutter` - Tokens → Flutter ThemeData
- `/design-transform-jetpack-compose` - Tokens → Compose Material 3
- `/design-transform-swiftui` - Tokens → SwiftUI extensions
- `/design-transform-web-components` - Tokens → Custom Elements

### Design Utilities
- `/design-generate-styles` - Generate STYLES.md brand guide
- `/design-promote` - Promote staging → production
- `/design-search` - Search tokens and components
- `/design-sync-monitor` - Monitor Figma changes

## Skills (12)

| Skill | Purpose |
|-------|---------|
| **design-explore-ui** | UI design exploration workflow |
| **design-explore-ux** | UX design exploration workflow |
| **bumba-design-director-frontend** | Production frontend design |
| **design-bridge-shared** | Design Bridge utilities |
| **design-figma-sketch** | Figma plugin bidirectional chat |
| **transform-react** | React transformation |
| **transform-vue** | Vue transformation |
| **transform-angular** | Angular transformation |
| **transform-svelte** | Svelte transformation |
| **transform-flutter** | Flutter transformation |
| **transform-jetpack-compose** | Jetpack Compose transformation |
| **transform-swiftui** | SwiftUI transformation |
| **transform-react-native** | React Native transformation |
| **extract-design** | Extract design patterns |
| **extract-figma-mcp** | Figma extraction via MCP |
| **extract-nlp-prompt** | NLP-based component generation |
| **extract-shadcn** | ShadCN component integration |

## Hooks (14)

| Hook | Event | Purpose |
|------|-------|---------|
| **on-component-extract.js** | Component extracted | Update registry |
| **on-component-transform.js** | Component transformed | Generate Storybook stories |
| **on-layout-extract.js** | Layout extracted | Save layout JSON |
| **on-layout-transform-complete.js** | Layout transformed | Validate output |
| **on-token-change.js** | Token file changed | Propagate changes |
| **on-tokens-updated.js** | Tokens transformed | Update theme files |
| **on-registry-change.js** | Registry modified | Maintain consistency |
| **on-cascade-complete.js** | Cascade sync done | Validate results |
| **on-sync-changes.js** | Figma sync detected | Trigger updates |
| **on-design-init-complete.js** | Design init done | Setup infrastructure |
| **on-design-server-setup.js** | Server setup | Configure Figma plugin |
| **post-sync-monitor.sh** | Post-sync | Monitor and cleanup |
| **PreToolUse/ensure-design-system-modules.js** | Before tool use | Validate modules |
| **design-bridge-hook-registry.js** | Hook management | Central registry |

## Plugins (6)

| Plugin | Purpose |
|--------|---------|
| **bumba-design-sync** | Auto-sync Figma changes |
| **bumba-frontend-design** | Frontend design creation |
| **bumba-nlp-design** | NLP to design components |
| **design-explorer-ui** | UI exploration (4 directions) |
| **design-explorer-ux** | UX exploration (4 directions) |
| **frontend-design** | Frontend utilities |

## Common Workflows

1. **Figma → Code**: design-init → extract → layout-to-jsx → hooks auto-generate stories
2. **Design Exploration**: design-explore-ui → select direction → refine → production
3. **Design System**: design-init → generate-styles → transform-react → sync-monitor
4. **Component Creation**: design-nlp → component-transform → storybook generation

## Related Departments

- **Product Strategy**: Receives specs and requirements
- **Engineering**: Hands off production code
- **QA**: Provides designs for visual testing
- **Operations**: Coordinates on design infrastructure

---

→ See [Full Agents Inventory](./inventory-agents.md#design-agents) for detailed agent specs
→ See [Full Commands Inventory](./inventory-commands.md) for command details
→ See [Design Framework](./design-framework.md) for methodologies

**Last Updated**: 2026-01-15

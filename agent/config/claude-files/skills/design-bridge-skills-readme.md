# Design Bridge Skills

Claude Code skills for design extraction and framework transformation.

## Available Skills

### Extraction Skills
- `/extract-design` - **Master extraction skill** - Unified interface for all extraction methods
- `/extract-figma-mcp` - Extract components from Figma via MCP
- `/extract-shadcn` - Extract components from ShadCN registry
- `/extract-nlp-prompt` - Generate components from natural language descriptions

### Core Transformers
- `/transform-react` - Transform to React + TypeScript
- `/transform-vue` - Transform to Vue 3 Composition API
- `/transform-angular` - Transform to Angular standalone components
- `/transform-svelte` - Transform to Svelte + TypeScript

### Mobile/Native Transformers
- `/transform-react-native` - Transform to React Native
- `/transform-flutter` - Transform to Flutter/Dart
- `/transform-swiftui` - Transform to SwiftUI
- `/transform-jetpack-compose` - Transform to Jetpack Compose

## Usage

Each skill:
1. Reads `.design/config.json` for project configuration
2. Loads design tokens from `.design/tokens/`
3. Calls framework-specific optimizer
4. Writes transformed code to `.design/extracted-code/{framework}/`
5. Updates metadata and tracking

## Shared Utilities

Located in `shared/`:
- `read-design-config.js` - Load project configuration
- `load-design-tokens.js` - Load and parse tokens
- `update-metadata.js` - Track transformation history

## Architecture

Skills are thin wrappers around production-tested BUMBA optimizers:

```
User runs: /transform-react
     ↓
skill.md (instructions for Claude Code)
     ↓
Shared utilities (config, tokens)
     ↓
BUMBA optimizer (proven transformation logic)
     ↓
Output to .design/extracted-code/react/
```

This architecture provides:
- **Speed:** Leverage existing tested code
- **Reliability:** Production-proven transformers
- **Consistency:** Same transformation logic as BUMBA CLI
- **Flexibility:** Claude Code wrapper adds new capabilities

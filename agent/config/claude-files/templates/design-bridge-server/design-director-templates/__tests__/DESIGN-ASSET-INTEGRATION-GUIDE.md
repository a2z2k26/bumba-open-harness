# Design Director - Design Asset Integration Guide

**Date**: 2025-12-19
**Purpose**: Documentation of how Design Director references and integrates with existing Bumba Design System assets

---

## Overview

Yes, Design Director **DOES suggest and reference existing design system assets** if they exist in the `.design/` directory. The system uses intelligent conditional logic to adapt its outputs based on what assets are available.

This is handled through:
1. **Runtime Detection** - Checking for tokens and components when commands run
2. **Conditional Templates** - Using Handlebars `{{#if}}` logic to show different instructions
3. **Export Instructions** - Generating framework-specific guidance that references available assets
4. **User Prompts** - Informing users during workflow about available components

---

## How Asset Detection Works

### The bumba-reader.js Utility

Every command loads Bumba context using `getBumbaContext()`:

```javascript
const { getBumbaContext } = require('./.design/bumba-design-director/lib/bumba-reader.js');
const bumbaContext = getBumbaContext();

// Returns:
{
  config: {...},              // .design/config.json (or null)
  tokens: {...},              // .design/tokens/*.json (or null)
  components: [...],          // .design/components/*.json (or null)
  framework: 'react',         // From config or default
  hasConfig: true/false,      // Boolean flags for conditional logic
  hasTokens: true/false,
  hasComponents: true/false
}
```

### Detection Locations

The system checks these locations:
- **Config**: `.design/config.json` → Framework preference
- **Tokens**: `.design/tokens/*.json` → All token files
- **Components**: `.design/components/*.json` → Component metadata

**Graceful Fallback**: If any asset doesn't exist, `bumba-reader.js` returns `null` and sets the `has*` flags to `false`, enabling conditional messaging.

---

## How Assets Are Referenced in Specifications

### 1. Product Overview Template

**Template**: `templates/product-overview.md.tmpl`

**When Tokens Exist**:
```markdown
## Design System Reference

This product uses design tokens from `.design/tokens/`:

- colors.json
- typography.json
- spacing.json

Use these tokens for colors, typography, spacing, and effects throughout the implementation.
```

**When Tokens Don't Exist**:
```markdown
## Design System Reference

Design system tokens will be defined separately using Bumba Design features.

To create design tokens:
1. Design your system in Figma
2. Use the Bumba Figma plugin to extract tokens
3. Tokens will be available in `.design/tokens/`
```

**Always Included**:
```markdown
## Framework

**Target framework**: react

Use `/design-transform-react` to transform Bumba components to this framework.
```

### 2. Section Specification Template

**Template**: `templates/section-spec.md.tmpl`

**When Components Exist**:
```markdown
## Component References

### Available Bumba Components

The following components are available in `.design/components/`:

- **Button** (component)
- **Card** (component)
- **Input** (component)

**Implementation**: Use these components where applicable. Components are available in `.design/extracted-code/react/` after transformation.

If targeting a different framework, run `/design-transform-[framework]` to convert components.
```

**When Components Don't Exist**:
```markdown
## Component References

### Component Requirements

Components should be designed and extracted using Bumba Design features:

1. Design components in Figma following the design system
2. Use Bumba Figma plugin to extract component definitions
3. Transform to react using `/design-transform-react`

The implementation should reference Bumba's component library for consistent patterns.
```

### 3. Shell Specification Template

**Template**: `templates/shell-spec.md.tmpl`

**Always References Framework**:
```markdown
## Framework Integration

Target framework: react

**Bumba Layouts**: If layout components exist in `.design/extracted-code/react/layouts/`, reference them for consistent navigation patterns.
```

---

## How Assets Are Referenced in Export Package

When `/design-director-export` runs, the `export-builder.js` utility generates a complete package with asset-aware instructions.

### Export Package Structure

```
.design/bumba-design-director/design-direction-plan/
├── README.md                    # Quick start with asset status
├── prompts/
│   ├── one-shot-prompt.md       # Full context for coding agents
│   └── section-prompt.md        # Template for incremental work
├── instructions/
│   └── implementation-guide.md  # Detailed asset references
└── specifications/              # Copy of all specs
    ├── product-overview.md
    ├── product-roadmap.md
    ├── data-model/
    ├── shell/
    └── sections/
```

### README.md (Export Package)

**When Assets Exist**:
```markdown
## Design Assets

### Design Tokens
**Location**: `.design/tokens/`
**Files**: colors, typography, spacing

Use these tokens for all styling throughout the application.

### Components
**Location**: `.design/extracted-code/react/`
**Available Components**: 12 components

Use these components as building blocks.
Use Bumba's transformation commands if targeting a different framework.
```

**When Assets Don't Exist**:
```markdown
## Design Assets

### Design Tokens
**Location**: `.design/tokens/`

Design tokens must be extracted from Figma:
1. Run `/design-init` if not already initialized
2. Use Bumba Figma plugin to extract tokens
3. Tokens will be available in `.design/tokens/`

### Components
**Location**: `.design/components/` and `.design/extracted-code/react/`

Components should be designed and extracted using Bumba Design features:
- Design components in Figma
- Extract via Bumba plugin
- Transform to react using `/design-transform-react`
```

### One-Shot Prompt (For Coding Agents)

**Dynamic Context Section**:
```markdown
## Context

All product specifications are in the `specifications/` directory. Design assets (tokens and components) are in the `.design/` directory of the project.

**Framework**: react
**Design Tokens**: Available in .design/tokens/        # OR: Need to be extracted from Figma
**Components**: Available in .design/components/       # OR: Need to be designed and extracted

## Your Task

1. Review all specifications in `specifications/`
2. Import design tokens from `.design/tokens/`
3. Use components from `.design/extracted-code/react/`
4. Implement all sections according to their specifications
...
```

The prompt automatically adapts based on what's available.

### Section Prompt Template

**Always References Assets**:
```markdown
## Design Assets

- **Tokens**: `.design/tokens/` (use for colors, typography, spacing)
- **Components**: `.design/extracted-code/react/` (reference where applicable)

## Your Task

1. Review the section specification
2. Understand the user flows and UI requirements
3. Implement all screens/views for this section
4. Use the provided sample data and types
5. Follow the testing requirements in the specification
```

---

## How Users Are Informed During Workflow

### During Commands

Commands inform users about available assets in real-time:

#### /design-director-section-spec (Step 7)

**When Components Exist**:
```
✓ Bumba components detected

Available components from .design/components/:
- Button (component)
- Card (component)
- Input (component)

These components will be referenced in the specification.
You can use them directly in implementation.
```

**When Components Don't Exist**:
```
ℹ No Bumba components detected

The specification will include instructions for creating components
using Bumba Design features.
```

#### /design-director-vision (Step X)

**When Tokens Exist**:
```
✓ Design tokens detected

Your product will reference these token files:
- colors.json (23 tokens)
- typography.json (8 tokens)
- spacing.json (12 tokens)

These will be documented in product-overview.md
```

### During /design-director-run (Unified Workflow)

The workflow command shows asset status at the beginning:

```
Welcome to Design Director!

Checking Bumba Design System integration...
✓ Config found (framework: react)
✓ Tokens found (3 token files)
✓ Components found (12 components)

Your specifications will reference these assets for implementation.
```

Or if assets don't exist:

```
Welcome to Design Director!

Checking Bumba Design System integration...
ℹ No design tokens found
ℹ No components found

Your specifications will include instructions for creating these assets
using Bumba Design features.
```

---

## Integration Points Summary

### Assets Referenced

| Asset Type | Detection Path | Referenced In | Purpose |
|------------|----------------|---------------|---------|
| **Config** | `.design/config.json` | All templates, export | Framework detection |
| **Tokens** | `.design/tokens/*.json` | product-overview, export | Color, typography, spacing guidance |
| **Components** | `.design/components/*.json` | section-spec, shell-spec, export | Component reuse instructions |
| **Extracted Code** | `.design/extracted-code/{framework}/` | export prompts | Direct code references |

### Commands That Check for Assets

| Command | Checks Tokens | Checks Components | Shows to User |
|---------|---------------|-------------------|---------------|
| `/design-director-init` | ✓ | ✓ | Shows integration status |
| `/design-director-vision` | ✓ | - | Documents in overview |
| `/design-director-section-spec` | - | ✓ | Lists available components |
| `/design-director-shell-spec` | - | ✓ | References layout components |
| `/design-director-export` | ✓ | ✓ | Full asset status in package |
| `/design-director-run` | ✓ | ✓ | Status at workflow start |

---

## Conditional Logic Patterns

### Template Pattern

All templates use this pattern for conditional asset references:

```handlebars
{{#if bumbaTokensAvailable}}
  [Instructions for using existing tokens]
{{else}}
  [Instructions for creating tokens via Bumba features]
{{/if}}
```

### Export Builder Pattern

The export builder adapts prompts dynamically:

```javascript
const instructions = `
**Design Tokens**: ${bumbaContext.hasTokens
  ? 'Available in .design/tokens/'
  : 'Need to be extracted from Figma'}

**Components**: ${bumbaContext.hasComponents
  ? 'Available in .design/components/'
  : 'Need to be designed and extracted'}
`;
```

### Command Pattern

Commands show real-time detection:

```javascript
const bumbaContext = getBumbaContext();

if (bumbaContext.hasComponents) {
  console.log(`✓ Found ${bumbaContext.components.length} components`);
  console.log('These will be referenced in specifications.');
} else {
  console.log('ℹ No components found');
  console.log('Specifications will include component creation guidance.');
}
```

---

## Example Workflows

### Scenario A: Full Bumba Design System Exists

User has already run:
1. `/design-init` (created `.design/` structure)
2. Extracted tokens from Figma (`.design/tokens/` populated)
3. Extracted components from Figma (`.design/components/` populated)
4. Transformed to React (`.design/extracted-code/react/` exists)

**When they run Design Director**:
- ✅ All specifications reference existing tokens
- ✅ Section specs list available components by name
- ✅ Export package provides direct paths to assets
- ✅ Prompts say "Use components from .design/extracted-code/react/"

**Result**: Specifications act as a blueprint that integrates seamlessly with existing design system.

### Scenario B: No Design Assets Yet

User has NOT run `/design-init` or hasn't extracted anything.

**When they run Design Director**:
- ℹ Specifications include instructions for creating tokens
- ℹ Section specs explain how to extract components
- ℹ Export package guides through Bumba feature usage
- ℹ Prompts say "Need to extract tokens from Figma"

**Result**: Specifications guide user through creating design system alongside product specs.

### Scenario C: Partial Design System

User has tokens but no components.

**When they run Design Director**:
- ✅ Token references included (specific file names)
- ℹ Component creation instructions included
- ✅ Export package references tokens directly
- ℹ Export package explains component extraction

**Result**: Specifications leverage what exists, guide creation of what's missing.

---

## Key Benefits

### 1. **Adaptive Guidance**
Specifications automatically adapt to what assets are available, providing relevant instructions for the current state of the project.

### 2. **Asset Reuse**
When design system components exist, specifications explicitly reference them, encouraging reuse and consistency.

### 3. **Progressive Workflow**
Users can:
- Plan product first (Design Director)
- Extract design system later (Bumba features)
- Or do it in reverse order

Both workflows are supported seamlessly.

### 4. **Clear Handoff**
Export packages provide coding agents with exact paths to assets, whether they exist or need to be created.

### 5. **No Duplication**
Design Director NEVER creates design tokens or components - it only references or instructs how to create them via Bumba features.

---

## Design Philosophy

**Design Director generates SPECIFICATIONS.**
**Bumba Design creates ASSETS.**

- Design Director tells you WHAT to build and WHERE existing assets are
- Bumba Design features tell you HOW to create the assets

The integration is **intelligent and conditional**:
- If assets exist → Reference them explicitly
- If assets don't exist → Provide creation instructions
- Always respect the separation of concerns

---

## Summary

✅ **Yes**, Design Director suggests and references existing design system assets

✅ **Detection** happens automatically via `bumba-reader.js`

✅ **References** appear in:
- Product overview (tokens)
- Section specifications (components)
- Shell specifications (layouts)
- Export package (all assets)
- Coding agent prompts (exact paths)

✅ **Conditional logic** adapts instructions based on what's available

✅ **User feedback** shows asset status during workflow

✅ **Integration** is seamless and respects separation of concerns

The system is designed to work whether you have a full design system or are starting from scratch.

---

**Document Generated**: 2025-12-19
**Purpose**: Documentation of design asset integration patterns
**Status**: Complete and validated

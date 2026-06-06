# Skill: Extract Components from ShadCN Registry

## Purpose

Extract components from the ShadCN registry using MCP Server tools,
including source code, CVA variants, Tailwind token dependencies,
and usage examples. This enables importing ShadCN components into
the Design Bridge ecosystem.

## When to Use

- You want to import a ShadCN component into your design system
- You need to analyze CVA variants from a ShadCN component
- You want to extract Tailwind token dependencies
- You need component examples for documentation or stories

## Prerequisites

- ShadCN MCP Server must be connected
- Target project must have `.design/` directory initialized
- Project should have `components.json` configured (for registry discovery)
- Node.js environment with access to extraction utilities

## What ShadCN MCP Provides

| Feature | Available |
|---------|-----------|
| Component source code | Yes |
| CVA variant definitions | Yes |
| TypeScript types | Yes |
| Usage examples | Yes |
| Dependencies list | Yes |
| Install commands | Yes |

## Instructions

### Step 1: Discover Available Registries

Query the project's configured registries.

```
Use mcp__shadcn__get_project_registries

Expected response:
"The following registries are configured in the current project:
- @shadcn"
```

If no `components.json` exists, default to `["@shadcn"]`.

### Step 2: Search for Component

Search the registry for the desired component.

```
Use mcp__shadcn__search_items_in_registries with:
- registries: ["@shadcn"]
- query: "{componentName}"
- limit: 10

Example:
mcp__shadcn__search_items_in_registries({
  registries: ["@shadcn"],
  query: "button",
  limit: 10
})
```

Note the item type:
- `registry:ui` - Main UI component
- `registry:example` - Usage example

### Step 3: Get Component Source Code

Fetch the full source code including CVA definitions.

```
Use mcp__shadcn__get_item_examples_from_registries with:
- registries: ["@shadcn"]
- query: "{componentName}"

This returns the complete source code with:
- Import statements (dependencies)
- CVA variant definitions
- Component implementation
- TypeScript types
```

### Step 4: Parse CVA Variants

Extract variant information from the source code.

```javascript
const { extractCvaVariants } = require('./shadcn-variant-extractor');

const cvaData = extractCvaVariants(sourceCode);

// Returns:
// {
//   variants: [
//     { name: 'variant', options: ['default', 'destructive', ...] },
//     { name: 'size', options: ['default', 'sm', 'lg', 'icon'] }
//   ],
//   defaultVariants: { variant: 'default', size: 'default' },
//   baseClasses: 'inline-flex items-center...'
// }
```

### Step 5: Extract Token Dependencies

Analyze Tailwind classes for design token usage.

```javascript
const { extractTokenDependencies } = require('./shadcn-token-extractor');

const tokens = extractTokenDependencies(sourceCode);

// Returns:
// {
//   colors: ['bg-primary', 'text-primary-foreground', ...],
//   typography: ['text-sm', 'font-medium'],
//   spacing: ['px-4', 'py-2', 'h-9'],
//   effects: ['shadow-xs', 'ring-[3px]'],
//   borderRadius: ['rounded-md'],
//   cssVariables: ['--primary', '--background']
// }
```

### Step 6: Get Usage Examples

Fetch demo code for the component.

```
Use mcp__shadcn__get_item_examples_from_registries with:
- registries: ["@shadcn"]
- query: "{componentName}-demo"

Common patterns:
- "button-demo" - Basic button examples
- "button-icon" - Icon button variations
- "button-link" - Link-style button
```

### Step 7: Get Dependencies

Query component dependencies for package.json.

```
Use mcp__shadcn__view_items_in_registries with:
- items: ["@shadcn/{componentName}"]

Returns metadata including npm dependencies:
- @radix-ui/react-* - Radix UI primitives
- class-variance-authority - CVA library
- clsx / tailwind-merge - Class utilities
```

### Step 8: Transform to Design Bridge Format

Convert extracted data to registry format.

```javascript
const { transformShadcnComponent } = require('./shadcn-transformer');

const component = transformShadcnComponent({
  componentName: 'button',
  registryName: '@shadcn',
  sourceCode: sourceCode,
  examples: exampleData,
  dependencies: dependencyList
});
```

### Step 9: Write to Source Directory

Save the transformed component.

```javascript
const outputPath = `.design/source/components/${componentName.toLowerCase()}.json`;
fs.writeFileSync(outputPath, JSON.stringify(component, null, 2));
```

### Step 10: Update Registry

Add component to the registry with source tracking.

```javascript
registry.components[componentId] = {
  name: component.name,
  type: 'COMPONENT',
  source: {
    type: 'shadcn',
    registry: '@shadcn',
    extractedAt: new Date().toISOString()
  },
  variants: component.variants,
  tokenDependencies: component.tokenDependencies,
  paths: {
    rawSource: outputPath,
    codeOutput: `src/components/${PascalCase(componentName)}.tsx`
  }
};
```

## Expected Output

```
Searching ShadCN registry for: button
Found component: button (registry:ui)

Extracting source code...
  CVA Variants: variant (6 options), size (6 options)
  Default: variant=default, size=default

Extracting tokens...
  Colors: 12 tokens found
  Typography: 2 tokens found
  Spacing: 4 tokens found
  Effects: 3 tokens found

Fetching examples...
  Found 8 examples (button-demo, button-icon, ...)

Dependencies:
  - @radix-ui/react-slot
  - class-variance-authority

Written to: .design/source/components/button.json
Registry updated: shadcn-button

Extraction complete!
  Component: Button
  Source: shadcn (@shadcn)
  Variants: 2 dimensions, 12 total options
  Tokens: 12 colors, 4 spacing
```

## Configuration

```javascript
// In .design/config.json
{
  "shadcn": {
    "defaultRegistry": "@shadcn",
    "includeExamples": true,
    "extractTokens": true,
    "autoInstallDependencies": false
  }
}
```

## Component Categories

ShadCN components are categorized as:

| Category | Components |
|----------|------------|
| button | button, toggle, toggle-group |
| input | input, textarea, select, checkbox, radio, switch, slider |
| card | card (CardHeader, CardContent, etc.) |
| modal | dialog, alert-dialog, sheet, drawer |
| navigation | tabs, menubar, dropdown-menu, breadcrumb |
| layout | accordion, collapsible, separator, scroll-area |
| feedback | toast, sonner, alert, progress, skeleton |
| overlay | popover, tooltip, hover-card, context-menu |
| data | table, calendar, date-picker |
| form | form, label, input-otp |
| display | avatar, badge, carousel |

## Troubleshooting

### "No registries found"
Run: Check if `components.json` exists or use default `["@shadcn"]`

### "Component not found"
Try searching with variations: "button", "Button", "btn"

### "CVA not detected"
Some components don't use CVA (e.g., Card uses composition)

### "MCP Server not connected"
Verify ShadCN MCP server is configured and running

### "Examples not found"
Try pattern: `{component}-demo` or just `{component}`

## Quick Reference

| MCP Tool | Purpose |
|----------|---------|
| `mcp__shadcn__get_project_registries` | Get configured registries |
| `mcp__shadcn__list_items_in_registries` | List all items with pagination |
| `mcp__shadcn__search_items_in_registries` | Fuzzy search components |
| `mcp__shadcn__view_items_in_registries` | Get component metadata |
| `mcp__shadcn__get_item_examples_from_registries` | Get source code & examples |
| `mcp__shadcn__get_add_command_for_items` | Get CLI install command |
| `mcp__shadcn__get_audit_checklist` | Post-install verification |

## Related Skills

- `/extract-figma-mcp` - Extract from Figma via MCP
- `/transform-react` - Transform to React code
- `/design-init` - Initialize .design/ directory

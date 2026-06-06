# Design Bridge Extraction Skill

## Purpose

This is the **master extraction skill** for Design Bridge. It provides a unified interface for extracting design components from any supported source:

- **Figma** (via MCP tools)
- **ShadCN Registry** (via MCP tools)
- **Natural Language** (AI-generated)
- **Manual Specification** (JSON input)

## Quick Start

```
Extract a button component
```

The system automatically detects the best method based on your input.

## Explicit Method Selection

### Figma Extraction
```
Extract from Figma: https://figma.com/file/abc123/Design-System?node-id=123:456
```

### ShadCN Extraction
```
Extract shadcn component: button
```

### NLP Generation
```
Generate component: A card with an image header, title, description, and action buttons
```

### Manual Specification
```json
{
  "method": "manual",
  "target": {
    "name": "Badge",
    "type": "COMPONENT",
    "structure": { ... }
  }
}
```

## Method Selection Guide

| If you have... | Use method | Example input |
|----------------|------------|---------------|
| Figma URL | figma-mcp | `figma.com/file/...` |
| ShadCN component name | shadcn | `button`, `card`, `dialog` |
| Description of what you want | nlp-prompt | "A hero section with..." |
| Detailed JSON specification | manual | `{"name": "...", ...}` |
| Nothing specific | interactive | Just ask for help |

## Auto-Detection Rules

The unified interface automatically detects methods based on input:

1. **Figma URL patterns**: `figma.com/file/`, `figma.com/design/`, `figma.com/proto/`
2. **ShadCN components**: Known component names (button, card, dialog, etc.) or short lowercase identifiers
3. **JSON specifications**: Input starting with `{` that parses as valid JSON with a `name` property
4. **Natural language**: Everything else defaults to NLP generation

## Workflow

### Step 1: Provide Input

Give me one of:
- A Figma URL
- A ShadCN component name
- A description of the component
- A JSON specification

### Step 2: Method Detection

I'll automatically detect the best extraction method, or you can specify:
```
Use method: shadcn
```

### Step 3: Extraction

The appropriate sub-skill handles extraction:
- `extract-figma-mcp.md` for Figma
- `extract-shadcn.md` for ShadCN
- `extract-nlp-prompt.md` for NLP
- Manual inline processing for JSON specs

### Step 4: Normalization

All outputs are normalized to the same format:
- Component ID and name
- Source tracking
- Token dependencies
- Structure and variants
- File paths

### Step 5: Registry Update

The component is added to `.design/registry.json` with:
- Unique ID
- Source type and timestamp
- File paths
- Metadata

## Options

| Option | Description | Default |
|--------|-------------|---------|
| framework | Target framework | react |
| outputDir | Output directory | .design |
| generateStory | Create Storybook story | false |
| generateCode | Transform to code | true |
| updateExisting | How to handle existing (update/merge/skip/new) | update |
| trackHistory | Track extraction history | true |

## Examples

### Example 1: Figma Component
```
Extract the Button component from our Figma design system:
https://figma.com/file/abc123/Components?node-id=10:20
```

**Result**: Button component extracted with all variants and states

### Example 2: ShadCN Dialog
```
I need the dialog component from shadcn
```

**Result**: Dialog component with all shadcn patterns and tokens

### Example 3: Custom Component via NLP
```
Create a pricing card with:
- Plan name at the top
- Large price display
- List of features with checkmarks
- CTA button at the bottom
- "Popular" badge option
```

**Result**: PricingCard component with inferred structure and tokens

### Example 4: Manual Definition
```json
{
  "method": "manual",
  "target": {
    "name": "StatusBadge",
    "type": "COMPONENT_SET",
    "category": "feedback",
    "variants": {
      "status": {
        "success": { "backgroundColor": "Green/500" },
        "warning": { "backgroundColor": "Yellow/500" },
        "error": { "backgroundColor": "Red/500" }
      }
    }
  }
}
```

**Result**: StatusBadge with 3 variants, precise token mapping

## Handling Existing Components

When extracting a component that already exists:

```
Component "Button" already exists (extracted 2024-11-28 via figma-mcp).

Options:
1. Update - Replace with new extraction
2. Merge - Combine new data with existing customizations
3. Skip - Keep existing, don't extract
4. New - Create as "Button_2"

Choose (1-4):
```

## Output Format

All methods produce unified output:

```json
{
  "success": true,
  "method": "shadcn",
  "timestamp": "2024-11-29T10:00:00.000Z",
  "component": {
    "id": "shadcn-button-a1b2c3",
    "name": "Button",
    "type": "COMPONENT_SET",
    "category": "button",
    "source": {
      "type": "shadcn",
      "extractedAt": "2024-11-29T10:00:00Z"
    },
    "paths": {
      "rawSource": ".design/source/components/Button.json",
      "component": ".design/components/Button.json",
      "generated": null,
      "story": null
    }
  },
  "warnings": [],
  "errors": [],
  "metadata": {
    "duration": 150,
    "normalizedFields": 8,
    "tokensExtracted": 12
  }
}
```

## CLI Usage

```bash
# Auto-detect method
design-bridge extract "button"

# Explicit Figma extraction
design-bridge extract --url "https://figma.com/file/..."

# ShadCN component
design-bridge extract --component dialog

# NLP description
design-bridge extract --describe "A hero section with gradient background"

# Manual JSON file
design-bridge extract --spec ./my-component.json

# Interactive mode
design-bridge extract --interactive

# View extraction history
design-bridge extract --history

# Re-extract existing component
design-bridge extract --re-extract Button
```

## Implementation Details

The unified interface uses these modules:

1. **unified-interface.js** - Core interface logic
   - `normalizeInput()` - Normalize all input types
   - `detectMethodFromTarget()` - Auto-detect method
   - `createUnifiedOutput()` - Create standard output
   - `validateOutput()` - Validate output schema

2. **Method-specific wrappers** - Handle extraction
   - Each method has its own skill and wrapper
   - All return data that gets normalized

3. **Registry integration** - Track components
   - All components stored in `.design/registry.json`
   - History tracked in `.design/extraction-history.json`

## Troubleshooting

### "Method could not be determined"
**Cause**: Input doesn't match any known pattern
**Fix**: Specify method explicitly or use interactive mode

### "Component extraction failed"
**Cause**: Method-specific error
**Fix**: Check sub-skill output for details, verify source is accessible

### "Normalization failed"
**Cause**: Source produced unexpected format
**Fix**: Check source skill is up to date, report as bug if persists

### "Component already exists"
**Cause**: A component with the same name was previously extracted
**Fix**: Use `updateExisting` option or choose action when prompted

## Notes

- All extractions are logged to `.design/extraction-history.json`
- Use `design-bridge extract --history` to view past extractions
- Use `design-bridge extract --re-extract ComponentName` to refresh
- The unified interface ensures consistent output regardless of source

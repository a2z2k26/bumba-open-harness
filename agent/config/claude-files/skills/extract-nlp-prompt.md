# NLP Prompt Extraction Skill

## Purpose

Generate Design Bridge components from natural language descriptions. This skill infers component structure, tokens, variants, and props from descriptive text.

## Quick Start

```
Generate a button with icon support and loading state
```

## Input Format

Provide a natural language description of the component you want to create. Include:

- **Name** (optional): "Create a component called PrimaryButton"
- **Description**: What the component does/looks like
- **Features**: Specific functionality (icon support, loading state, etc.)
- **Variants**: Different visual styles (primary, secondary, ghost)
- **States**: Interactive states (hover, disabled, loading)

## Examples

### Simple Button
```
Create a primary action button with hover and disabled states
```

### Complex Card
```
Create a pricing card with:
- Plan name at the top
- Large price display ($XX/month format)
- List of features with checkmarks
- CTA button at the bottom
- Optional "Popular" badge
```

### Input Field
```
A text input field with:
- Placeholder text support
- Error state with red border and message
- Required indicator (asterisk)
- Optional helper text below
```

### Modal Dialog
```
A confirmation modal with:
- Title and message
- Cancel and confirm buttons
- Close button in corner
- Backdrop click to dismiss
```

## Component Categories

The skill infers category from your description:

| Category | Keywords detected |
|----------|-------------------|
| button | button, click, action, submit |
| input | input, field, text, enter, type |
| card | card, container, box, panel |
| navigation | nav, menu, link, tab, breadcrumb |
| overlay | modal, dialog, popup, drawer, sheet |
| feedback | alert, toast, notification, message |
| display | badge, avatar, icon, image |
| layout | grid, flex, stack, container |

## What Gets Inferred

### Structure
- Root element type
- Children and nested components
- Layout patterns

### Tokens
- Colors (from category and description)
- Typography (text sizes, weights)
- Spacing (padding, margin, gap)
- Effects (shadows, borders)
- Border radius

### Variants
- Visual variants (primary, secondary, etc.)
- Size variants (sm, md, lg)
- State variants (default, hover, active)

### Props
- Category-specific props (onClick for buttons, value/onChange for inputs)
- Description-inferred props (icon, loading, error)
- Standard props (className, children)

## Options

Specify options in your request:

```
Create a button with these options:
- Name: IconButton
- Category: button
- Framework: react
- Variants: primary, secondary, ghost
- Sizes: sm, md, lg
- States: default, hover, active, disabled, loading
```

## Output

The skill produces a Design Bridge component in `.design/components/`:

```json
{
  "id": "nlp-primary-button-1701234567890",
  "name": "PrimaryButton",
  "type": "COMPONENT",
  "category": "button",
  "description": "A primary action button with hover and disabled states",
  "source": {
    "type": "nlp-prompt",
    "extractedAt": "2024-11-29T10:00:00.000Z",
    "prompt": "A primary action button with hover and disabled states",
    "generationParams": {
      "category": "button",
      "framework": "react"
    }
  },
  "structure": {
    "type": "button",
    "name": "PrimaryButton",
    "children": [...]
  },
  "tokenDependencies": {
    "colors": ["Primary/500", "Primary/600", "Neutral/200"],
    "typography": ["text-sm", "font-medium"],
    "spacing": ["12", "24"],
    "effects": ["shadow-sm"],
    "borderRadius": ["md"]
  },
  "variants": {
    "variant": {
      "primary": { "backgroundColor": "Primary/500" },
      "secondary": { "backgroundColor": "Secondary/500" }
    },
    "size": {
      "sm": { "padding": "8 16" },
      "md": { "padding": "12 24" }
    }
  },
  "props": [
    { "name": "children", "type": "React.ReactNode", "required": true },
    { "name": "onClick", "type": "() => void", "required": false },
    { "name": "disabled", "type": "boolean", "required": false, "default": "false" }
  ],
  "interactiveStates": ["default", "hover", "disabled"]
}
```

## Implementation

The NLP skill uses these modules:

1. **nlp-input-schema.js** - Validate and normalize input
2. **nlp-prompts.js** - System prompts for generation
3. **nlp-structure-generator.js** - Generate component structure
4. **nlp-token-inference.js** - Infer token dependencies
5. **nlp-variant-generator.js** - Generate variants
6. **nlp-props-inference.js** - Infer component props
7. **nlp-registry-integration.js** - Registry operations

## Best Practices

### Be Specific
```
Good: "A button with an icon on the left, loading spinner, and disabled state"
Bad: "A button"
```

### Include Context
```
Good: "A form submit button that shows loading while the form is being submitted"
Bad: "A loading button"
```

### Specify Visual Variants
```
Good: "Primary, secondary, and ghost button variants"
Bad: "Different types of buttons"
```

### Mention Interactive States
```
Good: "Default, hover, active, focus, and disabled states"
Bad: "With hover"
```

## Refinement

You can refine a generated component:

```
Refine PrimaryButton: Add an icon prop and increase the border radius
```

The skill tracks refinement history and version numbers.

## Troubleshooting

### "Component name required"
**Fix**: Specify a name in your description: "Create a component called MyButton..."

### "Category could not be inferred"
**Fix**: Include category keywords or specify: "Create a button component..."

### "No variants generated"
**Fix**: Describe the variations you need: "with primary and secondary variants"

## Notes

- Components are saved to `.design/components/{ComponentName}.json`
- Source JSON is saved to `.design/source/components/{ComponentName}.json`
- All NLP components have `source.type: "nlp-prompt"`
- Refinements increment the version number
- History is tracked in `.design/extraction-history.json`

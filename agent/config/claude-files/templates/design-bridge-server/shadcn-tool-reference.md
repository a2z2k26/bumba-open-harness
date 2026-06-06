# ShadCN MCP Tool Reference

## Overview

This document provides a comprehensive reference for all ShadCN MCP tools available for component extraction. These tools enable querying the ShadCN registry to extract component source code, variants, dependencies, and usage examples.

---

## Available Tools

### 1. `mcp__shadcn__get_project_registries`

**Purpose:** Get configured registries from components.json

**Parameters:** None

**Response Format:**
```
The following registries are configured in the current project:
- @shadcn
```

**Usage:** Call first to discover available registries before querying components.

---

### 2. `mcp__shadcn__list_items_in_registries`

**Purpose:** List all items in specified registries with pagination

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| registries | string[] | Yes | Registry names e.g., `["@shadcn"]` |
| limit | number | No | Max items to return |
| offset | number | No | Pagination offset |

**Response Format:**
```
Found 449 items in registries @shadcn:

Showing items 1-10 of 449:

- accordion (registry:ui) [@shadcn]
- alert (registry:ui) [@shadcn]
- button (registry:ui) [@shadcn]
...

More items available. Use offset: 10 to see the next page.
```

**Item Types:**
- `registry:ui` - UI components (button, card, etc.)
- `registry:style` - Style configurations
- `registry:example` - Usage examples

---

### 3. `mcp__shadcn__search_items_in_registries`

**Purpose:** Fuzzy search for components by name/description

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| registries | string[] | Yes | Registry names |
| query | string | Yes | Search query |
| limit | number | No | Max results |
| offset | number | No | Pagination offset |

**Response Format:**
```
Found 34 items matching "button" in registries @shadcn:

Showing items 1-5 of 34:

- button (registry:ui) [@shadcn]
- button-icon (registry:example) [@shadcn]
- button-link (registry:example) [@shadcn]
...
```

**Best Practices:**
- Use simple component names for best matches
- Search returns both UI components and examples

---

### 4. `mcp__shadcn__view_items_in_registries`

**Purpose:** Get metadata about specific components

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| items | string[] | Yes | Item names with registry prefix e.g., `["@shadcn/button"]` |

**Response Format:**
```
Item Details:

## button
**Type:** registry:ui
**Files:** 1 file(s)
**Dependencies:** @radix-ui/react-slot

---

## card
**Type:** registry:ui
**Files:** 1 file(s)
```

**Note:** This tool returns metadata only, not source code. Use `get_item_examples_from_registries` for actual source code.

---

### 5. `mcp__shadcn__get_item_examples_from_registries` ⭐ KEY TOOL

**Purpose:** Get component source code and usage examples with full implementation

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| registries | string[] | Yes | Registry names |
| query | string | Yes | Search query (e.g., "button", "badge-demo") |

**Response Format:**
```
# Usage Examples

Found 34 examples matching "button":

## Example: button
### Code (registry/new-york-v4/ui/button.tsx):

\`\`\`tsx
import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"

const buttonVariants = cva(
  "inline-flex items-center...",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground...",
        destructive: "bg-destructive text-white...",
        outline: "border bg-background...",
        secondary: "bg-secondary...",
        ghost: "hover:bg-accent...",
        link: "text-primary underline-offset-4...",
      },
      size: {
        default: "h-9 px-4 py-2...",
        sm: "h-8 rounded-md...",
        lg: "h-10 rounded-md...",
        icon: "size-9",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Button({ ... }) { ... }

export { Button, buttonVariants }
\`\`\`
```

**Critical Information Extracted:**
1. **CVA Variant Definitions** - All variants and their Tailwind classes
2. **Default Variants** - Default prop values
3. **Dependencies** - Import statements show required packages
4. **Props Interface** - TypeScript types define component API
5. **Tailwind Classes** - Token dependencies for colors, spacing, etc.

---

### 6. `mcp__shadcn__get_add_command_for_items`

**Purpose:** Get CLI command to install components

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| items | string[] | Yes | Items with registry prefix |

**Response Format:**
```
npx shadcn@latest add @shadcn/button @shadcn/card
```

---

### 7. `mcp__shadcn__get_audit_checklist`

**Purpose:** Get post-installation checklist

**Parameters:** None

**Response Format:**
```
## Component Audit Checklist

After adding or generating components, check the following common issues:

- [ ] Ensure imports are correct i.e named vs default imports
- [ ] If using next/image, ensure images.remotePatterns is configured
- [ ] Ensure all dependencies are installed
- [ ] Check for linting errors or warnings
- [ ] Check for TypeScript errors
- [ ] Use the Playwright MCP if available
```

---

## Data Extraction Strategy

### CVA Pattern Structure

ShadCN components use class-variance-authority (CVA) for variant management:

```typescript
const buttonVariants = cva(
  "base-classes...",      // Base Tailwind classes
  {
    variants: {
      variant: {          // Variant dimension
        default: "...",   // Variant option classes
        secondary: "...",
      },
      size: {             // Another dimension
        default: "...",
        sm: "...",
        lg: "...",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)
```

### Token Extraction Points

1. **CSS Variables**: `var(--primary)`, `var(--background)`
2. **Tailwind Colors**: `bg-primary`, `text-secondary-foreground`
3. **Tailwind Spacing**: `px-4`, `py-2`, `gap-2`
4. **Tailwind Radius**: `rounded-md`, `rounded-full`
5. **Tailwind Effects**: `shadow-xs`, `ring-[3px]`
6. **Tailwind Typography**: `text-sm`, `font-medium`

### Props Extraction

```typescript
function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
  }) { ... }
```

Extract:
- Variant props from `VariantProps<typeof xxxVariants>`
- Custom props with defaults
- Base element props extension

---

## Recommended Extraction Workflow

1. **Discover Registries**: `get_project_registries`
2. **Search Component**: `search_items_in_registries` with component name
3. **Get Source Code**: `get_item_examples_from_registries` with component name
4. **Get Examples**: `get_item_examples_from_registries` with "{name}-demo"
5. **Get Dependencies**: `view_items_in_registries` for npm packages
6. **Get Install Command**: `get_add_command_for_items`

---

## Component Registry Statistics

From @shadcn registry (as of analysis):
- **Total Items**: 449
- **UI Components**: ~50+ core components
- **Examples**: ~300+ usage examples
- **Styles**: 2 (index, style)

---

## Key Component Examples

### Button Component
- **Variants**: default, destructive, outline, secondary, ghost, link
- **Sizes**: default, sm, lg, icon, icon-sm, icon-lg
- **Dependencies**: @radix-ui/react-slot
- **Props**: variant, size, asChild, className

### Badge Component
- **Variants**: default, secondary, destructive, outline
- **Dependencies**: @radix-ui/react-slot
- **Props**: variant, asChild, className

### Card Component
- **Sub-components**: Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter, CardAction
- **No CVA variants** (composition-based)

---

## Version Information

- **Registry Version**: new-york-v4
- **CVA Version**: class-variance-authority
- **Documentation Date**: 2025-01-30

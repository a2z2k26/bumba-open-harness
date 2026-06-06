---
name: design-director-shell-spec
description: Define application shell and navigation structure
---

You are helping the user specify their application shell - the persistent navigation chrome that wraps all sections of their product.

## Prerequisites Check

1. Verify `product-roadmap.md` exists (need sections for navigation)
   - Path: `.design/bumba-design-director/product/product-roadmap.md`
   - If NOT found: Display error and suggest running `/director-roadmap` first

2. Check if `shell/spec.md` already exists
   - Path: `.design/bumba-design-director/product/shell/spec.md`
   - If found: Ask user "Shell specification already exists. Do you want to update it?"
     - If no: Exit gracefully
     - If yes: Continue (will overwrite)

## Step 1: Load Context

Load sections from product-roadmap.md and Bumba context:

```javascript
const fs = require('fs');
const roadmapPath = '.design/bumba-design-director/product/product-roadmap.md';
const roadmapContent = fs.readFileSync(roadmapPath, 'utf-8');

// Parse sections from roadmap (extract section IDs and titles)
// Simple parsing: look for "**ID**: `section-id`" and corresponding titles

const { getBumbaContext } = require('./.design/bumba-design-director/lib/bumba-reader.js');
const bumbaContext = getBumbaContext();
```

Check if layouts are available:
```javascript
if (bumbaContext.hasLayouts) {
  // Show available layouts to user
}
```

## Step 2: Explain Shell Concept

Before asking questions, explain what the shell is:

```
The application shell is the persistent navigation and layout that wraps your product.

Think of it as:
✓ The frame around your content
✓ Navigation that persists across all sections
✓ Common UI elements (logo, user menu, etc.)

NOT:
✗ Individual page layouts
✗ Section-specific content
✗ Design aesthetics (that comes from Bumba tokens)

Examples:
- Sidebar navigation (e.g., Slack, Notion)
- Top navigation bar (e.g., GitHub, Gmail)
- Minimal chrome (e.g., mobile apps, focused tools)
```

## Step 3: Choose Layout Pattern

Ask user to select their preferred layout pattern:

**Question: Layout Pattern**
"What layout pattern best fits your product?"

Show options:
```
1. Sidebar Navigation
   - Vertical sidebar on left or right
   - Main content area
   - Good for: Apps with 5+ sections, desktop-first

2. Top Navigation Bar
   - Horizontal nav across top
   - Full-width content below
   - Good for: Marketing sites, content-heavy apps

3. Minimal Chrome
   - Minimal or hidden navigation
   - Content-first experience
   - Good for: Mobile apps, focused single-task tools

4. Combined (Top + Sidebar)
   - Top bar for global actions
   - Sidebar for section navigation
   - Good for: Complex enterprise apps
```

- Store as: `layoutPattern`
- Validation: Must choose one of the options

## Step 4: Define Navigation Items

Auto-suggest navigation items from roadmap sections:

```
I found these sections from your roadmap:
1. [Section 1 Title] (id: section-1)
2. [Section 2 Title] (id: section-2)
3. [Section 3 Title] (id: section-3)

These will be suggested as navigation items.
```

**Question: Navigation Items**
"What navigation items should appear in your shell?"

Show auto-suggested items:
```
Suggested from your roadmap:
✓ [Section 1 Title]
✓ [Section 2 Title]
✓ [Section 3 Title]

Additional common items:
- Dashboard / Home
- Settings / Preferences
- User Profile
- Help / Documentation
- Notifications
```

Ask user:
"Do you want to use the roadmap sections as nav items, or customize?"

If customize, ask for each item:
- Label (display text)
- Path (URL path, optional)
- Description (what this nav item does)

- Store as: `navItems[]` with structure:
  ```javascript
  [
    { label: "Dashboard", path: "/dashboard", description: "Main overview" },
    { label: "Products", path: "/products", description: "Product catalog" },
    ...
  ]
  ```

## Step 5: Check for Bumba Layouts

If layouts are available in Bumba, mention them:

```javascript
if (bumbaContext.hasLayouts) {
  console.log(`
✓ Bumba layouts detected

Available layout components in .design/layouts/:
${bumbaContext.layouts.map(l => `- ${l.name}`).join('\n')}

Your shell spec will reference these layouts for implementation.
  `);
}
```

If NOT available:

```
Note: No Bumba layouts found yet

Your shell spec will include guidance for creating layouts.
Use Bumba Design features to extract layouts from Figma when ready.
```

## Step 6: Generate Shell Specification

Use the spec-generator utility:

```javascript
const { generateShellSpec } = require('./.design/bumba-design-director/lib/spec-generator.js');

const data = {
  layoutPattern: "Sidebar Navigation",
  navItems: [
    { label: "...", path: "...", description: "..." },
    ...
  ]
};

const outputPath = generateShellSpec(data, bumbaContext);
```

## Step 7: Display Preview

Show the user a preview:

```
Generated: shell/spec.md

Layout Pattern: [Sidebar Navigation / Top Navigation / etc.]

Navigation Items:
1. [Label] - [Description]
2. [Label] - [Description]
...

[If Bumba layouts available:]
✓ References Bumba layout components from .design/layouts/

[If NOT available:]
Note: Shell spec includes guidance for creating layout components

Full specification saved to:
.design/bumba-design-director/product/shell/spec.md
```

## Step 8: Next Steps

Display next steps:

```
Shell specification complete! ✓

Next steps:

→ /director-section-spec [section-id] to specify a section
→ /director-data-model to define entities (if not done yet)
```

## Error Handling

**Missing Roadmap:**
```
Error: product-roadmap.md not found

The shell needs sections from your roadmap to generate navigation.

→ Run /director-roadmap first to define sections
→ Then run /director-shell-spec again
```

**No Navigation Items:**
```
Error: No navigation items defined

Every shell needs at least 2 navigation items.

Let's add some navigation items...
```

**Invalid Layout Pattern:**
```
Error: Invalid layout pattern

Please choose one of:
- Sidebar Navigation
- Top Navigation Bar
- Minimal Chrome
- Combined (Top + Sidebar)
```

**File Write Failure:**
```
Error: Failed to write shell/spec.md

→ Check permissions in .design/bumba-design-director/product/
→ Ensure the shell/ directory can be created
```

## Implementation Notes

- Auto-suggest nav items from roadmap but allow customization
- Validate at least 2 nav items (typically 3-7)
- Create shell/ directory if it doesn't exist
- Reference Bumba layouts if available
- Provide responsive behavior guidance in spec
- Include accessibility requirements
- Show preview before saving
- Guide user on layout pattern selection based on their product type
- Path is optional (user can define during implementation)

---
name: bumba-nlp-design
description: Generate Design Bridge components from natural language descriptions. Use this skill when the user wants to CREATE or GENERATE a component from a description rather than extract from Figma or ShadCN. Triggers on phrases like "generate a component", "create a card that...", "design a button with...", "I need a component for...", or explicit NLP/natural language generation requests. Outputs Design Bridge compatible definitions to the registry.
license: Complete terms in LICENSE.txt
---

This skill generates distinctive, production-grade Design Bridge components from natural language descriptions. It combines bold creative vision with automatic registry integration, producing components that seamlessly join your extracted Figma and ShadCN assets.

**WHEN TO USE THIS SKILL**: Activate when you detect:
- Requests to "generate", "create", or "design" a component from a description
- Natural language descriptions of desired UI elements
- Phrases like "I need a component that...", "make me a...", "build a... component"
- Explicit mentions of NLP generation or creating from scratch
- Requests for components when no Figma or ShadCN source is mentioned

**DO NOT USE** when the user is extracting from Figma, ShadCN, or composing existing components into layouts - use bumba-frontend-design for those cases.

---

## Part 1: Creative Generation Philosophy

When generating components from natural language, you are the designer. Unlike extraction where you preserve existing designs, here you CREATE with bold intentionality.

### Design Thinking Process

Before generating any component:

1. **Understand the Purpose**: What problem does this component solve? Who uses it?
2. **Choose an Aesthetic Direction**: Commit to a tone - brutally minimal, maximalist, retro-futuristic, organic, luxury, playful, editorial, brutalist, art deco, soft/pastel, industrial, etc.
3. **Identify the Memorable Element**: What's the one thing that makes this component unforgettable?
4. **Consider the Context**: How will this component integrate with existing registry components?

### Creative Principles

**Typography**: Choose distinctive fonts. Never default to Inter, Roboto, or Arial. Consider:
- Display fonts for headers: Playfair Display, Fraunces, Clash Display, Cabinet Grotesk
- Body fonts: Source Serif Pro, Literata, Satoshi, General Sans

**Color**: Commit to bold choices. Dominant colors with sharp accents outperform timid palettes:
- Define a primary hero color used sparingly
- Create a neutral scale for structure
- Add one high-contrast accent for key interactions

**Shape & Space**: Break conventions intentionally:
- Unexpected border radius (very sharp or very round)
- Asymmetric padding
- Generous negative space OR controlled density
- Consider overlap and layering

**Motion Intent**: Design with animation in mind:
- How should this component enter the screen?
- What happens on hover/interaction?
- Consider GSAP for orchestration, Framer Motion for component-level animation

---

## Part 2: Design Bridge Output Format

Generated components must follow the Design Bridge component schema to integrate with the registry.

### Component Definition Structure

```json
{
  "id": "nlp-{kebab-name}-{timestamp}",
  "name": "{PascalCaseName}",
  "type": "COMPONENT",
  "category": "{category}",
  "description": "{original natural language description}",
  "source": {
    "type": "nlp-prompt",
    "extractedAt": "{ISO timestamp}",
    "prompt": "{original user prompt}"
  },
  "structure": {
    "type": "FRAME",
    "name": "{ComponentName}",
    "layout": "flex-col | flex-row | grid",
    "gap": 8,
    "padding": { "top": 16, "right": 16, "bottom": 16, "left": 16 },
    "children": [
      { "type": "TEXT", "name": "Title", "style": "heading" },
      { "type": "FRAME", "name": "Content", "children": [...] },
      { "type": "COMPONENT_REF", "name": "Button", "refId": "existing-btn-id" }
    ]
  },
  "tokenDependencies": {
    "colors": ["Primary/500", "Neutral/100", "Neutral/900"],
    "typography": ["text-lg", "font-semibold", "text-sm"],
    "spacing": ["4", "8", "16", "24"],
    "borderRadius": ["md", "lg"]
  },
  "variants": {
    "variant": {
      "default": {
        "tokenOverrides": {
          "backgroundColor": "Neutral/100",
          "textColor": "Neutral/900"
        }
      },
      "highlighted": {
        "tokenOverrides": {
          "backgroundColor": "Primary/500",
          "textColor": "White"
        }
      }
    },
    "size": {
      "sm": { "tokenOverrides": { "padding": "8", "fontSize": "text-sm" } },
      "md": { "tokenOverrides": { "padding": "16", "fontSize": "text-base" } },
      "lg": { "tokenOverrides": { "padding": "24", "fontSize": "text-lg" } }
    }
  },
  "props": [
    { "name": "children", "type": "React.ReactNode", "required": true },
    { "name": "variant", "type": "'default' | 'highlighted'", "default": "'default'" },
    { "name": "size", "type": "'sm' | 'md' | 'lg'", "default": "'md'" },
    { "name": "className", "type": "string", "required": false }
  ],
  "interactiveStates": ["default", "hover", "active", "disabled"]
}
```

### Category Classification

Assign one of these categories based on component purpose:
- `button` - Clickable actions
- `card` - Content containers
- `input` - Form inputs, text fields
- `navigation` - Menus, tabs, breadcrumbs
- `layout` - Containers, grids, sections
- `feedback` - Alerts, toasts, badges
- `overlay` - Modals, dialogs, popovers
- `data` - Tables, lists, charts
- `form` - Form groups, fieldsets

### Structure Element Types

- `FRAME` - Container element (div)
- `TEXT` - Text content (p, span, h1-h6)
- `IMAGE` - Image element
- `COMPONENT_REF` - Reference to existing registry component
- `ICON` - Icon element (specify icon name)

---

## Part 3: Registry Integration

Generated components must be written to the Design Bridge registry structure.

### Output Locations

```
.design/
├── components/
│   └── {ComponentName}.json      # Raw component definition
├── componentRegistry.json         # Add entry here
└── tokens/                        # Reference existing tokens
```

### Registry Entry Format

Add to `.design/componentRegistry.json`:

```json
{
  "id": "nlp-{kebab-name}-{timestamp}",
  "name": "{ComponentName}",
  "source": {
    "type": "nlp-prompt",
    "extractedAt": "{ISO timestamp}"
  },
  "state": "IMPORTED",
  "category": "{category}",
  "filePaths": {
    "component": ".design/components/{ComponentName}.json"
  }
}
```

### Referencing Existing Components

Before generating, check the registry for existing components that could be referenced:

1. Read `.design/componentRegistry.json`
2. Identify components that could be children (e.g., Button, Icon, Avatar)
3. Use `COMPONENT_REF` type in structure to reference them
4. This maintains consistency and reduces duplication

### Component Reference Validation

When using `COMPONENT_REF`, always validate the reference exists:

```javascript
function validateComponentRef(refId, registry) {
  const component = registry.components.find(c => c.id === refId);

  if (!component) {
    console.warn(`Referenced component not found: ${refId}`);
    return {
      valid: false,
      error: `Component ${refId} does not exist in registry`,
      suggestions: findSimilarComponents(refId, registry)
    };
  }

  if (component.state !== 'TRANSFORMED') {
    console.warn(`Referenced component ${refId} is not TRANSFORMED`);
    return {
      valid: false,
      error: `Component ${refId} is ${component.state}, not TRANSFORMED`,
      suggestion: 'Run transformation first or use inline definition'
    };
  }

  return { valid: true, component };
}

function findSimilarComponents(refId, registry) {
  // Simple fuzzy match for suggestions
  const searchTerm = refId.toLowerCase().replace(/[^a-z]/g, '');
  return registry.components
    .filter(c => c.name.toLowerCase().includes(searchTerm) ||
                 c.id.toLowerCase().includes(searchTerm))
    .map(c => c.id)
    .slice(0, 3);
}

// Before finalizing component structure
function validateAllRefs(structure, registry) {
  const refs = findAllComponentRefs(structure);
  const errors = [];

  for (const ref of refs) {
    const result = validateComponentRef(ref.refId, registry);
    if (!result.valid) {
      errors.push({
        path: ref.path,
        refId: ref.refId,
        error: result.error,
        suggestions: result.suggestions
      });
    }
  }

  if (errors.length > 0) {
    console.error('Component reference validation failed:');
    errors.forEach(e => {
      console.error(`  - ${e.path}: ${e.error}`);
      if (e.suggestions?.length) {
        console.log(`    Did you mean: ${e.suggestions.join(', ')}?`);
      }
    });
    return false;
  }

  return true;
}
```

**Reference Error Handling**:

| Error | Cause | Resolution |
|-------|-------|------------|
| Component not found | Typo in refId or component deleted | Check spelling, use suggested alternatives |
| Component not TRANSFORMED | Referenced before code generation | Transform the component first |
| Circular reference | Component A refs B which refs A | Restructure to break cycle |
| Missing registry | Registry file doesn't exist | Initialize Design Bridge first |

### Token Alignment

Reference tokens from `.design/tokens/` when available:

1. Check `colors.json` for available color tokens
2. Check `typography.json` for font definitions
3. Check `spacing.json` for spacing scale
4. Use token names in `tokenDependencies`, not raw values

If tokens don't exist for your creative vision, document needed additions in the component's `tokenDependencies`.

---

## Part 4: Generation Workflow

### Step 1: Parse the Request

Extract from the natural language prompt:
- Component name (infer PascalCase name)
- Primary purpose and functionality
- Visual elements mentioned
- Variants or states implied
- Size considerations
- Any specific aesthetic direction

### Step 2: Check Existing Registry

Read `.design/componentRegistry.json` to:
- Avoid duplicating existing components
- Identify components to reference as children
- Understand the existing design language

### Step 3: Creative Design Phase

Apply bold aesthetic thinking:
- Choose distinctive typography
- Select a cohesive color approach
- Define spatial composition
- Plan motion and interaction

### Step 4: Build Component Definition

Create the full JSON structure:
- Unique ID with `nlp-` prefix
- Complete structure hierarchy
- Token dependencies
- Variants with overrides
- Props with TypeScript types
- Interactive states

### Step 5: Write to Registry (With Validation)

Before writing, perform safety checks:

```javascript
// 1. Validate ID uniqueness
function generateUniqueId(baseName) {
  const timestamp = Date.now();
  const candidateId = `nlp-${baseName.toLowerCase()}-${timestamp}`;

  // Check for collision
  const registry = JSON.parse(fs.readFileSync('.design/componentRegistry.json', 'utf-8'));
  const exists = registry.components.some(c => c.id === candidateId);

  if (exists) {
    // Add random suffix for uniqueness
    const suffix = Math.random().toString(36).substring(2, 6);
    return `nlp-${baseName.toLowerCase()}-${timestamp}-${suffix}`;
  }

  return candidateId;
}

// 2. Backup before write
function backupRegistry() {
  const registryPath = '.design/componentRegistry.json';
  const backupPath = '.design/componentRegistry.backup.json';

  if (fs.existsSync(registryPath)) {
    fs.copyFileSync(registryPath, backupPath);
    console.log('Registry backed up to componentRegistry.backup.json');
  }
}

// 3. Atomic write pattern
function writeRegistrySafely(newEntry) {
  const registryPath = '.design/componentRegistry.json';
  const tempPath = '.design/componentRegistry.tmp.json';

  // Backup first
  backupRegistry();

  // Read current
  let registry = { components: [] };
  if (fs.existsSync(registryPath)) {
    registry = JSON.parse(fs.readFileSync(registryPath, 'utf-8'));
  }

  // Validate new entry schema
  if (!validateComponentSchema(newEntry)) {
    throw new Error('Component schema validation failed');
  }

  // Add entry
  registry.components.push(newEntry);

  // Write to temp file first
  fs.writeFileSync(tempPath, JSON.stringify(registry, null, 2));

  // Validate JSON integrity
  try {
    JSON.parse(fs.readFileSync(tempPath, 'utf-8'));
  } catch (e) {
    fs.unlinkSync(tempPath);
    throw new Error('Registry write produced invalid JSON');
  }

  // Atomic rename
  fs.renameSync(tempPath, registryPath);
  console.log('Registry updated successfully');
}
```

**Write sequence**:
1. Generate unique ID with collision check
2. Backup existing registry
3. Write component JSON to `.design/components/{Name}.json`
4. Add entry to `.design/componentRegistry.json` atomically
5. Report what was created and where

**Error recovery**:
- If write fails, restore from `.design/componentRegistry.backup.json`
- If temp file exists on startup, previous write failed - prompt user to restore

### Step 6: Suggest Next Steps

After generation, suggest:
- Running transformation to generate framework code
- Creating additional variants if relevant
- Composing with other registry components

---

## Part 5: Creative Guidelines by Category

### Buttons
- Consider pill shapes vs sharp corners
- Add micro-interactions (scale, shadow lift on hover)
- Define clear state progression: default → hover → active → disabled
- Icon placement options (leading, trailing, icon-only)

### Cards
- Create visual hierarchy: media → header → content → actions
- Consider hover elevation changes
- Add subtle borders or shadows for depth
- Think about aspect ratios for media

### Inputs
- Design focus states that feel intentional
- Add label animations (floating labels)
- Consider helper text and error state styling
- Icon adornments (leading/trailing)

### Navigation
- Active state should be unmistakable
- Consider hover previews
- Mobile-first: how does it collapse?
- Add smooth transitions between states

### Feedback Components
- Color should convey meaning instantly
- Consider entry/exit animations
- Icon + text pairing for clarity
- Dismissibility patterns

---

## Part 6: Animation Specifications

When defining components, include animation intent:

### Entry Animations
```json
"animations": {
  "enter": {
    "type": "fade-up",
    "duration": 0.3,
    "ease": "power3.out"
  }
}
```

### Hover States
```json
"animations": {
  "hover": {
    "scale": 1.02,
    "y": -2,
    "shadow": "elevated",
    "transition": { "type": "spring", "stiffness": 400, "damping": 25 }
  }
}
```

### Recommended Patterns
- Buttons: scale + slight lift on hover
- Cards: shadow elevation on hover
- Inputs: border color transition on focus
- Feedback: slide-in from edge + fade

---

## Part 7: Anti-Patterns to Avoid

When generating components, NEVER:

- Default to Inter, Roboto, Arial, or system fonts
- Use purple gradients on white (overused AI aesthetic)
- Create generic, forgettable designs
- Ignore the existing registry's design language
- Generate components that duplicate existing registry entries
- Use raw color values instead of tokens
- Forget interactive states
- Skip motion considerations

---

## Part 8: Example Generations

### Example 1: Simple Request
**Prompt**: "Create a testimonial card"

**Creative Response**:
- Choose editorial aesthetic with serif typography
- Large quotation mark as visual anchor
- Subtle cream background with warm shadows
- Author info with small avatar
- Hover: slight rotation + shadow lift

### Example 2: Detailed Request
**Prompt**: "Generate a pricing card with plan name, price, feature list, and CTA button"

**Creative Response**:
- Bold geometric style with sharp corners
- Plan name in distinctive display font
- Price with large numerals, small period text
- Features with custom checkmark icons
- CTA button references existing registry Button component
- "Popular" badge variant with accent color
- Hover: entire card lifts with shadow

### Example 3: Abstract Request
**Prompt**: "I need a component for showing user stats"

**Creative Response**:
- Dashboard-style with data visualization feel
- Large metric number with subtle animation on load
- Trend indicator (up/down arrow with color)
- Sparkline or mini chart area
- Label with muted secondary color
- Grid-ready: designed to sit alongside siblings

---

## Implementation Checklist

Before finalizing any generated component:

- [ ] Unique ID with `nlp-` prefix and timestamp
- [ ] PascalCase name derived from description
- [ ] Appropriate category assigned
- [ ] Structure defines complete element hierarchy
- [ ] Token dependencies reference existing tokens where possible
- [ ] At least one variant defined beyond default
- [ ] Props include TypeScript types
- [ ] Interactive states specified
- [ ] Animation intent documented
- [ ] Checked registry for existing components to reference
- [ ] Output written to correct `.design/` paths
- [ ] Registry entry added to componentRegistry.json
- [ ] Design is distinctive and memorable, not generic

---

## Related Plugins & Coordination

### Plugin Ecosystem Overview

| Plugin | Purpose | When to Use |
|--------|---------|-------------|
| **bumba-nlp-design** (this) | Generate components | "Create a new card component", "I need a modal" |
| **bumba-frontend-design** | Build interfaces | "Build this page", "implement this component" |
| **bumba-explore-ui** | Visual exploration | "Show me design options", "explore visual directions" |
| **bumba-explore-ux** | Interaction exploration | "Explore user flows", "how should users navigate" |

### Handoff Patterns

**After Generation → Frontend Design**

After creating a component, hand off for use:

```json
{
  "workflow": "nlp-design → frontend-design",
  "handoff": {
    "generatedComponent": "ProductCard",
    "registryId": "nlp-product-card-1699999999999",
    "componentPath": ".design/components/ProductCard.json",
    "registryEntry": ".design/componentRegistry.json"
  },
  "nextStep": "Transform to framework code, then use in compositions"
}
```

**During Exploration → Return to Explore**

If called from an exploration plugin:

```json
{
  "workflow": "explore-ui → nlp-design → explore-ui",
  "handoff": {
    "requestedBy": "bumba-explore-ui",
    "missingComponent": "FeatureCard",
    "returnTo": "continue UI exploration with new component"
  }
}
```

### When to Switch Plugins

| Situation | Switch To | Reason |
|-----------|-----------|--------|
| Component generated, needs transformation | frontend-design | Transform and use |
| User wants to see component in context | explore-ui | Explore visual options |
| User describes a complex page | frontend-design | Composition, not generation |
| User wants to explore flows | explore-ux | UX decisions first |

### Integration with Registry

After generating a component:
1. Component JSON written to `.design/components/`
2. Registry entry added to `.design/componentRegistry.json`
3. Status set to `IMPORTED` (not yet transformed to code)
4. Next step: Run transformation for target framework

Other plugins can then:
- Reference via `COMPONENT_REF` in structures
- Import from `outputPaths` after transformation
- Use in explorations and compositions

---

## Troubleshooting

### "Component registry not found"

1. Initialize Design Bridge: Run `/design-init`
2. Create manually: `mkdir -p .design && echo '{"components":[]}' > .design/componentRegistry.json`
3. Ensure `.design/` directory has write permissions

### "ID collision detected"

1. Timestamps usually prevent this
2. If collision occurs, random suffix is added automatically
3. Check for duplicate generation requests
4. Clean up old components if registry is cluttered

### "Component reference not found"

1. Verify refId matches exactly (case-sensitive)
2. Check component exists in registry: `cat .design/componentRegistry.json | grep refId`
3. Look for suggested alternatives in error message
4. Use inline definition instead of reference if needed

### "Registry write failed"

1. Check `.design/` directory exists and is writable
2. Look for `.design/componentRegistry.tmp.json` - indicates interrupted write
3. Restore from `.design/componentRegistry.backup.json` if available
4. Validate JSON manually: `cat .design/componentRegistry.json | jq .`

### "Token not found"

1. Check token files exist in `.design/tokens/`
2. Verify token name matches exactly
3. Document new tokens in component's `tokenDependencies`
4. Create missing tokens or use fallback values

### "Schema validation failed"

1. Check component JSON structure matches expected format
2. Verify all required fields are present
3. Validate JSON syntax: `cat component.json | jq .`
4. Compare against example in Part 2 of this skill

### "Generated code won't compile"

1. Run transformation after generation to get framework code
2. Check TypeScript types are valid
3. Verify all imports resolve correctly
4. Check for syntax errors in generated component

---

Remember: You are the designer when generating from natural language. Don't just translate descriptions literally - interpret them creatively and produce something worth remembering. Every component should feel intentionally designed, not algorithmically assembled.

---
name: bumba-frontend-design
description: Use this skill whenever working with the Bumba Design Bridge system to create frontend interfaces. Triggers when: building pages or screens, composing layouts, creating UI with extracted components, designing dashboards or landing pages, working with .design/ directory, using componentRegistry or layoutManifest, or when the user mentions Design Bridge, Bumba, or asks for distinctive/memorable design. Produces bold, production-grade code using registry components, tokens, and layouts.
license: Complete terms in LICENSE.txt
---

This skill guides creation of distinctive, production-grade frontend interfaces using the Bumba Design Bridge system. It combines bold aesthetic principles with deep awareness of your component registry, layout manifest, and design tokens to produce memorable, cohesive designs.

**WHEN TO USE THIS SKILL**: Activate this skill whenever you detect:
- Work involving the `.design/` directory structure
- References to Design Bridge, Bumba, or component/layout registries
- Requests to build pages, screens, dashboards, or landing pages
- Composing multiple components into layouts
- Need for distinctive, memorable, or high-quality frontend design
- Questions about using extracted or transformed components

The user provides frontend requirements: a component, page, application, or interface to build. They may include context about the purpose, audience, or technical constraints.

---

## Part 1: Design Bridge System Awareness

Before designing, understand what's available to work with across three registries: **components**, **tokens**, and **layouts**.

### Directory Structure

Design Bridge maintains a comprehensive structure:

```
.design/
├── config.json               # Project configuration (framework, settings)
├── componentRegistry.json    # Master registry of all components
├── layoutManifest.json       # Registry of all extracted layouts
├── tokens/                   # Design tokens
│   ├── colors.json          # Color palette and semantic colors
│   ├── typography.json      # Font families, sizes, weights
│   └── spacing.json         # Spacing scale
├── components/               # Raw component data from extraction
├── layouts/                  # Extracted layout compositions
│   └── [layout-name]/
│       ├── layout.json      # Layout structure (flex, grid, spacing)
│       └── screenshot.png   # Visual reference from Figma
├── extracted-code/           # Transformed framework code
│   └── react/               # (or vue, angular, svelte, etc.)
│       ├── Button.tsx
│       ├── Card.tsx
│       └── layouts/
│           └── LoginScreen.tsx
└── stories/                  # Generated Storybook stories
```

### Component Registry

Read `.design/componentRegistry.json` to discover available components:

```json
{
  "components": [
    {
      "id": "figma-btn-123",
      "name": "PrimaryButton",
      "source": { "type": "figma" },
      "state": "TRANSFORMED",
      "transformedTo": ["react"],
      "outputPaths": {
        "react": ".design/extracted-code/react/PrimaryButton.tsx"
      },
      "variants": ["primary", "secondary", "ghost"]
    }
  ]
}
```

**Component States**:
- `IMPORTED` - Raw design data extracted, not yet transformed to code
- `TRANSFORMED` - Code generated for target framework(s)

**Component Sources**:
- **Figma** (`source.type: "figma"`) - Extracted from Figma designs
- **ShadCN** (`source.type: "shadcn"`) - Extracted from ShadCN registry
- **NLP** (`source.type: "nlp-prompt"`) - Generated from natural language descriptions
- **Manual** (`source.type: "manual"`) - Manually specified

### Layout Registry

Read `.design/layoutManifest.json` to discover extracted layouts:

```json
{
  "layouts": [
    {
      "name": "LoginScreen",
      "status": "code-generated",
      "source": { "type": "figma", "nodeId": "123:456" },
      "dimensions": { "width": 1440, "height": 900 },
      "componentsUsed": ["PrimaryButton", "TextField", "Logo"],
      "outputPath": ".design/extracted-code/react/layouts/LoginScreen.tsx"
    }
  ]
}
```

**Layout Stages**:
1. `extracted` - Layout JSON and screenshot captured from Figma
2. `html-generated` - Reference HTML created
3. `validated` - Visual validation completed against Figma screenshot
4. `code-generated` - Final framework code produced

Each layout folder contains:
- `layout.json` - Structure data (flex direction, gap, padding, alignment, component refs)
- `screenshot.png` - Visual reference from Figma for comparison

### Token Registry

Read tokens from `.design/tokens/` for design consistency:

**Colors** (`.design/tokens/colors.json`):
```json
{
  "primary": { "500": "#3B82F6", "600": "#2563EB" },
  "neutral": { "100": "#F3F4F6", "900": "#111827" },
  "semantic": { "success": "#10B981", "error": "#EF4444" }
}
```

**Typography** (`.design/tokens/typography.json`):
```json
{
  "fontFamilies": { "display": "Playfair Display", "body": "Source Sans Pro" },
  "fontSizes": { "xs": "12px", "sm": "14px", "base": "16px", "lg": "18px" },
  "fontWeights": { "normal": 400, "medium": 500, "bold": 700 }
}
```

**Spacing** (`.design/tokens/spacing.json`):
```json
{
  "scale": { "1": "4px", "2": "8px", "4": "16px", "6": "24px", "8": "32px" }
}
```

### Registry Access & Error Handling

Before using registry assets, verify they exist and are valid:

```javascript
// Check registry exists
const registryPath = '.design/componentRegistry.json';
if (!fs.existsSync(registryPath)) {
  console.warn('Component registry not found. Run /design-init or extract components first.');
  // Fallback: Create minimal registry or prompt user
}

// Parse with error handling
let registry;
try {
  const content = fs.readFileSync(registryPath, 'utf-8');
  registry = JSON.parse(content);
} catch (error) {
  if (error instanceof SyntaxError) {
    console.error(`Registry JSON parse error: ${error.message}`);
    // Show line number if possible, suggest fix
  }
  throw error;
}

// Validate structure
if (!registry.components || !Array.isArray(registry.components)) {
  console.error('Invalid registry structure: missing components array');
  // Provide fallback or prompt user
}
```

**Registry Error Scenarios**:

| Error | Cause | Resolution |
|-------|-------|------------|
| File not found | Design Bridge not initialized | Run `/design-init` or create manually |
| Parse error | Malformed JSON | Check syntax, validate with JSON linter |
| Empty registry | No components extracted | Extract from Figma or generate with NLP |
| Missing fields | Partial extraction | Re-run extraction or add missing fields |

### Using Registry Assets

When composing interfaces:

1. **Check component registry first** - Prefer existing components over creating new ones
2. **Import from correct paths** - Use `.design/extracted-code/{framework}/{ComponentName}`
3. **Reference layouts for composition** - Use layout JSON as spatial blueprints
4. **Apply design tokens** - Use token values for colors, typography, spacing
5. **Respect component variants** - Check what variants are available (primary, secondary, etc.)
6. **Verify transformation status** - Only use components that are `TRANSFORMED` to your target framework

### Handling Component States

Components may be in different states. Handle each appropriately:

```javascript
function getUsableComponent(componentId, targetFramework) {
  const component = registry.components.find(c => c.id === componentId);

  if (!component) {
    console.warn(`Component ${componentId} not found in registry`);
    return null;
  }

  switch (component.state) {
    case 'TRANSFORMED':
      if (component.transformedTo.includes(targetFramework)) {
        return component.outputPaths[targetFramework];
      }
      console.warn(`Component ${component.name} not transformed to ${targetFramework}`);
      console.log(`Available frameworks: ${component.transformedTo.join(', ')}`);
      console.log('Run transformation or use bumba-nlp-design to generate');
      return null;

    case 'IMPORTED':
      console.warn(`Component ${component.name} is IMPORTED but not TRANSFORMED`);
      console.log('Options:');
      console.log('  1. Run transformation to generate code');
      console.log('  2. Use bumba-nlp-design to generate from description');
      console.log('  3. Skip this component and use alternative');
      return null;

    default:
      console.error(`Unknown component state: ${component.state}`);
      return null;
  }
}
```

**Component State Handling**:

| State | Can Use? | Action Required |
|-------|----------|-----------------|
| `TRANSFORMED` (matching framework) | Yes | Import directly |
| `TRANSFORMED` (different framework) | No | Run transform for target framework |
| `IMPORTED` | No | Transform or regenerate |
| Unknown | No | Investigate and fix registry |

---

## Part 2: Design Thinking

Before coding, understand the context and commit to a BOLD aesthetic direction:

- **Purpose**: What problem does this interface solve? Who uses it?
- **Tone**: Pick an extreme: brutally minimal, maximalist chaos, retro-futuristic, organic/natural, luxury/refined, playful/toy-like, editorial/magazine, brutalist/raw, art deco/geometric, soft/pastel, industrial/utilitarian, etc.
- **Constraints**: Technical requirements (framework, performance, accessibility)
- **Differentiation**: What makes this UNFORGETTABLE? What's the one thing someone will remember?
- **Available Components**: What's in the Design Bridge registry that can be leveraged?

**CRITICAL**: Choose a clear conceptual direction and execute it with precision. Bold maximalism and refined minimalism both work - the key is intentionality, not intensity.

Then implement working code that is:
- Production-grade and functional
- Visually striking and memorable
- Cohesive with a clear aesthetic point-of-view
- Meticulously refined in every detail
- Built using available Design Bridge components where possible

---

## Part 3: Typography & Hierarchy

### Font Selection Philosophy

Choose fonts that are beautiful, unique, and interesting. Avoid generic fonts like Arial, Inter, and Roboto. Opt for distinctive choices that elevate the interface's aesthetics.

**Font Pairing Strategy**:
- **Display font**: Bold, characterful choice for headlines and hero text
- **Body font**: Refined, highly readable complement
- **Accent font** (optional): For special elements like quotes, callouts, or navigation

### Typographic Hierarchy

Establish a clear visual hierarchy with intentional scale relationships:

| Level | Purpose | Characteristics |
|-------|---------|-----------------|
| **Display** | Hero headlines, major section titles | Largest, most distinctive, commands attention |
| **H1** | Page titles | Bold presence, sets the tone |
| **H2** | Section headers | Clear demarcation, introduces new contexts |
| **H3** | Subsection headers | Supports H2, groups related content |
| **Body Large** | Lead paragraphs, emphasis | Slightly elevated for importance |
| **Body** | Main content | Optimized for extended reading |
| **Caption** | Labels, metadata, timestamps | Subtle, supportive, never competing |

### Scale Relationships

Use intentional ratios between type sizes:
- **Major Third (1.25)**: Subtle, refined progression
- **Perfect Fourth (1.333)**: Balanced, versatile
- **Golden Ratio (1.618)**: Dramatic, high-impact

### Typography Guidelines

- Line height for body text: 1.5-1.7 for readability
- Line height for headlines: 1.1-1.3 for tightness
- Paragraph max-width: 65-75 characters for optimal reading
- Letter-spacing: Slightly increased for uppercase, tight for large display text

---

## Part 4: Color & Theme

### Color Philosophy

Commit to a cohesive aesthetic. Dominant colors with sharp accents outperform timid, evenly-distributed palettes.

**Color Architecture**:
- **Primary**: The hero color, used sparingly for maximum impact
- **Secondary**: Supports primary, provides variety without competition
- **Neutral scale**: Grays/tones for backgrounds, borders, text hierarchy
- **Accent**: High-contrast pop for CTAs, alerts, key interactions
- **Semantic**: Success, warning, error states

### Theme Execution

Use CSS variables for consistency:

```css
:root {
  --color-primary: ...;
  --color-primary-hover: ...;
  --color-surface: ...;
  --color-surface-elevated: ...;
  --color-text-primary: ...;
  --color-text-secondary: ...;
  --color-text-muted: ...;
  --color-accent: ...;
  --color-border: ...;
}
```

### Color Guidelines

- Never use pure black (#000) or pure white (#FFF) - they're harsh
- Create depth with subtle surface elevation differences
- Ensure sufficient contrast ratios (WCAG AA minimum)
- Dark themes need careful attention to elevation and depth cues

---

## Part 5: Motion & Animation

### Animation Philosophy

Motion should feel intentional, not decorative. Focus on high-impact moments: one well-orchestrated page load with staggered reveals creates more delight than scattered micro-interactions.

### Animation Libraries

**GSAP (GreenSock Animation Platform)**:
- Use for complex timeline sequences
- Page transitions with multiple elements
- Scroll-triggered animations (ScrollTrigger)
- Physics-based motion (inertia, momentum)
- SVG morphing and path animations

```javascript
// GSAP timeline example
gsap.timeline()
  .from('.hero-title', { y: 100, opacity: 0, duration: 1, ease: 'power3.out' })
  .from('.hero-subtitle', { y: 50, opacity: 0, duration: 0.8 }, '-=0.6')
  .from('.cta-button', { scale: 0.8, opacity: 0, duration: 0.5 }, '-=0.4');
```

**Framer Motion (React)**:
- Use for component-level animations
- Layout animations and shared element transitions
- Gesture-based interactions (drag, hover, tap)
- Spring physics for natural feel
- AnimatePresence for enter/exit animations

```tsx
// Framer Motion example
<motion.div
  initial={{ opacity: 0, y: 20 }}
  animate={{ opacity: 1, y: 0 }}
  transition={{ type: 'spring', stiffness: 300, damping: 30 }}
  whileHover={{ scale: 1.02 }}
/>
```

### When to Use Each

| Scenario | Recommended Library |
|----------|---------------------|
| Page load orchestration | GSAP Timeline |
| Scroll-triggered reveals | GSAP ScrollTrigger |
| Component hover/tap states | Framer Motion |
| Layout shifts and reflows | Framer Motion |
| Complex SVG animations | GSAP |
| Drag and gesture interactions | Framer Motion |
| Shared element transitions | Framer Motion |

### Animation Patterns

**Staggered Reveals**: Elements enter sequentially with consistent delay
```javascript
// GSAP stagger
gsap.from('.card', {
  y: 40,
  opacity: 0,
  stagger: 0.1,
  duration: 0.6
});
```

**Scroll-Triggered Sections**: Content animates as it enters viewport
```javascript
// GSAP ScrollTrigger
gsap.from('.section', {
  scrollTrigger: { trigger: '.section', start: 'top 80%' },
  y: 60,
  opacity: 0,
  duration: 0.8
});
```

**Spring Physics**: Natural, organic feel for interactions
```tsx
// Framer Motion spring
transition={{ type: 'spring', stiffness: 400, damping: 25 }}
```

### Motion Guidelines

- Entrance animations: 0.3-0.8s depending on complexity
- Hover transitions: 0.15-0.25s for snappy feedback
- Page transitions: 0.4-0.6s for smooth flow
- Use easing curves: `power3.out`, `expo.out` for entrances; `power2.inOut` for transitions
- Respect `prefers-reduced-motion` for accessibility

---

## Part 6: Spatial Composition

### Layout Philosophy

Break free from predictable grids. Unexpected layouts create visual interest:

- **Asymmetry**: Off-center compositions create tension and interest
- **Overlap**: Elements that break boundaries add depth
- **Diagonal flow**: Guide the eye along unexpected paths
- **Grid-breaking elements**: Strategic rule-breakers draw attention
- **Generous negative space**: Breathing room elevates perceived quality

### Component Composition Patterns

When combining Design Bridge components into layouts:

**Rhythm & Repetition**: Establish visual patterns through consistent spacing and component reuse
```
[Card] --- [Card] --- [Card]
   gap: 24px   gap: 24px
```

**Progressive Disclosure**: Layer information from essential to detailed
```
Hero (immediate impact)
    ↓
Key Features (quick scan)
    ↓
Detailed Sections (engaged users)
    ↓
Supporting Content (deep dive)
```

**Visual Grouping**: Related components share proximity and styling
```
┌─────────────────────┐
│  [Icon]  [Title]    │  ← Grouped header
│  [Description]      │
│                     │
│  [Button] [Button]  │  ← Grouped actions
└─────────────────────┘
```

**Contrast & Focus**: Create clear focal points through size, color, or position

### Spacing System

Use a consistent spacing scale (e.g., 4px base):
- `4px` - Tight: related inline elements
- `8px` - Close: related stacked elements
- `16px` - Default: standard component spacing
- `24px` - Comfortable: section padding
- `32px` - Relaxed: major section separation
- `48px+` - Generous: dramatic separation

---

## Part 7: Backgrounds & Visual Details

### Creating Atmosphere

Move beyond solid color backgrounds. Add depth and character through:

- **Gradient meshes**: Soft, organic color transitions
- **Noise textures**: Subtle grain adds tactile quality
- **Geometric patterns**: Repeated shapes create rhythm
- **Layered transparencies**: Depth through overlapping translucent elements
- **Dramatic shadows**: Elevation and dimensionality
- **Decorative borders**: Frame and define spaces
- **Grain overlays**: Film-like texture for sophistication

### Background Techniques

```css
/* Gradient mesh */
background:
  radial-gradient(at 20% 30%, var(--color-accent) 0%, transparent 50%),
  radial-gradient(at 80% 70%, var(--color-primary) 0%, transparent 50%),
  var(--color-surface);

/* Noise texture overlay */
.textured::after {
  content: '';
  position: absolute;
  inset: 0;
  background-image: url('/noise.png');
  opacity: 0.03;
  pointer-events: none;
}

/* Geometric pattern */
background-image:
  linear-gradient(30deg, var(--pattern-color) 12%, transparent 12.5%),
  linear-gradient(150deg, var(--pattern-color) 12%, transparent 12.5%);
background-size: 60px 100px;
```

---

## Part 8: Micro-Interactions & Feedback

### Interaction States

Every interactive element needs clear state definition:

| State | Visual Treatment |
|-------|------------------|
| **Default** | Base appearance, inviting interaction |
| **Hover** | Subtle elevation, color shift, or scale |
| **Active/Pressed** | Slight depression, darker tone |
| **Focus** | Clear outline/ring for accessibility |
| **Disabled** | Reduced opacity, no pointer events |
| **Loading** | Spinner, skeleton, or progress indicator |
| **Success** | Confirmation color, checkmark animation |
| **Error** | Error color, shake animation, clear message |

### Micro-Interaction Patterns

**Button Feedback**:
```tsx
<motion.button
  whileHover={{ scale: 1.02, y: -2 }}
  whileTap={{ scale: 0.98 }}
  transition={{ type: 'spring', stiffness: 400, damping: 17 }}
/>
```

**Input Focus**:
```css
input:focus {
  outline: none;
  box-shadow: 0 0 0 3px var(--color-primary-alpha);
  border-color: var(--color-primary);
}
```

**Loading States**:
- Skeleton screens for content loading
- Spinner for action processing
- Progress bar for multi-step processes
- Optimistic UI for perceived speed

---

## Part 9: Responsive Design Thinking

### Adaptive Aesthetics

The aesthetic vision must translate across breakpoints without losing character:

**Mobile-First Principles**:
- Start with essential content and interactions
- Add complexity and visual richness as space allows
- Touch targets minimum 44px
- Consider thumb zones for navigation

**Breakpoint Strategy**:
```css
/* Mobile: 320px - 767px */
/* Tablet: 768px - 1023px */
/* Desktop: 1024px - 1439px */
/* Large: 1440px+ */
```

**Responsive Typography**:
```css
/* Fluid typography */
font-size: clamp(1rem, 0.5rem + 2vw, 1.5rem);
```

**Layout Adaptation**:
- Single column on mobile, multi-column on desktop
- Stack navigation on mobile, horizontal on desktop
- Simplify animations on mobile for performance
- Adjust spacing scale proportionally

---

## Part 10: Anti-Patterns to Avoid

NEVER use generic AI-generated aesthetics:

- **Overused fonts**: Inter, Roboto, Arial, system fonts
- **Cliched colors**: Purple gradients on white backgrounds
- **Predictable layouts**: Cookie-cutter component patterns
- **Safe convergence**: Don't gravitate toward common "default" choices
- **Decoration without purpose**: Random shapes, gratuitous gradients
- **Inconsistent systems**: Mix-and-match without cohesion

**Each design should be unique**. Vary between light and dark themes, different fonts, different aesthetics. Never converge on common choices across projects.

---

## Implementation Checklist

Before finalizing any interface:

- [ ] Checked Design Bridge registry for available components
- [ ] Imported transformed components from correct paths
- [ ] Established clear typographic hierarchy
- [ ] Committed to a cohesive color theme with CSS variables
- [ ] Added intentional motion with GSAP or Framer Motion
- [ ] Created spatial interest through composition
- [ ] Added atmospheric background details
- [ ] Defined all interaction states with micro-feedback
- [ ] Verified responsive behavior across breakpoints
- [ ] Avoided all anti-patterns listed above
- [ ] The design is distinctive and memorable

---

## Related Plugins & Coordination

### Plugin Ecosystem Overview

| Plugin | Purpose | When to Use |
|--------|---------|-------------|
| **bumba-frontend-design** (this) | Build interfaces | "Build this page", "implement this component" |
| **bumba-explore-ui** | Visual exploration | "Show me design options", "explore visual directions" |
| **bumba-explore-ux** | Interaction exploration | "Explore user flows", "how should users navigate" |
| **bumba-nlp-design** | Generate components | "Create a new card component", "I need a modal" |

### When to Switch Plugins

| Situation | Switch To | Reason |
|-----------|-----------|--------|
| User asks "what are my options?" | explore-ui | Need to explore before committing |
| User asks "how should this flow work?" | explore-ux | Need UX decisions before UI |
| Registry missing needed component | nlp-design | Generate before composing |
| User wants to compare layouts | explore-ui | Exploration, not implementation |

### Receiving Handoffs

**From UI Exploration**

When user selects a direction from explore-ui:

```json
{
  "receivedFrom": "bumba-explore-ui",
  "directionFile": ".design/explorations/ui/[id]/direction-2-refined.json",
  "implementation": {
    "components": ["Button", "Card", "Header"],
    "tokenApplications": { "primary": "colors.primary.600" },
    "motionIntent": { "entrance": "staggered-reveal" }
  }
}
```

Action: Use direction JSON as blueprint for implementation.

**From UX Exploration**

When user selects a UX direction:

```json
{
  "receivedFrom": "bumba-explore-ux",
  "flowType": "streamlined-linear",
  "pages": ["step-1", "step-2", "confirmation"],
  "navigationPattern": "progress-indicator"
}
```

Action: Build pages/routes according to flow specification.

**From NLP Design**

When a new component was generated:

```json
{
  "receivedFrom": "bumba-nlp-design",
  "newComponent": "ProductCard",
  "registryId": "nlp-product-card-1699999999999",
  "path": ".design/components/ProductCard.json"
}
```

Action: Transform component to framework code, then use in composition.

### Handing Off to Other Plugins

If user needs exploration during implementation:
1. Save current progress
2. Note which components/layouts are in progress
3. Suggest: "Would you like to explore visual options first? Use bumba-explore-ui."

---

## Troubleshooting

### "Component registry not found"

1. Initialize Design Bridge: Run `/design-init`
2. Extract from Figma: Use Figma plugin
3. Create manually: `mkdir -p .design && echo '{"components":[]}' > .design/componentRegistry.json`

### "Component is IMPORTED but not TRANSFORMED"

1. Run the transformation step for your target framework
2. Or use `bumba-nlp-design` to generate from description
3. Check if component has valid structure for transformation

### "Import path not found"

1. Verify component `outputPaths` in registry
2. Check if extracted code exists at path
3. Ensure transformation completed without errors
4. Re-run transformation if files are missing

### "Tokens not applying correctly"

1. Check token file exists in `.design/tokens/`
2. Verify token names match registry references
3. Ensure CSS variables are defined in root
4. Check for typos in token names (case-sensitive)

### "Layout not rendering correctly"

1. Check layout JSON structure in `.design/layouts/`
2. Verify all referenced components exist
3. Compare against screenshot.png for visual reference
4. Check flex/grid properties match layout intent

### "Animation not working"

1. Verify GSAP or Framer Motion is installed
2. Check animation library is imported correctly
3. Verify `prefers-reduced-motion` isn't blocking
4. Check browser console for animation errors

### "Responsive layout breaking"

1. Test at all breakpoints (320, 768, 1024, 1440+)
2. Verify media queries are correct
3. Check container max-width constraints
4. Use browser DevTools responsive mode

---

Remember: Claude is capable of extraordinary creative work. When using Design Bridge components, don't just assemble them generically - compose them into something memorable. Show what can truly be created when thinking outside the box and committing fully to a distinctive vision.

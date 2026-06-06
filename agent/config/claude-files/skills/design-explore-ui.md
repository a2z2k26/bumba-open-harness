---
name: design-explore-ui
description: Generate four divergent UI design directions in parallel E2B sandboxes using design-ui-template. Creates distinctive visual designs across conservative, refined, expressive, and experimental directions with Design Bridge system integration. Spawns design-visual-designer and design-ui-designer agents for each direction.
license: Complete terms in LICENSE.txt
---

# ⚡ IMMEDIATE EXECUTION MODE

**WHEN THIS SKILL IS INVOKED**: Immediately jump to "Orchestration Workflow - EXECUTE IMMEDIATELY" section and start executing. DO NOT read the entire skill first. DO NOT wait for permission. DO NOT explain what you're going to do. Just START EXECUTING the workflow steps.

The user invoked this skill to RUN the exploration, not to learn about it.

---

# E2B Template Configuration

**MANDATORY**: This skill ONLY uses the `design-ui-template` E2B sandbox.

- Template ID: 7k5wtd8ecoxz9bpvwa3l
- Contains: imagemagick, SVG tools, fonts, style-dictionary
- DO NOT use any other template

---

This skill guides creation of distinctive, production-grade frontend interfaces using the Bumba Design Bridge system. It combines bold aesthetic principles with deep awareness of your component registry, layout manifest, and design tokens to produce memorable, cohesive designs.

**VISUAL DESIGN FOCUS**: This skill specializes in visual/aesthetic aspects of design:
- Typography selection, hierarchy, and scale relationships
- Color theory, theme development, and palette cohesion
- Spatial composition, layout experimentation, and grid systems
- Visual atmosphere through backgrounds, textures, and details
- Micro-interactions and animation for visual polish

**4 UI DESIGN DIRECTIONS**:
This skill supports exploration across a conservative-to-experimental spectrum:
1. **Conservative**: Standard 12-column grid, conventional patterns, WCAG AA, semantic HTML
2. **Refined**: Enhanced grid with subtle variations, polished micro-interactions, elevated but predictable
3. **Expressive**: Intentional grid breaks, bold typography, dynamic spacing, strong visual personality
4. **Experimental**: Boundary-pushing layouts, unconventional navigation, dramatic effects, WCAG AA still required

**WHEN TO USE THIS SKILL**: Activate this skill whenever you detect:
- Work involving the `.design/` directory structure
- References to Design Bridge, Bumba, or component/layout registries
- Requests to build pages, screens, dashboards, or landing pages with visual emphasis
- Composing multiple components into layouts with aesthetic focus
- Need for distinctive, memorable, or high-quality frontend visual design
- Questions about using extracted or transformed components for visual composition
- UI design exploration requests across the 4-direction spectrum

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

### Using Registry Assets

When composing interfaces:

1. **Check component registry first** - Prefer existing components over creating new ones
2. **Import from correct paths** - Use `.design/extracted-code/{framework}/{ComponentName}`
3. **Reference layouts for composition** - Use layout JSON as spatial blueprints
4. **Apply design tokens** - Use token values for colors, typography, spacing
5. **Respect component variants** - Check what variants are available (primary, secondary, etc.)
6. **Verify transformation status** - Only use components that are `TRANSFORMED` to your target framework

---

## Part 2: Design Thinking

Before coding, understand the context and commit to a BOLD aesthetic direction:

- **Purpose**: What problem does this interface solve? Who uses it?
- **Tone**: Pick an extreme: brutally minimal, maximalist chaos, retro-futuristic, organic/natural, luxury/refined, playful/toy-like, editorial/magazine, brutalist/raw, art deco/geometric, soft/pastel, industrial/utilitarian, etc.
- **Constraints**: Technical requirements (framework, performance, accessibility)
- **Differentiation**: What makes this UNFORGETTABLE? What's the one thing someone will remember?
- **Available Components**: What's in the Design Bridge registry that can be leveraged?
- **Direction Alignment**: Which of the 4 UI directions (conservative, refined, expressive, experimental) does this align with?

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
- [ ] Direction aligns with intended spectrum position (conservative/refined/expressive/experimental)

---

## Direction-Specific Design Guidance

When agents are spawned for parallel exploration, use these direction-specific guidelines:

### Conservative Direction
**Philosophy**: Usability, accessibility, and predictability over visual creativity.

**Layout**:
- Strict 12-column grid with 8-point spacing system
- Predictable hierarchy with consistent spacing
- Conventional patterns (card grids, sidebars, top nav)
- Breakpoints: 640px, 768px, 1024px, 1280px

**Visual Treatment**:
- Minimal decoration, content-focused
- Subtle shadows (2dp, 4dp, 8dp maximum)
- System fonts or professional web-safe fonts
- Restrained color palette with high contrast
- Generous whitespace for comfortable reading

**Components**:
- Semantic HTML5 elements required
- Proper ARIA labels and roles
- Keyboard navigation fully supported
- Clear focus indicators
- Touch targets minimum 44×44px

**DO**: Standard grids, conventional nav, established libraries, WCAG AA minimum
**DON'T**: Break grid, experimental nav, low contrast, decorative hindrance

---

### Moderate Direction
**Philosophy**: Polished, elevated experience with subtle innovations.

**Layout**:
- Enhanced 12-column grid with intentional variations
- Refined hierarchy with dynamic spacing
- Familiar patterns with polished touches
- Smooth transitions between breakpoints

**Visual Treatment**:
- Refined decoration adds value
- Layered shadows (4dp, 8dp, 16dp)
- Professional fonts with personality
- Sophisticated color palette with brand essence
- Strategic whitespace creates rhythm

**Components**:
- Semantic HTML with enhanced interaction
- Comprehensive ARIA implementation
- Advanced keyboard navigation patterns
- Micro-interactions add polish
- Touch targets 48×48px for comfort

**DO**: Enhanced grids, refined nav, polished libraries, WCAG AAA target
**DON'T**: Pure conservatism, boring patterns, missed opportunities

---

### Progressive Direction
**Philosophy**: Modern, dynamic approach with intentional creativity.

**Layout**:
- Flexible grid system with intentional breaks
- Dynamic hierarchy responds to content
- Modern patterns (bento boxes, split sections)
- Fluid responsive with dramatic shifts

**Visual Treatment**:
- Bold decoration creates atmosphere
- Dynamic shadows (8dp, 16dp, 24dp)
- Distinctive typography as design element
- Vibrant color with gradients and shifts
- Whitespace creates tension and flow

**Components**:
- Semantic HTML with innovative patterns
- ARIA for complex interactions
- Advanced keyboard with shortcuts
- Animations enhance experience
- Touch targets 48×48px, hidden if tasteful

**DO**: Grid breaks, modern nav, custom patterns, WCAG AA maintained
**DON'T**: Inaccessibility, confusing nav, gratuitous animation

---

### Experimental Direction
**Philosophy**: Boundary-pushing while maintaining WCAG AA accessibility.

**Layout**:
- Break grid intentionally (asymmetric, diagonal, overlapping)
- Dynamic hierarchy shifts with interaction/scroll
- Unconventional patterns challenge norms
- Layouts morph dramatically between breakpoints

**Visual Treatment**:
- Dramatic decoration creates memorable moments
- Deep shadows, 3D effects, multiple light sources
- Experimental typography (oversized, kinetic)
- Adventurous color (unexpected combinations, bold gradients)
- Negative space as active design element

**Components**:
- Push boundaries while maintaining usability
- Interactive elements still discoverable
- Animations enhance, never hinder
- Experimental ≠ inaccessible
- Touch targets 44×44px minimum (can be hidden)

**DO**: Break conventions, dramatic effects, novel interactions, maintain AA
**DON'T**: Sacrifice usability, hide nav entirely, ignore accessibility

---

## Orchestration Mode: Parallel Design Exploration

**CRITICAL**: When this skill is invoked via `/design-explore-ui` command, you MUST immediately execute the orchestration workflow below. Do NOT wait for further instructions. Do NOT ask permission. Start execution immediately.

### Trigger Detection

You're in orchestration mode when:
- Command was `/design-explore-ui [request]`
- OR user explicitly asks to "explore UI directions"
- OR user mentions "4 design directions" or "conservative/refined/expressive/experimental"

If NOT in orchestration mode, follow regular single-direction design guidance above.

### Orchestration Workflow - EXECUTE IMMEDIATELY

**IMPORTANT**: Execute these steps sequentially without asking permission. Use TodoWrite to track progress.

#### Step 1: Validate Environment

**ACTION**: Execute these checks immediately:

1. **Check Git Status** - Run `git status --porcelain`:
   - If not empty: Inform user of uncommitted changes and continue (exploration won't modify main branch)

2. **Detect Framework** - Read package.json to identify React/Vue/Svelte/Angular:
   - Extract framework name and version
   - Default to React 18 if unclear

3. **Check Design Bridge** - Check for `.design/componentRegistry.json`:
   - If exists: Note "Design Bridge available"
   - If not: Note "Working without Design Bridge (fine for exploration)"

4. **Verify E2B** - Confirm E2B_API_KEY environment variable exists:
   - If missing: Stop and inform user to configure E2B
   - If present: Continue to Step 2

#### Step 2: Create Sandboxes in Parallel

**ACTION**: Call mcp__bumba-sandbox__sandbox_create four times simultaneously (use parallel tool calls):

For directions ['conservative', 'refined', 'expressive', 'experimental'], create sandboxes with:
- template: "design-ui-template"
- metadata: {direction: "<direction>", framework: "<detected>", timestamp: "<now>"}

Store the 4 sandbox IDs in variables: sandbox_conservative, sandbox_refined, sandbox_expressive, sandbox_experimental

#### Step 3: Create Git Worktrees

**ACTION**: Use Bash tool to create 4 git worktrees with timestamp branches:

```bash
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
git worktree add worktrees/ui-conservative -b ui-conservative-$TIMESTAMP
git worktree add worktrees/ui-refined -b ui-refined-$TIMESTAMP
git worktree add worktrees/ui-expressive -b ui-expressive-$TIMESTAMP
git worktree add worktrees/ui-experimental -b ui-experimental-$TIMESTAMP
```

Each direction gets an isolated git worktree on its own branch.

#### Step 4: Spawn Phase 1 Agents (Visual Designers)

**ACTION**: Use Task tool to spawn 4 design-visual-designer agents in parallel (run_in_background: true):

For each direction, spawn with this prompt template:
```
You are exploring the {DIRECTION} visual direction for: {USER_REQUEST}

🔧 SANDBOX ENVIRONMENT DETECTED:
- Sandbox ID: {SANDBOX_ID}
- Framework: {FRAMEWORK}
- E2B Template: design-ui-template
- Design Bridge: {AVAILABLE/NOT_AVAILABLE}

⚠️ CRITICAL - USE SANDBOX TOOLS ONLY:
You MUST use these sandbox MCP tools (regular tools will be auto-denied):
- mcp__bumba-sandbox__files_write(sandboxId: "{SANDBOX_ID}", path: "/tmp/...", content: "...")
- mcp__bumba-sandbox__files_read(sandboxId: "{SANDBOX_ID}", path: "/tmp/...")
- mcp__bumba-sandbox__make_directory(sandboxId: "{SANDBOX_ID}", path: "/tmp/...")

NEVER use: Write, Edit, Read, or Bash tools - they will fail in background mode.

Your Phase 1 Role:
1. Explore visual direction focusing on typography, color, spacing, atmosphere
2. Create /tmp/design-spec.json with your visual decisions using mcp__bumba-sandbox__files_write:

   Example call:
   mcp__bumba-sandbox__files_write({
     sandboxId: "{SANDBOX_ID}",
     path: "/tmp/design-spec.json",
     content: JSON.stringify({
       "direction": "{direction}",
       "typography": {"primary": "Clash Display", "body": "Inter", "scale": [14, 16, 20, 28, 40, 64]},
       "colors": {"primary": "#3B82F6", "accent": "#10B981", "background": "#FFFFFF", "text": "#111827"},
       "spacing": {"base": 8, "scale": [4, 8, 16, 24, 32, 48, 64]},
       "shadows": ["0 1px 2px rgba(0,0,0,0.05)", "0 4px 6px rgba(0,0,0,0.1)"],
       "atmosphere": "Clean, modern, professional with vibrant accent colors"
     })
   })

3. Write completion marker using mcp__bumba-sandbox__files_write:
   mcp__bumba-sandbox__files_write({
     sandboxId: "{SANDBOX_ID}",
     path: "/tmp/phase1_complete.md",
     content: "Phase 1 visual exploration complete for {DIRECTION} direction"
   })

Direction-Specific Guidance for {DIRECTION}:
{INSERT GUIDANCE FROM "Direction-Specific Design Guidance" SECTION ABOVE}

Remember: You are in a background sandbox. Write files directly without asking permission.
```

Store the 4 agent task IDs for monitoring.

#### Step 5: Monitor Phase 1 and Spawn Phase 2

**ACTION**: Monitor for phase1_complete.md in each sandbox using mcp__bumba-sandbox__file_exists:

```
Check every 30 seconds:
For each sandbox_id:
  result = mcp__bumba-sandbox__file_exists(sandbox_id, "/tmp/phase1_complete.md")
  if result AND phase2_not_yet_spawned:
    spawn Phase 2 agent for this direction
```

When phase1_complete.md detected, **immediately** spawn Phase 2 agent (design-ui-designer) with prompt:
```
You are implementing the {DIRECTION} UI direction for: {USER_REQUEST}

🔧 SANDBOX ENVIRONMENT DETECTED:
- Sandbox ID: {SANDBOX_ID}
- Framework: {FRAMEWORK}
- E2B Template: design-ui-template
- Phase 1 Complete: /tmp/design-spec.json contains visual decisions

⚠️ CRITICAL - USE SANDBOX TOOLS ONLY:
You MUST use these sandbox MCP tools (regular tools will be auto-denied):
- mcp__bumba-sandbox__files_read(sandboxId: "{SANDBOX_ID}", path: "/tmp/design-spec.json")
- mcp__bumba-sandbox__files_write(sandboxId: "{SANDBOX_ID}", path: "/tmp/output/...", content: "...")
- mcp__bumba-sandbox__make_directory(sandboxId: "{SANDBOX_ID}", path: "/tmp/output/src")
- mcp__bumba-sandbox__execute_command(sandboxId: "{SANDBOX_ID}", command: "...")

NEVER use: Write, Edit, Read, or Bash tools - they will fail in background mode.

Your Phase 2 Role:

1. Read the design spec from Phase 1:
   const spec = await mcp__bumba-sandbox__files_read({
     sandboxId: "{SANDBOX_ID}",
     path: "/tmp/design-spec.json"
   })

2. Create directory structure:
   await mcp__bumba-sandbox__make_directory({
     sandboxId: "{SANDBOX_ID}",
     path: "/tmp/output/src/components"
   })

3. Implement production-grade {FRAMEWORK} code following the design spec
   - Write components to /tmp/output/src/components/
   - Write styles to /tmp/output/src/styles/
   - Write main page/app to /tmp/output/src/

   Example:
   await mcp__bumba-sandbox__files_write({
     sandboxId: "{SANDBOX_ID}",
     path: "/tmp/output/src/App.tsx",
     content: `import React from 'react';

     export default function App() {
       // Your implementation using design spec
       return <div>...</div>;
     }`
   })

4. Write completion marker:
   await mcp__bumba-sandbox__files_write({
     sandboxId: "{SANDBOX_ID}",
     path: "/tmp/phase2_complete.md",
     content: "Phase 2 implementation complete for {DIRECTION} direction\n\nFiles created:\n- /tmp/output/src/App.tsx\n- /tmp/output/src/components/..."
   })

Quality Requirements:
- Production-ready, clean code (no TODOs, no placeholders)
- Responsive design (mobile-first)
- WCAG AA accessibility minimum
- Real content (no "Lorem ipsum")
- Complete implementation
- All files in /tmp/output/ directory

Remember: You are in a background sandbox. Write files directly without asking permission.
```

Continue monitoring until all 4 sandboxes have phase2_complete.md

#### Step 6: Sync Files to Worktrees

**ACTION**: When phase2_complete.md exists, sync files from sandbox to worktree:

For each completed sandbox:
1. List files: `mcp__bumba-sandbox__files_list(sandboxId, "/tmp/output")`
2. For each file in the list:
   - Read: `mcp__bumba-sandbox__files_read(sandboxId, "/tmp/output/{file}")`
   - Write: `Write("worktrees/ui-{direction}/{file}", content)`
3. Inform user: "✅ {Direction} files synced to worktrees/ui-{direction}/"

Repeat for all 4 directions as they complete.

#### Step 7: Present Results and Cleanup

**ACTION**: Once all 4 directions are synced, present summary:

```markdown
✅ UI Design Exploration Complete!

Generated 4 design directions for: <USER_REQUEST>

📁 Results Location:
  worktrees/ui-conservative/     → Standard patterns, WCAG AA
  worktrees/ui-refined/          → Polished, elevated experience
  worktrees/ui-expressive/       → Bold, strong personality
  worktrees/ui-experimental/     → Boundary-pushing, dramatic

🔍 Next Steps:
1. Review each direction:
   cd worktrees/ui-conservative && npm install && npm run dev

2. Test the implementations
3. Choose your preferred direction (or hybrid elements)
4. Merge to main:
   git checkout main
   git merge ui-conservative  # (or whichever you chose)

5. Cleanup worktrees:
   git worktree remove worktrees/ui-conservative
   # (repeat for others)

💡 Observations:
- Conservative: <1-sentence summary>
- Refined: <1-sentence summary>
- Expressive: <1-sentence summary>
- Experimental: <1-sentence summary>
```

### Error Handling

**If sandbox creation fails**:
- Continue with remaining sandboxes
- Report which direction failed
- Offer to retry failed direction

**If agent fails or times out**:
- Mark direction as incomplete
- Preserve sandbox for debugging
- Provide sandbox ID for manual inspection

**If git worktree creation fails**:
- Check for existing worktrees: `git worktree list`
- Suggest cleanup: `git worktree prune`
- Retry worktree creation

**If file sync fails**:
- Keep sandbox alive for manual sync
- Provide commands for manual file retrieval:
  ```bash
  mcp__bumba-sandbox__files_download(sandboxId, "/tmp/output/", "./backup/")
  ```

### Cleanup

After successful exploration:
1. **Sandboxes**: Destroy completed sandboxes to save costs
   ```
   For each sandbox_id:
     mcp__bumba-sandbox__sandbox_kill(sandboxId)
   ```

2. **Worktrees**: Preserved for user review (user manually removes later)

3. **Branches**: Preserved on worktree branches (user merges/deletes later)

---

Remember: Claude is capable of extraordinary creative work. When using Design Bridge components, don't just assemble them generically - compose them into something memorable. Show what can truly be created when thinking outside the box and committing fully to a distinctive vision.

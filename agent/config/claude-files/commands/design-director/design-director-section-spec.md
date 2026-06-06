---
name: design-director-section-spec
description: Define user flows, UI requirements, and data for a specific section
---

You are helping the user specify a section - defining user flows, UI requirements, and data needs for a specific feature area.

## Prerequisites Check

1. Verify `product-roadmap.md` exists (need sections list)
   - Path: `.design/bumba-design-director/product/product-roadmap.md`
   - If NOT found: Display error and suggest running `/director-roadmap` first

2. Load available sections from roadmap

## Step 1: Select Section

Display available sections from roadmap:

```
Which section would you like to specify?

Available sections:
1. [Section 1 Title] (id: section-1)
2. [Section 2 Title] (id: section-2)
3. [Section 3 Title] (id: section-3)

Enter section ID or number:
```

Get user selection:
- Store as: `sectionId`
- Validation: Must be a valid section ID from roadmap

Check if section spec already exists:
- Path: `.design/bumba-design-director/product/sections/[sectionId]/spec.md`
- If found: Ask "Specification for [sectionTitle] already exists. Update it?"
  - If no: Exit gracefully
  - If yes: Continue (will overwrite)

## Step 2: Load Context

Load section details from roadmap and Bumba components:

```javascript
const { getBumbaContext } = require('./.design/bumba-design-director/lib/bumba-reader.js');
const bumbaContext = getBumbaContext();

// Show section title and description from roadmap for context
console.log(`
Specifying section: ${sectionTitle}
${sectionDescription}
`);
```

## Step 3: Consult Specification Writing Skill

Read the specification writing skill:

Path: `.design/bumba-design-director/.claude/skills/specification-writing/SKILL.md`

## Step 4: Gather User Flows

Explain user flows:

```
User flows describe what users DO in this section - step-by-step sequences.

Examples:
✓ "User views product list → clicks product → sees details → adds to cart"
✓ "User navigates to settings → changes password → receives confirmation"

Focus on user actions and system responses, not UI specifics.
```

**Question: User Flows**
"What are the main user flows in [SectionName]? Describe 2-5 key flows step-by-step."

Ask conversationally and let user describe naturally. Parse their descriptions into structured flows.

Example user input:
"Users can browse products, filter by category, search, and view details of individual products"

Parse to:
```
User Flows:
1. Browse Products
   - User lands on product list
   - User sees all products with images and prices
   - User scrolls through paginated list

2. Filter Products
   - User selects category from filter
   - List updates to show only matching products
   - User can clear filters to see all again

3. Search Products
   - User enters search term
   - Results filter in real-time
   - User clicks result to view details

4. View Product Details
   - User clicks a product card
   - Detail page shows full product info
   - User can add to cart from details
```

- Store as: `userFlows` (multi-line markdown string)
- Validation: At least 1 flow described

## Step 5: Gather UI Requirements

Explain UI requirements:

```
UI requirements describe WHAT screens/views are needed, not HOW they look.

Examples:
✓ "Product list view with grid layout, search bar, and category filters"
✓ "Product detail view showing images, description, price, and add-to-cart button"

NOT:
✗ "Blue buttons with rounded corners" (that's design aesthetic)
✗ "18px font for titles" (that comes from Bumba tokens)
```

**Question: UI Requirements**
"What screens or views are needed for [SectionName]? Describe the key UI elements and their purpose."

Let user describe naturally. Help structure their input.

Example user input:
"Need a main list page with product cards, a detail page, search and filters"

Parse to:
```
UI Requirements:

1. Product List View
   - Grid of product cards
   - Each card shows: image, name, price
   - Search bar at top
   - Category filter sidebar
   - Pagination controls

2. Product Detail View
   - Hero image carousel
   - Product name and description
   - Price display
   - Add to cart button
   - Related products section

3. Search & Filter Controls
   - Real-time search input
   - Category checkboxes
   - Price range slider
   - Clear filters button
```

- Store as: `uiRequirements` (multi-line markdown string)
- Validation: At least 1 UI requirement described

## Step 6: Optional Data Requirements

Ask if user wants to specify data requirements:

**Question: Data Requirements** (Optional)
"What data does this section need? (You can specify this, or we'll reference the data model)"

If user wants to specify:
- Ask for entities involved (e.g., "Product, Category")
- Ask for specific fields needed
- Store as: `dataRequirements` (string)

If user skips:
- Set `dataRequirements` to null
- Template will use default: "See types.ts and data.json"

## Step 7: Check for Bumba Components

If components are available, show them:

```javascript
if (bumbaContext.hasComponents) {
  console.log(`
✓ Bumba components detected

Available components from .design/components/:
${bumbaContext.components.map(c => `- ${c.name} (${c.type})`).join('\n')}

Your section spec will reference these for implementation.
  `);

  // Optionally ask user which components are relevant for this section
}
```

If NOT available:

```
Note: No Bumba components found yet

Your section spec will include guidance for creating components.
Use Bumba Design features to extract components from Figma when ready.
```

## Step 8: Generate Section Specification

Use the spec-generator utility:

```javascript
const { generateSectionSpec } = require('./.design/bumba-design-director/lib/spec-generator.js');

const data = {
  sectionName: sectionTitle,
  userFlows: "...", // Multi-line markdown
  uiRequirements: "...", // Multi-line markdown
  dataRequirements: "..." || null // Optional
};

// generateSectionSpec uses section-spec.md.tmpl template which references:
// - bumbaComponentsAvailable (boolean)
// - bumbaComponents (array) - from bumbaContext.components

const outputPath = generateSectionSpec(sectionId, data, bumbaContext);
```

## Step 9: Display Preview

Show preview of generated spec:

```
Generated: sections/[sectionId]/spec.md

Section: [SectionName]

User Flows: [N] flows defined
UI Requirements: [N] screens/views specified
Data Requirements: [Specified / See types.ts]

[If Bumba components available:]
✓ References [N] Bumba components

Preview:
─────────────────────────────────────
[Display first 30-40 lines]
─────────────────────────────────────

Full specification saved to:
.design/bumba-design-director/product/sections/[sectionId]/spec.md
```

## Step 10: Next Steps

Display next steps:

```
Section specification complete! ✓

Next steps for this section:

→ /director-sample-data [sectionId] to create sample data
→ /director-screen-spec [sectionId] to add detailed screen specifications

Or specify another section:
→ /director-section-spec
```

## Error Handling

**Missing Roadmap:**
```
Error: product-roadmap.md not found

You need to define sections first.

→ Run /director-roadmap to create sections
→ Then run /director-section-spec again
```

**Invalid Section ID:**
```
Error: Section "[sectionId]" not found in roadmap

Available sections:
- section-1
- section-2
- section-3

Please enter a valid section ID.
```

**No User Flows:**
```
Error: At least 1 user flow is required

User flows describe what users DO in this section.

Let's try again...
```

**No UI Requirements:**
```
Error: At least 1 UI requirement is needed

UI requirements describe the screens/views needed.

Let's try again...
```

**File Write Failure:**
```
Error: Failed to write section spec

→ Check permissions in .design/bumba-design-director/product/sections/
→ Directory will be created automatically if missing
```

## Implementation Notes

- Create sections/[sectionId]/ directory if it doesn't exist
- Help user structure natural language into organized flows
- Distinguish between user flows (actions) and UI requirements (screens)
- Reference Bumba components if available
- Show section context (title, description from roadmap)
- Allow user to skip data requirements (will use data model reference)
- Display available sections clearly with both ID and title
- Accept section number or ID as input
- Validate section exists before proceeding
- Show preview of generated spec for confirmation

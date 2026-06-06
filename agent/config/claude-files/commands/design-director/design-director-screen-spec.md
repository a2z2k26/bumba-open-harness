---
name: design-director-screen-spec
description: Add detailed screen specifications to a section
---

You are helping the user add detailed screen-level specifications to a section - describing WHAT screens do, not HOW they look.

## Prerequisites Check

1. Verify section spec exists
   - Path: `.design/bumba-design-director/product/sections/[sectionId]/spec.md`
   - If NOT found: Display error and suggest running `/director-section-spec [sectionId]` first

2. Check if sample data exists (optional but helpful)
   - Path: `.design/bumba-design-director/product/sections/[sectionId]/data.json`
   - If found: Load and show relevant data types
   - If not found: Continue without sample data context

## Step 1: Load Context

Load section spec and optional sample data:

```javascript
const fs = require('fs');
const sectionSpecPath = `.design/bumba-design-director/product/sections/${sectionId}/spec.md`;
const sectionSpec = fs.readFileSync(sectionSpecPath, 'utf-8');

// Check for sample data
let sampleData = null;
const dataPath = `.design/bumba-design-director/product/sections/${sectionId}/data.json`;
if (fs.existsSync(dataPath)) {
  sampleData = JSON.parse(fs.readFileSync(dataPath, 'utf-8'));
}

// Load Bumba components
const { getBumbaContext } = require('./.design/bumba-design-director/lib/bumba-reader.js');
const bumbaContext = getBumbaContext();
```

Show context:
```
Adding screen specifications to: [SectionName]

[If sample data exists:]
Sample data available with: [list entity types]

[If components available:]
Bumba components available: [N] components
```

## Step 2: Consult Specification Writing Skill

Read the specification writing skill:

Path: `.design/bumba-design-director/.claude/skills/specification-writing/SKILL.md`

## Step 3: Explain Screen Specifications

Before gathering info, explain screen specs:

```
Screen specifications describe WHAT each screen does, not HOW it looks.

Focus on:
✓ Purpose - What is this screen for?
✓ Data - What data is displayed?
✓ Actions - What can users do?
✓ States - Loading, error, empty, success states

NOT:
✗ Colors, fonts, spacing (Bumba tokens)
✗ Exact pixel layouts (implementation detail)
✗ Design aesthetics

Examples:

Good:
- "Product list shows 12 products per page with name, image, price"
- "Filter sidebar allows category selection and price range"
- "Detail view displays full product info with add-to-cart action"

Not specific enough:
- "Product page"
- "Shows products"
```

## Step 4: Ask About Screens

Ask how many screens to specify:

```
The section spec mentions these UI requirements:
[Extract from section spec]

How many distinct screens would you like to specify?
(Typically 2-5 screens per section)
```

- Store as: `screenCount`
- Validation: At least 1 screen

## Step 5: For Each Screen

For each screen, ask these questions conversationally:

**Screen [N] Name**
"What is screen [N]? (e.g., 'Product List', 'Product Detail', 'Checkout')"

- Store as: `screens[N].name`
- Validation: Not empty, unique within section

**Screen [N] Purpose**
"What is the purpose of the [ScreenName] screen? (1-2 sentences)"

- Store as: `screens[N].purpose`
- Validation: At least 10 characters
- Guidance: Focus on user goals

**Screen [N] Data Displayed**
"What data is displayed on [ScreenName]?"

If sample data exists, suggest entities:
```
Your sample data has: [list entities]
Which of these appear on this screen?
```

Parse user response into structured list:
```
Example user input:
"Shows list of products with names, prices, images, and category tags"

Parse to:
- Product list (name, price, image)
- Category tags
- Pagination info
```

- Store as: `screens[N].dataDisplayed`
- Validation: At least 1 data element

**Screen [N] Actions Available**
"What actions can users take on [ScreenName]?"

```
Examples:
- Click product to view details
- Add to cart
- Filter by category
- Sort by price
- Search products
```

- Store as: `screens[N].actions`
- Validation: At least 1 action (even if just "navigate back")

**Screen [N] States**
"What different states can [ScreenName] be in?"

Show common states:
```
Common states:
- Loading (data is being fetched)
- Success (data loaded, content shown)
- Empty (no data to display)
- Error (failed to load data)
```

Ask user which states apply and if there are any custom states.

- Store as: `screens[N].states`
- Default: "Loading, Success, Error, Empty"

## Step 6: Reference Bumba Components (Optional)

If Bumba components are available, ask:

```
✓ Bumba components available:
${bumbaContext.components.map(c => `- ${c.name} (${c.type})`).join('\n')}

Which components would you use for [ScreenName]?
(Or skip to suggest during implementation)
```

- Store as: `screens[N].suggestedComponents` (optional)

## Step 7: Update Section Spec

Read the existing section spec and append screen specifications:

```javascript
// Parse existing spec.md
// Add a new section "## Screen Specifications" if not present
// Append each screen's details

// Format:
### [ScreenName]

**Purpose**: [purpose]

**Data Displayed**: [dataDisplayed]

**Actions Available**: [actions]

**States**: [states]

[If components suggested:]
**Suggested Components**: [list]

---
```

Write updated spec back to file.

## Step 8: Display Preview

Show what was added:

```
Updated: sections/[sectionId]/spec.md

Added [N] screen specifications:

1. [Screen1Name]
   Purpose: [purpose]
   Data: [summary]
   Actions: [count] actions

2. [Screen2Name]
   Purpose: [purpose]
   Data: [summary]
   Actions: [count] actions

Preview of additions:
─────────────────────────────────────
[Display added section from spec.md]
─────────────────────────────────────

Updated spec saved to:
.design/bumba-design-director/product/sections/[sectionId]/spec.md
```

## Step 9: Next Steps

Display next steps:

```
Screen specifications added! ✓

Next steps:

→ Add more screens to this section: /director-screen-spec [sectionId]
→ Specify another section: /director-section-spec
→ Export implementation package: /director-export
```

## Error Handling

**Missing Section Spec:**
```
Error: Section spec not found for "[sectionId]"

You need to create a section specification first.

→ Run /director-section-spec [sectionId]
→ Then run /director-screen-spec [sectionId] again
```

**Duplicate Screen Names:**
```
Error: Screen "[ScreenName]" already exists in this section

Please use a different name or update the existing screen.
```

**No Actions Specified:**
```
Warning: No actions specified for "[ScreenName]"

Even view-only screens typically have actions (e.g., "Navigate back", "Scroll to view more")

Add actions? (yes/no)
```

**File Update Failure:**
```
Error: Failed to update section spec

→ Check permissions for spec.md
→ Ensure file is not locked or open in another program
```

## Implementation Notes

- Update existing spec.md (append, don't overwrite)
- Check for existing "## Screen Specifications" section
- If exists, append new screens
- If not exists, add section header then screens
- Validate screen names are unique within section
- Default states to common set if user unsure
- Link data displayed to sample data entities if available
- Reference Bumba components when available
- Allow adding multiple screens in one session
- Show preview of what's being added
- Preserve existing content in spec.md
- Use markdown formatting consistently (###, **, -, ---)

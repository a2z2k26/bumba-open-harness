---
name: design-director-roadmap
description: Break product into 3-5 development sections
---

You are helping the user organize their product into logical development sections - self-contained feature areas that can be designed and built independently.

## Prerequisites Check

1. Verify `product-overview.md` exists
   - Path: `.design/bumba-design-director/product/product-overview.md`
   - If NOT found: Display error and suggest running `/director-vision` first

2. Check if `product-roadmap.md` already exists
   - Path: `.design/bumba-design-director/product/product-roadmap.md`
   - If found: Ask user "Product roadmap already exists. Do you want to update it?"
     - If no: Exit gracefully
     - If yes: Continue (will overwrite)

## Step 1: Show Context

Load and display the product name from product-overview.md to remind the user:

```
Creating roadmap for: [Product Name]
```

## Step 2: Consult Specification Writing Skill

Read the specification writing skill for guidance:

Path: `.design/bumba-design-director/.claude/skills/specification-writing/SKILL.md`

## Step 3: Explain Sections Concept

Before asking for sections, explain what sections are:

```
A "section" is a self-contained feature area of your product. Think of sections as:

✓ Independent modules that can be built separately
✓ Major functional areas (e.g., "User Authentication", "Dashboard", "Settings")
✓ Bounded by clear user-facing boundaries

Examples:
- E-commerce: "Product Catalog", "Shopping Cart", "Checkout", "Order History"
- SaaS Tool: "User Onboarding", "Main Workspace", "Analytics Dashboard", "Team Management"
- Social App: "User Profiles", "Feed", "Messaging", "Notifications"

Recommended: 3-5 sections for most products
```

## Step 4: Gather Section Information

Ask the user to define their sections. Use conversational prompts:

**Question 1: Number of Sections**
"How many main sections will your product have? (Recommended: 3-5)"

- Validation: Between 3 and 5 inclusive
- If user wants more or less, allow but warn:
  - Less than 3: "Are you sure? Most products have at least 3 distinct areas."
  - More than 5: "That's quite a few. Consider grouping related features together."

**Question 2: For Each Section**

Ask these questions for each section:

**Section [N] Title**
"What is section [N]? (e.g., 'User Dashboard', 'Product Catalog')"

- Store as: `sections[N].title`
- Validation: Not empty, unique among sections

**Section [N] Description**
"Describe section [N] in 1-2 sentences. What does this section do?"

- Store as: `sections[N].description`
- Validation: At least 10 characters
- Guidance: Focus on user capabilities, not implementation

## Step 5: Auto-Generate Section IDs

For each section, generate a URL-safe ID from the title:

```javascript
function generateSectionId(title) {
  return title
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, '')  // Remove special chars
    .replace(/\s+/g, '-')           // Replace spaces with hyphens
    .replace(/-+/g, '-')            // Remove duplicate hyphens
    .trim();
}
```

Store as: `sections[N].id`

Show generated IDs to user for confirmation:

```
Generated section IDs:
1. [Title] → [id]
2. [Title] → [id]
3. [Title] → [id]

These IDs will be used for file organization and references.
```

## Step 6: Validate No Duplicate IDs

Check that all generated IDs are unique:

```javascript
const ids = sections.map(s => s.id);
const uniqueIds = new Set(ids);
if (ids.length !== uniqueIds.size) {
  // Error: duplicate IDs found
}
```

If duplicates found, ask user to rephrase section titles to make them distinct.

## Step 7: Generate Product Roadmap

Use the spec-generator utility:

```javascript
const { generateProductRoadmap } = require('./.design/bumba-design-director/lib/spec-generator.js');

const outputPath = generateProductRoadmap(sections);
```

Where `sections` is:
```javascript
[
  { title: "...", id: "...", description: "..." },
  { title: "...", id: "...", description: "..." },
  ...
]
```

## Step 8: Display Preview

Show the user a preview:

```
Generated: product-roadmap.md

Your product has [N] sections:

1. [Title] (id: [id])
   [Description]

2. [Title] (id: [id])
   [Description]

...

Full roadmap saved to:
.design/bumba-design-director/product/product-roadmap.md
```

## Step 9: Next Steps

Display next steps:

```
Product roadmap complete! ✓

Next step: Define your data model

→ Run /director-data-model to specify entities and relationships

Or skip to:
→ /director-shell-spec to define navigation structure
→ /director-section-spec [section-id] to specify a section
```

## Error Handling

**Missing Product Overview:**
```
Error: product-overview.md not found

You need to define your product vision first.

→ Run /director-vision to create product overview
→ Then run /director-roadmap again
```

**Duplicate Section IDs:**
```
Error: Duplicate section IDs detected

Sections "[Title1]" and "[Title2]" both generate ID: "[id]"

Please rephrase one of these section titles to make them distinct.
```

**Invalid Section Count:**
```
Validation error: Number of sections must be between 3 and 5

You entered: [N]

[Ask question again]
```

**File Write Failure:**
```
Error: Failed to write product-roadmap.md

→ Check permissions in .design/bumba-design-director/product/
→ Ensure the directory exists
```

## Implementation Notes

- Generate IDs automatically but show them to user
- Validate uniqueness of IDs before proceeding
- Store complete section data (title, id, description) in array
- Display sections in numbered list for clarity
- Encourage 3-5 sections but allow flexibility
- Guide user on what makes a good section boundary
- Show both immediate next step (/director-data-model) and alternative paths

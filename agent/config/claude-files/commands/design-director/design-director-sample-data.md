---
name: design-director-sample-data
description: Generate sample data and TypeScript types for a section
---

You are helping the user create realistic sample data for a section - data that can be used for implementation and testing.

## Prerequisites Check

1. Verify section spec exists
   - Path: `.design/bumba-design-director/product/sections/[sectionId]/spec.md`
   - If NOT found: Display error and suggest running `/director-section-spec [sectionId]` first

2. Check if `data.json` already exists for this section
   - Path: `.design/bumba-design-director/product/sections/[sectionId]/data.json`
   - If found: Ask "Sample data already exists for [sectionName]. Update it?"
     - If no: Exit gracefully
     - If yes: Continue (will overwrite)

## Step 1: Load Context

Load section spec and data model if available:

```javascript
const fs = require('fs');
const sectionSpecPath = `.design/bumba-design-director/product/sections/${sectionId}/spec.md`;
const sectionSpec = fs.readFileSync(sectionSpecPath, 'utf-8');

// Extract section name from spec
// Show for context

// Check for data model
const dataModelPath = '.design/bumba-design-director/product/data-model/data-model.md';
let dataModel = null;
if (fs.existsSync(dataModelPath)) {
  dataModel = fs.readFileSync(dataModelPath, 'utf-8');
}
```

## Step 2: Consult Data Modeling Skill

Read the data modeling best practices skill:

Path: `.design/bumba-design-director/.claude/skills/data-modeling-best-practices/SKILL.md`

## Step 3: Explain Sample Data Purpose

Before gathering data, explain:

```
Sample data provides realistic test data for implementation.

Purpose:
✓ Gives developers concrete examples to work with
✓ Used for UI testing and validation
✓ Defines structure without design aesthetics

This is STRUCTURAL data only:
✓ Names, emails, dates, quantities, prices
✓ Status values, categories, tags
✓ Relationships between entities

NOT design information:
✗ Colors, fonts, spacing (comes from Bumba tokens)
✗ Visual layout (comes from specifications)
```

## Step 4: Determine Data Generation Method

Ask user how they want to provide sample data:

```
How would you like to create sample data for [SectionName]?

1. Auto-generate from data model
   - I'll create realistic sample data based on your entities
   - Quick and easy

2. Provide JSON directly
   - You paste/write JSON structure
   - Full control over data

3. Guided entry
   - I'll ask questions and build the JSON
   - Good for small datasets
```

- Store as: `method` (1, 2, or 3)

### Option 1: Auto-Generate

If data model exists, generate sample data from it:

```javascript
// Extract entities relevant to this section
// Generate 3-5 sample records for each entity
// Use realistic data (faker.js patterns if available, otherwise sensible defaults)

// Example for Product entity:
const sampleData = {
  products: [
    {
      id: "prod-001",
      name: "Wireless Headphones",
      description: "High-quality wireless headphones with noise cancellation",
      price: 199.99,
      category: "Electronics",
      inStock: true,
      createdAt: "2024-01-15T10:30:00Z"
    },
    // ... more products
  ]
};
```

Show generated data to user for approval.

### Option 2: Provide JSON

Ask user to provide JSON:

```
Please provide your sample data as JSON.

Example format:
{
  "products": [
    { "id": "1", "name": "Product 1", "price": 29.99 },
    { "id": "2", "name": "Product 2", "price": 39.99 }
  ]
}

Paste your JSON:
```

Validate JSON syntax:
```javascript
try {
  const data = JSON.parse(userInput);
  // Valid JSON
} catch (error) {
  // Invalid - show error and ask again
}
```

### Option 3: Guided Entry

Ask questions to build JSON:

```
What entities does this section use?
(e.g., "Product", "Category", or "Product, User, Order")
```

For each entity:
```
How many sample [Entity] records do you want? (3-5 recommended)
```

Then ask for each record:
```
[Entity] #1:
- Field1: [value]
- Field2: [value]
...
```

Build JSON structure from user responses.

## Step 5: Validate Sample Data

Check that:
- JSON is valid
- Data is an object (not array or primitive)
- Has at least one top-level key
- Values match expected types from data model (if available)

Show warnings for:
- Design aesthetic data (e.g., "backgroundColor": "blue")
- Missing common fields (id, createdAt, etc.)
- Unrealistic data (e.g., negative prices)

## Step 6: Generate data.json

Write the sample data to file:

```javascript
const fs = require('fs');
const outputPath = `.design/bumba-design-director/product/sections/${sectionId}/data.json`;

fs.writeFileSync(outputPath, JSON.stringify(sampleData, null, 2), 'utf-8');
```

## Step 7: Auto-Generate TypeScript Types

Use type-generator to infer types from the JSON:

```javascript
const { generateSectionTypes } = require('./.design/bumba-design-director/lib/type-generator.js');

const typesPath = generateSectionTypes(sectionId, sampleData);
```

This creates `.design/bumba-design-director/product/sections/[sectionId]/types.ts`

## Step 8: Display Preview

Show user what was generated:

```
Generated: data.json and types.ts for [SectionName]

Sample Data:
{
  "products": [
    { "id": "prod-001", "name": "Wireless Headphones", ... },
    { "id": "prod-002", "name": "Smart Watch", ... }
  ]
}

TypeScript Types:
export interface Product {
  id: string;
  name: string;
  description: string;
  price: number;
  category: string;
  inStock: boolean;
  createdAt: Date | string;
}

export interface SectionData {
  products: Product[];
}

Files saved to:
.design/bumba-design-director/product/sections/[sectionId]/
```

## Step 9: Next Steps

Display next steps:

```
Sample data complete! ✓

Next steps:

→ /director-screen-spec [sectionId] to add detailed screen specifications
→ /director-section-spec to specify another section
→ /director-export to create implementation package
```

## Error Handling

**Missing Section Spec:**
```
Error: Section spec not found for "[sectionId]"

You need to create a section specification first.

→ Run /director-section-spec [sectionId]
→ Then run /director-sample-data [sectionId] again
```

**Invalid JSON:**
```
Error: Invalid JSON syntax

Error at line [N]: [error message]

Please check your JSON and try again.
Common issues:
- Missing commas between items
- Unclosed brackets or braces
- Unquoted string values
```

**Design Aesthetic Warning:**
```
Warning: Your data includes design aesthetic information

Found: "color": "blue", "fontSize": "16px"

Remember: Sample data should be STRUCTURAL only.
Design aesthetics come from Bumba Design tokens.

Continue anyway? (yes/no)
```

**Empty Data:**
```
Error: Sample data is empty

You need to provide at least one entity with sample records.

Let's try again...
```

**File Write Failure:**
```
Error: Failed to write data.json

→ Check permissions in .design/bumba-design-director/product/sections/[sectionId]/
→ Directory will be created if missing
```

## Implementation Notes

- Default to auto-generation if data model exists
- Validate JSON thoroughly before saving
- Warn about design aesthetics but don't block
- Generate TypeScript types automatically (no user input needed)
- Use realistic sample data (proper format for emails, dates, etc.)
- Provide 3-5 sample records per entity (enough to test, not too many)
- Date strings should use ISO 8601 format
- Infer TypeScript types intelligently (Date detection, array types, etc.)
- Show both data.json AND types.ts in preview
- Create section directory if it doesn't exist
- Preserve existing types.ts if data.json is updated (will regenerate)

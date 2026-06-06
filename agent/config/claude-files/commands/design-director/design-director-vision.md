---
name: design-director-vision
description: Define product vision, problems, and key features
---

You are helping the user define their product vision - the foundation for all Design Director specifications.

## Prerequisites Check

1. Verify `.design/bumba-design-director/` exists
   - If NOT found: Display error and instruct to run `/director-init` first

2. Check if `product-overview.md` already exists
   - Path: `.design/bumba-design-director/product/product-overview.md`
   - If found: Ask user "Product overview already exists. Do you want to update it?"
     - If no: Exit gracefully
     - If yes: Continue (will overwrite)

## Step 1: Load Bumba Context

Before asking questions, load the Bumba Design System context:

```javascript
const { getBumbaContext } = require('./.design/bumba-design-director/lib/bumba-reader.js');
const bumbaContext = getBumbaContext();
```

This will tell you:
- `bumbaContext.framework` - Target framework (react, vue, etc.)
- `bumbaContext.hasTokens` - Whether design tokens are available
- `bumbaContext.hasComponents` - Whether components are available
- `bumbaContext.tokens` - Token data if available

## Step 2: Consult Specification Writing Skill

Read the specification writing skill for guidance on writing clear specifications:

Path: `.design/bumba-design-director/.claude/skills/specification-writing/SKILL.md`

Apply its principles throughout this workflow (clarity, actionability, user-focused language).

## Step 3: Gather Product Information

Ask the user the following questions conversationally. DO NOT use a form - have a natural conversation.

**Question 1: Product Name**
"What is your product name?"

- Store as: `productName`
- Validation: Not empty

**Question 2: Product Description**
"Describe your product in 2-3 sentences. What does it do and who is it for?"

- Store as: `description`
- Validation: At least 20 characters
- Guidance: Focus on WHAT and WHO, not technical details

**Question 3: Problems & Pain Points**
"What problems does this product solve? List 3-5 specific pain points your users experience."

- Store as: `problems` (array or multi-line string)
- Validation: At least 1 problem listed
- Guidance: Be specific - "Users waste 2 hours daily on manual data entry" is better than "Data entry is tedious"

**Question 4: Key Features**
"What are the key features of your product? List 3-7 core capabilities."

- Store as: `features` (array or multi-line string)
- Validation: At least 1 feature listed
- Guidance: Focus on capabilities, not implementation details

## Step 4: Generate Product Overview

Use the spec-generator utility to create the product overview:

```javascript
const { generateProductOverview } = require('./.design/bumba-design-director/lib/spec-generator.js');

const data = {
  productName: "[user's answer]",
  description: "[user's answer]",
  problems: "[user's answer]",
  features: "[user's answer]"
};

const outputPath = generateProductOverview(data, bumbaContext);
```

## Step 5: Display Preview

Show the user a preview of the generated specification:

```
Generated: product-overview.md

Preview:
─────────────────────────────────────
[Display first 20-30 lines of the generated file]
─────────────────────────────────────

Full specification saved to:
.design/bumba-design-director/product/product-overview.md
```

## Step 6: Bumba Integration Note

If Bumba tokens are available, mention:

```
✓ Design tokens detected
  Your specification references [N] token files from .design/tokens/
  These will be used as the design foundation for implementation.
```

If Bumba tokens are NOT available:

```
Note: No design tokens found yet
      Your specification includes a placeholder for design tokens.
      Run Bumba Design commands to extract tokens from Figma when ready.
```

## Step 7: Next Steps

Display next steps:

```
Product vision defined! ✓

Next step: Break your product into development sections

→ Run /director-roadmap to organize your product into 3-5 feature areas
```

## Error Handling

**Validation Failure:**
```
Validation error: [specific issue]

Let's try that again. [Repeat the question that failed validation]
```

**File Write Failure:**
```
Error: Failed to write product-overview.md

→ Check permissions in .design/bumba-design-director/product/
→ Ensure the directory exists
```

**Missing Bumba Context:**
```
Warning: Could not load Bumba context

This won't prevent specification generation, but Bumba integration
features will use fallback values.

→ Check that bumba-reader.js exists in .design/bumba-design-director/lib/
```

## Implementation Notes

- Keep conversation natural and encouraging
- Validate inputs before generating spec
- Show preview to give user confidence in output
- Reference Bumba integration status clearly
- Guide user to next logical step (/director-roadmap)
- If user provides very brief answers, ask follow-up questions to get more detail
- Store all data before calling generateProductOverview()

---
name: design-director-run
description: Complete guided workflow for creating product specifications from vision to export
---

# Design Director Run

This command guides you through the complete Design Director workflow in a single session, from product vision to exportable specification package.

## Overview

You'll complete these steps in order:

1. **Vision** - Define product vision, problems, and features
2. **Roadmap** - Break product into 3-5 development sections
3. **Data Model** - Define entities and relationships
4. **Shell Spec** - Specify navigation structure
5. **Section Specs** - Define requirements for each section
6. **Sample Data** - Generate test data for sections
7. **Screen Specs** - Add detailed screen specifications (optional)
8. **Export** - Generate implementation package

**Estimated Time**: 30-60 minutes depending on product complexity

---

## Prerequisites

Before starting, ensure:

1. `/design-init` has been run and Design Director is enabled
2. You have a clear product concept in mind
3. You have 30-60 minutes of uninterrupted time

---

## Walkthrough Flow

### Introduction

Welcome to Design Director! This wizard will help you create comprehensive product specifications that integrate with your Bumba Design System.

**What we'll create:**
- Product overview with vision and features
- Development roadmap with 3-5 sections
- Data model with entities and TypeScript types
- Navigation shell specification
- Section requirements and user flows
- Sample data and screen specifications
- Complete implementation package

**What we won't create:**
- Design tokens (use Bumba Design features)
- Components (use Bumba transformers)
- Actual code (specifications only)

Let's begin!

---

## Step 1: Product Vision

*Invoking /design-director-vision...*

Ask the user the following questions conversationally:

### 1.1 Product Name
"What is your product name?"

Store as: `productName`

### 1.2 Product Description
"Describe your product in 2-3 sentences. What does it do?"

Store as: `description`

### 1.3 Problems Solved
"What problems does this product solve? List 3-5 specific pain points your users experience."

Store as: `problems` (array of strings)

### 1.4 Key Features
"What are the key features? List 3-7 core capabilities."

Store as: `features` (array of strings)

### 1.5 Generate Vision Document

Use the spec-generator.js utility to generate:
- `.design/bumba-design-director/product/product-overview.md`

Display:
```
✓ Product vision created!
  File: .design/bumba-design-director/product/product-overview.md
```

Continue to Step 2.

---

## Step 2: Product Roadmap

*Proceeding to roadmap definition...*

### 2.1 Explain Sections

"Now let's break your product into 3-5 development sections. Each section represents a self-contained feature area that can be built independently."

Examples:
- User Authentication
- Dashboard
- Product Management
- Analytics & Reporting
- Settings

### 2.2 Collect Sections

For each section (3-5 total):

**Section {{number}}:**
- "Section title?"
- "Brief description (1-2 sentences)?"

Auto-generate section ID from title (slug format).

Store as: `sections` array with `{title, description, id}`

### 2.3 Generate Roadmap

Use spec-generator.js to generate:
- `.design/bumba-design-director/product/product-roadmap.md`

Display generated section IDs:
```
✓ Product roadmap created!
  File: .design/bumba-design-director/product/product-roadmap.md

  Sections:
  1. user-authentication (User Authentication)
  2. dashboard (Dashboard)
  3. product-management (Product Management)
```

Continue to Step 3.

---

## Step 3: Data Model

*Proceeding to data model definition...*

### 3.1 Explain Data Model

"Let's define your data model. Think about the core 'nouns' of your system - the main entities that your product manages."

Examples: User, Product, Order, Invoice, Task, Project

### 3.2 Collect Entities

Ask: "How many entities does your product have? (Typically 3-8)"

For each entity:

**Entity {{number}}:**
- "Entity name?" (e.g., User, Product)
- "Description?" (1 sentence)
- "Key attributes?" (Ask for 3-7 attributes with types)
  - For each: "Attribute name and type?" (e.g., `email: string`, `createdAt: Date`)
- "Relationships to other entities?" (e.g., User hasMany Orders)

Store as: `entities` array

### 3.3 Generate Data Model

Use spec-generator.js and type-generator.js to generate:
- `.design/bumba-design-director/product/data-model/data-model.md`
- `.design/bumba-design-director/product/data-model/types.ts`

Display:
```
✓ Data model created!
  Files:
  - .design/bumba-design-director/product/data-model/data-model.md
  - .design/bumba-design-director/product/data-model/types.ts
```

Continue to Step 4.

---

## Step 4: Shell Specification

*Proceeding to navigation shell...*

### 4.1 Explain Shell

"The shell is your app's persistent navigation structure - the chrome that wraps all your screens."

### 4.2 Layout Pattern

Ask: "Which layout pattern fits your product?"

Options (use AskUserQuestion):
1. **Sidebar Navigation** - Persistent left sidebar with nav items
2. **Top Navigation** - Horizontal nav bar at top
3. **Combined** - Top bar + sidebar
4. **Minimal** - Bottom tab bar or minimal chrome

Store as: `layoutPattern`

### 4.3 Navigation Items

"What navigation items should appear in your shell?"

Auto-suggest from sections, allow user to add more (e.g., Profile, Settings).

Store as: `navItems` array

### 4.4 Bumba Layouts Check

Check if Bumba layouts exist via bumba-reader.js.

If layouts exist:
"I found {{count}} layouts in your Bumba Design System. Would you like to reference a specific layout for the shell?"
- Show list of available layouts
- User can choose one or skip

### 4.5 Generate Shell Spec

Use spec-generator.js to generate:
- `.design/bumba-design-director/product/shell/spec.md`

Display:
```
✓ Shell specification created!
  File: .design/bumba-design-director/product/shell/spec.md
  Layout: {{layoutPattern}}
```

Continue to Step 5.

---

## Step 5: Section Specifications

*Proceeding to section requirements...*

### 5.1 Introduction

"Now let's detail each section. For each section, you'll define user flows and UI requirements."

### 5.2 For Each Section

Loop through all sections from roadmap:

**Section: {{section.title}}**

#### 5.2.1 User Flows

"What are the main user flows for {{section.title}}? Describe step-by-step what users do."

Example format:
```
1. User clicks "Create Product"
2. User fills out product form
3. User uploads product image
4. User clicks "Save"
5. System validates and saves product
```

Store as: `userFlows`

#### 5.2.2 UI Requirements

"What screens/views are needed for {{section.title}}?"

Example: "Product list view, Product detail view, Create/edit form"

Store as: `uiRequirements`

#### 5.2.3 Bumba Components Check

Check for Bumba components via bumba-reader.js.

If components exist:
"I found {{count}} components in your Bumba Design System. Here are components that might be relevant for {{section.title}}:"
- List relevant components
- User notes which to use

#### 5.2.4 Generate Section Spec

Use spec-generator.js to generate:
- `.design/bumba-design-director/product/sections/{{section.id}}/spec.md`

Display:
```
✓ Specification created for {{section.title}}!
  File: .design/bumba-design-director/product/sections/{{section.id}}/spec.md
```

Repeat for all sections, then continue to Step 6.

---

## Step 6: Sample Data

*Proceeding to sample data generation...*

### 6.1 Introduction

"Let's generate sample data for each section to help with implementation."

### 6.2 For Each Section

Loop through all sections:

**Section: {{section.title}}**

Ask: "How should we generate sample data for {{section.title}}?"

Options (use AskUserQuestion):
1. **Auto-generate** - I'll create realistic sample data based on your data model
2. **Provide JSON** - You provide a JSON structure
3. **Guided entry** - I'll ask for each field

#### 6.2.1 If Auto-generate

Generate sample data from data model entities.

#### 6.2.2 If Provide JSON

Ask: "Paste your JSON sample data:"

Validate JSON structure.

#### 6.2.3 If Guided entry

For each entity in this section:
- Ask for field values
- Build JSON structure

#### 6.2.4 Generate Files

Use type-generator.js to generate:
- `.design/bumba-design-director/product/sections/{{section.id}}/data.json`
- `.design/bumba-design-director/product/sections/{{section.id}}/types.ts` (auto-generated by hook)

Display:
```
✓ Sample data created for {{section.title}}!
  Files:
  - .design/bumba-design-director/product/sections/{{section.id}}/data.json
  - .design/bumba-design-director/product/sections/{{section.id}}/types.ts (auto-generated)
```

Repeat for all sections, then continue to Step 7.

---

## Step 7: Screen Specifications (Optional)

*Optional screen details...*

### 7.1 Ask if User Wants Screen Details

Ask: "Would you like to add detailed screen specifications now?"

Options:
- **Yes** - Add screen details for each section
- **Skip** - Continue to export (can add later with /design-director-screen-spec)

If Skip, go to Step 8.

### 7.2 For Each Section (if Yes)

Loop through sections:

**Section: {{section.title}}**

Ask: "How many screens does {{section.title}} have?" (Typically 2-5)

For each screen:
- "Screen name/purpose?"
- "What data is displayed?"
- "What actions are available?"
- "Success and error states?"

Update section spec with screen details.

Display:
```
✓ Screen specifications added to {{section.title}}!
```

Continue to Step 8.

---

## Step 8: Export Package

*Generating implementation package...*

### 8.1 Completeness Check

Check for:
- ✓ product-overview.md
- ✓ product-roadmap.md
- ✓ data-model/
- ✓ shell/spec.md
- ✓ All section specs

Display completeness:
```
Specification Completeness: 100%
✓ Product overview
✓ Roadmap ({{sections.length}} sections)
✓ Data model ({{entities.length}} entities)
✓ Shell specification
✓ Section specifications ({{sections.length}}/{{sections.length}})
✓ Sample data ({{sections.length}}/{{sections.length}})
```

### 8.2 Load Bumba Context

Use bumba-reader.js to check for tokens, components, framework.

### 8.3 Build Export Package

Use export-builder.js to generate:
- `.design/bumba-design-director/design-direction-plan/`

This creates:
- README.md
- prompts/ (one-shot and incremental)
- instructions/ (implementation guides)
- specifications/ (copy of all specs)

Display:
```
✓ Export package generated!

Location: .design/bumba-design-director/design-direction-plan/

Package includes:
  - README.md (quick start guide)
  - prompts/ (ready-to-use coding agent prompts)
  - instructions/ (implementation guides)
  - specifications/ (all your specs)

Framework: {{framework}}
Bumba Assets Referenced:
  - Tokens: {{tokenFiles.length}} files
  - Components: {{components.length}} components
```

---

## Completion

### Success Summary

```
🎉 Design Director Walkthrough Complete!

You've created:
  ✓ Product vision and overview
  ✓ {{sections.length}}-section development roadmap
  ✓ {{entities.length}}-entity data model with TypeScript types
  ✓ Navigation shell specification
  ✓ {{sections.length}} section specifications with user flows
  ✓ Sample data for all sections
  ✓ Complete implementation package

Export Package Location:
  .design/bumba-design-director/design-direction-plan/

Next Steps:
  1. Review specifications in design-direction-plan/
  2. Copy export package to your implementation project
  3. Use prompts in design-direction-plan/prompts/ with coding agents
  4. Implement using Bumba components from .design/extracted-code/{{framework}}/
  5. Follow design-direction-plan/README.md for detailed guidance

Individual Commands (for updates):
  /design-director-vision - Update product vision
  /design-director-roadmap - Modify sections
  /design-director-data-model - Update data model
  /design-director-section-spec - Update specific section
  /design-director-sample-data - Regenerate sample data
  /design-director-screen-spec - Add more screen details
  /design-director-export - Re-export package
```

---

## Error Handling

### If Prerequisites Not Met

If `.design/bumba-design-director/` doesn't exist:

```
Error: Design Director not initialized

Please run /design-init first and ensure Design Director is enabled.

If you've already run /design-init but don't have Design Director:
1. Re-run /design-init
2. Choose "Yes" for Design Director when prompted
```

Exit walkthrough.

### If Partial Completion

If user exits mid-walkthrough, specs are saved incrementally.

They can:
- Resume with /design-director-walkthrough (will detect completed steps and skip them)
- Continue manually with individual commands
- Start over by deleting `.design/bumba-design-director/product/` and re-running

---

## Technical Implementation Notes

This walkthrough command:
1. Calls the same utility libraries (bumba-reader, spec-generator, type-generator, export-builder) as individual commands
2. Stores state in `.design/bumba-design-director/product/` incrementally
3. Can be interrupted and resumed (detects existing files)
4. Hooks still fire automatically (type regeneration, completeness checks)
5. Final export step uses same export-builder.js as /design-director-export

This ensures consistency between walkthrough and individual commands.

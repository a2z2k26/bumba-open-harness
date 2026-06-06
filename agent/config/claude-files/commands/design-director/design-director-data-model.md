---
name: design-director-data-model
description: Define core entities, attributes, and relationships
---

You are helping the user define their data model - the core entities (nouns) of their system, their attributes, and relationships between them.

## Prerequisites Check

1. Verify `product-roadmap.md` exists
   - Path: `.design/bumba-design-director/product/product-roadmap.md`
   - If NOT found: Display error and suggest running `/director-roadmap` first (though data model can be done independently)

2. Check if `data-model/data-model.md` already exists
   - Path: `.design/bumba-design-director/product/data-model/data-model.md`
   - If found: Ask user "Data model already exists. Do you want to update it?"
     - If no: Exit gracefully
     - If yes: Continue (will overwrite)

## Step 1: Consult Data Modeling Skill

Read the data modeling best practices skill:

Path: `.design/bumba-design-director/.claude/skills/data-modeling-best-practices/SKILL.md`

Apply its principles throughout (entity identification, attribute design, TypeScript patterns).

## Step 2: Explain Data Model Purpose

Before asking questions, explain what a data model is:

```
The data model defines the STRUCTURE of your system, not its design.

Think in terms of:
✓ Entities: The "nouns" of your system (User, Product, Order, Task, etc.)
✓ Attributes: Properties of each entity (id, name, email, createdAt, etc.)
✓ Relationships: How entities connect (User has many Orders, Order has many Items)

Important: This is purely structural - no colors, fonts, or visual design.
           Design aesthetics come from Bumba Design tokens.

Examples:
- E-commerce: User, Product, Order, OrderItem, Review, ShippingAddress
- Task Manager: User, Project, Task, Comment, Attachment, Label
- Social App: User, Post, Comment, Like, Follow, Message
```

## Step 3: Gather Entity Information

Ask the user to define their entities conversationally:

**Question 1: Entity List**
"What are the main entities (nouns) in your system? List 3-10 core entities."

Examples to guide them:
- User / Account / Profile
- Product / Item / Listing
- Order / Purchase / Transaction
- etc.

- Store as: `entityNames` (array)
- Validation: At least 2 entities
- Guidance: Focus on domain nouns, not UI concepts

**For Each Entity:**

**Entity [N] Description**
"Describe the [EntityName] entity in 1-2 sentences. What does it represent?"

- Store as: `entities[N].description`
- Validation: At least 10 characters

**Entity [N] Attributes**
"What are the key attributes of [EntityName]? List property names and their types."

Show TypeScript type examples:
```
Common types:
- string (text, emails, names)
- number (quantities, prices, counts)
- boolean (flags, yes/no)
- Date (timestamps, dates)
- string[] (arrays of text)
- [EntityName] (references to other entities)
- [EntityName][] (arrays of entities)
```

Ask conversationally:
"For [EntityName], what properties does it have? You can describe them naturally and I'll convert to TypeScript."

Example user input:
"It has an id, a name, an email address, a creation date, and an optional profile picture URL"

Parse and convert to:
```typescript
[
  { name: "id", type: "string" },
  { name: "name", type: "string" },
  { name: "email", type: "string" },
  { name: "createdAt", type: "Date" },
  { name: "profilePictureUrl", type: "string | null" }
]
```

- Store as: `entities[N].attributes[]`
- Validation: At least 2 attributes per entity
- Each attribute needs: name, type, optional description

**Entity [N] Relationships** (Optional)
"Does [EntityName] relate to other entities? (e.g., 'User has many Orders', 'Order belongs to User')"

- Store as: `entities[N].relationships[]` (array of descriptions)
- This is optional - relationships can be described textually
- Examples:
  - "User has many Orders"
  - "Order belongs to User"
  - "Order has many OrderItems"
  - "Post has many Comments"

## Step 4: Validate Entity Structure

Check that:
- Each entity has a name
- Each entity has a description
- Each entity has at least 2 attributes
- Attribute types are valid TypeScript types
- No circular dependencies that would cause issues

## Step 5: Generate Data Model Specification

Use the spec-generator utility:

```javascript
const { generateDataModelSpec } = require('./.design/bumba-design-director/lib/spec-generator.js');

const entities = [
  {
    name: "User",
    description: "...",
    attributes: [
      { name: "id", type: "string", description: "..." },
      { name: "email", type: "string" },
      ...
    ],
    relationships: [
      "User has many Orders",
      ...
    ]
  },
  ...
];

const outputPath = generateDataModelSpec(entities);
```

## Step 6: Generate TypeScript Interfaces

Also generate TypeScript type definitions:

```javascript
const { generateDataModelTypes } = require('./.design/bumba-design-director/lib/type-generator.js');

const typesPath = generateDataModelTypes(entities);
```

This creates `.design/bumba-design-director/product/data-model/types.ts` with interface definitions.

## Step 7: Display Preview

Show the user what was generated:

```
Generated: data-model/data-model.md and data-model/types.ts

Entities defined:
1. User
   - id: string
   - name: string
   - email: string
   - createdAt: Date

2. Order
   - id: string
   - userId: string
   - total: number
   - createdAt: Date

TypeScript interfaces:
export interface User {
  id: string;
  name: string;
  email: string;
  createdAt: Date;
}

export interface Order {
  id: string;
  userId: string;
  total: number;
  createdAt: Date;
}

Files saved to:
.design/bumba-design-director/product/data-model/
```

## Step 8: Next Steps

Display next steps:

```
Data model complete! ✓

Next steps:

→ /director-shell-spec to define navigation structure
→ /director-section-spec [section-id] to specify a section
→ /director-sample-data [section-id] to create sample data for a section
```

## Error Handling

**Missing Roadmap (Warning Only):**
```
Note: product-roadmap.md not found

This won't prevent data model creation, but roadmap helps provide context.
Consider running /director-roadmap if you haven't already.
```

**Invalid TypeScript Type:**
```
Error: Invalid TypeScript type: "[invalid-type]"

Valid types include: string, number, boolean, Date, [EntityName], arrays (type[])

Please correct the type for attribute "[attribute-name]"
```

**Too Few Entities:**
```
Validation error: At least 2 entities required

You provided: [N] entities

A data model needs multiple entities to define relationships.
```

**Missing Attributes:**
```
Error: Entity "[EntityName]" has no attributes

Each entity needs at least 2 attributes (typically including an id).
```

**Circular Dependencies:**
```
Warning: Potential circular dependency detected

Entity "[A]" references "[B]" and "[B]" references "[A]"

This is okay for relationships, just be aware when implementing.
```

## Implementation Notes

- Help user convert natural language to TypeScript types
- Be flexible with type inference - ask clarifying questions if needed
- Generate both markdown spec AND TypeScript interfaces
- Relationships can be described textually (don't need to be enforced)
- Focus on core attributes - user can add more during implementation
- Suggest common attributes if user is stuck (id, createdAt, updatedAt)
- Show preview of both files before saving
- Create data-model/ directory if it doesn't exist

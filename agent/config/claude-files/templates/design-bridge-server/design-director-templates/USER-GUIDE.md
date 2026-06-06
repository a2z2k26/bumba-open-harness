# Bumba Design Director - User Guide

**CLI-based specification generator for product planning with Bumba Design System integration**

## Overview

Bumba Design Director is a specification-only tool that guides you through structured product planning, from vision to exportable implementation instructions. It generates hyper-detailed design specifications with written instructions that reference your existing Bumba Design System assets.

**What Design Director Does**:
- Product vision and roadmap planning
- Data model specification with TypeScript types
- Section specifications (user flows, UI requirements)
- Sample data generation
- Shell specification (navigation structure)
- Screen specifications
- Export package with implementation instructions

**What Design Director Does NOT Do**:
- ❌ Create design tokens (use Bumba Design features)
- ❌ Generate React/Vue/Angular components (use Bumba transformers)
- ❌ Create shell components (use Bumba layouts)
- ❌ Generate any tangible design assets

**Design Director generates SPECIFICATIONS. Bumba Design creates ASSETS.**

## Integration with Bumba Design System

Design Director seamlessly integrates with the Bumba Design System:

### Reads from Bumba
- Design tokens from `.design/tokens/*.json`
- Components from `.design/components/*.json`
- Framework preference from `.design/config.json`

### Adapts to Bumba
- Specifications reference available tokens
- Instructions point to components
- Export package is framework-specific
- Graceful fallback when Bumba assets don't exist

### Workflow Synergy
```
1. Extract design from Figma → Bumba Design (/design-transform-react)
2. Plan product structure → Design Director (/director-vision, /director-roadmap)
3. Define data model → Design Director (/director-data-model)
4. Specify sections → Design Director (/director-section-spec)
5. Generate sample data → Design Director (/director-sample-data)
6. Export specifications → Design Director (/director-export)
7. Implement with references to .design/ assets
```

## Installation

Design Director is installed automatically when you initialize Bumba Design System:

```bash
# Initialize Bumba Design System (if not already done)
/design-init

# When prompted: "Include Design Director for product planning?"
# Choose: Yes

# This copies Design Director to .design/bumba-design-director/
```

## Directory Structure

```
.design/
├── bumba-design-director/          # Design Director root
│   ├── lib/                        # Utility libraries
│   │   ├── bumba-reader.js         # Reads Bumba context
│   │   ├── spec-generator.js       # Generates markdown specs
│   │   ├── type-generator.js       # Generates TypeScript types
│   │   └── export-builder.js       # Builds export package
│   ├── templates/                  # Handlebars templates
│   │   ├── product-overview.md.tmpl
│   │   ├── product-roadmap.md.tmpl
│   │   ├── data-model.md.tmpl
│   │   ├── shell-spec.md.tmpl
│   │   └── section-spec.md.tmpl
│   ├── product/                    # Generated specifications
│   │   ├── product-overview.md
│   │   ├── product-roadmap.md
│   │   ├── data-model/
│   │   │   ├── data-model.md
│   │   │   └── types.ts
│   │   ├── shell/
│   │   │   └── spec.md
│   │   └── sections/
│   │       └── [section-id]/
│   │           ├── spec.md
│   │           ├── data.json
│   │           └── types.ts
│   └── product-plan/               # Export package
│       ├── README.md
│       ├── prompts/                # Coding agent prompts
│       ├── instructions/           # Implementation guide
│       └── specifications/         # All specs
└── tokens/                         # Bumba tokens (referenced by specs)
└── components/                     # Bumba components (referenced by specs)
```

## Commands Reference

Design Director provides 9 slash commands for guided workflow:

### 1. `/director-init` - Initialize Design Director

**Purpose**: Set up Design Director structure in `.design/bumba-design-director/`

**Prerequisites**:
- `.design/` directory must exist (run `/design-init` first)

**What it does**:
1. Creates directory structure
2. Copies utility libraries
3. Copies template files
4. Detects Bumba assets (config, tokens, components)
5. Displays integration status

**Example**:
```
/director-init

✓ Bumba Design Director initialized successfully!

Bumba Integration Status:
   Config: ✓ Found (framework: react)
   Tokens: ✓ Found (3 token files)
   Components: ✓ Found (12 components)

Next Steps:
   1. Start product planning: /director-vision
```

### 2. `/director-vision` - Define Product Vision

**Purpose**: Define product name, description, problems, and features

**Prerequisites**:
- Design Director initialized

**What it does**:
1. Asks product vision questions
2. References available Bumba tokens
3. Generates `product/product-overview.md`

**Example**:
```
/director-vision

What is your product name?
> TaskFlow

Describe your product in 2-3 sentences:
> TaskFlow is a collaborative task management platform that helps teams
> organize, prioritize, and track work. It combines simplicity with
> powerful automation to keep projects on track.

What problems does this product solve?
> - Teams lose track of tasks across multiple tools
> - Manual status updates waste time
> - Lack of visibility into project progress

What are the key features?
> - Kanban boards with drag-and-drop
> - Automated notifications and reminders
> - Real-time collaboration
> - Custom workflows

✓ Generated: product/product-overview.md
```

### 3. `/director-roadmap` - Break into Sections

**Purpose**: Define 3-5 development sections

**Prerequisites**:
- `product-overview.md` exists

**What it does**:
1. Asks for 3-5 section titles and descriptions
2. Auto-generates section IDs (slug format)
3. Generates `product/product-roadmap.md`

**Example**:
```
/director-roadmap

Section 1 Title:
> User Authentication

Section 1 Description:
> Complete user registration, login, password reset, and profile management

Section 2 Title:
> Task Management

Section 2 Description:
> Create, edit, organize, and track tasks with rich metadata

Section 3 Title:
> Team Collaboration

Section 3 Description:
> Real-time updates, comments, mentions, and notifications

✓ Generated section IDs:
   - user-authentication
   - task-management
   - team-collaboration

✓ Generated: product/product-roadmap.md
```

### 4. `/director-data-model` - Define Entities

**Purpose**: Define core entities, attributes, and relationships

**Prerequisites**:
- `product-roadmap.md` exists

**What it does**:
1. Consults data-modeling-best-practices skill
2. Asks for entity definitions
3. Generates `product/data-model/data-model.md`
4. Generates `product/data-model/types.ts`

**Example**:
```
/director-data-model

Entity 1 Name:
> User

Entity 1 Attributes:
> id: string
> email: string
> name: string
> createdAt: Date

Entity 2 Name:
> Task

Entity 2 Attributes:
> id: string
> title: string
> description: string
> status: 'todo' | 'in-progress' | 'done'
> assigneeId: string
> createdAt: Date

✓ Generated: product/data-model/data-model.md
✓ Generated: product/data-model/types.ts
```

### 5. `/director-shell-spec` - Specify Navigation

**Purpose**: Define navigation structure and layout pattern

**Prerequisites**:
- `product-roadmap.md` exists (for nav items)

**What it does**:
1. Offers 4 layout pattern options
2. Loads sections from roadmap for navigation
3. References Bumba layouts if available
4. Generates `product/shell/spec.md`

**Example**:
```
/director-shell-spec

Choose layout pattern:
1. Sidebar (persistent left nav)
2. Top Nav (horizontal header nav)
3. Tabs (tabbed interface)
4. Minimal (no persistent chrome)

> 1

Navigation items (auto-suggested from sections):
☑ Dashboard
☑ Tasks
☑ Team
☑ Settings

Additional nav items?
> Profile, Notifications

✓ Generated: product/shell/spec.md

Bumba Integration:
   Available layouts: .design/extracted-code/react/layouts/
   Sidebar.tsx, TopNav.tsx
```

### 6. `/director-section-spec` - Define Section Requirements

**Purpose**: Specify user flows and UI requirements for a section

**Prerequisites**:
- `product-roadmap.md` exists

**What it does**:
1. Loads sections from roadmap
2. Asks for user flows and UI requirements
3. References Bumba components if available
4. Generates `product/sections/[id]/spec.md`

**Example**:
```
/director-section-spec

Which section?
1. user-authentication
2. task-management
3. team-collaboration

> 2

User Flows (what users do):
> 1. User clicks "New Task" button
> 2. User fills in task form (title, description, assignee)
> 3. User clicks "Create Task"
> 4. Task appears in task list
> 5. User can drag task between columns to change status

UI Requirements:
> - Task list with kanban columns (Todo, In Progress, Done)
> - Task cards showing title, assignee avatar, due date
> - "New Task" button in header
> - Task detail modal for editing
> - Drag-and-drop between columns
> - Empty state for new boards

✓ Generated: product/sections/task-management/spec.md

Bumba Integration:
   Available components: .design/components/
   - Button.json
   - Modal.json
   - Card.json
```

### 7. `/director-sample-data` - Generate Sample Data

**Purpose**: Create realistic test data and TypeScript types

**Prerequisites**:
- Section spec exists for target section

**What it does**:
1. Offers 3 generation methods (auto, JSON, guided)
2. Generates `data.json`
3. Auto-generates `types.ts` via hook
4. Validates against data model

**Example**:
```
/director-sample-data

Which section?
> task-management

Choose generation method:
1. Auto-generate (from data model)
2. Provide JSON
3. Guided entry

> 2

Paste JSON:
> {
>   "tasks": [
>     {
>       "id": "task-1",
>       "title": "Design homepage mockup",
>       "description": "Create high-fidelity mockup in Figma",
>       "status": "in-progress",
>       "assigneeId": "user-1",
>       "createdAt": "2025-01-15T10:00:00Z"
>     }
>   ]
> }

✓ Generated: product/sections/task-management/data.json
✓ Auto-generated: product/sections/task-management/types.ts
   (via on-director-data-change hook)
```

### 8. `/director-screen-spec` - Add Screen Details

**Purpose**: Specify what screens do (functional requirements)

**Prerequisites**:
- Section spec exists
- Sample data recommended

**What it does**:
1. Loads existing section spec
2. Asks for screen specifications
3. Appends to spec (doesn't overwrite)
4. References Bumba components

**Example**:
```
/director-screen-spec

Which section?
> task-management

Screen name:
> Task Detail View

What data is displayed?
> - Task title
> - Task description
> - Assignee name and avatar
> - Status dropdown
> - Created date
> - Comments thread

What actions are available?
> - Edit title (inline)
> - Edit description (textarea)
> - Change assignee (dropdown)
> - Change status (dropdown)
> - Add comment
> - Delete task (with confirmation)

Success/error states:
> - Loading: Show skeleton UI
> - Error loading: Show error message with retry
> - Save success: Show toast notification
> - Save error: Show inline error, keep edits

✓ Updated: product/sections/task-management/spec.md
   (Screen Details section appended)
```

### 9. `/director-export` - Export Specification Package

**Purpose**: Generate implementation handoff package

**Prerequisites**:
- At least `product-overview.md` and `product-roadmap.md` exist

**What it does**:
1. Validates completeness (warns if incomplete)
2. Generates export package with framework-specific instructions
3. References Bumba assets in implementation guide
4. Creates coding agent prompts

**Example**:
```
/director-export

Completeness Check:
   ✓ product-overview.md
   ✓ product-roadmap.md
   ✓ data-model.md
   ✓ shell/spec.md
   ✓ 3 section specs

   Progress: 100% complete

✓ Export package generated!

Location: .design/bumba-design-director/product-plan/

Contents:
   README.md              Quick start guide
   prompts/               Coding agent prompts
   instructions/          Implementation guide
   specifications/        All markdown specs

Framework: react
Bumba Assets Referenced:
   - .design/tokens/ (3 files)
   - .design/components/ (12 components)
   - .design/extracted-code/react/

Next Steps:
   1. Review export package
   2. Copy to implementation project
   3. Use prompts with coding agent
```

## Workflow Guide

### Complete Planning Workflow

**Step 1: Initialize** (one-time)
```bash
/design-init                    # Initialize Bumba Design System
# Choose: Include Design Director? Yes
```

**Step 2: Define Vision**
```bash
/director-vision                # Product name, description, problems, features
```

**Step 3: Break into Sections**
```bash
/director-roadmap               # 3-5 development sections
```

**Step 4: Define Data Model**
```bash
/director-data-model            # Entities, attributes, relationships
```

**Step 5: Specify Shell**
```bash
/director-shell-spec            # Navigation structure, layout pattern
```

**Step 6: Specify Each Section** (repeat for each)
```bash
/director-section-spec          # User flows, UI requirements
/director-sample-data           # Realistic test data
/director-screen-spec           # Optional: detailed screen specs
```

**Step 7: Export**
```bash
/director-export                # Generate implementation package
```

### Quick Workflow (Minimal)

For rapid prototyping:

```bash
/director-vision                # Just vision
/director-roadmap               # Just sections
/director-export                # Export incomplete (with warnings)
```

### Iterative Workflow

Update specifications over time:

```bash
# Add new section to roadmap
/director-roadmap               # Append new section

# Update section spec
/director-section-spec          # Select section, update flows

# Add more screens
/director-screen-spec           # Append screen details

# Re-export
/director-export                # Updated package
```

## Troubleshooting

### Issue: "Error: .design/ directory not found"

**Cause**: Design Director requires Bumba Design System
**Solution**:
```bash
/design-init                    # Initialize Bumba first
/director-init                  # Then initialize Director
```

### Issue: "Error: product-overview.md not found"

**Cause**: Commands have prerequisites (linear workflow)
**Solution**: Follow command order:
```bash
/director-vision                # Creates product-overview.md
/director-roadmap               # Then this will work
```

### Issue: Types not auto-generating

**Cause**: Hook may not be enabled or data.json has syntax errors
**Solution**:
```bash
# Verify hook is enabled
ls .claude/hooks/on-director-data-change.js

# Validate JSON syntax
cat .design/bumba-design-director/product/sections/[id]/data.json | jq .

# Manually regenerate types
node .design/bumba-design-director/lib/type-generator.js
```

### Issue: Export says "incomplete"

**Cause**: Required specs are missing
**Solution**:
```bash
# Check what's missing
/director-export

# Progress: 60% complete
# Missing: data-model, shell, 2 sections

# Complete missing specs, then re-export
```

### Issue: No Bumba assets found

**Cause**: Bumba features haven't been run yet
**Solution**: This is normal! Design Director works standalone.

```
# Graceful fallback: Specs generated without asset references
# Message: "Design tokens will be defined separately using Bumba Design features"

# To add Bumba assets later:
/design-transform-react         # Extract components from Figma
# Then re-run /director-export (updated references)
```

## Best Practices

### Specification Writing

1. **Be Specific**: "List shows 20 items per page" not "List shows items"
2. **Be Actionable**: "User clicks 'Save' button" not "User saves data"
3. **Avoid Design Details**: "Display user name" not "Display user name in 16px Helvetica"
4. **Focus on What, Not How**: "Validate email format" not "Use regex /^[a-z].../"

### Data Modeling

1. **Start with Core Entities**: User, Product, Order (not UserSettings, ProductImage)
2. **Use TypeScript Types**: `status: 'pending' | 'shipped'` not `status: string`
3. **Model Relationships**: `userId: string` (foreign key) not `user: User` (embedded)
4. **Keep It Normalized**: Separate entities, don't duplicate data

### Workflow Optimization

1. **Complete Vision First**: Foundation for all other specs
2. **Don't Over-Specify**: Partial specs are OK, iterate later
3. **Use Sample Data**: Makes specs concrete and testable
4. **Version Control Specs**: Team collaboration, history, rollback

## FAQ

**Q: Can I use Design Director without Bumba Design System?**
A: Yes! Design Director works standalone with graceful fallbacks. Specs will have generic component instructions instead of Bumba asset references.

**Q: Can I edit the generated specs?**
A: Yes! All specs are markdown files. Edit directly, hooks will validate on save.

**Q: What if I skip a command (e.g., shell spec)?**
A: Export will warn about incompleteness but allow partial export. Complete missing specs later.

**Q: Can I use this for non-web products?**
A: Yes! Data models and user flows are framework-agnostic. Export instructions adapt to framework preference.

**Q: How do I share specs with non-technical stakeholders?**
A: Specs are plain markdown - readable by anyone. Export to PDF or host on wiki.

**Q: Can I integrate with other tools (Jira, Notion)?**
A: Yes! Copy specs to any tool that accepts markdown. Sample data is JSON (universal).

## Version

- Design Director: 1.0.0
- Bumba Design Integration: Compatible with Bumba Design System 4.0.0+
- Node.js: Requires Node.js 14+
- Dependencies: fs, path, Handlebars (installed automatically)

---

**Built with Bumba Design System**

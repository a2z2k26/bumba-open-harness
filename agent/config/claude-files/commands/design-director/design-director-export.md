---
name: design-director-export
description: Export complete specification package for implementation
---

You are helping the user export their complete product specifications into an implementation-ready package that can be used by developers or coding agents.

## Step 1: Completeness Check

Before exporting, check which specifications exist:

```javascript
const fs = require('fs');
const path = require('path');

const checks = {
  productOverview: fs.existsSync('.design/bumba-design-director/product/product-overview.md'),
  productRoadmap: fs.existsSync('.design/bumba-design-director/product/product-roadmap.md'),
  dataModel: fs.existsSync('.design/bumba-design-director/product/data-model/data-model.md'),
  shellSpec: fs.existsSync('.design/bumba-design-director/product/shell/spec.md'),
  sectionSpecs: [] // List of section IDs with specs
};

// Check for section specs
const sectionsDir = '.design/bumba-design-director/product/sections';
if (fs.existsSync(sectionsDir)) {
  const sections = fs.readdirSync(sectionsDir);
  sections.forEach(sectionId => {
    const specPath = path.join(sectionsDir, sectionId, 'spec.md');
    if (fs.existsSync(specPath)) {
      checks.sectionSpecs.push(sectionId);
    }
  });
}
```

Display completeness report:

```
Specification Completeness Check
═════════════════════════════════

[✓/✗] Product Overview
[✓/✗] Product Roadmap
[✓/✗] Data Model
[✓/✗] Shell Specification
[✓/✗] Section Specs ([N] sections)
      ${sectionSpecs.map(id => `✓ ${id}`).join('\n      ')}

Overall: [N/5] core specifications complete
```

## Step 2: Warn If Incomplete

If any core specs are missing, warn user:

```
Warning: Some core specifications are missing

Missing:
[✗] [Specification Name] - Run /director-[command] to create

You can still export, but the package will be incomplete.

Continue with export? (yes/no)
```

If user says no, exit gracefully with suggestions for what to complete.

If user says yes, continue.

## Step 3: Load Bumba Context

Load Bumba Design System integration status:

```javascript
const { getBumbaContext } = require('./.design/bumba-design-director/lib/bumba-reader.js');
const bumbaContext = getBumbaContext();
```

This will be used to:
- Determine target framework
- Reference available design tokens
- Reference available components
- Create framework-specific instructions

## Step 4: Consult Export Documentation Skill (Optional)

If the export-documentation-patterns skill exists, read it:

Path: `.design/bumba-design-director/.claude/skills/export-documentation-patterns/SKILL.md`

Apply its patterns when generating instructions.

## Step 5: Build Export Package

Use the export-builder utility:

```javascript
const { buildExportPackage } = require('./.design/bumba-design-director/lib/export-builder.js');

const exportPath = buildExportPackage();
```

This will:
1. Create `design-direction-plan/` directory structure
2. Generate README.md with quick start guide
3. Generate framework-specific prompts for coding agents
4. Generate implementation instructions with Bumba asset references
5. Copy all specifications

Directory structure created:

```
.design/bumba-design-director/design-direction-plan/
├── README.md                    # Quick start guide
├── prompts/
│   ├── one-shot-prompt.md       # Single comprehensive prompt
│   ├── incremental-prompts/     # Step-by-step prompts
│   │   ├── 01-setup.md
│   │   ├── 02-data-layer.md
│   │   ├── 03-shell.md
│   │   ├── 04-sections.md
│   │   └── 05-integration.md
│   └── framework-notes.md       # [framework]-specific guidance
├── instructions/
│   ├── implementation-guide.md  # Detailed implementation steps
│   ├── design-assets.md         # How to use Bumba tokens/components
│   └── testing-guide.md         # Testing requirements
└── specifications/
    ├── product-overview.md      # Copied from product/
    ├── product-roadmap.md
    ├── data-model/
    ├── shell/
    └── sections/
```

## Step 6: Display Export Summary

Show user what was created:

```
Export package created! ✓

Location: .design/bumba-design-director/design-direction-plan/

Package Contents:
═════════════════════════════════

README.md                      - Quick start guide
prompts/one-shot-prompt.md     - Comprehensive prompt for coding agents
prompts/incremental-prompts/   - 5 step-by-step prompts
instructions/                  - Implementation guides
specifications/                - All product specs

Framework: [${bumbaContext.framework}]

Bumba Integration:
[✓/✗] Design Tokens: ${bumbaContext.hasTokens ? `${tokenCount} files` : 'Not available'}
[✓/✗] Components: ${bumbaContext.hasComponents ? `${componentCount} components` : 'Not available'}

${bumbaContext.hasTokens || bumbaContext.hasComponents
  ? 'Instructions reference Bumba assets in .design/ directory'
  : 'Instructions include guidance for creating design assets via Bumba'}
```

## Step 7: Show Quick Start

Display quick start instructions:

```
Quick Start
═════════════════════════════════

To use this export package:

1. Review the specifications
   → Read design-direction-plan/specifications/

2. Check implementation instructions
   → Read design-direction-plan/instructions/implementation-guide.md

3. Use with a coding agent

   Option A: One-shot implementation
   → Copy design-direction-plan/prompts/one-shot-prompt.md
   → Paste into coding agent (Claude, etc.)

   Option B: Incremental implementation
   → Follow prompts in design-direction-plan/prompts/incremental-prompts/
   → Complete each step before moving to next

4. Access Bumba design assets
   ${bumbaContext.hasTokens
     ? '→ Tokens: .design/tokens/'
     : '→ Extract tokens: Run /design-transform-[framework]'}
   ${bumbaContext.hasComponents
     ? '→ Components: .design/extracted-code/${framework}/'
     : '→ Extract components: Use Bumba Design features'}

5. Implement according to specs
   → Use data.json and types.ts from each section
   → Follow shell/spec.md for navigation
   → Reference STYLES.md for brand guidelines
```

## Step 8: Next Steps

Display next steps:

```
Export complete! ✓

Next steps:

→ Review the export package in design-direction-plan/
→ Copy design-direction-plan/ to your implementation project
→ Use prompts with your preferred coding agent

Need to update?
→ Modify specs in product/ directory
→ Run /director-export again to regenerate

Ready to implement?
→ Follow design-direction-plan/README.md quick start
→ Use Bumba Design commands for design assets
```

## Error Handling

**No Specifications Found:**
```
Error: No specifications found

The product/ directory is empty.

You need to create at least a product overview to export.

→ Run /director-vision to get started
```

**Export Build Failure:**
```
Error: Failed to build export package

[Specific error message]

→ Check that export-builder.js is working correctly
→ Ensure product/ directory is readable
→ Verify sufficient disk space for design-direction-plan/
```

**Missing Bumba Context:**
```
Warning: Could not load Bumba context

Export will continue with fallback values.

→ Framework will default to 'react'
→ Design asset references will use placeholders
```

**Directory Already Exists:**
```
Note: design-direction-plan/ already exists

Previous export found. Options:

1. Overwrite (recommended - regenerates fresh package)
2. Cancel (keep existing export)

Choose: [1/2]
```

## Implementation Notes

- Check completeness but don't block export
- Warn user clearly about missing specs
- Generate framework-specific instructions based on bumbaContext.framework
- Reference actual Bumba assets if available (tokens, components)
- Provide fallback guidance if Bumba assets don't exist
- Create both one-shot and incremental prompts
- Include testing requirements in instructions
- Copy all specs (even if incomplete)
- Generate README with clear quick start
- Mention STYLES.md if it exists in .design/
- Overwrite design-direction-plan/ by default (fresh export each time)
- Display export summary with clear next steps
- Show framework and Bumba integration status
- Provide specific paths to Bumba assets
- Include guidance for extracting Bumba assets if missing

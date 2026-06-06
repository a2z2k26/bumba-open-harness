# Bumba Design Director Templates

This directory contains the master templates for Bumba Design Director - a CLI-based specification generator that integrates with the Bumba Design System.

## Purpose

Design Director generates hyper-detailed product specifications WITHOUT creating tangible design assets (tokens, components, layouts). All design assets are created via existing Bumba Design features.

## Directory Structure

```
design-director-templates/
├── lib/                    # Utility libraries
│   ├── bumba-reader.js     # Read Bumba config, tokens, components
│   ├── spec-generator.js   # Generate markdown specs from templates
│   ├── type-generator.js   # Generate TypeScript types from JSON
│   └── export-builder.js   # Build export package
├── templates/              # Handlebars templates
│   ├── product-overview.md.tmpl
│   ├── product-roadmap.md.tmpl
│   ├── section-spec.md.tmpl
│   ├── shell-spec.md.tmpl
│   └── export-instructions.md.tmpl
├── .claude/
│   ├── commands/           # Director slash commands (9 total)
│   ├── skills/             # Reusable expertise guides (2-3)
│   └── hooks/              # Automation hooks (3)
└── README.md               # This file
```

## Installation

These templates are copied to `.design/bumba-design-director/` when a user runs `/design-init` and chooses to include Design Director.

## Architecture

- **Commands**: User-initiated workflow steps (vision, roadmap, data model, etc.)
- **Hooks**: Automated reactions to file changes (type regeneration, status tracking)
- **Skills**: Reusable domain expertise (specification writing, data modeling)
- **Utilities**: Pure transformation functions (no workflow logic)

## Integration with Bumba

Design Director reads from:
- `.design/config.json` - Framework preference
- `.design/tokens/` - Design tokens (if available)
- `.design/components/` - Component metadata (if available)

Design Director generates:
- `.design/bumba-design-director/product/` - Markdown specifications
- `.design/bumba-design-director/product-plan/` - Export package with implementation instructions

## Key Principle

**Specification Only**: Design Director does NOT create design tokens, components, or layouts. It generates specifications that REFERENCE Bumba-generated assets.

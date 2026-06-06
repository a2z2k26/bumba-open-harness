---
name: design-generate-styles
description: Generate STYLES.md brand guide from design tokens and components
allowed-tools: Read, Write, Bash
---

# Generate Brand Style Guide

Generate a human-readable `STYLES.md` file from the project's design tokens and components.

## What This Command Does

1. Reads all design tokens from `.design/tokens/`
2. Reads all component definitions from `.design/components/`
3. Generates a comprehensive `STYLES.md` with:
   - Color palette with usage guidelines
   - Typography styles with font stacks
   - Spacing scale
   - Effects (shadows)
   - Border radius values
   - Available components and their variants
   - Ready-to-use CSS variables block
   - Usage guidelines and best practices

## Execution

Run the generator:

```bash
node "$PROJECT_PATH/server/styles-md-generator.js" "$PROJECT_PATH"
```

Where `$PROJECT_PATH` is the current working directory.

## Output

The command creates/updates `.design/STYLES.md` which serves as:
- A quick reference for designers and developers
- Context for AI assistants generating branded content
- Documentation for the design system

## When to Run

- After extracting tokens from Figma
- After adding or updating components
- Before generating branded documents
- When onboarding new team members

## Example Output

```markdown
# Brand Style Guide

## Color Palette
| Token | Value | CSS Variable | Usage |
|-------|-------|--------------|-------|
| primary | #00aa00 | --color-primary | Brand identity, CTAs, headings |
| secondary | #66bb00 | --color-secondary | Accents, highlights, links |

## Typography
| Style | Font Family | Weight | Size | Usage |
|-------|-------------|--------|------|-------|
| Heading | Plantin MT Pro | 400 | 72px | Page titles, hero text |
| Body | Apertura | 500 | 16px | Paragraphs, UI text |

...
```

After running, inform the user of the generated file location and statistics.

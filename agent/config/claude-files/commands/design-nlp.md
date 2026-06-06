---
name: design-nlp
description: Generate design components from natural language descriptions with creative interpretation
allowed-tools: Read, Write, Bash, Glob
---

# Design NLP

Generate Design Bridge components from natural language descriptions with bold creative vision.

## What This Does

This command invokes the `bumba-nlp-design` skill to create distinctive, production-grade components from your descriptions. Unlike extraction from Figma or ShadCN, here Claude acts as the designer - interpreting your words creatively and generating components that integrate seamlessly with your Design Bridge registry.

## Usage

Describe the component you want to create:

```
/design-nlp a testimonial card with quote, author photo, and company logo
/design-nlp a pricing tier component with plan name, price, feature list, and CTA
/design-nlp a notification badge that shows count and pulses when new
/design-nlp a stat card showing metric, trend indicator, and sparkline
/design-nlp a hero section with gradient background and animated text
```

## What Makes This Different

- **Creative Generation**: Claude designs the component, applying bold aesthetic principles
- **Registry Integration**: Output writes directly to `.design/components/` and updates the registry
- **Token Alignment**: Uses your existing design tokens where possible
- **Component References**: Can reference other registry components as children

## Prerequisites

- Design Bridge initialized (`.design/` directory exists)
- Design tokens defined in `.design/tokens/` (optional but recommended)

## Output

Creates:
- Component definition at `.design/components/[ComponentName].json`
- Registry entry in `.design/componentRegistry.json` with `source.type: "nlp-prompt"`

The component is ready for transformation to your target framework.

## Creative Philosophy

Components are generated with:
- **Distinctive Typography**: No generic fonts, characterful choices
- **Bold Color Application**: Dominant colors with sharp accents
- **Intentional Shape**: Purposeful border radius, asymmetric spacing
- **Motion Intent**: Animation specifications for GSAP/Framer Motion

## Process

1. Parse your natural language description
2. Check registry for existing components to reference
3. Apply creative design principles
4. Generate complete component definition with structure, tokens, variants, props
5. Write to Design Bridge registry
6. Suggest next steps (transformation, additional variants)

## Request

$ARGUMENTS

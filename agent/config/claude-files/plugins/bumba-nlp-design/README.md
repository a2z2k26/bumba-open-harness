# Bumba NLP Design Plugin

Generate distinctive Design Bridge components from natural language descriptions.

## What It Does

This skill transforms natural language descriptions into Design Bridge compatible components. Unlike extraction from Figma or ShadCN, here Claude acts as the designer - creating bold, memorable components from scratch that integrate seamlessly with your existing registry.

When you describe what you want, Claude will:

1. **Interpret creatively** - Apply distinctive aesthetic vision to your description
2. **Generate component structure** - Build complete element hierarchies
3. **Define variants and states** - Create useful variations and interactive states
4. **Integrate with registry** - Write output to `.design/` and update componentRegistry.json
5. **Reference existing components** - Use your registry's existing assets where appropriate

## When It Activates

This skill triggers when you want to CREATE components from descriptions:
- "Generate a testimonial card"
- "Create a pricing component with..."
- "Design a button that has..."
- "I need a component for showing user stats"
- "Make me a notification badge"

## When NOT to Use

Don't use this for:
- Extracting from Figma (use Figma MCP)
- Extracting from ShadCN (use ShadCN MCP)
- Composing existing components into layouts (use bumba-frontend-design)

## Output

Generated components are written to:
- `.design/components/{ComponentName}.json` - Full component definition
- `.design/componentRegistry.json` - Registry entry added

Components include:
- Unique ID with `nlp-` prefix
- Complete structure hierarchy
- Token dependencies aligned with existing tokens
- Variants with token overrides
- TypeScript-typed props
- Interactive states
- Animation intent

## Creative Philosophy

This plugin embodies bold design principles:

- **Typography**: Distinctive fonts, never generic defaults
- **Color**: Dominant colors with sharp accents
- **Shape**: Intentional border radius, asymmetric spacing
- **Motion**: Every component designed with animation in mind

## Based On

This plugin combines Anthropic's Frontend Design Skill creative principles with Bumba Design Bridge registry integration.

## Related Plugins

- **bumba-frontend-design** - For composing existing components into layouts
- **frontend-design** - Original Anthropic skill for general frontend work

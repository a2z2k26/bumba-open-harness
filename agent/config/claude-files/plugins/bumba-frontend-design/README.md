# Bumba Frontend Design Plugin

Creates distinctive, production-grade frontend interfaces using the Bumba Design Bridge system.

## What It Does

This skill combines bold aesthetic principles with Design Bridge awareness. When building interfaces, Claude will:

1. **Check the Design Bridge registries** for available components, layouts, and tokens
2. **Apply distinctive design thinking** with bold typography, color, and spatial choices
3. **Orchestrate motion** using GSAP and Framer Motion
4. **Compose layouts** using registry components creatively
5. **Implement production-ready code** with meticulous attention to detail

## When It Activates

This skill triggers automatically when:
- Working with the `.design/` directory structure
- Building pages, screens, dashboards, or landing pages
- Composing layouts from extracted components
- Referencing Design Bridge, Bumba, or component registries
- Requesting distinctive, memorable, or high-quality design

## Usage

```
"Build a dashboard using the components in my Design Bridge registry"
"Create a landing page with the Button and Card components I extracted"
"Design a settings panel using my transformed components"
"Compose a hero section using the layout from Figma"
```

Claude will read your `.design/componentRegistry.json`, `.design/layoutManifest.json`, and `.design/tokens/`, then compose them into memorable interfaces.

## Key Features

### Design Bridge Integration
- Reads component registry automatically
- Uses transformed components from `.design/extracted-code/`
- References layouts from `.design/layouts/`
- Respects design tokens from `.design/tokens/`
- Aware of component variants and states

### Enhanced Design Guidelines
- **Typography Hierarchy**: Display, headings, body, captions with intentional scale
- **Color Philosophy**: Dominant colors with sharp accents, CSS variable systems
- **Motion Design**: GSAP for orchestration, Framer Motion for interactions
- **Spatial Composition**: Asymmetry, overlap, grid-breaking, negative space
- **Micro-Interactions**: Comprehensive state definitions and feedback patterns
- **Responsive Thinking**: Adaptive aesthetics across breakpoints

## Animation Libraries

The skill includes specific guidance for:

- **GSAP**: Timeline sequences, ScrollTrigger, physics-based motion
- **Framer Motion**: Component animations, gestures, layout transitions

## Based On

This plugin is based on Anthropic's Frontend Design Skill by Prithvi Rajasekaran and Alexander Bricken, enhanced with Bumba Design Bridge system awareness and expanded design guidelines.

## Learn More

- [Frontend Aesthetics Cookbook](https://github.com/anthropics/claude-cookbooks/blob/main/coding/prompting_for_frontend_aesthetics.ipynb)
- [Design Bridge Documentation](./docs/)

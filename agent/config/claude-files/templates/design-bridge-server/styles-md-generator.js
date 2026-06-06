/**
 * styles-md-generator.js
 * Generates a human-readable STYLES.md brand guide from design tokens and components
 *
 * This module creates a pre-compiled brand reference that:
 * - Provides semantic context for when/how to use each token
 * - Lists available components with their variants
 * - Reduces context overhead for AI assistants
 * - Stays in sync with the .design/ directory
 *
 * @version 1.0.0
 */

const fs = require('fs');
const path = require('path');

class StylesMdGenerator {
  constructor(options = {}) {
    this.projectPath = options.projectPath || process.cwd();
    this.designPath = path.join(this.projectPath, '.design');
    this.tokensPath = path.join(this.designPath, 'tokens');
    this.componentsPath = path.join(this.designPath, 'components');
    this.outputPath = path.join(this.designPath, 'STYLES.md');
  }

  /**
   * Generate the STYLES.md file
   * @returns {Object} Result with success status and file path
   */
  async generate() {
    try {
      // Load tokens and components
      const tokens = await this.loadTokens();
      const components = await this.loadComponents();

      if (!tokens && !components) {
        return {
          success: false,
          error: 'No tokens or components found in .design/ directory'
        };
      }

      // Generate markdown content
      const markdown = this.generateMarkdown(tokens, components);

      // Write file
      fs.writeFileSync(this.outputPath, markdown, 'utf8');

      return {
        success: true,
        path: this.outputPath,
        stats: {
          colors: tokens?.colors ? Object.keys(tokens.colors).length : 0,
          typography: tokens?.typography ? Object.keys(tokens.typography).length : 0,
          spacing: tokens?.spacing ? Object.keys(tokens.spacing).length : 0,
          effects: tokens?.effects ? Object.keys(tokens.effects).length : 0,
          components: components ? components.length : 0
        }
      };
    } catch (error) {
      return {
        success: false,
        error: error.message
      };
    }
  }

  /**
   * Load all token files from .design/tokens/
   * @returns {Object|null} Merged tokens object
   */
  async loadTokens() {
    if (!fs.existsSync(this.tokensPath)) {
      return null;
    }

    const files = fs.readdirSync(this.tokensPath)
      .filter(f => f.endsWith('.json'));

    if (files.length === 0) {
      return null;
    }

    // Merge all token files
    const merged = {
      colors: {},
      typography: {},
      spacing: {},
      effects: {},
      borderRadius: {},
      metadata: {}
    };

    for (const file of files) {
      try {
        const content = fs.readFileSync(path.join(this.tokensPath, file), 'utf8');
        const data = JSON.parse(content);
        const tokens = data.tokens || data;

        // Merge each category
        if (tokens.colors) Object.assign(merged.colors, tokens.colors);
        if (tokens.typography) Object.assign(merged.typography, tokens.typography);
        if (tokens.spacing) Object.assign(merged.spacing, tokens.spacing);
        if (tokens.effects) Object.assign(merged.effects, tokens.effects);
        if (tokens.borderRadius) Object.assign(merged.borderRadius, tokens.borderRadius);
        if (tokens.metadata || data.metadata) {
          merged.metadata = { ...merged.metadata, ...(tokens.metadata || data.metadata) };
        }
      } catch (e) {
        console.warn(`[styles-md-generator] Failed to parse ${file}: ${e.message}`);
      }
    }

    return merged;
  }

  /**
   * Load all component definitions from .design/components/
   * @returns {Array|null} Array of component objects
   */
  async loadComponents() {
    if (!fs.existsSync(this.componentsPath)) {
      return null;
    }

    const components = [];
    const entries = fs.readdirSync(this.componentsPath, { withFileTypes: true });

    for (const entry of entries) {
      try {
        let componentData = null;

        if (entry.isDirectory()) {
          // Look for component.json inside directory
          const componentFile = path.join(this.componentsPath, entry.name, 'component.json');
          if (fs.existsSync(componentFile)) {
            componentData = JSON.parse(fs.readFileSync(componentFile, 'utf8'));
          }
        } else if (entry.name.endsWith('.json')) {
          // Direct JSON file
          const content = fs.readFileSync(path.join(this.componentsPath, entry.name), 'utf8');
          componentData = JSON.parse(content);
        }

        if (componentData) {
          components.push(componentData);
        }
      } catch (e) {
        console.warn(`[styles-md-generator] Failed to load component ${entry.name}: ${e.message}`);
      }
    }

    return components.length > 0 ? components : null;
  }

  /**
   * Generate the complete STYLES.md markdown content
   * @param {Object} tokens - Design tokens
   * @param {Array} components - Component definitions
   * @returns {string} Markdown content
   */
  generateMarkdown(tokens, components) {
    const sections = [];

    // Header
    sections.push(this.generateHeader(tokens));

    // Color Palette
    if (tokens?.colors && Object.keys(tokens.colors).length > 0) {
      sections.push(this.generateColorSection(tokens.colors));
    }

    // Typography
    if (tokens?.typography && Object.keys(tokens.typography).length > 0) {
      sections.push(this.generateTypographySection(tokens.typography));
    }

    // Spacing
    if (tokens?.spacing && Object.keys(tokens.spacing).length > 0) {
      sections.push(this.generateSpacingSection(tokens.spacing));
    }

    // Effects (Shadows)
    if (tokens?.effects && Object.keys(tokens.effects).length > 0) {
      sections.push(this.generateEffectsSection(tokens.effects));
    }

    // Border Radius
    if (tokens?.borderRadius && Object.keys(tokens.borderRadius).length > 0) {
      sections.push(this.generateBorderRadiusSection(tokens.borderRadius));
    }

    // Components
    if (components && components.length > 0) {
      sections.push(this.generateComponentsSection(components));
    }

    // CSS Variables Reference
    sections.push(this.generateCSSVariablesSection(tokens));

    // Usage Guidelines
    sections.push(this.generateUsageGuidelines(tokens, components));

    // Footer
    sections.push(this.generateFooter());

    return sections.join('\n\n');
  }

  /**
   * Generate header section
   */
  generateHeader(tokens) {
    const brandName = tokens?.metadata?.fileName || 'Brand';
    const date = new Date().toISOString().split('T')[0];

    return `# ${brandName} Style Guide

> Auto-generated from design tokens and components
> Last updated: ${date}

This document provides a comprehensive reference for the brand's design system.
Use these tokens and components to maintain visual consistency across all materials.

---`;
  }

  /**
   * Generate color palette section with semantic usage hints
   */
  generateColorSection(colors) {
    const lines = [
      '## Color Palette',
      '',
      '| Token | Value | CSS Variable | Usage |',
      '|-------|-------|--------------|-------|'
    ];

    for (const [name, color] of Object.entries(colors)) {
      const value = color.value || color;
      const cssVar = `--color-${this.toKebabCase(name)}`;
      const usage = this.inferColorUsage(name, value);

      lines.push(`| ${name} | \`${value}\` | \`${cssVar}\` | ${usage} |`);
    }

    // Add color swatches reference
    lines.push('');
    lines.push('### Quick Reference');
    lines.push('');

    for (const [name, color] of Object.entries(colors)) {
      const value = color.value || color;
      lines.push(`- **${name}**: ${value}`);
    }

    return lines.join('\n');
  }

  /**
   * Generate typography section
   */
  generateTypographySection(typography) {
    const lines = [
      '## Typography',
      '',
      '| Style | Font Family | Weight | Size | CSS Variable | Usage |',
      '|-------|-------------|--------|------|--------------|-------|'
    ];

    for (const [name, style] of Object.entries(typography)) {
      const family = style.fontFamily || 'system-ui';
      const weight = style.fontWeight || 400;
      const size = style.fontSize || '16px';
      const cssVar = `--font-${this.toKebabCase(name)}`;
      const usage = this.inferTypographyUsage(name);

      lines.push(`| ${this.capitalize(name)} | ${family} | ${weight} | ${size} | \`${cssVar}-*\` | ${usage} |`);
    }

    // Add font stack recommendations
    lines.push('');
    lines.push('### Font Stacks');
    lines.push('');

    const families = new Set();
    for (const style of Object.values(typography)) {
      if (style.fontFamily) families.add(style.fontFamily);
    }

    for (const family of families) {
      lines.push(`- **${family}**: \`"${family}", system-ui, sans-serif\``);
    }

    return lines.join('\n');
  }

  /**
   * Generate spacing section
   */
  generateSpacingSection(spacing) {
    const lines = [
      '## Spacing',
      '',
      '| Token | Value | CSS Variable | Usage |',
      '|-------|-------|--------------|-------|'
    ];

    for (const [name, value] of Object.entries(spacing)) {
      const cssVar = `--spacing-${name}`;
      const usage = this.inferSpacingUsage(name, value);

      lines.push(`| ${name} | \`${value}\` | \`${cssVar}\` | ${usage} |`);
    }

    return lines.join('\n');
  }

  /**
   * Generate effects (shadows) section
   */
  generateEffectsSection(effects) {
    const lines = [
      '## Effects & Shadows',
      '',
      '| Token | CSS Variable | Value | Usage |',
      '|-------|--------------|-------|-------|'
    ];

    for (const [name, effect] of Object.entries(effects)) {
      const cssVar = `--shadow-${this.toKebabCase(name).replace('shadow-', '')}`;
      const cssValue = this.effectToCSS(effect);
      const usage = this.inferEffectUsage(name);

      lines.push(`| ${name} | \`${cssVar}\` | \`${cssValue}\` | ${usage} |`);
    }

    return lines.join('\n');
  }

  /**
   * Generate border radius section
   */
  generateBorderRadiusSection(borderRadius) {
    const lines = [
      '## Border Radius',
      '',
      '| Token | Value | CSS Variable | Usage |',
      '|-------|-------|--------------|-------|'
    ];

    for (const [name, value] of Object.entries(borderRadius)) {
      const cssVar = `--radius-${this.toKebabCase(name)}`;
      const usage = this.inferRadiusUsage(name, value);

      lines.push(`| ${name} | \`${value}\` | \`${cssVar}\` | ${usage} |`);
    }

    return lines.join('\n');
  }

  /**
   * Generate components section
   */
  generateComponentsSection(components) {
    const lines = [
      '## Available Components',
      '',
      'The following components are available in the design system:',
      ''
    ];

    for (const component of components) {
      const name = component.name || component.componentName || 'Unknown';
      const variants = this.extractVariants(component);
      const props = this.extractProps(component);

      lines.push(`### ${name}`);
      lines.push('');

      if (component.description) {
        lines.push(`${component.description}`);
        lines.push('');
      }

      if (variants.length > 0) {
        lines.push(`**Variants:** ${variants.join(', ')}`);
      }

      if (props.length > 0) {
        lines.push(`**Props:** ${props.join(', ')}`);
      }

      lines.push('');
    }

    return lines.join('\n');
  }

  /**
   * Generate CSS variables reference section
   */
  generateCSSVariablesSection(tokens) {
    const lines = [
      '## CSS Variables Reference',
      '',
      'Copy this block into your styles to use the design tokens:',
      '',
      '```css',
      ':root {'
    ];

    // Colors
    if (tokens?.colors) {
      lines.push('  /* Colors */');
      for (const [name, color] of Object.entries(tokens.colors)) {
        const value = color.value || color;
        lines.push(`  --color-${this.toKebabCase(name)}: ${value};`);
      }
      lines.push('');
    }

    // Typography
    if (tokens?.typography) {
      lines.push('  /* Typography */');
      for (const [name, style] of Object.entries(tokens.typography)) {
        const prefix = `--font-${this.toKebabCase(name)}`;
        if (style.fontFamily) lines.push(`  ${prefix}-family: "${style.fontFamily}";`);
        if (style.fontWeight) lines.push(`  ${prefix}-weight: ${style.fontWeight};`);
        if (style.fontSize) lines.push(`  ${prefix}-size: ${style.fontSize};`);
      }
      lines.push('');
    }

    // Spacing
    if (tokens?.spacing) {
      lines.push('  /* Spacing */');
      for (const [name, value] of Object.entries(tokens.spacing)) {
        lines.push(`  --spacing-${name}: ${value};`);
      }
      lines.push('');
    }

    // Border Radius
    if (tokens?.borderRadius) {
      lines.push('  /* Border Radius */');
      for (const [name, value] of Object.entries(tokens.borderRadius)) {
        lines.push(`  --radius-${this.toKebabCase(name)}: ${value};`);
      }
      lines.push('');
    }

    // Effects
    if (tokens?.effects) {
      lines.push('  /* Shadows */');
      for (const [name, effect] of Object.entries(tokens.effects)) {
        const cssValue = this.effectToCSS(effect);
        const varName = this.toKebabCase(name).replace('shadow-', '');
        lines.push(`  --shadow-${varName}: ${cssValue};`);
      }
    }

    lines.push('}');
    lines.push('```');

    return lines.join('\n');
  }

  /**
   * Generate usage guidelines section
   */
  generateUsageGuidelines(tokens, components) {
    const lines = [
      '## Usage Guidelines',
      '',
      '### Color Usage',
      ''
    ];

    // Infer primary/secondary usage
    if (tokens?.colors?.primary) {
      lines.push('- **Primary color** (`--color-primary`): Use for main CTAs, headings, brand identity elements');
    }
    if (tokens?.colors?.secondary) {
      lines.push('- **Secondary color** (`--color-secondary`): Use for accents, highlights, secondary actions');
    }
    if (tokens?.colors?.success) {
      lines.push('- **Success color** (`--color-success`): Use for success states, confirmations, positive feedback');
    }
    if (tokens?.colors?.warning) {
      lines.push('- **Warning color** (`--color-warning`): Use for warnings, cautions, attention-needed states');
    }
    if (tokens?.colors?.error) {
      lines.push('- **Error color** (`--color-error`): Use for error states, destructive actions, validation errors');
    }

    lines.push('');
    lines.push('### Typography Usage');
    lines.push('');

    if (tokens?.typography?.heading) {
      lines.push('- **Heading**: Page titles, section headers, hero text');
    }
    if (tokens?.typography?.body) {
      lines.push('- **Body**: Paragraphs, UI text, descriptions');
    }
    if (tokens?.typography?.caption) {
      lines.push('- **Caption**: Labels, metadata, timestamps, code snippets');
    }

    lines.push('');
    lines.push('### General Principles');
    lines.push('');
    lines.push('1. **Consistency**: Always use CSS variables instead of hardcoded values');
    lines.push('2. **Hierarchy**: Use heading styles for titles, body for content');
    lines.push('3. **Contrast**: Ensure sufficient contrast for accessibility');
    lines.push('4. **Spacing**: Use spacing tokens for consistent rhythm');

    return lines.join('\n');
  }

  /**
   * Generate footer
   */
  generateFooter() {
    return `---

*This file is auto-generated by BUMBA Design. Do not edit manually.*
*Run \`/design-generate-styles\` to regenerate after token or component changes.*`;
  }

  // ============ Helper Methods ============

  /**
   * Convert string to kebab-case
   */
  toKebabCase(str) {
    return str
      .replace(/([a-z])([A-Z])/g, '$1-$2')
      .replace(/[\s_]+/g, '-')
      .toLowerCase();
  }

  /**
   * Capitalize first letter
   */
  capitalize(str) {
    return str.charAt(0).toUpperCase() + str.slice(1);
  }

  /**
   * Infer color usage based on name
   */
  inferColorUsage(name, value) {
    const nameLower = name.toLowerCase();

    if (nameLower === 'primary') return 'Brand identity, CTAs, headings';
    if (nameLower === 'secondary') return 'Accents, highlights, links';
    if (nameLower === 'success') return 'Success states, confirmations';
    if (nameLower === 'warning') return 'Warnings, cautions';
    if (nameLower === 'error' || nameLower === 'danger') return 'Error states, destructive actions';
    if (nameLower.includes('background') || nameLower.includes('bg')) return 'Background surfaces';
    if (nameLower.includes('text') || nameLower.includes('foreground')) return 'Text content';
    if (nameLower.includes('border')) return 'Borders, dividers';
    if (nameLower.includes('muted') || nameLower.includes('subtle')) return 'Subtle accents, disabled states';

    // Check if it's a gray/neutral
    if (value && /^#[def]/i.test(value)) return 'Light backgrounds, borders';
    if (value && /^#[0-3]/i.test(value)) return 'Dark text, dark backgrounds';

    return 'General use';
  }

  /**
   * Infer typography usage based on name
   */
  inferTypographyUsage(name) {
    const nameLower = name.toLowerCase();

    if (nameLower.includes('heading') || nameLower.includes('title') || nameLower.includes('h1')) {
      return 'Page titles, hero text';
    }
    if (nameLower.includes('subheading') || nameLower.includes('h2')) {
      return 'Section headers';
    }
    if (nameLower.includes('body') || nameLower.includes('paragraph')) {
      return 'Paragraphs, UI text';
    }
    if (nameLower.includes('caption') || nameLower.includes('small')) {
      return 'Labels, metadata';
    }
    if (nameLower.includes('mono') || nameLower.includes('code')) {
      return 'Code snippets, technical text';
    }
    if (nameLower.includes('display')) {
      return 'Large display text, banners';
    }

    return 'General typography';
  }

  /**
   * Infer spacing usage based on name/value
   */
  inferSpacingUsage(name, value) {
    const px = parseInt(value);

    if (px <= 4) return 'Tight spacing, inline elements';
    if (px <= 8) return 'Small gaps, compact layouts';
    if (px <= 16) return 'Standard spacing, form elements';
    if (px <= 24) return 'Medium spacing, card padding';
    if (px <= 48) return 'Large spacing, section gaps';
    if (px > 48) return 'Extra large spacing, page sections';

    return 'Layout spacing';
  }

  /**
   * Infer effect usage based on name
   */
  inferEffectUsage(name) {
    const nameLower = name.toLowerCase();

    if (nameLower.includes('sm') || nameLower.includes('small')) {
      return 'Subtle elevation, buttons';
    }
    if (nameLower.includes('md') || nameLower.includes('medium')) {
      return 'Cards, dropdowns';
    }
    if (nameLower.includes('lg') || nameLower.includes('large')) {
      return 'Modals, popovers';
    }
    if (nameLower.includes('xl')) {
      return 'Floating elements, dialogs';
    }

    return 'Elevation, depth';
  }

  /**
   * Infer border radius usage
   */
  inferRadiusUsage(name, value) {
    const nameLower = name.toLowerCase();

    if (nameLower === 'none' || value === '0' || value === '0px') {
      return 'Sharp corners, tables';
    }
    if (nameLower.includes('sm') || nameLower.includes('small')) {
      return 'Subtle rounding, inputs';
    }
    if (nameLower.includes('md') || nameLower.includes('medium')) {
      return 'Standard rounding, buttons';
    }
    if (nameLower.includes('lg') || nameLower.includes('large')) {
      return 'Pronounced rounding, cards';
    }
    if (nameLower.includes('full') || nameLower.includes('pill')) {
      return 'Pills, avatars, circular';
    }

    return 'Corner rounding';
  }

  /**
   * Convert effect object to CSS value
   */
  effectToCSS(effect) {
    if (Array.isArray(effect)) {
      return effect.map(e => this.singleEffectToCSS(e)).join(', ');
    }
    return this.singleEffectToCSS(effect);
  }

  singleEffectToCSS(effect) {
    if (effect.type === 'DROP_SHADOW' || effect.type === 'drop-shadow') {
      const x = effect.x || '0px';
      const y = effect.y || '4px';
      const blur = effect.blur || '4px';
      const spread = effect.spread || '0px';
      const color = effect.color || 'rgba(0,0,0,0.25)';
      return `${x} ${y} ${blur} ${spread} ${color}`;
    }
    return 'none';
  }

  /**
   * Extract variants from component definition
   */
  extractVariants(component) {
    const variants = [];

    if (component.variants) {
      if (Array.isArray(component.variants)) {
        variants.push(...component.variants);
      } else if (typeof component.variants === 'object') {
        for (const [key, value] of Object.entries(component.variants)) {
          if (typeof value === 'object') {
            variants.push(...Object.keys(value));
          } else {
            variants.push(key);
          }
        }
      }
    }

    // Check for variant in name (e.g., "ButtonPrimary")
    const name = component.name || '';
    if (name.toLowerCase().includes('primary')) variants.push('primary');
    if (name.toLowerCase().includes('secondary')) variants.push('secondary');
    if (name.toLowerCase().includes('tertiary')) variants.push('tertiary');

    return [...new Set(variants)];
  }

  /**
   * Extract props from component definition
   */
  extractProps(component) {
    const props = [];

    if (component.props) {
      if (Array.isArray(component.props)) {
        props.push(...component.props.map(p => p.name || p));
      } else if (typeof component.props === 'object') {
        props.push(...Object.keys(component.props));
      }
    }

    return props;
  }
}

// Export for use as module
module.exports = { StylesMdGenerator };

// CLI execution
if (require.main === module) {
  const args = process.argv.slice(2);
  const projectPath = args[0] || process.cwd();

  const generator = new StylesMdGenerator({ projectPath });

  generator.generate().then(result => {
    if (result.success) {
      console.log(`✓ Generated: ${result.path}`);
      console.log(`  Colors: ${result.stats.colors}`);
      console.log(`  Typography: ${result.stats.typography}`);
      console.log(`  Spacing: ${result.stats.spacing}`);
      console.log(`  Effects: ${result.stats.effects}`);
      console.log(`  Components: ${result.stats.components}`);
    } else {
      console.error(`✗ Failed: ${result.error}`);
      process.exit(1);
    }
  });
}

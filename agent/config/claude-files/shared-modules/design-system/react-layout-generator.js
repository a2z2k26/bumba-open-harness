/**
 * React Layout Generator
 *
 * Extends LayoutGenerator for React/Next.js/TypeScript
 * Generates page layouts using registry components instead of recreating them
 */

const LayoutGenerator = require('./layout-generator');

class ReactLayoutGenerator extends LayoutGenerator {
  constructor(projectPath, options = {}) {
    super(projectPath, 'nextjs', options);
    this.useTypeScript = options.typescript !== false;
  }

  /**
   * Generate React layout code using registry components
   */
  generateLayoutCode(layoutName, layoutJson, componentUsage, validComponents) {
    const pageName = this.toPascalCase(layoutName);
    const outputPath = this._getLayoutOutputPath(layoutName);

    // Generate imports
    const imports = this.generateImports(validComponents, outputPath);

    // Extract layout styles from Figma
    const layoutStyles = this._extractLayoutStyles(layoutJson);

    // Generate JSX structure
    const jsx = this._generateJSXStructure(layoutJson, componentUsage, validComponents);

    return `/**
 * ${pageName} Page
 *
 * Generated from Figma layout using registry components
 * Layout: ${layoutName}
 * Generated: ${new Date().toISOString()}
 *
 * Components used: ${validComponents.length}
 * All components sourced from component registry (no duplication)
 */

import React from 'react';
import styled from 'styled-components';
${imports}

${this._generateStyledComponents(layoutStyles)}

${this._generatePageComponent(pageName, jsx)}

export default ${pageName};
`;
  }

  /**
   * Generate styled-components for layout containers
   */
  _generateStyledComponents(layoutStyles) {
    return `const PageContainer = styled.div\`
  width: 100%;
  min-height: 100vh;
  background: ${layoutStyles.background || '#ffffff'};
  display: flex;
  flex-direction: column;
\`;

const LayoutWrapper = styled.div\`
  max-width: ${layoutStyles.width || 1200}px;
  margin: 0 auto;
  width: 100%;
\`;`;
  }

  /**
   * Generate the main page component
   */
  _generatePageComponent(pageName, jsx) {
    const propsType = this.useTypeScript ? ': React.FC' : '';

    return `/**
 * ${pageName} Page Component
 */
const ${pageName}${propsType} = () => {
  return (
    <PageContainer>
      <LayoutWrapper>
${jsx}
      </LayoutWrapper>
    </PageContainer>
  );
};`;
  }

  /**
   * Generate JSX structure from layout JSON using registry components
   */
  _generateJSXStructure(layoutJson, componentUsage, validComponents, indent = 4) {
    const lines = [];
    const indentStr = ' '.repeat(indent);

    // Create a map of valid components for quick lookup
    const validComponentMap = new Map(
      validComponents.map(c => [this.normalizeComponentName(c.name), c])
    );

    // Group components by their parent/container
    const rootComponents = componentUsage.filter(c => {
      // Get root-level components (typically Header, Hero, Content sections, Footer)
      const pathParts = c.path.split('/').filter(p => p);
      return pathParts.length <= 2; // Direct children or one level deep
    });

    // Sort components by Y position (top to bottom)
    rootComponents.sort((a, b) => a.position.y - b.position.y);

    // Generate JSX for each component
    for (const component of rootComponents) {
      const normalizedName = this.normalizeComponentName(component.name);
      const validComponent = validComponentMap.get(normalizedName);

      if (!validComponent) {
        lines.push(`${indentStr}{/* TODO: Component "${component.name}" not found in registry */}`);
        continue;
      }

      // Generate component JSX
      const componentName = this.toPascalCase(component.name);
      const props = this._generateComponentProps(component);
      const propsStr = props.length > 0 ? ' ' + props.join(' ') : '';

      lines.push(`${indentStr}<${componentName}${propsStr} />`);
    }

    return lines.join('\n');
  }

  /**
   * Generate props for component instance
   */
  _generateComponentProps(componentInstance) {
    const props = [];

    // Add variant props
    if (componentInstance.variants) {
      for (const [key, value] of Object.entries(componentInstance.variants)) {
        const propName = this.toCamelCase(key);
        props.push(`${propName}="${value}"`);
      }
    }

    // Add className for styling if needed
    const className = this._generateClassName(componentInstance);
    if (className) {
      props.push(`className="${className}"`);
    }

    return props;
  }

  /**
   * Generate className from component instance name
   */
  _generateClassName(componentInstance) {
    // Convert instance name to kebab-case for className
    return componentInstance.instanceName
      .toLowerCase()
      .replace(/\s+/g, '-')
      .replace(/[^a-z0-9-]/g, '');
  }

  /**
   * Extract layout styles from Figma JSON
   */
  _extractLayoutStyles(layoutJson) {
    const styles = {
      width: layoutJson.width || 1200,
      height: layoutJson.height || 'auto',
      background: this._extractBackgroundColor(layoutJson)
    };

    return styles;
  }

  /**
   * Extract background color from Figma fills
   */
  _extractBackgroundColor(node) {
    if (!node.fills || node.fills.length === 0) {
      return '#ffffff';
    }

    const solidFill = node.fills.find(fill => fill.type === 'SOLID');
    if (!solidFill || !solidFill.color) {
      return '#ffffff';
    }

    const { r, g, b } = solidFill.color;
    return `rgb(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)})`;
  }

  /**
   * Convert to PascalCase
   */
  toPascalCase(str) {
    return str
      .replace(/[^a-zA-Z0-9]+/g, ' ')
      .split(' ')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
      .join('');
  }

  /**
   * Convert to camelCase
   */
  toCamelCase(str) {
    const pascal = this.toPascalCase(str);
    return pascal.charAt(0).toLowerCase() + pascal.slice(1);
  }

  /**
   * Normalize component name for comparison
   */
  normalizeComponentName(name) {
    return name.toLowerCase().replace(/[^a-z0-9]/g, '');
  }

  /**
   * Get file extension
   */
  getFileExtension() {
    return this.useTypeScript ? '.tsx' : '.jsx';
  }
}

module.exports = ReactLayoutGenerator;

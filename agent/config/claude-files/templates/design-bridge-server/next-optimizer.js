/**
 * Next.js Optimizer
 * Sprint 4: Next.js Framework Support
 *
 * Optimizes code generation specifically for Next.js applications
 * Supports App Router, Server/Client Components, and multiple styling approaches
 */

const EventEmitter = require('events');

class NextOptimizer extends EventEmitter {
  constructor() {
    super();

    this.name = 'NextOptimizer';
    this.version = '1.0.0';
    this.framework = 'nextjs';

    // Next.js-specific configuration
    this.config = {
      nextVersion: '14.x',
      router: 'app', // 'app' or 'pages'
      useTypeScript: true,
      useServerComponents: true,
      useClientDirective: true,
      styleApproach: 'css-modules', // 'css-modules', 'tailwind', 'styled-components', 'inline'
      imageOptimization: true,
      linkPrefetch: true,
      fontOptimization: true,
      metadataExport: true
    };

    // Next.js patterns
    this.patterns = {
      serverComponents: this.getServerComponentPatterns(),
      clientComponents: this.getClientComponentPatterns(),
      routing: this.getRoutingPatterns(),
      styling: this.getStylingPatterns()
    };

    // Statistics
    this.stats = {
      componentsGenerated: 0,
      clientComponents: 0,
      serverComponents: 0,
      optimizationsApplied: 0
    };
  }

  /**
   * Determine if component needs 'use client' directive
   * @param {Object} componentData - Component data
   * @returns {boolean} Whether 'use client' is needed
   */
  needsClientDirective(componentData) {
    const clientIndicators = [
      // Has state
      componentData.state && Object.keys(componentData.state).length > 0,
      // Has event handlers
      componentData.events && componentData.events.length > 0,
      // Has interactive props (onClick, onChange, etc.)
      componentData.props?.onClick || componentData.props?.onChange || componentData.props?.onSubmit,
      // Uses browser APIs
      componentData.usesBrowserAPIs,
      // Explicit client component flag
      componentData.isClientComponent
    ];
    return clientIndicators.some(Boolean);
  }

  /**
   * Add 'use client' directive at top of file
   * @param {string} code - Source code
   * @returns {string} Code with directive
   */
  addClientDirective(code) {
    if (code.startsWith("'use client'") || code.startsWith('"use client"')) {
      return code;
    }
    return `'use client';\n\n${code}`;
  }

  /**
   * Optimize code for Next.js
   * @param {string} code - Input code
   * @param {Object} componentData - Component metadata
   * @param {Object} config - Optimization config
   * @returns {string} Optimized code
   */
  async optimize(code, componentData, config = {}) {
    let optimizedCode = code;
    const mergedConfig = { ...this.config, ...config };

    // Add 'use client' if needed
    if (this.needsClientDirective(componentData)) {
      optimizedCode = this.addClientDirective(optimizedCode);
      this.stats.clientComponents++;
    } else {
      this.stats.serverComponents++;
    }

    // Apply Next.js-specific optimizations
    optimizedCode = await this.optimizeImages(optimizedCode, componentData, mergedConfig);
    optimizedCode = await this.optimizeLinks(optimizedCode, componentData, mergedConfig);
    optimizedCode = await this.optimizeStyles(optimizedCode, componentData, mergedConfig);

    this.stats.optimizationsApplied++;

    return optimizedCode;
  }

  /**
   * Generate Next.js component from design data
   * @param {Object} componentData - Component design data
   * @param {Object} config - Generation config
   * @returns {string} Generated component code
   */
  async generateComponent(componentData, config = {}) {
    const mergedConfig = { ...this.config, ...config };
    const { name, props = {}, state = {}, children, styles } = componentData;
    const needsClient = this.needsClientDirective(componentData);

    let code = [];

    // 'use client' directive (must be first line, only for App Router mode)
    // Pages Router (appRouter: false) doesn't use/support 'use client' directive
    const isAppRouter = mergedConfig.appRouter !== false;
    if (needsClient && isAppRouter && !mergedConfig.forceServer) {
      code.push("'use client';");
      code.push('');
    }

    // Imports
    code.push(this.generateImports(componentData, mergedConfig, needsClient));
    code.push('');

    // Type definitions (TypeScript)
    if (mergedConfig.useTypeScript) {
      code.push(this.generateTypeDefinitions(componentData));
      code.push('');
    }

    // Component declaration
    const componentType = mergedConfig.useTypeScript ? `: React.FC<${name}Props>` : '';
    code.push(`export default function ${name}${componentType}({`);

    // Props destructuring
    const propsList = Object.entries(props).map(([key, prop]) => {
      return prop.default !== undefined ? `  ${key} = ${JSON.stringify(prop.default)}` : `  ${key}`;
    });
    if (propsList.length > 0) {
      code.push(propsList.join(',\n'));
    }
    code.push('}) {');

    // State hooks (only for client components)
    if (needsClient && state && Object.keys(state).length > 0) {
      code.push(this.generateStateHooks(state));
    }

    // Component body
    code.push('  return (');
    code.push(this.generateJSX(componentData, mergedConfig));
    code.push('  );');
    code.push('}');

    this.stats.componentsGenerated++;

    this.emit('component:generated', {
      name,
      isClient: needsClient,
      timestamp: new Date().toISOString()
    });

    return code.join('\n');
  }

  /**
   * Generate import statements
   * @param {Object} data - Component data
   * @param {Object} config - Config options
   * @param {boolean} needsClient - Whether client component
   * @returns {string} Import statements
   */
  generateImports(data, config, needsClient) {
    const imports = [];

    // React imports
    const reactImports = [];
    if (needsClient && data.state && Object.keys(data.state).length > 0) {
      reactImports.push('useState');
    }
    if (data.useEffect) {
      reactImports.push('useEffect');
    }
    if (data.useCallback) {
      reactImports.push('useCallback');
    }
    if (data.useMemo) {
      reactImports.push('useMemo');
    }
    if (reactImports.length > 0) {
      imports.push(`import { ${reactImports.join(', ')} } from 'react';`);
    }

    // Next.js imports
    if (data.hasImages || config.imageOptimization) {
      imports.push("import Image from 'next/image';");
    }
    if (data.hasLinks || config.linkPrefetch) {
      imports.push("import Link from 'next/link';");
    }
    if (config.fontOptimization && data.hasCustomFont) {
      imports.push("import { Inter } from 'next/font/google';");
    }

    // Style imports
    if (config.styleApproach === 'css-modules') {
      imports.push(`import styles from './${data.name}.module.css';`);
    } else if (config.styleApproach === 'styled-components') {
      imports.push("import styled from 'styled-components';");
    }

    return imports.join('\n');
  }

  /**
   * Generate TypeScript type definitions
   * @param {Object} data - Component data
   * @returns {string} Type definitions
   */
  generateTypeDefinitions(data) {
    const { name, props = {} } = data;
    const propTypes = Object.entries(props).map(([key, prop]) => {
      const optional = prop.required ? '' : '?';
      const propType = this.convertToTypeScriptType(prop.type || 'any');
      return `  ${key}${optional}: ${propType};`;
    });

    if (propTypes.length === 0) {
      return `interface ${name}Props {}`;
    }

    return `interface ${name}Props {\n${propTypes.join('\n')}\n}`;
  }

  /**
   * Convert JavaScript type to TypeScript type
   * @param {string} type - JavaScript type
   * @returns {string} TypeScript type
   */
  convertToTypeScriptType(type) {
    const typeMap = {
      'string': 'string',
      'number': 'number',
      'boolean': 'boolean',
      'array': 'any[]',
      'object': 'Record<string, any>',
      'function': '() => void',
      '() => void': '() => void',
      'any': 'any'
    };
    return typeMap[type] || type;
  }

  /**
   * Generate state hooks
   * @param {Object} state - State definitions
   * @returns {string} State hook declarations
   */
  generateStateHooks(state) {
    return Object.entries(state).map(([key, value]) => {
      const defaultValue = JSON.stringify(value.default ?? value);
      const setterName = `set${key.charAt(0).toUpperCase()}${key.slice(1)}`;
      return `  const [${key}, ${setterName}] = useState(${defaultValue});`;
    }).join('\n');
  }

  /**
   * Generate JSX structure
   * @param {Object} data - Component data
   * @param {Object} config - Config options
   * @returns {string} JSX code
   */
  generateJSX(data, config) {
    const className = config.styleApproach === 'css-modules'
      ? `className={styles.container}`
      : config.styleApproach === 'tailwind'
      ? `className="flex flex-col"`
      : '';

    return `    <div ${className}>\n      {/* Component content */}\n    </div>`;
  }

  /**
   * Optimize images for Next.js
   * @param {string} code - Source code
   * @param {Object} data - Component data
   * @param {Object} config - Config options
   * @returns {string} Optimized code
   */
  async optimizeImages(code, data, config) {
    if (!config.imageOptimization) return code;

    // Replace <img> tags with Next.js Image component
    let optimized = code;

    // Pattern: <img src="..." alt="..." />
    optimized = optimized.replace(
      /<img\s+src=["']([^"']+)["']\s+alt=["']([^"']*)["']\s*\/?>/g,
      '<Image src="$1" alt="$2" width={500} height={300} />'
    );

    // Pattern: <img src={...} alt={...} />
    optimized = optimized.replace(
      /<img\s+src=\{([^}]+)\}\s+alt=\{([^}]+)\}\s*\/?>/g,
      '<Image src={$1} alt={$2} width={500} height={300} />'
    );

    return optimized;
  }

  /**
   * Optimize links for Next.js
   * @param {string} code - Source code
   * @param {Object} data - Component data
   * @param {Object} config - Config options
   * @returns {string} Optimized code
   */
  async optimizeLinks(code, data, config) {
    if (!config.linkPrefetch) return code;

    // Replace <a> tags with Next.js Link component
    let optimized = code;

    // Pattern: <a href="...">...</a>
    optimized = optimized.replace(
      /<a\s+href=["']([^"']+)["']>([^<]*)<\/a>/g,
      '<Link href="$1">$2</Link>'
    );

    return optimized;
  }

  /**
   * Optimize styles for Next.js
   * @param {string} code - Source code
   * @param {Object} componentData - Component data
   * @param {Object} config - Config options
   * @returns {string} Optimized code
   */
  async optimizeStyles(code, componentData, config) {
    const styleApproach = config.styleApproach || this.config.styleApproach;

    switch (styleApproach) {
      case 'css-modules':
        return this.applyCSSModulesPattern(code, componentData);
      case 'tailwind':
        return this.applyTailwindPattern(code, componentData);
      case 'styled-components':
        return this.applyStyledComponentsPattern(code, componentData);
      case 'inline':
        return this.applyInlineStylePattern(code, componentData);
      default:
        return code;
    }
  }

  /**
   * Apply CSS Modules pattern
   * @param {string} code - Source code
   * @param {Object} componentData - Component data
   * @returns {string} Transformed code
   */
  applyCSSModulesPattern(code, componentData) {
    // Ensure import exists
    const importStatement = `import styles from './${componentData.name}.module.css';`;
    if (!code.includes(importStatement) && !code.includes('.module.css')) {
      // Find first import line and add after it
      const lines = code.split('\n');
      const firstImportIndex = lines.findIndex(l => l.startsWith('import'));
      if (firstImportIndex >= 0) {
        lines.splice(firstImportIndex + 1, 0, importStatement);
        code = lines.join('\n');
      }
    }

    // Replace className strings with styles references
    code = code.replace(/className="([^"]+)"/g, (match, classes) => {
      const classArray = classes.split(' ').map(c => `styles.${c}`);
      return classArray.length === 1
        ? `className={${classArray[0]}}`
        : `className={\`\${${classArray.join('} \${')}\`}`;
    });

    return code;
  }

  /**
   * Apply Tailwind pattern
   * @param {string} code - Source code
   * @param {Object} componentData - Component data
   * @returns {string} Transformed code
   */
  applyTailwindPattern(code, componentData) {
    // Convert design tokens to Tailwind classes
    const { styles } = componentData;
    if (!styles) return code;

    const tailwindMap = {
      // Spacing
      padding: (v) => `p-${this.spacingToTailwind(v)}`,
      margin: (v) => `m-${this.spacingToTailwind(v)}`,
      // Colors
      backgroundColor: (v) => `bg-${this.colorToTailwind(v)}`,
      color: (v) => `text-${this.colorToTailwind(v)}`,
      // Typography
      fontSize: (v) => `text-${this.fontSizeToTailwind(v)}`,
      fontWeight: (v) => `font-${v}`,
      // Layout
      display: (v) => v === 'flex' ? 'flex' : v === 'grid' ? 'grid' : '',
      flexDirection: (v) => v === 'column' ? 'flex-col' : 'flex-row',
      justifyContent: (v) => `justify-${this.justifyToTailwind(v)}`,
      alignItems: (v) => `items-${this.alignToTailwind(v)}`,
      // Border
      borderRadius: (v) => `rounded-${this.borderRadiusToTailwind(v)}`
    };

    // Build Tailwind class string
    const classes = [];
    for (const [prop, value] of Object.entries(styles)) {
      if (tailwindMap[prop]) {
        const twClass = tailwindMap[prop](value);
        if (twClass) classes.push(twClass);
      }
    }

    return code.replace('className=""', `className="${classes.join(' ')}"`);
  }

  // Tailwind helper methods
  spacingToTailwind(value) {
    const map = { '4px': '1', '8px': '2', '12px': '3', '16px': '4', '20px': '5', '24px': '6', '32px': '8', '40px': '10', '48px': '12' };
    return map[value] || '4';
  }

  colorToTailwind(value) {
    // Simplified color mapping
    if (value.startsWith('#')) return `[${value}]`;
    return value.replace(/\./g, '-');
  }

  fontSizeToTailwind(value) {
    const map = { '12px': 'xs', '14px': 'sm', '16px': 'base', '18px': 'lg', '20px': 'xl', '24px': '2xl', '30px': '3xl' };
    return map[value] || 'base';
  }

  justifyToTailwind(value) {
    const map = { 'flex-start': 'start', 'flex-end': 'end', 'center': 'center', 'space-between': 'between', 'space-around': 'around' };
    return map[value] || 'start';
  }

  alignToTailwind(value) {
    const map = { 'flex-start': 'start', 'flex-end': 'end', 'center': 'center', 'stretch': 'stretch', 'baseline': 'baseline' };
    return map[value] || 'start';
  }

  borderRadiusToTailwind(value) {
    const map = { '0': 'none', '2px': 'sm', '4px': 'md', '6px': 'md', '8px': 'lg', '12px': 'xl', '16px': '2xl', '9999px': 'full' };
    return map[value] || 'md';
  }

  /**
   * Apply styled-components pattern
   * @param {string} code - Source code
   * @param {Object} componentData - Component data
   * @returns {string} Transformed code
   */
  applyStyledComponentsPattern(code, componentData) {
    // Add styled-components import if not present
    if (!code.includes("import styled from 'styled-components'")) {
      code = `import styled from 'styled-components';\n${code}`;
    }
    return code;
  }

  /**
   * Apply inline style pattern
   * @param {string} code - Source code
   * @param {Object} componentData - Component data
   * @returns {string} Transformed code
   */
  applyInlineStylePattern(code, componentData) {
    const { styles } = componentData;
    if (!styles) return code;

    const styleObj = JSON.stringify(styles);
    return code.replace('style={}', `style={${styleObj}}`);
  }

  /**
   * Generate CSS Module file content
   * @param {Object} componentData - Component data
   * @returns {Object} CSS module file info
   */
  generateCSSModule(componentData) {
    const { name, styles } = componentData;
    let css = [];

    css.push(`.container {`);
    if (styles) {
      for (const [prop, value] of Object.entries(styles)) {
        const cssProperty = prop.replace(/([A-Z])/g, '-$1').toLowerCase();
        css.push(`  ${cssProperty}: ${value};`);
      }
    }
    css.push(`}`);

    return {
      filename: `${name}.module.css`,
      content: css.join('\n')
    };
  }

  // Pattern getters
  getServerComponentPatterns() {
    return {
      asyncComponent: 'export default async function Component() { const data = await fetch(); return <div>{data}</div>; }',
      dataFetching: 'async component with direct await',
      noStateHooks: 'Cannot use useState, useEffect',
      canPassToClient: 'Can render client components as children'
    };
  }

  getClientComponentPatterns() {
    return {
      directive: "'use client' at top of file",
      stateHooks: 'useState, useReducer',
      effectHooks: 'useEffect, useLayoutEffect',
      eventHandlers: 'onClick, onChange, onSubmit',
      browserAPIs: 'window, document, localStorage'
    };
  }

  getRoutingPatterns() {
    return {
      appRouter: {
        page: 'app/page.tsx',
        layout: 'app/layout.tsx',
        loading: 'app/loading.tsx',
        error: 'app/error.tsx',
        notFound: 'app/not-found.tsx'
      },
      pagesRouter: {
        page: 'pages/index.tsx',
        api: 'pages/api/*.ts',
        document: 'pages/_document.tsx',
        app: 'pages/_app.tsx'
      }
    };
  }

  getStylingPatterns() {
    return {
      cssModules: "import styles from './Component.module.css'",
      tailwind: "className='flex items-center'",
      styledComponents: "import styled from 'styled-components'",
      inline: "style={{ color: 'red' }}"
    };
  }

  /**
   * Get optimizer statistics
   * @returns {Object} Statistics
   */
  getStats() {
    return {
      ...this.stats,
      framework: this.framework,
      version: this.version
    };
  }

  /**
   * Reset statistics
   */
  resetStats() {
    this.stats = {
      componentsGenerated: 0,
      clientComponents: 0,
      serverComponents: 0,
      optimizationsApplied: 0
    };
  }
}

module.exports = NextOptimizer;

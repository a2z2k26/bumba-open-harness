#!/usr/bin/env node

/**
 * Design Bridge Framework Adapters
 * Sprint 8.2: Framework-Specific Code Generators
 *
 * Features:
 * - React adapter with hooks and JSX
 * - Vue adapter with composition API
 * - Svelte adapter with reactive syntax
 * - Angular adapter with TypeScript decorators
 * - Custom adapter registration
 * - Template transformation engine
 */

const EventEmitter = require('events');

// Base Adapter class
class BaseAdapter extends EventEmitter {
  constructor(name, options = {}) {
    super();
    this.name = name;
    this.options = {
      typescript: options.typescript || false,
      cssModule: options.cssModule || false,
      styleFormat: options.styleFormat || 'css',
      outputDir: options.outputDir || './components',
      ...options
    };
  }

  // Override in subclasses
  generateComponent(componentData) {
    throw new Error('generateComponent must be implemented');
  }

  generateStyles(styles) {
    throw new Error('generateStyles must be implemented');
  }

  generateExports(components) {
    throw new Error('generateExports must be implemented');
  }

  // Common utilities
  formatComponentName(name) {
    return name
      .replace(/[^a-zA-Z0-9]/g, ' ')
      .split(' ')
      .filter(Boolean)
      .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
      .join('');
  }

  formatPropName(name) {
    return name
      .replace(/[^a-zA-Z0-9]/g, ' ')
      .split(' ')
      .filter(Boolean)
      .map((word, i) => i === 0
        ? word.toLowerCase()
        : word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()
      )
      .join('');
  }

  formatCssClassName(name) {
    return name
      .replace(/[^a-zA-Z0-9]/g, '-')
      .toLowerCase()
      .replace(/-+/g, '-')
      .replace(/^-|-$/g, '');
  }

  generatePropTypes(props) {
    if (!props || !Array.isArray(props)) return {};

    return props.reduce((acc, prop) => {
      acc[this.formatPropName(prop.name)] = {
        type: prop.type || 'string',
        required: prop.required || false,
        default: prop.default
      };
      return acc;
    }, {});
  }

  cssValueToJs(value) {
    if (typeof value !== 'string') return value;
    if (value.endsWith('px')) {
      return parseInt(value, 10);
    }
    return value;
  }

  generateStyleObject(styles) {
    const result = {};
    for (const [key, value] of Object.entries(styles)) {
      const jsKey = key.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
      result[jsKey] = value;
    }
    return result;
  }
}

// React Adapter
class ReactAdapter extends BaseAdapter {
  constructor(options = {}) {
    super('react', options);
    this.fileExtension = this.options.typescript ? '.tsx' : '.jsx';
  }

  generateComponent(componentData) {
    const { name, props = [], styles = {}, children = [], variants = [] } = componentData;
    const componentName = this.formatComponentName(name);
    const propsInterface = this.generatePropsInterface(props, componentName);
    const styleImport = this.generateStyleImport(name);
    const variantLogic = this.generateVariantLogic(variants);

    const template = `${this.options.typescript ? propsInterface : ''}
import React${this.options.typescript ? ', { FC }' : ''} from 'react';
${styleImport}

${this.options.typescript
  ? `const ${componentName}: FC<${componentName}Props> = ({`
  : `const ${componentName} = ({`}
  ${this.generatePropsDestructure(props)}
}) => {
${variantLogic}
  return (
    <div className={${this.generateClassNameLogic(name, variants)}}>
      ${this.generateChildren(children)}
    </div>
  );
};

${componentName}.displayName = '${componentName}';

export default ${componentName};
`;

    this.emit('component:generated', { name: componentName, framework: 'react' });
    return {
      filename: `${componentName}${this.fileExtension}`,
      content: template.trim(),
      type: 'component'
    };
  }

  generatePropsInterface(props, componentName) {
    if (!this.options.typescript) return '';

    const propsTypes = props.map(prop => {
      const propName = this.formatPropName(prop.name);
      const optional = prop.required ? '' : '?';
      const type = this.mapToTsType(prop.type);
      return `  ${propName}${optional}: ${type};`;
    }).join('\n');

    return `
interface ${componentName}Props {
${propsTypes}
  children?: React.ReactNode;
  className?: string;
}
`;
  }

  mapToTsType(type) {
    const typeMap = {
      'string': 'string',
      'number': 'number',
      'boolean': 'boolean',
      'array': 'any[]',
      'object': 'Record<string, any>',
      'function': '(...args: any[]) => void',
      'node': 'React.ReactNode'
    };
    return typeMap[type] || 'any';
  }

  generatePropsDestructure(props) {
    const propNames = props.map(p => {
      const name = this.formatPropName(p.name);
      if (p.default !== undefined) {
        return `${name} = ${JSON.stringify(p.default)}`;
      }
      return name;
    });
    return [...propNames, 'children', 'className'].join(',\n  ');
  }

  generateStyleImport(name) {
    const className = this.formatCssClassName(name);
    if (this.options.cssModule) {
      return `import styles from './${className}.module.${this.options.styleFormat}';`;
    }
    return `import './${className}.${this.options.styleFormat}';`;
  }

  generateClassNameLogic(name, variants) {
    const baseClass = this.formatCssClassName(name);
    if (this.options.cssModule) {
      if (variants.length > 0) {
        return `\`\${styles.${baseClass}} \${variantClass} \${className || ''}\``;
      }
      return `\`\${styles.${baseClass}} \${className || ''}\``;
    }
    if (variants.length > 0) {
      return `\`${baseClass} \${variantClass} \${className || ''}\``;
    }
    return `\`${baseClass} \${className || ''}\``;
  }

  generateVariantLogic(variants) {
    if (!variants || variants.length === 0) return '';

    const variantMap = variants.map(v =>
      `    '${v.name}': '${this.formatCssClassName(v.name)}'`
    ).join(',\n');

    return `  const variantClasses = {\n${variantMap}\n  };
  const variantClass = variant ? variantClasses[variant] || '' : '';`;
  }

  generateChildren(children) {
    if (!children || children.length === 0) return '{children}';

    return children.map(child => {
      if (child.type === 'text') {
        return `<span>${child.content || '{children}'}</span>`;
      }
      if (child.type === 'component') {
        return `<${this.formatComponentName(child.name)} />`;
      }
      return '{children}';
    }).join('\n      ');
  }

  generateStyles(styles) {
    const cssRules = Object.entries(styles).map(([selector, rules]) => {
      const cssProps = Object.entries(rules)
        .map(([prop, value]) => `  ${prop}: ${value};`)
        .join('\n');
      return `.${selector} {\n${cssProps}\n}`;
    }).join('\n\n');

    return {
      filename: `styles.${this.options.styleFormat}`,
      content: cssRules,
      type: 'styles'
    };
  }

  generateExports(components) {
    const exports = components.map(c => {
      const name = this.formatComponentName(c.name);
      return `export { default as ${name} } from './${name}';`;
    }).join('\n');

    return {
      filename: `index.${this.options.typescript ? 'ts' : 'js'}`,
      content: exports,
      type: 'index'
    };
  }

  generateHook(hookData) {
    const { name, state = [], effects = [], callbacks = [] } = hookData;
    const hookName = `use${this.formatComponentName(name)}`;

    const stateDeclarations = state.map(s =>
      `  const [${s.name}, set${this.formatComponentName(s.name)}] = useState(${JSON.stringify(s.default)});`
    ).join('\n');

    const effectDeclarations = effects.map(e =>
      `  useEffect(() => {\n    ${e.body}\n  }, [${(e.deps || []).join(', ')}]);`
    ).join('\n\n');

    const callbackDeclarations = callbacks.map(c =>
      `  const ${c.name} = useCallback(${c.body}, [${(c.deps || []).join(', ')}]);`
    ).join('\n');

    const returnValues = [
      ...state.map(s => s.name),
      ...state.map(s => `set${this.formatComponentName(s.name)}`),
      ...callbacks.map(c => c.name)
    ].join(', ');

    return {
      filename: `${hookName}.${this.options.typescript ? 'ts' : 'js'}`,
      content: `import { useState, useEffect, useCallback } from 'react';

export function ${hookName}() {
${stateDeclarations}

${effectDeclarations}

${callbackDeclarations}

  return { ${returnValues} };
}`,
      type: 'hook'
    };
  }
}

// Vue Adapter
class VueAdapter extends BaseAdapter {
  constructor(options = {}) {
    super('vue', options);
    this.fileExtension = '.vue';
    this.compositionApi = options.compositionApi !== false;
  }

  generateComponent(componentData) {
    const { name, props = [], styles = {}, children = [], variants = [] } = componentData;
    const componentName = this.formatComponentName(name);

    const template = this.compositionApi
      ? this.generateCompositionComponent(componentData)
      : this.generateOptionsComponent(componentData);

    this.emit('component:generated', { name: componentName, framework: 'vue' });
    return {
      filename: `${componentName}.vue`,
      content: template,
      type: 'component'
    };
  }

  generateCompositionComponent(componentData) {
    const { name, props = [], styles = {}, children = [] } = componentData;
    const componentName = this.formatComponentName(name);
    const className = this.formatCssClassName(name);

    const propsDefinition = this.generatePropsDefinition(props);
    const styleBlock = this.generateStyleBlock(styles, className);

    return `<template>
  <div :class="['${className}', props.className]">
    ${this.generateTemplateChildren(children)}
    <slot></slot>
  </div>
</template>

<script setup${this.options.typescript ? ' lang="ts"' : ''}>
${this.options.typescript ? this.generateTypeImports(props) : ''}
const props = defineProps(${propsDefinition});

const emit = defineEmits(['click', 'change']);
</script>

<style${this.options.styleFormat === 'scss' ? ' lang="scss"' : ''} scoped>
${styleBlock}
</style>`;
  }

  generateOptionsComponent(componentData) {
    const { name, props = [], styles = {}, children = [] } = componentData;
    const componentName = this.formatComponentName(name);
    const className = this.formatCssClassName(name);

    const propsDefinition = this.generatePropsDefinition(props);
    const styleBlock = this.generateStyleBlock(styles, className);

    return `<template>
  <div :class="['${className}', className]">
    ${this.generateTemplateChildren(children)}
    <slot></slot>
  </div>
</template>

<script>
export default {
  name: '${componentName}',
  props: ${propsDefinition},
  emits: ['click', 'change']
};
</script>

<style${this.options.styleFormat === 'scss' ? ' lang="scss"' : ''} scoped>
${styleBlock}
</style>`;
  }

  generatePropsDefinition(props) {
    const propsDef = props.reduce((acc, prop) => {
      const propName = this.formatPropName(prop.name);
      acc[propName] = {
        type: this.mapToVueType(prop.type),
        required: prop.required || false,
        default: prop.default
      };
      return acc;
    }, {});

    propsDef.className = { type: String, default: '' };

    return JSON.stringify(propsDef, null, 2).replace(/"(\w+)":/g, '$1:');
  }

  mapToVueType(type) {
    const typeMap = {
      'string': 'String',
      'number': 'Number',
      'boolean': 'Boolean',
      'array': 'Array',
      'object': 'Object',
      'function': 'Function'
    };
    return typeMap[type] || 'String';
  }

  generateTypeImports(props) {
    return `import type { PropType } from 'vue';\n`;
  }

  generateTemplateChildren(children) {
    if (!children || children.length === 0) return '';

    return children.map(child => {
      if (child.type === 'text') {
        return `<span>{{ ${child.binding || `"${child.content}"`} }}</span>`;
      }
      if (child.type === 'component') {
        return `<${this.formatComponentName(child.name)} />`;
      }
      return '';
    }).join('\n    ');
  }

  generateStyleBlock(styles, className) {
    if (!styles || Object.keys(styles).length === 0) {
      return `.${className} {\n  /* Component styles */\n}`;
    }

    return Object.entries(styles).map(([selector, rules]) => {
      const cssProps = Object.entries(rules)
        .map(([prop, value]) => `  ${prop}: ${value};`)
        .join('\n');
      return `.${selector} {\n${cssProps}\n}`;
    }).join('\n\n');
  }

  generateStyles(styles) {
    // Vue styles are typically inline in SFC
    return null;
  }

  generateExports(components) {
    const imports = components.map(c => {
      const name = this.formatComponentName(c.name);
      return `import ${name} from './${name}.vue';`;
    }).join('\n');

    const exports = components.map(c =>
      this.formatComponentName(c.name)
    ).join(',\n  ');

    return {
      filename: `index.${this.options.typescript ? 'ts' : 'js'}`,
      content: `${imports}

export {
  ${exports}
};`,
      type: 'index'
    };
  }

  generateComposable(composableData) {
    const { name, state = [], computed = [], methods = [] } = composableData;
    const composableName = `use${this.formatComponentName(name)}`;

    const stateDeclarations = state.map(s =>
      `  const ${s.name} = ref(${JSON.stringify(s.default)});`
    ).join('\n');

    const computedDeclarations = computed.map(c =>
      `  const ${c.name} = computed(() => ${c.body});`
    ).join('\n');

    const methodDeclarations = methods.map(m =>
      `  const ${m.name} = (${(m.params || []).join(', ')}) => {\n    ${m.body}\n  };`
    ).join('\n\n');

    const returnValues = [
      ...state.map(s => s.name),
      ...computed.map(c => c.name),
      ...methods.map(m => m.name)
    ].join(',\n    ');

    return {
      filename: `${composableName}.${this.options.typescript ? 'ts' : 'js'}`,
      content: `import { ref, computed } from 'vue';

export function ${composableName}() {
${stateDeclarations}

${computedDeclarations}

${methodDeclarations}

  return {
    ${returnValues}
  };
}`,
      type: 'composable'
    };
  }
}

// Svelte Adapter
class SvelteAdapter extends BaseAdapter {
  constructor(options = {}) {
    super('svelte', options);
    this.fileExtension = '.svelte';
  }

  generateComponent(componentData) {
    const { name, props = [], styles = {}, children = [], variants = [] } = componentData;
    const componentName = this.formatComponentName(name);
    const className = this.formatCssClassName(name);

    const propsDeclarations = this.generatePropsDeclarations(props);
    const styleBlock = this.generateStyleBlock(styles, className);
    const variantLogic = this.generateVariantLogic(variants);

    const template = `<script${this.options.typescript ? ' lang="ts"' : ''}>
${propsDeclarations}

${variantLogic}
  let combinedClass = \`${className} \${variant ? variantClasses[variant] : ''} \${className}\`;
</script>

<div class={combinedClass}>
  ${this.generateChildren(children)}
  <slot></slot>
</div>

<style${this.options.styleFormat === 'scss' ? ' lang="scss"' : ''}>
${styleBlock}
</style>`;

    this.emit('component:generated', { name: componentName, framework: 'svelte' });
    return {
      filename: `${componentName}.svelte`,
      content: template,
      type: 'component'
    };
  }

  generatePropsDeclarations(props) {
    return props.map(prop => {
      const propName = this.formatPropName(prop.name);
      const type = this.options.typescript ? `: ${this.mapToTsType(prop.type)}` : '';
      const defaultValue = prop.default !== undefined
        ? ` = ${JSON.stringify(prop.default)}`
        : '';
      return `  export let ${propName}${type}${defaultValue};`;
    }).join('\n') + '\n  export let className = \'\';';
  }

  mapToTsType(type) {
    const typeMap = {
      'string': 'string',
      'number': 'number',
      'boolean': 'boolean',
      'array': 'any[]',
      'object': 'Record<string, any>',
      'function': '(...args: any[]) => void'
    };
    return typeMap[type] || 'any';
  }

  generateVariantLogic(variants) {
    if (!variants || variants.length === 0) {
      return '  export let variant = \'\';';
    }

    const variantMap = variants.map(v =>
      `    '${v.name}': '${this.formatCssClassName(v.name)}'`
    ).join(',\n');

    return `  export let variant = '';

  const variantClasses = {
${variantMap}
  };`;
  }

  generateChildren(children) {
    if (!children || children.length === 0) return '';

    return children.map(child => {
      if (child.type === 'text') {
        return `<span>{${child.binding || `'${child.content}'`}}</span>`;
      }
      if (child.type === 'component') {
        return `<${this.formatComponentName(child.name)} />`;
      }
      return '';
    }).join('\n  ');
  }

  generateStyleBlock(styles, className) {
    if (!styles || Object.keys(styles).length === 0) {
      return `.${className} {\n  /* Component styles */\n}`;
    }

    return Object.entries(styles).map(([selector, rules]) => {
      const cssProps = Object.entries(rules)
        .map(([prop, value]) => `  ${prop}: ${value};`)
        .join('\n');
      return `.${selector} {\n${cssProps}\n}`;
    }).join('\n\n');
  }

  generateStyles(styles) {
    // Svelte styles are typically inline in SFC
    return null;
  }

  generateExports(components) {
    const exports = components.map(c => {
      const name = this.formatComponentName(c.name);
      return `export { default as ${name} } from './${name}.svelte';`;
    }).join('\n');

    return {
      filename: `index.${this.options.typescript ? 'ts' : 'js'}`,
      content: exports,
      type: 'index'
    };
  }

  generateStore(storeData) {
    const { name, state = {}, derived = [], actions = [] } = storeData;
    const storeName = this.formatPropName(name);

    const derivedStores = derived.map(d =>
      `export const ${d.name} = derived(${storeName}, $${storeName} => ${d.body});`
    ).join('\n');

    const actionFunctions = actions.map(a =>
      `export const ${a.name} = (${(a.params || []).join(', ')}) => {
  ${storeName}.update(state => {
    ${a.body}
    return state;
  });
};`
    ).join('\n\n');

    return {
      filename: `${storeName}Store.${this.options.typescript ? 'ts' : 'js'}`,
      content: `import { writable, derived } from 'svelte/store';

export const ${storeName} = writable(${JSON.stringify(state, null, 2)});

${derivedStores}

${actionFunctions}`,
      type: 'store'
    };
  }
}

// Angular Adapter
class AngularAdapter extends BaseAdapter {
  constructor(options = {}) {
    super('angular', {
      typescript: true, // Angular always uses TypeScript
      ...options
    });
    this.fileExtension = '.ts';
  }

  generateComponent(componentData) {
    const { name, props = [], styles = {}, children = [] } = componentData;
    const componentName = this.formatComponentName(name);
    const selector = this.formatCssClassName(name);

    const componentTs = this.generateComponentClass(componentData);
    const templateHtml = this.generateTemplate(componentData);
    const stylesCss = this.generateComponentStyles(styles, selector);

    this.emit('component:generated', { name: componentName, framework: 'angular' });

    return [
      {
        filename: `${selector}.component.ts`,
        content: componentTs,
        type: 'component'
      },
      {
        filename: `${selector}.component.html`,
        content: templateHtml,
        type: 'template'
      },
      {
        filename: `${selector}.component.${this.options.styleFormat}`,
        content: stylesCss,
        type: 'styles'
      }
    ];
  }

  generateComponentClass(componentData) {
    const { name, props = [] } = componentData;
    const componentName = this.formatComponentName(name);
    const selector = this.formatCssClassName(name);

    const inputDecorators = props.map(prop => {
      const propName = this.formatPropName(prop.name);
      const type = this.mapToTsType(prop.type);
      const defaultValue = prop.default !== undefined
        ? ` = ${JSON.stringify(prop.default)}`
        : '';
      return `  @Input() ${propName}${prop.required ? '!' : '?'}: ${type}${defaultValue};`;
    }).join('\n');

    return `import { Component, Input, Output, EventEmitter } from '@angular/core';

@Component({
  selector: '${selector}',
  templateUrl: './${selector}.component.html',
  styleUrls: ['./${selector}.component.${this.options.styleFormat}']
})
export class ${componentName}Component {
${inputDecorators}
  @Input() className = '';

  @Output() clicked = new EventEmitter<void>();
  @Output() changed = new EventEmitter<any>();

  onClick(): void {
    this.clicked.emit();
  }

  onChange(value: any): void {
    this.changed.emit(value);
  }
}`;
  }

  generateTemplate(componentData) {
    const { name, children = [] } = componentData;
    const selector = this.formatCssClassName(name);

    const childContent = this.generateTemplateChildren(children);

    return `<div [class]="'${selector} ' + className">
  ${childContent}
  <ng-content></ng-content>
</div>`;
  }

  generateTemplateChildren(children) {
    if (!children || children.length === 0) return '';

    return children.map(child => {
      if (child.type === 'text') {
        return `<span>{{ ${child.binding || `'${child.content}'`} }}</span>`;
      }
      if (child.type === 'component') {
        const selector = this.formatCssClassName(child.name);
        return `<${selector}></${selector}>`;
      }
      return '';
    }).join('\n  ');
  }

  generateComponentStyles(styles, className) {
    if (!styles || Object.keys(styles).length === 0) {
      return `:host {\n  display: block;\n}\n\n.${className} {\n  /* Component styles */\n}`;
    }

    const styleRules = Object.entries(styles).map(([selector, rules]) => {
      const cssProps = Object.entries(rules)
        .map(([prop, value]) => `  ${prop}: ${value};`)
        .join('\n');
      return `.${selector} {\n${cssProps}\n}`;
    }).join('\n\n');

    return `:host {\n  display: block;\n}\n\n${styleRules}`;
  }

  mapToTsType(type) {
    const typeMap = {
      'string': 'string',
      'number': 'number',
      'boolean': 'boolean',
      'array': 'any[]',
      'object': 'Record<string, any>',
      'function': '(...args: any[]) => void'
    };
    return typeMap[type] || 'any';
  }

  generateStyles(styles) {
    // Angular styles are component-specific
    return null;
  }

  generateExports(components) {
    const imports = components.map(c => {
      const name = this.formatComponentName(c.name);
      const selector = this.formatCssClassName(c.name);
      return `import { ${name}Component } from './${selector}/${selector}.component';`;
    }).join('\n');

    const declarations = components.map(c =>
      `${this.formatComponentName(c.name)}Component`
    ).join(',\n    ');

    return {
      filename: 'components.module.ts',
      content: `import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
${imports}

@NgModule({
  declarations: [
    ${declarations}
  ],
  imports: [
    CommonModule
  ],
  exports: [
    ${declarations}
  ]
})
export class ComponentsModule { }`,
      type: 'module'
    };
  }

  generateService(serviceData) {
    const { name, methods = [], state = {} } = serviceData;
    const serviceName = this.formatComponentName(name);

    const stateDeclaration = Object.keys(state).length > 0
      ? `private state = ${JSON.stringify(state, null, 2)};`
      : '';

    const methodDeclarations = methods.map(m =>
      `  ${m.name}(${(m.params || []).map(p => `${p.name}: ${p.type || 'any'}`).join(', ')}): ${m.returnType || 'void'} {
    ${m.body}
  }`
    ).join('\n\n');

    return {
      filename: `${this.formatCssClassName(name)}.service.ts`,
      content: `import { Injectable } from '@angular/core';

@Injectable({
  providedIn: 'root'
})
export class ${serviceName}Service {
  ${stateDeclaration}

${methodDeclarations}
}`,
      type: 'service'
    };
  }
}

// Framework Adapter Manager
class FrameworkAdapterManager extends EventEmitter {
  constructor() {
    super();
    this.adapters = new Map();
    this.registerBuiltInAdapters();
  }

  registerBuiltInAdapters() {
    this.registerAdapter('react', ReactAdapter);
    this.registerAdapter('vue', VueAdapter);
    this.registerAdapter('svelte', SvelteAdapter);
    this.registerAdapter('angular', AngularAdapter);
  }

  registerAdapter(name, AdapterClass) {
    this.adapters.set(name, AdapterClass);
    this.emit('adapter:registered', { name });
  }

  unregisterAdapter(name) {
    this.adapters.delete(name);
    this.emit('adapter:unregistered', { name });
  }

  getAdapter(name, options = {}) {
    const AdapterClass = this.adapters.get(name);
    if (!AdapterClass) {
      throw new Error(`Unknown framework adapter: ${name}`);
    }
    return new AdapterClass(options);
  }

  listAdapters() {
    return Array.from(this.adapters.keys());
  }

  hasAdapter(name) {
    return this.adapters.has(name);
  }

  async generateForFramework(framework, componentData, options = {}) {
    const adapter = this.getAdapter(framework, options);
    return adapter.generateComponent(componentData);
  }

  async generateBatch(framework, components, options = {}) {
    const adapter = this.getAdapter(framework, options);
    const results = [];

    for (const component of components) {
      const result = adapter.generateComponent(component);
      results.push(Array.isArray(result) ? result : [result]);
    }

    const exports = adapter.generateExports(components);
    if (exports) {
      results.push([exports]);
    }

    return results.flat();
  }
}

// Factory function
function createFrameworkAdapter(framework, options = {}) {
  const manager = new FrameworkAdapterManager();
  return manager.getAdapter(framework, options);
}

module.exports = {
  BaseAdapter,
  ReactAdapter,
  VueAdapter,
  SvelteAdapter,
  AngularAdapter,
  FrameworkAdapterManager,
  createFrameworkAdapter,
  SUPPORTED_FRAMEWORKS: ['react', 'vue', 'svelte', 'angular']
};

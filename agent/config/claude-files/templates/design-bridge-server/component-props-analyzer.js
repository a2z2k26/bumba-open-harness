/**
 * component-props-analyzer.js
 * Analyzes component files to extract props/properties
 *
 * Uses regex-based approach for simplicity (can be enhanced with AST parsing later)
 */

const fs = require('fs');
const path = require('path');

/**
 * Analyze component props from file
 *
 * @param {string} componentPath - Path to component file
 * @returns {Object} Analyzed props
 */
function analyzeComponentProps(componentPath) {
  if (!fs.existsSync(componentPath)) {
    return {};
  }

  const content = fs.readFileSync(componentPath, 'utf8');
  const ext = path.extname(componentPath);

  // Determine analysis strategy based on file type
  if (ext === '.tsx' || ext === '.ts') {
    return analyzeTypeScriptProps(content);
  } else if (ext === '.jsx' || ext === '.js') {
    return analyzeJavaScriptProps(content);
  } else if (ext === '.vue') {
    return analyzeVueProps(content);
  } else if (ext === '.svelte') {
    return analyzeSvelteProps(content);
  }

  return {};
}

/**
 * Analyze TypeScript/React props
 *
 * @param {string} content - File content
 * @returns {Object} Props
 */
function analyzeTypeScriptProps(content) {
  const props = {};

  // Match interface or type definitions
  const interfaceMatch = content.match(/interface\s+\w+Props\s*{([^}]+)}/);
  const typeMatch = content.match(/type\s+\w+Props\s*=\s*{([^}]+)}/);

  const propsText = interfaceMatch?.[1] || typeMatch?.[1] || '';

  if (!propsText) return {};

  // Parse individual prop lines
  const propLines = propsText.split('\n').filter(line => line.trim() && !line.trim().startsWith('//'));

  propLines.forEach(line => {
    // Match: propName?: type = default
    // Examples:
    //   label: string
    //   size?: 'sm' | 'md' | 'lg'
    //   disabled?: boolean
    //   onClick?: () => void
    const match = line.match(/(\w+)(\?)?\s*:\s*([^;,=]+)(?:\s*=\s*([^;,]+))?/);

    if (match) {
      const [, name, optional, typeStr, defaultValue] = match;

      props[name] = {
        type: inferType(typeStr.trim()),
        optional: !!optional,
        rawType: typeStr.trim()
      };

      // Extract enum values if union type
      if (typeStr.includes('|')) {
        const values = typeStr.split('|').map(v => v.trim().replace(/['"]/g, ''));
        props[name].values = values;
        props[name].type = 'enum';
      }

      // Parse default value if present
      if (defaultValue) {
        props[name].default = parseDefaultValue(defaultValue.trim());
      }
    }
  });

  return props;
}

/**
 * Analyze JavaScript/React props (PropTypes)
 *
 * @param {string} content - File content
 * @returns {Object} Props
 */
function analyzeJavaScriptProps(content) {
  const props = {};

  // Match PropTypes definition
  const propTypesMatch = content.match(/propTypes\s*=\s*{([^}]+)}/);

  if (!propTypesMatch) return {};

  const propsText = propTypesMatch[1];
  const propLines = propsText.split('\n').filter(line => line.trim());

  propLines.forEach(line => {
    // Match: propName: PropTypes.string.isRequired
    const match = line.match(/(\w+)\s*:\s*PropTypes\.(\w+)/);

    if (match) {
      const [, name, type] = match;
      const optional = !line.includes('.isRequired');

      props[name] = {
        type: type.toLowerCase(),
        optional,
        rawType: `PropTypes.${type}`
      };
    }
  });

  return props;
}

/**
 * Analyze Vue component props
 *
 * @param {string} content - File content
 * @returns {Object} Props
 */
function analyzeVueProps(content) {
  const props = {};

  // Match props definition in <script> section
  const propsMatch = content.match(/props\s*:\s*{([^}]+)}/);

  if (!propsMatch) return {};

  const propsText = propsMatch[1];
  const propLines = propsText.split('\n').filter(line => line.trim());

  propLines.forEach(line => {
    // Match: propName: { type: String, default: 'value' }
    const nameMatch = line.match(/(\w+)\s*:\s*{/);

    if (nameMatch) {
      const name = nameMatch[1];
      const typeMatch = line.match(/type\s*:\s*(\w+)/);
      const defaultMatch = line.match(/default\s*:\s*([^,}]+)/);
      const requiredMatch = line.match(/required\s*:\s*(\w+)/);

      props[name] = {
        type: (typeMatch?.[1] || 'String').toLowerCase(),
        optional: requiredMatch?.[1] !== 'true',
        rawType: typeMatch?.[1] || 'String'
      };

      if (defaultMatch) {
        props[name].default = parseDefaultValue(defaultMatch[1].trim());
      }
    }
  });

  return props;
}

/**
 * Analyze Svelte component props
 *
 * @param {string} content - File content
 * @returns {Object} Props
 */
function analyzeSvelteProps(content) {
  const props = {};

  // Match export let declarations
  const exportMatches = content.matchAll(/export\s+let\s+(\w+)(?:\s*:\s*([^=;]+))?(?:\s*=\s*([^;]+))?/g);

  for (const match of exportMatches) {
    const [, name, typeStr, defaultValue] = match;

    props[name] = {
      type: typeStr ? inferType(typeStr.trim()) : 'string',
      optional: !!defaultValue,
      rawType: typeStr?.trim() || 'any'
    };

    if (defaultValue) {
      props[name].default = parseDefaultValue(defaultValue.trim());
    }

    // Check for union types
    if (typeStr && typeStr.includes('|')) {
      const values = typeStr.split('|').map(v => v.trim().replace(/['"]/g, ''));
      props[name].values = values;
      props[name].type = 'enum';
    }
  }

  return props;
}

/**
 * Infer prop type from TypeScript type string
 *
 * @param {string} typeStr - Type string
 * @returns {string} Inferred type
 */
function inferType(typeStr) {
  const lower = typeStr.toLowerCase();

  if (lower === 'string') return 'string';
  if (lower === 'number') return 'number';
  if (lower === 'boolean') return 'boolean';
  if (lower.includes('|')) return 'enum';
  if (lower.includes('[]') || lower.includes('array')) return 'array';
  if (lower.includes('=>') || lower.includes('function')) return 'function';
  if (lower === 'object') return 'object';

  return 'string'; // Default fallback
}

/**
 * Parse default value from string
 *
 * @param {string} valueStr - Default value string
 * @returns {*} Parsed value
 */
function parseDefaultValue(valueStr) {
  // Remove quotes
  if ((valueStr.startsWith("'") && valueStr.endsWith("'")) ||
      (valueStr.startsWith('"') && valueStr.endsWith('"'))) {
    return valueStr.slice(1, -1);
  }

  // Boolean
  if (valueStr === 'true') return true;
  if (valueStr === 'false') return false;

  // Number
  if (!isNaN(valueStr)) return Number(valueStr);

  // Null/undefined
  if (valueStr === 'null') return null;
  if (valueStr === 'undefined') return undefined;

  // Return as string
  return valueStr;
}

module.exports = {
  analyzeComponentProps,
  analyzeTypeScriptProps,
  analyzeJavaScriptProps,
  analyzeVueProps,
  analyzeSvelteProps
};

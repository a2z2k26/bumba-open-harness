/**
 * variant-sync.js
 * Cross-Framework Variant Synchronization Module (P6)
 *
 * This module normalizes variant data from Figma extraction into a universal format
 * that works across ALL framework optimizers. It bridges the gap between:
 *
 * Group 1 (uses variant.name): React, Vue, Flutter, React Native, Web Components
 * Group 2 (uses variant.property + variant.values): Angular, Svelte, SwiftUI, Jetpack Compose
 *
 * The normalized format includes all fields so any optimizer can use its preferred keys.
 */

const fs = require('fs');
const path = require('path');

/**
 * Normalize a single variant to the universal format
 * @param {Object} variant - Raw variant from Figma extraction or registry
 * @returns {Object} Normalized variant with all fields populated
 */
function normalizeVariant(variant) {
  if (!variant) return null;

  // Determine the property name (some sources use 'name', others use 'property')
  const propertyName = variant.property || variant.name || 'variant';

  // Determine the values array (may come from 'values', 'options', or need extraction)
  let values = [];
  if (Array.isArray(variant.values)) {
    values = variant.values;
  } else if (Array.isArray(variant.options)) {
    values = variant.options;
  } else if (variant.type && typeof variant.type === 'string' && variant.type.includes('|')) {
    // Extract from union type string like "'sm' | 'md' | 'lg'"
    values = variant.type
      .split('|')
      .map(s => s.trim().replace(/^['"]|['"]$/g, ''))
      .filter(Boolean);
  }

  // Determine default value
  let defaultValue = variant.default;
  if (defaultValue && typeof defaultValue === 'string') {
    // Remove quotes from default if present
    defaultValue = defaultValue.replace(/^['"]|['"]$/g, '');
  }
  if (!defaultValue && values.length > 0) {
    defaultValue = values[0];
  }

  // Build normalized variant object
  return {
    // Group 1 fields (React, Vue, Flutter, RN, WebComp)
    name: propertyName,

    // Group 2 fields (Angular, Svelte, SwiftUI, JetpackCompose)
    property: propertyName,
    values: values,

    // Figma-compatible alias
    options: values,

    // Common fields
    default: defaultValue,
    type: isTypeScriptType(variant.type) ? variant.type : inferTypeFromValues(values),

    // Optional styling data (React Native, Web Components)
    styles: variant.styles || {},

    // Optional props for story generation
    props: variant.props || {},

    // Preserve original for debugging
    _original: variant
  };
}

/**
 * Check if a type string looks like a TypeScript type (vs Figma category)
 * @param {string} type - Type string to check
 * @returns {boolean} True if it's a TypeScript type
 */
function isTypeScriptType(type) {
  if (!type || typeof type !== 'string') return false;
  // TypeScript types contain '|' for unions or are primitives
  const primitives = ['string', 'number', 'boolean', 'any', 'void', 'null', 'undefined'];
  return type.includes('|') || primitives.includes(type.toLowerCase());
}

/**
 * Infer TypeScript type from values array
 * @param {Array} values - Array of possible values
 * @returns {string} TypeScript union type or 'string'
 */
function inferTypeFromValues(values) {
  if (!Array.isArray(values) || values.length === 0) {
    return 'string';
  }

  // Check if all values are boolean-like
  const boolValues = values.map(v => String(v).toLowerCase());
  if (boolValues.every(v => v === 'true' || v === 'false')) {
    return 'boolean';
  }

  // Generate union type
  return values.map(v => `'${v}'`).join(' | ');
}

/**
 * Normalize variants from either array or object format
 * @param {Array|Object} variants - Raw variants (array or COMPONENT_SET object format)
 * @returns {Array} Array of normalized variants
 */
function normalizeVariants(variants) {
  // Handle array format (already in expected format)
  if (Array.isArray(variants)) {
    return variants.map(normalizeVariant).filter(Boolean);
  }

  // Handle object format from Figma COMPONENT_SET
  // Format: { Type: ['Filled', 'Outline'], Size: ['Small', 'Medium', 'Large'] }
  if (variants && typeof variants === 'object') {
    const normalizedArray = [];

    Object.entries(variants).forEach(([propName, values]) => {
      if (Array.isArray(values) && values.length > 0) {
        // Create a normalized variant object for each property
        normalizedArray.push(normalizeVariant({
          name: propName,
          property: propName,
          values: values,
          default: values[0]
        }));
      }
    });

    return normalizedArray.filter(Boolean);
  }

  return [];
}

/**
 * Read and normalize variants from component registry
 * @param {string} componentId - Component ID in registry
 * @param {string} projectPath - Project root path
 * @returns {Promise<Array>} Normalized variants array
 */
async function getCanonicalVariants(componentId, projectPath = process.cwd()) {
  const registryPath = path.join(projectPath, '.design', 'componentRegistry.json');

  if (!fs.existsSync(registryPath)) {
    return [];
  }

  let registry;
  try {
    const content = fs.readFileSync(registryPath, 'utf8');
    registry = JSON.parse(content);
  } catch (error) {
    console.warn(`[variant-sync] Failed to read registry: ${error.message}`);
    return [];
  }

  // Find component in registry
  const component = findComponentInRegistry(registry, componentId);
  if (!component) {
    return [];
  }

  // Get variants from component entry
  const rawVariants = component.variants || component.variantProperties || [];
  return normalizeVariants(rawVariants);
}

/**
 * Find component in registry by ID
 * @param {Object} registry - Component registry
 * @param {string} componentId - Component ID to find
 * @returns {Object|null} Component entry or null
 */
function findComponentInRegistry(registry, componentId) {
  if (!registry || !registry.components) {
    return null;
  }

  // Direct lookup
  if (registry.components[componentId]) {
    return registry.components[componentId];
  }

  // Search by ID field
  for (const [key, component] of Object.entries(registry.components)) {
    if (component.id === componentId || key === componentId) {
      return component;
    }
  }

  return null;
}

/**
 * Apply framework-specific transformations (optional)
 * Most frameworks can use the normalized format directly.
 * This function applies any final adjustments if needed.
 *
 * @param {Array} variants - Normalized variants
 * @param {string} framework - Target framework name
 * @returns {Array} Framework-ready variants
 */
function syncToFramework(variants, framework) {
  const normalized = normalizeVariants(variants);

  // Framework-specific adjustments (currently minimal)
  switch (framework) {
    case 'flutter':
      // Flutter uses variant.name for enum generation
      return normalized.map(v => ({
        ...v,
        enumName: toTitleCase(v.name) + 'Variant'
      }));

    case 'swiftui':
    case 'jetpack-compose':
      // These use property + values and generate typed enums
      return normalized.map(v => ({
        ...v,
        enumName: toTitleCase(v.property) + 'Style',
        enumCases: (v.values || []).map(val => toEnumCase(val))
      }));

    case 'angular':
    case 'svelte':
      // These use property + values for input bindings
      return normalized;

    case 'react':
    case 'vue':
    case 'react-native':
    case 'web-components':
    default:
      // These use name primarily
      return normalized;
  }
}

/**
 * Convert string to TitleCase
 * @param {string} str - Input string
 * @returns {string} TitleCase string
 */
function toTitleCase(str) {
  if (!str) return '';
  return str
    .replace(/[^a-zA-Z0-9]+(.)/g, (_, c) => c.toUpperCase())
    .replace(/^[a-z]/, c => c.toUpperCase());
}

/**
 * Convert value to valid enum case name
 * @param {string} value - Variant value
 * @returns {string} Valid enum case
 */
function toEnumCase(value) {
  if (!value) return '';
  // For Swift/Kotlin: lowercase with underscores for non-alphanumeric
  return String(value)
    .toLowerCase()
    .replace(/[^a-z0-9]/g, '_')
    .replace(/^_+|_+$/g, '')
    .replace(/_+/g, '_');
}

/**
 * Validate that variants are properly normalized
 * @param {Array} variants - Variants to validate
 * @returns {Object} Validation result with { valid, errors }
 */
function validateVariants(variants) {
  const errors = [];

  if (!Array.isArray(variants)) {
    return { valid: false, errors: ['variants must be an array'] };
  }

  variants.forEach((v, i) => {
    if (!v.name && !v.property) {
      errors.push(`Variant ${i}: missing both name and property`);
    }
    if (!v.values && !v.options) {
      errors.push(`Variant ${i} (${v.name || v.property}): missing values array`);
    }
  });

  return {
    valid: errors.length === 0,
    errors
  };
}

/**
 * Merge variants from multiple sources, keeping the most complete version
 * @param {Array} sources - Array of variant arrays from different sources
 * @returns {Array} Merged and deduplicated variants
 */
function mergeVariants(...sources) {
  const variantMap = new Map();

  for (const source of sources) {
    if (!Array.isArray(source)) continue;

    for (const variant of source) {
      const normalized = normalizeVariant(variant);
      if (!normalized) continue;

      const key = normalized.name || normalized.property;
      const existing = variantMap.get(key);

      if (!existing) {
        variantMap.set(key, normalized);
      } else {
        // Merge: prefer the one with more values
        const existingValues = existing.values?.length || 0;
        const newValues = normalized.values?.length || 0;

        if (newValues > existingValues) {
          variantMap.set(key, {
            ...existing,
            ...normalized,
            values: normalized.values,
            options: normalized.values
          });
        }
      }
    }
  }

  return Array.from(variantMap.values());
}

module.exports = {
  normalizeVariant,
  normalizeVariants,
  getCanonicalVariants,
  syncToFramework,
  validateVariants,
  mergeVariants,
  // Utilities
  inferTypeFromValues,
  toTitleCase,
  toEnumCase
};

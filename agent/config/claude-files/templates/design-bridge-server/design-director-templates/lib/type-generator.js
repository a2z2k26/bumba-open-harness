/**
 * Type Generator - Generate TypeScript interfaces from data structures
 *
 * Infers TypeScript types from JSON data and entity definitions,
 * generating type definition files for the product.
 */

const fs = require('fs');
const path = require('path');

/**
 * Infer TypeScript type from JavaScript value
 * @param {*} value - Value to infer type from
 * @param {string} interfaceName - Name for generated interface (if object)
 * @returns {string} - TypeScript type string
 */
function inferTypeFromValue(value, interfaceName = 'Unknown') {
  if (value === null || value === undefined) {
    return 'any';
  }

  const type = typeof value;

  // Handle arrays
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return 'any[]';
    }
    const elementType = inferTypeFromValue(value[0], interfaceName);
    return `${elementType}[]`;
  }

  // Handle objects
  if (type === 'object') {
    return interfaceName;
  }

  // Handle primitives
  if (type === 'string') {
    // Check for date strings
    const datePattern = /^\d{4}-\d{2}-\d{2}/;
    if (datePattern.test(value)) {
      return 'Date | string';
    }
    return 'string';
  }

  if (type === 'number') {
    return 'number';
  }

  if (type === 'boolean') {
    return 'boolean';
  }

  return 'any';
}

/**
 * Generate TypeScript interface from JSON object
 * @param {Object} jsonData - JSON object to convert
 * @param {string} interfaceName - Name for the interface
 * @returns {string} - TypeScript interface definition
 */
function generateInterfaceFromJSON(jsonData, interfaceName = 'DataType') {
  if (!jsonData || typeof jsonData !== 'object' || Array.isArray(jsonData)) {
    return `export type ${interfaceName} = any;`;
  }

  let typescript = `export interface ${interfaceName} {\n`;

  Object.keys(jsonData).forEach(key => {
    const value = jsonData[key];
    const tsType = inferTypeFromValue(value, `${interfaceName}${capitalize(key)}`);

    // Generate nested interfaces if needed
    if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
      typescript = generateInterfaceFromJSON(value, `${interfaceName}${capitalize(key)}`) + '\n\n' + typescript;
    }

    typescript += `  ${key}: ${tsType};\n`;
  });

  typescript += '}';

  return typescript;
}

/**
 * Capitalize first letter of string
 * @param {string} str - String to capitalize
 * @returns {string} - Capitalized string
 */
function capitalize(str) {
  return str.charAt(0).toUpperCase() + str.slice(1);
}

/**
 * Generate TypeScript types from data model entities
 * @param {Array} entities - Array of {name, attributes: [{name, type}]}
 * @returns {string} - Path to generated types file
 */
function generateDataModelTypes(entities) {
  let typescript = '// Generated TypeScript interfaces for data model\n';
  typescript += '// DO NOT EDIT - Regenerate via /director-data-model command\n\n';

  entities.forEach(entity => {
    typescript += `export interface ${entity.name} {\n`;

    entity.attributes.forEach(attr => {
      const optional = attr.required === false ? '?' : '';
      typescript += `  ${attr.name}${optional}: ${attr.type};\n`;
    });

    typescript += '}\n\n';
  });

  const outputPath = path.resolve(__dirname, '../product/data-model/types.ts');
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, typescript, 'utf-8');

  console.log(`[type-generator] Generated: ${outputPath}`);
  return outputPath;
}

/**
 * Generate TypeScript types from sample data JSON
 * @param {string} sectionId - Section identifier
 * @param {Object} sampleData - Sample data object
 * @returns {string} - Path to generated types file
 */
function generateSectionTypes(sectionId, sampleData) {
  const interfaceName = `${capitalize(sectionId.replace(/-/g, ''))}Data`;

  let typescript = '// Generated TypeScript interfaces for section sample data\n';
  typescript += '// AUTO-GENERATED when data.json changes (via on-director-data-change hook)\n\n';

  typescript += generateInterfaceFromJSON(sampleData, interfaceName);

  const outputPath = path.resolve(__dirname, `../product/sections/${sectionId}/types.ts`);
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, typescript, 'utf-8');

  console.log(`[type-generator] Generated: ${outputPath}`);
  return outputPath;
}

module.exports = {
  generateDataModelTypes,
  generateSectionTypes,
  inferTypeFromValue,
  generateInterfaceFromJSON
};

/**
 * Spec Generator - Generate markdown specifications from Handlebars templates
 *
 * Reads Handlebars templates, compiles them with data, and writes
 * markdown specifications to the product/ directory.
 */

const fs = require('fs');
const path = require('path');
const Handlebars = require('handlebars');

/**
 * Load and compile a Handlebars template
 * @param {string} templateName - Name of template file (without .tmpl extension)
 * @returns {Function} - Compiled Handlebars template function
 */
function loadTemplate(templateName) {
  const templatePath = path.resolve(__dirname, '../templates', `${templateName}.tmpl`);

  if (!fs.existsSync(templatePath)) {
    throw new Error(`Template not found: ${templateName} at ${templatePath}`);
  }

  const templateSource = fs.readFileSync(templatePath, 'utf-8');
  return Handlebars.compile(templateSource);
}

/**
 * Generate product overview specification
 * @param {Object} data - Product data {productName, description, problems, features}
 * @param {Object} bumbaContext - Bumba context from getBumbaContext()
 * @returns {string} - Path to generated file
 */
function generateProductOverview(data, bumbaContext) {
  const template = loadTemplate('product-overview.md');

  const markdown = template({
    ...data,
    bumbaTokensAvailable: bumbaContext.hasTokens,
    tokenFiles: bumbaContext.tokens ? Object.keys(bumbaContext.tokens) : [],
    framework: bumbaContext.framework
  });

  const outputPath = path.resolve(__dirname, '../product/product-overview.md');
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, markdown, 'utf-8');

  console.log(`[spec-generator] Generated: ${outputPath}`);
  return outputPath;
}

/**
 * Generate product roadmap specification
 * @param {Array} sections - Array of {title, description, id}
 * @returns {string} - Path to generated file
 */
function generateProductRoadmap(sections) {
  const template = loadTemplate('product-roadmap.md');

  const markdown = template({ sections });

  const outputPath = path.resolve(__dirname, '../product/product-roadmap.md');
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, markdown, 'utf-8');

  console.log(`[spec-generator] Generated: ${outputPath}`);
  return outputPath;
}

/**
 * Generate data model specification
 * @param {Array} entities - Array of {name, description, attributes, relationships}
 * @returns {string} - Path to generated file
 */
function generateDataModelSpec(entities) {
  const template = loadTemplate('data-model.md');

  const markdown = template({ entities });

  const outputPath = path.resolve(__dirname, '../product/data-model/data-model.md');
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, markdown, 'utf-8');

  console.log(`[spec-generator] Generated: ${outputPath}`);
  return outputPath;
}

/**
 * Generate shell specification
 * @param {Object} data - Shell data {navItems, layoutPattern}
 * @param {Object} bumbaContext - Bumba context from getBumbaContext()
 * @returns {string} - Path to generated file
 */
function generateShellSpec(data, bumbaContext) {
  const template = loadTemplate('shell-spec.md');

  const markdown = template({
    ...data,
    bumbaLayoutsAvailable: bumbaContext.hasComponents, // Layouts are components
    framework: bumbaContext.framework
  });

  const outputPath = path.resolve(__dirname, '../product/shell/spec.md');
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, markdown, 'utf-8');

  console.log(`[spec-generator] Generated: ${outputPath}`);
  return outputPath;
}

/**
 * Generate section specification
 * @param {string} sectionId - Section identifier (slug)
 * @param {Object} data - Section data {userFlows, uiRequirements, dataRequirements}
 * @param {Object} bumbaContext - Bumba context from getBumbaContext()
 * @returns {string} - Path to generated file
 */
function generateSectionSpec(sectionId, data, bumbaContext) {
  const template = loadTemplate('section-spec.md');

  const markdown = template({
    ...data,
    sectionId,
    bumbaComponentsAvailable: bumbaContext.hasComponents,
    bumbaComponents: bumbaContext.components || [],
    framework: bumbaContext.framework
  });

  const outputPath = path.resolve(__dirname, `../product/sections/${sectionId}/spec.md`);
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, markdown, 'utf-8');

  console.log(`[spec-generator] Generated: ${outputPath}`);
  return outputPath;
}

module.exports = {
  loadTemplate,
  generateProductOverview,
  generateProductRoadmap,
  generateDataModelSpec,
  generateShellSpec,
  generateSectionSpec
};

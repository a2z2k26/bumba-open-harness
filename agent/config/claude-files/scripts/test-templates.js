#!/usr/bin/env node
/**
 * test-templates.js
 * Validate all template files for JSON syntax and schema compliance
 */

const fs = require('fs');
const path = require('path');

const templatesDir = path.join(__dirname, '../templates/design-init');
const results = {
  total: 0,
  passed: 0,
  failed: 0,
  errors: []
};

console.log('=== TEMPLATE VALIDATION TEST ===\n');

// Get all JSON template files
const templateFiles = fs.readdirSync(templatesDir)
  .filter(f => f.endsWith('.json'));

results.total = templateFiles.length;

templateFiles.forEach(filename => {
  const filepath = path.join(templatesDir, filename);
  const templateName = path.basename(filename, '.json');

  console.log(`Testing: ${filename}`);

  try {
    // Test 1: Valid JSON
    const content = fs.readFileSync(filepath, 'utf8');
    const template = JSON.parse(content);
    console.log('  ✅ Valid JSON');

    // Test 2: Required fields
    const required = ['name', 'description', 'framework', 'typescript', 'outputPath'];
    const missing = required.filter(field => !(field in template));

    if (missing.length > 0) {
      throw new Error(`Missing required fields: ${missing.join(', ')}`);
    }
    console.log('  ✅ All required fields present');

    // Test 3: Name matches filename
    if (template.name !== templateName) {
      throw new Error(`Template name '${template.name}' doesn't match filename '${templateName}'`);
    }
    console.log('  ✅ Name matches filename');

    // Test 4: Valid framework
    const validFrameworks = ['react', 'vue', 'angular', 'svelte', 'react-native', 'flutter', 'swiftui', 'jetpack-compose'];
    if (!validFrameworks.includes(template.framework)) {
      throw new Error(`Invalid framework: ${template.framework}`);
    }
    console.log('  ✅ Valid framework');

    // Test 5: TypeScript is boolean
    if (typeof template.typescript !== 'boolean') {
      throw new Error(`TypeScript must be boolean, got: ${typeof template.typescript}`);
    }
    console.log('  ✅ TypeScript is boolean');

    // Test 6: Output path is relative
    if (template.outputPath.startsWith('/')) {
      throw new Error(`Output path must be relative, not absolute: ${template.outputPath}`);
    }
    console.log('  ✅ Output path is relative');

    console.log(`  ✅ ${filename} PASSED\n`);
    results.passed++;

  } catch (error) {
    console.log(`  ❌ ${filename} FAILED: ${error.message}\n`);
    results.failed++;
    results.errors.push({ filename, error: error.message });
  }
});

// Summary
console.log('=== VALIDATION SUMMARY ===');
console.log(`Total templates: ${results.total}`);
console.log(`Passed: ${results.passed}`);
console.log(`Failed: ${results.failed}`);

if (results.failed > 0) {
  console.log('\nErrors:');
  results.errors.forEach(e => {
    console.log(`  - ${e.filename}: ${e.error}`);
  });
  process.exit(1);
} else {
  console.log('\n✅ All templates valid!');
  process.exit(0);
}

#!/usr/bin/env node
/**
 * generate-stories.js
 * CLI for generating Storybook stories from components
 */

const { StoryGenerator } = require('/opt/bumba-harness/Bumba - DesignBridge/design-feature/packages/@design-bridge/server/story-generator');
const { analyzeComponentProps } = require('/opt/bumba-harness/Bumba - DesignBridge/design-feature/packages/@design-bridge/server/component-props-analyzer');
const fs = require('fs');
const path = require('path');

/**
 * Find all component files in a directory
 *
 * @param {string} dir - Directory to search
 * @param {string} ext - File extension to match
 * @returns {string[]} Array of component file paths
 */
function findComponents(dir, ext = '.tsx') {
  const components = [];

  function walk(currentDir) {
    if (!fs.existsSync(currentDir)) return;

    const entries = fs.readdirSync(currentDir, { withFileTypes: true });

    for (const entry of entries) {
      const fullPath = path.join(currentDir, entry.name);

      if (entry.isDirectory()) {
        walk(fullPath);
      } else if (entry.isFile() && entry.name.endsWith(ext) && !entry.name.includes('.stories.')) {
        components.push(fullPath);
      }
    }
  }

  walk(dir);
  return components;
}

/**
 * Generate stories for a project
 *
 * @param {string} projectPath - Project root path
 * @param {string} framework - Framework name
 */
async function generateStoriesForProject(projectPath = process.cwd(), framework = 'react') {
  console.log(`\n📖 Generating Storybook stories for ${framework}...\n`);

  const componentDir = path.join(projectPath, '.design/extracted-code', framework, 'components');

  if (!fs.existsSync(componentDir)) {
    console.error(`❌ Component directory not found: ${componentDir}`);
    console.log('\nRun transformation first:');
    console.log(`  /transform-${framework}\n`);
    return;
  }

  // Determine file extension
  const extMap = {
    'react': '.tsx',
    'vue': '.vue',
    'angular': '.component.ts',
    'svelte': '.svelte',
    'react-native': '.tsx'
  };

  const ext = extMap[framework] || '.tsx';

  // Find component files
  const componentFiles = findComponents(componentDir, ext);

  if (componentFiles.length === 0) {
    console.log(`⚠️  No ${ext} component files found in ${componentDir}\n`);
    return;
  }

  console.log(`Found ${componentFiles.length} component files\n`);

  // Create story generator
  const generator = new StoryGenerator({ framework });

  let generated = 0;
  let skipped = 0;
  let errors = 0;

  for (const file of componentFiles) {
    try {
      const componentName = path.basename(file, ext);

      // Check if story already exists
      const storyPath = file.replace(ext, `.stories${ext}`);
      if (fs.existsSync(storyPath)) {
        console.log(`⏭️  Skipped (exists): ${componentName}`);
        skipped++;
        continue;
      }

      // Analyze component props
      const props = analyzeComponentProps(file);

      // Create component data
      const componentData = {
        name: componentName,
        title: `Components/${componentName}`,
        props: props,
        figmaUrl: '', // Can be populated from metadata
        layout: 'centered'
      };

      // Generate and write story
      const writtenPath = generator.generateAndWriteStory(componentData, file, framework);

      if (writtenPath) {
        console.log(`✅ Generated: ${path.relative(projectPath, writtenPath)}`);
        generated++;
      }
    } catch (error) {
      console.error(`❌ Error processing ${file}:`, error.message);
      errors++;
    }
  }

  // Summary
  console.log(`\n📊 Story Generation Summary`);
  console.log(`   Generated: ${generated}`);
  console.log(`   Skipped:   ${skipped}`);
  console.log(`   Errors:    ${errors}`);
  console.log(`   Total:     ${componentFiles.length}\n`);

  if (generated > 0) {
    console.log(`✅ Story generation complete!`);
    console.log(`\nNext steps:`);
    console.log(`  1. Review generated stories`);
    console.log(`  2. Run: npm run storybook`);
    console.log(`  3. View stories at http://localhost:6006\n`);
  }
}

// CLI execution
if (require.main === module) {
  const framework = process.argv[2] || 'react';
  const projectPath = process.cwd();

  generateStoriesForProject(projectPath, framework)
    .catch(err => {
      console.error('\n❌ Story generation failed:', err.message);
      process.exit(1);
    });
}

module.exports = { generateStoriesForProject, findComponents };

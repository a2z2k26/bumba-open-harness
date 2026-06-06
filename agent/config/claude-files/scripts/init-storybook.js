#!/usr/bin/env node
/**
 * init-storybook.js
 * Initialize Storybook with canonical BUMBA theme
 *
 * IMPORTANT: This script copies the canonical BUMBA Storybook theme from
 * design-feature/.storybook/ which contains all 6 required files:
 * - theme.js (brand colors, typography, theme exports)
 * - manager.js (manager UI configuration)
 * - preview.jsx (preview decorators and parameters)
 * - main.js (main config with CSS injection)
 * - bumba-manager.css (manager UI styling)
 * - bumba-preview.css (preview canvas styles)
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

// Canonical theme files (all required for BUMBA brand)
const CANONICAL_THEME_FILES = [
  'theme.js',
  'manager.js',
  'preview.jsx',
  'main.js',
  'bumba-manager.css',
  'bumba-preview.css'
];

function initStorybook(projectPath = process.cwd(), framework = 'react') {
  console.log('\n📚 Initializing Storybook with BUMBA theme...\n');

  const storybookDir = path.join(projectPath, '.storybook');

  // Check if Storybook already exists
  if (fs.existsSync(storybookDir)) {
    console.log('✅ Storybook directory exists');
    console.log(`   Location: ${storybookDir}\n`);
  } else {
    // Create .storybook directory
    fs.mkdirSync(storybookDir, { recursive: true });
    console.log('✅ Created .storybook directory\n');
  }

  // Install Storybook 10 dependencies
  console.log('📦 Installing Storybook 10 dependencies...\n');
  try {
    execSync('npm install --save-dev storybook@^10.0.8 @storybook/react-vite@^10.0.8 @storybook/addon-docs@^10.0.8', {
      cwd: projectPath,
      stdio: 'inherit'
    });
    console.log('\n✅ Storybook dependencies installed\n');
  } catch (error) {
    console.error('\n⚠️  Failed to install dependencies. Continuing with theme copy...\n');
  }

  // Copy canonical theme files
  copyCanonicalTheme(projectPath);

  // Update package.json scripts
  updatePackageJsonScripts(projectPath);

  console.log('\n✅ Storybook initialized with canonical BUMBA theme!');
  console.log('\nNext steps:');
  console.log('  1. Run Storybook: npm run storybook');
  console.log('  2. View at: http://localhost:6006\n');
}

function copyCanonicalTheme(projectPath) {
  console.log('📋 Copying canonical BUMBA theme...\n');

  const storybookDir = path.join(projectPath, '.storybook');

  // Find canonical theme location (design-feature/.storybook/)
  const canonicalDir = path.join(__dirname, '../../.storybook');

  if (!fs.existsSync(canonicalDir)) {
    console.error('❌ Canonical theme not found at:', canonicalDir);
    console.error('   Please ensure design-feature/.storybook/ exists with all theme files.\n');
    return false;
  }

  // Copy all canonical theme files
  let copiedCount = 0;
  for (const file of CANONICAL_THEME_FILES) {
    const srcPath = path.join(canonicalDir, file);
    const destPath = path.join(storybookDir, file);

    if (fs.existsSync(srcPath)) {
      fs.copyFileSync(srcPath, destPath);
      console.log(`  ✅ Copied ${file}`);
      copiedCount++;
    } else {
      console.warn(`  ⚠️  Missing: ${file}`);
    }
  }

  console.log(`\n  Copied ${copiedCount}/${CANONICAL_THEME_FILES.length} theme files\n`);

  if (copiedCount < CANONICAL_THEME_FILES.length) {
    console.warn('⚠️  Some theme files were missing. BUMBA theme may not display correctly.\n');
  }

  return copiedCount === CANONICAL_THEME_FILES.length;
}

function updatePackageJsonScripts(projectPath) {
  const packageJsonPath = path.join(projectPath, 'package.json');

  if (!fs.existsSync(packageJsonPath)) {
    console.warn('⚠️  No package.json found. Skipping script update.\n');
    return;
  }

  try {
    const packageJson = JSON.parse(fs.readFileSync(packageJsonPath, 'utf8'));

    if (!packageJson.scripts) {
      packageJson.scripts = {};
    }

    // Add Storybook scripts if not present
    if (!packageJson.scripts.storybook) {
      packageJson.scripts.storybook = 'storybook dev -p 6006';
      console.log('  ✅ Added "storybook" script');
    }

    if (!packageJson.scripts['build-storybook']) {
      packageJson.scripts['build-storybook'] = 'storybook build';
      console.log('  ✅ Added "build-storybook" script');
    }

    fs.writeFileSync(packageJsonPath, JSON.stringify(packageJson, null, 2) + '\n', 'utf8');
  } catch (error) {
    console.error('⚠️  Failed to update package.json:', error.message);
  }
}

// CLI execution
if (require.main === module) {
  const framework = process.argv[2] || 'react';
  initStorybook(process.cwd(), framework);
}

module.exports = { initStorybook, copyCanonicalTheme };

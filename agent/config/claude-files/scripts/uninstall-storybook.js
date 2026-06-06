#!/usr/bin/env node
/**
 * uninstall-storybook.js
 * Safely remove Storybook installation for testing purposes
 *
 * This script will:
 * 1. Remove .storybook/ directory
 * 2. Remove Storybook dependencies from package.json
 * 3. Remove Storybook scripts from package.json
 * 4. Clean node_modules of Storybook packages
 * 5. Create a backup before removal
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

function createBackup(projectPath) {
  console.log('\n📦 Creating backup...\n');

  const backupDir = path.join(projectPath, '.storybook-backup');
  const storybookDir = path.join(projectPath, '.storybook');
  const packageJsonPath = path.join(projectPath, 'package.json');

  // Create backup directory
  if (!fs.existsSync(backupDir)) {
    fs.mkdirSync(backupDir, { recursive: true });
  }

  // Backup .storybook directory
  if (fs.existsSync(storybookDir)) {
    const backupStorybookDir = path.join(backupDir, 'storybook-' + Date.now());
    fs.cpSync(storybookDir, backupStorybookDir, { recursive: true });
    console.log(`  ✅ Backed up .storybook/ to ${backupStorybookDir}`);
  }

  // Backup package.json
  if (fs.existsSync(packageJsonPath)) {
    const backupPackageJson = path.join(backupDir, `package.json.backup-${Date.now()}`);
    fs.copyFileSync(packageJsonPath, backupPackageJson);
    console.log(`  ✅ Backed up package.json to ${backupPackageJson}`);
  }

  console.log('');
}

function removeStorybookDirectory(projectPath) {
  console.log('🗑️  Removing .storybook directory...\n');

  const storybookDir = path.join(projectPath, '.storybook');

  if (fs.existsSync(storybookDir)) {
    fs.rmSync(storybookDir, { recursive: true, force: true });
    console.log('  ✅ Removed .storybook/\n');
  } else {
    console.log('  ℹ️  No .storybook/ directory found\n');
  }
}

function removeStorybookFromPackageJson(projectPath) {
  console.log('📝 Cleaning package.json...\n');

  const packageJsonPath = path.join(projectPath, 'package.json');

  if (!fs.existsSync(packageJsonPath)) {
    console.log('  ℹ️  No package.json found\n');
    return;
  }

  const packageJson = JSON.parse(fs.readFileSync(packageJsonPath, 'utf8'));
  let modified = false;

  // Remove Storybook dependencies
  const depsToRemove = [
    'dependencies',
    'devDependencies'
  ];

  depsToRemove.forEach(depType => {
    if (packageJson[depType]) {
      const originalCount = Object.keys(packageJson[depType]).length;

      // Remove all @storybook/* packages
      Object.keys(packageJson[depType]).forEach(dep => {
        if (dep.startsWith('@storybook/') || dep === 'storybook') {
          delete packageJson[depType][dep];
          modified = true;
        }
      });

      const newCount = Object.keys(packageJson[depType]).length;
      if (originalCount !== newCount) {
        console.log(`  ✅ Removed ${originalCount - newCount} Storybook packages from ${depType}`);
      }
    }
  });

  // Remove Storybook scripts
  if (packageJson.scripts) {
    const scriptsToRemove = ['storybook', 'build-storybook'];
    scriptsToRemove.forEach(script => {
      if (packageJson.scripts[script]) {
        delete packageJson.scripts[script];
        console.log(`  ✅ Removed script: ${script}`);
        modified = true;
      }
    });
  }

  if (modified) {
    fs.writeFileSync(packageJsonPath, JSON.stringify(packageJson, null, 2) + '\n', 'utf8');
    console.log('  ✅ Updated package.json\n');
  } else {
    console.log('  ℹ️  No Storybook entries found in package.json\n');
  }
}

function cleanNodeModules(projectPath) {
  console.log('🧹 Cleaning node_modules...\n');

  const nodeModulesPath = path.join(projectPath, 'node_modules');

  if (!fs.existsSync(nodeModulesPath)) {
    console.log('  ℹ️  No node_modules directory found\n');
    return;
  }

  // Remove @storybook directory
  const storybookModulesPath = path.join(nodeModulesPath, '@storybook');
  if (fs.existsSync(storybookModulesPath)) {
    fs.rmSync(storybookModulesPath, { recursive: true, force: true });
    console.log('  ✅ Removed node_modules/@storybook/');
  }

  // Remove storybook package
  const storybookPkgPath = path.join(nodeModulesPath, 'storybook');
  if (fs.existsSync(storybookPkgPath)) {
    fs.rmSync(storybookPkgPath, { recursive: true, force: true });
    console.log('  ✅ Removed node_modules/storybook/');
  }

  console.log('');
}

function removePackageLock(projectPath) {
  console.log('🔒 Removing package-lock.json...\n');

  const packageLockPath = path.join(projectPath, 'package-lock.json');

  if (fs.existsSync(packageLockPath)) {
    fs.unlinkSync(packageLockPath);
    console.log('  ✅ Removed package-lock.json\n');
  } else {
    console.log('  ℹ️  No package-lock.json found\n');
  }
}

function showSummary() {
  console.log('╔════════════════════════════════════════════╗');
  console.log('║  ✅ Storybook Uninstalled Successfully    ║');
  console.log('╚════════════════════════════════════════════╝\n');

  console.log('What was removed:');
  console.log('  • .storybook/ directory');
  console.log('  • All @storybook/* packages from package.json');
  console.log('  • Storybook scripts from package.json');
  console.log('  • Storybook packages from node_modules');
  console.log('  • package-lock.json (will be regenerated on next npm install)\n');

  console.log('Backups created in:');
  console.log('  • .storybook-backup/\n');

  console.log('To restore from backup:');
  console.log('  1. Copy files from .storybook-backup/');
  console.log('  2. Run: npm install\n');

  console.log('To clean install fresh dependencies:');
  console.log('  Run: npm install\n');
}

function uninstallStorybook(projectPath = process.cwd()) {
  console.log('╔════════════════════════════════════════════╗');
  console.log('║  Storybook Uninstall Utility              ║');
  console.log('╚════════════════════════════════════════════╝');

  // Step 1: Create backup
  createBackup(projectPath);

  // Step 2: Remove .storybook directory
  removeStorybookDirectory(projectPath);

  // Step 3: Clean package.json
  removeStorybookFromPackageJson(projectPath);

  // Step 4: Clean node_modules
  cleanNodeModules(projectPath);

  // Step 5: Remove package-lock.json
  removePackageLock(projectPath);

  // Step 6: Show summary
  showSummary();
}

// CLI execution
if (require.main === module) {
  const projectPath = process.argv[2] || process.cwd();

  console.log('\n⚠️  This will remove Storybook from your project.');
  console.log('A backup will be created in .storybook-backup/\n');

  // In non-interactive mode, just proceed
  uninstallStorybook(projectPath);
}

module.exports = { uninstallStorybook };

/**
 * Design Structure Manager Tests
 *
 * Tests the .design/ directory structure management and manifest handling.
 */

const path = require('path');
const fs = require('fs');
const os = require('os');
const {
  DesignStructure,
  createDesignStructure,
  initializeDesignStructure,
  STRUCTURE,
  DEFAULT_MANIFESTS
} = require('./design-structure');

// Create a temporary test directory
let testDir;

function setup() {
  testDir = path.join(os.tmpdir(), `design-structure-test-${Date.now()}`);
  fs.mkdirSync(testDir, { recursive: true });
}

function cleanup() {
  if (testDir && fs.existsSync(testDir)) {
    fs.rmSync(testDir, { recursive: true, force: true });
  }
}

async function runTests() {
  console.log('\n  Design Structure Manager Tests\n');
  console.log('  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n');

  let passed = 0;
  let failed = 0;

  // Test 1: Create structure instance
  console.log('  ▸ Test 1: Create structure instance');
  setup();
  try {
    const structure = new DesignStructure(testDir);
    if (structure.projectPath === testDir) {
      console.log('    ✓ Structure instance created');
      passed++;
    } else {
      throw new Error('Project path mismatch');
    }
  } catch (e) {
    console.log(`    ✗ Failed: ${e.message}`);
    failed++;
  }
  cleanup();

  // Test 2: Initialize creates directories
  console.log('\n  ▸ Test 2: Initialize creates directories');
  setup();
  try {
    const structure = new DesignStructure(testDir);
    const result = structure.initialize({ framework: 'react' });

    const designDir = path.join(testDir, '.design');
    const tokensDir = path.join(testDir, '.design', 'tokens');
    const layoutsDir = path.join(testDir, '.design', 'layouts');

    if (fs.existsSync(designDir) && fs.existsSync(tokensDir) && fs.existsSync(layoutsDir)) {
      console.log('    ✓ Base directories created');
      console.log(`      Created: ${result.directoriesCreated.length} directories`);
      passed++;
    } else {
      throw new Error('Missing directories');
    }
  } catch (e) {
    console.log(`    ✗ Failed: ${e.message}`);
    failed++;
  }
  cleanup();

  // Test 3: Initialize creates manifests
  console.log('\n  ▸ Test 3: Initialize creates manifests');
  setup();
  try {
    const structure = new DesignStructure(testDir);
    structure.initialize({ framework: 'react' });

    const configPath = path.join(testDir, '.design', 'config.json');
    const registryPath = path.join(testDir, '.design', 'componentRegistry.json');
    const layoutManifestPath = path.join(testDir, '.design', 'layoutManifest.json');

    if (fs.existsSync(configPath) && fs.existsSync(registryPath) && fs.existsSync(layoutManifestPath)) {
      const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
      if (config.project.framework === 'react') {
        console.log('    ✓ Manifests created with correct data');
        passed++;
      } else {
        throw new Error('Framework not set correctly');
      }
    } else {
      throw new Error('Missing manifest files');
    }
  } catch (e) {
    console.log(`    ✗ Failed: ${e.message}`);
    failed++;
  }
  cleanup();

  // Test 4: Initialize creates framework directories
  console.log('\n  ▸ Test 4: Initialize creates framework directories');
  setup();
  try {
    const structure = new DesignStructure(testDir);
    structure.initialize({ framework: 'vue' });

    const vueComponentsDir = path.join(testDir, '.design', 'extracted-code', 'vue', 'components');
    const vueLayoutsDir = path.join(testDir, '.design', 'extracted-code', 'vue', 'layouts');

    if (fs.existsSync(vueComponentsDir) && fs.existsSync(vueLayoutsDir)) {
      console.log('    ✓ Framework-specific directories created');
      passed++;
    } else {
      throw new Error('Missing framework directories');
    }
  } catch (e) {
    console.log(`    ✗ Failed: ${e.message}`);
    failed++;
  }
  cleanup();

  // Test 5: Get status
  console.log('\n  ▸ Test 5: Get status');
  setup();
  try {
    const structure = new DesignStructure(testDir);
    structure.initialize({ framework: 'react' });

    const status = structure.getStatus();

    if (status.initialized && status.manifests.config.exists && status.frameworks.react) {
      console.log('    ✓ Status report generated');
      console.log(`      Manifests: ${Object.keys(status.manifests).length}`);
      console.log(`      Frameworks: ${Object.keys(status.frameworks).join(', ')}`);
      passed++;
    } else {
      throw new Error('Invalid status');
    }
  } catch (e) {
    console.log(`    ✗ Failed: ${e.message}`);
    failed++;
  }
  cleanup();

  // Test 6: Register layout
  console.log('\n  ▸ Test 6: Register layout');
  setup();
  try {
    const structure = new DesignStructure(testDir);
    structure.initialize({ framework: 'react' });

    const layout = structure.registerLayout({
      name: 'LoginScreen',
      safeName: 'login-screen',
      dimensions: { width: 375, height: 812 }
    });

    if (layout.name === 'LoginScreen' && layout.stage === 1) {
      const manifestPath = path.join(testDir, '.design', 'layoutManifest.json');
      const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));

      if (manifest.layouts.length === 1 && manifest.metadata.totalLayouts === 1) {
        console.log('    ✓ Layout registered');
        console.log(`      Name: ${layout.name}, Stage: ${layout.stage}`);
        passed++;
      } else {
        throw new Error('Manifest not updated');
      }
    } else {
      throw new Error('Layout not created correctly');
    }
  } catch (e) {
    console.log(`    ✗ Failed: ${e.message}`);
    failed++;
  }
  cleanup();

  // Test 7: Update layout stage
  console.log('\n  ▸ Test 7: Update layout stage');
  setup();
  try {
    const structure = new DesignStructure(testDir);
    structure.initialize({ framework: 'react' });

    structure.registerLayout({
      name: 'LoginScreen',
      safeName: 'login-screen'
    });

    const updated = structure.updateLayoutStage('LoginScreen', 3, {
      referenceHtml: '.design/layouts/login-screen/reference.html'
    });

    if (updated.stage === 3 && updated.status === 'html-generated') {
      console.log('    ✓ Layout stage updated');
      console.log(`      Stage: ${updated.stage}, Status: ${updated.status}`);
      passed++;
    } else {
      throw new Error('Stage not updated');
    }
  } catch (e) {
    console.log(`    ✗ Failed: ${e.message}`);
    failed++;
  }
  cleanup();

  // Test 8: Register component
  console.log('\n  ▸ Test 8: Register component');
  setup();
  try {
    const structure = new DesignStructure(testDir);
    structure.initialize({ framework: 'react' });

    const component = structure.registerComponent({
      name: 'PrimaryButton',
      source: 'figma',
      figmaNodeId: '123:456',
      transformedTo: ['react'],
      outputPaths: {
        react: '.design/extracted-code/react/components/PrimaryButton.tsx'
      }
    });

    if (component.name === 'PrimaryButton' && component.source === 'figma') {
      const registryPath = path.join(testDir, '.design', 'componentRegistry.json');
      const registry = JSON.parse(fs.readFileSync(registryPath, 'utf8'));

      if (registry.components.length === 1 && registry.metadata.sources.figma === 1) {
        console.log('    ✓ Component registered');
        console.log(`      Name: ${component.name}, Source: ${component.source}`);
        passed++;
      } else {
        throw new Error('Registry not updated');
      }
    } else {
      throw new Error('Component not created correctly');
    }
  } catch (e) {
    console.log(`    ✗ Failed: ${e.message}`);
    failed++;
  }
  cleanup();

  // Test 9: Get layout by name
  console.log('\n  ▸ Test 9: Get layout by name');
  setup();
  try {
    const structure = new DesignStructure(testDir);
    structure.initialize({ framework: 'react' });

    structure.registerLayout({ name: 'HomeScreen' });
    structure.registerLayout({ name: 'ProfileScreen' });

    const layout = structure.getLayout('ProfileScreen');

    if (layout && layout.name === 'ProfileScreen') {
      console.log('    ✓ Layout retrieved');
      passed++;
    } else {
      throw new Error('Layout not found');
    }
  } catch (e) {
    console.log(`    ✗ Failed: ${e.message}`);
    failed++;
  }
  cleanup();

  // Test 10: Get component by name
  console.log('\n  ▸ Test 10: Get component by name');
  setup();
  try {
    const structure = new DesignStructure(testDir);
    structure.initialize({ framework: 'react' });

    structure.registerComponent({ name: 'Button', source: 'shadcn' });
    structure.registerComponent({ name: 'Card', source: 'figma' });

    const component = structure.getComponent('Card');

    if (component && component.source === 'figma') {
      console.log('    ✓ Component retrieved');
      passed++;
    } else {
      throw new Error('Component not found');
    }
  } catch (e) {
    console.log(`    ✗ Failed: ${e.message}`);
    failed++;
  }
  cleanup();

  // Test 11: Factory function
  console.log('\n  ▸ Test 11: Factory function');
  setup();
  try {
    const structure = createDesignStructure(testDir);
    if (structure instanceof DesignStructure) {
      console.log('    ✓ Factory function works');
      passed++;
    } else {
      throw new Error('Wrong instance type');
    }
  } catch (e) {
    console.log(`    ✗ Failed: ${e.message}`);
    failed++;
  }
  cleanup();

  // Test 12: Quick initialization function
  console.log('\n  ▸ Test 12: Quick initialization function');
  setup();
  try {
    const result = initializeDesignStructure(testDir, { framework: 'svelte' });

    if (result.success) {
      const configPath = path.join(testDir, '.design', 'config.json');
      const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));

      if (config.project.framework === 'svelte') {
        console.log('    ✓ Quick initialization works');
        passed++;
      } else {
        throw new Error('Framework not set');
      }
    } else {
      throw new Error('Initialization failed');
    }
  } catch (e) {
    console.log(`    ✗ Failed: ${e.message}`);
    failed++;
  }
  cleanup();

  // Test 13: Barrel exports created
  console.log('\n  ▸ Test 13: Barrel exports created');
  setup();
  try {
    const structure = new DesignStructure(testDir);
    structure.initialize({ framework: 'react' });

    const componentsIndex = path.join(testDir, '.design', 'extracted-code', 'react', 'components', 'index.ts');
    const layoutsIndex = path.join(testDir, '.design', 'extracted-code', 'react', 'layouts', 'index.ts');

    if (fs.existsSync(componentsIndex) && fs.existsSync(layoutsIndex)) {
      console.log('    ✓ Barrel export files created');
      passed++;
    } else {
      throw new Error('Missing barrel exports');
    }
  } catch (e) {
    console.log(`    ✗ Failed: ${e.message}`);
    failed++;
  }
  cleanup();

  // Test 14: Pipeline stage metadata tracking
  console.log('\n  ▸ Test 14: Pipeline stage metadata tracking');
  setup();
  try {
    const structure = new DesignStructure(testDir);
    structure.initialize({ framework: 'react' });

    // Register layouts at different stages
    structure.registerLayout({ name: 'Layout1', status: 'extracted', stage: 1 });
    structure.registerLayout({ name: 'Layout2', status: 'screenshot', stage: 2 });
    structure.registerLayout({ name: 'Layout3', status: 'validated', stage: 4 });

    const manifestPath = path.join(testDir, '.design', 'layoutManifest.json');
    const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));

    if (manifest.metadata.byStage.extracted === 1 &&
        manifest.metadata.byStage.screenshot === 1 &&
        manifest.metadata.byStage.validated === 1) {
      console.log('    ✓ Pipeline stage metadata tracked');
      console.log(`      byStage: ${JSON.stringify(manifest.metadata.byStage)}`);
      passed++;
    } else {
      throw new Error('Stage metadata incorrect');
    }
  } catch (e) {
    console.log(`    ✗ Failed: ${e.message}`);
    failed++;
  }
  cleanup();

  // Summary
  console.log('\n  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
  console.log(`\n  Results: ${passed} passed, ${failed} failed\n`);

  return failed === 0;
}

// Run tests
runTests()
  .then(success => {
    process.exit(success ? 0 : 1);
  })
  .catch(err => {
    console.error('Test error:', err);
    process.exit(1);
  });

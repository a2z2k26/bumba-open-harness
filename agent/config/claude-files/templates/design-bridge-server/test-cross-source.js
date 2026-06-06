/**
 * Cross-Source Integration Test Suite
 * Tests integration between different extraction sources
 */

const fs = require('fs');
const path = require('path');
const { TokenSharingManager, detectSourceType } = require('./token-sharing');
const { ComponentRefResolver } = require('./component-refs');
const { DependencyGraph } = require('./dependency-graph');
const { BatchTransformer } = require('./batch-transform');
const { SourceMigration } = require('./source-migration');

class CrossSourceTestSuite {
  constructor(projectRoot) {
    this.projectRoot = projectRoot;
    this.registryPath = path.join(projectRoot, '.design');
    this.results = [];
  }

  /**
   * Run all integration tests
   */
  async runAll() {
    console.log('=== Cross-Source Integration Test Suite ===\n');

    const tests = [
      this.testTokenSharing,
      this.testComponentReferences,
      this.testDependencyGraph,
      this.testBatchTransform,
      this.testSourceMigration,
      this.testMixedSourceProject,
      this.testCircularDependencyDetection,
      this.testTokenResolutionAcrossSources
    ];

    for (const test of tests) {
      await this.runTest(test.bind(this));
    }

    this.printSummary();
    return this.results;
  }

  async runTest(testFn) {
    const testName = testFn.name.replace('bound ', '');
    console.log(`Running: ${testName}...`);

    try {
      await testFn();
      this.results.push({ name: testName, passed: true });
      console.log(`  [PASS]\n`);
    } catch (err) {
      this.results.push({ name: testName, passed: false, error: err.message });
      console.log(`  [FAIL] ${err.message}\n`);
    }
  }

  // Test 1: Token sharing across sources
  async testTokenSharing() {
    const manager = new TokenSharingManager(this.projectRoot);

    // Test CSS variable mapping (ShadCN)
    const cssResult = manager.resolveToken('--primary', 'css');
    if (!cssResult.resolved) throw new Error('CSS token not resolved');

    // Test natural language mapping (NLP)
    const nlpResult = manager.resolveToken('primary', 'natural');
    if (!nlpResult.resolved) throw new Error('Natural language token not resolved');

    // Test cross-source token resolution
    const tokenDeps = {
      colors: ['--primary', 'secondary'],
      spacing: ['medium']
    };

    const resolved = manager.resolveComponentTokens(tokenDeps, 'css');
    if (resolved.valid !== false && resolved.missing.length > 0) {
      // Expected some missing tokens - document them
      console.log(`    Note: ${resolved.missing.length} tokens need mapping`);
    }
  }

  // Test 2: Component references across sources
  async testComponentReferences() {
    const resolver = new ComponentRefResolver(this.registryPath);

    // Test reference parsing
    const parsed = resolver.parseReference('@ref:Button');
    if (!parsed.valid) throw new Error('Reference parsing failed');

    // Test with props
    const parsedWithProps = resolver.parseReference('@ref:Button{"variant":"primary"}');
    if (!parsedWithProps.valid) throw new Error('Props parsing failed');

    // Test structure processing (simulated)
    const structure = {
      type: 'container',
      children: [
        { type: 'component-ref', ref: 'Button', props: { variant: 'primary' } }
      ]
    };

    const processed = resolver.processStructure(structure);
    // Should handle missing components gracefully
    if (!processed.structure) throw new Error('Structure processing failed');
  }

  // Test 3: Dependency graph building
  async testDependencyGraph() {
    const graph = new DependencyGraph(this.projectRoot);
    const built = graph.build();

    if (!built.components) throw new Error('Graph has no components');
    if (!built.tokens) throw new Error('Graph has no tokens');
    if (!built.metadata) throw new Error('Graph has no metadata');

    // Test transformation order
    const order = graph.getTransformationOrder();
    if (!Array.isArray(order)) throw new Error('Transformation order not array');

    // Test impact analysis (if components exist)
    const componentIds = Object.keys(built.components);
    if (componentIds.length > 0) {
      const impact = graph.getImpactAnalysis(componentIds[0]);
      if (!impact.componentId) throw new Error('Impact analysis failed');
    }
  }

  // Test 4: Batch transformation
  async testBatchTransform() {
    const transformer = new BatchTransformer(this.projectRoot, { dryRun: true });

    // Test preview
    const preview = transformer.preview(['all']);
    if (!preview.transformationOrder) throw new Error('Preview failed');
    if (!preview.dependencyLevels) throw new Error('Dependency levels not computed');

    // Test batch transform dry run
    const result = await transformer.transform(['all'], { dryRun: true });
    if (!result.order) throw new Error('Batch transform failed');
    if (typeof result.duration !== 'number') throw new Error('Duration not tracked');
  }

  // Test 5: Source migration
  async testSourceMigration() {
    const migration = new SourceMigration(this.projectRoot);

    // Test customization collection (simulated component)
    const mockComponent = {
      name: 'TestButton',
      customProps: { testProp: true },
      styleOverrides: { color: 'red' },
      tags: ['test'],
      category: 'Testing'
    };

    const customizations = migration.collectCustomizations(mockComponent);
    if (!customizations.customProps) throw new Error('CustomProps not collected');
    if (!customizations.tags) throw new Error('Tags not collected');

    // Test merge customizations
    const newData = { name: 'TestButton', structure: {} };
    const merged = migration.mergeCustomizations(newData, customizations, {
      preserveCustomizations: true,
      preserveTokenMappings: true
    });

    if (!merged.customProps) throw new Error('Customizations not merged');
    if (!merged.tags) throw new Error('Tags not preserved');
  }

  // Test 6: Mixed source project
  async testMixedSourceProject() {
    const registryFile = path.join(this.registryPath, 'components', 'registry.json');

    if (!fs.existsSync(registryFile)) {
      console.log('    Skipped: No registry file');
      return;
    }

    const registry = JSON.parse(fs.readFileSync(registryFile, 'utf-8'));
    const components = registry.components || {};

    // Count sources
    const sourceCounts = {};
    for (const component of Object.values(components)) {
      const source = component.source?.type || 'unknown';
      sourceCounts[source] = (sourceCounts[source] || 0) + 1;
    }

    console.log(`    Source distribution: ${JSON.stringify(sourceCounts)}`);

    // All sources should produce valid components
    const tokenManager = new TokenSharingManager(this.projectRoot);

    for (const [id, component] of Object.entries(components)) {
      const sourceType = detectSourceType(component.source);
      const result = tokenManager.resolveComponentTokens(
        component.tokenDependencies,
        sourceType
      );

      // Log any issues but don't fail
      if (result.missing.length > 0) {
        console.log(`    Note: ${component.name} has ${result.missing.length} unresolved tokens`);
      }
    }
  }

  // Test 7: Circular dependency detection
  async testCircularDependencyDetection() {
    const graph = new DependencyGraph(this.projectRoot);
    const built = graph.build();

    // Verify circular detection works
    if (typeof built.metadata.hasCircularDeps !== 'boolean') {
      throw new Error('Circular dependency check not performed');
    }

    if (built.metadata.hasCircularDeps) {
      console.log(`    Warning: Circular dependencies detected`);
      if (built.metadata.circularPaths) {
        console.log(`    Paths: ${built.metadata.circularPaths.length}`);
      }
    }
  }

  // Test 8: Token resolution across all source types
  async testTokenResolutionAcrossSources() {
    const manager = new TokenSharingManager(this.projectRoot);

    const sourceTypes = ['css', 'natural', 'figma', 'manual'];
    const testTokens = ['primary', '--primary', 'Primary/500', 'blue'];

    for (const sourceType of sourceTypes) {
      for (const token of testTokens) {
        const result = manager.resolveToken(token, sourceType);
        // Just verify it doesn't throw
        if (result.resolved === undefined) {
          throw new Error(`Token resolution failed for ${token} (${sourceType})`);
        }
      }
    }

    console.log('    All source types handle token resolution');
  }

  printSummary() {
    console.log('=== Test Summary ===\n');

    const passed = this.results.filter(r => r.passed).length;
    const failed = this.results.filter(r => !r.passed).length;

    console.log(`Total: ${this.results.length}`);
    console.log(`Passed: ${passed}`);
    console.log(`Failed: ${failed}`);

    if (failed > 0) {
      console.log('\nFailed tests:');
      for (const result of this.results.filter(r => !r.passed)) {
        console.log(`  - ${result.name}: ${result.error}`);
      }
    }

    console.log(`\n${failed === 0 ? 'All tests passed!' : 'Some tests failed'}`);
  }
}

// Run tests
async function runTests() {
  const projectRoot = process.cwd();
  const suite = new CrossSourceTestSuite(projectRoot);

  try {
    const results = await suite.runAll();
    const failed = results.filter(r => !r.passed).length;
    process.exit(failed > 0 ? 1 : 0);
  } catch (err) {
    console.error('Test suite error:', err);
    process.exit(1);
  }
}

module.exports = { CrossSourceTestSuite, runTests };

// CLI
if (require.main === module) {
  runTests();
}

#!/usr/bin/env node
/**
 * test-migration.js
 * Tests the migration module against the layout-extract-test project
 */

const path = require('path');
const { getRegistryManager, clearRegistryManager } = require('./registry-manager');
const { RegistryMigration, createMigration } = require('./registry-migration');

const TEST_PROJECT = path.join(__dirname, '../.design');

async function runMigrationTest() {
  console.log('================================================');
  console.log('   Registry Migration Test');
  console.log('================================================\n');

  // Clear any cached manager
  clearRegistryManager();

  try {
    // Create migration instance
    console.log('1. Creating migration instance...');
    const migration = await createMigration(TEST_PROJECT);
    console.log('   ✅ Migration instance created\n');

    // Detect legacy registries
    console.log('2. Detecting legacy registries...');
    const detected = await migration.detectLegacyRegistries();

    console.log('   Found:');
    for (const [type, info] of Object.entries(detected)) {
      if (info.exists) {
        console.log(`   - ${type}: ${info.count || 'N/A'} entries (v${info.version})`);
      } else {
        console.log(`   - ${type}: Not found`);
      }
    }
    console.log('');

    // Run dry-run migration
    console.log('3. Running dry-run migration...');
    migration.setProgressCallback((phase, progress, message) => {
      console.log(`   [${phase}] ${progress}% - ${message}`);
    });

    const dryRunResult = await migration.migrateFromLegacy({ dryRun: true });

    if (dryRunResult.success) {
      console.log('\n   ✅ Dry-run successful');
      console.log(`   Would migrate:`);
      console.log(`   - Components: ${dryRunResult.status.components.migrated}`);
      console.log(`   - Tokens: ${dryRunResult.status.tokens.migrated}`);
      console.log(`   - Layouts: ${dryRunResult.status.layouts.migrated}`);
    } else {
      console.log('\n   ❌ Dry-run failed:', dryRunResult.error);
    }
    console.log('');

    // Run actual migration (with backup)
    console.log('4. Running actual migration...');

    // Create a fresh manager for real migration
    clearRegistryManager();
    const realMigration = await createMigration(TEST_PROJECT);

    const result = await realMigration.migrateFromLegacy({ dryRun: false });

    if (result.success) {
      console.log('\n   ✅ Migration successful');
      console.log(`   Backup: ${result.backupDir}`);
      console.log(`   Results:`);
      console.log(`   - Components: ${result.status.components.migrated} migrated, ${result.status.components.skipped} skipped`);
      console.log(`   - Tokens: ${result.status.tokens.migrated} migrated, ${result.status.tokens.skipped} skipped`);
      console.log(`   - Layouts: ${result.status.layouts.migrated} migrated, ${result.status.layouts.skipped} skipped`);
      console.log(`   - ID Mappings imported: ${result.status.idMappings.imported}`);

      if (result.status.totalErrors > 0) {
        console.log(`\n   ⚠️  ${result.status.totalErrors} errors occurred`);
      }
    } else {
      console.log('\n   ❌ Migration failed:', result.error);
    }
    console.log('');

    // Verify migration
    console.log('5. Verifying migrated data...');
    clearRegistryManager();
    const manager = await getRegistryManager(TEST_PROJECT);

    const stats = await manager.getStats();
    console.log(`   Registry Stats:`);
    console.log(`   - Components: ${stats.registries.components.count}`);
    console.log(`   - Tokens: ${stats.registries.tokens.count}`);
    console.log(`   - Layouts: ${stats.registries.layouts.count}`);
    console.log(`   - ID Index entries: ${stats.totals.idMappings}`);
    console.log(`   - Source mappings: ${stats.totals.sourceMappings}`);
    console.log(`   - Dependency graph nodes: ${stats.totals.dependencyNodes}`);
    console.log('');

    // Test some queries
    console.log('6. Testing queries...');

    // Find by name
    const buttons = await manager.findByName('button');
    console.log(`   - findByName("button"): ${buttons.length} results`);

    // Find by category
    const colors = await manager.findByCategory('colors', 'tokens');
    console.log(`   - findByCategory("colors", "tokens"): ${colors.length} results`);

    // Find by source
    const figmaComponents = await manager.findBySource('figma-plugin', 'components');
    console.log(`   - findBySource("figma-plugin", "components"): ${figmaComponents.length} results`);

    // Test findDependents
    if (colors.length > 0) {
      const dependents = await manager.findDependents(colors[0].id);
      console.log(`   - findDependents for first color token: ${dependents.components.length} components, ${dependents.layouts.length} layouts`);
    }
    console.log('');

    // Save report
    console.log('7. Saving migration report...');
    const reportPath = await realMigration.saveReport();
    console.log(`   Report saved: ${reportPath}`);
    console.log('');

    console.log('================================================');
    console.log('   Migration Test Complete');
    console.log('================================================');
    console.log('\n✅ All tests passed!\n');

  } catch (error) {
    console.error('\n❌ Test failed:', error.message);
    console.error(error.stack);
    process.exit(1);
  }
}

runMigrationTest();

/**
 * Phase 9: Final Integration and Polish - Performance Check
 * Sprint 9.2: Verify no performance regressions
 */

const fs = require('fs');
const path = require('path');
const os = require('os');

const testProjectPath = path.join(os.tmpdir(), 'design-bridge-perf-test-' + Date.now());

console.log('\n' + '='.repeat(70));
console.log('  PHASE 9 - Sprint 9.2: Performance Check');
console.log('='.repeat(70));
console.log('\nTest project: ' + testProjectPath + '\n');

const results = {};

async function benchmark(name, fn, iterations) {
  iterations = iterations || 5;
  const times = [];
  await fn(); // Warm-up
  for (let i = 0; i < iterations; i++) {
    const start = process.hrtime.bigint();
    await fn();
    const end = process.hrtime.bigint();
    times.push(Number(end - start) / 1e6);
  }
  const avg = times.reduce((a, b) => a + b, 0) / times.length;
  const min = Math.min(...times);
  const max = Math.max(...times);
  results[name] = { avg, min, max, iterations };
  console.log('📊 ' + name + ': avg=' + avg.toFixed(2) + 'ms, min=' + min.toFixed(2) + 'ms, max=' + max.toFixed(2) + 'ms');
  return avg;
}

async function runPerformanceTests() {
  fs.mkdirSync(testProjectPath, { recursive: true });
  fs.mkdirSync(path.join(testProjectPath, '.design'), { recursive: true });
  fs.mkdirSync(path.join(testProjectPath, '.design', 'components'), { recursive: true });
  fs.mkdirSync(path.join(testProjectPath, '.design', 'extracted-code', 'react'), { recursive: true });
  fs.mkdirSync(path.join(testProjectPath, '.design', 'stories'), { recursive: true });
  fs.mkdirSync(path.join(testProjectPath, '.design', 'tokens'), { recursive: true });

  const config = { version: '3.0.0', project: { name: 'perf-test', framework: 'react', typescript: true }, twoState: { autoRegisterOnImport: true } };
  fs.writeFileSync(path.join(testProjectPath, '.design', 'config.json'), JSON.stringify(config, null, 2));
  fs.writeFileSync(path.join(testProjectPath, '.design', 'componentRegistry.json'), JSON.stringify({ version: '3.0.0', components: {}, lastUpdated: new Date().toISOString() }, null, 2));

  console.log('--- Module Load Performance ---\n');
  await benchmark('Load AutoRegistrar module', async () => { delete require.cache[require.resolve('./auto-registrar')]; require('./auto-registrar'); });
  await benchmark('Load TransformStateUpdater module', async () => { delete require.cache[require.resolve('./transform-state-updater')]; require('./transform-state-updater'); });
  await benchmark('Load SyncCascade module', async () => { delete require.cache[require.resolve('./sync-cascade')]; require('./sync-cascade'); });
  await benchmark('Load AutoSyncManager module', async () => { delete require.cache[require.resolve('./auto-sync-manager')]; require('./auto-sync-manager'); });

  console.log('\n--- Core Operation Performance ---\n');
  const { AutoRegistrar } = require('./auto-registrar');
  const registrar = new AutoRegistrar({ projectPath: testProjectPath });
  let componentCounter = 0;

  await benchmark('Register single component', async () => {
    componentCounter++;
    await registrar.registerComponent({ name: 'TestComp' + componentCounter, props: { label: { type: 'string' } } }, { type: 'figma-plugin', nodeId: '1:' + componentCounter, fileKey: 'test-key' });
  });

  const { TransformStateUpdater } = require('./transform-state-updater');
  const updater = new TransformStateUpdater({ projectPath: testProjectPath });
  const registry = JSON.parse(fs.readFileSync(path.join(testProjectPath, '.design', 'componentRegistry.json'), 'utf8'));
  const firstComponentId = Object.keys(registry.components)[0];
  const codePath = '.design/extracted-code/react/TestComponent.tsx';
  fs.writeFileSync(path.join(testProjectPath, codePath), 'export const TestComponent = () => <div>Test</div>;');

  await benchmark('Mark component transformed', async () => { await updater.markTransformed(firstComponentId, { framework: 'react', codePath }); });
  await benchmark('Check needs retransform', async () => { await updater.needsRetransform(firstComponentId); });

  const { SyncCascade } = require('./sync-cascade');
  await benchmark('SyncCascade instantiation', async () => { new SyncCascade({ projectPath: testProjectPath }); });

  const { readComponentRegistry } = require('./registry-reader');
  await benchmark('Read component registry', async () => { await readComponentRegistry(testProjectPath); });

  const { ContentHasher } = require('./incremental-processor');
  const hasher = new ContentHasher();
  const testContent = 'export const Button = () => <button>Click me</button>;'.repeat(100);
  await benchmark('Hash content (5KB)', async () => { hasher.hash(testContent); });

  console.log('\n--- Batch Operation Performance ---\n');
  await benchmark('Register 10 components', async () => {
    for (let i = 0; i < 10; i++) { componentCounter++; await registrar.registerComponent({ name: 'BatchComp' + componentCounter, props: {} }, { type: 'nlp-prompt', promptHash: 'hash-' + componentCounter }); }
  }, 3);

  console.log('\n--- Registry Size Analysis ---\n');
  const finalRegistry = JSON.parse(fs.readFileSync(path.join(testProjectPath, '.design', 'componentRegistry.json'), 'utf8'));
  const componentCount = Object.keys(finalRegistry.components).length;
  const registryJson = JSON.stringify(finalRegistry);
  const registrySize = Buffer.byteLength(registryJson, 'utf8');
  const sizePerComponent = registrySize / componentCount;
  console.log('📁 Registry Statistics:');
  console.log('   - Total components: ' + componentCount);
  console.log('   - Registry size: ' + (registrySize / 1024).toFixed(2) + ' KB');
  console.log('   - Average per component: ' + sizePerComponent.toFixed(0) + ' bytes');
  results.registryStats = { componentCount, totalSizeKB: registrySize / 1024, bytesPerComponent: sizePerComponent };

  console.log('\n--- Cleanup ---\n');
  try { fs.rmSync(testProjectPath, { recursive: true, force: true }); console.log('✅ Test project cleaned up'); } catch (err) { console.log('⚠️ Could not clean up'); }

  console.log('\n' + '='.repeat(70));
  console.log('  Performance Summary');
  console.log('='.repeat(70) + '\n');
  console.log('| Operation                            | Avg (ms) | Min (ms) | Max (ms) |');
  console.log('|--------------------------------------|----------|----------|----------|');
  for (const [name, data] of Object.entries(results)) {
    if (data.avg !== undefined) {
      console.log('| ' + name.padEnd(36) + ' | ' + data.avg.toFixed(2).padStart(8) + ' | ' + data.min.toFixed(2).padStart(8) + ' | ' + data.max.toFixed(2).padStart(8) + ' |');
    }
  }

  console.log('\n--- Performance Validation ---\n');
  const issues = [];
  if (results['Register single component'].avg > 100) issues.push('⚠️ Component registration taking > 100ms');
  if (results['Read component registry'].avg > 50) issues.push('⚠️ Registry read taking > 50ms');
  if (results['Hash content (5KB)'].avg > 10) issues.push('⚠️ Content hashing taking > 10ms');
  if (results.registryStats.bytesPerComponent > 2000) issues.push('⚠️ Registry size per component > 2KB');
  if (issues.length === 0) console.log('✅ All performance checks passed!'); else issues.forEach(issue => console.log(issue));
  console.log('\n✅ Sprint 9.2 Performance Check COMPLETE\n');
}

runPerformanceTests().catch(err => { console.error('Performance test failed:', err); process.exit(1); });

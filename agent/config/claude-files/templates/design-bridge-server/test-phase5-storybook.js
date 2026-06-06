/**
 * test-phase5-storybook.js
 * Phase 5: Advanced Storybook Features - Test Suite
 *
 * Tests:
 * - Sprint 5.1: Story Variants (states, responsive, themes)
 * - Sprint 5.2: Interactive Playgrounds
 * - Sprint 5.3: MDX Documentation
 * - Sprint 5.4: Composition Patterns
 */

const { StoryVariants, VIEWPORT_SIZES, STATE_PATTERNS, THEME_CONFIGS } = require('./story-variants');
const { InteractivePlayground, PLAYGROUND_PRESETS, CODE_TEMPLATES } = require('./interactive-playground');
const { MDXGenerator, MDX_SECTIONS, MDX_TEMPLATES } = require('./mdx-generator');
const { CompositionPatterns, COMPOSITION_PATTERNS, LAYOUT_GENERATORS } = require('./composition-patterns');
const { StoryGenerator } = require('./story-generator');

// Test component fixture
const testComponent = {
  name: 'Button',
  description: 'A customizable button component',
  props: {
    label: { type: 'string', default: 'Click me', required: true, description: 'Button label text' },
    variant: { type: 'string', options: ['primary', 'secondary', 'outline'], default: 'primary' },
    size: { type: 'string', options: ['sm', 'md', 'lg'], default: 'md' },
    disabled: { type: 'boolean', default: false },
    onClick: { type: 'function', description: 'Click handler' }
  },
  features: ['Customizable variants', 'Multiple sizes', 'Loading state support']
};

let passed = 0;
let failed = 0;

function test(name, condition) {
  if (condition) {
    console.log(`  ✅ ${name}`);
    passed++;
  } else {
    console.log(`  ❌ ${name}`);
    failed++;
  }
}

function testSprint51() {
  console.log('\n=== Sprint 5.1: Advanced Story Variants ===\n');

  // Test StoryVariants class instantiation
  const variants = new StoryVariants();
  test('StoryVariants instantiates', variants instanceof StoryVariants);

  // Test VIEWPORT_SIZES exports
  test('VIEWPORT_SIZES has mobile', VIEWPORT_SIZES.mobile?.width === 375);
  test('VIEWPORT_SIZES has tablet', VIEWPORT_SIZES.tablet?.width === 768);
  test('VIEWPORT_SIZES has desktop', VIEWPORT_SIZES.desktop?.width === 1280);

  // Test STATE_PATTERNS exports
  test('STATE_PATTERNS has loading', STATE_PATTERNS.loading?.isLoading === true);
  test('STATE_PATTERNS has error', STATE_PATTERNS.error?.error !== null);
  test('STATE_PATTERNS has disabled', STATE_PATTERNS.disabled?.disabled === true);

  // Test THEME_CONFIGS exports
  test('THEME_CONFIGS has light', THEME_CONFIGS.light?.parameters?.theme === 'light');
  test('THEME_CONFIGS has dark', THEME_CONFIGS.dark?.parameters?.theme === 'dark');

  // Test generateStateVariants
  const stateVariants = variants.generateStateVariants(testComponent, ['default', 'loading', 'disabled']);
  test('generateStateVariants returns object', typeof stateVariants === 'object');
  test('generateStateVariants creates Loading variant', stateVariants.Loading !== undefined);
  test('generateStateVariants creates Disabled variant', stateVariants.Disabled !== undefined);

  // Test generateResponsiveVariants
  const responsiveVariants = variants.generateResponsiveVariants(testComponent, ['mobile', 'desktop']);
  test('generateResponsiveVariants returns object', typeof responsiveVariants === 'object');
  test('generateResponsiveVariants creates Mobile variant', responsiveVariants.Mobile !== undefined);
  test('generateResponsiveVariants creates Desktop variant', responsiveVariants.Desktop !== undefined);

  // Test generateThemeVariants
  const themeVariants = variants.generateThemeVariants(testComponent, ['light', 'dark']);
  test('generateThemeVariants returns object', typeof themeVariants === 'object');
  test('generateThemeVariants creates LightTheme variant', themeVariants.LightTheme !== undefined);
  test('generateThemeVariants creates DarkTheme variant', themeVariants.DarkTheme !== undefined);

  // Test generateAllVariants
  const allVariants = variants.generateAllVariants(testComponent);
  test('generateAllVariants returns Default', allVariants.Default !== undefined);
  test('generateAllVariants includes state variants', allVariants.Loading !== undefined);
  test('generateAllVariants includes responsive variants', allVariants.Mobile !== undefined);
  test('generateAllVariants includes theme variants', allVariants.LightTheme !== undefined);

  // Test generateStoryCode
  const storyCode = variants.generateStoryCode(testComponent, allVariants, 'react');
  test('generateStoryCode returns string', typeof storyCode === 'string');
  test('generateStoryCode includes imports', storyCode.includes("import type { Meta, StoryObj }"));
  test('generateStoryCode includes component name', storyCode.includes('Button'));

  // Test stats tracking
  const stats = variants.getStats();
  test('getStats returns variantsGenerated', stats.variantsGenerated > 0);
}

function testSprint52() {
  console.log('\n=== Sprint 5.2: Interactive Playgrounds ===\n');

  // Test InteractivePlayground class instantiation
  const playground = new InteractivePlayground();
  test('InteractivePlayground instantiates', playground instanceof InteractivePlayground);

  // Test PLAYGROUND_PRESETS exports
  test('PLAYGROUND_PRESETS has minimal', PLAYGROUND_PRESETS.minimal?.showCode === false);
  test('PLAYGROUND_PRESETS has full', PLAYGROUND_PRESETS.full?.showCode === true);
  test('PLAYGROUND_PRESETS has developer', PLAYGROUND_PRESETS.developer?.showSourcePanel === true);

  // Test CODE_TEMPLATES exports
  test('CODE_TEMPLATES has react', typeof CODE_TEMPLATES.react === 'function');
  test('CODE_TEMPLATES has vue', typeof CODE_TEMPLATES.vue === 'function');
  test('CODE_TEMPLATES has angular', typeof CODE_TEMPLATES.angular === 'function');
  test('CODE_TEMPLATES has svelte', typeof CODE_TEMPLATES.svelte === 'function');

  // Test generatePlayground
  const playgroundConfig = playground.generatePlayground(testComponent);
  test('generatePlayground returns object', typeof playgroundConfig === 'object');
  test('generatePlayground has component name', playgroundConfig.component === 'Button');
  test('generatePlayground has framework', playgroundConfig.framework === 'react');
  test('generatePlayground has props', typeof playgroundConfig.props === 'object');
  test('generatePlayground has examples', Array.isArray(playgroundConfig.examples));
  test('generatePlayground has codeSnippets', typeof playgroundConfig.codeSnippets === 'object');

  // Test generatePropControls
  const propControls = playground.generatePropControls(testComponent.props);
  test('generatePropControls returns object', typeof propControls === 'object');
  test('generatePropControls has label control', propControls.label?.type === 'text');
  test('generatePropControls has variant control', propControls.variant?.type === 'select');
  test('generatePropControls has disabled control', propControls.disabled?.type === 'boolean');

  // Test generateDefaultExamples
  const examples = playground.generateDefaultExamples(testComponent);
  test('generateDefaultExamples returns array', Array.isArray(examples));
  test('generateDefaultExamples has Default example', examples.find(e => e.name === 'Default') !== undefined);

  // Test generatePlaygroundStory
  const playgroundStory = playground.generatePlaygroundStory(testComponent, 'react');
  test('generatePlaygroundStory returns string', typeof playgroundStory === 'string');
  test('generatePlaygroundStory includes Playground story', playgroundStory.includes('Playground'));

  // Test preset management
  playground.addPreset('custom', { showCode: true, editable: true });
  const presets = playground.getPresets();
  test('addPreset adds custom preset', presets.custom !== undefined);
}

function testSprint53() {
  console.log('\n=== Sprint 5.3: MDX Documentation ===\n');

  // Test MDXGenerator class instantiation
  const mdxGen = new MDXGenerator();
  test('MDXGenerator instantiates', mdxGen instanceof MDXGenerator);

  // Test MDX_SECTIONS exports
  test('MDX_SECTIONS has overview', MDX_SECTIONS.overview === true);
  test('MDX_SECTIONS has installation', MDX_SECTIONS.installation === true);
  test('MDX_SECTIONS has props', MDX_SECTIONS.props === true);

  // Test MDX_TEMPLATES exports
  test('MDX_TEMPLATES has header', typeof MDX_TEMPLATES.header === 'function');
  test('MDX_TEMPLATES has canvas', typeof MDX_TEMPLATES.canvas === 'function');
  test('MDX_TEMPLATES has argsTable', typeof MDX_TEMPLATES.argsTable === 'function');
  test('MDX_TEMPLATES has codeBlock', typeof MDX_TEMPLATES.codeBlock === 'function');
  test('MDX_TEMPLATES has table', typeof MDX_TEMPLATES.table === 'function');

  // Test generateMDX
  const mdxContent = mdxGen.generateMDX(testComponent);
  test('generateMDX returns string', typeof mdxContent === 'string');
  test('generateMDX includes imports', mdxContent.includes('import { Meta'));
  test('generateMDX includes component name', mdxContent.includes('# Button'));
  test('generateMDX includes props section', mdxContent.includes('## Props'));

  // Test generateOverview
  const overview = mdxGen.generateOverview(testComponent);
  test('generateOverview includes description', overview.includes(testComponent.description));

  // Test generateInstallation
  const installation = mdxGen.generateInstallation(testComponent);
  test('generateInstallation includes import', installation.includes("import { Button }"));

  // Test generatePropsSection
  const propsSection = mdxGen.generatePropsSection(testComponent);
  test('generatePropsSection includes ArgsTable', propsSection.includes('ArgsTable'));

  // Test generateDocsPage
  const docsPage = mdxGen.generateDocsPage(testComponent);
  test('generateDocsPage returns object', typeof docsPage === 'object');
  test('generateDocsPage has filename', docsPage.filename === 'Button.mdx');
  test('generateDocsPage has content', typeof docsPage.content === 'string');

  // Test section management
  mdxGen.setSections({ changelog: true });
  const sections = mdxGen.getSections();
  test('setSections enables changelog', sections.changelog === true);

  // Test stats
  const stats = mdxGen.getStats();
  test('getStats returns docsGenerated', stats.docsGenerated > 0);
}

function testSprint54() {
  console.log('\n=== Sprint 5.4: Composition Patterns ===\n');

  // Test CompositionPatterns class instantiation
  const composer = new CompositionPatterns();
  test('CompositionPatterns instantiates', composer instanceof CompositionPatterns);

  // Test COMPOSITION_PATTERNS exports
  test('COMPOSITION_PATTERNS has cardWithActions', COMPOSITION_PATTERNS.cardWithActions !== undefined);
  test('COMPOSITION_PATTERNS has formWithValidation', COMPOSITION_PATTERNS.formWithValidation !== undefined);
  test('COMPOSITION_PATTERNS has tabs', COMPOSITION_PATTERNS.tabs !== undefined);
  test('COMPOSITION_PATTERNS has accordion', COMPOSITION_PATTERNS.accordion !== undefined);
  test('COMPOSITION_PATTERNS has dropdown', COMPOSITION_PATTERNS.dropdown !== undefined);

  // Test LAYOUT_GENERATORS exports
  test('LAYOUT_GENERATORS has container', typeof LAYOUT_GENERATORS.container === 'function');
  test('LAYOUT_GENERATORS has form', typeof LAYOUT_GENERATORS.form === 'function');
  test('LAYOUT_GENERATORS has list', typeof LAYOUT_GENERATORS.list === 'function');
  test('LAYOUT_GENERATORS has modal', typeof LAYOUT_GENERATORS.modal === 'function');
  test('LAYOUT_GENERATORS has tabbed', typeof LAYOUT_GENERATORS.tabbed === 'function');

  // Test generateComposition
  const cardComposition = composer.generateComposition('cardWithActions', {});
  test('generateComposition returns object', typeof cardComposition === 'object');
  test('generateComposition has name', cardComposition.name === 'Card with Actions');
  test('generateComposition has components', Array.isArray(cardComposition.components));
  test('generateComposition has code', typeof cardComposition.code === 'string');
  test('generateComposition has storyCode', typeof cardComposition.storyCode === 'string');

  // Test generateComposition for different patterns
  const tabsComposition = composer.generateComposition('tabs', {});
  test('tabs composition has Tab component', tabsComposition.components.includes('Tab'));

  const formComposition = composer.generateComposition('formWithValidation', {});
  test('form composition has Input component', formComposition.components.includes('Input'));

  // Test getPatterns
  const patterns = composer.getPatterns();
  test('getPatterns returns array', Array.isArray(patterns));
  test('getPatterns includes pattern id', patterns.some(p => p.id === 'cardWithActions'));

  // Test addPattern
  composer.addPattern('customPattern', {
    name: 'Custom Pattern',
    description: 'A custom pattern',
    components: ['Custom', 'Component'],
    layout: 'container'
  });
  const updatedPatterns = composer.getPatterns();
  test('addPattern adds custom pattern', updatedPatterns.some(p => p.id === 'customPattern'));

  // Test generateMultipleCompositions
  const multiple = composer.generateMultipleCompositions(['cardWithActions', 'tabs'], {});
  test('generateMultipleCompositions returns object', typeof multiple === 'object');
  test('generateMultipleCompositions has cardWithActions', multiple.cardWithActions !== undefined);
  test('generateMultipleCompositions has tabs', multiple.tabs !== undefined);

  // Test stats
  const stats = composer.getStats();
  test('getStats returns compositionsGenerated', stats.compositionsGenerated > 0);
  test('getStats returns patternsUsed', Array.isArray(stats.patternsUsed));
}

function testIntegration() {
  console.log('\n=== Integration Tests ===\n');

  // Test StoryGenerator integration with StoryVariants
  const generator = new StoryGenerator();
  test('StoryGenerator has variantsGenerator', generator.getVariantsGenerator() instanceof StoryVariants);

  // Test generateStoryWithVariants
  const storyWithVariants = generator.generateStoryWithVariants(testComponent, 'react');
  test('generateStoryWithVariants returns string', typeof storyWithVariants === 'string');
  test('generateStoryWithVariants includes Default', storyWithVariants.includes('Default'));
  test('generateStoryWithVariants includes Loading', storyWithVariants.includes('Loading'));

  // Test multi-framework support
  const vueVariants = new StoryVariants();
  const vueCode = vueVariants.generateStoryCode(testComponent, vueVariants.generateAllVariants(testComponent), 'vue');
  test('Vue story code generation works', vueCode.includes('@storybook/vue3'));

  const angularVariants = new StoryVariants();
  const angularCode = angularVariants.generateStoryCode(testComponent, angularVariants.generateAllVariants(testComponent), 'angular');
  test('Angular story code generation works', angularCode.includes('@storybook/angular'));

  // Test complete workflow
  const playground = new InteractivePlayground();
  const mdxGen = new MDXGenerator();
  const composer = new CompositionPatterns();

  const playgroundConfig = playground.generatePlayground(testComponent);
  const mdxContent = mdxGen.generateMDX(testComponent, { stories: playgroundConfig.examples });
  const composition = composer.generateComposition('cardWithActions', {});

  test('Complete workflow: playground generated', playgroundConfig.examples.length > 0);
  test('Complete workflow: MDX generated', mdxContent.includes('Button'));
  test('Complete workflow: composition generated', composition.code.includes('Card'));
}

// Run all tests
function runAllTests() {
  console.log('\n╔════════════════════════════════════════════════════════════╗');
  console.log('║    Phase 5: Advanced Storybook Features - Test Suite       ║');
  console.log('╚════════════════════════════════════════════════════════════╝');

  testSprint51();
  testSprint52();
  testSprint53();
  testSprint54();
  testIntegration();

  console.log('\n════════════════════════════════════════════════════════════');
  console.log(`Results: ${passed} passed, ${failed} failed (${passed}/${passed + failed})`);
  console.log('════════════════════════════════════════════════════════════\n');

  return failed === 0;
}

// Run if executed directly
if (require.main === module) {
  const success = runAllTests();
  process.exit(success ? 0 : 1);
}

module.exports = {
  runAllTests,
  testSprint51,
  testSprint52,
  testSprint53,
  testSprint54,
  testIntegration
};

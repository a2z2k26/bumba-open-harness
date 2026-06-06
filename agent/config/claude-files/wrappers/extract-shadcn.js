/**
 * extract-shadcn.js
 * Skill wrapper for ShadCN Registry extraction
 *
 * This module extracts components from the ShadCN registry using MCP Server tools,
 * including CVA variants, Tailwind token dependencies, and usage examples.
 */

const fs = require('fs');
const path = require('path');

// Import utilities from @design-bridge/server
const { extractCvaVariants, toDesignBridgeFormat, extractInteractiveStates, formatVariantSummary } = require('../../packages/@design-bridge/server/shadcn-variant-extractor');
const { extractTokenDependencies, mapToDesignTokens, formatTokenSummary } = require('../../packages/@design-bridge/server/shadcn-token-extractor');
const { transformShadcnComponent, formatComponentSummary, pascalCase, sanitizeFileName } = require('../../packages/@design-bridge/server/shadcn-transformer');

// Phase 2: Auto-registration support (Two-State Architecture)
const { AutoRegistrar } = require('../../packages/@design-bridge/server/auto-registrar');

/**
 * Main extraction function
 * @param {Object} options - Extraction options
 * @param {string} options.componentName - Component name to extract (e.g., "button")
 * @param {string} options.projectRoot - Project root directory
 * @param {Object} options.mcpClient - MCP client for tool calls
 * @param {Object} options.config - Additional configuration
 * @returns {Object} Extraction result
 */
async function extractFromShadcn(options) {
  const {
    componentName,
    projectRoot = process.cwd(),
    mcpClient,
    config = {}
  } = options;

  const startTime = Date.now();
  const log = [];
  const registries = config.registries || ['@shadcn'];

  try {
    // Step 1: Discover Registries (or use provided)
    log.push('Discovering available registries...');

    let availableRegistries = registries;
    try {
      const registryResponse = await mcpClient.call('mcp__shadcn__get_project_registries', {});
      if (registryResponse && registryResponse.registries) {
        availableRegistries = registryResponse.registries;
        log.push(`✓ Found registries: ${availableRegistries.join(', ')}`);
      } else {
        log.push(`⚠ Using default registries: ${registries.join(', ')}`);
      }
    } catch (regError) {
      log.push(`⚠ Could not discover registries: ${regError.message}`);
      log.push(`  Using default: ${registries.join(', ')}`);
    }

    // Step 2: Search for Component
    log.push(`Searching for component: ${componentName}...`);

    const searchResponse = await mcpClient.call('mcp__shadcn__search_items_in_registries', {
      registries: availableRegistries,
      query: componentName,
      limit: 10
    });

    if (!searchResponse || !searchResponse.items || searchResponse.items.length === 0) {
      throw new Error(`Component "${componentName}" not found in registry`);
    }

    // Find the main UI component (not examples)
    const uiComponent = searchResponse.items.find(item =>
      item.type === 'registry:ui' && item.name.toLowerCase() === componentName.toLowerCase()
    ) || searchResponse.items.find(item => item.type === 'registry:ui');

    if (!uiComponent) {
      throw new Error(`No UI component found for "${componentName}". Found: ${searchResponse.items.map(i => i.name).join(', ')}`);
    }

    log.push(`✓ Found component: ${uiComponent.name} (${uiComponent.type})`);

    // Step 3: Get Component Source Code
    log.push('Fetching component source code...');

    const sourceResponse = await mcpClient.call('mcp__shadcn__get_item_examples_from_registries', {
      registries: availableRegistries,
      query: componentName
    });

    if (!sourceResponse || !sourceResponse.examples || sourceResponse.examples.length === 0) {
      throw new Error('Could not fetch component source code');
    }

    // Find the main component source (not demos)
    const mainSource = sourceResponse.examples.find(ex =>
      ex.name === componentName || ex.name.endsWith(`.tsx`) || ex.type === 'registry:ui'
    ) || sourceResponse.examples[0];

    const sourceCode = mainSource.code || mainSource.content || '';
    log.push(`✓ Fetched source code (${sourceCode.length} chars)`);

    // Step 4: Extract CVA Variants
    log.push('Extracting CVA variants...');

    const cvaData = extractCvaVariants(sourceCode);
    const variantCount = cvaData.variants.length;
    const optionCount = cvaData.variants.reduce((sum, v) => sum + (v.options?.length || 0), 0);

    if (variantCount > 0) {
      log.push(`✓ Found ${variantCount} variant dimension(s) with ${optionCount} total options`);
      for (const variant of cvaData.variants) {
        log.push(`  - ${variant.name}: ${variant.options.map(o => o.value).join(', ')}`);
      }
    } else {
      log.push('⚠ No CVA variants detected (component may use composition)');
    }

    // Extract interactive states from CVA classes
    const interactiveStates = extractInteractiveStates(cvaData.variants);

    // Step 5: Extract Token Dependencies
    log.push('Extracting token dependencies...');

    const tokens = extractTokenDependencies(sourceCode);
    const tokenCounts = {
      colors: tokens.colors.length,
      typography: tokens.typography.length,
      spacing: tokens.spacing.length,
      effects: tokens.effects.length,
      borderRadius: tokens.borderRadius.length,
      cssVariables: tokens.cssVariables.length
    };

    log.push(`✓ Found tokens:`);
    log.push(`  Colors: ${tokenCounts.colors}`);
    log.push(`  Typography: ${tokenCounts.typography}`);
    log.push(`  Spacing: ${tokenCounts.spacing}`);
    log.push(`  Effects: ${tokenCounts.effects}`);
    log.push(`  Border Radius: ${tokenCounts.borderRadius}`);
    if (tokenCounts.cssVariables > 0) {
      log.push(`  CSS Variables: ${tokenCounts.cssVariables}`);
    }

    // Step 6: Get Usage Examples
    log.push('Fetching usage examples...');

    let examples = [];
    try {
      const examplesResponse = await mcpClient.call('mcp__shadcn__get_item_examples_from_registries', {
        registries: availableRegistries,
        query: `${componentName}-demo`
      });

      if (examplesResponse && examplesResponse.examples) {
        examples = examplesResponse.examples.map(ex => ({
          name: ex.name,
          code: ex.code || ex.content || '',
          description: ex.description || ''
        }));
        log.push(`✓ Found ${examples.length} example(s)`);
      }
    } catch (exampleError) {
      log.push(`⚠ Could not fetch examples: ${exampleError.message}`);
    }

    // Step 7: Get Dependencies
    log.push('Fetching dependencies...');

    let dependencies = [];
    try {
      const depsResponse = await mcpClient.call('mcp__shadcn__view_items_in_registries', {
        items: [`@shadcn/${componentName}`]
      });

      if (depsResponse && depsResponse.items) {
        const item = depsResponse.items[0];
        if (item && item.dependencies) {
          dependencies = Array.isArray(item.dependencies) ? item.dependencies : Object.keys(item.dependencies);
          log.push(`✓ Found ${dependencies.length} dependencies`);
          dependencies.forEach(dep => log.push(`  - ${dep}`));
        }
      }
    } catch (depsError) {
      log.push(`⚠ Could not fetch dependencies: ${depsError.message}`);
    }

    // Also extract dependencies from import statements
    const importDeps = extractImportDependencies(sourceCode);
    dependencies = [...new Set([...dependencies, ...importDeps])];

    // Step 8: Transform to Design Bridge Format
    log.push('Transforming to Design Bridge format...');

    const component = transformShadcnComponent({
      componentName: uiComponent.name,
      registryName: availableRegistries[0],
      sourceCode: sourceCode,
      examples: examples,
      dependencies: dependencies
    });

    // Merge extracted data
    component.variants = toDesignBridgeFormat(cvaData.variants, cvaData.defaultVariants);
    component.tokenDependencies = tokens;
    component.interactiveStates = interactiveStates;
    component.rawCva = {
      baseClasses: cvaData.baseClasses,
      defaultVariants: cvaData.defaultVariants
    };

    log.push(`✓ Transformed component: ${component.name}`);

    // Step 9: Write to Source Directory
    log.push('Writing source files...');

    const designDir = path.join(projectRoot, '.design');
    const sourceDir = path.join(designDir, 'source', 'components');

    // Ensure directories exist
    if (!fs.existsSync(sourceDir)) {
      fs.mkdirSync(sourceDir, { recursive: true });
    }

    const fileName = `${sanitizeFileName(component.name)}.json`;
    const filePath = path.join(sourceDir, fileName);

    // Add source code to component data
    const outputData = {
      ...component,
      sourceCode: sourceCode
    };

    fs.writeFileSync(filePath, JSON.stringify(outputData, null, 2));
    log.push(`✓ Written: ${path.relative(projectRoot, filePath)}`);

    // Step 10: Auto-register component (Phase 2: Two-State Architecture)
    log.push('Registering component...');

    const autoRegistrar = new AutoRegistrar({
      projectPath: projectRoot,
      autoRegisterOnImport: true,
      emitEvents: false
    });

    let componentId = `shadcn-${sanitizeFileName(component.name)}`;
    let registrationResult = null;

    try {
      const relativePath = path.relative(projectRoot, filePath);

      registrationResult = await autoRegistrar.registerComponent(
        {
          name: component.name,
          type: component.type,
          category: component.category,
          variants: component.variants,
          props: component.props || [],
          tokenDependencies: tokens,
          interactiveStates: interactiveStates
        },
        {
          type: 'shadcn',
          projectPath: projectRoot,
          fileKey: availableRegistries[0],
          nodeId: null,
          figmaModifiedAt: null,
          rawDataPath: relativePath
        }
      );

      componentId = registrationResult.id;
      log.push(`✓ Registered: ${componentId} (${registrationResult.isNew ? 'new' : 'updated'})`);
    } catch (regError) {
      log.push(`⚠ Registration failed: ${regError.message}`);
      log.push(`  Using fallback ID: ${componentId}`);
    }

    const duration = Date.now() - startTime;

    return {
      success: true,
      component: {
        id: componentId,
        name: component.name,
        type: component.type,
        category: component.category,
        variantDimensions: variantCount,
        totalOptions: optionCount,
        tokenCounts: tokenCounts,
        exampleCount: examples.length,
        dependencyCount: dependencies.length,
        hasInteractiveStates: Object.keys(interactiveStates).length > 0,
        registered: registrationResult?.success || false,
        isNew: registrationResult?.isNew || false
      },
      files: [filePath],
      duration: duration,
      log: log
    };

  } catch (error) {
    return {
      success: false,
      error: error.message,
      log: log
    };
  }
}

/**
 * Extract npm dependencies from import statements
 * @param {string} sourceCode - Component source code
 * @returns {Array} Dependencies
 */
function extractImportDependencies(sourceCode) {
  const deps = new Set();

  // Match import from 'package' or import from "package"
  const importMatches = sourceCode.matchAll(/import\s+.*?\s+from\s+['"]([^'"./][^'"]*)['"]/g);
  for (const match of importMatches) {
    const pkg = match[1];
    // Get package name (handle scoped packages like @radix-ui/react-slot)
    if (pkg.startsWith('@')) {
      const parts = pkg.split('/');
      deps.add(`${parts[0]}/${parts[1]}`);
    } else {
      deps.add(pkg.split('/')[0]);
    }
  }

  // Filter out React and common built-ins
  const filtered = Array.from(deps).filter(dep =>
    dep !== 'react' &&
    !dep.startsWith('react/') &&
    dep !== 'next' &&
    !dep.startsWith('next/')
  );

  return filtered;
}

/**
 * Extract multiple components
 * @param {Object} options - Extraction options
 * @param {string[]} options.componentNames - Array of component names
 * @param {string} options.projectRoot - Project root directory
 * @param {Object} options.mcpClient - MCP client for tool calls
 * @param {Object} options.config - Additional configuration
 * @returns {Object} Batch extraction result
 */
async function extractMultipleFromShadcn(options) {
  const {
    componentNames,
    projectRoot = process.cwd(),
    mcpClient,
    config = {}
  } = options;

  const results = [];
  const errors = [];

  for (const componentName of componentNames) {
    try {
      const result = await extractFromShadcn({
        componentName,
        projectRoot,
        mcpClient,
        config
      });

      if (result.success) {
        results.push(result);
      } else {
        errors.push({ componentName, error: result.error });
      }
    } catch (error) {
      errors.push({ componentName, error: error.message });
    }
  }

  return {
    success: errors.length === 0,
    extracted: results.length,
    failed: errors.length,
    components: results.map(r => r.component),
    errors: errors,
    totalDuration: results.reduce((sum, r) => sum + r.duration, 0)
  };
}

/**
 * Get CLI add command for components
 * @param {Object} options - Options
 * @param {string[]} options.componentNames - Component names
 * @param {Object} options.mcpClient - MCP client
 * @returns {Object} Add command result
 */
async function getAddCommand(options) {
  const { componentNames, mcpClient } = options;

  try {
    const items = componentNames.map(name => `@shadcn/${name}`);
    const response = await mcpClient.call('mcp__shadcn__get_add_command_for_items', {
      items: items
    });

    return {
      success: true,
      command: response.command || `npx shadcn@latest add ${componentNames.join(' ')}`
    };
  } catch (error) {
    return {
      success: false,
      error: error.message,
      command: `npx shadcn@latest add ${componentNames.join(' ')}`
    };
  }
}

/**
 * Format extraction result for display
 * @param {Object} result - Extraction result
 * @returns {string} Formatted output
 */
function formatExtractionResult(result) {
  if (!result.success) {
    return `Extraction failed: ${result.error}\n\nLog:\n${result.log.join('\n')}`;
  }

  const comp = result.component;
  const lines = [
    'Extraction complete!',
    '',
    `Component: ${comp.name}`,
    `Category: ${comp.category}`,
    `Type: ${comp.type}`,
    '',
    `Variants: ${comp.variantDimensions} dimensions, ${comp.totalOptions} total options`,
    '',
    'Token Dependencies:',
    `  Colors: ${comp.tokenCounts.colors}`,
    `  Typography: ${comp.tokenCounts.typography}`,
    `  Spacing: ${comp.tokenCounts.spacing}`,
    `  Effects: ${comp.tokenCounts.effects}`,
    '',
    `Examples: ${comp.exampleCount}`,
    `Dependencies: ${comp.dependencyCount}`,
    comp.hasInteractiveStates ? 'Has interactive states (hover/focus/etc.)' : '',
    '',
    `Duration: ${result.duration}ms`,
    '',
    'Log:',
  ];

  result.log.forEach(l => lines.push(`  ${l}`));

  return lines.filter(Boolean).join('\n');
}

module.exports = {
  extractFromShadcn,
  extractMultipleFromShadcn,
  extractImportDependencies,
  getAddCommand,
  formatExtractionResult
};

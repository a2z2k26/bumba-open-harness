/**
 * Batch Transformation Module
 * Transform multiple components in correct dependency order
 */

const fs = require('fs');
const path = require('path');
const { DependencyGraph } = require('./dependency-graph');

class BatchTransformer {
  constructor(projectRoot, options = {}) {
    this.projectRoot = projectRoot;
    this.registryPath = path.join(projectRoot, '.design');
    this.depGraph = new DependencyGraph(projectRoot);
    this.options = {
      continueOnError: options.continueOnError ?? true,
      parallelLimit: options.parallelLimit ?? 3,
      dryRun: options.dryRun ?? false,
      ...options
    };
  }

  /**
   * Transform a batch of components
   * @param {Array} componentIds - Component IDs to transform (or 'all')
   * @param {object} transformOptions - Options to pass to transformer
   * @returns {object} - Batch result
   */
  async transform(componentIds, transformOptions = {}) {
    const result = {
      started: new Date().toISOString(),
      requested: componentIds.length,
      succeeded: [],
      failed: [],
      skipped: [],
      order: [],
      duration: 0
    };

    const startTime = Date.now();

    try {
      // Build dependency graph
      this.depGraph.build();

      // Get transformation order
      let idsToTransform = componentIds;
      if (componentIds === 'all' || componentIds[0] === 'all') {
        idsToTransform = Object.keys(this.depGraph.graph.components);
      }

      result.order = this.depGraph.getOrderForComponents(idsToTransform);
      result.requested = result.order.length;

      console.log(`[batch-transform] Transforming ${result.order.length} components in dependency order`);

      // Transform in order
      const sharedContext = {
        imports: new Map(),
        processedComponents: new Set(),
        errors: []
      };

      for (let i = 0; i < result.order.length; i++) {
        const componentId = result.order[i];
        const componentData = this.depGraph.graph.components[componentId];

        console.log(`[batch-transform] (${i + 1}/${result.order.length}) ${componentData?.name || componentId}`);

        // Check dependencies are processed
        const unprocessedDeps = componentData?.dependsOn.components.filter(
          dep => !sharedContext.processedComponents.has(dep) && result.order.includes(dep)
        ) || [];

        if (unprocessedDeps.length > 0 && !this.options.continueOnError) {
          result.skipped.push({
            id: componentId,
            name: componentData?.name,
            reason: `Unprocessed dependencies: ${unprocessedDeps.join(', ')}`
          });
          continue;
        }

        try {
          if (!this.options.dryRun) {
            await this.transformComponent(componentId, transformOptions, sharedContext);
          }

          result.succeeded.push({
            id: componentId,
            name: componentData?.name,
            dependencies: componentData?.dependsOn.components.length || 0
          });

          sharedContext.processedComponents.add(componentId);

        } catch (err) {
          console.error(`[batch-transform] Failed: ${componentData?.name}:`, err.message);

          result.failed.push({
            id: componentId,
            name: componentData?.name,
            error: err.message
          });

          if (!this.options.continueOnError) {
            break;
          }
        }
      }

    } catch (err) {
      result.error = err.message;
    }

    result.duration = Date.now() - startTime;
    result.completed = new Date().toISOString();

    return result;
  }

  /**
   * Transform a single component with shared context
   */
  async transformComponent(componentId, options, sharedContext) {
    // Load component from registry
    const registryFile = path.join(this.registryPath, 'components', 'registry.json');
    const registry = JSON.parse(fs.readFileSync(registryFile, 'utf-8'));
    const component = registry.components[componentId];

    if (!component) {
      throw new Error(`Component not found: ${componentId}`);
    }

    // Determine transformer
    const framework = options.framework || 'react';
    const transformerPath = path.join(
      this.projectRoot,
      '.claude',
      'wrappers',
      `transform-${framework}.js`
    );

    if (!fs.existsSync(transformerPath)) {
      throw new Error(`Transformer not found: ${framework}`);
    }

    // Load raw file if exists
    let rawData = null;
    if (component.paths?.rawSource) {
      const rawPath = path.join(this.registryPath, component.paths.rawSource);
      if (fs.existsSync(rawPath)) {
        rawData = JSON.parse(fs.readFileSync(rawPath, 'utf-8'));
      }
    }

    // Merge shared imports
    const imports = Array.from(sharedContext.imports.values());

    // Call transformer
    const transformer = require(transformerPath);
    const result = await transformer.transform({
      component,
      rawData,
      options: {
        ...options,
        sharedImports: imports
      }
    });

    // Track output imports for subsequent components
    if (result.imports) {
      for (const imp of result.imports) {
        sharedContext.imports.set(imp.name, imp);
      }
    }

    // Write output if paths defined
    if (result.code && component.paths?.codeOutput) {
      const outputPath = path.join(this.projectRoot, component.paths.codeOutput);
      const outputDir = path.dirname(outputPath);

      if (!fs.existsSync(outputDir)) {
        fs.mkdirSync(outputDir, { recursive: true });
      }

      fs.writeFileSync(outputPath, result.code);
    }

    return result;
  }

  /**
   * Preview batch transformation (dry run)
   * @param {Array} componentIds - Component IDs
   * @returns {object} - Preview result
   */
  preview(componentIds) {
    this.depGraph.build();

    let idsToTransform = componentIds;
    if (componentIds === 'all' || componentIds[0] === 'all') {
      idsToTransform = Object.keys(this.depGraph.graph.components);
    }

    const order = this.depGraph.getOrderForComponents(idsToTransform);

    const preview = {
      totalComponents: order.length,
      transformationOrder: order.map((id, index) => ({
        order: index + 1,
        id,
        name: this.depGraph.graph.components[id]?.name,
        dependencies: this.depGraph.graph.components[id]?.dependsOn.components.length || 0,
        source: this.depGraph.graph.components[id]?.source
      })),
      dependencyLevels: this.groupByDependencyLevel(order)
    };

    return preview;
  }

  /**
   * Group components by dependency level
   */
  groupByDependencyLevel(order) {
    const levels = [];
    const processed = new Set();

    while (processed.size < order.length) {
      const currentLevel = [];

      for (const id of order) {
        if (processed.has(id)) continue;

        const data = this.depGraph.graph.components[id];
        const deps = data?.dependsOn.components || [];

        // Check if all deps are processed
        const allDepsProcessed = deps.every(dep =>
          processed.has(dep) || !order.includes(dep)
        );

        if (allDepsProcessed) {
          currentLevel.push({
            id,
            name: data?.name
          });
        }
      }

      if (currentLevel.length === 0) break; // Circular deps

      for (const item of currentLevel) {
        processed.add(item.id);
      }

      levels.push(currentLevel);
    }

    return levels;
  }

  /**
   * Generate batch report
   */
  generateReport(result) {
    const lines = [
      '=== Batch Transformation Report ===',
      '',
      `Started: ${result.started}`,
      `Completed: ${result.completed}`,
      `Duration: ${result.duration}ms`,
      '',
      `Requested: ${result.requested}`,
      `Succeeded: ${result.succeeded.length}`,
      `Failed: ${result.failed.length}`,
      `Skipped: ${result.skipped.length}`,
      ''
    ];

    if (result.succeeded.length > 0) {
      lines.push('--- Succeeded ---');
      for (const item of result.succeeded) {
        lines.push(`  ✓ ${item.name} (${item.dependencies} deps)`);
      }
      lines.push('');
    }

    if (result.failed.length > 0) {
      lines.push('--- Failed ---');
      for (const item of result.failed) {
        lines.push(`  ✗ ${item.name}: ${item.error}`);
      }
      lines.push('');
    }

    if (result.skipped.length > 0) {
      lines.push('--- Skipped ---');
      for (const item of result.skipped) {
        lines.push(`  ⊘ ${item.name}: ${item.reason}`);
      }
      lines.push('');
    }

    if (result.error) {
      lines.push(`Error: ${result.error}`);
    }

    return lines.join('\n');
  }
}

// CLI entry point
async function batchTransformCLI(args) {
  const projectRoot = process.cwd();
  const components = args.components || args.batch?.split(',') || ['all'];
  const options = {
    framework: args.framework || 'react',
    continueOnError: args.continueOnError !== false,
    dryRun: args.preview || args.dryRun || false
  };

  const transformer = new BatchTransformer(projectRoot, options);

  if (options.dryRun) {
    const preview = transformer.preview(components);
    console.log(JSON.stringify(preview, null, 2));
    return preview;
  }

  const result = await transformer.transform(components, options);
  console.log(transformer.generateReport(result));
  return result;
}

module.exports = { BatchTransformer, batchTransformCLI };

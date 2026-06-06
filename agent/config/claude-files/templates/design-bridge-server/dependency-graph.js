/**
 * Dependency Graph Module
 * Tracks and analyzes relationships between components and tokens
 */

const fs = require('fs');
const path = require('path');
const { ComponentRefResolver } = require('./component-refs');
const { TokenSharingManager, detectSourceType } = require('./token-sharing');

class DependencyGraph {
  constructor(projectRoot) {
    this.projectRoot = projectRoot;
    this.registryPath = path.join(projectRoot, '.design');
    this.refResolver = new ComponentRefResolver(this.registryPath);
    this.tokenManager = new TokenSharingManager(projectRoot);
    this.graph = null;
  }

  /**
   * Build the complete dependency graph
   * @returns {object} - Complete dependency graph
   */
  build() {
    const registryFile = path.join(this.registryPath, 'components', 'registry.json');
    if (!fs.existsSync(registryFile)) {
      const emptyGraph = {
        components: {},
        tokens: {},
        metadata: {
          built: new Date().toISOString(),
          componentCount: 0,
          hasCircularDeps: false,
          error: 'Registry not found'
        }
      };
      this.graph = emptyGraph;
      return emptyGraph;
    }

    const registry = JSON.parse(fs.readFileSync(registryFile, 'utf-8'));
    const components = registry.components || {};

    const graph = {
      components: {},
      tokens: {},
      metadata: {
        built: new Date().toISOString(),
        componentCount: Object.keys(components).length,
        hasCircularDeps: false
      }
    };

    // Process each component
    for (const [id, component] of Object.entries(components)) {
      const componentDeps = this.refResolver.getComponentDependencies(id);
      const sourceType = detectSourceType(component.source);
      const tokenResult = this.tokenManager.resolveComponentTokens(
        component.tokenDependencies,
        sourceType
      );

      graph.components[id] = {
        name: component.name,
        category: component.category,
        source: component.source?.type || 'unknown',
        dependsOn: {
          components: componentDeps,
          tokens: this.flattenTokenDeps(tokenResult.resolved)
        },
        usedBy: [], // Filled in second pass
        missingTokens: tokenResult.missing
      };
    }

    // Second pass: fill in usedBy
    for (const [id, data] of Object.entries(graph.components)) {
      for (const depId of data.dependsOn.components) {
        if (graph.components[depId]) {
          graph.components[depId].usedBy.push(id);
        }
      }
    }

    // Build token graph
    const allTokens = new Set();
    for (const data of Object.values(graph.components)) {
      data.dependsOn.tokens.forEach(t => allTokens.add(t));
    }

    for (const token of allTokens) {
      const usedBy = [];
      for (const [id, data] of Object.entries(graph.components)) {
        if (data.dependsOn.tokens.includes(token)) {
          usedBy.push(id);
        }
      }
      graph.tokens[token] = { usedBy };
    }

    // Check for circular dependencies
    graph.metadata.hasCircularDeps = this.hasCircularDependencies(graph.components);
    if (graph.metadata.hasCircularDeps) {
      graph.metadata.circularPaths = this.findCircularPaths(graph.components);
    }

    this.graph = graph;
    return graph;
  }

  /**
   * Flatten token dependencies into array
   */
  flattenTokenDeps(resolved) {
    const tokens = [];
    for (const refs of Object.values(resolved)) {
      tokens.push(...refs);
    }
    return [...new Set(tokens)];
  }

  /**
   * Check for circular dependencies
   */
  hasCircularDependencies(components) {
    const visited = new Set();
    const recursionStack = new Set();

    const dfs = (nodeId) => {
      visited.add(nodeId);
      recursionStack.add(nodeId);

      const node = components[nodeId];
      if (node && node.dependsOn.components) {
        for (const depId of node.dependsOn.components) {
          if (!visited.has(depId)) {
            if (dfs(depId)) return true;
          } else if (recursionStack.has(depId)) {
            return true;
          }
        }
      }

      recursionStack.delete(nodeId);
      return false;
    };

    for (const id of Object.keys(components)) {
      if (!visited.has(id)) {
        if (dfs(id)) return true;
      }
    }

    return false;
  }

  /**
   * Find circular dependency paths
   */
  findCircularPaths(components) {
    const paths = [];

    const findPath = (startId, currentId, path, visited) => {
      if (visited.has(currentId)) {
        if (currentId === startId && path.length > 1) {
          paths.push([...path, currentId]);
        }
        return;
      }

      visited.add(currentId);
      path.push(currentId);

      const node = components[currentId];
      if (node && node.dependsOn.components) {
        for (const depId of node.dependsOn.components) {
          findPath(startId, depId, [...path], new Set(visited));
        }
      }
    };

    for (const id of Object.keys(components)) {
      findPath(id, id, [], new Set());
    }

    return paths;
  }

  /**
   * Get topological sort order for transformation
   * @returns {Array} - Component IDs in transformation order
   */
  getTransformationOrder() {
    const graph = this.graph || this.build();
    const inDegree = {};
    const queue = [];
    const order = [];

    // Initialize in-degrees
    for (const id of Object.keys(graph.components)) {
      inDegree[id] = graph.components[id].dependsOn.components.length;
      if (inDegree[id] === 0) {
        queue.push(id);
      }
    }

    // Process queue
    while (queue.length > 0) {
      const current = queue.shift();
      order.push(current);

      // Reduce in-degree for dependents
      for (const id of graph.components[current].usedBy) {
        inDegree[id]--;
        if (inDegree[id] === 0) {
          queue.push(id);
        }
      }
    }

    // Check for remaining (circular deps)
    if (order.length !== Object.keys(graph.components).length) {
      console.warn('[dependency-graph] Circular dependencies detected, some components may not be in order');
      // Add remaining components
      for (const id of Object.keys(graph.components)) {
        if (!order.includes(id)) {
          order.push(id);
        }
      }
    }

    return order;
  }

  /**
   * Get transformation order for specific components
   * @param {Array} componentIds - Component IDs to transform
   * @returns {Array} - IDs in correct order
   */
  getOrderForComponents(componentIds) {
    const fullOrder = this.getTransformationOrder();
    return fullOrder.filter(id => componentIds.includes(id));
  }

  /**
   * Get all dependencies for a component (transitive)
   * @param {string} componentId - Component ID
   * @returns {Set} - All dependency IDs (transitive)
   */
  getAllDependencies(componentId) {
    const graph = this.graph || this.build();
    const deps = new Set();

    const collect = (id) => {
      const node = graph.components[id];
      if (!node) return;

      for (const depId of node.dependsOn.components) {
        if (!deps.has(depId)) {
          deps.add(depId);
          collect(depId);
        }
      }
    };

    collect(componentId);
    return deps;
  }

  /**
   * Get impact analysis for a component (what breaks if this changes)
   * @param {string} componentId - Component ID
   * @returns {object} - Impact analysis
   */
  getImpactAnalysis(componentId) {
    const graph = this.graph || this.build();
    const directDependents = new Set();
    const transitiveDependents = new Set();

    const collectDependents = (id, isDirect = true) => {
      const node = graph.components[id];
      if (!node) return;

      for (const depId of node.usedBy) {
        if (isDirect) directDependents.add(depId);
        if (!transitiveDependents.has(depId)) {
          transitiveDependents.add(depId);
          collectDependents(depId, false);
        }
      }
    };

    collectDependents(componentId);

    return {
      componentId,
      componentName: graph.components[componentId]?.name,
      directDependents: Array.from(directDependents),
      transitiveDependents: Array.from(transitiveDependents),
      totalImpact: transitiveDependents.size,
      affectedComponents: Array.from(transitiveDependents).map(id => ({
        id,
        name: graph.components[id]?.name
      }))
    };
  }

  /**
   * Export graph as JSON
   */
  exportGraph() {
    const graph = this.graph || this.build();
    return JSON.stringify(graph, null, 2);
  }

  /**
   * Generate Mermaid diagram for visualization
   * @param {object} options - { showTokens: boolean, maxNodes: number }
   * @returns {string} - Mermaid diagram source
   */
  toMermaid(options = {}) {
    const { showTokens = false, maxNodes = 50 } = options;
    const graph = this.graph || this.build();

    const lines = ['graph TD'];
    let nodeCount = 0;

    // Add component nodes and edges
    for (const [id, data] of Object.entries(graph.components)) {
      if (nodeCount >= maxNodes) break;

      // Node style based on source
      const style = this.getMermaidStyle(data.source);
      lines.push(`  ${id}[${data.name}]${style}`);
      nodeCount++;

      // Component dependencies
      for (const depId of data.dependsOn.components) {
        if (graph.components[depId]) {
          lines.push(`  ${id} --> ${depId}`);
        }
      }

      // Token dependencies (optional)
      if (showTokens && data.dependsOn.tokens.length > 0) {
        const tokenNode = `${id}_tokens`;
        const tokenList = data.dependsOn.tokens.slice(0, 3).join(', ');
        lines.push(`  ${tokenNode}{{${tokenList}...}}`);
        lines.push(`  ${id} -.-> ${tokenNode}`);
      }
    }

    return lines.join('\n');
  }

  getMermaidStyle(source) {
    const styles = {
      'figma-mcp': ':::figma',
      'figma-plugin': ':::figma',
      'shadcn': ':::shadcn',
      'nlp-prompt': ':::nlp',
      'manual': ':::manual'
    };
    return styles[source] || '';
  }

  /**
   * Generate summary report
   */
  generateReport() {
    const graph = this.graph || this.build();

    const lines = [
      '=== Dependency Graph Report ===',
      '',
      `Total Components: ${graph.metadata.componentCount}`,
      `Total Tokens Used: ${Object.keys(graph.tokens).length}`,
      `Has Circular Dependencies: ${graph.metadata.hasCircularDeps}`,
      '',
      '--- Components by Dependency Count ---'
    ];

    // Sort by dependency count
    const sorted = Object.entries(graph.components)
      .sort((a, b) => b[1].dependsOn.components.length - a[1].dependsOn.components.length);

    for (const [id, data] of sorted.slice(0, 10)) {
      lines.push(`  ${data.name}: ${data.dependsOn.components.length} deps, used by ${data.usedBy.length}`);
    }

    if (graph.metadata.hasCircularDeps) {
      lines.push('', '--- Circular Dependencies ---');
      for (const cyclePath of graph.metadata.circularPaths || []) {
        const names = cyclePath.map(id => graph.components[id]?.name || id);
        lines.push(`  ${names.join(' → ')}`);
      }
    }

    lines.push('', '--- Most Used Tokens ---');
    const tokensSorted = Object.entries(graph.tokens)
      .sort((a, b) => b[1].usedBy.length - a[1].usedBy.length);

    for (const [token, data] of tokensSorted.slice(0, 10)) {
      lines.push(`  ${token}: used by ${data.usedBy.length} components`);
    }

    return lines.join('\n');
  }

  /**
   * Get component stats
   */
  getStats() {
    const graph = this.graph || this.build();

    const sourceDistribution = {};
    for (const data of Object.values(graph.components)) {
      const source = data.source || 'unknown';
      sourceDistribution[source] = (sourceDistribution[source] || 0) + 1;
    }

    return {
      totalComponents: graph.metadata.componentCount,
      totalTokens: Object.keys(graph.tokens).length,
      hasCircularDeps: graph.metadata.hasCircularDeps,
      sourceDistribution,
      avgDependencies: Object.values(graph.components).reduce((sum, c) => sum + c.dependsOn.components.length, 0) / graph.metadata.componentCount || 0
    };
  }

  /**
   * Clear graph cache
   */
  clearCache() {
    this.graph = null;
    this.refResolver.clearCache();
    this.tokenManager.clearCache();
  }
}

module.exports = { DependencyGraph };

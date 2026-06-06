/**
 * Dependency Analysis Tool
 * Analyzes GitHub issue dependencies and builds dependency graph
 *
 * Unique feature not in agent-sandboxes - provides intelligent orchestration
 */

import { getIssue, parseDependencies, GitHubIssue } from '../mcp-servers/github.js';

// ============================================================================
// Types
// ============================================================================

export interface AnalyzeDependenciesArgs {
  owner: string;
  repo: string;
  issues: number[];
}

export interface DependencyNode {
  issueNumber: number;
  title: string;
  status: 'ready' | 'blocked' | 'completed' | 'failed';
  dependencies: number[];
  blockedBy: number[];
  labels: string[];
}

export interface DependencyGraph {
  nodes: Record<number, DependencyNode>;
  edges: Array<{ from: number; to: number }>;
}

export interface AnalyzeDependenciesResult {
  graph: DependencyGraph;
  ready: number[];
  blocked: number[];
  circular?: number[][];
  error?: string;
}

// ============================================================================
// Dependency Analysis
// ============================================================================

/**
 * Analyze dependencies for a set of GitHub issues
 * Returns dependency graph and categorizes issues as ready/blocked
 */
export async function analyzeDependencies(
  args: AnalyzeDependenciesArgs
): Promise<AnalyzeDependenciesResult> {
  const { owner, repo, issues } = args;

  try {
    // Step 1: Fetch all issues from GitHub
    const issueData: Map<number, GitHubIssue> = new Map();
    const dependencies: Map<number, { dependsOn: number[]; blockedBy: number[] }> = new Map();

    for (const issueNumber of issues) {
      try {
        const issue = await getIssue(owner, repo, issueNumber);
        issueData.set(issueNumber, issue);

        // Parse dependencies from issue body
        const deps = parseDependencies(issue.body);
        dependencies.set(issueNumber, deps);
      } catch (error) {
        // Issue doesn't exist or can't be accessed
        console.error(`Error fetching issue #${issueNumber}:`, error);
      }
    }

    // Step 2: Build dependency graph
    const graph: DependencyGraph = {
      nodes: {},
      edges: [],
    };

    for (const [issueNumber, issue] of issueData.entries()) {
      const deps = dependencies.get(issueNumber) || { dependsOn: [], blockedBy: [] };

      // Determine issue status
      let status: 'ready' | 'blocked' | 'completed' | 'failed' = 'ready';
      if (issue.state === 'closed') {
        status = 'completed';
      } else {
        // Check if any dependencies are unresolved
        const unresolvedDeps = deps.dependsOn.filter((depNum) => {
          const depIssue = issueData.get(depNum);
          return !depIssue || depIssue.state !== 'closed';
        });

        if (unresolvedDeps.length > 0) {
          status = 'blocked';
        }
      }

      // Create node
      graph.nodes[issueNumber] = {
        issueNumber,
        title: issue.title,
        status,
        dependencies: deps.dependsOn,
        blockedBy: deps.blockedBy,
        labels: issue.labels,
      };

      // Create edges (from dependency to dependent)
      for (const depNum of deps.dependsOn) {
        graph.edges.push({
          from: depNum,
          to: issueNumber,
        });
      }
    }

    // Step 3: Detect circular dependencies
    const circular = detectCircularDependencies(graph);

    // Step 4: Categorize issues
    const ready: number[] = [];
    const blocked: number[] = [];

    for (const [issueNumber, node] of Object.entries(graph.nodes)) {
      if (node.status === 'ready') {
        ready.push(parseInt(issueNumber, 10));
      } else if (node.status === 'blocked') {
        blocked.push(parseInt(issueNumber, 10));
      }
    }

    return {
      graph,
      ready,
      blocked,
      circular: circular.length > 0 ? circular : undefined,
    };
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : String(error);
    return {
      graph: { nodes: {}, edges: [] },
      ready: [],
      blocked: [],
      error: errorMessage,
    };
  }
}

// ============================================================================
// Circular Dependency Detection
// ============================================================================

/**
 * Detect circular dependencies using DFS
 * Returns array of cycles found
 */
function detectCircularDependencies(graph: DependencyGraph): number[][] {
  const cycles: number[][] = [];
  const visited = new Set<number>();
  const recursionStack = new Set<number>();
  const currentPath: number[] = [];

  function dfs(node: number): void {
    visited.add(node);
    recursionStack.add(node);
    currentPath.push(node);

    const nodeData = graph.nodes[node];
    if (nodeData) {
      for (const dep of nodeData.dependencies) {
        if (!visited.has(dep)) {
          dfs(dep);
        } else if (recursionStack.has(dep)) {
          // Found a cycle
          const cycleStart = currentPath.indexOf(dep);
          const cycle = currentPath.slice(cycleStart);
          cycles.push([...cycle, dep]); // Add dep again to show the cycle
        }
      }
    }

    currentPath.pop();
    recursionStack.delete(node);
  }

  for (const nodeNum of Object.keys(graph.nodes).map(Number)) {
    if (!visited.has(nodeNum)) {
      dfs(nodeNum);
    }
  }

  return cycles;
}

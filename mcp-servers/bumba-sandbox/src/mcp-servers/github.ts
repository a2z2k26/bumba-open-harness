/**
 * GitHub API Integration Module
 * Provides GitHub API wrapper using Octokit
 */

import { Octokit } from '@octokit/rest';

// ============================================================================
// GitHub Client
// ============================================================================

let octokit: Octokit | null = null;

/**
 * Initialize GitHub client with authentication
 */
export function initializeGitHub(token: string): Octokit {
  octokit = new Octokit({ auth: token });
  return octokit;
}

/**
 * Get GitHub client (must be initialized first)
 */
export function getGitHub(): Octokit {
  if (!octokit) {
    throw new Error('GitHub client not initialized. Call initializeGitHub() first.');
  }
  return octokit;
}

// ============================================================================
// Issue Operations
// ============================================================================

export interface GitHubIssue {
  number: number;
  title: string;
  body: string | null;
  state: 'open' | 'closed';
  labels: string[];
  assignees: string[];
}

/**
 * Get a single issue by number
 */
export async function getIssue(
  owner: string,
  repo: string,
  issueNumber: number
): Promise<GitHubIssue> {
  const client = getGitHub();

  const { data } = await client.issues.get({
    owner,
    repo,
    issue_number: issueNumber,
  });

  return {
    number: data.number,
    title: data.title,
    body: data.body || null,
    state: data.state as 'open' | 'closed',
    labels: data.labels.map((label) =>
      typeof label === 'string' ? label : label.name || ''
    ),
    assignees: data.assignees?.map((assignee) => assignee.login) || [],
  };
}

/**
 * List issues with optional filters
 */
export async function listIssues(
  owner: string,
  repo: string,
  options?: {
    state?: 'open' | 'closed' | 'all';
    labels?: string[];
    assignee?: string;
    perPage?: number;
  }
): Promise<GitHubIssue[]> {
  const client = getGitHub();

  const { data } = await client.issues.listForRepo({
    owner,
    repo,
    state: options?.state || 'open',
    labels: options?.labels?.join(','),
    assignee: options?.assignee,
    per_page: options?.perPage || 100,
  });

  return data.map((issue) => ({
    number: issue.number,
    title: issue.title,
    body: issue.body || null,
    state: issue.state as 'open' | 'closed',
    labels: issue.labels.map((label) =>
      typeof label === 'string' ? label : label.name || ''
    ),
    assignees: issue.assignees?.map((assignee) => assignee.login) || [],
  }));
}

/**
 * Create a new issue
 */
export async function createIssue(
  owner: string,
  repo: string,
  data: {
    title: string;
    body?: string;
    labels?: string[];
    assignees?: string[];
  }
): Promise<GitHubIssue> {
  const client = getGitHub();

  const { data: issue } = await client.issues.create({
    owner,
    repo,
    title: data.title,
    body: data.body,
    labels: data.labels,
    assignees: data.assignees,
  });

  return {
    number: issue.number,
    title: issue.title,
    body: issue.body || null,
    state: issue.state as 'open' | 'closed',
    labels: issue.labels.map((label) =>
      typeof label === 'string' ? label : label.name || ''
    ),
    assignees: issue.assignees?.map((assignee) => assignee.login) || [],
  };
}

/**
 * Update an existing issue
 */
export async function updateIssue(
  owner: string,
  repo: string,
  issueNumber: number,
  data: {
    title?: string;
    body?: string;
    state?: 'open' | 'closed';
    labels?: string[];
    assignees?: string[];
  }
): Promise<GitHubIssue> {
  const client = getGitHub();

  const { data: issue } = await client.issues.update({
    owner,
    repo,
    issue_number: issueNumber,
    title: data.title,
    body: data.body,
    state: data.state,
    labels: data.labels,
    assignees: data.assignees,
  });

  return {
    number: issue.number,
    title: issue.title,
    body: issue.body || null,
    state: issue.state as 'open' | 'closed',
    labels: issue.labels.map((label) =>
      typeof label === 'string' ? label : label.name || ''
    ),
    assignees: issue.assignees?.map((assignee) => assignee.login) || [],
  };
}

// ============================================================================
// Dependency Parsing
// ============================================================================

/**
 * Parse dependencies from issue body
 * Supports patterns: "Depends on #123", "Blocked by #456"
 */
export function parseDependencies(issueBody: string | null): {
  dependsOn: number[];
  blockedBy: number[];
} {
  if (!issueBody) {
    return { dependsOn: [], blockedBy: [] };
  }

  const dependsOn: number[] = [];
  const blockedBy: number[] = [];

  // Match "Depends on #123" pattern
  const dependsPattern = /depends\s+on\s+#(\d+)/gi;
  let match;
  while ((match = dependsPattern.exec(issueBody)) !== null) {
    dependsOn.push(parseInt(match[1], 10));
  }

  // Match "Blocked by #456" pattern
  const blockedPattern = /blocked\s+by\s+#(\d+)/gi;
  while ((match = blockedPattern.exec(issueBody)) !== null) {
    blockedBy.push(parseInt(match[1], 10));
  }

  return { dependsOn, blockedBy };
}

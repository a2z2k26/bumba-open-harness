/**
 * sync-helper.js
 *
 * Helper functions for GitHub → Notion synchronization
 * Implements project lookup, GitHub issue fetching, Notion task creation, and retry logic
 */

const fs = require('fs');
const path = require('path');
const https = require('https');
const { execSync } = require('child_process');

/**
 * Load configuration files
 */
function loadConfig() {
  const configDir = path.join(
    process.env.HOME || process.env.USERPROFILE,
    '.claude', 'plugins', 'bumba-notion', 'config'
  );

  const workspaceMapping = JSON.parse(
    fs.readFileSync(path.join(configDir, 'workspace-mapping.json'), 'utf8')
  );

  const syncRules = JSON.parse(
    fs.readFileSync(path.join(configDir, 'sync-rules.json'), 'utf8')
  );

  return { workspaceMapping, syncRules };
}

/**
 * Parse GitHub repository URL
 * @param {string} githubRepoUrl - Full GitHub repository URL
 * @returns {{owner: string, repo: string, url: string}} Parsed components
 */
function parseGitHubUrl(githubRepoUrl) {
  const urlPattern = /^https:\/\/github\.com\/([^\/]+)\/([^\/]+)\/?$/;
  const match = githubRepoUrl.match(urlPattern);

  if (!match) {
    throw new Error(`Invalid GitHub repository URL: ${githubRepoUrl}\nExpected format: https://github.com/owner/repo`);
  }

  return {
    owner: match[1],
    repo: match[2],
    url: githubRepoUrl
  };
}

/**
 * Find project metadata using three-tier lookup strategy
 * Note: MCP lookups should be done by the calling command context (Claude Code)
 * This function handles local file fallback
 *
 * @param {string} githubRepoUrl - GitHub repository URL
 * @returns {Object|null} Project metadata or null if not found
 */
async function findProjectMetadata(githubRepoUrl) {
  const { owner, repo } = parseGitHubUrl(githubRepoUrl);

  // Try local state fallback
  const stateDir = path.join(
    process.env.HOME || process.env.USERPROFILE,
    '.claude', 'plugins', 'bumba-notion', 'state'
  );

  if (!fs.existsSync(stateDir)) {
    return null;
  }

  // Search through project files
  const projectFiles = fs.readdirSync(stateDir).filter(f => f.startsWith('project-') && f.endsWith('.json'));

  for (const file of projectFiles) {
    const filePath = path.join(stateDir, file);
    try {
      const metadata = JSON.parse(fs.readFileSync(filePath, 'utf8'));
      if (metadata.githubRepo === githubRepoUrl) {
        return metadata;
      }
    } catch (error) {
      console.error(`Error reading ${file}:`, error.message);
    }
  }

  return null;
}

/**
 * Fetch GitHub issues using gh CLI
 * @param {string} owner - Repository owner
 * @param {string} repo - Repository name
 * @param {number} limit - Maximum number of issues to fetch
 * @returns {Array} Array of GitHub issues
 */
function fetchGitHubIssues(owner, repo, limit = 100) {
  try {
    const command = `gh issue list --repo ${owner}/${repo} --state open --limit ${limit} --json number,title,state,url,body,labels,createdAt,updatedAt,milestone`;

    const output = execSync(command, { encoding: 'utf8' });
    const issues = JSON.parse(output);

    // Filter out pull requests (gh issue list sometimes includes them)
    return issues.filter(issue => !issue.pull_request);
  } catch (error) {
    if (error.message.includes('gh: command not found')) {
      throw new Error('GitHub CLI (gh) not found. Please install: https://cli.github.com/');
    }
    throw new Error(`Failed to fetch GitHub issues: ${error.message}`);
  }
}

/**
 * Make Notion API request using native https module
 * @param {string} token - Notion API token
 * @param {string} method - HTTP method (GET, POST, PATCH)
 * @param {string} endpoint - API endpoint path
 * @param {Object} body - Request body (optional)
 * @returns {Promise<Object>} Response data
 */
function notionApiRequest(token, method, endpoint, body = null) {
  return new Promise((resolve, reject) => {
    const options = {
      hostname: 'api.notion.com',
      port: 443,
      path: endpoint,
      method: method,
      headers: {
        'Authorization': `Bearer ${token}`,
        'Notion-Version': '2022-06-28',
        'Content-Type': 'application/json'
      }
    };

    const req = https.request(options, (res) => {
      let data = '';

      res.on('data', (chunk) => {
        data += chunk;
      });

      res.on('end', () => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          try {
            resolve(JSON.parse(data));
          } catch (e) {
            resolve(data);
          }
        } else {
          reject(new Error(`Notion API error (${res.statusCode}): ${data}`));
        }
      });
    });

    req.on('error', (error) => {
      reject(error);
    });

    if (body) {
      req.write(JSON.stringify(body));
    }

    req.end();
  });
}

/**
 * Check if task already exists in Notion by GitHub Issue URL
 * @param {string} notionToken - Notion API token
 * @param {string} tasksDbId - Tasks database ID
 * @param {string} githubIssueUrl - GitHub issue URL to check
 * @returns {Promise<boolean>} True if task exists, false otherwise
 */
async function checkDuplicateTask(notionToken, tasksDbId, githubIssueUrl) {
  try {
    const filter = {
      property: 'GitHub Issue',
      url: {
        equals: githubIssueUrl
      }
    };

    const response = await notionApiRequest(
      notionToken,
      'POST',
      `/v1/databases/${tasksDbId}/query`,
      { filter }
    );

    return response.results && response.results.length > 0;
  } catch (error) {
    console.error(`Error checking duplicate for ${githubIssueUrl}:`, error.message);
    return false; // Assume doesn't exist on error, will fail gracefully when trying to create
  }
}

/**
 * Map GitHub issue state to Notion status
 * @param {string} githubState - GitHub issue state
 * @param {Object} statusMapping - Status mapping rules
 * @returns {string} Notion status
 */
function mapGitHubStateToNotion(githubState, statusMapping) {
  return statusMapping.github_to_notion[githubState] || 'backlog';
}

/**
 * Create Notion task from GitHub issue with retry logic
 * @param {string} notionToken - Notion API token
 * @param {string} tasksDbId - Tasks database ID
 * @param {Object} issue - GitHub issue object
 * @param {string} githubRepoUrl - GitHub repository URL
 * @param {Object} statusMapping - Status mapping rules
 * @param {Object} retryConfig - Retry configuration
 * @param {string} projectEntryId - Project entry ID (optional)
 * @param {string} sprintEntryId - Sprint entry ID (optional)
 * @param {Array<string>} dependencyTaskIds - Array of Notion task IDs for dependencies (optional)
 * @returns {Promise<{success: boolean, data?: Object, error?: string}>}
 */
async function createNotionTaskWithRetry(notionToken, tasksDbId, issue, githubRepoUrl, statusMapping, retryConfig, projectEntryId = null, sprintEntryId = null, dependencyTaskIds = null) {
  const { retryAttempts = 3, retryBackoff = [1000, 2000, 4000] } = retryConfig;

  const notionStatus = mapGitHubStateToNotion(issue.state, statusMapping);

  const taskData = {
    parent: {
      database_id: tasksDbId
    },
    properties: {
      'Task ID': {
        title: [
          {
            text: {
              content: issue.title
            }
          }
        ]
      },
      'Status': {
        select: {
          name: notionStatus
        }
      },
      'GitHub Issue': {
        url: issue.url
      },
      'Priority': {
        number: 5
      }
    }
  };

  // Add Project relation if projectEntryId is provided
  if (projectEntryId) {
    taskData.properties['Project'] = {
      relation: [{ id: projectEntryId }]
    };
  }

  // Add Sprint ID relation if sprintEntryId is provided
  if (sprintEntryId) {
    taskData.properties['Sprint ID'] = {
      relation: [{ id: sprintEntryId }]
    };
  }

  // Add Dependencies relation if dependencyTaskIds are provided
  if (dependencyTaskIds && dependencyTaskIds.length > 0) {
    taskData.properties['Dependencies'] = {
      relation: dependencyTaskIds.map(id => ({ id }))
    };
  }

  // Add dates if available
  if (issue.createdAt) {
    taskData.properties['Started At'] = {
      date: {
        start: issue.createdAt
      }
    };
  }

  if (issue.state === 'closed' && issue.updatedAt) {
    taskData.properties['Completed At'] = {
      date: {
        start: issue.updatedAt
      }
    };
  }

  // Retry logic with exponential backoff
  for (let attempt = 0; attempt <= retryAttempts; attempt++) {
    try {
      const result = await notionApiRequest(notionToken, 'POST', '/v1/pages', taskData);
      return { success: true, data: result, taskId: result.id };
    } catch (error) {
      const isRateLimitError = error.message.includes('429');
      const isServerError = error.message.match(/\b5\d{2}\b/);

      if ((isRateLimitError || isServerError) && attempt < retryAttempts) {
        const delay = retryBackoff[attempt] || retryBackoff[retryBackoff.length - 1];
        console.log(`  Retry attempt ${attempt + 1}/${retryAttempts} in ${delay}ms...`);
        await sleep(delay);
        continue;
      }

      return { success: false, error: error.message };
    }
  }

  return { success: false, error: 'Max retries exceeded' };
}

/**
 * Sleep helper for retry delays
 * @param {number} ms - Milliseconds to sleep
 * @returns {Promise<void>}
 */
function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Update sync state in local storage
 * Note: MCP storage should be handled by calling command context
 *
 * @param {string} projectSlug - Project slug
 * @param {Object} syncResult - Sync result data
 * @returns {string} Path to saved sync state file
 */
function updateSyncState(projectSlug, syncResult) {
  const stateDir = path.join(
    process.env.HOME || process.env.USERPROFILE,
    '.claude', 'plugins', 'bumba-notion', 'state'
  );

  if (!fs.existsSync(stateDir)) {
    fs.mkdirSync(stateDir, { recursive: true });
  }

  const syncStatePath = path.join(stateDir, `sync-${projectSlug}.json`);

  let syncState = {
    projectSlug: projectSlug,
    projectName: syncResult.projectName,
    githubRepo: syncResult.githubRepo,
    dashboardPageId: syncResult.dashboardPageId,
    syncHistory: [],
    stats: {
      totalSyncs: 0,
      totalIssuesCreated: 0,
      lastError: null
    },
    errors: []
  };

  // Load existing state if present
  if (fs.existsSync(syncStatePath)) {
    try {
      syncState = JSON.parse(fs.readFileSync(syncStatePath, 'utf8'));
    } catch (error) {
      console.error('Failed to load existing sync state:', error.message);
    }
  }

  // Add new sync entry to history
  const syncEntry = {
    timestamp: new Date().toISOString(),
    totalIssues: syncResult.totalIssues,
    created: syncResult.createdCount,
    skipped: syncResult.skippedCount,
    errors: syncResult.errorCount,
    duration: syncResult.duration,
    success: syncResult.errorCount === 0
  };

  syncState.syncHistory.push(syncEntry);
  syncState.lastSync = syncEntry.timestamp;
  syncState.stats.totalSyncs++;
  syncState.stats.totalIssuesCreated += syncResult.createdCount;

  if (syncResult.errorCount > 0) {
    syncState.stats.lastError = syncEntry.timestamp;
    syncState.errors = syncState.errors.concat(syncResult.errors || []);
  }

  // Keep only last 10 sync history entries
  if (syncState.syncHistory.length > 10) {
    syncState.syncHistory = syncState.syncHistory.slice(-10);
  }

  // Keep only last 20 errors
  if (syncState.errors.length > 20) {
    syncState.errors = syncState.errors.slice(-20);
  }

  fs.writeFileSync(syncStatePath, JSON.stringify(syncState, null, 2));

  return syncStatePath;
}

/**
 * Fetch GitHub milestones for a repository using gh CLI
 * @param {string} owner - Repository owner
 * @param {string} repo - Repository name
 * @returns {Array} Array of milestone objects
 */
function fetchGitHubMilestones(owner, repo) {
  try {
    const command = `gh api repos/${owner}/${repo}/milestones --paginate --jq '.[] | {number, title, state, html_url, due_on, created_at, description}'`;

    const output = execSync(command, { encoding: 'utf8' });

    // Parse line-delimited JSON (gh api with --jq returns one JSON object per line)
    const lines = output.trim().split('\n').filter(line => line.trim());
    const milestones = lines.map(line => JSON.parse(line));

    return milestones;
  } catch (error) {
    if (error.message.includes('gh: command not found')) {
      throw new Error('GitHub CLI (gh) not found. Please install: https://cli.github.com/');
    }
    throw new Error(`Failed to fetch milestones: ${error.message}`);
  }
}

/**
 * Check if Sprint already exists in Notion for a given GitHub milestone
 * @param {string} notionToken - Notion API token
 * @param {string} sprintsDbId - Sprints database ID
 * @param {string} milestoneUrl - GitHub milestone URL
 * @returns {Promise<Object|null>} Existing sprint or null
 */
async function checkDuplicateSprint(notionToken, sprintsDbId, milestoneUrl) {
  const query = {
    filter: {
      property: 'GitHub Milestone URL',
      url: {
        equals: milestoneUrl
      }
    }
  };

  const result = await notionApiRequest(notionToken, 'POST', `/v1/databases/${sprintsDbId}/query`, query);

  if (result.results && result.results.length > 0) {
    return result.results[0];
  }

  return null;
}

/**
 * Create or update Notion Sprint from GitHub Milestone
 * @param {string} notionToken - Notion API token
 * @param {string} sprintsDbId - Sprints database ID
 * @param {Object} milestone - GitHub milestone object
 * @param {string} epicEntryId - Epic entry ID to link to
 * @param {string} projectEntryId - Project entry ID to link to
 * @returns {Promise<{success: boolean, data?: Object, error?: string, action?: string}>}
 */
async function syncNotionSprint(notionToken, sprintsDbId, milestone, epicEntryId, projectEntryId) {
  try {
    const milestoneUrl = milestone.html_url;

    // Check if sprint already exists
    const existingSprint = await checkDuplicateSprint(notionToken, sprintsDbId, milestoneUrl);

    const sprintData = {
      properties: {
        'Sprint ID': {
          title: [
            {
              text: {
                content: milestone.title
              }
            }
          ]
        },
        'Epic': {
          relation: [{ id: epicEntryId }]
        },
        'Project': {
          relation: [{ id: projectEntryId }]
        },
        'GitHub Milestone URL': {
          url: milestoneUrl
        },
        'Status': {
          select: {
            name: milestone.state === 'open' ? 'active' : 'completed'
          }
        }
      }
    };

    // Add dates if available
    if (milestone.due_on) {
      sprintData.properties['End Date'] = {
        date: {
          start: milestone.due_on.split('T')[0]
        }
      };
    }

    if (milestone.created_at) {
      sprintData.properties['Start Date'] = {
        date: {
          start: milestone.created_at.split('T')[0]
        }
      };
    }

    if (existingSprint) {
      // Update existing sprint
      const updated = await notionApiRequest(
        notionToken,
        'PATCH',
        `/v1/pages/${existingSprint.id}`,
        sprintData
      );

      return {
        success: true,
        data: updated,
        action: 'updated',
        sprintId: existingSprint.id
      };
    } else {
      // Create new sprint
      sprintData.parent = {
        database_id: sprintsDbId
      };

      const created = await notionApiRequest(
        notionToken,
        'POST',
        '/v1/pages',
        sprintData
      );

      return {
        success: true,
        data: created,
        action: 'created',
        sprintId: created.id
      };
    }
  } catch (error) {
    return {
      success: false,
      error: error.message,
      milestoneNumber: milestone.number
    };
  }
}

/**
 * Format sync summary for display
 * @param {Object} syncResult - Sync result data
 * @returns {string} Formatted summary
 */
function formatSyncSummary(syncResult) {
  let summary = `✅ GitHub sync complete: ${syncResult.githubRepo}\n\n`;
  summary += `📊 Sync Summary:\n`;
  summary += `  • Found: ${syncResult.totalIssues} open issues\n`;
  summary += `  • Created: ${syncResult.createdCount} new tasks\n`;
  summary += `  • Skipped: ${syncResult.skippedCount} existing tasks\n`;
  summary += `  • Errors: ${syncResult.errorCount}\n\n`;
  summary += `🔗 View in Notion: ${syncResult.dashboardUrl}\n`;

  if (syncResult.errors && syncResult.errors.length > 0) {
    summary += `\n⚠️ Errors encountered:\n`;
    syncResult.errors.forEach(err => {
      summary += `  • Issue #${err.issueNumber}: ${err.error}\n`;
    });
    summary += `\n💡 Tip: Tasks with errors were not created. You can:\n`;
    summary += `  1. Check error messages above\n`;
    summary += `  2. Fix issues in GitHub\n`;
    summary += `  3. Run /sync-github again to retry\n`;
  }

  if (syncResult.createdCount > 0) {
    summary += `\n✨ ${syncResult.createdCount} task${syncResult.createdCount > 1 ? 's' : ''} added to your Notion dashboard!\n`;
    summary += `   Tasks are filtered by GitHub Repo: ${syncResult.githubRepo}\n`;
  }

  summary += `\nLast sync: ${new Date().toISOString()}\n`;
  summary += `Duration: ${(syncResult.duration / 1000).toFixed(1)}s\n`;

  return summary;
}

/**
 * Parse dependencies from GitHub issue body
 * Supports formats: "Depends on #123", "Blocked by #456", "Requires #789"
 *
 * @param {string} issueBody - GitHub issue body text
 * @param {string} githubRepoUrl - Base GitHub repository URL
 * @returns {Array<string>} Array of GitHub issue URLs that are dependencies
 */
function parseDependencies(issueBody, githubRepoUrl) {
  if (!issueBody) {
    return [];
  }

  const dependencyPatterns = [
    /depends on #(\d+)/gi,
    /blocked by #(\d+)/gi,
    /requires #(\d+)/gi
  ];

  const dependencyNumbers = new Set();

  for (const pattern of dependencyPatterns) {
    const matches = issueBody.matchAll(pattern);
    for (const match of matches) {
      dependencyNumbers.add(parseInt(match[1], 10));
    }
  }

  // Convert issue numbers to full GitHub URLs
  const baseUrl = githubRepoUrl.replace(/\/$/, ''); // Remove trailing slash
  return Array.from(dependencyNumbers).map(num => `${baseUrl}/issues/${num}`);
}

/**
 * Find Notion task IDs by GitHub issue URLs
 *
 * @param {string} notionToken - Notion API token
 * @param {string} tasksDbId - Tasks database ID
 * @param {Array<string>} githubUrls - Array of GitHub issue URLs to look up
 * @returns {Promise<Array<string>>} Array of Notion page IDs for found tasks
 */
async function findTasksByGitHubUrls(notionToken, tasksDbId, githubUrls) {
  if (!githubUrls || githubUrls.length === 0) {
    return [];
  }

  const foundTaskIds = [];

  for (const url of githubUrls) {
    try {
      // Query Notion for task with this GitHub URL
      const filter = {
        property: 'GitHub Issue',
        url: {
          equals: url
        }
      };

      const response = await notionApiRequest(
        notionToken,
        'POST',
        `/v1/databases/${tasksDbId}/query`,
        {
          filter: filter,
          page_size: 1
        }
      );

      if (response.results && response.results.length > 0) {
        foundTaskIds.push(response.results[0].id);
      } else {
        console.log(`  ⚠️  Dependency not found in Notion: ${url}`);
      }
    } catch (error) {
      console.log(`  ⚠️  Failed to look up dependency ${url}: ${error.message}`);
    }
  }

  return foundTaskIds;
}

/**
 * Update a Notion task with dependencies
 * @param {string} notionToken - Notion API token
 * @param {string} taskId - Notion task page ID to update
 * @param {Array<string>} dependencyTaskIds - Array of Notion task IDs for dependencies
 * @returns {Promise<{success: boolean, error?: string}>}
 */
async function updateTaskDependencies(notionToken, taskId, dependencyTaskIds) {
  if (!dependencyTaskIds || dependencyTaskIds.length === 0) {
    return { success: true };
  }

  try {
    const updateData = {
      properties: {
        'Dependencies': {
          relation: dependencyTaskIds.map(id => ({ id }))
        }
      }
    };

    await notionApiRequest(
      notionToken,
      'PATCH',
      `/v1/pages/${taskId}`,
      updateData
    );

    return { success: true };
  } catch (error) {
    return { success: false, error: error.message };
  }
}

module.exports = {
  loadConfig,
  parseGitHubUrl,
  findProjectMetadata,
  fetchGitHubIssues,
  fetchGitHubMilestones,
  checkDuplicateTask,
  checkDuplicateSprint,
  mapGitHubStateToNotion,
  createNotionTaskWithRetry,
  syncNotionSprint,
  updateSyncState,
  formatSyncSummary,
  notionApiRequest,
  parseDependencies,
  findTasksByGitHubUrls,
  updateTaskDependencies
};

/**
 * Bumba Sandbox MCP Server
 * Main MCP server implementing multi-agent orchestration with cloud sandboxes
 *
 * Architecture adapted from agent-sandboxes server.py:
 * - FastMCP-style tool registration pattern
 * - Stdio transport for Claude Desktop integration
 * - Tool categories: lifecycle, files, commands, orchestration, metadata
 * - Hook system integration for security and observability
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  Tool,
} from '@modelcontextprotocol/sdk/types.js';
import * as os from 'os';
import * as path from 'path';
import { loadConfig, loadState, saveState } from './utils.js';
import { initializeLogManager, getLogManager } from './logger.js';
import { BumbaSandboxConfig, OrchestratorState, HookType, HookTypeStats } from './types.js';
import * as sandboxLifecycle from '../tools/sandbox-lifecycle.js';
import * as fileOps from '../tools/file-operations.js';
import * as commandExec from '../tools/command-execution.js';
import * as depAnalysis from '../tools/analyze-dependencies.js';
import * as orchestration from '../tools/orchestration.js';
import { initializeGitHub } from './github.js';

// ============================================================================
// Server Configuration
// ============================================================================

const SERVER_NAME = 'bumba-sandbox';
const SERVER_VERSION = '1.0.0';

// ============================================================================
// Global State
// ============================================================================

let config: BumbaSandboxConfig;
let state: OrchestratorState;
let configPath: string;
let statePath: string;
let logsDir: string;

// ============================================================================
// Tool Registry
// ============================================================================

interface ToolDefinition {
  name: string;
  description: string;
  inputSchema: {
    type: string;
    properties: Record<string, any>;
    required?: string[];
  };
  handler: (args: any) => Promise<any>;
}

const tools: Map<string, ToolDefinition> = new Map();

/**
 * Register a tool with the MCP server
 */
function registerTool(tool: ToolDefinition): void {
  tools.set(tool.name, tool);
}

// ============================================================================
// Lifecycle Management Tools
// ============================================================================

registerTool({
  name: 'sandbox_init',
  description: 'Initialize a new sandbox with optional template',
  inputSchema: {
    type: 'object',
    properties: {
      template: {
        type: 'string',
        description: 'Sandbox template (e.g., "node", "python", "base")',
      },
      timeout: {
        type: 'number',
        description: 'Sandbox timeout in seconds (default: 3600)',
      },
    },
  },
  handler: async (args) => {
    return await sandboxLifecycle.sandboxInit(args as sandboxLifecycle.SandboxInitArgs);
  },
});

registerTool({
  name: 'sandbox_create',
  description: 'Create a new sandbox with advanced configuration',
  inputSchema: {
    type: 'object',
    properties: {
      template: { type: 'string', description: 'Sandbox template' },
      timeout: { type: 'number', description: 'Timeout in seconds' },
      metadata: { type: 'object', description: 'Custom metadata' },
      env: { type: 'object', description: 'Environment variables' },
    },
  },
  handler: async (args) => {
    return await sandboxLifecycle.sandboxCreate(args as sandboxLifecycle.SandboxCreateArgs);
  },
});

registerTool({
  name: 'sandbox_connect',
  description: 'Connect to an existing sandbox by ID',
  inputSchema: {
    type: 'object',
    properties: {
      sandboxId: {
        type: 'string',
        description: 'Existing sandbox ID',
      },
    },
    required: ['sandboxId'],
  },
  handler: async (args) => {
    return await sandboxLifecycle.sandboxConnect(args as sandboxLifecycle.SandboxConnectArgs);
  },
});

registerTool({
  name: 'sandbox_kill',
  description: 'Terminate and cleanup a sandbox',
  inputSchema: {
    type: 'object',
    properties: {
      sandboxId: {
        type: 'string',
        description: 'Sandbox ID to terminate',
      },
    },
    required: ['sandboxId'],
  },
  handler: async (args) => {
    return await sandboxLifecycle.sandboxKill(args as sandboxLifecycle.SandboxKillArgs);
  },
});

registerTool({
  name: 'sandbox_status',
  description: 'Get status and health information for a sandbox',
  inputSchema: {
    type: 'object',
    properties: {
      sandboxId: {
        type: 'string',
        description: 'Sandbox ID to check',
      },
    },
    required: ['sandboxId'],
  },
  handler: async (args) => {
    return await sandboxLifecycle.sandboxStatus(args as sandboxLifecycle.SandboxStatusArgs);
  },
});

// ============================================================================
// File Operation Tools
// ============================================================================

registerTool({
  name: 'files_list',
  description: 'List files and directories in a sandbox path',
  inputSchema: {
    type: 'object',
    properties: {
      sandboxId: { type: 'string', description: 'Sandbox ID' },
      path: { type: 'string', description: 'Directory path (default: "/")' },
    },
    required: ['sandboxId'],
  },
  handler: async (args) => {
    return await fileOps.filesList(args as fileOps.FilesListArgs);
  },
});

registerTool({
  name: 'files_read',
  description: 'Read a text file from sandbox',
  inputSchema: {
    type: 'object',
    properties: {
      sandboxId: { type: 'string', description: 'Sandbox ID' },
      path: { type: 'string', description: 'File path' },
    },
    required: ['sandboxId', 'path'],
  },
  handler: async (args) => {
    return await fileOps.filesRead(args as fileOps.FilesReadArgs);
  },
});

registerTool({
  name: 'files_write',
  description: 'Write a text file to sandbox',
  inputSchema: {
    type: 'object',
    properties: {
      sandboxId: { type: 'string', description: 'Sandbox ID' },
      path: { type: 'string', description: 'File path' },
      content: { type: 'string', description: 'File content' },
    },
    required: ['sandboxId', 'path', 'content'],
  },
  handler: async (args) => {
    return await fileOps.filesWrite(args as fileOps.FilesWriteArgs);
  },
});

registerTool({
  name: 'files_upload',
  description: 'Upload a binary file to sandbox',
  inputSchema: {
    type: 'object',
    properties: {
      sandboxId: { type: 'string', description: 'Sandbox ID' },
      path: { type: 'string', description: 'File path' },
      content: { type: 'string', description: 'Base64 encoded content' },
    },
    required: ['sandboxId', 'path', 'content'],
  },
  handler: async (args) => {
    return await fileOps.filesUpload(args as fileOps.FilesUploadArgs);
  },
});

registerTool({
  name: 'files_download',
  description: 'Download a binary file from sandbox',
  inputSchema: {
    type: 'object',
    properties: {
      sandboxId: { type: 'string', description: 'Sandbox ID' },
      path: { type: 'string', description: 'File path' },
    },
    required: ['sandboxId', 'path'],
  },
  handler: async (args) => {
    return await fileOps.filesDownload(args as fileOps.FilesDownloadArgs);
  },
});

registerTool({
  name: 'file_exists',
  description: 'Check if a file or directory exists',
  inputSchema: {
    type: 'object',
    properties: {
      sandboxId: { type: 'string', description: 'Sandbox ID' },
      path: { type: 'string', description: 'File or directory path' },
    },
    required: ['sandboxId', 'path'],
  },
  handler: async (args) => {
    return await fileOps.fileExists(args as fileOps.FileExistsArgs);
  },
});

registerTool({
  name: 'file_info',
  description: 'Get file or directory metadata',
  inputSchema: {
    type: 'object',
    properties: {
      sandboxId: { type: 'string', description: 'Sandbox ID' },
      path: { type: 'string', description: 'File or directory path' },
    },
    required: ['sandboxId', 'path'],
  },
  handler: async (args) => {
    return await fileOps.fileInfo(args as fileOps.FileInfoArgs);
  },
});

registerTool({
  name: 'file_remove',
  description: 'Remove a file or directory',
  inputSchema: {
    type: 'object',
    properties: {
      sandboxId: { type: 'string', description: 'Sandbox ID' },
      path: { type: 'string', description: 'File or directory path' },
    },
    required: ['sandboxId', 'path'],
  },
  handler: async (args) => {
    return await fileOps.fileRemove(args as fileOps.FileRemoveArgs);
  },
});

registerTool({
  name: 'file_rename',
  description: 'Rename or move a file',
  inputSchema: {
    type: 'object',
    properties: {
      sandboxId: { type: 'string', description: 'Sandbox ID' },
      oldPath: { type: 'string', description: 'Current file path' },
      newPath: { type: 'string', description: 'New file path' },
    },
    required: ['sandboxId', 'oldPath', 'newPath'],
  },
  handler: async (args) => {
    return await fileOps.fileRename(args as fileOps.FileRenameArgs);
  },
});

registerTool({
  name: 'make_directory',
  description: 'Create a directory (including parent directories)',
  inputSchema: {
    type: 'object',
    properties: {
      sandboxId: { type: 'string', description: 'Sandbox ID' },
      path: { type: 'string', description: 'Directory path' },
    },
    required: ['sandboxId', 'path'],
  },
  handler: async (args) => {
    return await fileOps.makeDirectory(args as fileOps.MakeDirectoryArgs);
  },
});

// ============================================================================
// Command Execution Tool
// ============================================================================

registerTool({
  name: 'execute_command',
  description: 'Execute a command in the sandbox with full control',
  inputSchema: {
    type: 'object',
    properties: {
      sandboxId: { type: 'string', description: 'Sandbox ID' },
      command: { type: 'string', description: 'Command to execute' },
      shell: { type: 'string', description: 'Shell to use (default: /bin/bash)' },
      root: { type: 'boolean', description: 'Run with root privileges' },
      env: { type: 'object', description: 'Environment variables' },
      cwd: { type: 'string', description: 'Working directory' },
      timeout: { type: 'number', description: 'Timeout in seconds (default: 60)' },
      background: { type: 'boolean', description: 'Run in background' },
    },
    required: ['sandboxId', 'command'],
  },
  handler: async (args) => {
    return await commandExec.executeCommand(args as commandExec.ExecuteCommandArgs);
  },
});

// ============================================================================
// Orchestration Tools
// ============================================================================

registerTool({
  name: 'analyze_dependencies',
  description: 'Analyze GitHub issue dependencies and build dependency graph',
  inputSchema: {
    type: 'object',
    properties: {
      owner: { type: 'string', description: 'GitHub repository owner' },
      repo: { type: 'string', description: 'GitHub repository name' },
      issues: {
        type: 'array',
        items: { type: 'number' },
        description: 'Array of issue numbers to analyze',
      },
    },
    required: ['owner', 'repo', 'issues'],
  },
  handler: async (args) => {
    return await depAnalysis.analyzeDependencies(args as depAnalysis.AnalyzeDependenciesArgs);
  },
});

registerTool({
  name: 'plan_sandbox_allocation',
  description: 'Plan sandbox allocation with different strategies (max-speed, cost-optimized, balanced)',
  inputSchema: {
    type: 'object',
    properties: {
      readyIssues: {
        type: 'array',
        items: { type: 'number' },
        description: 'Array of ready issue numbers',
      },
      maxConcurrent: { type: 'number', description: 'Max concurrent sandboxes' },
      budgetLimit: { type: 'number', description: 'Budget limit in dollars' },
      strategy: {
        type: 'string',
        description: 'Allocation strategy (max-speed, cost-optimized, balanced)',
      },
    },
    required: ['readyIssues', 'maxConcurrent', 'budgetLimit'],
  },
  handler: async (args) => {
    return await orchestration.planSandboxAllocation(args as orchestration.PlanSandboxAllocationArgs);
  },
});

registerTool({
  name: 'spawn_sandbox_agent',
  description: 'Spawn a sandbox agent for an issue (placeholder)',
  inputSchema: {
    type: 'object',
    properties: {
      issueNumber: { type: 'number', description: 'Issue number' },
      worktreePath: { type: 'string', description: 'Path to git worktree' },
      template: { type: 'string', description: 'Sandbox template' },
    },
    required: ['issueNumber'],
  },
  handler: async (args) => {
    return await orchestration.spawnSandboxAgent(args as orchestration.SpawnSandboxAgentArgs);
  },
});

registerTool({
  name: 'monitor_agents',
  description: 'Monitor all active agents and get summary statistics',
  inputSchema: {
    type: 'object',
    properties: {
      filter: {
        type: 'object',
        description: 'Filter options',
      },
    },
  },
  handler: async (args) => {
    return await orchestration.monitorAgents(args as orchestration.MonitorAgentsArgs);
  },
});

registerTool({
  name: 'handle_agent_event',
  description: 'Handle agent events and trigger auto-spawn (placeholder)',
  inputSchema: {
    type: 'object',
    properties: {
      agentId: { type: 'string', description: 'Agent ID' },
      event: {
        type: 'object',
        description: 'Event data',
      },
    },
    required: ['agentId', 'event'],
  },
  handler: async (args) => {
    return await orchestration.handleAgentEvent(args as orchestration.HandleAgentEventArgs);
  },
});

registerTool({
  name: 'optimize_resources',
  description: 'Analyze resource usage and provide optimization recommendations',
  inputSchema: {
    type: 'object',
    properties: {
      criteria: {
        type: 'string',
        description: 'Optimization criteria (cost, performance, balanced)',
      },
    },
  },
  handler: async (args) => {
    return await orchestration.optimizeResources(args as orchestration.OptimizeResourcesArgs);
  },
});

registerTool({
  name: 'get_cost_tracking',
  description: 'Get cost tracking information from hook logs',
  inputSchema: {
    type: 'object',
    properties: {},
  },
  handler: async () => {
    return await orchestration.getCostTracking();
  },
});

// ============================================================================
// MCP Server Setup
// ============================================================================

const server = new Server(
  {
    name: SERVER_NAME,
    version: SERVER_VERSION,
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

/**
 * List all available tools
 */
server.setRequestHandler(ListToolsRequestSchema, async () => {
  const toolsList: Tool[] = Array.from(tools.values()).map((tool) => ({
    name: tool.name,
    description: tool.description,
    inputSchema: tool.inputSchema as { type: "object"; properties?: { [x: string]: object }; required?: string[] },
  }));

  return { tools: toolsList };
});

/**
 * Handle tool execution requests
 */
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  const tool = tools.get(name);
  if (!tool) {
    throw new Error(`Unknown tool: ${name}`);
  }

  try {
    const result = await tool.handler(args || {});
    return {
      content: [
        {
          type: 'text',
          text: JSON.stringify(result, null, 2),
        },
      ],
    };
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : String(error);
    return {
      content: [
        {
          type: 'text',
          text: JSON.stringify(
            {
              error: errorMessage,
              tool: name,
            },
            null,
            2
          ),
        },
      ],
      isError: true,
    };
  }
});

// ============================================================================
// Server Lifecycle
// ============================================================================

/**
 * Initialize server configuration and state
 */
async function initialize(): Promise<void> {
  const homeDir = process.env.HOME || os.homedir();
  const baseDir = path.join(homeDir, '.claude/apps/sandbox_agent_working_dir');
  configPath = path.join(homeDir, '.claude/config/bumba-sandbox-config.json');
  statePath = path.join(baseDir, 'orchestrator-state.json');
  logsDir = path.join(baseDir, 'logs');

  // Load configuration
  config = await loadConfig(configPath);

  // Load or initialize state
  try {
    const loadedState = await loadState(statePath);
    if (loadedState) {
      state = loadedState;
    } else {
      throw new Error('State file returned null');
    }
  } catch (error) {
    // Initialize new state if file doesn't exist
    const now = new Date().toISOString();
    const hookStats: Record<HookType, HookTypeStats> = {
      PreToolUse: { count: 0, blocked: 0, errors: 0 },
      PostToolUse: { count: 0, blocked: 0, errors: 0 },
      UserPromptSubmit: { count: 0, blocked: 0, errors: 0 },
      Stop: { count: 0, blocked: 0, errors: 0 },
      SubagentStop: { count: 0, blocked: 0, errors: 0 },
      PreCompact: { count: 0, blocked: 0, errors: 0 },
    };

    state = {
      session: {
        id: `session-${Date.now()}`,
        startedAt: now,
        updatedAt: now,
        strategy: 'balanced',
        status: 'active',
      },
      issues: {},
      agents: {},
      sandboxes: {},
      resources: {
        current: {
          activeSandboxes: 0,
          activeAgents: 0,
          totalCost: 0,
        },
        limits: {
          maxConcurrentSandboxes: config.sandboxDefaults.maxConcurrent,
          budgetLimit: config.costManagement.budgetLimit,
        },
        budget: {
          period: config.costManagement.trackingPeriod,
          periodStart: now,
          spent: 0,
          remaining: config.costManagement.budgetLimit,
          percentUsed: 0,
        },
      },
      events: [],
      hooks: {
        totalExecutions: 0,
        byType: hookStats,
        recentBlocks: [],
      },
    };
    await saveState(state, statePath);
  }

  // Initialize logging
  initializeLogManager(logsDir);

  // Initialize GitHub if token is available
  const githubToken = process.env.GITHUB_TOKEN;
  if (githubToken) {
    initializeGitHub(githubToken);
    console.error(`[${SERVER_NAME}] GitHub client initialized`);
  } else {
    console.error(`[${SERVER_NAME}] Warning: GitHub token not found, analyze_dependencies will not work`);
  }

  console.error(`[${SERVER_NAME}] Initialized successfully`);
  console.error(`[${SERVER_NAME}] Config: ${configPath}`);
  console.error(`[${SERVER_NAME}] State: ${statePath}`);
  console.error(`[${SERVER_NAME}] Logs: ${logsDir}`);
  console.error(`[${SERVER_NAME}] Registered ${tools.size} tools`);
}

/**
 * Graceful shutdown
 */
async function shutdown(): Promise<void> {
  console.error(`[${SERVER_NAME}] Shutting down...`);

  // Save final state
  try {
    await saveState(state, statePath);
    console.error(`[${SERVER_NAME}] State saved`);
  } catch (error) {
    console.error(`[${SERVER_NAME}] Error saving state:`, error);
  }

  // Close all loggers
  try {
    const logManager = getLogManager();
    await logManager.closeAll();
    console.error(`[${SERVER_NAME}] Loggers closed`);
  } catch (error) {
    console.error(`[${SERVER_NAME}] Error closing loggers:`, error);
  }

  console.error(`[${SERVER_NAME}] Shutdown complete`);
}

// ============================================================================
// Main Entry Point
// ============================================================================

async function main(): Promise<void> {
  try {
    // Initialize server
    await initialize();

    // Setup stdio transport
    const transport = new StdioServerTransport();

    // Connect server to transport
    await server.connect(transport);

    console.error(`[${SERVER_NAME}] Server running on stdio`);

    // Handle shutdown signals
    process.on('SIGINT', async () => {
      await shutdown();
      process.exit(0);
    });

    process.on('SIGTERM', async () => {
      await shutdown();
      process.exit(0);
    });
  } catch (error) {
    console.error(`[${SERVER_NAME}] Fatal error:`, error);
    process.exit(1);
  }
}

// Start server
main().catch((error) => {
  console.error(`[${SERVER_NAME}] Unhandled error:`, error);
  process.exit(1);
});

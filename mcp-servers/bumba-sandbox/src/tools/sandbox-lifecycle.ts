/**
 * Sandbox Lifecycle Management Tools
 * Adapted from agent-sandboxes MCP server lifecycle tools
 *
 * Provides 5 core operations:
 * - sandbox_init: Initialize a new sandbox with template
 * - sandbox_create: Create sandbox with advanced config
 * - sandbox_connect: Connect to existing sandbox
 * - sandbox_kill: Terminate and cleanup sandbox
 * - sandbox_status: Get sandbox health information
 *
 * Memory Bridge Integration:
 * - On spawn: Syncs context from shared memory to sandbox
 * - On kill: Syncs results from sandbox back to shared memory
 */

import { Sandbox } from 'e2b';
import { SandboxState } from '../mcp-servers/types.js';

// ============================================================================
// Memory Bridge Configuration
// ============================================================================

const MEMORY_BRIDGE_URL = process.env.MEMORY_BRIDGE_URL || 'http://127.0.0.1:3847';
const MEMORY_BRIDGE_ENABLED = process.env.MEMORY_BRIDGE_ENABLED !== 'false';

/**
 * Sync context INTO sandbox from shared memory (called before spawn)
 */
async function syncMemoryIn(sandboxId: string, contextKeys: string[] = []): Promise<any> {
  if (!MEMORY_BRIDGE_ENABLED) {
    return { skipped: true, reason: 'Memory bridge disabled' };
  }

  try {
    const response = await fetch(`${MEMORY_BRIDGE_URL}/sync-in`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        sandboxId,
        contextKeys,
        includeTeamStatus: true
      }),
      signal: AbortSignal.timeout(5000) // 5 second timeout
    });

    if (!response.ok) {
      console.warn(`Memory sync-in failed: ${response.status}`);
      return { skipped: true, reason: `HTTP ${response.status}` };
    }

    return await response.json();
  } catch (error: any) {
    console.warn(`Memory sync-in error: ${error.message}`);
    return { skipped: true, reason: error.message };
  }
}

/**
 * Sync context OUT from sandbox to shared memory (called before kill)
 */
async function syncMemoryOut(
  sandboxId: string,
  sandbox: Sandbox
): Promise<any> {
  if (!MEMORY_BRIDGE_ENABLED) {
    return { skipped: true, reason: 'Memory bridge disabled' };
  }

  try {
    // Try to read sandbox summary file if it exists
    let summary = null;
    let artifacts: any[] = [];
    let decisions: any[] = [];
    let contexts: Record<string, any> = {};

    try {
      const summaryContent = await sandbox.files.read('/workspace/.bumba-summary.json');
      const parsed = JSON.parse(summaryContent);
      summary = parsed.summary;
      artifacts = parsed.artifacts || [];
      decisions = parsed.decisions || [];
      contexts = parsed.contexts || {};
    } catch {
      // Summary file doesn't exist, create a minimal summary
      summary = {
        sandboxId,
        endedAt: new Date().toISOString(),
        status: 'completed-no-summary'
      };
    }

    // Try to read any notes files
    try {
      const noteFiles = await sandbox.files.list('/workspace/.bumba-notes');
      for (const file of noteFiles || []) {
        if (file.name.endsWith('.json')) {
          try {
            const content = await sandbox.files.read(`/workspace/.bumba-notes/${file.name}`);
            const note = JSON.parse(content);
            if (note.type === 'artifact') artifacts.push(note);
            if (note.type === 'decision') decisions.push(note);
            if (note.type === 'context') contexts[note.key] = note.value;
          } catch {
            // Skip malformed files
          }
        }
      }
    } catch {
      // Notes directory doesn't exist
    }

    // Send to memory bridge
    const response = await fetch(`${MEMORY_BRIDGE_URL}/sync-out`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        sandboxId,
        summary,
        artifacts,
        decisions,
        contexts
      }),
      signal: AbortSignal.timeout(10000) // 10 second timeout
    });

    if (!response.ok) {
      console.warn(`Memory sync-out failed: ${response.status}`);
      return { skipped: true, reason: `HTTP ${response.status}` };
    }

    return await response.json();
  } catch (error: any) {
    console.warn(`Memory sync-out error: ${error.message}`);
    return { skipped: true, reason: error.message };
  }
}

/**
 * Write context file to sandbox for agent to read
 */
async function writeContextToSandbox(sandbox: Sandbox, context: any): Promise<void> {
  try {
    await sandbox.files.write(
      '/workspace/.bumba-context.json',
      JSON.stringify(context, null, 2)
    );

    // Create notes directory
    await sandbox.commands.run('mkdir -p /workspace/.bumba-notes');
  } catch (error: any) {
    console.warn(`Failed to write context to sandbox: ${error.message}`);
  }
}

// ============================================================================
// Active Sandboxes Registry
// ============================================================================

const activeSandboxes: Map<string, Sandbox> = new Map();

/**
 * Register an active sandbox
 */
export function registerSandbox(sandboxId: string, sandbox: Sandbox): void {
  activeSandboxes.set(sandboxId, sandbox);
}

/**
 * Get a registered sandbox
 */
export function getSandbox(sandboxId: string): Sandbox | undefined {
  return activeSandboxes.get(sandboxId);
}

/**
 * Unregister a sandbox
 */
export function unregisterSandbox(sandboxId: string): void {
  activeSandboxes.delete(sandboxId);
}

/**
 * Get all active sandbox IDs
 */
export function getActiveSandboxIds(): string[] {
  return Array.from(activeSandboxes.keys());
}

// ============================================================================
// Sandbox Init - Simple template-based initialization
// ============================================================================

export interface SandboxInitArgs {
  template?: string;
  timeout?: number;
  contextKeys?: string[]; // Memory context keys to sync in
}

export interface SandboxInitResult {
  sandboxId: string;
  template: string;
  status: string;
  url: string | null;
  memorySync?: any; // Memory sync result
}

/**
 * Initialize a new sandbox with optional template
 * This is the simplest way to create a sandbox
 *
 * Memory Bridge Integration:
 * - Syncs context from shared memory before agent starts
 * - Writes context to /workspace/.bumba-context.json
 */
export async function sandboxInit(args: SandboxInitArgs): Promise<SandboxInitResult> {
  const { template = 'base', timeout = 3600, contextKeys = [] } = args;

  // Validate template
  const validTemplates = ['base', 'node', 'python', 'go', 'rust', 'java'];
  if (!validTemplates.includes(template)) {
    throw new Error(`Invalid template: ${template}. Valid templates: ${validTemplates.join(', ')}`);
  }

  // Create sandbox using E2B SDK (underlying cloud infrastructure)
  const sandbox = await Sandbox.create(template, {
    timeoutMs: timeout * 1000,
  });

  // Register sandbox
  registerSandbox(sandbox.sandboxId, sandbox);

  // Sync memory context INTO sandbox
  const memorySync = await syncMemoryIn(sandbox.sandboxId, contextKeys);

  // Write context to sandbox if sync succeeded
  if (!memorySync.skipped && memorySync.contexts) {
    await writeContextToSandbox(sandbox, memorySync);
  }

  return {
    sandboxId: sandbox.sandboxId,
    template,
    status: 'running',
    url: null, // Sandbox doesn't expose direct URL
    memorySync,
  };
}

// ============================================================================
// Sandbox Create - Advanced configuration
// ============================================================================

export interface SandboxCreateArgs {
  template?: string;
  timeout?: number;
  metadata?: Record<string, any>;
  env?: Record<string, string>;
  contextKeys?: string[]; // Memory context keys to sync in
}

export interface SandboxCreateResult {
  sandboxId: string;
  template: string;
  status: string;
  metadata: Record<string, any>;
  createdAt: string;
  memorySync?: any; // Memory sync result
}

/**
 * Create a new sandbox with advanced configuration
 * Provides more control than sandbox_init
 *
 * Memory Bridge Integration:
 * - Syncs context from shared memory before agent starts
 * - Writes context to /workspace/.bumba-context.json
 */
export async function sandboxCreate(args: SandboxCreateArgs): Promise<SandboxCreateResult> {
  const {
    template = 'base',
    timeout = 3600,
    metadata = {},
    env = {},
    contextKeys = [],
  } = args;

  // Create sandbox with env vars
  const sandbox = await Sandbox.create(template, {
    timeoutMs: timeout * 1000,
    metadata,
  });

  // Set environment variables if provided
  if (Object.keys(env).length > 0) {
    const envEntries = Object.entries(env)
      .map(([key, value]) => `export ${key}="${value}"`)
      .join('\n');

    await sandbox.files.write('/etc/profile.d/custom-env.sh', envEntries);
  }

  // Register sandbox
  registerSandbox(sandbox.sandboxId, sandbox);

  // Sync memory context INTO sandbox
  const memorySync = await syncMemoryIn(sandbox.sandboxId, contextKeys);

  // Write context to sandbox if sync succeeded
  if (!memorySync.skipped && memorySync.contexts) {
    await writeContextToSandbox(sandbox, memorySync);
  }

  return {
    sandboxId: sandbox.sandboxId,
    template,
    status: 'running',
    metadata,
    createdAt: new Date().toISOString(),
    memorySync,
  };
}

// ============================================================================
// Sandbox Connect - Connect to existing sandbox
// ============================================================================

export interface SandboxConnectArgs {
  sandboxId: string;
}

export interface SandboxConnectResult {
  sandboxId: string;
  status: string;
  connected: boolean;
  message: string;
}

/**
 * Connect to an existing sandbox by ID
 * Useful for resuming work with a previously created sandbox
 */
export async function sandboxConnect(args: SandboxConnectArgs): Promise<SandboxConnectResult> {
  const { sandboxId } = args;

  if (!sandboxId) {
    throw new Error('sandboxId is required');
  }

  // Check if already registered
  const existing = getSandbox(sandboxId);
  if (existing) {
    return {
      sandboxId,
      status: 'running',
      connected: true,
      message: 'Already connected to this sandbox',
    };
  }

  // Connect to existing sandbox
  const sandbox = await Sandbox.connect(sandboxId);

  // Register sandbox
  registerSandbox(sandboxId, sandbox);

  return {
    sandboxId,
    status: 'running',
    connected: true,
    message: 'Successfully connected to existing sandbox',
  };
}

// ============================================================================
// Sandbox Kill - Terminate and cleanup
// ============================================================================

export interface SandboxKillArgs {
  sandboxId: string;
  skipMemorySync?: boolean; // Skip memory sync-out (default: false)
}

export interface SandboxKillResult {
  sandboxId: string;
  status: string;
  terminated: boolean;
  message: string;
  memorySync?: any; // Memory sync result
}

/**
 * Terminate and cleanup a sandbox
 * This permanently destroys the sandbox and all its data
 *
 * Memory Bridge Integration:
 * - Reads /workspace/.bumba-summary.json and .bumba-notes/
 * - Syncs all artifacts, decisions, and contexts to shared memory
 * - Preserves sandbox work for primary session access
 */
export async function sandboxKill(args: SandboxKillArgs): Promise<SandboxKillResult> {
  const { sandboxId, skipMemorySync = false } = args;

  if (!sandboxId) {
    throw new Error('sandboxId is required');
  }

  // Get sandbox
  const sandbox = getSandbox(sandboxId);
  if (!sandbox) {
    throw new Error(`Sandbox ${sandboxId} not found in active registry`);
  }

  // Sync memory OUT before killing (preserves sandbox work)
  let memorySync = null;
  if (!skipMemorySync) {
    memorySync = await syncMemoryOut(sandboxId, sandbox);
  }

  // Kill sandbox
  await sandbox.kill();

  // Unregister
  unregisterSandbox(sandboxId);

  return {
    sandboxId,
    status: 'terminated',
    terminated: true,
    message: memorySync?.skipped
      ? 'Sandbox terminated (memory sync skipped)'
      : 'Sandbox terminated with memory sync',
    memorySync,
  };
}

// ============================================================================
// Sandbox Status - Health check
// ============================================================================

export interface SandboxStatusArgs {
  sandboxId: string;
}

export interface SandboxStatusResult {
  sandboxId: string;
  status: string;
  registered: boolean;
  uptime?: number;
  template?: string;
}

/**
 * Get status and health information for a sandbox
 * Returns current state and basic metrics
 */
export async function sandboxStatus(args: SandboxStatusArgs): Promise<SandboxStatusResult> {
  const { sandboxId } = args;

  if (!sandboxId) {
    throw new Error('sandboxId is required');
  }

  // Check if registered
  const sandbox = getSandbox(sandboxId);
  if (!sandbox) {
    return {
      sandboxId,
      status: 'unknown',
      registered: false,
    };
  }

  // Get sandbox info
  return {
    sandboxId,
    status: 'running',
    registered: true,
  };
}

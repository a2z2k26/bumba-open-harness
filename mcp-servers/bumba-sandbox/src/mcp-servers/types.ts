/**
 * TypeScript type definitions for Bumba Sandbox Orchestrator
 * Generated from JSON schemas in .claude/config/
 */

// ============================================================================
// Execution Modes
// ============================================================================

export type ExecutionMode = 'local' | 'sandbox' | 'auto';

export type OrchestrationStrategy = 'max-speed' | 'cost-optimized' | 'balanced';

// ============================================================================
// Configuration Types
// ============================================================================

export interface BumbaSandboxConfig {
  defaultMode: ExecutionMode;
  autoModeRules: AutoModeRules;
  sandboxDefaults: SandboxDefaults;
  hookConfig: HookConfig;
  costManagement: CostManagement;
  notifications: NotificationConfig;
  orchestration: OrchestrationConfig;
  github: GitHubConfig;
  logging: LoggingConfig;
}

export interface AutoModeRules {
  sandboxLabels: string[];
  localLabels: string[];
  sandboxKeywords: string[];
  defaultWhenUncertain: 'local' | 'sandbox';
}

export interface SandboxDefaults {
  template: string;
  maxConcurrent: number;
  timeout: number;
  autoCleanup: boolean;
  cleanupDelay: number;
  envVars: Record<string, string>;
}

export interface HookConfig {
  enabled: boolean;
  enabledHooks: HookType[];
  pathRestrictions: PathRestrictions;
  logging: HookLogging;
}

export interface PathRestrictions {
  enabled: boolean;
  allowedPaths: string[];
  blockedTools: string[];
}

export interface HookLogging {
  logAllToolUse: boolean;
  logPrompts: boolean;
  logCosts: boolean;
}

export interface CostManagement {
  budgetLimit: number;
  trackingPeriod: 'daily' | 'weekly' | 'monthly';
  alerts: CostAlerts;
  costPerHour: CostRates;
}

export interface CostAlerts {
  enabled: boolean;
  thresholds: CostThreshold[];
}

export interface CostThreshold {
  percentage: number;
  action: 'notify' | 'warn' | 'block';
}

export interface CostRates {
  sandboxCost: number;
  claudeAPI: {
    inputTokens: number;
    outputTokens: number;
  };
}

export interface NotificationConfig {
  enabled: boolean;
  channels: ('console' | 'file' | 'webhook')[];
  events: NotificationEvents;
}

export interface NotificationEvents {
  agentStarted: boolean;
  agentCompleted: boolean;
  agentFailed: boolean;
  budgetThreshold: boolean;
  sandboxCreated: boolean;
  sandboxDestroyed: boolean;
}

export interface OrchestrationConfig {
  autoCascade: boolean;
  defaultStrategy: OrchestrationStrategy;
  retryFailedAgents: boolean;
  maxRetries: number;
}

export interface GitHubConfig {
  autoCreateBranches: boolean;
  branchPrefix: string;
  autoCreatePRs: boolean;
  prLabels: string[];
}

export interface LoggingConfig {
  level: 'error' | 'warn' | 'info' | 'debug';
  format: 'json' | 'text';
  directory: string;
  maxFiles: number;
  maxSize: string;
}

// ============================================================================
// Orchestrator State Types
// ============================================================================

export interface OrchestratorState {
  session: SessionState;
  issues: Record<string, IssueState>;
  agents: Record<string, AgentState>;
  sandboxes: Record<string, SandboxState>;
  resources: ResourceState;
  events: OrchestrationEvent[];
  hooks: HookStats;
}

export interface SessionState {
  id: string;
  startedAt: string; // ISO 8601 timestamp
  updatedAt: string; // ISO 8601 timestamp
  strategy: OrchestrationStrategy;
  status: 'active' | 'paused' | 'completed' | 'failed';
  metadata?: Record<string, any>;
}

export interface IssueState {
  issueNumber: number;
  status: 'pending' | 'ready' | 'active' | 'blocked' | 'completed' | 'failed';
  dependencies: number[];
  blockedBy: number[];
  title: string;
  labels: string[];
  assignedAgentId: string | null;
  mode: ExecutionMode;
  worktreePath: string | null;
  branchName: string | null;
  prNumber: number | null;
  startedAt: string | null;
  completedAt: string | null;
  error: string | null;
}

export interface AgentState {
  agentId: string;
  issueNumber: number;
  sandboxId: string | null;
  status: 'initializing' | 'running' | 'paused' | 'completed' | 'failed';
  progress: AgentProgress;
  mode: 'local' | 'sandbox';
  startedAt: string;
  completedAt: string | null;
  costs: AgentCosts;
  logFile: string | null;
}

export interface AgentProgress {
  percentage: number;
  currentTask: string;
  toolsUsed: number;
  lastActivity: string;
}

export interface AgentCosts {
  inputTokens: number;
  outputTokens: number;
  totalCost: number;
}

export interface SandboxState {
  sandboxId: string;
  agentId: string;
  template: string;
  status: 'creating' | 'running' | 'paused' | 'terminated' | 'failed';
  resources: SandboxResources;
  cost: SandboxCost;
  createdAt: string;
  terminatedAt: string | null;
  lastActivityAt: string;
  url: string | null;
}

export interface SandboxResources {
  cpu: {
    usage: number;
    limit: number;
  };
  memory: {
    usage: number;
    limit: number;
  };
  disk: {
    usage: number;
    limit: number;
  };
}

export interface SandboxCost {
  durationSeconds: number;
  totalCost: number;
}

export interface ResourceState {
  current: CurrentResources;
  limits: ResourceLimits;
  budget: BudgetState;
}

export interface CurrentResources {
  activeSandboxes: number;
  activeAgents: number;
  totalCost: number;
}

export interface ResourceLimits {
  maxConcurrentSandboxes: number;
  budgetLimit: number;
}

export interface BudgetState {
  period: 'daily' | 'weekly' | 'monthly';
  periodStart: string;
  spent: number;
  remaining: number;
  percentUsed: number;
}

export type OrchestrationEventType =
  | 'session_started'
  | 'session_paused'
  | 'session_resumed'
  | 'session_completed'
  | 'agent_spawned'
  | 'agent_completed'
  | 'agent_failed'
  | 'sandbox_created'
  | 'sandbox_terminated'
  | 'issue_blocked'
  | 'issue_unblocked'
  | 'dependency_satisfied'
  | 'budget_threshold'
  | 'error';

export interface OrchestrationEvent {
  eventId: string;
  type: OrchestrationEventType;
  timestamp: string;
  data: Record<string, any>;
  severity: 'info' | 'warning' | 'error' | 'critical';
}

export interface HookStats {
  totalExecutions: number;
  byType: Record<HookType, HookTypeStats>;
  recentBlocks: HookBlock[];
}

export interface HookTypeStats {
  count: number;
  blocked: number;
  errors: number;
}

export interface HookBlock {
  agentId: string;
  hookType: HookType;
  tool: string;
  reason: string;
  timestamp: string;
}

// ============================================================================
// Hook System Types
// ============================================================================

export type HookType =
  | 'PreToolUse'
  | 'PostToolUse'
  | 'UserPromptSubmit'
  | 'Stop'
  | 'SubagentStop'
  | 'PreCompact';

export interface HookResult {
  hookType: HookType;
  hookSpecificOutput?: {
    permissionDecision?: 'allow' | 'deny';
    reason?: string;
    [key: string]: any;
  };
}

export interface PreToolUseData {
  tool: string;
  params: Record<string, any>;
}

export interface PostToolUseData {
  tool: string;
  params: Record<string, any>;
  result: any;
  error?: string;
}

export interface StopData {
  reason: string;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  totalCost: number;
}

// ============================================================================
// MCP Tool Types
// ============================================================================

export interface MCPToolInput {
  [key: string]: any;
}

export interface MCPToolOutput {
  success: boolean;
  data?: any;
  error?: string;
  message?: string;
}

// Dependency Analysis Tool
export interface AnalyzeDependenciesInput {
  issues: number[];
}

export interface DependencyGraph {
  nodes: DependencyNode[];
  edges: DependencyEdge[];
}

export interface DependencyNode {
  issueNumber: number;
  title: string;
  status: 'ready' | 'blocked';
  dependencies: number[];
}

export interface DependencyEdge {
  from: number;
  to: number;
}

export interface AnalyzeDependenciesOutput extends MCPToolOutput {
  data?: {
    ready: number[];
    blocked: number[];
    graph: DependencyGraph;
  };
}

// Sandbox Allocation Planning Tool
export interface PlanSandboxAllocationInput {
  readyIssues: number[];
  constraints: {
    maxConcurrent?: number;
    budgetLimit?: number;
  };
  preferences: {
    strategy: OrchestrationStrategy;
  };
}

export interface AllocationPlan {
  immediate: number[];
  queued: number[];
  deferred: number[];
  estimatedCost: number;
  estimatedDuration: number;
}

export interface PlanSandboxAllocationOutput extends MCPToolOutput {
  data?: AllocationPlan;
}

// Spawn Sandbox Agent Tool
export interface SpawnSandboxAgentInput {
  issueNumber: number;
  worktreePath: string;
  template?: string;
  spec: string;
}

export interface SpawnSandboxAgentOutput extends MCPToolOutput {
  data?: {
    agentId: string;
    sandboxId: string | null;
    mode: 'local' | 'sandbox';
  };
}

// Monitor Agents Tool
export interface MonitorAgentsInput {
  filter?: {
    status?: string[];
    issues?: number[];
  };
}

export interface MonitorAgentsOutput extends MCPToolOutput {
  data?: {
    agents: AgentState[];
    summary: {
      total: number;
      active: number;
      completed: number;
      failed: number;
      averageProgress: number;
    };
  };
}

// ============================================================================
// Utility Types
// ============================================================================

export interface GitHubIssue {
  number: number;
  title: string;
  body: string;
  state: 'open' | 'closed';
  labels: string[];
  assignee: string | null;
  created_at: string;
  updated_at: string;
}

export interface GitHubPullRequest {
  number: number;
  title: string;
  body: string;
  state: 'open' | 'closed';
  head: {
    ref: string;
    sha: string;
  };
  base: {
    ref: string;
    sha: string;
  };
  mergeable: boolean | null;
  merged: boolean;
}

// ============================================================================
// Error Types
// ============================================================================

export class OrchestratorError extends Error {
  constructor(
    message: string,
    public code: string,
    public details?: any
  ) {
    super(message);
    this.name = 'OrchestratorError';
  }
}

export class ConfigurationError extends OrchestratorError {
  constructor(message: string, details?: any) {
    super(message, 'CONFIG_ERROR', details);
    this.name = 'ConfigurationError';
  }
}

export class SandboxError extends OrchestratorError {
  constructor(message: string, details?: any) {
    super(message, 'SANDBOX_ERROR', details);
    this.name = 'SandboxError';
  }
}

export class GitHubError extends OrchestratorError {
  constructor(message: string, details?: any) {
    super(message, 'GITHUB_ERROR', details);
    this.name = 'GitHubError';
  }
}

export class BudgetExceededError extends OrchestratorError {
  constructor(message: string, details?: any) {
    super(message, 'BUDGET_EXCEEDED', details);
    this.name = 'BudgetExceededError';
  }
}

export class DependencyError extends OrchestratorError {
  constructor(message: string, details?: any) {
    super(message, 'DEPENDENCY_ERROR', details);
    this.name = 'DependencyError';
  }
}

# Bumba Sandbox Orchestration Architecture
## MCP Skill Design for Dynamic Parallel Agent Management

---

## Table of Contents

1. [Orchestration Problem](#orchestration-problem)
2. [Why MCP Skill vs Slash Commands](#why-mcp-skill-vs-slash-commands)
3. [Orchestrator Architecture](#orchestrator-architecture)
4. [MCP Skill Design](#mcp-skill-design)
5. [Orchestration Workflows](#orchestration-workflows)
6. [Dynamic Scaling](#dynamic-scaling)
7. [State Management](#state-management)
8. [Implementation Example](#implementation-example)

---

## Orchestration Problem

### The Core Challenge

When you run `/parallel-implement-features #42 #43 #44 #45 #46 #47`, the orchestrator needs to:

1. **Analyze dependencies** between all issues
2. **Determine optimal sandbox count** based on:
   - Available dependencies (what can start now?)
   - Resource limits (free tier = 100 concurrent)
   - Cost optimization (don't over-provision)
   - System capacity (your machine's limits)
3. **Create the right number of sandboxes** (not too many, not too few)
4. **Spawn Claude agents** for each sandbox
5. **Monitor progress** across all agents
6. **Handle completions** (when issue #42 finishes, what depends on it?)
7. **Auto-scale** (start new sandboxes when dependencies are satisfied)
8. **Manage failures** (agent crashes, sandbox errors)
9. **Optimize costs** (destroy idle sandboxes, reuse templates)
10. **Coordinate state** across all moving parts

### Why This Can't Be a Simple Slash Command

**Slash commands are stateless prompts**:
```markdown
<!-- .claude/commands/parallel-implement-features.md -->
When user runs /parallel-implement-features:
1. Create worktrees
2. Spawn agents
3. Done
```

**Problems**:
- ❌ Can't maintain state across agent sessions
- ❌ Can't make dynamic decisions based on real-time events
- ❌ Can't monitor multiple agents simultaneously
- ❌ Can't handle dependency chains automatically
- ❌ Can't optimize resource allocation

**What you need**: A stateful, intelligent orchestrator that runs continuously and makes decisions.

---

## Why MCP Skill vs Slash Commands

### Slash Commands: Static Instructions

**What they are**: Markdown files with text prompts
**Execution**: One-time instruction to Claude
**State**: None (stateless)
**Decisions**: Pre-defined, static logic

**Example**:
```markdown
<!-- .claude/commands/create-pr.md -->
Create a pull request for the current branch:
1. Run tests
2. Generate description
3. Submit PR with gh CLI
```

**Good for**:
- Simple, linear workflows
- One-time actions
- User-initiated tasks
- Stateless operations

**Not good for**:
- Managing multiple concurrent processes
- Long-running orchestration
- Dynamic decision-making
- State tracking across sessions

---

### MCP Skills: Intelligent Tools

**What they are**: Custom tools (MCP servers) that Claude can use
**Execution**: Claude calls tools as needed
**State**: Can maintain state across calls
**Decisions**: Dynamic, based on real-time data

**Example**:
```typescript
// MCP Skill: bumba-sandbox
Tools provided:
- analyze_dependencies(issues[]) → dependency graph
- calculate_optimal_sandboxes(graph) → sandbox plan
- spawn_sandbox_agent(issue, sandbox) → agent instance
- monitor_all_agents() → real-time status
- handle_completion(agent) → trigger dependent work
- optimize_resources() → cost/performance tuning
```

**Good for**:
- Complex orchestration
- Multi-step workflows with decision points
- Real-time monitoring and adaptation
- State management
- Dynamic resource allocation

---

## Orchestrator Architecture

### Three-Layer Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Layer 1: User Interface                       │
│                                                                   │
│  Slash Commands (User-facing):                                   │
│  - /parallel-implement-features #42 #43 #44                      │
│  - /sandbox-status                                               │
│  - /optimize-sandboxes                                           │
│                                                                   │
│  These are simple prompts that invoke the orchestrator           │
└───────────────────────────┬─────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│              Layer 2: Orchestrator (MCP Skill)                   │
│                                                                   │
│  Primary Claude Agent (Orchestrator):                            │
│  - Receives user command                                         │
│  - Calls MCP skill tools to analyze and plan                     │
│  - Makes intelligent decisions                                   │
│  - Spawns worker agents                                          │
│  - Monitors and coordinates all activities                       │
│  - Handles dynamic events (completions, failures, etc.)          │
│                                                                   │
│  MCP Skill Tools:                                                │
│  ├─ analyze_dependencies()                                       │
│  ├─ plan_sandbox_allocation()                                    │
│  ├─ spawn_sandbox_agent()                                        │
│  ├─ monitor_agents()                                             │
│  ├─ handle_agent_event()                                         │
│  └─ optimize_resources()                                         │
└───────────────────────────┬─────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│           Layer 3: Worker Agents (in Bumba Sandboxes)            │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ Worker Agent │  │ Worker Agent │  │ Worker Agent │          │
│  │     #42      │  │     #43      │  │     #45      │          │
│  │              │  │              │  │              │          │
│  │ Sandbox-42   │  │ Sandbox-43   │  │ Sandbox-45   │          │
│  │ - Code impl  │  │ - Code impl  │  │ - Code impl  │          │
│  │ - Run tests  │  │ - Run tests  │  │ - Run tests  │          │
│  │ - Commit     │  │ - Commit     │  │ - Commit     │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│                                                                   │
│  Each worker:                                                     │
│  - Isolated in own E2B sandbox                                   │
│  - Isolated in own git worktree                                  │
│  - Reports progress to orchestrator                              │
│  - Signals completion when done                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## MCP Skill Design

### Skill Name: `bumba-sandbox`

**Purpose**: Intelligent orchestration of parallel sandbox agents

### Tool 1: `analyze_dependencies`

**Purpose**: Analyze GitHub issues and build dependency graph

**Input**:
```typescript
{
  issues: number[]  // [42, 43, 44, 45, 46, 47]
}
```

**Process**:
1. Fetch all issue details from GitHub
2. Parse "Depends on #X" from descriptions
3. Build directed acyclic graph (DAG)
4. Identify issues with no dependencies (ready to start)
5. Identify blocked issues (waiting for dependencies)

**Output**:
```typescript
{
  ready: number[],      // Issues ready to start [42, 45]
  blocked: {            // Issues waiting
    43: [42],          // #43 depends on #42
    44: [42],          // #44 depends on #42
    46: [43, 45],      // #46 depends on #43 and #45
    47: [44, 46]       // #47 depends on #44 and #46
  },
  graph: DependencyGraph  // Full DAG for visualization
}
```

---

### Tool 2: `plan_sandbox_allocation`

**Purpose**: Determine optimal number of sandboxes to create

**Input**:
```typescript
{
  readyIssues: number[],      // Issues ready to start
  constraints: {
    maxConcurrent: number,    // 100 for free tier
    budgetLimit: number,      // $ per hour
    machineLimit: number      // Local resource limit
  },
  preferences: {
    strategy: 'max-speed' | 'cost-optimized' | 'balanced'
  }
}
```

**Process**:
1. Calculate resources needed per issue
2. Apply constraints (max concurrent, budget)
3. Optimize based on strategy:
   - **max-speed**: Use all available slots
   - **cost-optimized**: Minimal sandboxes, sequential when needed
   - **balanced**: Sweet spot between speed and cost

**Output**:
```typescript
{
  plan: {
    immediate: number[],     // Start these now [42, 45]
    queued: number[],        // Queue these [43, 44]
    deferred: number[]       // Wait until dependencies clear [46, 47]
  },
  sandboxes: {
    count: number,           // Total sandboxes to create
    templates: {             // Template for each sandbox
      42: 'node-postgres',
      45: 'python-redis'
    }
  },
  estimatedCost: number,     // $ estimate
  estimatedTime: number      // Hours estimate
}
```

---

### Tool 3: `spawn_sandbox_agent`

**Purpose**: Create sandbox and spawn worker agent

**Input**:
```typescript
{
  issue: number,
  worktreePath: string,
  sandboxTemplate: string,
  spec: string  // Issue specification
}
```

**Process**:
1. Create E2B sandbox from template
2. Upload worktree code to sandbox
3. Install dependencies
4. Spawn new Claude agent instance
5. Provide agent with:
   - Sandbox connection
   - Issue specification
   - Execution context
6. Register agent in orchestrator state

**Output**:
```typescript
{
  agentId: string,
  sandboxId: string,
  status: 'spawned' | 'failed',
  metadata: {
    issue: number,
    worktree: string,
    startedAt: timestamp
  }
}
```

---

### Tool 4: `monitor_agents`

**Purpose**: Real-time monitoring of all active agents

**Input**:
```typescript
{
  filter?: {
    status?: 'active' | 'idle' | 'completed' | 'failed',
    issues?: number[]
  }
}
```

**Process**:
1. Query all registered agents
2. Check sandbox status for each
3. Retrieve progress metrics
4. Calculate estimates

**Output**:
```typescript
{
  agents: [{
    agentId: string,
    issue: number,
    status: 'active' | 'idle' | 'completed' | 'failed',
    progress: {
      phase: 'planning' | 'coding' | 'testing' | 'committing',
      percentage: number,
      currentTask: string
    },
    sandbox: {
      id: string,
      cpu: number,
      memory: number,
      uptime: number,
      cost: number
    },
    metrics: {
      commits: number,
      testsPass: number,
      testsFail: number,
      linesChanged: number
    }
  }],
  summary: {
    total: number,
    active: number,
    completed: number,
    failed: number,
    totalCost: number
  }
}
```

---

### Tool 5: `handle_agent_event`

**Purpose**: Handle agent lifecycle events (completion, failure, etc.)

**Input**:
```typescript
{
  event: {
    type: 'completed' | 'failed' | 'blocked' | 'progress',
    agentId: string,
    issue: number,
    data: any
  }
}
```

**Process**:

**On Completion**:
1. Mark issue as complete
2. Destroy sandbox
3. Check dependency graph for newly unblocked issues
4. Spawn new agents for unblocked issues
5. Update orchestrator state

**On Failure**:
1. Log failure details
2. Preserve sandbox for debugging
3. Notify user
4. Optionally retry with different approach

**On Blocked**:
1. Identify blocking issue
2. Pause agent
3. Snapshot sandbox state
4. Resume when unblocked

**Output**:
```typescript
{
  handled: boolean,
  actions: [{
    type: 'spawn_agent' | 'destroy_sandbox' | 'notify_user',
    details: any
  }],
  newState: OrchestratorState
}
```

---

### Tool 6: `optimize_resources`

**Purpose**: Continuous optimization of sandbox allocation

**Input**:
```typescript
{
  criteria: 'cost' | 'speed' | 'both'
}
```

**Process**:
1. Identify idle sandboxes (no activity for N minutes)
2. Identify low-priority queued issues
3. Calculate cost of current allocation
4. Simulate alternative allocations
5. Recommend optimizations

**Output**:
```typescript
{
  current: {
    sandboxes: number,
    cost: number,
    eta: number  // hours to completion
  },
  optimized: {
    actions: [{
      type: 'destroy' | 'spawn' | 'defer',
      sandboxId?: string,
      issue?: number,
      reason: string
    }],
    newCost: number,
    newEta: number,
    savings: number
  }
}
```

---

## Orchestration Workflows

### Workflow 1: Initial Parallel Launch

**User Command**:
```
/parallel-implement-features #42 #43 #44 #45 #46 #47
```

**Orchestrator Process**:

```typescript
// Step 1: Analyze dependencies
const deps = await orchestrator.analyze_dependencies({
  issues: [42, 43, 44, 45, 46, 47]
});

// Result:
// ready: [42, 45]
// blocked: { 43: [42], 44: [42], 46: [43, 45], 47: [44, 46] }

// Step 2: Plan allocation
const plan = await orchestrator.plan_sandbox_allocation({
  readyIssues: deps.ready,  // [42, 45]
  constraints: {
    maxConcurrent: 100,
    budgetLimit: 50,  // $50/hour
    machineLimit: 10
  },
  preferences: {
    strategy: 'balanced'
  }
});

// Result:
// immediate: [42, 45]
// queued: [43, 44]
// deferred: [46, 47]
// count: 2 sandboxes

// Step 3: Spawn agents for immediate issues
for (const issue of plan.immediate) {
  await orchestrator.spawn_sandbox_agent({
    issue,
    worktreePath: `worktrees/feature-${issue}`,
    sandboxTemplate: plan.sandboxes.templates[issue],
    spec: await fetchIssueSpec(issue)
  });
}

// Result:
// Agent-42 spawned in Sandbox-42
// Agent-45 spawned in Sandbox-45

// Step 4: Monitor progress
setInterval(async () => {
  const status = await orchestrator.monitor_agents({});
  console.log('Active agents:', status.agents.length);
  console.log('Total cost:', status.summary.totalCost);
}, 30000);  // Every 30 seconds
```

**User sees**:
```
Analyzing dependencies...
✓ Found 2 ready: #42, #45
✓ Found 4 blocked: #43, #44, #46, #47

Planning sandbox allocation...
✓ Strategy: balanced
✓ Creating 2 sandboxes immediately
✓ Queuing 2 for later
✓ Estimated cost: $2.50
✓ Estimated time: 4 hours

Spawning agents...
✓ Agent-42: Working on #42 in Sandbox-42
✓ Agent-45: Working on #45 in Sandbox-45

Monitoring progress...
[Live dashboard updates every 30s]
```

---

### Workflow 2: Dynamic Completion Handling

**Agent-42 completes Issue #42**:

```typescript
// Agent-42 signals completion
orchestrator.handle_agent_event({
  event: {
    type: 'completed',
    agentId: 'agent-42',
    issue: 42,
    data: {
      prNumber: 52,
      commits: 8,
      testsPass: 42
    }
  }
});

// Orchestrator process:

// 1. Mark #42 as complete
markIssueComplete(42);

// 2. Destroy sandbox
destroyE2BSandbox('sandbox-42');

// 3. Check dependency graph
const unblocked = checkUnblockedIssues(42);
// Returns: [43, 44] (both were waiting for #42)

// 4. Check if we can spawn more agents
const currentAgents = await monitor_agents({});
const availableSlots = constraints.maxConcurrent - currentAgents.agents.length;

// 5. Spawn agents for newly unblocked issues
if (availableSlots >= 2) {
  await spawn_sandbox_agent({ issue: 43, ... });
  await spawn_sandbox_agent({ issue: 44, ... });
} else if (availableSlots === 1) {
  // Prioritize based on strategy
  await spawn_sandbox_agent({ issue: 43, ... });  // Higher priority
}
```

**User sees**:
```
✓ Agent-42 completed #42!
  - PR #52 created
  - 8 commits, 42 tests passing

✓ Destroying Sandbox-42
✓ Freed resources

Dependencies satisfied!
✓ #43 is now ready (was waiting for #42)
✓ #44 is now ready (was waiting for #42)

Spawning new agents...
✓ Agent-43: Working on #43 in Sandbox-43
✓ Agent-44: Working on #44 in Sandbox-44

Active agents: 3
- Agent-45: 65% complete
- Agent-43: Just started
- Agent-44: Just started
```

---

### Workflow 3: Cascading Completions

**Agent-43 and Agent-45 both complete**:

```typescript
// Both complete around same time
handle_agent_event({ type: 'completed', issue: 43 });
handle_agent_event({ type: 'completed', issue: 45 });

// Check dependency graph
const unblocked = checkUnblockedIssues([43, 45]);
// Returns: [46] (was waiting for BOTH #43 AND #45)

// Spawn agent for #46
await spawn_sandbox_agent({ issue: 46, ... });
```

**User sees**:
```
✓ Agent-43 completed #43!
✓ Agent-45 completed #45!

Dependencies satisfied!
✓ #46 is now ready (was waiting for #43 AND #45)

Spawning new agents...
✓ Agent-46: Working on #46 in Sandbox-46

Active agents: 2
- Agent-44: 80% complete
- Agent-46: Just started
```

---

## Dynamic Scaling

### Scenario: Budget-Constrained Scaling

**User sets budget limit**:
```
/parallel-implement-features #1-20 --max-budget 100 --strategy cost-optimized
```

**Orchestrator logic**:

```typescript
const plan = await plan_sandbox_allocation({
  readyIssues: [1, 2, 3, 4, 5, ...],  // 20 issues
  constraints: {
    budgetLimit: 100  // $100 total
  },
  preferences: {
    strategy: 'cost-optimized'
  }
});

// Calculation:
// - Average $5 per issue
// - $100 budget = 20 issues
// - Cost per hour = $2 (2 vCPU @ $0.014/s)
// - Budget $100 / $2 = 50 hours available
// - Want to finish in ~10 hours
// - 50 hours / 10 hours = 5 concurrent sandboxes

// Result:
plan = {
  immediate: [1, 2, 3, 4, 5],  // Start 5
  strategy: 'rolling',          // As each completes, start next
  maxConcurrent: 5,
  estimatedCost: 95,
  estimatedTime: 10
};
```

**Behavior**:
- Start with 5 sandboxes
- When Issue #1 completes → destroy sandbox → start Issue #6
- When Issue #2 completes → destroy sandbox → start Issue #7
- Continues until all 20 complete
- Never exceeds 5 concurrent sandboxes
- Stays within $100 budget

---

### Scenario: Speed-Optimized Scaling

**User prioritizes speed**:
```
/parallel-implement-features #1-20 --strategy max-speed
```

**Orchestrator logic**:

```typescript
const plan = await plan_sandbox_allocation({
  readyIssues: [1, 2, 3, ..., 20],  // All ready
  constraints: {
    maxConcurrent: 100  // Free tier limit
  },
  preferences: {
    strategy: 'max-speed'
  }
});

// Result:
plan = {
  immediate: [1, 2, 3, ..., 20],  // Start all 20!
  maxConcurrent: 20,
  estimatedCost: 40,  // Higher cost
  estimatedTime: 2    // Much faster
};
```

**Behavior**:
- Create 20 sandboxes immediately
- All agents work in parallel
- Complete in ~2 hours instead of 10 hours
- Higher cost but maximum speed

---

## State Management

### Orchestrator State Schema

```typescript
interface OrchestratorState {
  session: {
    id: string,
    startedAt: timestamp,
    command: string,
    strategy: 'max-speed' | 'cost-optimized' | 'balanced'
  },

  issues: {
    [issueNumber: number]: {
      status: 'pending' | 'active' | 'completed' | 'failed',
      dependencies: number[],
      blockedBy: number[],
      agent?: string,
      sandbox?: string,
      worktree?: string
    }
  },

  agents: {
    [agentId: string]: {
      issue: number,
      sandboxId: string,
      status: 'spawning' | 'active' | 'idle' | 'completed' | 'failed',
      startedAt: timestamp,
      progress: {
        phase: string,
        percentage: number
      },
      metrics: {
        commits: number,
        testsPass: number,
        testsFail: number
      }
    }
  },

  sandboxes: {
    [sandboxId: string]: {
      issue: number,
      template: string,
      status: 'creating' | 'active' | 'idle' | 'destroyed',
      resources: {
        cpu: number,
        memory: number
      },
      cost: number,
      uptime: number
    }
  },

  resources: {
    maxConcurrent: number,
    currentActive: number,
    budgetLimit?: number,
    currentCost: number
  },

  events: [{
    timestamp: timestamp,
    type: string,
    details: any
  }]
}
```

**State persistence**:
```typescript
// Save state to file
saveState('.claude/orchestrator-state.json', state);

// Load state on resume
const state = loadState('.claude/orchestrator-state.json');

// User can resume interrupted session
/resume-orchestration
// Restores all agents, sandboxes, and continues
```

---

## Implementation Example

### Complete MCP Skill Implementation

```typescript
// .claude/mcp-servers/bumba-sandbox.ts

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { Sandbox } from '@e2b/sdk';
import { Octokit } from '@octokit/rest';

class BumbaSandboxOrchestrator {
  private state: OrchestratorState;
  private github: Octokit;

  constructor() {
    this.state = this.loadState();
    this.github = new Octokit({ auth: process.env.GITHUB_TOKEN });
  }

  async analyzeDependencies(issues: number[]) {
    const graph: DependencyGraph = { nodes: [], edges: [] };
    const ready: number[] = [];
    const blocked: Record<number, number[]> = {};

    for (const issue of issues) {
      // Fetch issue from GitHub
      const { data } = await this.github.issues.get({
        owner: 'user',
        repo: 'repo',
        issue_number: issue
      });

      // Parse dependencies from description
      const deps = this.parseDependencies(data.body);

      if (deps.length === 0) {
        ready.push(issue);
      } else {
        blocked[issue] = deps;
      }

      // Build graph
      graph.nodes.push({ id: issue, label: data.title });
      deps.forEach(dep => {
        graph.edges.push({ from: dep, to: issue });
      });
    }

    return { ready, blocked, graph };
  }

  async planSandboxAllocation(readyIssues: number[], constraints: any, preferences: any) {
    const plan = {
      immediate: [],
      queued: [],
      deferred: [],
      sandboxes: { count: 0, templates: {} },
      estimatedCost: 0,
      estimatedTime: 0
    };

    // Determine how many to start based on strategy
    if (preferences.strategy === 'max-speed') {
      plan.immediate = readyIssues;
      plan.sandboxes.count = readyIssues.length;
    } else if (preferences.strategy === 'cost-optimized') {
      // Start minimal, sequential execution
      plan.immediate = [readyIssues[0]];
      plan.queued = readyIssues.slice(1);
      plan.sandboxes.count = 1;
    } else {
      // Balanced: Start multiple but not all
      const balanced = Math.min(readyIssues.length, 5);
      plan.immediate = readyIssues.slice(0, balanced);
      plan.queued = readyIssues.slice(balanced);
      plan.sandboxes.count = balanced;
    }

    // Assign templates based on issue labels/tech stack
    for (const issue of plan.immediate) {
      plan.sandboxes.templates[issue] = await this.determineTemplate(issue);
    }

    // Estimate cost and time
    plan.estimatedCost = this.calculateCost(plan.sandboxes.count);
    plan.estimatedTime = this.estimateTime(readyIssues.length, plan.sandboxes.count);

    return plan;
  }

  async spawnSandboxAgent(issue: number, worktreePath: string, template: string, spec: string) {
    // Create E2B sandbox
    const sandbox = await Sandbox.create({ template });

    // Upload code
    await sandbox.files.upload(worktreePath, '/home/user/code');

    // Install dependencies
    await sandbox.process.start({
      cmd: 'npm install',
      cwd: '/home/user/code'
    });

    // Generate agent ID
    const agentId = `agent-${issue}-${Date.now()}`;

    // Spawn Claude agent (using Claude API or subprocess)
    const agent = await this.spawnClaudeAgent({
      id: agentId,
      sandboxId: sandbox.id,
      issue,
      spec,
      context: {
        worktree: worktreePath,
        sandbox: sandbox.id
      }
    });

    // Register in state
    this.state.agents[agentId] = {
      issue,
      sandboxId: sandbox.id,
      status: 'active',
      startedAt: Date.now(),
      progress: { phase: 'planning', percentage: 0 },
      metrics: { commits: 0, testsPass: 0, testsFail: 0 }
    };

    this.state.sandboxes[sandbox.id] = {
      issue,
      template,
      status: 'active',
      resources: { cpu: 0, memory: 0 },
      cost: 0,
      uptime: 0
    };

    this.saveState();

    return { agentId, sandboxId: sandbox.id, status: 'spawned' };
  }

  async monitorAgents(filter?: any) {
    const agents = Object.entries(this.state.agents)
      .filter(([id, agent]) => {
        if (filter?.status && agent.status !== filter.status) return false;
        if (filter?.issues && !filter.issues.includes(agent.issue)) return false;
        return true;
      })
      .map(([id, agent]) => ({
        agentId: id,
        ...agent,
        sandbox: this.state.sandboxes[agent.sandboxId]
      }));

    const summary = {
      total: agents.length,
      active: agents.filter(a => a.status === 'active').length,
      completed: agents.filter(a => a.status === 'completed').length,
      failed: agents.filter(a => a.status === 'failed').length,
      totalCost: Object.values(this.state.sandboxes)
        .reduce((sum, s) => sum + s.cost, 0)
    };

    return { agents, summary };
  }

  async handleAgentEvent(event: any) {
    const { type, agentId, issue, data } = event;

    if (type === 'completed') {
      // Mark agent complete
      this.state.agents[agentId].status = 'completed';
      this.state.issues[issue].status = 'completed';

      // Destroy sandbox
      const sandboxId = this.state.agents[agentId].sandboxId;
      await Sandbox.connect(sandboxId).then(s => s.close());
      this.state.sandboxes[sandboxId].status = 'destroyed';

      // Check for unblocked issues
      const unblocked = this.checkUnblockedIssues(issue);

      // Spawn new agents
      const actions = [];
      for (const unblockedIssue of unblocked) {
        const spawned = await this.spawnSandboxAgent(
          unblockedIssue,
          `worktrees/feature-${unblockedIssue}`,
          await this.determineTemplate(unblockedIssue),
          await this.fetchIssueSpec(unblockedIssue)
        );

        actions.push({
          type: 'spawn_agent',
          details: spawned
        });
      }

      this.saveState();

      return { handled: true, actions, newState: this.state };
    }

    // Handle other event types...
  }

  private checkUnblockedIssues(completedIssue: number): number[] {
    const unblocked: number[] = [];

    for (const [issue, data] of Object.entries(this.state.issues)) {
      if (data.status === 'pending' && data.blockedBy.includes(completedIssue)) {
        // Remove completed issue from blockedBy
        data.blockedBy = data.blockedBy.filter(i => i !== completedIssue);

        // If no longer blocked, mark as ready
        if (data.blockedBy.length === 0) {
          unblocked.push(Number(issue));
        }
      }
    }

    return unblocked;
  }

  private saveState() {
    // Save to file
    require('fs').writeFileSync(
      '.claude/orchestrator-state.json',
      JSON.stringify(this.state, null, 2)
    );
  }

  private loadState(): OrchestratorState {
    // Load from file or create new
    try {
      return JSON.parse(
        require('fs').readFileSync('.claude/orchestrator-state.json', 'utf8')
      );
    } catch {
      return this.createInitialState();
    }
  }
}

// MCP Server setup
const server = new Server({ name: 'bumba-sandbox', version: '1.0.0' });
const orchestrator = new BumbaSandboxOrchestrator();

server.setRequestHandler('tools/call', async (request) => {
  const { name, arguments: args } = request.params;

  if (name === 'analyze_dependencies') {
    return orchestrator.analyzeDependencies(args.issues);
  }

  if (name === 'plan_sandbox_allocation') {
    return orchestrator.planSandboxAllocation(
      args.readyIssues,
      args.constraints,
      args.preferences
    );
  }

  if (name === 'spawn_sandbox_agent') {
    return orchestrator.spawnSandboxAgent(
      args.issue,
      args.worktreePath,
      args.sandboxTemplate,
      args.spec
    );
  }

  if (name === 'monitor_agents') {
    return orchestrator.monitorAgents(args.filter);
  }

  if (name === 'handle_agent_event') {
    return orchestrator.handleAgentEvent(args.event);
  }
});

// Start server
const transport = new StdioServerTransport();
server.connect(transport);
```

---

## Summary

### Orchestrator = Primary Claude Agent

The **primary Claude agent** (the one you interact with) becomes the **orchestrator**:

1. **You**: `/parallel-implement-features #42 #43 #44`
2. **Primary Claude**: Uses MCP skill tools to:
   - Analyze dependencies
   - Plan sandbox allocation
   - Spawn worker agents
   - Monitor progress
   - Handle events dynamically

3. **Worker Claude Agents**: Each spawned in their own sandbox, working independently

### Why This Works

- **Slash commands**: Simple user interface
- **MCP skill**: Intelligent orchestration logic
- **Primary Claude**: Makes decisions using skill tools
- **Worker Claudes**: Execute implementation work
- **E2B Sandboxes**: Provide isolated execution environments

### Key Insight

The **orchestrator is NOT a separate service** - it's the **primary Claude agent using sophisticated MCP tools** to coordinate multiple worker agents. This gives you:

- Natural language control
- Intelligent decision-making
- Dynamic adaptation
- State management
- Event handling

All through conversational interaction with Claude!

---

**Document Version**: 1.0
**Created**: 2025-11-17
**Status**: Architecture Design

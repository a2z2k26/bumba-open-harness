```
██████╗ ██╗   ██╗███╗   ███╗██████╗  █████╗     ███████╗ █████╗ ███╗   ██╗██████╗ ██████╗  ██████╗ ██╗  ██╗
██╔══██╗██║   ██║████╗ ████║██╔══██╗██╔══██╗    ██╔════╝██╔══██╗████╗  ██║██╔══██╗██╔══██╗██╔═══██╗╚██╗██╔╝
██████╔╝██║   ██║██╔████╔██║██████╔╝███████║    ███████╗███████║██╔██╗ ██║██║  ██║██████╔╝██║   ██║ ╚███╔╝
██╔══██╗██║   ██║██║╚██╔╝██║██╔══██╗██╔══██║    ╚════██║██╔══██║██║╚██╗██║██║  ██║██╔══██╗██║   ██║ ██╔██╗
██████╔╝╚██████╔╝██║ ╚═╝ ██║██████╔╝██║  ██║    ███████║██║  ██║██║ ╚████║██████╔╝██████╔╝╚██████╔╝██╔╝ ██╗
╚═════╝  ╚═════╝ ╚═╝     ╚═╝╚═════╝ ╚═╝  ╚═╝    ╚══════╝╚═╝  ╚═╝╚═╝  ╚═══╝╚═════╝ ╚═════╝  ╚═════╝ ╚═╝  ╚═╝
```

[![TypeScript](https://img.shields.io/badge/typescript-5.3+-blue.svg)](https://www.typescriptlang.org)

<br>

### Orchestrate sandboxes from any model. Parallel agents. Drop-in MCP. Bumba Sandbox is a Model Context Protocol server that lets any MCP-compatible AI client spin up isolated cloud sandboxes through E2B, run code in them, and coordinate parallel agents — all from inside a conversation. Built for the case where the model itself is the orchestrator. ###

---

### 🔴 Sandbox Lifecycle ###

1. **Initialize**: create a sandbox with a chosen template (Python, Node, Go, Rust, base).
2. **Operate**: read and write files, run shell commands, stream output.
3. **Tear down**: pause, resume, or kill the sandbox when work is complete.

---

### 🟡 Multi-Agent Orchestration ###

- **Parallel sandboxes**: dispatch multiple agents across isolated environments.
- **Dependency-aware scheduling**: `analyze_dependencies` resolves build order automatically.
- **Resource allocation**: balanced, max-speed, and cost-aware strategies.

---

### 🟢 Model-Agnostic ###

- **Any MCP client** — Claude Desktop, Claude Code, Cursor, Continue, custom.
- **Stdio transport** with no model dependency.
- **Your client picks the model.** The server only exposes the tools.

<br>

### 🏁 Tool Inventory ###

| Category | Tools | What you can do |
|----------|-------|------------------|
| **Lifecycle** | 5 | Create, connect, pause, resume, kill sandboxes |
| **File ops** | 10 | Read, write, list, copy, move, sync inside sandboxes |
| **Commands** | 1 | Execute shell commands with streaming + exit codes |
| **Orchestration** | 8 | Plan allocation, spawn agents, monitor, handle events |
| **Dependencies** | 1 | Analyze a GitHub repo's dependency graph |

24 tools total. Full reference: [`docs/MCP_TOOLS_REFERENCE.md`](docs/MCP_TOOLS_REFERENCE.md).

<br>

### 🏁 Installation ###

(requires Node.js 18+, an [E2B](https://e2b.dev) account, and an MCP-compatible client)

```bash
# Clone and install
git clone https://github.com/your-org/bumba-sandbox-mcp.git
cd bumba-sandbox-mcp
npm install
npm run build
```

<br>

### 🏁 Configuration ###

Add to Claude Desktop (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "bumba-sandbox": {
      "command": "node",
      "args": ["/absolute/path/to/bumba-sandbox-mcp/dist/mcp-servers/bumba-sandbox.js"],
      "env": {
        "E2B_API_KEY": "e2b_...",
        "GITHUB_TOKEN": "<github-token>",
        "GITHUB_REPO_OWNER": "your-username",
        "GITHUB_REPO_NAME": "your-repo"
      }
    }
  }
}
```

Cursor, Continue, and other MCP clients use the same shape — point them at `dist/mcp-servers/bumba-sandbox.js` with the same env block.

<br>

### 🏁 Environment Setup ###

Copy the template and fill in your keys:

```bash
cp .env.example .env
```

```bash
# Required
E2B_API_KEY=e2b_your_api_key_here
GITHUB_TOKEN=<github-token>
GITHUB_REPO_OWNER=your-github-username
GITHUB_REPO_NAME=your-repository-name

# Optional
# E2B_API_URL=https://api.e2b.dev
# GITHUB_API_URL=https://github.your-company.com/api/v3
# LOG_LEVEL=info
# MAX_CONCURRENT_SANDBOXES=5
```

<br>

---

<br>

### 🏁 First Sandbox ###

Once connected, ask your model:

```text
Spin up a Python sandbox, install pandas,
and run analyses/q1.py against data.csv.
Report back with the results.
```

The model invokes `sandbox_init` → `file_write` → `command_execute` → `sandbox_kill` to handle the full lifecycle.

<br>

### 🟢 Parallel Agents ###

```text
Implement issues #12, #13, and #14 in parallel sandboxes.
Stop early if any of them fail tests.
```

`analyze_dependencies` and `spawn_parallel_agents` handle dependency-aware scheduling automatically. Use `set_orchestration_strategy` to switch between `balanced`, `max-speed`, and `cost-aware`.

<br>

---

<br>

### 🏁 Architecture ###

```
   MCP client                 MCP server                External
  ┌───────────┐   stdio    ┌─────────────────┐
  │  Claude / │ ─────────► │  bumba-sandbox  │ ──► E2B Cloud Sandboxes
  │  Cursor / │            │      -mcp       │ ──► GitHub API
  │  custom   │ ◄───────── │                 │ ──► Local state / logs
  └───────────┘            └─────────────────┘
```

Deep dive: [`docs/BUMBA_SANDBOX_ARCHITECTURE.md`](docs/BUMBA_SANDBOX_ARCHITECTURE.md).

<br>

### 🏁 Development ###

```bash
npm run build       # compile TypeScript
npm run watch       # rebuild on change
npm test            # run jest test suite (111 tests)
npm run lint        # eslint
npm run type-check  # tsc --noEmit
```

<br>

---

<br>

### 🏁 Documentation ###

- [`docs/QUICK_START_GUIDE.md`](docs/QUICK_START_GUIDE.md) — 10-minute end-to-end walkthrough
- [`docs/SETUP.md`](docs/SETUP.md) — full setup with troubleshooting
- [`docs/MCP_TOOLS_REFERENCE.md`](docs/MCP_TOOLS_REFERENCE.md) — every tool, every parameter
- [`docs/BUMBA_SANDBOX_ARCHITECTURE.md`](docs/BUMBA_SANDBOX_ARCHITECTURE.md) — system design

<br>

### 🏁 License ###

[MIT](LICENSE) — Bumba Harness Contributors.

Built on [E2B](https://e2b.dev), [Model Context Protocol](https://modelcontextprotocol.io), and [Octokit](https://github.com/octokit/rest.js).

<br>

### 🏁 Contributing ###

Issues and PRs welcome. For larger changes, please open an issue first to discuss the approach.

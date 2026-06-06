# Vendored MCP Servers

This directory contains in-tree MCP servers used by the harness.

```text
mcp-servers/
├── bumba-memory/     JavaScript MCP server for shared memory
└── bumba-sandbox/    TypeScript MCP server for sandbox orchestration
```

They are vendored here so a deployment can reference repository-relative paths
instead of machine-specific source trees.

## Development

`bumba-memory` is plain JavaScript:

```bash
cd mcp-servers/bumba-memory
npm ci
npm test
```

`bumba-sandbox` is TypeScript and commits compiled output:

```bash
cd mcp-servers/bumba-sandbox
npm ci
npm test
npm run build
```

When editing `bumba-sandbox/src/`, rebuild before committing so `dist/` stays in
sync.

## Runtime State

Do not commit:

- `node_modules/`
- `.env`
- local `.mcp.json`
- browser/session state
- generated logs or databases

The harness-level MCP registration reference is
`agent/config/mcp-servers.canonical.json`.

## Node Version

Use Node.js 20.x or 22.x. Node 24+ is not currently recommended because native
dependencies used by the memory server may not have compatible prebuilt
binaries.

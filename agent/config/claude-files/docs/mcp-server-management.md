# MCP Server Management Guide

**Last Updated:** 2025-12-18

## Configuration Location

**Canonical Location (ALWAYS USE THIS):**
```
~/.claude.json → "mcpServers" section
```

This is the **single source of truth** for all MCP servers in Claude Code.

## Current Configuration

- **Total MCP Servers:** 39
- **Configuration File:** `~/.claude.json`
- **Managed Via:** Claude Code MCP Manager UI

### Server Categories

1. **Bumba Servers (5)**
   - bumba
   - bumba-figma
   - bumba-memory
   - bumba-sandbox
   - (bumba voice via "bumba" entry)

2. **Anthropic Official (4)**
   - filesystem
   - github
   - memory
   - sequential-thinking

3. **Databases & Vector Stores (5)**
   - chroma
   - mongodb
   - pinecone
   - postgres
   - qdrant

4. **Development Tools (4)**
   - chrome-devtools
   - docker-gateway
   - kubernetes
   - playwright

5. **Third-Party Services (22)**
   - All other integrations (Notion, Figma, Stripe, etc.)

## Best Practices

### ✓ DO

1. **Add servers to user-scope only:**
   ```bash
   # Edit ~/.claude.json and add to "mcpServers" section
   ```

2. **Use MCP Manager UI:**
   - Enable/disable servers per project
   - View server status
   - Manage server permissions

3. **Keep backups:**
   ```bash
   cp ~/.claude.json ~/.claude.json.backup-$(date +%Y%m%d)
   ```

### ✗ DON'T

1. **Never add project-level MCP servers:**
   - Avoid adding `mcpServers` in project-specific config
   - This creates conflicts and duplicate registrations
   - Project-level config is stored in `~/.claude.json → projects → {path} → mcpServers`

2. **Don't confuse with Claude Desktop:**
   - Claude Desktop: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Claude Code: `~/.claude.json`
   - These are **separate applications** with separate configs

3. **Don't manually edit while Claude Code is running:**
   - Close Claude Code before editing `~/.claude.json`
   - Restart after making changes

## Adding a New MCP Server

```json
{
  "mcpServers": {
    "your-server-name": {
      "type": "stdio",
      "command": "node",  // or "npx", "python", etc.
      "args": [
        "/path/to/your/server.js"
      ],
      "env": {
        "API_KEY": "your-key-here"  // optional
      }
    }
  }
}
```

## Troubleshooting

### Server not appearing in MCP Manager?

1. Check it's in `~/.claude.json → mcpServers` (user-scope)
2. Restart Claude Code
3. Verify the file path is correct and accessible

### Duplicate servers or conflicts?

1. Search `~/.claude.json` for project-level `mcpServers`
2. Remove any entries under `projects → {path} → mcpServers`
3. Keep only the user-scope registration

### Need to disable a server for specific project?

1. Use MCP Manager UI
2. Navigate to project
3. Toggle server on/off
4. Don't delete from `~/.claude.json`

## Conflict Resolution History

**2025-12-18:** Cleaned up project-level MCP server configurations
- Removed duplicate registrations from:
  - `/opt/bumba-harness/SystemTesting`
  - `/opt/bumba-harness/Desktop 12.16/bumba-project`
  - `/opt/bumba-harness/Bumba Memory`
- Migrated all servers to user-scope
- Added missing `notion` server
- Total servers: 39

## Quick Reference

```bash
# View all configured servers
grep -A 5 '"mcpServers"' ~/.claude.json | head -200

# Count servers
python3 -c "import json; print(len(json.load(open('$HOME/.claude.json'))['mcpServers']))"

# Backup configuration
cp ~/.claude.json ~/.claude.json.backup-$(date +%Y%m%d)

# Validate JSON
python3 -m json.tool ~/.claude.json > /dev/null && echo "Valid JSON" || echo "Invalid JSON"
```

---

**Remember:** The MCP Manager is your primary interface. Only edit `~/.claude.json` directly when adding new servers or troubleshooting.

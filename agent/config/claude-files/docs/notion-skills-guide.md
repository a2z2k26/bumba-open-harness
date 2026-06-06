# Notion Skills for Claude Code

**Installation Date:** 2025-12-18
**Location:** `~/.claude/skills/notion-*`
**Total Notion Skills:** 4

## Available Skills

### 1. notion-knowledge-capture

**Purpose:** Transforms conversations and discussions into structured documentation pages in Notion.

**Use When:**
- You want to save insights from a conversation to Notion
- You need to document decisions made during chat
- You want to capture knowledge for team reference
- You need to create wiki pages from discussions

**Key Features:**
- Extracts key information from conversation context
- Structures content appropriately for documentation
- Saves to wikis or databases with proper organization
- Creates discoverable links and navigation

**Typical Usage:**
```
"Save this conversation to our Engineering Wiki in Notion"
"Document these API design decisions in Notion"
"Create a Notion page capturing what we just discussed"
```

---

### 2. notion-meeting-intelligence

**Purpose:** Prepares comprehensive meeting materials by gathering context from Notion and creating structured meeting docs.

**Use When:**
- You have an upcoming meeting and need preparation materials
- You want to create a meeting agenda with background context
- You need both internal prep docs and external agenda
- You want to gather relevant information from existing Notion pages

**Key Features:**
- Gathers context from Notion workspace
- Enriches with Claude research and analysis
- Creates internal pre-read documents
- Generates external meeting agendas
- Saves all materials to Notion for team access

**Typical Usage:**
```
"Prepare materials for tomorrow's product planning meeting"
"Create a meeting agenda with background on the redesign project"
"I need a pre-read doc for the quarterly review meeting"
```

---

### 3. notion-research-documentation

**Purpose:** Searches across Notion, synthesizes findings, and creates comprehensive research documentation.

**Use When:**
- You need to research a topic across your Notion workspace
- You want to synthesize scattered information into one document
- You need a comprehensive report with citations
- You want to turn multiple pages into a structured summary

**Key Features:**
- Searches entire Notion workspace for relevant content
- Synthesizes findings from multiple pages
- Creates structured research reports
- Includes proper citations and references
- Saves results as new Notion pages with actionable insights

**Typical Usage:**
```
"Research everything we have in Notion about our authentication system"
"Create a comprehensive report on our customer feedback"
"Synthesize all Notion pages about the mobile app redesign"
```

---

### 4. notion-spec-to-implementation

**Purpose:** Turns product/tech specs into concrete implementation tasks that guide development.

**Use When:**
- You have a spec document that needs to be broken into tasks
- You want to create an implementation plan from requirements
- You need detailed tasks with acceptance criteria
- You want progress tracking for development work

**Key Features:**
- Breaks down spec pages into detailed implementation plans
- Creates clear tasks with acceptance criteria
- Sets up progress tracking in Notion
- Links tasks to original specs
- Guides development from requirements to completion

**Typical Usage:**
```
"Turn this API spec into implementation tasks"
"Create development tasks from the product requirements doc"
"Break down this technical spec into actionable items"
```

---

## How to Use These Skills

### Activation

Skills are automatically available when you invoke Claude Code. To use a specific skill:

1. **Implicit invocation:** Just describe what you want to do
   - "Save this to Notion" → may trigger knowledge-capture
   - "Prepare for my meeting" → may trigger meeting-intelligence

2. **Explicit invocation:** Reference the skill by name
   - "Use the notion-research-documentation skill to research X"
   - "I need the notion-spec-to-implementation skill for this spec"

### Prerequisites

**Required MCP Server:**
- `notion` MCP server must be enabled (already configured in your setup)
- Accessible via Claude Code MCP Manager

**Notion Setup:**
- Notion workspace with appropriate permissions
- API access configured through the Notion MCP server

### Best Practices

1. **Be specific about location:**
   - Mention workspace names, database names, or page titles
   - Example: "Save to the Engineering wiki in the Product workspace"

2. **Provide context:**
   - Share relevant background for better documentation
   - Reference existing Notion pages when applicable

3. **Review before saving:**
   - Ask to see the structured content before creating pages
   - Request modifications if needed

4. **Link and organize:**
   - Let skills create proper links and navigation
   - They'll ensure content is discoverable

## Skill Locations

All skills are installed in:
```
~/.claude/skills/
├── notion-knowledge-capture/
│   ├── SKILL.md
│   ├── examples/
│   ├── reference/
│   └── evaluations/
├── notion-meeting-intelligence/
│   ├── SKILL.md
│   ├── examples/
│   ├── reference/
│   └── evaluations/
├── notion-research-documentation/
│   ├── SKILL.md
│   ├── examples/
│   ├── reference/
│   └── evaluations/
└── notion-spec-to-implementation/
    ├── SKILL.md
    ├── examples/
    ├── reference/
    └── evaluations/
```

## Troubleshooting

### Skills not working?

1. **Check Notion MCP server is enabled:**
   - Open MCP Manager in Claude Code
   - Verify "notion" server is active
   - Test connection with a simple Notion search

2. **Verify skill installation:**
   ```bash
   ls -la ~/.claude/skills/notion-*
   ```

3. **Check skill structure:**
   - Each skill should have SKILL.md, examples/, reference/, evaluations/
   - Run the verification script above

4. **Restart Claude Code:**
   - Skills are loaded at startup
   - Restart after adding new skills

### Notion permissions issues?

1. Ensure Notion integration has proper workspace access
2. Check that you have write permissions for target databases/pages
3. Verify API token is current and valid

## Examples from Skill Documentation

Each skill includes:
- **examples/** - Sample workflows and use cases
- **reference/** - Detailed API and integration docs
- **evaluations/** - Test cases and quality checks

Explore these directories for more detailed usage examples and patterns.

---

## Related Documentation

- **MCP Server Management:** `~/.claude/docs/mcp-server-management.md`
- **Notion MCP Configuration:** `~/.claude.json` → `mcpServers.notion`
- **Skills Directory:** `~/.claude/skills/`

---

**Last Updated:** 2025-12-18
**Status:** All 4 skills successfully installed and verified ✓

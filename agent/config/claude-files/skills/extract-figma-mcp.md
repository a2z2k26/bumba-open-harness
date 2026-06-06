# Skill: Extract Design from Figma MCP

## Purpose

Extract design components directly from Figma using MCP Server tools,
without requiring the Figma Plugin to be running. This method works
through API calls and can be scripted or automated.

## When to Use

- You have a Figma URL and want to extract a component
- The Figma Plugin is not running or not available
- You need to batch-extract multiple components
- You want to automate extraction in a CI/CD pipeline

## Prerequisites

- Figma MCP Server must be connected and authenticated
- Target project must have `.design/` directory initialized
- Valid Figma file URL with appropriate permissions
- Node must be a COMPONENT or COMPONENT_SET (recommended)

## Limitations (vs Figma Plugin)

| Feature | Plugin | MCP |
|---------|--------|-----|
| Prototype reactions (click actions) | Yes | No |
| Real-time updates | Yes | No |
| Interactive state from interactions | Yes | Partial* |
| File-wide extraction | Yes | Yes |
| Batch processing | Manual | Yes |

*MCP can detect interactive states from COMPONENT_SET variant naming

## Instructions

### Step 1: Parse Figma URL

Extract the fileKey and nodeId from the provided Figma URL.

```javascript
const { parseFigmaUrl } = require('./figma-url-parser');
const parsed = parseFigmaUrl(figmaUrl);

if (!parsed.valid) {
  throw new Error(`Invalid URL: ${parsed.error}`);
}

const { fileKey, nodeId } = parsed;
```

**Expected URL formats:**
- `https://www.figma.com/file/{fileKey}/{name}?node-id={nodeId}`
- `https://www.figma.com/design/{fileKey}/{name}?node-id={nodeId}`

### Step 2: Fetch Node Data

Use MCP tools to retrieve the node data from Figma.

```
Use mcp__mcp-figma__get_file_nodes with:
- fileKey: "{extracted fileKey}"
- node_ids: ["{nodeId}"]
- depth: 4

Example:
mcp__mcp-figma__get_file_nodes({
  fileKey: "abc123XYZ",
  node_ids: ["123:456"],
  depth: 4
})
```

### Step 3: Fetch File Styles

Retrieve the file's style definitions for token mapping.

```
Use mcp__mcp-figma__get_file_styles with:
- fileKey: "{extracted fileKey}"

This returns color styles, text styles, and effect styles
that can be mapped to token names.
```

### Step 4: Transform to Design Bridge Format

Convert the Figma response to Design Bridge component format.

```javascript
const { transformMcpResponse } = require('./figma-transformer');
const components = transformMcpResponse(mcpResponse, fileKey);
```

### Step 5: Detect Interactive States

For COMPONENT_SET nodes, analyze variants to detect interactive states.

```javascript
// Look for variants with state naming:
// - "State=Default", "State=Hover", "State=Pressed"
// - "default", "hover", "pressed" in name

const interactiveStates = detectInteractiveStates(componentSet);
```

### Step 6: Write to Source Directory

Save the transformed component to the source directory.

```javascript
const outputPath = `.design/source/components/${componentName.toLowerCase()}.json`;
fs.writeFileSync(outputPath, JSON.stringify(component, null, 2));
```

### Step 7: Update Registry

Add the component to the registry with source tracking.

```javascript
registry.components[componentId] = {
  name: component.name,
  figmaId: component.figmaId,
  source: {
    type: "figma-mcp",
    fileKey: fileKey,
    nodeId: nodeId,
    extractedAt: new Date().toISOString()
  },
  tokenDependencies: component.tokenDependencies,
  paths: {
    rawSource: outputPath,
    codeOutput: `src/components/${component.name}.tsx`
  }
};
```

## Expected Output

```
Parsed Figma URL: abc123XYZ / 123:456
Fetched node data: "Button" (COMPONENT_SET)
Fetched 12 styles from file
Transformed to Design Bridge format
Detected 2 interactive states (hover, pressed)
Written to: .design/source/components/button.json
Registry updated: button-figma-123

Extraction complete!
  Component: Button
  Source: figma-mcp
  Tokens: 3 colors, 1 typography
  States: hover, pressed
```

## Configuration

```javascript
// In .design/config.json
{
  "figmaMcp": {
    "defaultDepth": 4,
    "preserveFigmaProperties": true,
    "autoDetectStates": true
  }
}
```

## Troubleshooting

### "Invalid Figma URL format"
Ensure URL matches: `figma.com/file/{key}` or `figma.com/design/{key}`

### "MCP Server not connected"
Run: Check MCP server configuration and authentication

### "Node not found"
Verify the node-id exists in the file. The node may have been deleted.

### "Permission denied"
Ensure your Figma API token has read access to the file.

### "No styles found"
The file may not have any published styles. Colors will be extracted as raw values.

## Quick Reference

| MCP Tool | Purpose |
|----------|---------|
| `mcp__mcp-figma__get_file` | Get entire file structure |
| `mcp__mcp-figma__get_file_nodes` | Get specific nodes by ID |
| `mcp__mcp-figma__get_file_styles` | Get file style definitions |
| `mcp__mcp-figma__get_file_components` | List all components in file |
| `mcp__mcp-figma__get_image` | Export node as image |

## Related Skills

- `/extract-figma` - Extract using Figma Plugin (more features)
- `/transform` - Transform extracted components to code
- `/design-init` - Initialize .design/ directory structure

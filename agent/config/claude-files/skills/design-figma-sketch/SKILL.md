---
name: design-figma-sketch
description: Start bidirectional chat with Figma plugin for design creation
version: 1.0.0
author: BUMBA
tags: [figma, design, mcp, websocket, chat]
---

# Design Figma Sketch

Start a bidirectional design chat session with the Figma plugin. This skill:
1. Starts the WebSocket server for Figma plugin communication
2. Starts the design-bridge server for token extraction
3. Connects to the bumba-figma MCP server
4. Joins your Figma channel
5. Listens continuously for design requests from the Figma plugin

## Prerequisites

- Figma plugin running with CREATE tab open
- bumba-figma MCP server configured in user settings
- WebSocket server at: `/opt/bumba-harness/Bumba - Design/claude-talk-to-figma-mcp-main`
- Design-bridge server at: `/opt/bumba-harness/Documents/bumba-project/server`
- THEME.js file at: `/opt/bumba-harness/Documents/bumba-project/src/design-system/THEME.js`

## Usage

When the user invokes this skill:

1. **Check running servers**
   - Check if WebSocket server is running on port 3055
   - Check if design-bridge server is running on ports 9001/9002
   - Start any missing servers in background

2. **Verify MCP connection**
   - Confirm bumba-figma MCP is connected
   - If not, instruct user to run `/mcp` to connect

3. **Get channel ID**
   - Ask user for their current Figma channel ID from the CREATE tab
   - The channel ID is shown in the plugin (e.g., "G2K7NY")

4. **Connect and listen**
   - Use `join_channel` with the provided channel ID
   - Load THEME.js for design reference
   - Start continuous listening loop with `wait_for_prompt`
   - Process design requests using bumba-figma MCP tools
   - Use BUMBA THEME.js styling for all designs

5. **Design execution**
   - Receive user messages from Figma plugin
   - Interpret design requests
   - Use bumba-figma MCP tools to create designs
   - Apply BUMBA design tokens (colors, typography, spacing)
   - Continue listening for next request

## Important Notes

- Keep servers running in background throughout session
- Use THEME.js for all color, typography, and spacing decisions
- Always apply design tokens instead of hardcoded values
- Listen continuously - don't stop after one request
- If channel ID changes, user must provide new ID to reconnect

## Example Interaction

User: "/design-figma-sketch"
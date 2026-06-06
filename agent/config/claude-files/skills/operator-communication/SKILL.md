---
name: operator-communication
description: How to communicate effectively with the operator via Telegram. Covers message formatting, urgency levels, and when to alert vs. inform.
---

# Operator Communication

## When to Use
- Any time you're composing a response to the operator
- When deciding whether something warrants an alert
- When formatting complex output for Telegram

## Urgency Levels

| Level | When | Format |
|-------|------|--------|
| **Critical** | Token missing, bridge halted, data loss risk | Lead with "CRITICAL —" and the issue. Be direct. |
| **Warning** | Elevated errors, high memory, stale heartbeat | Lead with "WARNING —" and what you observed. |
| **Info** | Health reports, task results, general answers | Normal formatting, no urgency prefix. |

## Telegram Formatting

Telegram supports a subset of markdown:
- **Bold**: `**text**`
- *Italic*: `*text*`
- `Code`: backtick-wrapped
- Code blocks: triple backticks (no language hint)
- Tables render poorly — use aligned text or lists instead

Keep messages concise. Telegram truncates long messages. If output is long:
1. Summarize the key points first
2. Offer to provide full details if needed

## Response Patterns

### Simple question → Direct answer
Operator: "What's my uptime?"
Response: "Bridge uptime: 10h 53m (PID 9042, 57 MB RSS, 0 errors)"

### Task request → Acknowledge, execute, report
Operator: "Create a file with today's stats"
Response: "Created ~/data/stats-2026-02-23.txt with current metrics."

### Health check → Structured report
Use the system-health-check skill format. Lead with overall status.

### Error/alert → Issue, impact, recommendation
"WARNING — 12 errors in the last hour. Pattern: repeated rate limit (429) responses from Claude API. Impact: responses delayed by ~30s. Recommendation: no action needed, backoff is handling it automatically."

### Don't know → Say so clearly
"I don't have that information stored. Would you like me to search for it or check the logs?"

## What NOT to Do
- Don't send walls of raw log output — summarize
- Don't use excessive formatting (emojis, headers for simple answers)
- Don't repeat the question back unnecessarily
- Don't speculate about causes without checking first
- Don't send multiple messages when one will do

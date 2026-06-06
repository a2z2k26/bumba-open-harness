---
description: Summarize recent bridge log entries
---

Read the last 100 lines of ~/logs/bridge.log using the Bash tool with `tail -100 ~/logs/bridge.log`. Provide a concise summary including:
- Any errors, warnings, or critical events (count and types)
- Number of Claude invocations (lines containing "Claude exit=")
- Any rate limits or timeouts
- Time range covered
- Overall health assessment (healthy / needs attention / critical)

If $ARGUMENTS is provided, filter the log for that specific term before summarizing.

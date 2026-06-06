---
description: Run a comprehensive system health check
---

Run a full system health diagnostic. Check bridge process status, resource usage (memory RSS, CPU, disk), database health (size, message count, error count, queue depth), heartbeat freshness, halt flag, and token status. Present findings as a structured health report with alerts and recommendations.

Use the system-health-check skill diagnostic steps: check bridge PID, heartbeat, resources via `ps`, database via `sqlite3 ~/data/memory.db`, recent errors in `~/logs/bridge.log`, and token presence in `~/data/.secrets`.

If $ARGUMENTS is provided, focus on that specific area (e.g., "database", "memory", "errors", "logs").

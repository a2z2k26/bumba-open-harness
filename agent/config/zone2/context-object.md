# Bumba — Context Object

*The unified context object: what the agent knows right now.*

---

## Purpose

The context object answers: "What is the current state of everything I'm responsible for?" It's assembled on cold start by the briefing service, updated incrementally by other services, and consumed by check-in decisions and voice session context injection.

## Schema

```json
{
  "built_at": "2026-03-05T07:30:00-05:00",
  "operator": {
    "last_contact": "2026-03-05T14:30:00-05:00",
    "last_contact_hours_ago": 2.5,
    "active_project": "bumba-open-harness"
  },
  "schedule": {
    "next_event": {
      "title": "Client sync",
      "start": "2026-03-05T15:00:00-05:00",
      "location": "Zoom",
      "minutes_until": 28
    },
    "today_count": 4,
    "conflicts": []
  },
  "inbox": {
    "unread_total": 12,
    "unread_urgent": 1,
    "last_check": "2026-03-05T12:00:00-05:00"
  },
  "goals": {
    "active": [
      {"key": "goal:deploy-zone2", "deadline": "2026-03-07", "status": "active"}
    ],
    "overdue": []
  },
  "system": {
    "uptime_hours": 48.2,
    "error_count_1h": 0,
    "halt_flag": false,
    "disk_free_gb": 45.3
  },
  "knowledge": {
    "entries_active": 234,
    "entries_updated_24h": 5,
    "entries_low_salience": 12
  },
  "escalation": {
    "current_level": 0,
    "unanswered_checkins": 0,
    "last_escalation": null
  }
}
```

## Data Sources

| Field | Source | Query |
|-------|--------|-------|
| `operator.last_contact` | `conversations` table | `MAX(created_at) WHERE role='user'` |
| `operator.active_project` | `data/service_state/track.json` | Current project name |
| `schedule.next_event` | `calendar_interface.get_upcoming_events(hours=4)` | First upcoming |
| `schedule.today_count` | `calendar_interface.get_today_events()` | len() |
| `inbox.unread_total` | `gmail_interface.get_unread_count()` | Sum across accounts |
| `inbox.unread_urgent` | `gmail_interface.get_unread_messages()` | Count starred/flagged |
| `goals.active` | `knowledge` table | `WHERE key LIKE 'goal:%' AND archived=0` |
| `goals.overdue` | Same query | Filter deadline < now |
| `system.uptime_hours` | PID file mtime | `now - mtime` |
| `system.error_count_1h` | `audit_log` table | `COUNT WHERE timestamp > now-1h` |
| `system.halt_flag` | `data/halt.flag` | File exists check |
| `system.disk_free_gb` | `shutil.disk_usage()` | Free bytes / 1e9 |
| `knowledge.*` | `knowledge` table | COUNT queries |
| `escalation.*` | `data/service_state/checkin-state.json` | State file |

## Assembly

**Full build** (briefing service, daily at 7:30am):
- Queries ALL data sources
- Writes complete object to `data/service_state/context.json`
- Takes <500ms (all local: SQLite + file reads, no API calls except calendar/email which are optional)

**Partial update** (other services, on each run):
- Each service updates only its section
- Reads existing context.json, merges, writes back
- Calendar updates: `schedule` section
- Email updates: `inbox` section
- Check-in updates: `escalation` section

## Consumers

| Consumer | What It Reads | When |
|----------|--------------|------|
| CheckinService | Full context | Every check-in for escalation decision |
| Voice fast-path | Summary (~200 tokens) | Every voice transcription |
| BriefingService | Builds it | Morning |
| (future) Dashboard | Full context | On demand |

## Voice Context Summary Format

For voice injection, the full context is summarized to ~200 tokens:

```
Context: 2 meetings today (next: Client sync in 28 min @ Zoom). 12 unread emails (1 urgent).
3 active goals, none overdue. System healthy, 48h uptime.
```

This summary is cached for 5 minutes to avoid re-reading on every utterance.

## Storage

- **Path:** `data/service_state/context.json`
- **Owner:** `bumba-agent:staff`
- **Permissions:** 644
- **Updated by:** Any service via partial merge
- **Read by:** Check-in, voice, briefing

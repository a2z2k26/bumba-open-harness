# Bumba — Rhythm Schema

*The agent's daily rhythm. What runs when, and why.*

---

## Daily Timeline

| Time | Service | Mode | Trigger Type | Purpose |
|------|---------|------|-------------|---------|
| 3:00 AM | maintenance.sh | Full run | `StartCalendarInterval` | DB backup, log rotation, cleanup |
| 7:00 AM | CalendarService | Morning digest | `StartInterval: 900` | the operator sees his day before coffee |
| 7:30 AM | BriefingService | Full briefing | `StartCalendarInterval` | Goals, health, knowledge, schedule |
| 9:00 AM | EmailService | First digest | `StartInterval: 7200` | First inbox pass, categorized |
| 9:00 AM–10:00 PM | EmailService | Digest cycle | `StartInterval: 7200` | Every 2h: inbox awareness |
| 7:00 AM–10:00 PM | CalendarService | Alert check | `StartInterval: 900` | Every 15m: 30-min advance warnings |
| 8:00 AM–10:00 PM | CheckinService | Escalation check | `StartInterval: 3600` | Hourly: proactive nudges |
| 6:00 PM | RetroService | EOD retro | `StartCalendarInterval` | Activity, open loops, tomorrow preview |
| 6:00 PM (Sun) | WeeklyReviewService | Weekly review | `StartCalendarInterval` | 7-day trends, patterns, system health |
| 11:00 PM | KnowledgeReviewService | Nightly review | `StartCalendarInterval` | Memory hygiene before sleep |

## Time Windows

- **Active hours:** 7:00 AM – 10:00 PM (services self-gate via `should_run()`)
- **Extended hours:** 10:00 PM – 1:00 AM (monitoring only, no outbound messages)
- **Quiet hours:** 1:00 AM – 7:00 AM (only critical alerts: system halt, security)

## Service Priority (Conflict Resolution)

When multiple services want to deliver simultaneously:

1. Calendar alerts (time-sensitive, 30-min window)
2. Urgent email (starred/flagged)
3. Check-in (escalation level 2+)
4. Email digest
5. Knowledge review

The bridge delivers service messages in filesystem sort order. Services use timestamped filenames, so natural delivery order matches creation order.

## Dedup Rules

Each service manages its own dedup:

| Service | Dedup Key | Guard |
|---------|-----------|-------|
| BriefingService | `last_briefing_date` | Once per calendar day |
| CheckinService | `last_checkin_time` | Minimum 2h gap + snooze |
| EmailService | `last_check_time` + `last_digest_count` | 2h gap + skip if count unchanged |
| CalendarService (morning) | `last_morning_date` | Once per calendar day |
| CalendarService (alert) | `alerted_events` set | Per-event ID, keep last 50 |
| KnowledgeReviewService | `last_review_date` | Once per calendar day |
| RetroService | `last_retro_date` | Once per calendar day |
| WeeklyReviewService | `last_review_week` | Once per ISO week (`%Y-W%W`) |

## LaunchDaemon Schedule Types

**`StartCalendarInterval`** — fires at a specific wall-clock time. Used for: briefing (7:30am), knowledge review (11pm), maintenance (3am).

**`StartInterval`** — fires every N seconds. Used for: email (7200s), calendar (900s), checkin (3600s).

**`RunAtLoad: true`** — fires immediately on daemon bootstrap. Used for interval-based services so first run doesn't wait.

## Integration Points

- **Briefing** calls `context_builder.build_context()` to assemble the full context object
- **Calendar alerts** from CalendarService are independent of the briefing schedule source
- **Check-in** reads context object for escalation decisions (level 2+ uses Claude)
- All services write to `data/service_messages/` → bridge polls every ~2s → Discord delivery

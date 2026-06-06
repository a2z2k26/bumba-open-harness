# Bumba — Proactive Jobs

*Jobs the agent runs without being asked. Maps to Zone 2 master functions.*

---

## Job Categories

### OBSERVE (passive data gathering, no output)

| Job | Service | Frequency | What It Watches |
|-----|---------|-----------|-----------------|
| Inbox monitor | EmailService | Every 2h | Unread count per account |
| Calendar watch | CalendarService | Every 15m | Event changes, new bookings |
| Goal tracker | CheckinService | Every 1h | Deadline proximity, overdue status |
| Knowledge decay | KnowledgeReviewService | Daily 11pm | Salience approaching archive threshold |
| System health | monitor.sh | Hourly | Bridge process, heartbeat, disk, token |

### ALERT (triggered output when conditions met)

| Job | Trigger Condition | Escalation | Output |
|-----|-------------------|------------|--------|
| Upcoming meeting | Event starts within 30 min | Level 2 (NUDGE) | Time, title, location, meeting URL |
| Urgent email | Starred/flagged message from known sender | Level 2 (NUDGE) | Sender, subject, snippet |
| Goal deadline | Goal due within 24 hours | Level 2 (URGENT) | Goal description, deadline |
| Overdue goal | Goal past deadline | Level 3 (URGENT) | Goal description, how overdue |
| System anomaly | 5+ errors in 1h, halt flag, disk <5GB | Level 3 (URGENT) | Error summary, recommended action |
| Knowledge reinforcement | Accessed entry with salience <0.5 | Level 0 (SILENCE) | Auto-reinforce +0.1, no message |

### DIGEST (scheduled compilation)

| Job | Schedule | Content |
|-----|----------|---------|
| Morning briefing | 7:30 AM daily | Goals, activity, knowledge updates, schedule, health |
| Calendar timeline | 7:00 AM daily | Full day: all-day events, timed events, Cal.com bookings, conflicts |
| Email digest | Every 2h (9am-10pm) | Per-account unread: urgent, actionable, informational |
| Knowledge review | 11:00 PM daily | Low-salience entries, duplicates, recently archived, stats |
| EOD retro | 6:00 PM daily | Today's activity, goals status, open loops, tomorrow preview |
| Weekly review | Sunday 6:00 PM | 7-day activity, goals lifecycle, knowledge growth, system reliability, patterns |

## Job Schema

Every proactive job has:

```yaml
name: "Upcoming meeting alert"
category: alert          # observe | alert | digest
service: CalendarService
trigger:
  type: threshold        # time | interval | threshold
  condition: "event.start_minutes_until <= 30"
guard:
  active_hours: [7, 22]
  min_interval_s: 900
  dedup_key: "alerted_events"
output:
  format: text
  escalation: 2
  buttons: null
master_function: MONITOR  # from zone-plan.md
```

## Master Function Coverage

| # | Function | Jobs | Status |
|---|----------|------|--------|
| 1 | CAPTURE | (voice transcription persistence) | Sprint B19 |
| 2 | ORGANISE | Email categorization, knowledge review | Active |
| 3 | REMEMBER | Knowledge decay/reinforcement, context object | Active |
| 6 | PRIORITISE | Goal deadline tracking, escalation logic, EOD open loops | Active |
| 7 | COACH | Check-in nudges (level 1-3), weekly pattern review | Active |
| 10 | COMMUNICATE | Email digest delivery, calendar alerts | Active |
| 12 | MONITOR | System health, inbox watch, calendar watch | Active |
| 13 | ANTICIPATE | Goal deadline proximity, meeting prep alerts | Active |

## Adding New Jobs

1. Determine category (observe/alert/digest)
2. Map to a master function from zone-plan.md
3. Implement in the appropriate service class
4. Add dedup guard to prevent spam
5. Set escalation level per escalation-logic.md
6. Update rhythm-schema.md if schedule changes

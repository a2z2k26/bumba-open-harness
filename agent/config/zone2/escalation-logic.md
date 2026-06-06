# Bumba — Escalation Logic

*When the agent escalates from passive to active to urgent.*

---

## Escalation Levels

| Level | Name | When | Output | Example |
|-------|------|------|--------|---------|
| 0 | SILENCE | Default state, nothing noteworthy | None | All green, recent contact |
| 1 | CASUAL | Informational, no action needed | Scheduled digest | "3 new emails, none urgent" |
| 2 | NUDGE | Action suggested but not critical | Proactive message | "Meeting in 30 min" |
| 3 | URGENT | Requires attention now | Direct message | "Client deliverable overdue" |

## Trigger Matrix

### Time-Based Triggers

| Condition | Level |
|-----------|-------|
| <3h since last operator contact | 0 (SILENCE) |
| 3-6h since last contact, no pending items | 1 (CASUAL) |
| 3-6h since last contact, pending items exist | 2 (NUDGE) |
| 6h+ since last contact | 2 (NUDGE) |
| 6h+ since last contact + overdue goals | 3 (URGENT) |

### Event-Based Triggers

| Condition | Level |
|-----------|-------|
| Meeting in 30 minutes | 2 (NUDGE) |
| Starred/flagged email from known sender | 2 (NUDGE) |
| Goal deadline within 24 hours | 2 (NUDGE) |
| Goal past deadline | 3 (URGENT) |
| Multiple unanswered check-ins (2+) | escalate by +1 |
| System halt flag set | 3 (URGENT) |
| 5+ errors in 1 hour | 3 (URGENT) |
| Disk space <5GB | 3 (URGENT) |

### Compound Triggers

| Condition | Level |
|-----------|-------|
| Overdue goal + 2 unanswered check-ins | 3 (URGENT) → CALL_REQUEST |
| Critical deadline (<2h) + no contact in 4h+ | 3 (URGENT) → CALL_REQUEST |

## De-escalation Rules

- **Operator response** at any level → reset to level 0
- **Snooze button** → delay re-check by 30m/1h/2h (operator chooses)
- **Dismiss button** → reset unanswered check-in counter to 0
- **Goal completed** → remove from escalation triggers

## Service Mapping

| Service | Escalation Range | Decision Method |
|---------|-----------------|-----------------|
| BriefingService | Always level 1 | Scheduled, no escalation |
| EmailService | 1-2 | Urgent email → level 2, else level 1 |
| CalendarService | 1-2 | Upcoming event → level 2, digest → level 1 |
| CheckinService | 0-3 | Rule-based (0-1), Claude-assisted (2-3) |
| KnowledgeReviewService | Always level 1 | Scheduled, no escalation |
| monitor.sh | 2-3 | Threshold-based, direct Discord API |

## Check-in Escalation Detail

The CheckinService uses a two-tier decision process:

**Level 0-1 (rule-based, no API cost):**
- Level 0: <3h since contact AND no overdue goals → SILENCE
- Level 1: 3h+ since contact → friendly nudge

**Level 2-3 (Claude-assisted when context object available):**
- Reads `data/service_state/context.json`
- Injects into Claude decision prompt (CHECKIN_DECISION_PROMPT in checkin.py)
- Claude decides message content and appropriate tone
- Fallback: if Claude call fails, use rule-based decision
- Cost guard: max 1 Claude-assisted check-in per 4 hours

## Quiet Hours Override

During quiet hours (1am-7am), only level 3 alerts are delivered:
- System halt
- Security breach
- Critical infrastructure failure

All other messages are queued and delivered at 7:00 AM with the morning briefing.

## Message Formatting

| Level | Format |
|-------|--------|
| 0 | (no message) |
| 1 | Plain text, no prefix |
| 2 | Bold prefix: **Heads up:** |
| 3 | Bold + urgent: **URGENT:** |
| CALL_REQUEST | **URGENT — Please respond:** + reason |

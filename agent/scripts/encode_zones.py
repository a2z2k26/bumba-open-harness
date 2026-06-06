#!/usr/bin/env python3
"""One-time migration: encode zone architecture into knowledge table."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Add agent root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bridge.database import Database
from bridge.memory import Memory

ZONE_ENTRIES = [
    {
        "key": "zone:architecture",
        "value": (
            "Concentric zones radiating outward: "
            "Zone 1 (Identity) -> Zone 2 (Always-On) -> Zone 3 (Engineering) -> Zone 4 (Departments). "
            "Each zone is a prerequisite for the next. "
            "Zone 1 must cold-start correctly before Zone 2 services activate."
        ),
        "category": "process",
        "tags": "zone,architecture",
    },
    {
        "key": "zone:1:identity",
        "value": (
            "Zone 1 — Core Identity. Soul, rhythm, guiding principles, understanding of operator, "
            "sense of purpose and intent. Must contain: system prompt (bootstrap files), operator profile, "
            "core principles (P1-P25), zone architecture, self-improvement protocol. "
            "Cold-start = instant resumption, not reconstruction."
        ),
        "category": "process",
        "tags": "zone,identity",
    },
    {
        "key": "zone:2:always-on",
        "value": (
            "Zone 2 — Always-On Functions. Persistent cron-driven behaviors: "
            "morning briefings (08:00), health checks, escalation monitoring, "
            "email management (every 2h), calendar sync (every 15m), "
            "knowledge review (23:00 daily). These run continuously via LaunchDaemons."
        ),
        "category": "process",
        "tags": "zone,services",
    },
    {
        "key": "zone:3:engineering",
        "value": (
            "Zone 3 — Engineering (CTO Function). Complex software projects built using "
            "Specification-Driven Development (SDD) via Spec-Kit. Each project follows: "
            "specify -> plan -> tasks -> implement. Each project has a YAML registry file "
            "in data/projects/. Track switching: 'Switch to [Name]' loads context, "
            "'Switch to System' returns to zone work."
        ),
        "category": "process",
        "tags": "zone,engineering",
    },
    {
        "key": "zone:4:departments",
        "value": (
            "Zone 4 — Departments (/board). Sub-agent teams: analyst, strategist, critic, researcher. "
            "Future additions: Marketing, Image Gen, others. Bumba orchestrates, routes, and maintains "
            "coherence. Shared memory MCP ready for multi-agent coordination. "
            "Persona archive (169 domain-expert references) available."
        ),
        "category": "process",
        "tags": "zone,departments",
    },
    {
        "key": "zone:functions",
        "value": (
            "Master function registry (15 functions across zones): "
            "Z1: Identity persistence, operator model, principle enforcement. "
            "Z2: Briefing, check-in, email, calendar, escalation, health. "
            "Z3: Project registry, track switching, SDD, deploy, validate. "
            "Z4: Board meetings, sub-agent routing, department management."
        ),
        "category": "process",
        "tags": "zone,functions",
    },
    {
        "key": "zone:rules",
        "value": (
            "Architecture design rules: "
            "1. Each zone is a prerequisite for the next. "
            "2. Zone 1 must survive cold restart. "
            "3. Services in Zone 2 must be idempotent. "
            "4. Zone 3 projects are isolated via track switching. "
            "5. Zone 4 agents cannot modify Zone 1 identity. "
            "6. All zones share the same SQLite database. "
            "7. MCP servers are cross-cutting infrastructure. "
            "8. Cron schedules are defined in LaunchDaemon plists. "
            "9. Commands and skills are Zone 3 artifacts. "
            "10. Hooks are kernel-protected (Tier C). "
            "11. Deploy helper classifies changes by tier. "
            "12. Self-improvement is bounded by tier system. "
            "13. Operator profile is Zone 1 (Tier B). "
            "14. One rule, one home (no duplication). "
            "15. Documents are living. "
            "16. Meta-rule: these rules are themselves Zone 1."
        ),
        "category": "process",
        "tags": "zone,rules",
    },
]


async def main():
    db_path = "/opt/bumba-harness/data/memory.db"
    if not Path(db_path).exists():
        print(f"Database not found at {db_path}, using test path")
        db_path = "/tmp/test-zone-encode.db"

    db = Database(db_path)
    await db.connect()
    await db.migrate()

    memory = Memory(db)

    for entry in ZONE_ENTRIES:
        await memory.store_knowledge(
            key=entry["key"],
            value=entry["value"],
            tags=entry["tags"],
            category=entry["category"],
            source="zone-plan",
        )
        print(f"  Stored: {entry['key']}")

    print(f"\nEncoded {len(ZONE_ENTRIES)} zone knowledge entries")

    # Verify searchability
    results = await memory.search_knowledge("zone 1")
    print(f"Search 'zone 1': {len(results)} result(s)")
    if results:
        print(f"  Top result: {results[0]['key']}")

    await db.close()


if __name__ == "__main__":
    asyncio.run(main())

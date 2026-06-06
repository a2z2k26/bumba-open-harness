"""SQLite persistence for the Skill Journey ledger.

Sprint S11: stores skill_journey + skill_agent_proficiency tables.
E4.8: adds `assignment` column (main | global | <team_name>) to skill_journey.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from bridge.skill_journey import AgentProficiency, SkillRecord

log = logging.getLogger(__name__)

_SKILL_SCHEMA = """
CREATE TABLE IF NOT EXISTS skill_journey (
    name TEXT PRIMARY KEY,
    tier TEXT NOT NULL CHECK (tier IN ('experimental','graduated','canonical')),
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    total_runs INTEGER NOT NULL DEFAULT 0,
    last_run_at TEXT,
    promoted_at TEXT,
    demoted_at TEXT
);

CREATE TABLE IF NOT EXISTS skill_agent_proficiency (
    skill TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    last_run_at TEXT,
    PRIMARY KEY (skill, agent_id)
);
"""


# E4.8 — idempotent migration: adds assignment column with default 'main'.
# Guarded by user_version pragma so it runs exactly once per database file.
_ASSIGNMENT_MIGRATION_VERSION = 1
_ASSIGNMENT_MIGRATION = """
ALTER TABLE skill_journey ADD COLUMN assignment TEXT NOT NULL DEFAULT 'main';
"""


class SkillStore:
    """SQLite-backed store for skill journey records."""

    def __init__(self, db_path: Path | str = ":memory:") -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SKILL_SCHEMA)
        self._apply_migrations()
        self._seed_canonical_skills()

    def _apply_migrations(self) -> None:
        """Apply additive schema migrations exactly once, guarded by user_version."""
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version < _ASSIGNMENT_MIGRATION_VERSION:
            try:
                self._conn.execute(_ASSIGNMENT_MIGRATION.strip())
                self._conn.commit()
            except sqlite3.OperationalError as exc:
                if "duplicate column" not in str(exc).lower():
                    raise
            # L-4 (P8.3 #1749): PRAGMA value is a module-constant int so this is
            # safe today, but the f-string pattern is a copy-paste footgun.
            # SQLite does not support parameter binding inside PRAGMA, so
            # fold the constant into the literal SQL text up-front instead of
            # interpolating at execute() time.
            self._conn.execute(
                "PRAGMA user_version = " + str(int(_ASSIGNMENT_MIGRATION_VERSION))
            )
            self._conn.commit()

    def _seed_canonical_skills(self) -> None:
        """Seed the 3 canonical skills if they don't exist."""
        canonical_skills = ["fix-test", "review-pr", "ship-feature"]
        for skill in canonical_skills:
            exists = self._conn.execute(
                "SELECT 1 FROM skill_journey WHERE name = ?", (skill,)
            ).fetchone()
            if not exists:
                self._conn.execute(
                    """INSERT INTO skill_journey
                       (name, tier, success_count, failure_count, total_runs)
                       VALUES (?, 'experimental', 0, 0, 0)""",
                    (skill,),
                )
        self._conn.commit()

    def get_skill(self, name: str) -> SkillRecord | None:
        """Return a SkillRecord by name, or None."""
        row = self._conn.execute(
            """SELECT name, tier, success_count, failure_count, total_runs,
                      last_run_at, promoted_at, demoted_at
               FROM skill_journey WHERE name = ?""",
            (name,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def upsert_skill(self, rec: SkillRecord) -> None:
        """Insert or update a SkillRecord."""
        self._conn.execute(
            """INSERT INTO skill_journey
               (name, tier, success_count, failure_count, total_runs,
                last_run_at, promoted_at, demoted_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                 tier = excluded.tier,
                 success_count = excluded.success_count,
                 failure_count = excluded.failure_count,
                 total_runs = excluded.total_runs,
                 last_run_at = excluded.last_run_at,
                 promoted_at = excluded.promoted_at,
                 demoted_at = excluded.demoted_at""",
            (
                rec.name,
                rec.tier,
                rec.success_count,
                rec.failure_count,
                rec.total_runs,
                rec.last_run_at,
                rec.promoted_at,
                rec.demoted_at,
            ),
        )
        self._conn.commit()

    def list_skills(self) -> list[SkillRecord]:
        """Return all skill records."""
        rows = self._conn.execute(
            """SELECT name, tier, success_count, failure_count, total_runs,
                      last_run_at, promoted_at, demoted_at
               FROM skill_journey ORDER BY name"""
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def get_agent_proficiency(self, skill: str, agent_id: str) -> AgentProficiency | None:
        """Return per-agent proficiency for a skill."""
        row = self._conn.execute(
            """SELECT skill, agent_id, success_count, failure_count, last_run_at
               FROM skill_agent_proficiency WHERE skill = ? AND agent_id = ?""",
            (skill, agent_id),
        ).fetchone()
        if row is None:
            return None
        return AgentProficiency(
            skill=row[0],
            agent_id=row[1],
            success_count=row[2],
            failure_count=row[3],
            last_run_at=row[4],
        )

    def upsert_agent_proficiency(self, prof: AgentProficiency) -> None:
        """Insert or update per-agent proficiency."""
        self._conn.execute(
            """INSERT INTO skill_agent_proficiency
               (skill, agent_id, success_count, failure_count, last_run_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(skill, agent_id) DO UPDATE SET
                 success_count = excluded.success_count,
                 failure_count = excluded.failure_count,
                 last_run_at = excluded.last_run_at""",
            (
                prof.skill,
                prof.agent_id,
                prof.success_count,
                prof.failure_count,
                prof.last_run_at,
            ),
        )
        self._conn.commit()

    def list_agent_proficiencies(self, skill: str) -> list[AgentProficiency]:
        """Return all agent proficiencies for a skill."""
        rows = self._conn.execute(
            """SELECT skill, agent_id, success_count, failure_count, last_run_at
               FROM skill_agent_proficiency WHERE skill = ? ORDER BY agent_id""",
            (skill,),
        ).fetchall()
        return [
            AgentProficiency(
                skill=r[0], agent_id=r[1],
                success_count=r[2], failure_count=r[3], last_run_at=r[4],
            )
            for r in rows
        ]

    def set_assignment(self, name: str, assignment: str) -> None:
        """Set the assignment scope for a skill (main | global | <team_name>)."""
        self._conn.execute(
            "UPDATE skill_journey SET assignment = ? WHERE name = ?",
            (assignment, name),
        )
        self._conn.commit()

    def get_assignment(self, name: str) -> str | None:
        """Return the assignment scope for a skill, or None if not found."""
        row = self._conn.execute(
            "SELECT assignment FROM skill_journey WHERE name = ?", (name,)
        ).fetchone()
        return row[0] if row else None

    def skills_for_team(self, team: str) -> list[SkillRecord]:
        """Return skills assigned to a team or globally available.

        Returns skills with assignment == team OR assignment == 'global'.
        Global skills are available to every team's chief.
        """
        rows = self._conn.execute(
            """SELECT name, tier, success_count, failure_count, total_runs,
                      last_run_at, promoted_at, demoted_at
               FROM skill_journey
               WHERE assignment = ? OR assignment = 'global'
               ORDER BY name""",
            (team,),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _row_to_record(row: tuple) -> SkillRecord:
        name, tier, sc, fc, total, last_run, promoted, demoted = row
        return SkillRecord(
            name=name,
            tier=tier,  # type: ignore[arg-type]
            success_count=sc,
            failure_count=fc,
            total_runs=total,
            last_run_at=last_run,
            promoted_at=promoted,
            demoted_at=demoted,
        )

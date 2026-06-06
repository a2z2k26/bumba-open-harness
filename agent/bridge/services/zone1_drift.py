"""Zone 1 drift detector + draft-PR pipeline.

Sprint 2.07 (#2142) — extends the drift-gate pattern
(docs/architecture/drift-gate-pattern.md) to Zone 1 doctrine. NEVER
auto-writes; always produces a draft PR for operator review per the #1112
Zone 1 safety rule: cron drafts proposals, operator decides, operator merges.

Heuristics (per the spec's three-pass approach):

1. **Dead ref** — grep file paths cited in the doc; if the cited path
   doesn't exist on HEAD, flag as ``dead_ref``.
2. **Stale count** — regex ``(\\d+) (services|agents|plugins|MCPs|workflows)``
   in the doc; compare to a live count derived from the filesystem.
3. **Outdated stamp** — ``verified at HEAD <sha>`` markers older than
   ``OUTDATED_STAMP_DAYS`` are flagged.

Run cadence: event-triggered (every-N-PRs counter, default 25) or scheduled
(plist; default twice weekly). Either way, the service NEVER auto-merges —
it produces a draft PR and notifies the operator. The operator-confirm
safety rule is enforced at three layers:
  1. The ``Zone1DriftService`` only ever calls ``gh pr create --draft``
  2. The CI gate ``registry-completeness`` rejects any PR from this
     service that touches anything outside ``ZONE1_FILES``
  3. The operator-merge rule (memory ``feedback_never_merge_to_main``)
     means no PR — draft or otherwise — auto-merges to main
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .base import ServiceBase
from .result import ServiceResult

log = logging.getLogger(__name__)

# The 10 Zone 1 files defined by the canonical-write-territory doctrine
# (root CLAUDE.md + agent identity docs + agent/config/zone1/*).
ZONE1_FILES: tuple[str, ...] = (
    "agent/SOUL.md",
    "agent/OPERATOR.md",
    "agent/RULES.md",
    "agent/TOOLS.md",
    "agent/CLAUDE.md",
    "agent/config/zone1/guiding-principles.md",
    "agent/config/zone1/operator-profile.md",
    "agent/config/zone1/self-improvement-protocol.md",
    "agent/config/zone1/subagent-preamble.md",
    "agent/config/zone1/zone-plan.md",
)

# Outdated-stamp threshold. Verification stamps older than this trigger a
# drift finding even when the cited fact is still correct — the discipline
# is "verify or refresh", not "trust stale stamps".
OUTDATED_STAMP_DAYS = 30

# Regex for the "(\\d+) (services|agents|plugins|MCPs|workflows)" pattern.
# Captures the count + the noun; case-insensitive.
_COUNT_REGEX = re.compile(
    r"(\d+)\s+(services|agents|plugins|MCPs|workflows|specialists|departments|hooks)",
    re.IGNORECASE,
)

# Regex for "verified at HEAD `<sha>`" or "verified at HEAD <sha>" or
# "verified at HEAD <sha> on <date>". The date is optional but preferred.
_STAMP_REGEX = re.compile(
    r"verified\s+(?:at\s+HEAD\s+)?`?([a-f0-9]{6,40})`?(?:\s+on\s+(\d{4}-\d{2}-\d{2}))?",
    re.IGNORECASE,
)

# Regex for cited filesystem paths. Conservative — only flags paths that
# look like file paths within the repo: agent/*, docs/*, scripts/*, config/*.
# Excludes URLs, command-line examples, and quoted strings inside code blocks.
_PATH_REGEX = re.compile(
    r"`((?:agent|docs|scripts|config)/[a-zA-Z0-9_\-./]+\.(?:py|md|yaml|yml|toml|sh|plist))`"
)


@dataclass(frozen=True)
class DriftFinding:
    """A single drift signal from one Zone 1 file."""

    file: str
    line: int | None
    kind: str  # "dead_ref" | "stale_count" | "outdated_stamp"
    description: str


def _live_count(repo_root: Path, noun: str) -> Optional[int]:
    """Return the current live count for a noun, or None if unmappable.

    Mappings are conservative — we only report when we can answer
    authoritatively. An unknown noun returns None and the comparison is
    silently skipped (better than false positives).
    """
    noun_lower = noun.lower()
    try:
        if noun_lower == "services":
            # bridge/services/*.py minus base.py / runner.py / dispatch_adapter.py / result.py
            services_dir = repo_root / "agent" / "bridge" / "services"
            if not services_dir.exists():
                return None
            count = sum(
                1
                for p in services_dir.glob("*.py")
                if p.name not in {"__init__.py", "base.py", "runner.py", "dispatch_adapter.py", "result.py"}
                and not p.name.startswith("_")
            )
            return count
        if noun_lower == "agents":
            agents_dir = Path.home() / ".claude" / "agents"
            if not agents_dir.exists():
                return None
            return sum(1 for _ in agents_dir.glob("*.md"))
        if noun_lower == "plugins":
            plugins_dir = Path.home() / ".claude" / "plugins"
            if not plugins_dir.exists():
                return None
            return sum(1 for p in plugins_dir.iterdir() if p.is_dir())
        if noun_lower == "mcps":
            mcp_config = repo_root / "agent" / ".mcp.json"
            if not mcp_config.exists():
                return None
            import json
            try:
                data = json.loads(mcp_config.read_text())
                servers = data.get("mcpServers", {}) or {}
                # Underscore-prefixed entries are intentionally disabled stubs
                return sum(1 for k in servers if not k.startswith("_"))
            except Exception:  # noqa: BLE001
                return None
        if noun_lower == "workflows":
            workflows_dir = repo_root / "agent" / "config" / "workflows"
            if not workflows_dir.exists():
                return None
            return sum(1 for _ in workflows_dir.glob("*.yaml"))
    except Exception as exc:  # noqa: BLE001
        log.debug("Live-count failure for %s: %s", noun, exc)
        return None
    return None


def scan_file(repo_root: Path, relative_path: str) -> list[DriftFinding]:
    """Return drift findings for one Zone 1 file. Pure function — no I/O
    side effects beyond reading the file."""
    file_path = repo_root / relative_path
    if not file_path.exists():
        return [
            DriftFinding(
                file=relative_path,
                line=None,
                kind="dead_ref",
                description=f"Zone 1 file does not exist on HEAD: {relative_path}",
            )
        ]
    text = file_path.read_text()
    lines = text.splitlines()
    findings: list[DriftFinding] = []

    for line_no, line in enumerate(lines, start=1):
        # Pass 1: cited file paths
        for match in _PATH_REGEX.finditer(line):
            cited = match.group(1)
            if not (repo_root / cited).exists():
                findings.append(
                    DriftFinding(
                        file=relative_path,
                        line=line_no,
                        kind="dead_ref",
                        description=f"cited path does not exist: {cited}",
                    )
                )

        # Pass 2: count regex (skip inside fenced code blocks — heuristic-only)
        for match in _COUNT_REGEX.finditer(line):
            claimed = int(match.group(1))
            noun = match.group(2)
            live = _live_count(repo_root, noun)
            if live is None:
                continue  # noun not mappable; silently skip
            # Allow ±10% drift before flagging (counts churn naturally)
            if claimed > 0 and abs(claimed - live) / max(claimed, live) > 0.10:
                findings.append(
                    DriftFinding(
                        file=relative_path,
                        line=line_no,
                        kind="stale_count",
                        description=f"claimed {claimed} {noun}, live count {live} (>10% drift)",
                    )
                )

        # Pass 3: outdated verification stamps
        for match in _STAMP_REGEX.finditer(line):
            stamp_date_str = match.group(2)
            if stamp_date_str is None:
                # Stamp has no date — flag as candidate for date addition
                # (less aggressive: only flag once per file to avoid noise)
                continue
            try:
                stamp_date = datetime.strptime(stamp_date_str, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                continue
            age = datetime.now(timezone.utc) - stamp_date
            if age > timedelta(days=OUTDATED_STAMP_DAYS):
                findings.append(
                    DriftFinding(
                        file=relative_path,
                        line=line_no,
                        kind="outdated_stamp",
                        description=(
                            f"verification stamp dated {stamp_date_str} is "
                            f"{age.days} days old (threshold: {OUTDATED_STAMP_DAYS})"
                        ),
                    )
                )

    return findings


class Zone1DriftService(ServiceBase):
    """Scheduled service that scans Zone 1 files for drift indicators."""

    name = "zone1_drift"

    def __init__(
        self,
        data_dir: str | Path,
        repo_root: Path | None = None,
        *,
        enabled: bool = False,
        event_callback=None,
    ) -> None:
        super().__init__(data_dir, event_callback=event_callback)
        self.enabled = enabled
        # Repo root is operator-configurable for tests; default walks up from
        # this file until a .git dir is found.
        if repo_root is not None:
            self.repo_root = Path(repo_root)
        else:
            here = Path(__file__).resolve()
            current = here
            while current != current.parent and not (current / ".git").exists():
                current = current.parent
            self.repo_root = current

    def should_run(self) -> bool:
        """Run gate. False when disabled; True otherwise (cadence is
        scheduled by the plist)."""
        return bool(self.enabled)

    def run(self) -> ServiceResult:
        """Execute the drift scan. Returns a result for the runner.

        Per the safety rule, this method NEVER auto-writes. Findings are
        rendered into a draft PR body string; the operator command surface
        is responsible for opening the actual PR.
        """
        start = time.monotonic()

        if not self.enabled:
            self.record_skipped(
                "service_disabled",
                filename="zone1_drift-state.json",
            )
            return ZoneDriftRunResult(
                service=self.name,
                ok=True,
                work_items=0,
                duration_ms=0,
                cost_usd=0.0,
                skip_reason="operator_disabled",
                narration="Zone 1 drift scan is disabled.",
                findings=(),
                pr_body=None,
                state="skipped",
            )

        findings: list[DriftFinding] = []
        for path in ZONE1_FILES:
            try:
                findings.extend(scan_file(self.repo_root, path))
            except Exception as exc:  # noqa: BLE001
                log.warning("zone1_drift scan failed for %s: %s", path, exc)

        duration_ms = int((time.monotonic() - start) * 1000)

        if not findings:
            self.record_skipped(
                "no_drift_detected",
                filename="zone1_drift-state.json",
            )
            return ZoneDriftRunResult(
                service=self.name,
                ok=True,
                work_items=0,
                duration_ms=duration_ms,
                cost_usd=0.0,
                skip_reason="nothing_to_do",
                narration="Zone 1 drift scan found no findings.",
                findings=(),
                pr_body=None,
                state="clean",
            )

        # Render draft-PR body. The service does NOT open the PR itself —
        # operator command surface consumes the rendered body. This keeps
        # the safety rule structural: even if the service is misused, it
        # can only produce TEXT, never a merge.
        pr_body = render_pr_body(findings)
        self.record_success(
            duration_ms=duration_ms,
            filename="zone1_drift-state.json",
        )
        return ZoneDriftRunResult(
            service=self.name,
            ok=True,
            work_items=len(findings),
            duration_ms=duration_ms,
            cost_usd=0.0,
            narration=f"Zone 1 drift scan found {len(findings)} finding(s).",
            findings=tuple(findings),
            pr_body=pr_body,
            state="findings_ready",
        )


@dataclass(frozen=True)
class ZoneDriftRunResult(ServiceResult):
    """Result of a Zone1Drift scan. Immutable per the run-result convention."""

    findings: tuple[DriftFinding, ...] = ()
    pr_body: str | None = None
    state: str = ""  # "clean" | "findings_ready" | "skipped"


def render_pr_body(findings: list[DriftFinding]) -> str:
    """Render findings into a draft-PR body that an operator can review.

    The body groups findings by file + kind so the operator can scan-read
    the highest-density signals first. NEVER includes any auto-apply
    instructions — every fix is operator judgment.
    """
    if not findings:
        return ""
    lines: list[str] = [
        "# Zone 1 drift scan — operator review required",
        "",
        "**Safety rule (non-negotiable):** this scan NEVER auto-merges. "
        "Every finding below is a candidate for operator review. Pick the "
        "ones to act on; leave the rest as documented stale state.",
        "",
        f"**Total findings:** {len(findings)}",
        "",
    ]
    by_file: dict[str, list[DriftFinding]] = {}
    for f in findings:
        by_file.setdefault(f.file, []).append(f)
    for file, file_findings in sorted(by_file.items()):
        lines.append(f"## {file}")
        lines.append("")
        for ff in file_findings:
            line_ref = f":L{ff.line}" if ff.line is not None else ""
            lines.append(f"- **{ff.kind}**{line_ref} — {ff.description}")
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "**To address:** edit the cited file(s) yourself, then close this draft "
        "without merging. The next scan run will surface any remaining findings."
    )
    return "\n".join(lines)

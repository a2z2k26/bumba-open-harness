"""Project pulse service — nightly repo-health report via gh CLI.

Queries every configured repo for:
  - Last commit date
  - Open PRs bucketed by age (0-7d / 7-14d / 14-30d / 30+d)
  - Open branch count
  - Stale flag (no commit in >14 days)

Posts a consolidated Discord report at 23:30 daily.

Spec: docs/specs/2026-04-17-zone2-sprint-plan.md → Sprint S5.4
GitHub: #506
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from .base import ServiceBase

log = logging.getLogger(__name__)

STATE_FILE = "project-pulse-state.json"

# Stale threshold in days (no commit → flag stale).
STALE_DAYS = 14

# Default repos if bridge.toml does not provide [project_pulse] repos.
DEFAULT_REPOS = [
    "your-org/bumba-open-harness",
    "your-org/Bumba-Desktop",
]

# PR age buckets (label, max_days).  Checked in order; first match wins.
PR_BUCKETS = [
    ("0-7d",  7),
    ("7-14d", 14),
    ("14-30d", 30),
    ("30+d",  None),
]

GH_TIMEOUT = 30


def _run_gh(args: list[str]) -> dict | list | None:
    """Run a gh CLI command and return parsed JSON, or None on failure."""
    gh_bin = shutil.which("gh") or "/opt/homebrew/bin/gh"
    cmd = [gh_bin] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=GH_TIMEOUT,
            cwd="/tmp",
        )
        if result.returncode != 0:
            log.warning("gh command failed: %s", result.stderr.strip()[:200])
            return None
        stdout = result.stdout.strip()
        if not stdout:
            return None
        return json.loads(stdout)
    except subprocess.TimeoutExpired:
        log.warning("gh command timed out: %s", " ".join(args[:4]))
        return None
    except json.JSONDecodeError:
        log.warning("gh returned non-JSON: %s", " ".join(args[:4]))
        return None
    except Exception as exc:
        log.warning("gh error: %s", exc)
        return None


def _last_commit_date(repo: str) -> datetime | None:
    """Return the datetime of the most recent commit on the default branch."""
    data = _run_gh([
        "api", f"repos/{repo}/commits",
        "--paginate",
        "--jq", ".[0].commit.committer.date",
    ])
    # gh --jq returns a plain string; handle both string and list.
    if isinstance(data, str):
        date_str = data.strip().strip('"')
    elif isinstance(data, list) and data:
        date_str = str(data[0]).strip().strip('"')
    else:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _open_prs(repo: str) -> list[dict]:
    """Return all open PRs for *repo* with created_at field."""
    data = _run_gh([
        "api", f"repos/{repo}/pulls",
        "--field", "state=open",
        "--field", "per_page=100",
        "--jq", "[.[] | {number, title, created_at, user: .user.login, requested_reviewers: [.requested_reviewers[].login]}]",
    ])
    if isinstance(data, list):
        return data
    return []


def _open_branch_count(repo: str) -> int:
    """Return the number of open (non-default) branches."""
    data = _run_gh([
        "api", f"repos/{repo}/branches",
        "--field", "per_page=100",
        "--jq", "length",
    ])
    if isinstance(data, int):
        return data
    if isinstance(data, str):
        try:
            return int(data.strip())
        except ValueError:
            pass
    return 0


def _bucket_prs(prs: list[dict]) -> dict[str, list[dict]]:
    """Bucket PRs by age."""
    now = datetime.now(timezone.utc)
    buckets: dict[str, list[dict]] = {label: [] for label, _ in PR_BUCKETS}

    for pr in prs:
        created_str = pr.get("created_at", "")
        try:
            created = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            age_days = (now - created).days
        except (ValueError, TypeError):
            age_days = 999

        for label, max_days in PR_BUCKETS:
            if max_days is None or age_days <= max_days:
                buckets[label].append(pr)
                break

    return buckets


def _load_repos_from_config() -> list[str]:
    """Load repo list from bridge.toml [project_pulse] repos if available."""
    try:
        import tomllib

        from bridge.paths import agent_root

        config_path = agent_root() / "config" / "bridge.toml"
        if config_path.exists():
            with open(config_path, "rb") as f:
                cfg = tomllib.load(f)
            repos = cfg.get("project_pulse", {}).get("repos", [])
            if repos and isinstance(repos, list):
                return repos
    except Exception:
        pass
    return DEFAULT_REPOS


def _format_repo_section(name: str, last_commit: datetime | None,
                          buckets: dict[str, list[dict]], branch_count: int) -> str:
    """Format one repo section for the Discord report."""
    now = datetime.now(timezone.utc)
    stale = False

    if last_commit is None:
        last_commit_str = "unknown"
        stale = True
    else:
        days_ago = (now - last_commit).days
        last_commit_str = last_commit.strftime("%Y-%m-%d") + f" ({days_ago}d ago)"
        stale = days_ago > STALE_DAYS

    stale_marker = "  STALE" if stale else ""
    short_name = name.split("/")[-1]

    lines = [f"**{short_name}**{stale_marker}  (last commit: {last_commit_str})"]

    total_prs = sum(len(v) for v in buckets.values())
    if total_prs == 0:
        lines.append("  No open PRs")
    else:
        for label, prs_in_bucket in buckets.items():
            if prs_in_bucket:
                lines.append(f"  PRs {label}: {len(prs_in_bucket)}")
                # Surface PRs older than 30d with reviewer info.
                if label == "30+d":
                    for pr in prs_in_bucket[:5]:
                        reviewers = pr.get("requested_reviewers") or ["no reviewer"]
                        rev_str = ", ".join(str(r) for r in reviewers[:2])
                        lines.append(f"    - #{pr.get('number')} {pr.get('title', '')[:50]} [{rev_str}]")

    lines.append(f"  Open branches: {branch_count}")
    return "\n".join(lines)


class ProjectPulseService(ServiceBase):
    """Nightly repo-health pulse — one Discord post at 23:30."""

    def __init__(
        self,
        data_dir: str | Path,
        chat_id: str,
        *,
        event_callback=None,
        repos: list[str] | None = None,
        stale_days: int = STALE_DAYS,
    ) -> None:
        super().__init__(data_dir, event_callback=event_callback)
        self.chat_id = chat_id
        self._repos = repos  # None = load from config at run time
        self.stale_days = stale_days

    def should_run(self) -> bool:
        """True if the service hasn't run today."""
        state = self.load_state(STATE_FILE)
        last_run = state.get("last_run")
        if not last_run:
            return True
        try:
            last_dt = datetime.fromisoformat(last_run)
            return last_dt.date() < datetime.now(timezone.utc).date()
        except (ValueError, TypeError):
            return True

    def _get_repos(self) -> list[str]:
        if self._repos is not None:
            return self._repos
        return _load_repos_from_config()

    def build_report(self, repos: list[str]) -> str:
        """Build the consolidated repo-health report string."""
        sections: list[str] = []
        anomalies: list[str] = []

        for repo in repos:
            try:
                last_commit = _last_commit_date(repo)
                prs = _open_prs(repo)
                branch_count = _open_branch_count(repo)
                buckets = _bucket_prs(prs)
                section = _format_repo_section(repo, last_commit, buckets, branch_count)
                sections.append(section)
            except Exception as exc:
                log.warning("Error fetching data for %s: %s", repo, exc)
                anomalies.append(f"partial_data:{repo.split('/')[-1]}")
                sections.append(f"**{repo.split('/')[-1]}** — data unavailable")

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        header = f"**Project Pulse** — {now_str}\n"
        body = "\n\n".join(sections)
        report = header + body

        if anomalies:
            report += f"\n\n_Anomalies: {', '.join(anomalies)}_"

        return report

    def run(self) -> "ServiceResult":
        """Execute the nightly project pulse report."""
        from bridge.services.result import ServiceResult

        _start = time.monotonic()

        if not self.should_run():
            self.record_skipped("already ran today", STATE_FILE)
            return ServiceResult(
                service="project_pulse",
                ok=True,
                work_items=0,
                duration_ms=int((time.monotonic() - _start) * 1000),
                cost_usd=0.0,
                skip_reason="already_ran_today",
                narration="Project pulse already ran today.",
            )

        try:
            return self._run_inner(_start)
        except Exception as exc:
            self.record_failure(str(exc)[:500], STATE_FILE)
            log.error("ProjectPulseService failed: %s", exc)
            raise

    def _run_inner(self, _start: float) -> "ServiceResult":
        from bridge.services.result import ServiceResult

        repos = self._get_repos()
        report = self.build_report(repos)
        self.deliver_message(self.chat_id, report, source="project-pulse")

        duration_ms = int((time.monotonic() - _start) * 1000)

        # Enforce ≤30s cost requirement per spec (FR-007).
        if duration_ms > 30_000:
            log.warning("ProjectPulseService exceeded 30s target: %dms", duration_ms)

        self.record_success(duration_ms, STATE_FILE)
        narration = f"Project pulse: scanned {len(repos)} repo(s) in {duration_ms / 1000:.1f}s."
        return ServiceResult(
            service="project_pulse",
            ok=True,
            work_items=len(repos),
            duration_ms=duration_ms,
            cost_usd=0.0,
            narration=narration,
        )

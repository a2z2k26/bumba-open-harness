"""Sprint 4.2 — Harness-observed evidence: pre-PR hook.

Removes the agent as narrator of its own work. The harness runs the project's
build/test commands, captures real output, and writes it into the PR body. The
agent cannot edit the harness-written section. A false claim of the
bumba-desktop-incident type (PRs #389–#403 claiming "563/563 tests passing"
while the target could not compile) is structurally impossible in this path.

Module contract:
    - ``capture_evidence()`` runs a command, captures stdout/stderr, writes
      raw files to ``.harness/evidence/pr-<N>/``, and returns an
      ``EvidenceRecord`` (immutable dataclass).
    - ``EvidenceFailedError`` is raised when a command exits non-zero. The
      caller is responsible for blocking PR creation and notifying the operator.
    - ``EvidenceConfig`` loads per-repo build/test commands from
      ``agent/config/evidence.toml``. Unknown repos get an empty command list.
    - The ``## Harness-Observed Evidence`` section is written by
      ``EvidenceRecord.to_pr_section()`` — the only call site is
      ``create_pr_with_evidence()`` in this module.

Sprint P8.3 / audit M-3 (#1749): moved from ``agent/bridge/evidence.py`` to
``agent/scripts/evidence.py`` because the only active consumer is operator
CLI tooling — no bridge runtime call site existed. The module remains an
importable library (``from scripts.evidence import ...``) plus a CLI
(``python3 -m scripts.evidence``).

Usage (programmatic — the normal path):
    from scripts.evidence import EvidenceConfig, create_pr_with_evidence
    config = EvidenceConfig.load()
    pr_url = await create_pr_with_evidence(
        title="fix: correct the thing",
        body="## Summary\n…",
        repo="your-org/bumba-open-harness",
        config=config,
    )

Usage (CLI — for manual testing):
    python3 -m scripts.evidence --repo your-org/bumba-open-harness --dry-run

Exit codes (CLI):
    0 — PR created (or dry-run completed)
    1 — evidence capture failed (PR blocked; failure details printed)
    2 — config error (missing evidence.toml, unknown repo)
"""

from __future__ import annotations

import asyncio
import logging
import socket
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

logger = logging.getLogger(__name__)

# Harness marker — the PR body parser refuses to overwrite any block
# containing this sentinel on an edit/update operation.
EVIDENCE_SECTION_MARKER = "<!-- harness-observed-evidence -->"

# Maximum lines of output included in the PR body (keeps the body readable).
OUTPUT_TAIL_LINES = 40

# Default path to evidence.toml (resolved relative to this file's location).
_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
DEFAULT_EVIDENCE_TOML = _CONFIG_DIR / "evidence.toml"

# Default evidence root relative to repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_EVIDENCE_ROOT = _REPO_ROOT / ".harness" / "evidence"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class EvidenceFailedError(RuntimeError):
    """Raised when one or more evidence commands exit with a non-zero code.

    PR creation MUST be blocked when this is raised. The caller surfaces the
    failure to the operator via the dialogue channel.
    """

    def __init__(self, message: str, records: list["EvidenceRecord"]) -> None:
        super().__init__(message)
        self.records = records


class EvidenceConfigError(ValueError):
    """Raised when evidence.toml is missing or structurally invalid."""


# ---------------------------------------------------------------------------
# EvidenceRecord (immutable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceRecord:
    """Captured output from one build/test command.

    All fields are immutable. New values require a new instance.
    """

    command: str
    """The full command string as executed (space-joined argv)."""

    exit_code: int
    """Process exit code. 0 = pass; anything else = fail."""

    duration_seconds: float
    """Wall-clock seconds from process start to process end."""

    stdout_tail: str
    """Last ``OUTPUT_TAIL_LINES`` lines of stdout (UTF-8, errors=replace)."""

    stderr_tail: str
    """Last ``OUTPUT_TAIL_LINES`` lines of stderr (UTF-8, errors=replace)."""

    captured_at: datetime
    """UTC timestamp when capture completed."""

    host: str
    """Hostname of the machine that ran the command."""

    evidence_path: str
    """Absolute path to the raw output file written to ``.harness/evidence/``."""

    @property
    def passed(self) -> bool:
        return self.exit_code == 0

    def to_pr_section(self) -> str:
        """Render the harness-observed evidence block for inclusion in a PR body.

        The block is wrapped with ``EVIDENCE_SECTION_MARKER`` so that any
        PR-update logic can detect and refuse to overwrite it.
        """
        status = "PASS" if self.passed else "FAIL"
        ts = self.captured_at.strftime("%Y-%m-%dT%H:%M:%SZ")

        combined_tail = self.stdout_tail
        if self.stderr_tail.strip():
            combined_tail = (
                combined_tail + "\n--- stderr ---\n" + self.stderr_tail
                if combined_tail.strip()
                else self.stderr_tail
            )

        return (
            f"{EVIDENCE_SECTION_MARKER}\n"
            f"## Harness-Observed Evidence\n\n"
            f"> This section is written by the bumba-agent harness, not the agent. "
            f"It reflects actual command execution on `{self.host}` at `{ts}`. "
            f"**Do not edit this section.**\n\n"
            f"| Field | Value |\n"
            f"|---|---|\n"
            f"| Command | `{self.command}` |\n"
            f"| Status | **{status}** (exit code `{self.exit_code}`) |\n"
            f"| Duration | `{self.duration_seconds:.1f}s` |\n"
            f"| Raw output | `{self.evidence_path}` |\n\n"
            f"<details><summary>Last {OUTPUT_TAIL_LINES} lines of output</summary>\n\n"
            f"```\n"
            f"{combined_tail}\n"
            f"```\n\n"
            f"</details>\n"
            f"{EVIDENCE_SECTION_MARKER}"
        )


# ---------------------------------------------------------------------------
# EvidenceConfig
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RepoEvidenceSpec:
    """Per-repo evidence specification loaded from evidence.toml."""

    name: str
    """Fully-qualified repo name, e.g. ``your-org/bumba-open-harness``."""

    commands: tuple[tuple[str, ...], ...]
    """Ordered list of commands to run, each as an argv tuple."""

    timeout_seconds: int = 300
    """Per-command wall-clock timeout. Commands exceeding this are killed."""


@dataclass(frozen=True)
class EvidenceConfig:
    """All per-repo evidence specs. Immutable after construction."""

    specs: tuple[RepoEvidenceSpec, ...]

    @classmethod
    def load(cls, toml_path: Path | None = None) -> "EvidenceConfig":
        """Load from ``evidence.toml``.

        Raises:
            EvidenceConfigError: if the file is missing or unparseable.
        """
        path = toml_path or DEFAULT_EVIDENCE_TOML
        if not path.exists():
            raise EvidenceConfigError(
                f"evidence.toml not found at {path}. "
                "Create it with per-repo build/test commands."
            )
        try:
            import tomllib
        except ImportError:
            try:
                import tomli as tomllib  # type: ignore[no-redef]
            except ImportError as exc:
                raise EvidenceConfigError(
                    "Neither tomllib (Python 3.11+) nor tomli is available."
                ) from exc

        try:
            with open(path, "rb") as f:
                raw = tomllib.load(f)
        except Exception as exc:
            raise EvidenceConfigError(f"Failed to parse {path}: {exc}") from exc

        specs: list[RepoEvidenceSpec] = []
        for entry in raw.get("repos", []):
            name = entry.get("name", "")
            if not name:
                continue
            raw_commands: list[list[str]] = entry.get("commands", [])
            timeout = int(entry.get("timeout_seconds", 300))
            spec = RepoEvidenceSpec(
                name=name,
                commands=tuple(tuple(cmd) for cmd in raw_commands),
                timeout_seconds=timeout,
            )
            specs.append(spec)

        return cls(specs=tuple(specs))

    def commands_for_repo(self, repo: str) -> tuple[tuple[str, ...], ...]:
        """Return the argv tuples for ``repo``, or empty tuple if not configured."""
        for spec in self.specs:
            if spec.name == repo:
                return spec.commands
        return ()

    def timeout_for_repo(self, repo: str) -> int:
        """Return per-command timeout for ``repo``. Falls back to 300s."""
        for spec in self.specs:
            if spec.name == repo:
                return spec.timeout_seconds
        return 300


# ---------------------------------------------------------------------------
# Capture (sync — used internally and in unit tests)
# ---------------------------------------------------------------------------


def _tail(text: str, n: int) -> str:
    """Return the last ``n`` lines of ``text``."""
    lines = text.splitlines()
    return "\n".join(lines[-n:]) if len(lines) > n else text


def _run_command(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout_seconds: int,
    runner: Callable | None = None,
) -> tuple[int, bytes, bytes, float]:
    """Run ``command`` synchronously and return (exit_code, stdout, stderr, duration).

    Args:
        command: argv sequence.
        cwd: Working directory for the subprocess.
        timeout_seconds: Kill the process after this many wall-clock seconds.
        runner: Injectable subprocess runner for unit tests. Signature must match
                ``subprocess.run(args, *, capture_output, timeout, cwd)``.

    Returns:
        (exit_code, raw_stdout_bytes, raw_stderr_bytes, elapsed_seconds)
    """
    _runner = runner or subprocess.run
    start = time.monotonic()
    try:
        proc = _runner(
            list(command),
            capture_output=True,
            timeout=timeout_seconds,
            cwd=str(cwd),
        )
        elapsed = time.monotonic() - start
        return proc.returncode, proc.stdout or b"", proc.stderr or b"", elapsed
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - start
        stdout = exc.stdout or b""
        stderr = exc.stderr or b""
        timeout_msg = f"\n[HARNESS: command killed after {timeout_seconds}s timeout]"
        return 1, stdout, stderr + timeout_msg.encode(), elapsed
    except (OSError, FileNotFoundError) as exc:
        elapsed = time.monotonic() - start
        return 1, b"", str(exc).encode(), elapsed


def capture_evidence(
    command: Sequence[str],
    *,
    cwd: Path,
    pr_number: int,
    evidence_root: Path | None = None,
    timeout_seconds: int = 300,
    runner: Callable | None = None,
) -> EvidenceRecord:
    """Run ``command``, capture output, write raw file, return an ``EvidenceRecord``.

    This is the core harness-side observation function. It does NOT raise on
    command failure — it captures and returns the evidence faithfully. The caller
    (``create_pr_with_evidence``) decides whether to block based on exit code.

    Args:
        command: argv sequence, e.g. ``["python", "-m", "pytest", "tests/"]``.
        cwd: Directory in which to run the command (typically the repo root).
        pr_number: PR number for directory namespacing. Use 0 for pre-creation captures.
        evidence_root: Override the default ``.harness/evidence/`` root.
        timeout_seconds: Kill the process after this many seconds.
        runner: Injectable for unit tests (same signature as ``subprocess.run``).

    Returns:
        ``EvidenceRecord`` with all fields populated.
    """
    root = evidence_root or DEFAULT_EVIDENCE_ROOT
    evidence_dir = root / f"pr-{pr_number}"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    exit_code, raw_stdout, raw_stderr, duration = _run_command(
        command,
        cwd=cwd,
        timeout_seconds=timeout_seconds,
        runner=runner,
    )

    # Write the raw output file — durable record independent of PR body
    timestamp_int = int(time.time())
    safe_cmd = "_".join(command[:2]).replace("/", "-").replace(" ", "_")[:40]
    raw_filename = f"{timestamp_int}_{safe_cmd}.txt"
    raw_path = evidence_dir / raw_filename
    try:
        raw_path.write_bytes(
            b"=== COMMAND ===\n"
            + " ".join(command).encode()
            + b"\n\n=== STDOUT ===\n"
            + raw_stdout
            + b"\n\n=== STDERR ===\n"
            + raw_stderr
        )
    except OSError as exc:
        logger.warning("Could not write evidence file %s: %s", raw_path, exc)

    return EvidenceRecord(
        command=" ".join(command),
        exit_code=exit_code,
        duration_seconds=duration,
        stdout_tail=_tail(raw_stdout.decode("utf-8", errors="replace"), OUTPUT_TAIL_LINES),
        stderr_tail=_tail(raw_stderr.decode("utf-8", errors="replace"), OUTPUT_TAIL_LINES),
        captured_at=datetime.now(timezone.utc),
        host=socket.gethostname(),
        evidence_path=str(raw_path),
    )


# ---------------------------------------------------------------------------
# Async capture (for async callers)
# ---------------------------------------------------------------------------


async def capture_evidence_async(
    command: Sequence[str],
    *,
    cwd: Path,
    pr_number: int,
    evidence_root: Path | None = None,
    timeout_seconds: int = 300,
) -> EvidenceRecord:
    """Async variant of ``capture_evidence`` for use in async call sites.

    Uses ``asyncio.create_subprocess_exec`` so the event loop is not blocked
    during long-running build/test commands.
    """
    root = evidence_root or DEFAULT_EVIDENCE_ROOT
    evidence_dir = root / f"pr-{pr_number}"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    start = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            raw_stdout, raw_stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_seconds
            )
            exit_code = proc.returncode if proc.returncode is not None else 1
        except asyncio.TimeoutError:
            proc.kill()
            raw_stdout, raw_stderr = await proc.communicate()
            timeout_msg = f"\n[HARNESS: command killed after {timeout_seconds}s timeout]"
            raw_stderr = (raw_stderr or b"") + timeout_msg.encode()
            exit_code = 1
    except (OSError, FileNotFoundError) as exc:
        raw_stdout, raw_stderr = b"", str(exc).encode()
        exit_code = 1

    duration = time.monotonic() - start

    timestamp_int = int(time.time())
    safe_cmd = "_".join(command[:2]).replace("/", "-").replace(" ", "_")[:40]
    raw_filename = f"{timestamp_int}_{safe_cmd}.txt"
    raw_path = evidence_dir / raw_filename
    try:
        raw_path.write_bytes(
            b"=== COMMAND ===\n"
            + " ".join(command).encode()
            + b"\n\n=== STDOUT ===\n"
            + (raw_stdout or b"")
            + b"\n\n=== STDERR ===\n"
            + (raw_stderr or b"")
        )
    except OSError as exc:
        logger.warning("Could not write evidence file %s: %s", raw_path, exc)

    return EvidenceRecord(
        command=" ".join(command),
        exit_code=exit_code,
        duration_seconds=duration,
        stdout_tail=_tail(
            (raw_stdout or b"").decode("utf-8", errors="replace"), OUTPUT_TAIL_LINES
        ),
        stderr_tail=_tail(
            (raw_stderr or b"").decode("utf-8", errors="replace"), OUTPUT_TAIL_LINES
        ),
        captured_at=datetime.now(timezone.utc),
        host=socket.gethostname(),
        evidence_path=str(raw_path),
    )


# ---------------------------------------------------------------------------
# PR creation path (the only sanctioned entry point for PR creation)
# ---------------------------------------------------------------------------


async def _run_gh(argv: list[str], *, runner: Callable | None = None) -> tuple[int, str, str]:
    """Run a ``gh`` CLI command. Returns (exit_code, stdout, stderr).

    Sync-compatible via asyncio.run() when called from outside an event loop.
    The injectable ``runner`` keeps unit tests off the network.
    """
    if runner is not None:
        proc = runner(["gh"] + argv, capture_output=True, text=True)
        return proc.returncode, proc.stdout or "", proc.stderr or ""

    proc = await asyncio.create_subprocess_exec(
        "gh", *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    raw_out, raw_err = await proc.communicate()
    return (
        proc.returncode if proc.returncode is not None else 1,
        raw_out.decode("utf-8", errors="replace"),
        raw_err.decode("utf-8", errors="replace"),
    )


async def create_pr_with_evidence(
    *,
    title: str,
    body: str,
    repo: str,
    config: EvidenceConfig,
    cwd: Path | None = None,
    evidence_root: Path | None = None,
    dialogue_notify: Callable[[str], None] | None = None,
    gh_runner: Callable | None = None,
    subprocess_runner: Callable | None = None,
    dry_run: bool = False,
) -> str:
    """Create a GitHub PR after running and capturing harness-observed evidence.

    This is the ONLY sanctioned path for PR creation. All other ``gh pr create``
    call sites in the agent's action space must be removed.

    Workflow:
        1. Look up the evidence commands for ``repo`` in ``config``.
        2. Run each command via ``capture_evidence_async`` (or sync runner if
           ``subprocess_runner`` is injected — for tests).
        3. If any command fails, raise ``EvidenceFailedError`` (PR blocked).
           The ``dialogue_notify`` callback is called so the operator knows.
        4. Append the harness-written ``## Harness-Observed Evidence`` section
           to ``body``. The agent-supplied body is preserved above the section.
        5. Call ``gh pr create`` with the combined body.
        6. Return the PR URL.

    Args:
        title: PR title (agent-supplied).
        body: Agent-supplied PR body. The harness section is appended below it.
        repo: Fully-qualified repo name, e.g. ``"your-org/bumba-open-harness"``.
        config: Loaded ``EvidenceConfig`` instance.
        cwd: Working directory for evidence commands. Defaults to ``DEFAULT_EVIDENCE_ROOT``'s
             grandparent (the repo root inferred from this file's location).
        evidence_root: Override the ``.harness/evidence/`` root.
        dialogue_notify: Optional callback for surfacing failures to the operator.
                         Called with a human-readable message string.
        gh_runner: Injectable subprocess runner for the ``gh`` CLI (tests only).
        subprocess_runner: Injectable subprocess runner for evidence commands (tests only).
        dry_run: If True, run evidence commands but do not call ``gh pr create``.

    Returns:
        The PR URL string returned by ``gh pr create``, or a dry-run description.

    Raises:
        EvidenceFailedError: when one or more evidence commands exit non-zero.
        EvidenceConfigError: when the config is missing or the repo is unknown.
        RuntimeError: when ``gh pr create`` fails.
    """
    effective_cwd = cwd or _REPO_ROOT

    commands = config.commands_for_repo(repo)
    timeout = config.timeout_for_repo(repo)

    # Use pr_number=0 for pre-creation captures (we don't have a number yet)
    evidence_records: list[EvidenceRecord] = []
    for cmd in commands:
        if subprocess_runner is not None:
            # Sync path for tests
            record = capture_evidence(
                cmd,
                cwd=effective_cwd,
                pr_number=0,
                evidence_root=evidence_root,
                timeout_seconds=timeout,
                runner=subprocess_runner,
            )
        else:
            record = await capture_evidence_async(
                cmd,
                cwd=effective_cwd,
                pr_number=0,
                evidence_root=evidence_root,
                timeout_seconds=timeout,
            )
        evidence_records.append(record)
        logger.info(
            "Evidence captured: cmd=%r exit_code=%d duration=%.1fs",
            record.command, record.exit_code, record.duration_seconds,
        )

    # If any command failed, block PR creation and notify the operator
    failed = [r for r in evidence_records if not r.passed]
    if failed:
        failure_paths = ", ".join(r.evidence_path for r in failed)
        msg = (
            f"Harness evidence capture failed for {len(failed)} of "
            f"{len(evidence_records)} command(s) in repo '{repo}'. "
            f"PR creation is blocked. Fix the underlying issue before retrying. "
            f"Raw output: {failure_paths}"
        )
        if dialogue_notify is not None:
            dialogue_notify(msg)
        raise EvidenceFailedError(msg, records=failed)

    # Build the full PR body: agent section + harness evidence section
    harness_section = "\n\n".join(r.to_pr_section() for r in evidence_records)
    full_body = f"{body}\n\n{harness_section}" if harness_section else body

    if dry_run:
        summary = f"DRY RUN — would create PR '{title}' on {repo}\n"
        for r in evidence_records:
            summary += f"  [{r.command}] exit={r.exit_code} ({r.duration_seconds:.1f}s)\n"
        return summary

    # Create the PR
    rc, stdout, stderr = await _run_gh(
        [
            "pr", "create",
            "--repo", repo,
            "--title", title,
            "--body", full_body,
        ],
        runner=gh_runner,
    )
    if rc != 0:
        raise RuntimeError(
            f"gh pr create failed (exit {rc}): {stderr.strip()}"
        )

    pr_url = stdout.strip()
    logger.info("PR created: %s", pr_url)
    return pr_url


# ---------------------------------------------------------------------------
# CLI entry point (manual testing / debugging)
# ---------------------------------------------------------------------------


def _parse_cli_args(argv: list[str] | None = None) -> object:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Sprint 4.2 — harness pre-PR evidence hook. "
            "Run build/test commands and inject real output into a PR body."
        )
    )
    parser.add_argument("--repo", required=True, help="Fully-qualified repo name")
    parser.add_argument("--title", default="[test] evidence hook dry run")
    parser.add_argument("--body", default="## Summary\nDry-run test.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Capture evidence but do not call gh pr create",
    )
    parser.add_argument(
        "--toml",
        default=None,
        help="Override evidence.toml path",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    import sys

    args = _parse_cli_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    try:
        toml_path = Path(args.toml) if args.toml else None
        config = EvidenceConfig.load(toml_path)
    except EvidenceConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    try:
        result = asyncio.run(
            create_pr_with_evidence(
                title=args.title,
                body=args.body,
                repo=args.repo,
                config=config,
                dry_run=args.dry_run,
            )
        )
        print(result)
        return 0
    except EvidenceFailedError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    import sys

    sys.exit(main())

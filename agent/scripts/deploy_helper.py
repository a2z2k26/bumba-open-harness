#!/usr/bin/env python3
"""Deploy Helper Daemon — watches for deploy manifests and executes them.

Runs as user `bumba` (admin) via LaunchDaemon, so it has privileges to:
- Write to kernel files (bridge/*.py, system-prompt.md, etc.)
- Regenerate kernel baseline hashes
- Restart the bridge LaunchDaemon
- Set file ownership

Agent writes manifests to data/deploy-requests/*.json.
Helper picks them up, classifies tier, executes or requests approval.
"""

from __future__ import annotations

import glob
import hashlib
import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────

AGENT_DIR = Path("/opt/bumba-harness/agent-flat/agent")
DATA_DIR = Path("/opt/bumba-harness/data")
REQUESTS_DIR = DATA_DIR / "deploy-requests"
MESSAGES_DIR = DATA_DIR / "service_messages"
LOG_FILE = Path("/opt/bumba-harness/logs/deploy-helper.log")
BASELINE_PATH = DATA_DIR / "kernel-baseline.json"
HALT_FLAG = DATA_DIR / "halt.flag"
BRIDGE_PLIST = "/Library/LaunchDaemons/com.bumba.agent-bridge.plist"
BRIDGE_LABEL = "com.bumba.agent-bridge"
POLL_INTERVAL = 10  # seconds
APPROVAL_TIMEOUT = 3600  # 1 hour

# ── Logging ────────────────────────────────────────────────────

log = logging.getLogger("deploy-helper")


def _setup_logging() -> None:
    """Set up logging handlers. Deferred to avoid import-time side effects."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler(sys.stdout),
        ],
    )

# ── Tier Classification ────────────────────────────────────────

TIER_A_PATTERNS = [
    r"/config/claude-files/",
    r"/data/",
    r"/docs/",
    r"/tools/",
    r"/mcp-servers/",
    r"/config/notion-bridge/",
]

TIER_B_PATTERNS = [
    r"/config/system-prompt\.md$",
    r"/config/hooks/",
    r"/config/bridge\.toml$",
    r"/\.mcp\.json$",
]

TIER_C_PATTERNS = [
    r"/bridge/[^/]+\.py$",
    r"\.plist$",
    r"/kernel-baseline\.json$",
]

ALLOWED_DST_PREFIXES = [
    "/opt/bumba-harness/agent/",
    "/opt/bumba-harness/agent-flat/agent/",
    "/opt/bumba-harness/data/",
]

SAFE_COMMAND_PREFIXES = ["mkdir ", "chmod ", "chown ", "rm -f /opt/bumba-harness/data/halt.flag"]


def classify_file_tier(dst: str) -> str:
    """Classify a single destination path into tier A, B, or C."""
    for pattern in TIER_C_PATTERNS:
        if re.search(pattern, dst):
            return "C"
    for pattern in TIER_B_PATTERNS:
        if re.search(pattern, dst):
            return "B"
    for pattern in TIER_A_PATTERNS:
        if re.search(pattern, dst):
            return "A"
    # Unknown paths default to C (safest)
    return "C"


def classify_manifest_tier(manifest: dict) -> str:
    """Classify an entire manifest — highest tier among all files."""
    tier_order = {"A": 0, "B": 1, "C": 2}
    highest = "A"
    for f in manifest.get("files", []):
        ft = classify_file_tier(f["dst"])
        if tier_order[ft] > tier_order[highest]:
            highest = ft
    return highest


# ── Path Validation ────────────────────────────────────────────

def validate_path(path: str) -> bool:
    """Validate a destination path is safe."""
    if ".." in path:
        return False
    resolved = str(Path(path).resolve())
    return any(resolved.startswith(prefix) for prefix in ALLOWED_DST_PREFIXES)


def validate_command(cmd: str) -> bool:
    """Validate a pre/post command is safe."""
    return any(cmd.strip().startswith(prefix) for prefix in SAFE_COMMAND_PREFIXES)


# ── Manifest Validation ───────────────────────────────────────

def validate_manifest(manifest: dict) -> list[str]:
    """Validate manifest structure. Returns list of errors (empty = valid)."""
    errors = []
    required = ["id", "description", "files", "status", "created_at"]
    for field in required:
        if field not in manifest:
            errors.append(f"Missing required field: {field}")

    if not isinstance(manifest.get("files"), list) or not manifest.get("files"):
        errors.append("'files' must be a non-empty array")
        return errors

    for i, f in enumerate(manifest["files"]):
        for key in ("src", "dst", "owner", "mode"):
            if key not in f:
                errors.append(f"files[{i}]: missing '{key}'")

        if "dst" in f and not validate_path(f["dst"]):
            errors.append(f"files[{i}]: invalid destination path: {f['dst']}")

        if "src" in f and not os.path.isfile(f["src"]):
            errors.append(f"files[{i}]: source file not found: {f['src']}")

    for cmd in manifest.get("pre_commands", []):
        if not validate_command(cmd):
            errors.append(f"Unsafe pre_command: {cmd}")

    for cmd in manifest.get("post_commands", []):
        if not validate_command(cmd):
            errors.append(f"Unsafe post_command: {cmd}")

    return errors


# ── Pre-Deploy Validation ──────────────────────────────────────

def has_python_files(manifest: dict) -> bool:
    """Check if manifest contains any .py file deploys."""
    return any(f["dst"].endswith(".py") for f in manifest.get("files", []))


def run_tests() -> tuple[bool, str]:
    """Run pytest and return (passed, output)."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-x", "--tb=line"],
            capture_output=True,
            text=True,
            cwd=str(AGENT_DIR),
            timeout=120,
        )
        output = result.stdout + result.stderr
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, "Test suite timed out after 120 seconds"
    except Exception as e:
        return False, f"Failed to run tests: {e}"


# ── Deploy Execution ───────────────────────────────────────────

# Audit-2026-05-16.A.01 (#2045, CR-1): the privileged deploy daemon runs
# pre/post commands under user `bumba` with admin rights.  shell=True on an
# operator-curated manifest is still a shell-injection surface — any future
# manifest tamper, or any defect in the upstream agent that writes the
# manifest, becomes arbitrary code execution at admin scope.  Execute the
# narrow set of operations the schema actually allows via argv + shell=False
# instead, and reject anything that doesn't match the allowlist before we
# hand it to subprocess.
#
# The four prefixes below mirror SAFE_COMMAND_PREFIXES (the validator already
# enforces these at manifest-load time) and the docs at
# config/claude-files/docs/deploy-manifest-schema.md: mkdir, chmod, chown,
# rm -f (halt flag only).
ALLOWED_ARGV_PREFIXES: tuple[tuple[str, ...], ...] = (
    ("mkdir",),
    ("chmod",),
    ("chown",),
    ("rm", "-f", "/opt/bumba-harness/data/halt.flag"),
)

# shlex.split leaves these as ordinary argv tokens, which would silently
# succeed under shell=False but bypass operator intent.  Reject the raw
# string before tokenisation so the denial reason is unambiguous.
_FORBIDDEN_METACHARS: frozenset[str] = frozenset(";&|`$<>\n")


class DeployError(Exception):
    """Raised when a deploy command fails validation before execution."""


def parse_allowed_command(raw: str) -> list[str]:
    """Parse a manifest command string into an argv list, enforcing allowlist.

    Raises ``DeployError`` if the command contains shell metacharacters,
    parses to an empty argv, or does not match any
    ``ALLOWED_ARGV_PREFIXES`` entry.
    """
    if not isinstance(raw, str):
        raise DeployError(f"command must be a string, got {type(raw).__name__}")
    found = [ch for ch in _FORBIDDEN_METACHARS if ch in raw]
    if found:
        raise DeployError(
            f"shell metacharacters forbidden ({''.join(sorted(found))!r}): {raw!r}"
        )
    try:
        argv = shlex.split(raw)
    except ValueError as e:
        raise DeployError(f"could not parse command {raw!r}: {e}") from e
    if not argv:
        raise DeployError(f"empty command after parse: {raw!r}")
    for prefix in ALLOWED_ARGV_PREFIXES:
        if tuple(argv[: len(prefix)]) == prefix:
            return argv
    raise DeployError(
        f"command is not allowlisted (argv prefix {tuple(argv[:2])!r}): {raw!r}"
    )


def execute_commands(commands: list[str]) -> tuple[bool, str]:
    """Execute a list of allowlisted argv commands. Returns (success, output).

    Each entry in ``commands`` is parsed via ``parse_allowed_command`` and
    executed with ``shell=False`` so manifest content is never interpreted by
    a shell.  Any rejected command short-circuits the batch with a structured
    denial reason logged at ERROR.
    """
    for cmd in commands:
        try:
            argv = parse_allowed_command(cmd)
        except DeployError as e:
            log.error("deploy command rejected: %s", e)
            return False, f"Command rejected: {cmd}\n{e}"
        try:
            result = subprocess.run(
                argv,
                shell=False,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(AGENT_DIR),
            )
            if result.returncode != 0:
                return False, f"Command failed: {cmd}\n{result.stderr}"
        except Exception as e:
            return False, f"Command error: {cmd}\n{e}"
    return True, ""


# Audit-2026-05-16.A.02 (#2046): manifest sources used to be passed
# straight to ``shutil.copy2`` — the destination tier allowlist defended
# against bad ``dst`` paths but ``src`` was unconstrained.  A buggy or
# malicious manifest could read ``/home/operator/.secrets/...`` and land it under
# an approved destination, or escape the repo via symlinks/``..`` traversal.
# Constrain sources to repo-root-relative paths or absolute paths inside one
# of the explicit ``staging_roots`` we trust the agent to populate.
#
# Both legitimate runtime staging surfaces:
#   - ``AGENT_DIR``  (``/opt/bumba-harness/agent-flat/agent``) — git tree,
#     covers every in-repo source the manifest can legitimately reference.
#   - ``DATA_DIR``  (``/opt/bumba-harness/data``) — runtime staging for
#     generated artefacts (e.g. regenerated configs about to be promoted).
# Anything outside this set is rejected at validation time, before copy.
_DEFAULT_STAGING_ROOTS: tuple[Path, ...] = (AGENT_DIR, DATA_DIR)


def resolve_manifest_source(
    raw: str,
    repo_root: Path,
    staging_roots: tuple[Path, ...] | None = None,
) -> Path:
    """Resolve and validate a manifest ``src`` entry to a safe absolute Path.

    Rules:
      * Absolute paths are accepted only when they resolve under one of the
        configured ``staging_roots`` (defaults to ``_DEFAULT_STAGING_ROOTS``
        when ``None``; pass an empty tuple to forbid absolute paths entirely).
      * Relative paths are resolved against ``repo_root`` and must remain
        inside it after ``Path.resolve()`` (so symlinks and ``..`` traversal
        cannot escape).
      * Any other shape raises :class:`DeployError` with a structured reason.

    The destination tier allowlist already covers ``dst``; this is the
    matching guard for ``src``.
    """
    if not isinstance(raw, str) or not raw:
        raise DeployError(f"source path must be a non-empty string, got {raw!r}")

    roots: tuple[Path, ...] = (
        _DEFAULT_STAGING_ROOTS if staging_roots is None else tuple(staging_roots)
    )
    raw_path = Path(raw)

    if raw_path.is_absolute():
        resolved = raw_path.resolve()
        for root in roots:
            try:
                resolved.relative_to(root.resolve())
                return resolved
            except ValueError:
                continue
        if not roots:
            raise DeployError(
                f"absolute source paths not allowed (no staging roots configured): {raw}"
            )
        allowed = ", ".join(str(r) for r in roots)
        raise DeployError(
            f"absolute source not under any allowed staging root [{allowed}]: {raw}"
        )

    resolved = (repo_root / raw_path).resolve()
    try:
        resolved.relative_to(repo_root.resolve())
    except ValueError:
        raise DeployError(
            f"source escapes repo root {repo_root}: {raw}"
        ) from None
    return resolved


def copy_files(files: list[dict]) -> tuple[bool, str]:
    """Copy files from src to dst with ownership and permissions.

    Each ``src`` is run through :func:`resolve_manifest_source` first so the
    helper cannot be coerced into reading paths outside the agent's
    legitimate staging surfaces (audit-2026-05-16.A.02, issue #2046).
    """
    for f in files:
        raw_src, dst, owner, mode = f["src"], f["dst"], f["owner"], f["mode"]
        try:
            src = resolve_manifest_source(raw_src, repo_root=AGENT_DIR)
        except DeployError as e:
            log.error("deploy source rejected: %s", e)
            return False, f"Source path rejected: {raw_src}\n{e}"
        try:
            # Ensure destination directory exists
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(str(src), dst)
            # Set ownership
            user, group = owner.split(":")
            subprocess.run(["chown", f"{user}:{group}", dst], check=True)
            # Set permissions
            subprocess.run(["chmod", mode, dst], check=True)
            log.info("Copied: %s → %s (%s, %s)", src, dst, owner, mode)
        except Exception as e:
            return False, f"Failed to copy {src} → {dst}: {e}"
    return True, ""


# ── Baseline Regeneration ──────────────────────────────────────

def regenerate_baseline() -> None:
    """Regenerate kernel-baseline.json with SHA-256 hashes."""
    baseline_files = [
        "/opt/bumba-harness/.claude/hooks/memory-session-start.sh",
        "/opt/bumba-harness/.claude/hooks/memory-session-stop.sh",
        "/opt/bumba-harness/.claude/hooks/memory-subagent-stop.sh",
        "/opt/bumba-harness/.claude/settings.json",
        "/opt/bumba-harness/agent-flat/agent/config/system-prompt.md",
        "/opt/bumba-harness/agent-flat/agent/config/disallowed-tools.txt",
        "/opt/bumba-harness/agent-flat/agent/config/bridge.toml",
        "/opt/bumba-harness/agent-flat/agent/.mcp.json",
    ] + glob.glob("/opt/bumba-harness/agent-flat/agent/bridge/*.py")

    hashes = {}
    for f in baseline_files:
        if os.path.isfile(f):
            with open(f, "rb") as fh:
                hashes[f] = hashlib.sha256(fh.read()).hexdigest()

    with open(BASELINE_PATH, "w") as out:
        json.dump({"files": hashes}, out, indent=2)

    log.info("Baseline regenerated: %d files hashed", len(hashes))


# ── Bridge Restart ─────────────────────────────────────────────

def restart_bridge() -> tuple[bool, str]:
    """Restart the bridge LaunchDaemon."""
    try:
        subprocess.run(
            ["launchctl", "bootout", f"system/{BRIDGE_LABEL}"],
            capture_output=True, timeout=10,
        )
        time.sleep(2)
        result = subprocess.run(
            ["launchctl", "bootstrap", "system", BRIDGE_PLIST],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return False, f"Bootstrap failed: {result.stderr}"
        log.info("Bridge restarted successfully")
        return True, ""
    except Exception as e:
        return False, f"Restart failed: {e}"


# ── Discord Approval ──────────────────────────────────────────

def request_approval(manifest: dict) -> None:
    """Write a Discord message requesting approval for a Tier B deploy."""
    MESSAGES_DIR.mkdir(parents=True, exist_ok=True)
    file_list = "\n".join(f"  - {f['dst']}" for f in manifest["files"])
    text = (
        f"**Deploy Approval Required** (Tier B)\n\n"
        f"**ID:** `{manifest['id']}`\n"
        f"**Description:** {manifest['description']}\n\n"
        f"**Files:**\n{file_list}\n\n"
        f"**Baseline regen:** {manifest.get('requires_baseline_regen', False)}\n"
        f"**Bridge restart:** {manifest.get('requires_restart', False)}\n\n"
        f"Reply with: `deploy approve {manifest['id']}` or `deploy reject {manifest['id']}`\n"
        f"Auto-rejects in 1 hour."
    )
    msg = {
        "chat_id": "",  # Uses operator_discord_id default
        "text": text,
        "source": "deploy-helper",
        "timestamp": time.time(),
    }
    filename = f"deploy-helper_{int(time.time() * 1000)}_{os.getpid()}.json"
    (MESSAGES_DIR / filename).write_text(json.dumps(msg, indent=2))
    log.info("Approval requested for deploy %s", manifest["id"])


def check_approval(manifest_id: str) -> str | None:
    """Check for approval/rejection response. Returns 'approved', 'rejected', or None."""
    response_path = REQUESTS_DIR / f"{manifest_id}.response"
    if response_path.exists():
        try:
            data = json.loads(response_path.read_text())
            return data.get("action")
        except (json.JSONDecodeError, OSError):
            return None
    return None



# ── Runtime Permission Hygiene ─────────────────────────────────

def _ensure_runtime_perms() -> None:
    """Validate and fix directory permissions needed by the deploy-helper daemon.

    The two-user model (bumba-agent writes, bumba deploys) requires specific
    group-write permissions on shared directories.  Upstream defaults from
    bumba-agent's umask leave these wrong after a fresh install or rebuild.
    Self-healing here means no operator action is needed after a reset.
    See issue #278.

    Required state:
      /opt/bumba-harness/data          0o750  (group needs traverse, not write)
      /opt/bumba-harness/data/deploy-requests  0o770  (group needs write)
      /opt/bumba-harness/data/service_messages 0o770  (group needs write)
    """
    needs: list[tuple[Path, int]] = [
        (DATA_DIR, 0o750),
        (REQUESTS_DIR, 0o770),
        (MESSAGES_DIR, 0o770),
    ]
    for path, want in needs:
        if not path.exists():
            continue
        current = path.stat().st_mode & 0o777
        if current != want:
            log.warning(
                "Fixing permissions on %s: %o → %o", path, current, want
            )
            os.chmod(path, want)

# ── Experiment-Mode Surfacing (Sprint audit-2026-05-15.C.04, #2001) ─

def _current_experiment_mode() -> str | None:
    """Return the active ``experiment_loop.mode`` for post-deploy summaries.

    Fail-soft: any import/load failure returns ``None`` and the caller
    omits the line — a misconfigured config must not crash the deploy
    helper itself.
    """
    try:
        sys.path.insert(0, str(AGENT_DIR))
        from bridge.config import load_config  # noqa: PLC0415
        cfg = load_config(skip_secrets=True, skip_validation=True)
        mode = getattr(cfg, "experiment_mode", None)
        if isinstance(mode, str) and mode:
            return mode
        return None
    except Exception as e:  # noqa: BLE001 — fail-soft is the whole point
        log.warning("Could not resolve experiment_mode for summary: %s", e)
        return None


# ── Manifest Processing ───────────────────────────────────────

def update_manifest(path: Path, updates: dict) -> None:
    """Update fields in a manifest file using atomic write-via-rename.

    Avoids O_WRONLY|O_TRUNC on the original file, which requires write
    permission on the file itself (fails when manifests created by bumba-agent
    are mode 0644 and we run as bumba:staff).  os.replace() only needs
    write+execute on the parent directory, which we already own via 0o770.
    See issue #277.
    """
    manifest = json.loads(path.read_text())
    manifest.update(updates)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=2))
    os.replace(tmp, path)


def process_manifest(path: Path) -> None:
    """Process a single deploy manifest."""
    try:
        manifest = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        log.error("Failed to read manifest %s: %s", path, e)
        return

    if manifest.get("status") != "pending":
        return

    manifest_id = manifest.get("id", "unknown")
    log.info("Processing manifest: %s — %s", manifest_id, manifest.get("description"))

    # Validate
    errors = validate_manifest(manifest)
    if errors:
        log.error("Manifest validation failed: %s", errors)
        update_manifest(path, {
            "status": "failed",
            "error": f"Validation errors: {'; '.join(errors)}",
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        return

    # Classify tier
    tier = classify_manifest_tier(manifest)
    manifest["tier"] = tier
    log.info("Tier classification: %s", tier)

    # Tier C: auto-reject
    if tier == "C":
        log.warning("Tier C deploy rejected: %s", manifest_id)
        update_manifest(path, {
            "tier": "C",
            "status": "rejected",
            "error": "Tier C: kernel files require operator manual deploy",
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        return

    # Tier B: request approval
    if tier == "B":
        update_manifest(path, {"tier": "B", "status": "pending"})
        request_approval(manifest)
        # Don't block — approval is checked in the poll loop
        return

    # Tier A: auto-execute
    execute_deploy(path, manifest)


def execute_deploy(path: Path, manifest: dict) -> None:
    """Execute an approved or auto-approved deploy."""
    manifest_id = manifest.get("id", "unknown")

    # Pre-deploy validation: run tests if deploying Python files
    if has_python_files(manifest):
        log.info("Running pre-deploy tests for Python files...")
        passed, output = run_tests()
        if not passed:
            log.error("Pre-deploy tests failed, rejecting manifest")
            update_manifest(path, {
                "status": "failed",
                "error": f"Pre-deploy tests failed:\n{output[:500]}",
                "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            return

    # Harness verification — validate config/script files before copying
    changed_files = [f["dst"] for f in manifest.get("files", [])]
    try:
        sys.path.insert(0, str(AGENT_DIR))
        from bridge.harness_verifier import HarnessVerifier  # noqa: PLC0415
        verifier = HarnessVerifier(config_dir=str(AGENT_DIR / "config"))
        verification = verifier.verify_pre_deploy(changed_files)
        if not verification.passed:
            critical = [
                fv.message
                for fv in verification.failures
                if fv.severity == "critical"
            ]
            log.error(
                "Harness verification failed for manifest %s: %s",
                manifest_id,
                "; ".join(critical),
            )
            update_manifest(path, {
                "status": "failed",
                "error": f"Harness verification failed: {'; '.join(critical)}",
                "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            return
        log.info(
            "Harness verification passed for manifest %s (%d checks)",
            manifest_id,
            len(verification.checks_run),
        )
    except ImportError:
        log.debug("HarnessVerifier not available, skipping pre-deploy verification")

    # Pre-commands
    pre_cmds = manifest.get("pre_commands", [])
    if pre_cmds:
        ok, err = execute_commands(pre_cmds)
        if not ok:
            update_manifest(path, {
                "status": "failed",
                "error": f"Pre-command failed: {err}",
                "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            return

    # Copy files
    ok, err = copy_files(manifest["files"])
    if not ok:
        update_manifest(path, {
            "status": "failed",
            "error": err,
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        return

    # Post-commands
    post_cmds = manifest.get("post_commands", [])
    if post_cmds:
        ok, err = execute_commands(post_cmds)
        if not ok:
            update_manifest(path, {
                "status": "failed",
                "error": f"Post-command failed: {err}",
                "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            return

    # Post-deploy validation: run tests after files are copied
    if has_python_files(manifest):
        log.info("Running post-deploy tests to verify imports...")
        passed, output = run_tests()
        if not passed:
            log.error("Post-deploy tests FAILED — bridge may be broken:\n%s", output[:500])
            # Don't rollback — operator needs to fix. But alert via Discord.
            MESSAGES_DIR.mkdir(parents=True, exist_ok=True)
            alert_msg = {
                "chat_id": "",
                "text": (
                    f"**[ALERT] Post-deploy tests FAILED** for {manifest_id}\n"
                    f"Bridge may be in a broken state.\n```\n{output[:400]}\n```"
                ),
                "source": "deploy-helper",
                "timestamp": time.time(),
            }
            alert_filename = f"deploy-helper_{int(time.time() * 1000)}_{os.getpid()}.json"
            (MESSAGES_DIR / alert_filename).write_text(json.dumps(alert_msg, indent=2))

    # Baseline regen
    if manifest.get("requires_baseline_regen"):
        regenerate_baseline()
        # Halt-flag policy after baseline regen (audit-2026-05-16.A.03, #2047):
        # by default LEAVE the halt flag in place — the operator may have set
        # it deliberately (audit in progress, validation window, incident).
        # Only clear when the manifest explicitly opts in via
        # `clear_halt: true`, signalling operator intent at manifest-author time.
        if HALT_FLAG.exists():
            if manifest.get("clear_halt") is True:
                HALT_FLAG.unlink()
                log.info("operator-requested halt clear after baseline refresh")
            else:
                log.warning("preserving halt flag during baseline refresh")

    # Bridge restart
    if manifest.get("requires_restart"):
        ok, err = restart_bridge()
        if not ok:
            log.error("Bridge restart failed: %s", err)
            # Don't fail the whole deploy for restart issues

    # Mark completed
    update_manifest(path, {
        "status": "completed",
        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    log.info("Deploy completed: %s", manifest_id)

    # Notify via Discord
    MESSAGES_DIR.mkdir(parents=True, exist_ok=True)
    summary_lines = [f"Deploy completed: {manifest.get('description', manifest_id)}"]
    mode = _current_experiment_mode()
    if mode is not None:
        summary_lines.append(f"experiment_mode = {mode}")
    msg = {
        "chat_id": "",
        "text": "\n".join(summary_lines),
        "source": "deploy-helper",
        "timestamp": time.time(),
    }
    filename = f"deploy-helper_{int(time.time() * 1000)}_{os.getpid()}.json"
    (MESSAGES_DIR / filename).write_text(json.dumps(msg, indent=2))


# ── Approval Polling ──────────────────────────────────────────

def check_pending_approvals() -> None:
    """Check for approval responses on Tier B manifests."""
    for path in sorted(REQUESTS_DIR.glob("*.json")):
        if path.suffix != ".json" or path.name.endswith(".response"):
            continue
        try:
            manifest = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        if manifest.get("status") != "pending" or manifest.get("tier") != "B":
            continue

        manifest_id = manifest.get("id", "unknown")
        action = check_approval(manifest_id)

        if action == "approved":
            log.info("Deploy approved: %s", manifest_id)
            update_manifest(path, {"status": "approved"})
            execute_deploy(path, manifest)
        elif action == "rejected":
            log.info("Deploy rejected: %s", manifest_id)
            update_manifest(path, {
                "status": "rejected",
                "error": "Operator rejected via Discord",
                "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
        else:
            # Check timeout
            created = manifest.get("created_at", "")
            try:
                import datetime
                created_dt = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
                age = (datetime.datetime.now(datetime.timezone.utc) - created_dt).total_seconds()
                if age > APPROVAL_TIMEOUT:
                    log.warning("Deploy approval timed out: %s", manifest_id)
                    update_manifest(path, {
                        "status": "rejected",
                        "error": "Approval timed out (1 hour)",
                        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    })
            except (ValueError, TypeError):
                pass


# ── Main Loop ──────────────────────────────────────────────────

def main() -> None:
    """Main polling loop."""
    _setup_logging()
    log.info("Deploy helper started")
    REQUESTS_DIR.mkdir(parents=True, exist_ok=True)
    MESSAGES_DIR.mkdir(parents=True, exist_ok=True)
    _ensure_runtime_perms()

    while True:
        try:
            # Process new pending manifests
            for path in sorted(REQUESTS_DIR.glob("*.json")):
                if path.name.endswith(".response"):
                    continue
                try:
                    manifest = json.loads(path.read_text())
                except (json.JSONDecodeError, OSError) as e:
                    log.error("Failed to read manifest %s: %s", path, e)
                    continue
                if manifest.get("status") == "pending" and manifest.get("tier") != "B":
                    try:
                        process_manifest(path)
                    except Exception:
                        log.exception("Manifest processing failed: %s", path)
                        try:
                            update_manifest(path, {
                                "status": "failed",
                                "error": "Internal error during processing — see log",
                                "completed_at": time.strftime(
                                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                                ),
                            })
                        except Exception:
                            log.exception(
                                "Could not mark manifest failed: %s", path
                            )

            # Check pending approvals
            check_pending_approvals()

        except Exception as e:
            log.error("Error in poll loop: %s", e, exc_info=True)

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()

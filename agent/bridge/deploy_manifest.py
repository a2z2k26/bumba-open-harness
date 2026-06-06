"""Deploy manifest schema and tier classification.

Defines the JSON manifest format for deploy requests and classifies
files into deployment tiers:
  - Tier A: auto-deploy, no tests (docs, templates, test files)
  - Tier B+: test-gated auto-deploy (bridge .py files)
  - Tier B: requires Discord approval (config files)
  - Tier C: reject (kernel files, security, plist)
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from bridge.dispatch_metrics import increment_module_counter

log = logging.getLogger(__name__)

VALID_TIERS = {"A", "B+", "B", "C"}
VALID_STATUSES = {
    "pending", "testing", "deploying", "complete",
    "failed", "rolled_back", "rejected",
}

# Kernel/security files — always Tier C (admin only)
KERNEL_PATTERNS = [
    re.compile(r"bridge/security\.py$"),
    re.compile(r"config/system-prompt\.md$"),
    re.compile(r"config/hooks/"),
    re.compile(r"config/bootstrap/"),
    re.compile(r"\.plist$"),
    re.compile(r"kernel.baseline\.json$"),
    re.compile(r"scripts/deploy_helper\.py$"),
    re.compile(r"\.secrets$"),
    re.compile(r"\.mcp\.json$"),
]

# Bridge Python files — Tier B+ (test-gated)
BRIDGE_PY_PATTERNS = [
    re.compile(r"bridge/.*\.py$"),
    re.compile(r"bridge/services/.*\.py$"),
    re.compile(r"job_search/.*\.py$"),
]

# Config files — Tier B (requires approval)
CONFIG_PATTERNS = [
    re.compile(r"\.toml$"),
    re.compile(r"config/.*\.yaml$"),
    re.compile(r"config/.*\.yml$"),
    re.compile(r"config/.*\.json$"),
]

# Auto-deploy — Tier A
AUTO_PATTERNS = [
    re.compile(r"tests/.*\.py$"),
    re.compile(r"docs/"),
    re.compile(r"templates/"),
    re.compile(r"scripts/(?!deploy_helper).*\.(sh|py)$"),
    re.compile(r"README"),
    re.compile(r"\.md$"),
]


def classify_tier(file_path: str) -> str:
    increment_module_counter("deploy_manifest.classify_tier", tier=1)
    """Classify a file path into a deployment tier."""
    # Normalize path separators
    normalized = file_path.replace("\\", "/")

    # Check kernel first (highest restriction)
    for pattern in KERNEL_PATTERNS:
        if pattern.search(normalized):
            return "C"

    # Check bridge Python
    for pattern in BRIDGE_PY_PATTERNS:
        if pattern.search(normalized):
            return "B+"

    # Check config
    for pattern in CONFIG_PATTERNS:
        if pattern.search(normalized):
            return "B"

    # Check auto-deploy
    for pattern in AUTO_PATTERNS:
        if pattern.search(normalized):
            return "A"

    # Default: require approval
    return "B"


def classify_manifest_tier(files: list[dict[str, str]]) -> str:
    """Classify the overall tier for a manifest (highest restriction wins)."""
    tier_order = ["A", "B+", "B", "C"]
    max_tier = "A"
    for f in files:
        src = f.get("source", "")
        tier = classify_tier(src)
        if tier_order.index(tier) > tier_order.index(max_tier):
            max_tier = tier
    return max_tier


def create_manifest(
    files: list[dict[str, str]],
    reason: str,
    requested_by: str = "agent",
) -> dict:
    """Create a deploy manifest.

    Args:
        files: List of {"source": "...", "target": "..."} dicts
        reason: Why this deploy is happening
        requested_by: Who requested the deploy

    Returns:
        Manifest dict with all required fields
    """
    manifest_id = str(uuid.uuid4())[:8]
    tier = classify_manifest_tier(files)
    test_required = tier in ("B+",)

    return {
        "id": manifest_id,
        "files": files,
        "tier": tier,
        "reason": reason,
        "test_required": test_required,
        "requested_by": requested_by,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
    }


def validate_manifest(manifest: dict) -> list[str]:
    """Validate a deploy manifest. Returns list of errors."""
    errors: list[str] = []

    if not manifest.get("id"):
        errors.append("'id' is required")

    if not manifest.get("files") or not isinstance(manifest["files"], list):
        errors.append("'files' must be a non-empty list")
    else:
        for i, f in enumerate(manifest["files"]):
            if not isinstance(f, dict):
                errors.append(f"files[{i}] must be a dict")
            elif not f.get("source"):
                errors.append(f"files[{i}] missing 'source'")

    tier = manifest.get("tier", "")
    if tier not in VALID_TIERS:
        errors.append(f"'tier' must be one of {VALID_TIERS}, got '{tier}'")

    status = manifest.get("status", "")
    if status not in VALID_STATUSES:
        errors.append(f"'status' must be one of {VALID_STATUSES}, got '{status}'")

    if not manifest.get("reason"):
        errors.append("'reason' is required")

    return errors


def write_manifest(manifest: dict, requests_dir: str | Path) -> Path:
    """Write manifest to deploy-requests directory atomically."""
    requests_dir = Path(requests_dir)
    requests_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{manifest['id']}.json"
    target = requests_dir / filename

    fd, tmp = tempfile.mkstemp(dir=str(requests_dir), suffix=".json")
    try:
        os.write(fd, (json.dumps(manifest, indent=2) + "\n").encode())
        os.close(fd)
        os.replace(tmp, str(target))
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise

    return target


def read_manifest(path: str | Path) -> dict:
    """Read a manifest file."""
    return json.loads(Path(path).read_text())


def update_manifest_status(
    path: str | Path,
    status: str,
    extra: dict | None = None,
) -> dict:
    """Update the status of a manifest file."""
    path = Path(path)
    manifest = json.loads(path.read_text())
    manifest["status"] = status
    manifest[f"{status}_at"] = datetime.now(timezone.utc).isoformat()
    if extra:
        manifest.update(extra)
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


# --- Deploy History ---

def append_history(
    history_file: str | Path,
    manifest: dict,
    result: dict | None = None,
) -> None:
    """Append a deploy record to the history JSONL file."""
    history_file = Path(history_file)
    history_file.parent.mkdir(parents=True, exist_ok=True)

    record = {
        "deploy_id": manifest.get("id"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "files": [f.get("source", "") for f in manifest.get("files", [])],
        "tier": manifest.get("tier"),
        "test_result": result.get("test_result") if result else None,
        "deploy_result": manifest.get("status"),
        "rolled_back": manifest.get("status") == "rolled_back",
        "duration_ms": result.get("duration_ms") if result else None,
    }

    with open(history_file, "a") as f:
        f.write(json.dumps(record) + "\n")


def read_history(history_file: str | Path, limit: int = 50) -> list[dict]:
    """Read recent deploy history."""
    path = Path(history_file)
    if not path.exists():
        return []

    lines = path.read_text().strip().split("\n")
    records = []
    for line in lines[-limit:]:
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


# --- Rollback Support ---

def create_backup_manifest(
    deploy_id: str,
    files: list[dict[str, str]],
    backup_dir: str | Path,
) -> dict:
    """Create a backup manifest for pre-deploy backup."""
    backup = {
        "deploy_id": deploy_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": [],
    }

    backup_path = Path(backup_dir) / deploy_id
    backup_path.mkdir(parents=True, exist_ok=True)

    for f in files:
        target = Path(f.get("target", ""))
        if target.exists():
            # Record original file info
            import hashlib
            content = target.read_bytes()
            sha256 = hashlib.sha256(content).hexdigest()

            # Copy to backup
            backup_file = backup_path / target.name
            backup_file.write_bytes(content)

            backup["files"].append({
                "original_path": str(target),
                "backup_path": str(backup_file),
                "sha256": sha256,
                "size": len(content),
            })

    # Write backup manifest
    manifest_path = backup_path / "backup-manifest.json"
    manifest_path.write_text(json.dumps(backup, indent=2) + "\n")

    return backup


def restore_from_backup(backup_dir: str | Path, deploy_id: str) -> list[str]:
    """Restore files from a backup. Returns list of restored file paths."""
    backup_path = Path(backup_dir) / deploy_id
    manifest_path = backup_path / "backup-manifest.json"

    if not manifest_path.exists():
        raise FileNotFoundError(f"No backup found for deploy {deploy_id}")

    manifest = json.loads(manifest_path.read_text())
    restored: list[str] = []

    for f in manifest.get("files", []):
        backup_file = Path(f["backup_path"])
        original = Path(f["original_path"])

        if backup_file.exists():
            # Verify hash
            import hashlib
            content = backup_file.read_bytes()
            actual_hash = hashlib.sha256(content).hexdigest()
            if actual_hash != f["sha256"]:
                log.warning("Backup hash mismatch for %s", original)

            original.parent.mkdir(parents=True, exist_ok=True)
            original.write_bytes(content)
            restored.append(str(original))
            log.info("Restored: %s", original)

    return restored


def purge_old_backups(backup_dir: str | Path, max_age_days: int = 7) -> int:
    """Remove backups older than max_age_days. Returns count removed."""
    import shutil

    backup_path = Path(backup_dir)
    if not backup_path.exists():
        return 0

    removed = 0
    cutoff = datetime.now(timezone.utc)

    for entry in backup_path.iterdir():
        if not entry.is_dir():
            continue
        manifest_path = entry / "backup-manifest.json"
        if not manifest_path.exists():
            continue

        try:
            manifest = json.loads(manifest_path.read_text())
            created = datetime.fromisoformat(manifest["created_at"])
            age_days = (cutoff - created).days
            if age_days > max_age_days:
                shutil.rmtree(entry)
                removed += 1
        except (json.JSONDecodeError, KeyError, ValueError):
            continue

    return removed

"""Per-board credential vault for job-search browser-use (#2160 / Sprint 5j.05).

Implements the design from `docs/architecture/adr/2026-05-18-job-search-credential-vault.md`:

- **Storage**: extension of existing `.secrets` flat file (honors Infisical
  ADR DEFER decision; matches `calcom_api_key_<account>` namespacing precedent)
- **Key shape**: `ats_<family>_<account>_<field>` (lowercase family + account)
- **Access pattern**: chief passes a REFERENCE (e.g. `ats_greenhouse_main`);
  only `browser-use-specialist` running in the bumba-browser sandbox
  resolves the actual field values via `read_credentials(ref)`
- **Rotation**: operator-initiated; in-flight sessions complete with old
  values; new values take effect on next session start (after daemon restart)

Application-layer allowlist gates which keys can be resolved through this
module. Non-`ats_*` keys are rejected with `KeyError` even when present in
`.secrets` — defense in depth on top of the OS-level file-mode/group scoping
established by the sandbox ADR (#2158).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# Default secrets file location matches the documented operator pattern.
_DEFAULT_SECRETS_PATH = Path("/opt/bumba-harness/data/.secrets")

# Per-ATS-family canonical field set. Each family declares the field keys
# the workflow expects to find under `ats_<family>_<account>_<field>`.
# A family with fewer fields than declared is OK (operator may seed only
# what they need); a family with EXTRA undeclared fields is a violation
# and is logged + skipped on read.
FAMILY_FIELD_SETS: dict[str, frozenset[str]] = {
    "greenhouse": frozenset({"email", "password", "mfa_secret"}),
    "lever": frozenset({"email", "password", "mfa_secret"}),
    "workday": frozenset({"email", "password", "mfa_secret"}),
    "ashby": frozenset({"email", "password", "mfa_secret"}),
    "bamboohr": frozenset({"email", "password", "mfa_secret"}),
}

# The application-layer allowlist regex. Only keys matching this pattern
# are readable through `read_credentials` / `list_accounts`. Defends
# against accidental cross-key reads even if file mode/group is
# misconfigured at the OS layer.
_ALLOWED_KEY_REGEX = re.compile(
    r"^ats_([a-z]+)_([a-z0-9]+)_([a-z_]+)$"
)


@dataclass(frozen=True)
class CredentialRef:
    """A reference to a per-account credential set. Chief passes this; the
    specialist resolves it via `read_credentials`."""

    family: str
    account: str

    def __post_init__(self) -> None:
        if not self.family or not self.account:
            raise ValueError(
                f"CredentialRef requires both family + account "
                f"(got family={self.family!r}, account={self.account!r})"
            )
        if not re.fullmatch(r"[a-z]+", self.family):
            raise ValueError(
                f"family must be lowercase letters only (got {self.family!r})"
            )
        if not re.fullmatch(r"[a-z0-9]+", self.account):
            raise ValueError(
                f"account must be lowercase alphanumeric only (got {self.account!r})"
            )

    @classmethod
    def parse(cls, ref: str) -> "CredentialRef":
        """Parse a chief-passed reference string like `ats_greenhouse_main`."""
        m = re.fullmatch(r"ats_([a-z]+)_([a-z0-9]+)", ref)
        if m is None:
            raise ValueError(
                f"Invalid credential reference: {ref!r} (expected ats_<family>_<account>)"
            )
        return cls(family=m.group(1), account=m.group(2))

    def key_prefix(self) -> str:
        """Return the manifest-key prefix for this reference."""
        return f"ats_{self.family}_{self.account}_"


@dataclass(frozen=True)
class CredentialSet:
    """Resolved credential set for a per-account vault entry. The actual
    plaintext values; specialist holds this in-process only and discards
    on session end."""

    family: str
    account: str
    fields: dict[str, str]

    def get(self, field: str) -> str | None:
        """Return the value of one field, or None if not present."""
        return self.fields.get(field)


def _parse_secrets_file(path: Path) -> dict[str, str]:
    """Parse a flat key=value secrets file. Tolerant of blank lines and
    `# comment` lines. Returns dict; never raises (missing file → {})."""
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    return out


def read_credentials(
    ref: CredentialRef | str,
    *,
    secrets_path: Path | None = None,
) -> CredentialSet:
    """Resolve a credential reference to actual field values.

    Per the sandbox ADR (#2158), this function is intended to run as the
    `bumba-browser` UID. The application-layer allowlist enforces that
    only `ats_*` keys are readable; non-ats keys are silently filtered.

    Raises:
        KeyError: if no fields are present for the given (family, account).
        ValueError: if the ref is malformed.
    """
    if isinstance(ref, str):
        ref = CredentialRef.parse(ref)
    path = secrets_path or _DEFAULT_SECRETS_PATH
    all_secrets = _parse_secrets_file(path)
    prefix = ref.key_prefix()

    fields: dict[str, str] = {}
    declared_fields = FAMILY_FIELD_SETS.get(ref.family)
    for key, value in all_secrets.items():
        if not key.startswith(prefix):
            continue
        # Validate against allowlist regex (defense in depth)
        match = _ALLOWED_KEY_REGEX.match(key)
        if match is None:
            log.warning(
                "credential vault: key %r matched prefix but failed allowlist regex — skipping",
                key,
            )
            continue
        family, account, field = match.group(1), match.group(2), match.group(3)
        if family != ref.family or account != ref.account:
            continue  # paranoid: shouldn't fire given prefix match, but defensive
        if declared_fields is not None and field not in declared_fields:
            log.warning(
                "credential vault: undeclared field %r for family %s — skipping (declared: %s)",
                field,
                ref.family,
                sorted(declared_fields),
            )
            continue
        fields[field] = value

    if not fields:
        raise KeyError(
            f"No credentials found for {ref.family}/{ref.account}. "
            f"Expected keys matching {prefix}<field> in {path}."
        )
    return CredentialSet(family=ref.family, account=ref.account, fields=fields)


def list_accounts(
    family: str | None = None,
    *,
    secrets_path: Path | None = None,
) -> list[CredentialRef]:
    """Return all (family, account) pairs present in the vault.

    If `family` is given, restrict to that family. Sorted for stable
    operator-facing output.
    """
    path = secrets_path or _DEFAULT_SECRETS_PATH
    all_secrets = _parse_secrets_file(path)
    seen: set[tuple[str, str]] = set()
    for key in all_secrets:
        match = _ALLOWED_KEY_REGEX.match(key)
        if match is None:
            continue
        fam, acct, _ = match.group(1), match.group(2), match.group(3)
        if family is not None and fam != family:
            continue
        seen.add((fam, acct))
    return sorted(
        (CredentialRef(family=f, account=a) for f, a in seen),
        key=lambda r: (r.family, r.account),
    )


def list_families(*, secrets_path: Path | None = None) -> list[str]:
    """Return all ATS families with at least one credential present."""
    accounts = list_accounts(secrets_path=secrets_path)
    return sorted({r.family for r in accounts})


# ---------------------------------------------------------------------------
# Operator CLI — `python -m job_search.credentials add|list|remove`
# ---------------------------------------------------------------------------


def _cli_add(args) -> int:
    """Add or update a credential set for (family, account). Reads each
    declared field interactively from stdin; refuses to write any
    undeclared fields."""
    ref = CredentialRef(family=args.family, account=args.account)
    declared = FAMILY_FIELD_SETS.get(ref.family)
    if declared is None:
        print(
            f"Unknown family '{ref.family}'. Known: {sorted(FAMILY_FIELD_SETS)}",
        )
        return 2

    print(
        f"Adding credentials for {ref.family}/{ref.account}. "
        f"Declared fields: {sorted(declared)}",
    )
    print("Press Enter to skip a field; Ctrl-C to abort.")

    new_entries: dict[str, str] = {}
    for field in sorted(declared):
        value = input(f"  {field}: ").strip()
        if value:
            new_entries[field] = value

    if not new_entries:
        print("No values entered; aborting.")
        return 0

    # Append (or update) entries in the secrets file. Operator owns
    # the file; we read-modify-write defensively.
    path = Path(args.secrets_path) if args.secrets_path else _DEFAULT_SECRETS_PATH
    if not path.exists():
        print(f"Secrets file not found at {path}; refusing to create.")
        return 2

    existing = _parse_secrets_file(path)
    for field, value in new_entries.items():
        existing[f"{ref.key_prefix()}{field}"] = value

    # Write back. Preserve approximate ordering: existing keys first,
    # new keys appended (the parse is order-tolerant; this is for human
    # readability).
    lines = [f"{k}={v}" for k, v in existing.items()]
    path.write_text("\n".join(lines) + "\n")
    print(f"Wrote {len(new_entries)} field(s) for {ref.family}/{ref.account}")
    return 0


def _cli_list(args) -> int:
    """List all (family, account) pairs in the vault."""
    accounts = list_accounts(
        family=args.family,
        secrets_path=Path(args.secrets_path) if args.secrets_path else None,
    )
    if not accounts:
        scope = f" for family={args.family}" if args.family else ""
        print(f"No credentials found{scope}.")
        return 0
    for ref in accounts:
        try:
            cs = read_credentials(
                ref,
                secrets_path=Path(args.secrets_path) if args.secrets_path else None,
            )
            field_summary = ", ".join(sorted(cs.fields))
        except KeyError:
            field_summary = "(unreadable)"
        print(f"  {ref.family}/{ref.account} — fields: {field_summary}")
    return 0


def _cli_remove(args) -> int:
    """Remove ALL fields for a (family, account) from the vault. Requires
    `--confirm` flag; operator-protected."""
    if not args.confirm:
        print("Refusing to remove without --confirm. This deletes credential entries.")
        return 2
    ref = CredentialRef(family=args.family, account=args.account)
    path = Path(args.secrets_path) if args.secrets_path else _DEFAULT_SECRETS_PATH
    if not path.exists():
        print(f"Secrets file not found at {path}.")
        return 2

    existing = _parse_secrets_file(path)
    prefix = ref.key_prefix()
    removed = [k for k in existing if k.startswith(prefix)]
    for k in removed:
        del existing[k]
    if not removed:
        print(f"No keys matched prefix {prefix}.")
        return 0
    lines = [f"{k}={v}" for k, v in existing.items()]
    path.write_text("\n".join(lines) + "\n")
    print(f"Removed {len(removed)} key(s) for {ref.family}/{ref.account}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: `python -m job_search.credentials <add|list|remove>`"""
    import argparse

    parser = argparse.ArgumentParser(
        prog="job_search.credentials",
        description="Manage per-board credentials for the job-search vault (#2160).",
    )
    parser.add_argument(
        "--secrets-path",
        default=None,
        help=f"Override the default secrets file path ({_DEFAULT_SECRETS_PATH}).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add", help="Add or update a credential set")
    p_add.add_argument("family", help="ATS family (e.g. greenhouse, lever, workday, ashby, bamboohr)")
    p_add.add_argument("account", help="Account label (e.g. operator, test)")
    p_add.set_defaults(func=_cli_add)

    p_list = sub.add_parser("list", help="List all credential sets in the vault")
    p_list.add_argument("--family", default=None, help="Restrict to one family")
    p_list.set_defaults(func=_cli_list)

    p_rm = sub.add_parser("remove", help="Remove a credential set (use --confirm)")
    p_rm.add_argument("family", help="ATS family")
    p_rm.add_argument("account", help="Account label")
    p_rm.add_argument("--confirm", action="store_true", help="Required to actually remove")
    p_rm.set_defaults(func=_cli_remove)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

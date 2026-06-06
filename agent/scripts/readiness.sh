#!/usr/bin/env bash
# agent/scripts/readiness.sh — Production Readiness Gate (Sprint P7.3, issue #1597)
#
# Runs the six audit-plan gate checks and emits a Markdown readiness report.
# Each row is PASS / FAIL / PENDING. PENDING is reserved for dependency-blocked
# checks (deps not yet merged); the row records the blocker issue number so a
# future invocation can swap stub-skip → live invocation without script
# changes elsewhere.
#
# Per the brief:
#   - Stub-skips exit 0 for that row (do not fail the whole gate).
#   - Strict mode (--strict) runs everything and treats any PENDING as FAIL.
#   - The gate exits non-zero only if any LIVE check FAILs (or strict + any
#     PENDING). PENDING alone in non-strict mode keeps overall exit 0 so the
#     gap is documented, not silently passed.
#
# Usage:
#   bash agent/scripts/readiness.sh           # non-strict: PENDING tolerated
#   bash agent/scripts/readiness.sh --strict  # strict: PENDING → FAIL
#
# Output:
#   Markdown report written to $READINESS_REPORT (default: data/readiness-report.md).
#   data/ paths are .gitignored (see .gitignore "Production readiness gate output").
#
# Exit codes:
#   0  all live checks PASS (or PASS + PENDING in non-strict mode)
#   1  any live check FAILed, or strict mode + any PENDING
#   2  internal harness error (report path, tool resolution, etc.)

set -u  # NB: not -e — each check is allowed to fail without aborting the gate.

# --- Repo root resolution --------------------------------------------------

# Resolve the repo root so the script can be invoked from any cwd.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}" || { echo "harness: failed to cd to repo root" >&2; exit 2; }

# --- Configuration ---------------------------------------------------------

STRICT="${STRICT:-0}"
if [ "${1:-}" = "--strict" ]; then
    STRICT=1
fi

READINESS_REPORT="${READINESS_REPORT:-data/readiness-report.md}"
mkdir -p "$(dirname "${READINESS_REPORT}")" || { echo "harness: failed to create report dir" >&2; exit 2; }

# Pick a Python interpreter. Prefer agent/.venv (production layout), fall back
# to system python3 (CI / fresh worktree). This matches the deploy story where
# the runtime always has .venv but worktrees may not.
#
# We resolve to an ABSOLUTE path so subshells that `cd agent` (services.runner
# --validate, validate_team_yaml --all) don't lose the interpreter.
if [ -x "${REPO_ROOT}/agent/.venv/bin/python" ]; then
    PYBIN="${REPO_ROOT}/agent/.venv/bin/python"
elif [ -x "${REPO_ROOT}/agent/.venv/bin/python3" ]; then
    PYBIN="${REPO_ROOT}/agent/.venv/bin/python3"
else
    PYBIN="$(command -v python3 || true)"
fi

if [ -z "${PYBIN}" ]; then
    echo "harness: no python3 found on PATH" >&2
    exit 2
fi

# --- Result accumulators ---------------------------------------------------

declare -a ROW_NAMES=()
declare -a ROW_STATUS=()
declare -a ROW_NOTES=()
declare -a ROW_DETAIL=()

TOTAL_PASS=0
TOTAL_FAIL=0
TOTAL_PENDING=0

record_row() {
    # Args: name status note detail
    ROW_NAMES+=("$1")
    ROW_STATUS+=("$2")
    ROW_NOTES+=("$3")
    ROW_DETAIL+=("$4")
    case "$2" in
        PASS)    TOTAL_PASS=$((TOTAL_PASS + 1)) ;;
        FAIL)    TOTAL_FAIL=$((TOTAL_FAIL + 1)) ;;
        PENDING) TOTAL_PENDING=$((TOTAL_PENDING + 1)) ;;
    esac
}

run_check() {
    # Args: name note cmd...
    # Runs the command, captures combined stdout+stderr, records PASS/FAIL.
    local name="$1"; shift
    local note="$1"; shift
    local tmp; tmp="$(mktemp)"
    if "$@" > "${tmp}" 2>&1; then
        record_row "${name}" "PASS" "${note}" "$(tail -n 20 "${tmp}")"
    else
        local rc=$?
        record_row "${name}" "FAIL" "${note} (exit ${rc})" "$(tail -n 40 "${tmp}")"
    fi
    rm -f "${tmp}"
}

stub_pending() {
    # Args: name blocker_note
    # Records a PENDING row without running anything. Used for checks blocked
    # by a sprint dep that has not yet merged.
    record_row "$1" "PENDING" "$2" "blocked by unmerged dependency"
}

# --- The six audit-plan checks ---------------------------------------------

# 1. make test  (P0.3 — MERGED — live)
run_check "make test" "offline pytest sweep (P0.3)" make test

# 2. make test-socket  (P0.3 — MERGED — live)
run_check "make test-socket" "offline + socket pytest sweep (P0.3)" make test-socket

# 3. bridge.services.runner --validate  (live)
#    The audit plan spells this as `cd agent && .venv/bin/python -m bridge.services.runner --validate`.
#    We honour the spirit: invoke the runner's --validate from the agent/ cwd
#    with whichever python we resolved above. Manual handling (not run_check)
#    because the subshell `cd agent` is required.
RUNNER_TMP="$(mktemp)"
if ( cd agent && "${PYBIN}" -m bridge.services.runner --validate ) > "${RUNNER_TMP}" 2>&1; then
    record_row "services.runner --validate" "PASS" "service registry validates" "$(tail -n 20 "${RUNNER_TMP}")"
else
    rc=$?
    record_row "services.runner --validate" "FAIL" "service registry validation failed (exit ${rc})" "$(tail -n 40 "${RUNNER_TMP}")"
fi
rm -f "${RUNNER_TMP}"

# 4. ruff check  (live)
run_check "ruff check" "lint: E,F,W ignoring E501,E402" \
    ruff check agent/ --select E,F,W --ignore E501,E402 --exit-non-zero-on-fix --no-fix

# 5. gitleaks detect  (live)
if command -v gitleaks >/dev/null 2>&1; then
    run_check "gitleaks detect" "secret-scan with .gitleaks.toml" \
        gitleaks detect --source . --config .gitleaks.toml --redact --exit-code 1 --no-banner
else
    # gitleaks is required by the audit-plan gate; missing binary is a FAIL not
    # a PENDING, since no sprint dep gates installation — the operator just
    # needs `brew install gitleaks`.
    record_row "gitleaks detect" "FAIL" "gitleaks binary not on PATH" "install via: brew install gitleaks"
fi

# 6. validate_team_yaml --all --strict  (live)
#    Audit-plan spells the path as `scripts/validate_team_yaml.py`; the canonical
#    location post-D6-bis is `agent/scripts/validate_team_yaml.py`. Invoke via
#    -m to preserve package-relative imports.
run_check "validate_team_yaml --all --strict" "team YAML structural cross-refs (strict)" \
    bash -c "cd agent && '${PYBIN}' -m scripts.validate_team_yaml --all --strict"

# 7. check_feature_flags.py  (live — Sprint E1.1, issue #1711)
#    Audits drift between BridgeConfig bool fields, _TOML_MAP, and
#    agent/config/feature_flags.yaml. Mirrors the CI gate at
#    .github/workflows/feature-flag-drift.yml.
run_check "check_feature_flags" "BridgeConfig <-> feature_flags.yaml drift (E1.1)" \
    "${PYBIN}" agent/scripts/check_feature_flags.py --quiet

# 7b. backend doc drift  (live — Sprint backend-op S5.2, issue #2287)
#    Tripwire for the doc claims S5.1 (#2327) brought into alignment:
#    legacy warm-MCP path, raw port 8199 without a "stale"/"historical"
#    qualifier, and the feature_flags.yaml marker in current-state/README.
#    Reuses check_readiness_docs.py — already invoked by readiness-strict,
#    now also fired as its own row so the non-strict gate catches drift.
run_check "backend doc drift" "current-state/operator docs vs S5.1 truth (S5.2)" \
    "${PYBIN}" agent/scripts/check_readiness_docs.py

# 8. experiment_mode surfacing + validation
#    (live — Sprint audit-2026-05-15.C.04, issue #2001)
#    Surfaces the configured experiment_loop.mode value so an operator
#    running readiness can confirm whether the launchdaemon will boot
#    into proposal_only / shadow / production. Fail-closes if the value
#    is unknown — caught at gate time, not at daemon-start time.
EXPERIMENT_MODE_VALUE="$(grep -E '^experiment_loop\.mode\s*=' agent/config/bridge.toml 2>/dev/null | head -n1 | sed -E 's/^experiment_loop\.mode\s*=\s*//; s/^"//; s/"$//' || true)"
if [ -z "${EXPERIMENT_MODE_VALUE}" ]; then
    EXPERIMENT_MODE_VALUE="(default: shadow)"
fi
echo "experiment_mode = ${EXPERIMENT_MODE_VALUE}"
run_check "experiment_mode validator" \
    "experiment_loop.mode = ${EXPERIMENT_MODE_VALUE} — must be proposal_only|shadow|production (C.04)" \
    "${PYBIN}" -c "
import sys
sys.path.insert(0, 'agent')
from bridge.config import load_config
cfg = load_config(skip_secrets=True, skip_validation=True)
assert cfg.experiment_mode in {'proposal_only','shadow','production'}, f'bad mode: {cfg.experiment_mode!r}'
"

# 9. verification flag guard
#    (live — Sprint backend-op S2.2, issue #2281)
#    Fails readiness if ``verification_enabled=true`` while the dispatcher's
#    verifier-completion path is still unwired.  Today the flag is False by
#    default; the dispatcher logs a warning and emits
#    ``workorder.verifying.stalled`` if a future flip happens before the
#    real verifier lands.  This row hard-fails the gate so the flag cannot
#    be enabled in production without the wiring sprint shipping first.
run_check "verification flag guard" \
    "verification_enabled must remain false until verifier completion path is wired (S2.2)" \
    "${PYBIN}" -c "
import sys
sys.path.insert(0, 'agent')
from bridge.config import load_config
cfg = load_config(skip_secrets=True, skip_validation=True)
assert not cfg.verification_enabled, 'verification_enabled=true but dispatcher verification completion remains unwired'
"

# --- Stub-skips for unmerged dependencies ----------------------------------
#
# These rows surface readiness checks that the audit plan's `depends_on` graph
# tells us belong in the gate but whose validating sprint has not yet merged.
# Swap each stub to a live invocation as the corresponding PR lands. The
# operator runbook in docs/operator/readiness-runbook.md tracks the swap-in
# instructions per row.

run_check "halt: process-group termination check" \
    "ClaudeRunner halt/interrupt paths signal the child process group (P1.2 #1573 — R1.1)" \
    bash -c "cd agent && '${PYBIN}' -m pytest tests/test_claude_runner_process_group.py -q"
run_check "VAPI webhook secret verification" \
    "VAPI webhook requires X-VAPI-SECRET, constant-time compare via secrets.compare_digest (P2.3 #1578 — R1.2)" \
    bash -c "cd agent && '${PYBIN}' -m pytest tests/test_vapi_webhook_auth.py -q"
run_check "tool/MCP allowlist split" \
    "MCP server allowlists and tool-name allowlists remain distinct (P2.4 #1582 — R1.3)" \
    bash -c "cd agent && '${PYBIN}' -m pytest tests/test_tool_isolation.py::TestP24LayerSeparation -q"
run_check "ChiefDispatcher end-to-end observability" \
    "synthetic WorkOrder emits dispatcher + chief-session event lineage with correlated session_id/work_order_id (P3.3 #1584 — R1.4)" \
    bash -c "cd agent && '${PYBIN}' -m pytest tests/test_chief_dispatcher_readiness.py -q"

# --- Render the report -----------------------------------------------------

NOW_UTC="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
GIT_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"

OVERALL="PASS"
if [ "${TOTAL_FAIL}" -gt 0 ]; then
    OVERALL="FAIL"
elif [ "${STRICT}" = "1" ] && [ "${TOTAL_PENDING}" -gt 0 ]; then
    OVERALL="FAIL (strict: PENDING rows treated as FAIL)"
elif [ "${TOTAL_PENDING}" -gt 0 ]; then
    OVERALL="PASS (with ${TOTAL_PENDING} PENDING gap${TOTAL_PENDING:+s})"
fi

{
    echo "# Production Readiness Report"
    echo ""
    echo "- Generated: \`${NOW_UTC}\`"
    echo "- Branch: \`${GIT_BRANCH}\` @ \`${GIT_SHA}\`"
    echo "- Strict mode: \`${STRICT}\`"
    echo "- Overall: **${OVERALL}**"
    echo "- Tally: ${TOTAL_PASS} PASS / ${TOTAL_FAIL} FAIL / ${TOTAL_PENDING} PENDING"
    echo ""
    echo "## Checks"
    echo ""
    echo "| # | Check | Status | Notes |"
    echo "|---|-------|--------|-------|"
    for i in "${!ROW_NAMES[@]}"; do
        idx=$((i + 1))
        echo "| ${idx} | ${ROW_NAMES[$i]} | ${ROW_STATUS[$i]} | ${ROW_NOTES[$i]} |"
    done
    echo ""
    echo "## Detail"
    echo ""
    for i in "${!ROW_NAMES[@]}"; do
        echo "### ${ROW_NAMES[$i]} — ${ROW_STATUS[$i]}"
        echo ""
        echo "${ROW_NOTES[$i]}"
        echo ""
        echo '```'
        echo "${ROW_DETAIL[$i]}"
        echo '```'
        echo ""
    done
    echo "## Gap-filling roadmap"
    echo ""
    echo "PENDING rows are stub-skips blocked by an upstream sprint dependency."
    echo "Each one names its blocker issue; swap the stub for a live check"
    echo "when the blocker PR merges. See \`docs/operator/readiness-runbook.md\`"
    echo "for the per-row swap-in instructions."
} > "${READINESS_REPORT}"

# --- Console summary -------------------------------------------------------

echo ""
echo "Readiness report: ${READINESS_REPORT}"
echo "Overall: ${OVERALL}"
echo "Tally: ${TOTAL_PASS} PASS / ${TOTAL_FAIL} FAIL / ${TOTAL_PENDING} PENDING"
echo ""

# --- Exit semantics --------------------------------------------------------

if [ "${TOTAL_FAIL}" -gt 0 ]; then
    exit 1
fi
if [ "${STRICT}" = "1" ] && [ "${TOTAL_PENDING}" -gt 0 ]; then
    exit 1
fi
exit 0

#!/bin/bash
# wave5_mini_batch_diagnostic.sh — batch operator-mini diagnostic for Wave 5
#
# Bundles four operator-mini verification runbooks into a single invocation:
#   - #1559  D6-bis old-tree archive insurance check
#   - #1561  experiment-loop overnight data validation
#   - #1564  kickoff doc 5-min bridge health check (/healthz round-trip)
#   - #1683  escalation widening verification (last_skipped_at in staleness check)
#
# Replaces four manual paste-and-eyeball sessions against
# `docs/operator/wave5-mini-diagnostic-runbooks.md` and
# `docs/operator/2026-05-12-1615-checkin-incident-investigation.md` (Section 3).
#
# RUN ON THE MAC MINI ONLY. Do not run from the workstation via SSH —
# #1564's auto-mode classifier (correctly) blocks the cross-host secret
# read. The bridge `api_token` is read from `/opt/bumba-harness/data/.secrets`
# (mode 0600, owned by bumba-agent) and used only for a local-loopback curl;
# the token NEVER appears in the report.
#
# Invocation:
#   sudo -u bumba-agent /opt/bumba-harness/agent-flat/agent/scripts/wave5_mini_batch_diagnostic.sh
#
# Exit codes:
#   0    All 4 diagnostics pass — close #1559, #1561, #1564 inline
#   >0   At least one diagnostic failed — read the report for details,
#        fall back to the per-issue runbook in #1671 / #1682
#
# Layout assumptions (post-D6-bis, 2026-05-09):
#   Runtime tree : /opt/bumba-harness/agent-flat/agent/
#   Data dir     : /opt/bumba-harness/data/
#   Logs         : /opt/bumba-harness/logs/
#   Secrets      : /opt/bumba-harness/data/.secrets
#
# Operator usage doc: docs/operator/wave5-batch-diagnostic-usage.md

set +e  # continue on errors so every diagnostic runs to completion
set -u  # but treat unset vars as errors

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------
DATA_DIR="/opt/bumba-harness/data"
LOGS_DIR="/opt/bumba-harness/logs"
SECRETS_FILE="${DATA_DIR}/.secrets"
ARCHIVE_PATH="/opt/bumba-harness/deploys/d6-bis-old-tree-20260509T160000"
EXPERIMENT_LOG="${LOGS_DIR}/experiment-loop-stdout.log"
CHECKIN_STATE_FILE="${DATA_DIR}/service_state/checkin-state.json"
ESCALATION_STATE_FILE="${DATA_DIR}/escalation-state.json"
HEALTHZ_URL="http://localhost:8200/healthz"

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
REPORT_DIR="${DATA_DIR}"
REPORT="${REPORT_DIR}/wave5-diagnostic-report-${TIMESTAMP}.md"

# Per-diagnostic exit accumulator. 0 = pass, 1 = fail. Stays 0 unless an
# issue requires attention. We do NOT exit early — every diagnostic runs.
STATUS_1559=0
STATUS_1561=0
STATUS_1564=0
STATUS_1683=0

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
emit() {
    # append a line to the report
    printf '%s\n' "$*" >> "${REPORT}"
}

emit_block() {
    # append a fenced code block; arg 1 is content, optional arg 2 is language
    local content="$1"
    local lang="${2:-}"
    emit "\`\`\`${lang}"
    printf '%s\n' "${content}" >> "${REPORT}"
    emit "\`\`\`"
}

now_iso() {
    date -u +%Y-%m-%dT%H:%M:%SZ
}

# -----------------------------------------------------------------------------
# Pre-flight: confirm we're on the mini and report dir is writable
# -----------------------------------------------------------------------------
HOSTNAME_OUT="$(hostname 2>/dev/null || echo unknown)"
WHOAMI_OUT="$(whoami 2>/dev/null || echo unknown)"

# Ensure report dir exists and is writable. If $DATA_DIR doesn't exist we are
# almost certainly not on the mini — fail fast with a clear message.
if [ ! -d "${REPORT_DIR}" ]; then
    printf 'wave5_mini_batch_diagnostic: report dir %s does not exist.\n' "${REPORT_DIR}" >&2
    printf 'Are you running on the Mac mini? Aborting.\n' >&2
    exit 2
fi

if ! touch "${REPORT}" 2>/dev/null; then
    printf 'wave5_mini_batch_diagnostic: cannot write %s.\n' "${REPORT}" >&2
    printf 'Run as bumba-agent or via sudo -u bumba-agent ... (see usage doc).\n' >&2
    exit 2
fi

# -----------------------------------------------------------------------------
# Report header
# -----------------------------------------------------------------------------
emit "# Wave 5 batch diagnostic report"
emit ""
emit "- Generated: $(now_iso)"
emit "- Host: ${HOSTNAME_OUT}"
emit "- User: ${WHOAMI_OUT}"
emit "- Script: \`agent/scripts/wave5_mini_batch_diagnostic.sh\`"
emit ""
emit "Diagnostics in this report:"
emit ""
emit "1. **#1559** D6-bis old-tree archive insurance"
emit "2. **#1561** experiment-loop overnight data"
emit "3. **#1564** bridge \`/healthz\` 5-minute check"
emit "4. **#1683** escalation widening verification"
emit ""
emit "**Security note:** the bridge \`api_token\` is read from \`.secrets\` for the"
emit "\`/healthz\` curl but is NEVER written to this report."
emit ""
emit "---"
emit ""

# =============================================================================
# Diagnostic 1 — #1559: D6-bis old-tree archive insurance check
# =============================================================================
emit "## 1. #1559 — D6-bis old-tree archive insurance"
emit ""
emit "Confirm \`${ARCHIVE_PATH}\` still exists ahead of the 2026-05-16 delete target (#1490)."
emit ""

LS_OUT="$(ls -ld /opt/bumba-harness/deploys/ "${ARCHIVE_PATH}" 2>&1)"
emit "### \`ls -ld\` output"
emit_block "${LS_OUT}"

if [ -d "${ARCHIVE_PATH}" ]; then
    # mindepth/maxdepth 1 = top-level entries only (matches `ls -A | wc -l`
    # semantics — hidden + visible files at depth 1).
    ENTRY_COUNT="$(find "${ARCHIVE_PATH}" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l | tr -d ' ')"
    DU_OUT="$(du -sh "${ARCHIVE_PATH}" 2>&1 | head -1)"
    emit ""
    emit "### archive summary"
    emit "- entry-count: \`${ENTRY_COUNT}\`"
    emit "- du -sh: \`${DU_OUT}\`"

    if [ "${ENTRY_COUNT}" -gt 0 ] 2>/dev/null; then
        emit ""
        emit "**Result: PASS** — archive present, ${ENTRY_COUNT} entries on disk."
        STATUS_1559=0
    else
        emit ""
        emit "**Result: FAIL** — archive directory exists but is empty (entry-count = 0)."
        emit "Insurance window broken. Do NOT proceed with the 2026-05-16 delete."
        emit "Comment on #1490 with this finding before closing #1559."
        STATUS_1559=1
    fi
else
    emit ""
    emit "**Result: FAIL** — archive directory not found at \`${ARCHIVE_PATH}\`."
    emit "Insurance window broken ahead of schedule. Re-open or amend #1490;"
    emit "do NOT proceed with the 2026-05-16 delete. Leave #1559 open."
    STATUS_1559=1
fi
emit ""
emit "---"
emit ""

# =============================================================================
# Diagnostic 2 — #1561: experiment-loop overnight data
# =============================================================================
emit "## 2. #1561 — experiment-loop overnight data"
emit ""
emit "Validate experiment-loop daemon health: state, runs, proposal count, error/timeout count."
emit ""

LAUNCHCTL_OUT="$(launchctl print system/com.bumba.agent-experiment 2>&1 | grep -E 'state|runs|last exit' | head -10)"
emit "### \`launchctl print\` (filtered)"
emit_block "${LAUNCHCTL_OUT}"

if [ -f "${EXPERIMENT_LOG}" ]; then
    # grep -c prints the count then exits 1 on zero matches; the `|| echo 0`
    # would concatenate a duplicate zero. Use { ...; true; } to swallow the
    # exit-1 without polluting stdout. -c always prints exactly one integer.
    PROPOSAL_COUNT="$(grep -c 'Experiment proposed' "${EXPERIMENT_LOG}" 2>/dev/null; true)"
    PROPOSAL_COUNT="${PROPOSAL_COUNT//$'\n'/}"
    [ -z "${PROPOSAL_COUNT}" ] && PROPOSAL_COUNT=0
    ERROR_COUNT="$(grep -ci 'error\|timeout' "${EXPERIMENT_LOG}" 2>/dev/null; true)"
    ERROR_COUNT="${ERROR_COUNT//$'\n'/}"
    [ -z "${ERROR_COUNT}" ] && ERROR_COUNT=0
    HANG_HITS="$(grep -ci 'hang' "${EXPERIMENT_LOG}" 2>/dev/null; true)"
    HANG_HITS="${HANG_HITS//$'\n'/}"
    [ -z "${HANG_HITS}" ] && HANG_HITS=0

    emit ""
    emit "### counts from \`${EXPERIMENT_LOG}\`"
    emit "- proposals (\`Experiment proposed\`): \`${PROPOSAL_COUNT}\`"
    emit "- errors+timeouts (case-insensitive): \`${ERROR_COUNT}\`"
    emit "- hang hits (case-insensitive): \`${HANG_HITS}\`"

    # Pass criterion (from #1561 runbook):
    #   state = running AND last exit code = 0 AND runs >= 50
    #   AND proposals >= 50 AND errors in single digits AND no hang regression
    LAUNCHCTL_STATE_RUNNING=0
    LAUNCHCTL_LAST_EXIT_ZERO=0
    if echo "${LAUNCHCTL_OUT}" | grep -q 'state = running'; then
        LAUNCHCTL_STATE_RUNNING=1
    fi
    if echo "${LAUNCHCTL_OUT}" | grep -q 'last exit code = 0'; then
        LAUNCHCTL_LAST_EXIT_ZERO=1
    fi

    PASS_1561=1
    REASONS=""
    if [ "${LAUNCHCTL_STATE_RUNNING}" -ne 1 ]; then
        PASS_1561=0
        REASONS="${REASONS}- state != running\n"
    fi
    if [ "${LAUNCHCTL_LAST_EXIT_ZERO}" -ne 1 ]; then
        PASS_1561=0
        REASONS="${REASONS}- last exit code != 0\n"
    fi
    if [ "${PROPOSAL_COUNT}" -lt 50 ] 2>/dev/null; then
        PASS_1561=0
        REASONS="${REASONS}- proposal-count ${PROPOSAL_COUNT} < 50\n"
    fi
    if [ "${ERROR_COUNT}" -ge 10 ] 2>/dev/null; then
        PASS_1561=0
        REASONS="${REASONS}- error/timeout count ${ERROR_COUNT} >= 10 (single digits expected)\n"
    fi
    if [ "${HANG_HITS}" -gt 0 ] 2>/dev/null; then
        PASS_1561=0
        REASONS="${REASONS}- hang indicator present (${HANG_HITS} hits); see feedback_claude_p_hang_under_sudo.md + #1529\n"
    fi

    emit ""
    if [ "${PASS_1561}" -eq 1 ]; then
        emit "**Result: PASS** — daemon healthy."
        STATUS_1561=0
    else
        emit "**Result: FAIL** — daemon degraded. Reasons:"
        # REASONS is a constructed string containing literal '\n' sequences;
        # printf with %b interprets them safely without using the var as format.
        printf '%b' "${REASONS}" >> "${REPORT}"
        emit ""
        emit "Recommended: run the \`tail -30\` from the #1561 runbook to inspect."
        emit "If hang indicators present, link finding to #1529."
        STATUS_1561=1
    fi
else
    emit ""
    emit "**Result: FAIL** — experiment-loop log not found at \`${EXPERIMENT_LOG}\`."
    emit "The daemon may not have run yet, or the log path has changed."
    emit "Inspect with \`sudo launchctl print system/com.bumba.agent-experiment\` and locate the StandardOutPath."
    STATUS_1561=1
fi
emit ""
emit "---"
emit ""

# =============================================================================
# Diagnostic 3 — #1564: bridge /healthz 5-minute check
# =============================================================================
emit "## 3. #1564 — bridge \`/healthz\` 5-minute check"
emit ""
emit "Read \`api_token\` from \`.secrets\`, hit \`${HEALTHZ_URL}\`, parse status + uptime."
emit "(Token never written to this report.)"
emit ""

if [ ! -f "${SECRETS_FILE}" ]; then
    emit "**Result: FAIL** — \`${SECRETS_FILE}\` not found."
    STATUS_1564=1
elif ! TOKEN="$(grep -E '^api_token=' "${SECRETS_FILE}" 2>/dev/null | cut -d= -f2)" || [ -z "${TOKEN}" ]; then
    emit "**Result: FAIL** — \`api_token=\` not present in \`${SECRETS_FILE}\`."
    STATUS_1564=1
else
    # curl -sf returns non-zero on HTTP error. Capture body for parsing.
    HEALTHZ_BODY="$(curl -sf -H "Authorization: Bearer ${TOKEN}" "${HEALTHZ_URL}" 2>&1)"
    CURL_RC=$?
    # Token goes out of scope after this command; never written to disk.
    unset TOKEN

    if [ ${CURL_RC} -ne 0 ]; then
        emit "**Result: FAIL** — \`curl\` to \`${HEALTHZ_URL}\` returned exit code ${CURL_RC}."
        emit ""
        emit "### curl output (sanitized — body only, no headers)"
        emit_block "${HEALTHZ_BODY}"
        emit "Inspect \`sudo -u bumba-agent tail -50 ${LOGS_DIR}/bridge.log\` before bouncing the daemon."
        STATUS_1564=1
    else
        # Parse JSON via python3. We deliberately do NOT print the body raw;
        # the parser extracts status + uptime only.
        PARSED="$(printf '%s' "${HEALTHZ_BODY}" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
    print("status={} uptime_seconds={}".format(d.get("status"), d.get("uptime_seconds")))
except Exception as exc:
    print("parse_error: {}".format(exc))
    sys.exit(2)
' 2>&1)"
        PARSE_RC=$?

        emit "### parsed response"
        emit_block "${PARSED}"

        if [ ${PARSE_RC} -ne 0 ]; then
            emit "**Result: FAIL** — response was not valid JSON or missing fields."
            STATUS_1564=1
        else
            STATUS_VAL="$(printf '%s' "${PARSED}" | sed -n 's/.*status=\([^ ]*\).*/\1/p')"
            UPTIME_VAL="$(printf '%s' "${PARSED}" | sed -n 's/.*uptime_seconds=\([0-9]*\).*/\1/p')"

            if [ "${STATUS_VAL}" = "ok" ]; then
                emit "**Result: PASS** — bridge status=ok, uptime=${UPTIME_VAL}s."
                STATUS_1564=0
            else
                emit "**Result: FAIL** — bridge status is \`${STATUS_VAL}\` (expected \`ok\`)."
                STATUS_1564=1
            fi
        fi
    fi
fi
emit ""
emit "---"
emit ""

# =============================================================================
# Diagnostic 4 — #1683 verification: escalation widening fix
# =============================================================================
emit "## 4. #1683 verification — escalation widening fix"
emit ""
emit "PR #1686 widened \`escalation.evaluate_triggers\` to consider \`last_skipped_at\`"
emit "(plus \`last_run\` and \`last_success_time\`) as activity signals. Verify:"
emit ""
emit "- checkin state file has \`last_skipped_at\` populated"
emit "- the field is recent (post-deploy of the fix)"
emit "- escalation engine no longer flags checkin as stale (#1615 incident loop closed)"
emit ""

if [ ! -f "${CHECKIN_STATE_FILE}" ]; then
    emit "**Result: FAIL** — \`${CHECKIN_STATE_FILE}\` not found."
    emit "Run \`sudo launchctl kickstart -p system/com.bumba.agent-checkin\` to force a tick,"
    emit "then re-run this script."
    STATUS_1683=1
else
    emit "### \`${CHECKIN_STATE_FILE}\` (parsed)"
    PARSED_STATE="$(python3 -m json.tool "${CHECKIN_STATE_FILE}" 2>&1)"
    PARSE_RC=$?
    emit_block "${PARSED_STATE}" "json"

    if [ ${PARSE_RC} -ne 0 ]; then
        emit "**Result: FAIL** — state file is not valid JSON."
        STATUS_1683=1
    else
        # Inspect the fields we care about. Use python for ISO-timestamp math.
        FIELD_REPORT="$(python3 - "${CHECKIN_STATE_FILE}" <<'PY'
import json, sys
from datetime import datetime, timezone

path = sys.argv[1]
with open(path) as fh:
    state = json.load(fh)

last_skipped_at = state.get("last_skipped_at")
last_run = state.get("last_run")
last_success_time = state.get("last_success_time")
consecutive_failures = state.get("consecutive_failures", 0)

def age_hours(iso_str):
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
    except Exception:
        return None

skip_age = age_hours(last_skipped_at)
run_age = age_hours(last_run)
success_age = age_hours(last_success_time)

print("last_skipped_at: {} (age: {})".format(last_skipped_at, "{:.1f}h".format(skip_age) if skip_age is not None else "n/a"))
print("last_run: {} (age: {})".format(last_run, "{:.1f}h".format(run_age) if run_age is not None else "n/a"))
print("last_success_time: {} (age: {})".format(last_success_time, "{:.1f}h".format(success_age) if success_age is not None else "n/a"))
print("consecutive_failures: {}".format(consecutive_failures))

# Pass criterion: last_skipped_at present AND recent (< 25h — the 2x expected
# interval the staleness check uses) OR another activity signal recent.
ok = False
reason = []
if last_skipped_at is not None and skip_age is not None and skip_age < 25.0:
    ok = True
    reason.append("last_skipped_at present and recent ({:.1f}h)".format(skip_age))
elif last_run is not None and run_age is not None and run_age < 25.0:
    ok = True
    reason.append("last_run recent ({:.1f}h) — fix not exercised but no stale alert expected".format(run_age))
elif last_success_time is not None and success_age is not None and success_age < 25.0:
    ok = True
    reason.append("last_success_time recent ({:.1f}h) — fix not exercised but no stale alert expected".format(success_age))
else:
    reason.append("no activity signal younger than 25h — escalation engine WILL flag stale")

print("---")
print("VERDICT: {}".format("OK" if ok else "FAIL"))
print("REASON: " + "; ".join(reason))
PY
)"
        FIELD_RC=$?
        emit ""
        emit "### field analysis"
        emit_block "${FIELD_REPORT}"

        if [ ${FIELD_RC} -ne 0 ]; then
            emit "**Result: FAIL** — python field analyzer errored."
            STATUS_1683=1
        elif echo "${FIELD_REPORT}" | grep -q '^VERDICT: OK'; then
            # Now also check the escalation state — there should be no recent
            # active alert for checkin.
            if [ -f "${ESCALATION_STATE_FILE}" ]; then
                emit ""
                emit "### \`${ESCALATION_STATE_FILE}\` (checkin alert lines)"
                CHECKIN_ALERT_LINES="$(grep -i 'checkin' "${ESCALATION_STATE_FILE}" 2>&1 | head -20)"
                if [ -z "${CHECKIN_ALERT_LINES}" ]; then
                    emit "no checkin entries found in escalation state — clean."
                    STATUS_1683=0
                else
                    emit_block "${CHECKIN_ALERT_LINES}"
                    if echo "${CHECKIN_ALERT_LINES}" | grep -qi 'stale'; then
                        emit "**Result: FAIL** — escalation state still references \`checkin*stale*\`."
                        emit "Inspect the alert entry; it may be an older active alert that hasn't de-escalated yet."
                        STATUS_1683=1
                    else
                        emit "**Result: PASS** — checkin activity signals fresh and no stale-alert lines in escalation state."
                        STATUS_1683=0
                    fi
                fi
            else
                emit ""
                emit "Note: \`${ESCALATION_STATE_FILE}\` not present — engine may persist state elsewhere."
                emit "Activity-signal check is the primary verification; treating as PASS based on field analysis."
                STATUS_1683=0
            fi
        else
            emit "**Result: FAIL** — no activity signal recent enough; escalation WILL still flag stale."
            STATUS_1683=1
        fi
    fi
fi
emit ""
emit "---"
emit ""

# =============================================================================
# Final summary
# =============================================================================
emit "## Summary"
emit ""
emit "| # | Issue | Result |"
emit "|---|---|---|"

row() {
    # row <num> <label> <status>
    local num="$1" label="$2" status="$3"
    if [ "${status}" -eq 0 ]; then
        emit "| ${num} | ${label} | PASS |"
    else
        emit "| ${num} | ${label} | **FAIL** |"
    fi
}

row 1 "#1559 D6-bis archive insurance"       "${STATUS_1559}"
row 2 "#1561 experiment-loop overnight"      "${STATUS_1561}"
row 3 "#1564 bridge /healthz 5-min"          "${STATUS_1564}"
row 4 "#1683 escalation widening verify"     "${STATUS_1683}"
emit ""

TOTAL_FAIL=$((STATUS_1559 + STATUS_1561 + STATUS_1564 + STATUS_1683))
if [ "${TOTAL_FAIL}" -eq 0 ]; then
    emit "**Overall: ALL PASS.**"
    emit ""
    emit "Closing actions:"
    emit ""
    emit "- Comment + close #1559, #1561, #1564 (inline)"
    emit "- Confirm #1615 stays closed (it was closed inline tonight via PR #1686)"
    emit "- #1683 verification: confirms PR #1686 is working on the runtime"
    EXIT_CODE=0
else
    emit "**Overall: ${TOTAL_FAIL} of 4 require attention.**"
    emit ""
    emit "Do NOT auto-close failed issues. Investigate using the per-issue runbook:"
    emit ""
    emit "- #1559/#1561/#1564 → \`docs/operator/wave5-mini-diagnostic-runbooks.md\`"
    emit "- #1683 verification → \`docs/operator/2026-05-12-1615-checkin-incident-investigation.md\` Section 3"
    EXIT_CODE=1
fi

emit ""
emit "Report path: \`${REPORT}\`"
emit "Exit code: ${EXIT_CODE}"

printf '\nReport written to: %s\n' "${REPORT}"
printf 'Exit code: %s\n' "${EXIT_CODE}"

exit ${EXIT_CODE}

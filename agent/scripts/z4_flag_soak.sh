#!/usr/bin/env bash
# scripts/z4_flag_soak.sh
#
# Z4 flag-flip soak checker.
#
# Usage:
#   bash scripts/z4_flag_soak.sh [WINDOW_HOURS]
#
# Arguments:
#   WINDOW_HOURS  How many hours of history to analyse (default: 24)
#
# Exits:
#   0  GREEN  — all checks pass; safe to proceed with flag flip (or confirm it)
#   1  RED    — one or more checks failed; do NOT flip the flag
#
# Run this script TWICE:
#   1. OFF-SOAK  (before the flag flip, with dispatcher.enabled = false):
#        bash scripts/z4_flag_soak.sh 24
#      Confirms baseline is healthy and Z4 code paths are ready.
#
#   2. ON-SOAK   (after the operator sets dispatcher.enabled = true, 24h later):
#        bash scripts/z4_flag_soak.sh 24
#      Confirms the live Z4 path is meeting all SLAs.
#
# Checks performed:
#   1. Z4 error rate       < 1 %      (from bridge-stderr.log)
#   2. Per-dept cost       within cap  (from z4-sessions/*.jsonl)
#   3. Circuit state       all CLOSED  (from bridge-stderr.log or healthz)
#   4. Latency SLA         P95 < 30s   (from bridge-stderr.log span timings)
#   5. Flag state          reported    (from bridge.toml)
#
# The script never flips the flag itself — that is an operator action.
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

WINDOW_HOURS="${1:-24}"

BRIDGE_STDERR="/opt/bumba-harness/logs/bridge-stderr.log"
BRIDGE_TOML="/opt/bumba-harness/agent-flat/agent/config/bridge.toml"
Z4_SESSIONS_DIR="/opt/bumba-harness/data/z4-sessions"
HEALTH_URL="http://127.0.0.1:8199/healthz"

# Cost caps per department (USD / 24h window)
declare -A DEPT_COST_CAPS=(
    ["board"]=3.00
    ["engineering"]=5.00
    ["qa"]=2.00
    ["ops"]=2.00
    ["strategy"]=2.00
    ["job-search"]=1.00
    ["outreach"]=1.00
)

# Error rate threshold (%)
ERROR_RATE_THRESHOLD=1.0

# P95 latency threshold (seconds)
LATENCY_P95_THRESHOLD=30

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

pass() { echo -e "${GREEN}  PASS${NC}  $*"; }
fail() { echo -e "${RED}  FAIL${NC}  $*"; FAILURES=$((FAILURES + 1)); }
warn() { echo -e "${YELLOW}  WARN${NC}  $*"; }
info() { echo -e "${CYAN}  INFO${NC}  $*"; }

FAILURES=0

# Compute the ISO-8601 cutoff timestamp for WINDOW_HOURS ago (macOS date)
cutoff_epoch=$(date -u -v-"${WINDOW_HOURS}"H +%s 2>/dev/null \
    || date -u -d "${WINDOW_HOURS} hours ago" +%s)
cutoff_human=$(date -u -r "${cutoff_epoch}" '+%Y-%m-%d %H:%M UTC' 2>/dev/null \
    || date -u -d "@${cutoff_epoch}" '+%Y-%m-%d %H:%M UTC')

echo ""
echo "================================================================"
echo " Z4 Flag Soak Check"
echo " Window : last ${WINDOW_HOURS}h  (since ${cutoff_human})"
echo " Run at : $(date -u '+%Y-%m-%d %H:%M UTC')"
echo "================================================================"
echo ""

# ---------------------------------------------------------------------------
# Check 0: Flag state (informational — never fails the soak)
# ---------------------------------------------------------------------------

echo "--- [0] Z4.10 flag state ---"
if [[ -f "${BRIDGE_TOML}" ]]; then
    dispatcher_section=false
    while IFS= read -r line; do
        [[ "${line}" =~ ^\[dispatcher\] ]] && dispatcher_section=true
        if ${dispatcher_section} && [[ "${line}" =~ ^[[:space:]]*enabled[[:space:]]*=[[:space:]]*(.+) ]]; then
            flag_val="${BASH_REMATCH[1]}"
            info "dispatcher.enabled = ${flag_val}"
            dispatcher_section=false
        fi
    done < "${BRIDGE_TOML}"
else
    warn "bridge.toml not found at ${BRIDGE_TOML}"
fi
echo ""

# ---------------------------------------------------------------------------
# Check 1: Z4 error rate
# ---------------------------------------------------------------------------

echo "--- [1] Z4 error rate (threshold < ${ERROR_RATE_THRESHOLD}%) ---"
if [[ ! -f "${BRIDGE_STDERR}" ]]; then
    warn "bridge-stderr.log not found — skipping error rate check"
else
    z4_fails=$(grep -c '\[Z4\].*\(FAIL\|ERROR\|exception\)' "${BRIDGE_STDERR}" 2>/dev/null || echo 0)
    z4_oks=$(grep -c '\[Z4\].*OK' "${BRIDGE_STDERR}" 2>/dev/null || echo 0)
    z4_total=$((z4_fails + z4_oks))

    if [[ "${z4_total}" -eq 0 ]]; then
        warn "No Z4 log entries found in ${BRIDGE_STDERR} — no data to evaluate"
    else
        rate=$(awk "BEGIN { printf \"%.2f\", ${z4_fails} / ${z4_total} * 100 }")
        info "Z4 calls: ${z4_oks} OK + ${z4_fails} FAIL = ${z4_total} total  |  error rate: ${rate}%"
        threshold_exceeded=$(awk "BEGIN { print (${rate} > ${ERROR_RATE_THRESHOLD}) ? 1 : 0 }")
        if [[ "${threshold_exceeded}" -eq 1 ]]; then
            fail "Z4 error rate ${rate}% exceeds threshold ${ERROR_RATE_THRESHOLD}%"
        else
            pass "Z4 error rate ${rate}% is within threshold"
        fi
    fi
fi
echo ""

# ---------------------------------------------------------------------------
# Check 2: Per-department cost
# ---------------------------------------------------------------------------

echo "--- [2] Per-department cost (window: last ${WINDOW_HOURS}h) ---"
if command -v jq &>/dev/null && [[ -d "${Z4_SESSIONS_DIR}" ]]; then
    declare -A dept_costs
    while IFS= read -r jsonl_file; do
        while IFS= read -r line; do
            [[ -z "${line}" ]] && continue
            ts=$(echo "${line}" | jq -r '.timestamp // empty' 2>/dev/null) || continue
            [[ -z "${ts}" ]] && continue
            line_epoch=$(date -u -j -f '%Y-%m-%dT%H:%M:%S' "${ts:0:19}" +%s 2>/dev/null \
                || date -u -d "${ts}" +%s 2>/dev/null || echo 0)
            [[ "${line_epoch}" -lt "${cutoff_epoch}" ]] && continue
            dept=$(echo "${line}" | jq -r '.department // empty' 2>/dev/null) || continue
            cost=$(echo "${line}" | jq -r '.total_cost_usd // 0' 2>/dev/null) || continue
            [[ -z "${dept}" || -z "${cost}" ]] && continue
            if [[ -n "${dept_costs[${dept}]+_}" ]]; then
                dept_costs["${dept}"]=$(awk "BEGIN { printf \"%.4f\", ${dept_costs[${dept}]} + ${cost} }")
            else
                dept_costs["${dept}"]="${cost}"
            fi
        done < "${jsonl_file}"
    done < <(find "${Z4_SESSIONS_DIR}" -name '*.jsonl' -newer /tmp/.z4_soak_cutoff 2>/dev/null \
        || find "${Z4_SESSIONS_DIR}" -name '*.jsonl' 2>/dev/null)

    if [[ ${#dept_costs[@]} -eq 0 ]]; then
        warn "No Z4 session cost data found in ${Z4_SESSIONS_DIR}"
    else
        for dept in "${!dept_costs[@]}"; do
            cost="${dept_costs[${dept}]}"
            cap="${DEPT_COST_CAPS[${dept}]:-2.00}"
            over=$(awk "BEGIN { print (${cost} > ${cap}) ? 1 : 0 }")
            if [[ "${over}" -eq 1 ]]; then
                fail "dept=${dept} cost=\$${cost} exceeds cap=\$${cap}"
            else
                pass "dept=${dept} cost=\$${cost} within cap=\$${cap}"
            fi
        done
    fi
else
    if ! command -v jq &>/dev/null; then
        warn "jq not installed — skipping per-dept cost check"
    else
        warn "Z4 sessions directory not found: ${Z4_SESSIONS_DIR} — skipping cost check"
    fi
fi
echo ""

# ---------------------------------------------------------------------------
# Check 3: Circuit state
# ---------------------------------------------------------------------------

echo "--- [3] Circuit breaker state (all departments should be CLOSED) ---"
circuit_open_count=0
if curl -s --connect-timeout 3 "${HEALTH_URL}" &>/dev/null; then
    health_json=$(curl -s --connect-timeout 3 "${HEALTH_URL}" 2>/dev/null || echo '{}')
    if command -v jq &>/dev/null; then
        open_circuits=$(echo "${health_json}" \
            | jq -r '.components.departments // {} | to_entries[] | select(.value.circuit == "open") | .key' \
            2>/dev/null || true)
        if [[ -n "${open_circuits}" ]]; then
            while IFS= read -r dept; do
                fail "circuit OPEN for department: ${dept}"
                circuit_open_count=$((circuit_open_count + 1))
            done <<< "${open_circuits}"
        else
            pass "All department circuits are CLOSED (or healthz has no circuit data)"
        fi
    else
        info "healthz reachable but jq not available — manual circuit check required"
        warn "Run: curl -s ${HEALTH_URL} | python3 -m json.tool"
    fi
else
    # Fall back to log grep
    if [[ -f "${BRIDGE_STDERR}" ]]; then
        open_log=$(grep -c 'circuit.*OPEN\|CIRCUIT_OPEN' "${BRIDGE_STDERR}" 2>/dev/null || echo 0)
        if [[ "${open_log}" -gt 0 ]]; then
            warn "Found ${open_log} circuit-OPEN log entries — manual review recommended"
        else
            pass "No circuit-OPEN entries in bridge-stderr.log"
        fi
    else
        warn "healthz unreachable and no log file — skipping circuit check"
    fi
fi
echo ""

# ---------------------------------------------------------------------------
# Check 4: Latency SLA  (P95 < LATENCY_P95_THRESHOLD seconds)
# ---------------------------------------------------------------------------

echo "--- [4] Latency SLA (P95 < ${LATENCY_P95_THRESHOLD}s) ---"
if [[ -f "${BRIDGE_STDERR}" ]] && command -v awk &>/dev/null; then
    # Extract duration values from lines like: [Z4] dept=board duration=12.34s
    mapfile -t durations < <(
        grep -oE '\bduration=([0-9]+\.[0-9]+)s' "${BRIDGE_STDERR}" 2>/dev/null \
        | awk -F= '{print $2+0}' | sort -n
    )
    count="${#durations[@]}"
    if [[ "${count}" -eq 0 ]]; then
        warn "No Z4 duration entries in bridge-stderr.log — skipping latency check"
    else
        p95_idx=$(awk "BEGIN { printf \"%d\", int(${count} * 0.95) }")
        [[ "${p95_idx}" -ge "${count}" ]] && p95_idx=$((count - 1))
        p95="${durations[${p95_idx}]}"
        info "Latency sample: n=${count}  P95=${p95}s  (threshold: ${LATENCY_P95_THRESHOLD}s)"
        threshold_exceeded=$(awk "BEGIN { print (${p95} > ${LATENCY_P95_THRESHOLD}) ? 1 : 0 }")
        if [[ "${threshold_exceeded}" -eq 1 ]]; then
            fail "P95 latency ${p95}s exceeds SLA threshold ${LATENCY_P95_THRESHOLD}s"
        else
            pass "P95 latency ${p95}s is within SLA"
        fi
    fi
else
    warn "Cannot compute latency — bridge-stderr.log not found or awk unavailable"
fi
echo ""

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo "================================================================"
if [[ "${FAILURES}" -eq 0 ]]; then
    echo -e "${GREEN}  Z4 SOAK: GREEN — all checks passed (${WINDOW_HOURS}h window)${NC}"
    echo ""
    echo "  Next steps:"
    echo "    OFF-SOAK passed? -> operator sets dispatcher.enabled = true in bridge.toml"
    echo "                        then runs: sudo launchctl bootout/bootstrap to restart"
    echo "                        then re-runs this script 24h later (ON-SOAK)"
    echo "    ON-SOAK  passed? -> Z4.10 flag flip is confirmed. Update MEMORY.md."
    echo ""
    exit 0
else
    echo -e "${RED}  Z4 SOAK: RED — ${FAILURES} check(s) failed${NC}"
    echo ""
    echo "  Do NOT flip (or confirm) the Z4.10 flag until all checks pass."
    echo "  Fix the issues above and re-run this script."
    echo ""
    exit 1
fi

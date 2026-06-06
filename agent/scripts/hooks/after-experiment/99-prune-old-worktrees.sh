#!/usr/bin/env bash
#
# 99-prune-old-worktrees.sh — example after-experiment hook.
#
# Real cleanup is operator-tunable; this placeholder just announces
# itself so operators see hooks firing end-to-end. The companion
# `bridge.worktree_gc` already prunes /private/tmp worktrees with
# mtime > 24h, so a fully-fledged pruner here is intentionally
# deferred until an operator decides to override that policy.
#
# Contract reminders:
#   - 30s wall-clock timeout
#   - 8 KB stdout cap
#   - non-zero exit is logged but does NOT crash the loop
#   - JSON object on stdout is parsed as steering directives
#
set -euo pipefail

# Drain stdin so a piping orchestrator never blocks on a closed reader.
cat >/dev/null 2>&1 || true

echo "prune-old-worktrees: placeholder (no action)"

#!/bin/bash
# Handoff readiness check — triggers on git push when design specs exist
# Runs as a PostToolUse hook on Bash commands containing "git push"

TOOL_INPUT="$1"

# Only trigger on git push commands
if ! echo "$TOOL_INPUT" | grep -q "git push"; then
  exit 0
fi

# Check if this repo has design-director specs
if [ ! -d ".design/bumba-design-director/product" ]; then
  exit 0
fi

# Check if handoff manifest exists and is current
HANDOFF_FILE="specs/HANDOFF.md"

if [ ! -f "$HANDOFF_FILE" ]; then
  echo '{"additionalContext": "⚠️ HANDOFF CHECK: This repo has design specs but NO handoff manifest (specs/HANDOFF.md). Before pushing, ask the user: \"This repo has design specs. Should I run /handoff-prepare to validate readiness before pushing?\" If they say yes, invoke the handoff-prepare skill. If they say no, proceed with the push."}'
  exit 0
fi

# Check if any spec files are newer than the handoff manifest
HANDOFF_MOD=$(stat -f %m "$HANDOFF_FILE" 2>/dev/null || echo 0)
STALE=false

find .design/bumba-design-director/product -name "*.md" -o -name "*.ts" -o -name "*.json" 2>/dev/null | while read specfile; do
  SPEC_MOD=$(stat -f %m "$specfile" 2>/dev/null || echo 0)
  if [ "$SPEC_MOD" -gt "$HANDOFF_MOD" ]; then
    echo "STALE"
    break
  fi
done | grep -q "STALE" && STALE=true

if [ "$STALE" = true ]; then
  echo '{"additionalContext": "⚠️ HANDOFF CHECK: specs/HANDOFF.md exists but is STALE — design specs have been modified since last handoff check. Ask the user: \"Design specs changed since last handoff check. Should I re-run /handoff-prepare before pushing?\" If yes, invoke the handoff-prepare skill. If no, proceed."}'
  exit 0
fi

# Handoff manifest exists and is current — all good
exit 0

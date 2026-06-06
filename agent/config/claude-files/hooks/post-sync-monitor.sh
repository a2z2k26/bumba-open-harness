#!/bin/bash
# Post Sync Monitor Hook
# Automatically triggers sync-cascade after sync-monitor detects changes

# This hook is triggered after the sync-monitor skill completes
# It reads the change data and invokes sync-cascade to update the codebase

set -e

# Configuration
CHANGE_DATA_FILE=".design/logs/last-sync-changes.json"
CASCADE_ENABLED=$(jq -r '.cascade.enabled // true' .design/config.json 2>/dev/null || echo "true")

# Check if cascade is enabled
if [ "$CASCADE_ENABLED" != "true" ]; then
  echo "Cascade disabled in config. Skipping automatic transformation."
  exit 0
fi

# Check if change data file exists
if [ ! -f "$CHANGE_DATA_FILE" ]; then
  echo "No changes detected. Skipping cascade."
  exit 0
fi

# Read change data
CHANGED_COMPONENTS=$(jq -r '.changedComponents[]?' "$CHANGE_DATA_FILE" 2>/dev/null || echo "")
NEW_COMPONENTS=$(jq -r '.newComponents[]?' "$CHANGE_DATA_FILE" 2>/dev/null || echo "")
CHANGED_TOKENS=$(jq -r '.changedTokens[]?' "$CHANGE_DATA_FILE" 2>/dev/null || echo "")

# Count changes
CHANGE_COUNT=$(echo "$CHANGED_COMPONENTS $NEW_COMPONENTS" | wc -w | tr -d ' ')

if [ "$CHANGE_COUNT" -eq 0 ]; then
  echo "No component changes to cascade."
  exit 0
fi

# Log cascade trigger
echo "Triggering sync-cascade for $CHANGE_COUNT component(s)..."
echo "Changed: $CHANGED_COMPONENTS"
echo "New: $NEW_COMPONENTS"

# Write trigger data for Claude to detect and invoke sync-cascade
mkdir -p .design/logs/triggers
cat > .design/logs/triggers/cascade-trigger.json <<EOF
{
  "skill": "design:sync-cascade",
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "changedComponents": $(jq '.changedComponents // []' "$CHANGE_DATA_FILE"),
  "newComponents": $(jq '.newComponents // []' "$CHANGE_DATA_FILE"),
  "changedTokens": $(jq '.changedTokens // []' "$CHANGE_DATA_FILE")
}
EOF

# Output message for Claude Code to detect and act on
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔄 DESIGN SYNC DETECTED"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Changes detected: $CHANGE_COUNT component(s)"
echo "Changed: $CHANGED_COMPONENTS"
echo "New: $NEW_COMPONENTS"
echo ""
echo "⚡ Action Required:"
echo "Run '/design:sync-cascade' to update components and Storybook"
echo ""
echo "Trigger data: .design/logs/triggers/cascade-trigger.json"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

exit 0

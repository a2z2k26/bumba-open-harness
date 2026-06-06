#!/bin/bash
#
# adapt-paths.sh
# Adapt all BUMBA paths from .bumba-design to .design
#
# Usage: ./adapt-paths.sh

echo "=== Design Bridge Path Adaptation ==="
echo "Updating all references from .bumba-design to .design"
echo ""

SERVER_DIR="/opt/bumba-harness/Bumba - DesignBridge/design-feature/packages/@design-bridge/server"
TRANSFORMERS_DIR="/opt/bumba-harness/Bumba - DesignBridge/design-feature/packages/@design-bridge/transformers"

# Counter for changes
TOTAL_FILES=0
TOTAL_CHANGES=0

echo "1. Updating Design Bridge Server files..."
cd "$SERVER_DIR"

for file in *.js; do
  if [ -f "$file" ]; then
    # Count occurrences before
    BEFORE=$(grep -c "\.bumba-design" "$file" 2>/dev/null || echo "0")

    if [ "$BEFORE" -gt 0 ]; then
      # Make the replacement
      sed -i '' 's/\.bumba-design/.design/g' "$file"

      # Count occurrences after (should be 0)
      AFTER=$(grep -c "\.bumba-design" "$file" 2>/dev/null || echo "0")

      CHANGES=$((BEFORE - AFTER))

      if [ "$CHANGES" -gt 0 ]; then
        echo "  ✓ $file: $CHANGES changes"
        TOTAL_FILES=$((TOTAL_FILES + 1))
        TOTAL_CHANGES=$((TOTAL_CHANGES + CHANGES))
      fi
    fi
  fi
done

echo ""
echo "2. Updating Framework Optimizers..."
cd "$TRANSFORMERS_DIR/optimizers"

for file in *.js; do
  if [ -f "$file" ]; then
    BEFORE=$(grep -c "\.bumba-design" "$file" 2>/dev/null || echo "0")

    if [ "$BEFORE" -gt 0 ]; then
      sed -i '' 's/\.bumba-design/.design/g' "$file"
      AFTER=$(grep -c "\.bumba-design" "$file" 2>/dev/null || echo "0")
      CHANGES=$((BEFORE - AFTER))

      if [ "$CHANGES" -gt 0 ]; then
        echo "  ✓ $file: $CHANGES changes"
        TOTAL_FILES=$((TOTAL_FILES + 1))
        TOTAL_CHANGES=$((TOTAL_CHANGES + CHANGES))
      fi
    fi
  fi
done

echo ""
echo "=== Path Adaptation Complete ==="
echo "Files updated: $TOTAL_FILES"
echo "Total changes: $TOTAL_CHANGES"
echo ""

# Verify no .bumba-design references remain
echo "Verification: Checking for remaining .bumba-design references..."
REMAINING=$(grep -r "\.bumba-design" "$SERVER_DIR" "$TRANSFORMERS_DIR" 2>/dev/null | wc -l)

if [ "$REMAINING" -eq 0 ]; then
  echo "✅ SUCCESS: All paths adapted to .design"
else
  echo "⚠️  WARNING: Found $REMAINING remaining .bumba-design references"
  echo "Run: grep -r '.bumba-design' packages/@design-bridge/"
fi

echo ""
echo "Done!"

#!/bin/bash
# Feature Usage Tracker
# Analyzes history.jsonl to show which features you actually use

HISTORY_FILE="$HOME/.claude/history.jsonl"
OUTPUT_DIR="$HOME/.claude/docs"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}Analyzing feature usage from history...${NC}\n"

if [ ! -f "$HISTORY_FILE" ]; then
    echo "Error: history.jsonl not found"
    exit 1
fi

# Extract slash commands used
echo -e "${GREEN}=== Most Used Commands ===${NC}"
grep -o '"/[a-z:-]*"' "$HISTORY_FILE" 2>/dev/null | \
    sort | uniq -c | sort -rn | head -20 | \
    awk '{print $1 "\t" $2}' | column -t

echo ""

# Extract agent mentions
echo -e "${GREEN}=== Most Used Agents ===${NC}"
grep -oE '"subagent_type":\s*"[^"]*"' "$HISTORY_FILE" 2>/dev/null | \
    cut -d'"' -f4 | sort | uniq -c | sort -rn | head -20 | \
    awk '{print $1 "\t" $2}' | column -t

echo ""

# Skill invocations
echo -e "${GREEN}=== Most Used Skills ===${NC}"
grep -oE '"skill":\s*"[^"]*"' "$HISTORY_FILE" 2>/dev/null | \
    cut -d'"' -f4 | sort | uniq -c | sort -rn | head -20 | \
    awk '{print $1 "\t" $2}' | column -t

echo ""

# Generate usage report
REPORT_FILE="$OUTPUT_DIR/feature-usage-report.md"
cat > "$REPORT_FILE" << 'EOF'
# Feature Usage Report

Generated from history analysis. Shows which features you actually use most frequently.

## Top Commands

EOF

grep -o '"/[a-z:-]*"' "$HISTORY_FILE" 2>/dev/null | \
    sort | uniq -c | sort -rn | head -20 | \
    awk '{print "- **" $2 "** - " $1 " uses"}' >> "$REPORT_FILE"

cat >> "$REPORT_FILE" << 'EOF'

## Top Agents

EOF

grep -oE '"subagent_type":\s*"[^"]*"' "$HISTORY_FILE" 2>/dev/null | \
    cut -d'"' -f4 | sort | uniq -c | sort -rn | head -20 | \
    awk '{print "- **" $2 "** - " $1 " invocations"}' >> "$REPORT_FILE"

cat >> "$REPORT_FILE" << 'EOF'

## Top Skills

EOF

grep -oE '"skill":\s*"[^"]*"' "$HISTORY_FILE" 2>/dev/null | \
    cut -d'"' -f4 | sort | uniq -c | sort -rn | head -20 | \
    awk '{print "- **" $2 "** - " $1 " invocations"}' >> "$REPORT_FILE"

cat >> "$REPORT_FILE" << 'EOF'

## Recommendations

Based on usage patterns:

### Frequently Used
Features you use often - make sure these are well-documented and optimized.

### Rarely Used
Features with low usage - consider:
- Are they still needed?
- Should they be archived?
- Do they need better documentation?

### Never Used
Features never appearing in history - candidates for archival or removal.

---

**Generated**: $(date)
**Analysis Period**: Full history
**Report Location**: `/opt/bumba-harness/.claude/docs/feature-usage-report.md`
EOF

echo -e "${YELLOW}Full report saved to: $REPORT_FILE${NC}"

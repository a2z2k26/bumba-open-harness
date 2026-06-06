#!/bin/bash
# Documentation Search Tool
# Search across all Claude Code documentation

DOCS_DIR="$HOME/.claude/docs"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

usage() {
    echo "Usage: search-docs.sh <search-term>"
    echo "Example: search-docs.sh 'design system'"
    echo ""
    echo "Searches across:"
    echo "  - All inventory documents"
    echo "  - Department quick references"
    echo "  - Framework documentation"
    exit 1
}

if [ $# -eq 0 ]; then
    usage
fi

SEARCH_TERM="$*"

echo -e "${BLUE}Searching documentation for: ${YELLOW}'$SEARCH_TERM'${NC}\n"

# Search inventories
echo -e "${GREEN}=== Feature Inventories ===${NC}"
grep -rn -i --color=always "$SEARCH_TERM" "$DOCS_DIR"/inventory-*.md 2>/dev/null | head -20

echo ""

# Search department docs
echo -e "${GREEN}=== Department Quick References ===${NC}"
grep -rn -i --color=always "$SEARCH_TERM" "$DOCS_DIR"/dept-*.md 2>/dev/null | head -20

echo ""

# Search frameworks
echo -e "${GREEN}=== Framework Documentation ===${NC}"
grep -rn -i --color=always "$SEARCH_TERM" "$DOCS_DIR"/*-framework.md 2>/dev/null | head -20

echo ""

# Count total matches
TOTAL=$(grep -ri "$SEARCH_TERM" "$DOCS_DIR"/*.md 2>/dev/null | wc -l)
echo -e "${BLUE}Total matches: $TOTAL${NC}"
echo ""
echo "Tip: Use 'search-docs.sh <term> | less' to page through all results"

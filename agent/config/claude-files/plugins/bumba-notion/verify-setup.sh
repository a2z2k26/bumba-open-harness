#!/bin/bash
#
# verify-setup.sh - Verify bumba-notion plugin installation and configuration
#
# Usage: ./verify-setup.sh
#

echo "=================================================="
echo "  Bumba Notion Plugin - Setup Verification"
echo "=================================================="
echo ""

SUCCESS=0
WARNINGS=0
ERRORS=0

# Helper functions
check_pass() {
    echo "[PASS] $1"
    ((SUCCESS++))
}

check_warn() {
    echo "[WARN] $1"
    ((WARNINGS++))
}

check_fail() {
    echo "[FAIL] $1"
    ((ERRORS++))
}

# 1. Check plugin directory structure
echo "1. Checking plugin directory structure..."
echo ""

if [ -d "$HOME/.claude/plugins/bumba-notion" ]; then
    check_pass "Plugin directory exists"
else
    check_fail "Plugin directory not found at ~/.claude/plugins/bumba-notion"
fi

if [ -f "$HOME/.claude/plugins/bumba-notion/plugin.json" ]; then
    check_pass "plugin.json exists"
else
    check_fail "plugin.json not found"
fi

if [ -d "$HOME/.claude/plugins/bumba-notion/config" ]; then
    check_pass "config/ directory exists"
else
    check_fail "config/ directory not found"
fi

if [ -d "$HOME/.claude/plugins/bumba-notion/docs" ]; then
    check_pass "docs/ directory exists"
else
    check_warn "docs/ directory not found (optional)"
fi

echo ""

# 2. Check configuration files
echo "2. Checking configuration files..."
echo ""

if [ -f "$HOME/.claude/plugins/bumba-notion/config/schema-definitions.json" ]; then
    check_pass "schema-definitions.json exists"

    # Validate JSON
    if command -v jq &> /dev/null; then
        if jq empty "$HOME/.claude/plugins/bumba-notion/config/schema-definitions.json" 2>/dev/null; then
            check_pass "schema-definitions.json is valid JSON"
        else
            check_fail "schema-definitions.json has invalid JSON syntax"
        fi
    else
        check_warn "jq not installed, skipping JSON validation"
    fi
else
    check_fail "schema-definitions.json not found"
fi

if [ -f "$HOME/.claude/plugins/bumba-notion/config/sync-rules.json" ]; then
    check_pass "sync-rules.json exists"
else
    check_fail "sync-rules.json not found"
fi

if [ -f "$HOME/.claude/plugins/bumba-notion/config/workspace-mapping.json" ]; then
    check_pass "workspace-mapping.json exists"

    # Validate structure
    if command -v jq &> /dev/null; then
        if jq -e '.notionToken and .masterDatabases and .templatePageId' "$HOME/.claude/plugins/bumba-notion/config/workspace-mapping.json" &> /dev/null; then
            check_pass "workspace-mapping.json has required fields"
        else
            check_fail "workspace-mapping.json missing required fields (notionToken, masterDatabases, templatePageId)"
        fi
    fi
else
    check_fail "workspace-mapping.json not found - Phase 0 setup required"
fi

echo ""

# 3. Check hook integration
echo "3. Checking hook integration..."
echo ""

if [ -f "$HOME/.claude/hooks/on-project-init-complete.js" ]; then
    check_pass "on-project-init-complete.js hook exists"

    # Check if hook is enabled
    if grep -q "enabled: true" "$HOME/.claude/hooks/on-project-init-complete.js"; then
        check_pass "Hook is enabled"
    else
        check_fail "Hook is not enabled"
    fi

    # Check if Notion integration exists
    if grep -q "createNotionDashboard" "$HOME/.claude/hooks/on-project-init-complete.js"; then
        check_pass "Notion integration code present in hook"
    else
        check_fail "Notion integration code not found in hook"
    fi
else
    check_fail "on-project-init-complete.js hook not found"
fi

if [ -f "$HOME/.claude/commands/project/init.md" ]; then
    check_pass "project-init command exists"

    # Check if Notion Dashboard option is present
    if grep -q "Notion Dashboard" "$HOME/.claude/commands/project/init.md"; then
        check_pass "Notion Dashboard option present in command"
    else
        check_fail "Notion Dashboard option not found in command"
    fi
else
    check_fail "project-init command not found"
fi

echo ""

# 4. Check Notion API access
echo "4. Testing Notion API access..."
echo ""

if [ -f "$HOME/.claude/plugins/bumba-notion/config/workspace-mapping.json" ]; then
    if command -v jq &> /dev/null && command -v curl &> /dev/null; then
        NOTION_TOKEN=$(jq -r '.notionToken' "$HOME/.claude/plugins/bumba-notion/config/workspace-mapping.json")

        if [ "$NOTION_TOKEN" != "null" ] && [ -n "$NOTION_TOKEN" ]; then
            echo "   Testing API token..."

            # Test API call
            API_RESPONSE=$(curl -s -X GET https://api.notion.com/v1/users/me \
                -H "Authorization: Bearer $NOTION_TOKEN" \
                -H "Notion-Version: 2022-06-28")

            if echo "$API_RESPONSE" | jq -e '.object == "user"' &> /dev/null; then
                check_pass "Notion API token is valid"
                USER_NAME=$(echo "$API_RESPONSE" | jq -r '.name // "Unknown"')
                echo "   Connected as: $USER_NAME"
            else
                check_fail "Notion API token is invalid or expired"
                ERROR_MSG=$(echo "$API_RESPONSE" | jq -r '.message // "Unknown error"')
                echo "   Error: $ERROR_MSG"
            fi
        else
            check_warn "Notion token not configured"
        fi
    else
        check_warn "jq or curl not available, skipping API test"
    fi
else
    check_warn "workspace-mapping.json not found, skipping API test"
fi

echo ""

# 5. Check documentation
echo "5. Checking documentation..."
echo ""

DOCS=(
    "QUICK-START.md"
    "PROJECT-INIT-INTEGRATION.md"
    "TROUBLESHOOTING.md"
    "HUMAN-SETUP-GUIDE.md"
)

for doc in "${DOCS[@]}"; do
    if [ -f "$HOME/.claude/plugins/bumba-notion/docs/$doc" ]; then
        check_pass "$doc exists"
    else
        check_warn "$doc not found (optional)"
    fi
done

echo ""

# 6. Summary
echo "=================================================="
echo "  Verification Summary"
echo "=================================================="
echo ""
echo "Passed:   $SUCCESS"
echo "Warnings: $WARNINGS"
echo "Failed:   $ERRORS"
echo ""

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo "SUCCESS: All checks passed! Plugin is ready to use."
    echo ""
    echo "Next steps:"
    echo "  1. Run: /project-init"
    echo "  2. Enable: Notion Dashboard feature"
    echo "  3. See: docs/QUICK-START.md for examples"
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo "SUCCESS: Plugin is functional with minor warnings."
    echo ""
    echo "Recommendations:"
    echo "  - Review warnings above"
    echo "  - Install jq for better validation: brew install jq"
    echo "  - Check documentation for optional features"
    exit 0
else
    echo "FAILURE: Plugin has errors that need to be fixed."
    echo ""
    echo "Action required:"
    echo "  1. Review errors above"
    echo "  2. See: docs/HUMAN-SETUP-GUIDE.md for Phase 0 setup"
    echo "  3. See: docs/TROUBLESHOOTING.md for solutions"
    exit 1
fi

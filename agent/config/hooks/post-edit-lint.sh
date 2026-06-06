#!/bin/bash
# PostToolUse hook: Auto-lint after file edits.
input=$(cat)
FILE=$(echo "$input" | jq -r '.tool_input.file_path // .tool_input.path // ""' 2>/dev/null)
if [ -z "$FILE" ] || [ ! -f "$FILE" ]; then exit 0; fi
EXTENSION="${FILE##*.}"
case "$EXTENSION" in
    py)
        if command -v ruff &> /dev/null; then
            ruff check "$FILE" --fix --quiet 2>/dev/null
            ruff format "$FILE" --quiet 2>/dev/null
        fi ;;
    ts|tsx|js|jsx)
        if command -v eslint &> /dev/null; then eslint --fix "$FILE" --quiet 2>/dev/null; fi
        if command -v prettier &> /dev/null; then prettier --write "$FILE" --log-level error 2>/dev/null; fi ;;
    go)
        if command -v gofmt &> /dev/null; then gofmt -w "$FILE" 2>/dev/null; fi ;;
esac

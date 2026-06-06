#!/bin/bash
# PostToolUse hook: Auto-typecheck after file edits. Warning mode.
input=$(cat)
FILE=$(echo "$input" | jq -r '.tool_input.file_path // .tool_input.path // ""' 2>/dev/null)
if [ -z "$FILE" ] || [ ! -f "$FILE" ]; then exit 0; fi
EXTENSION="${FILE##*.}"
case "$EXTENSION" in
    py)
        if command -v mypy &> /dev/null; then mypy "$FILE" --no-error-summary --no-color 2>/dev/null || true; fi ;;
    go)
        DIR=$(dirname "$FILE")
        if command -v go &> /dev/null; then go vet "$DIR/..." 2>/dev/null || true; fi ;;
esac

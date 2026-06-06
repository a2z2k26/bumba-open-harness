# Hook Registration

Register in `.claude/settings.local.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      {"matcher": "Edit|Write", "command": "bash agent/config/hooks/post-edit-lint.sh"},
      {"matcher": "Edit|Write", "command": "bash agent/config/hooks/post-edit-typecheck.sh"}
    ]
  }
}
```

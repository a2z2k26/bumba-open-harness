#!/bin/bash
# Refresh Claude Code OAuth token for bumba-agent
# Runs as bumba (admin) via LaunchAgent every 4 hours
# Extracts token from bumba-agent's Keychain and updates .secrets file
set -euo pipefail

SECRETS="/opt/bumba-harness/data/.secrets"
LOG="/opt/bumba-harness/logs/token-refresh.log"

log() {
    echo "$(date -Iseconds) $1" >> "$LOG" 2>/dev/null || true
}

# Extract credentials from bumba-agent's Keychain
# (admin user has sudo access to read bumba-agent's Keychain)
CRED_JSON=$(sudo -u bumba-agent security find-generic-password \
    -s "Claude Code-credentials" -a "bumba-agent" -w \
    /opt/bumba-harness/Library/Keychains/login.keychain-db 2>/dev/null) || true

if [ -z "$CRED_JSON" ]; then
    log "ERROR: Could not extract credentials from Keychain"
    exit 1
fi

# Extract accessToken
ACCESS_TOKEN=$(echo "$CRED_JSON" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data['claudeAiOauth']['accessToken'])
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(1)
" 2>/dev/null) || true

if [ -z "$ACCESS_TOKEN" ] || [[ "$ACCESS_TOKEN" == ERROR* ]]; then
    log "ERROR: Could not parse accessToken from credentials"
    exit 1
fi

# Read current token from secrets file
CURRENT_TOKEN=""
if [ -f "$SECRETS" ]; then
    CURRENT_TOKEN=$(grep "^claude_oauth_token=" "$SECRETS" 2>/dev/null | cut -d= -f2- || true)
fi

# Only update if token has changed
if [ "$ACCESS_TOKEN" = "$CURRENT_TOKEN" ]; then
    log "OK: Token unchanged (${#ACCESS_TOKEN} chars)"
    exit 0
fi

# Update .secrets file using python (avoids temp file permission issues)
python3 -c "
import pathlib
secrets_path = pathlib.Path('$SECRETS')
token = '''$ACCESS_TOKEN'''
lines = []
if secrets_path.exists():
    for line in secrets_path.read_text().splitlines():
        if not line.startswith('claude_oauth_token='):
            lines.append(line)
lines.append(f'claude_oauth_token={token}')
secrets_path.write_text('\n'.join(lines) + '\n')
"

log "REFRESHED: Token updated (${#ACCESS_TOKEN} chars)"

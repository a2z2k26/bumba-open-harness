#!/usr/bin/env bash
# Idempotent setup of bumba-agent's git config for narrow-permission experiment-loop pushes.
# Run as: sudo bash scripts/setup_bumba_agent_git.sh <github-pat>
#
# Sprint ref-audit-02-11 / issue #986. See:
#   docs/architecture/experiment-loop-narrow-permissions.md
#
# This script:
#   1. Writes /opt/bumba-harness/.gitconfig (mode 0600, owned by bumba-agent)
#   2. Writes /opt/bumba-harness/.git-credentials (mode 0600, owned by bumba-agent)
#
# It does NOT issue the PAT — operator must do that at github.com/settings/personal-access-tokens
# It does NOT bootstrap the launchd plist — operator does that after verifying the setup.

set -euo pipefail

if [ "$EUID" -ne 0 ]; then
    echo "ERROR: must run as root (sudo)"
    exit 1
fi

PAT="${1:-}"
if [ -z "$PAT" ]; then
    echo "Usage: sudo bash scripts/setup_bumba_agent_git.sh <github-pat>"
    exit 1
fi

BUMBA_AGENT_HOME="/opt/bumba-harness"
[ -d "$BUMBA_AGENT_HOME" ] || { echo "ERROR: $BUMBA_AGENT_HOME does not exist"; exit 1; }

# 1. .gitconfig — narrow identity, store helper, per-host useHttpPath so the
#    PAT only matches GitHub HTTPS URLs.
cat > "$BUMBA_AGENT_HOME/.gitconfig" <<'EOF'
[user]
    name = Bumba Agent (Experiment Loop)
    email = bumba-agent@local
[credential]
    helper = store
[credential "https://github.com"]
    useHttpPath = true
EOF
chown bumba-agent:staff "$BUMBA_AGENT_HOME/.gitconfig"
chmod 0600 "$BUMBA_AGENT_HOME/.gitconfig"

# 2. .git-credentials — single-line PAT for github.com only.
cat > "$BUMBA_AGENT_HOME/.git-credentials" <<EOF
https://bumba-agent:${PAT}@github.com
EOF
chown bumba-agent:staff "$BUMBA_AGENT_HOME/.git-credentials"
chmod 0600 "$BUMBA_AGENT_HOME/.git-credentials"

echo "OK — gitconfig and git-credentials written + secured"
echo ""
echo "Next steps (operator):"
echo "  Positive test (should succeed):"
echo "    sudo -u bumba-agent git -C $BUMBA_AGENT_HOME/agent ls-remote origin"
echo ""
echo "  Negative test (should fail with PAT scope error):"
echo "    sudo -u bumba-agent git -C $BUMBA_AGENT_HOME/agent push origin HEAD:refs/heads/main"
echo ""
echo "  Once both verify, bootstrap the experiment plist:"
echo "    sudo launchctl bootstrap system /Library/LaunchDaemons/com.bumba.agent-experiment.plist"

#!/bin/bash
# Wrapper for launchd to find python3 dynamically
PYTHON3=$(which python3 2>/dev/null || ls /opt/homebrew/bin/python3 2>/dev/null || ls /usr/bin/python3 2>/dev/null || ls /usr/local/bin/python3 2>/dev/null)

if [[ -z "$PYTHON3" ]]; then
    echo "ERROR: python3 not found in PATH or common locations" >&2
    exit 1
fi

cd "$HOME/.claude/status" || exit 1
exec "$PYTHON3" "$HOME/.claude/status/server.py"

#!/bin/bash
# claude-status server launcher (uses .venv/bin/python if present, else system python3)

STATUS_DIR="$HOME/.claude/status"
VENV_PY="$STATUS_DIR/.venv/bin/python"

if [[ -x "$VENV_PY" ]]; then
    PYTHON="$VENV_PY"
else
    PYTHON=$(which python3 2>/dev/null || ls /opt/homebrew/bin/python3 2>/dev/null || ls /usr/bin/python3 2>/dev/null || ls /usr/local/bin/python3 2>/dev/null)
fi

if [[ -z "$PYTHON" ]]; then
    echo "ERROR: python3 not found" >&2
    exit 1
fi

cd "$STATUS_DIR" || exit 1
exec "$PYTHON" "$STATUS_DIR/server.py"

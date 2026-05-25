#!/bin/bash
# claude-status update hook V1.4 — sticky needConfirm with 2-minute timeout
#
# Usage: echo '<hook-json>' | update.sh <state>
#   state: idle / thinking / working / needConfirm / done
#
# Sticky needConfirm rule (V1.4):
#   While a session is in needConfirm:
#     - UserPromptSubmit (the user actually replying) clears it.
#     - Other hooks within 2 minutes of the last needConfirm trigger get
#       coerced back to needConfirm (prevents PostToolUse from instantly
#       overwriting it the moment AskUserQuestion returns).
#     - After 2 minutes with no fresh needConfirm trigger, sticky is released
#       so a stale "awaiting input" session can naturally be cleaned up.

ORIG_STATE="$1"
STATE="${1:-idle}"
STATUS_FILE="$HOME/.claude/status/current.json"
LOCK_DIR="$HOME/.claude/status/.lock"
JQ=/usr/bin/jq
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Read hook JSON from stdin
HOOK_INPUT=""
if ! [ -t 0 ]; then
    HOOK_INPUT=$(cat)
fi

SESSION_ID=$(echo "$HOOK_INPUT" | $JQ -r '.session_id // "default"' 2>/dev/null || echo "default")
CWD=$(echo "$HOOK_INPUT" | $JQ -r '.cwd // ""' 2>/dev/null || echo "")
HOOK_EVENT=$(echo "$HOOK_INPUT" | $JQ -r '.hook_event_name // ""' 2>/dev/null || echo "")
if [[ -n "$CWD" ]]; then
    PROJECT=$(basename "$CWD")
else
    PROJECT="unknown"
fi

# Atomic mkdir lock
WAITED=0
while ! mkdir "$LOCK_DIR" 2>/dev/null; do
    sleep 0.1
    WAITED=$((WAITED + 1))
    if [[ $WAITED -gt 50 ]]; then
        echo "lock timeout, session=$SESSION_ID state=$STATE" >&2
        exit 1
    fi
done
trap "rmdir '$LOCK_DIR' 2>/dev/null" EXIT

# Read existing state file
if [[ -f "$STATUS_FILE" ]]; then
    CURRENT=$(cat "$STATUS_FILE")
else
    CURRENT='{"global_state":"idle","sessions":[],"updated_at":""}'
fi

# V1.4 sticky needConfirm with 2-minute timeout
# Find this session's current state + needConfirm_ts (last time a needConfirm hook fired)
CURRENT_STATE=$(echo "$CURRENT" | $JQ -r --arg sid "$SESSION_ID" '.sessions[]? | select(.id == $sid) | .state' 2>/dev/null || echo "")
CURRENT_NC_TS=$(echo "$CURRENT" | $JQ -r --arg sid "$SESSION_ID" '.sessions[]? | select(.id == $sid) | .needConfirm_ts // ""' 2>/dev/null || echo "")

# needConfirm 2-minute timeout cutoff
NC_CUTOFF=$(date -u -v-2M +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u +"%Y-%m-%dT%H:%M:%SZ")

# Sticky: currently needConfirm + new state isn't needConfirm + hook isn't UserPromptSubmit
# + needConfirm is within the 2-minute window → coerce back to needConfirm
if [[ "$CURRENT_STATE" == "needConfirm" ]] \
   && [[ "$STATE" != "needConfirm" ]] \
   && [[ "$HOOK_EVENT" != "UserPromptSubmit" ]] \
   && [[ -n "$CURRENT_NC_TS" ]] \
   && [[ "$CURRENT_NC_TS" > "$NC_CUTOFF" ]]; then
    STATE="needConfirm"
fi

# Compute new needConfirm_ts: refresh only when the original hook actually wrote
# needConfirm; otherwise carry the old ts forward (sticky must not refresh it)
if [[ "$ORIG_STATE" == "needConfirm" ]]; then
    NEW_NC_TS="$TIMESTAMP"
else
    NEW_NC_TS="$CURRENT_NC_TS"
fi

# 5-minute cleanup cutoff for stale sessions
CUTOFF=$(date -u -v-5M +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u +"%Y-%m-%dT%H:%M:%SZ")

# Update sessions array: remove this session's old entry, cleanup 5-min-old entries, append new
UPDATED=$(echo "$CURRENT" | $JQ \
    --arg sid "$SESSION_ID" \
    --arg state "$STATE" \
    --arg ts "$TIMESTAMP" \
    --arg proj "$PROJECT" \
    --arg cutoff "$CUTOFF" \
    --arg nc_ts "$NEW_NC_TS" \
    '.sessions = (.sessions // [] | map(select(.id != $sid)) | map(select(.updated_at >= $cutoff)))
     | .sessions += [{"id": $sid, "state": $state, "project": $proj, "updated_at": $ts, "needConfirm_ts": $nc_ts}]')

# Compute global_state (highest-priority state across all sessions)
PRIORITY=$(echo "$UPDATED" | $JQ -r '
    .sessions | map(.state) |
    if contains(["needConfirm"]) then "needConfirm"
    elif contains(["working"]) then "working"
    elif contains(["thinking"]) then "thinking"
    elif contains(["done"]) then "done"
    else "idle"
    end')

FINAL=$(echo "$UPDATED" | $JQ --arg gs "$PRIORITY" --arg ts "$TIMESTAMP" '.global_state = $gs | .updated_at = $ts')
echo "$FINAL" > "$STATUS_FILE"

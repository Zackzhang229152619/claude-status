#!/bin/bash
# claude-status update hook V1.3 — per-session state with priority merge + sticky needConfirm
#
# Usage: echo '<hook-json>' | update.sh <state>
#   state: idle / thinking / working / needConfirm / done
#
# Sticky needConfirm rule (V1.3):
#   When the current session is in needConfirm, only a UserPromptSubmit hook
#   (i.e. the user actually replying) can clear it. Other hooks
#   (PostToolUse / Stop / etc.) that try to write thinking / working / done
#   are coerced back to needConfirm, so the "awaiting input" overlay stays
#   visible until the user replies.

STATE="${1:-idle}"
STATUS_FILE="$HOME/.claude/status/current.json"
LOCK_DIR="$HOME/.claude/status/.lock"
JQ=/usr/bin/jq
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# 从 stdin 读 hook JSON
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
    PROJECT="未知"
fi

# mkdir 原子锁
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

# 读现有状态文件
if [[ -f "$STATUS_FILE" ]]; then
    CURRENT=$(cat "$STATUS_FILE")
else
    CURRENT='{"global_state":"idle","sessions":[],"updated_at":""}'
fi

# V1.3 sticky needConfirm logic
# Find this session's current state
CURRENT_STATE=$(echo "$CURRENT" | $JQ -r --arg sid "$SESSION_ID" '.sessions[]? | select(.id == $sid) | .state' 2>/dev/null || echo "")

# If currently needConfirm:
#   - Only UserPromptSubmit (user reply) can clear it (let STATE through)
#   - Re-asserting needConfirm is also fine
#   - All other hooks that try to overwrite get coerced back to needConfirm
if [[ "$CURRENT_STATE" == "needConfirm" ]] \
   && [[ "$STATE" != "needConfirm" ]] \
   && [[ "$HOOK_EVENT" != "UserPromptSubmit" ]]; then
    STATE="needConfirm"
fi

# 5 分钟前的时间戳
CUTOFF=$(date -u -v-5M +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u +"%Y-%m-%dT%H:%M:%SZ")

# 更新 sessions 数组：移除该 session 旧条目 + 清理 5 分钟前的 + 添加新条目
UPDATED=$(echo "$CURRENT" | $JQ \
    --arg sid "$SESSION_ID" \
    --arg state "$STATE" \
    --arg ts "$TIMESTAMP" \
    --arg proj "$PROJECT" \
    --arg cutoff "$CUTOFF" \
    '.sessions = (.sessions // [] | map(select(.id != $sid)) | map(select(.updated_at >= $cutoff)))
     | .sessions += [{"id": $sid, "state": $state, "project": $proj, "updated_at": $ts}]')

# 算 global_state（优先级最高的状态）
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

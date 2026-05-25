#!/usr/bin/env python3
"""
claude-status server V2.0

Custom HTTP routes:
  GET /                     -> dashboard.html
  GET /dashboard.html       -> dashboard.html
  GET /current.json         -> served from disk, written by update.sh
  GET /sessions_detail.json -> parses recent session transcripts on the fly
  GET /token_stats.json     -> aggregates token usage (today / month / all-time)
  *                         -> 404
"""

import json
import os
import glob
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

try:
    from pywebpush import webpush, WebPushException  # optional, enables push
    PUSH_AVAILABLE = True
except ImportError:
    PUSH_AVAILABLE = False
    webpush = None
    WebPushException = Exception

BASE_DIR = os.path.expanduser("~/.claude/status")
PROJECTS_DIR = os.path.expanduser("~/.claude/projects")
CURRENT_JSON = os.path.join(BASE_DIR, "current.json")
DASHBOARD_HTML = os.path.join(BASE_DIR, "dashboard.html")

# Cache so we don't re-read disk on every poll
_cache = {"data": None, "at": 0}
CACHE_TTL = 1.0  # seconds

# Token stats cache: 5s TTL
_token_cache = {"data": None, "at": 0}
TOKEN_CACHE_TTL = 5.0  # seconds


def empty_token_bucket() -> dict:
    """Return an empty token-stats bucket."""
    return {
        "input": 0,
        "output": 0,
        "cache_creation": 0,
        "cache_read": 0,
        "by_model": {},
    }


def add_usage_to_bucket(bucket: dict, usage: dict, model: str):
    """Accumulate one usage record into the bucket (overall + per-model)."""
    bucket["input"]          += usage.get("input_tokens", 0)
    bucket["output"]         += usage.get("output_tokens", 0)
    bucket["cache_creation"] += usage.get("cache_creation_input_tokens", 0)
    bucket["cache_read"]     += usage.get("cache_read_input_tokens", 0)

    if model:
        if model not in bucket["by_model"]:
            bucket["by_model"][model] = {"input": 0, "output": 0, "cache_creation": 0, "cache_read": 0}
        m = bucket["by_model"][model]
        m["input"]          += usage.get("input_tokens", 0)
        m["output"]         += usage.get("output_tokens", 0)
        m["cache_creation"] += usage.get("cache_creation_input_tokens", 0)
        m["cache_read"]     += usage.get("cache_read_input_tokens", 0)


def calculate_token_stats() -> dict:
    """Walk all transcript .jsonl files and aggregate token usage into today / month / all-time buckets."""
    now_utc = datetime.now(timezone.utc)
    today_prefix = now_utc.strftime("%Y-%m-%d")
    month_prefix = now_utc.strftime("%Y-%m")

    total = empty_token_bucket()
    today = empty_token_bucket()
    month = empty_token_bucket()

    pattern = os.path.join(PROJECTS_DIR, "*", "*.jsonl")
    files = glob.glob(pattern)

    for filepath in files:
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        d = json.loads(raw)
                    except Exception:
                        continue

                    if d.get("type") != "assistant":
                        continue

                    msg = d.get("message", {})
                    usage = msg.get("usage")
                    if not usage:
                        continue

                    model = msg.get("model", "unknown")
                    ts = d.get("timestamp", "")

                    add_usage_to_bucket(total, usage, model)

                    if ts.startswith(month_prefix):
                        add_usage_to_bucket(month, usage, model)

                    if ts.startswith(today_prefix):
                        add_usage_to_bucket(today, usage, model)

        except Exception:
            continue

    return {
        "today": today,
        "month": month,
        "total": total,
        "last_updated": now_utc.isoformat(),
    }


def get_token_stats_cached() -> bytes:
    """Token stats with 5-second cache."""
    now = time.time()
    if _token_cache["data"] is None or now - _token_cache["at"] > TOKEN_CACHE_TTL:
        data = calculate_token_stats()
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        _token_cache["data"] = body
        _token_cache["at"] = now
    return _token_cache["data"]


def find_transcript(session_id: str) -> str | None:
    """Find a transcript .jsonl file by session_id across all project dirs."""
    pattern = os.path.join(PROJECTS_DIR, "*", session_id + ".jsonl")
    matches = glob.glob(pattern)
    return matches[0] if matches else None


def read_last_n_lines(path: str, n: int = 100) -> list[str]:
    """Read the last N lines of a file without loading the whole thing."""
    try:
        with open(path, "rb") as f:
            # Read in chunks from the tail
            chunk_size = 8192
            f.seek(0, 2)
            file_size = f.tell()
            buf = b""
            pos = file_size
            while pos > 0 and buf.count(b"\n") < n + 1:
                read_size = min(chunk_size, pos)
                pos -= read_size
                f.seek(pos)
                buf = f.read(read_size) + buf
            lines = buf.decode("utf-8", errors="replace").splitlines()
            return lines[-n:] if len(lines) > n else lines
    except Exception:
        return []


def parse_transcript(session_id: str) -> dict:
    """Parse a transcript and return current_tool / current_target / last_prompt."""
    result = {
        "current_tool": None,
        "current_target": None,
        "last_prompt": None,
    }

    path = find_transcript(session_id)
    if not path:
        return result

    lines = read_last_n_lines(path, 150)

    found_tool = False
    found_prompt = False

    # Walk in reverse
    for raw in reversed(lines):
        raw = raw.strip()
        if not raw:
            continue
        try:
            d = json.loads(raw)
        except Exception:
            continue

        t = d.get("type", "")

        # Prefer the last-prompt event over reverse-scanning user messages (more reliable)
        if not found_prompt and t == "last-prompt":
            text = d.get("lastPrompt", "") or ""
            result["last_prompt"] = text[:80] if text else None
            found_prompt = True

        # Find the last tool_use
        if not found_tool and t == "assistant":
            msg = d.get("message", {})
            content = msg.get("content", [])
            if isinstance(content, list):
                for c in reversed(content):
                    if c.get("type") == "tool_use":
                        name = c.get("name", "")
                        inp = c.get("input", {})
                        result["current_tool"] = name
                        # Extract target path
                        if name in ("Edit", "Read", "Write", "MultiEdit", "NotebookEdit"):
                            fp = inp.get("file_path", "") or inp.get("notebook_path", "")
                            result["current_target"] = os.path.basename(fp) if fp else None
                        elif name == "Bash":
                            cmd = str(inp.get("command", ""))
                            result["current_target"] = cmd[:60] if cmd else None
                        else:
                            result["current_target"] = name
                        found_tool = True
                        break

        if found_tool and found_prompt:
            break

    return result


def build_sessions_detail() -> list:
"""Read sessions from current.json and parse each transcript."""
    try:
        with open(CURRENT_JSON) as f:
            cur = json.load(f)
    except Exception:
        return []

    sessions = cur.get("sessions", [])
    result = []
    for s in sessions:
        sid = s.get("id", "")
        detail = parse_transcript(sid)
        result.append({
            "id": sid,
            "id_short": sid[:8],
            "state": s.get("state", "idle"),
            "project": s.get("project", None),
            "updated_at": s.get("updated_at", None),
            "current_tool": detail["current_tool"],
            "current_target": detail["current_target"],
            "last_prompt": detail["last_prompt"],
        })
    return result


def get_sessions_detail_cached() -> bytes:
    """sessions_detail with 1-second cache."""
    now = time.time()
    if _cache["data"] is None or now - _cache["at"] > CACHE_TTL:
        data = build_sessions_detail()
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        _cache["data"] = body
        _cache["at"] = now
    return _cache["data"]


class StatusHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def log_message(self, fmt, *args):
        # Silence regular access logs; keep errors
        pass

    def do_GET(self):
        path = self.path.split("?")[0]  # strip query string

        # Deny sensitive files (private keys / subs / logs / backups / venv)
        if any(part in path for part in ("vapid_private.pem", "vapid_keys.json",
                                         "subscriptions.json", "server.log",
                                         "/backups/", "/.venv/", "/.lock")):
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"403 Forbidden")
            return

        if path == "/":
            self.send_response(302)
            self.send_header("Location", "/dashboard.html")
            self.end_headers()
            return

        if path in ("/dashboard.html",):
            self._serve_file(DASHBOARD_HTML, "text/html; charset=utf-8")
        elif path == "/current.json":
            self._serve_file(CURRENT_JSON, "application/json; charset=utf-8")
        elif path == "/sessions_detail.json":
            self._serve_dynamic_json(get_sessions_detail_cached())
        elif path == "/token_stats.json":
            self._serve_dynamic_json(get_token_stats_cached())
        elif path == "/vapid-public-key":
            self._serve_dynamic_json(
                json.dumps({"publicKey": get_vapid_public_key()}).encode()
            )
        else:
            # Fallback: let SimpleHTTPRequestHandler serve any static file under BASE_DIR
            return super().do_GET()

    def do_POST(self):
        path = self.path.split("?")[0]

        if path == "/push/subscribe":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode("utf-8")
                sub = json.loads(body)
                if not (isinstance(sub, dict) and sub.get("endpoint") and sub.get("keys")):
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b'{"ok":false,"error":"invalid subscription"}')
                    return
                add_subscription(sub)
                self._serve_dynamic_json(b'{"ok":true}')
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(f'{{"ok":false,"error":"{e}"}}'.encode())
        elif path == "/push/test":
            count = send_push_to_all({
                "title": "Claude Status — test",
                "body": "If you see this, push works.",
                "tag": "claude-test",
            })
            self._serve_dynamic_json(json.dumps({"ok": True, "delivered": count}).encode())
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"404 Not Found")

    def _serve_file(self, filepath: str, content_type: str):
        try:
            with open(filepath, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"404 File Not Found")
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode())

    def _serve_dynamic_json(self, body: bytes):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)


# ============================================================
# Web Push (optional — PWA notifications)
# ============================================================
VAPID_KEYS_FILE = os.path.join(BASE_DIR, "vapid_keys.json")
VAPID_PRIVATE_PEM = os.path.join(BASE_DIR, "vapid_private.pem")
SUBSCRIPTIONS_FILE = os.path.join(BASE_DIR, "subscriptions.json")
VAPID_CLAIMS_SUB = "mailto:noreply@example.com"


def get_vapid_public_key() -> str:
    """Return VAPID public key as base64url string (clients use this to subscribe)."""
    try:
        with open(VAPID_KEYS_FILE) as f:
            return json.load(f).get("public_b64url", "")
    except FileNotFoundError:
        return ""


def load_subscriptions() -> list:
    try:
        with open(SUBSCRIPTIONS_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return []
    except Exception:
        return []


_subs_lock = threading.Lock()


def save_subscriptions(subs: list):
    with _subs_lock:
        with open(SUBSCRIPTIONS_FILE, "w") as f:
            json.dump(subs, f, indent=2)


def add_subscription(sub: dict):
    """Add a new subscription, de-duplicating by endpoint."""
    subs = load_subscriptions()
    endpoint = sub.get("endpoint")
    subs = [s for s in subs if s.get("endpoint") != endpoint]
    subs.append(sub)
    save_subscriptions(subs)


def send_push_to_all(payload: dict) -> int:
    """Send a Web Push notification to every stored subscription. Returns delivered count."""
    if not PUSH_AVAILABLE:
        print("[push] pywebpush not installed; skipping", file=sys.stderr, flush=True)
        return 0
    try:
        with open(VAPID_PRIVATE_PEM) as f:
            vapid_priv_pem = f.read()
    except FileNotFoundError:
        print("[push] vapid_private.pem missing", file=sys.stderr, flush=True)
        return 0

    subs = load_subscriptions()
    if not subs:
        return 0
    body = json.dumps(payload, ensure_ascii=False)

    survivors = []
    delivered = 0
    for sub in subs:
        try:
            webpush(
                subscription_info=sub,
                data=body,
                vapid_private_key=vapid_priv_pem,
                vapid_claims={"sub": VAPID_CLAIMS_SUB},
                ttl=300,
            )
            survivors.append(sub)
            delivered += 1
        except WebPushException as e:
            # 410 Gone / 404 = subscription dead, drop it
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (404, 410):
                continue
            survivors.append(sub)  # transient error — keep for retry
        except Exception as e:
            print(f"[push] send error: {e}", file=sys.stderr, flush=True)
            survivors.append(sub)

    if len(survivors) != len(subs):
        save_subscriptions(survivors)
    return delivered


# Track which sessions we've already pushed about to avoid spamming the same alert
_last_needConfirm_sessions: set = set()


def push_watcher_loop():
    """Background thread: poll current.json, fire push when a session newly enters needConfirm."""
    global _last_needConfirm_sessions
    while True:
        try:
            time.sleep(1.0)
            try:
                with open(CURRENT_JSON) as f:
                    cur = json.load(f)
            except FileNotFoundError:
                continue

            now_needConfirm = set()
            new_alerts = []
            for s in cur.get("sessions", []):
                if s.get("state") == "needConfirm":
                    sid = s.get("id", "")
                    now_needConfirm.add(sid)
                    if sid and sid not in _last_needConfirm_sessions:
                        new_alerts.append(s)

            _last_needConfirm_sessions = now_needConfirm

            for s in new_alerts:
                proj = s.get("project", "unknown")
                sid_short = s.get("id", "")[:8]
                send_push_to_all({
                    "title": "Claude — awaiting input",
                    "body": f"{proj} · session {sid_short}",
                    "tag": f"claude-needConfirm-{s.get('id', '')}",
                    "requireInteraction": True,
                    "url": "./",
                })
        except Exception as e:
            print(f"[push-watcher] error: {e}", file=sys.stderr, flush=True)


def start_push_watcher():
    if not PUSH_AVAILABLE:
        print("[push-watcher] disabled: pywebpush not installed", file=sys.stderr, flush=True)
        return
    if not os.path.exists(VAPID_KEYS_FILE):
        print("[push-watcher] disabled: vapid_keys.json not found "
              "(run scripts/generate-vapid.sh)", file=sys.stderr, flush=True)
        return
    t = threading.Thread(target=push_watcher_loop, daemon=True, name="push-watcher")
    t.start()
    print("[push-watcher] thread started", flush=True)


def main():
    start_push_watcher()
    server = ThreadingHTTPServer(("0.0.0.0", 8765), StatusHandler)
    print(f"claude-status server V2.1 listening on 0.0.0.0:8765 "
          f"(push={'on' if PUSH_AVAILABLE else 'off'})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

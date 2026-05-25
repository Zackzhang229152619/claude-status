#!/usr/bin/env python3
"""
Claude Status Server V2.0
自定义 HTTP 路由：
  GET /                     -> dashboard.html
  GET /dashboard.html       -> dashboard.html
  GET /current.json         -> current.json (静态)
  GET /sessions_detail.json -> 动态解析 transcript，返回中集数据
  GET /token_stats.json     -> 动态统计 token 用量（今日/本月/累计）
  其他                      -> 404
"""

import json
import os
import glob
import time
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.expanduser("~/.claude/status")
PROJECTS_DIR = os.path.expanduser("~/.claude/projects")
CURRENT_JSON = os.path.join(BASE_DIR, "current.json")
DASHBOARD_HTML = os.path.join(BASE_DIR, "dashboard.html")

# 缓存：避免每秒读文件 N 次
_cache = {"data": None, "at": 0}
CACHE_TTL = 1.0  # 秒

# token 统计缓存：5 秒 TTL
_token_cache = {"data": None, "at": 0}
TOKEN_CACHE_TTL = 5.0  # 秒


def empty_token_bucket() -> dict:
    """返回一个空的 token 统计桶"""
    return {
        "input": 0,
        "output": 0,
        "cache_creation": 0,
        "cache_read": 0,
        "by_model": {},
    }


def add_usage_to_bucket(bucket: dict, usage: dict, model: str):
    """把一条 usage 加到统计桶里"""
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
    """
    遍历所有 transcript .jsonl，统计 token 用量。
    分类：今日 / 本月 / 总累计。
    """
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
    """带 5 秒缓存的 token 统计"""
    now = time.time()
    if _token_cache["data"] is None or now - _token_cache["at"] > TOKEN_CACHE_TTL:
        data = calculate_token_stats()
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        _token_cache["data"] = body
        _token_cache["at"] = now
    return _token_cache["data"]


def find_transcript(session_id: str) -> str | None:
    """根据 session_id 在所有 project 目录里找 .jsonl 文件"""
    pattern = os.path.join(PROJECTS_DIR, "*", session_id + ".jsonl")
    matches = glob.glob(pattern)
    return matches[0] if matches else None


def read_last_n_lines(path: str, n: int = 100) -> list[str]:
    """读文件最后 n 行，避免全量加载大文件"""
    try:
        with open(path, "rb") as f:
            # 从尾部读 chunk
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
    """解析 transcript，返回中集数据"""
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

    # 反向遍历
    for raw in reversed(lines):
        raw = raw.strip()
        if not raw:
            continue
        try:
            d = json.loads(raw)
        except Exception:
            continue

        t = d.get("type", "")

        # 找最后一个 last-prompt 事件（比反向遍历 user 消息更准）
        if not found_prompt and t == "last-prompt":
            text = d.get("lastPrompt", "") or ""
            result["last_prompt"] = text[:80] if text else None
            found_prompt = True

        # 找最后一个 tool_use
        if not found_tool and t == "assistant":
            msg = d.get("message", {})
            content = msg.get("content", [])
            if isinstance(content, list):
                for c in reversed(content):
                    if c.get("type") == "tool_use":
                        name = c.get("name", "")
                        inp = c.get("input", {})
                        result["current_tool"] = name
                        # 取目标路径
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
    """读 current.json 里的 sessions，逐个解析 transcript"""
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
    """带 1 秒缓存的 sessions_detail"""
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
        # 静默常规日志，只记录错误
        pass

    def do_GET(self):
        path = self.path.split("?")[0]  # 去掉查询参数

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
        else:
            # fallback：交给 SimpleHTTPRequestHandler serve BASE_DIR 下任意静态文件
            return super().do_GET()

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


def main():
    server = ThreadingHTTPServer(("0.0.0.0", 8765), StatusHandler)
    print(f"Claude Status Server V2.0 listening on 0.0.0.0:8765", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

"""Small, dependency-free bridge between a Dify Chatflow and PowerContext."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


POWERCONTEXT_URL = os.environ.get("POWERCONTEXT_URL", "http://127.0.0.1:8000").rstrip("/")
POWERCONTEXT_TOKEN = os.environ.get("POWERCONTEXT_TOKEN", "")
GAME_GATEWAY_TOKEN = os.environ.get("GAME_GATEWAY_TOKEN", "")
GAME_BIND = os.environ.get("GAME_BIND", "127.0.0.1")
GAME_PORT = int(os.environ.get("GAME_PORT", "8765"))
PLAYER_RE = re.compile(r"^[A-Za-z0-9_-]{3,48}$")


def powercontext_post(path: str, payload: dict) -> dict:
    headers = {"Content-Type": "application/json"}
    if POWERCONTEXT_TOKEN:
        headers["Authorization"] = f"Bearer {POWERCONTEXT_TOKEN}"
    request = Request(
        f"{POWERCONTEXT_URL}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=12) as response:
            return json.load(response)
    except HTTPError as error:
        raise RuntimeError(f"PowerContext {path}: HTTP {error.code}") from error
    except (URLError, TimeoutError) as error:
        raise RuntimeError(f"PowerContext {path}: unavailable") from error


def player_scope(player_id: str) -> str:
    digest = hashlib.sha256(f"night-shop-v1:{player_id}".encode()).hexdigest()[:32]
    result = powercontext_post(
        "/v1/scopes",
        {
            "title": f"Night shop player {digest}",
            "summary": "Memory for one Night Shop demo player",
            "idempotency_key": f"night-shop-v1-{digest}",
        },
    )
    return result["scope_id"]


def classify_event(message: str) -> str | None:
    normalized = re.sub(r"\s+", "", message)
    if "红伞" in normalized and any(word in normalized for word in ("归还", "还伞", "还你", "还给")):
        return "玩家把红伞归还给便利店老板。"
    if "红伞" in normalized and any(word in normalized for word in ("借", "拿走", "带走")):
        return "玩家从便利店借走红伞，约定下次归还。"
    return None


def play_turn(player_id: str, message: str) -> dict:
    if not PLAYER_RE.fullmatch(player_id):
        raise ValueError("player_id must be 3-48 ASCII letters, digits, _ or -")
    if not message.strip() or len(message) > 1000:
        raise ValueError("message must contain 1-1000 characters")
    scope_id = player_scope(player_id)
    event = classify_event(message)
    saved_refs = []
    if event:
        saved = powercontext_post(
            "/v1/memory/remember",
            {"scope_id": scope_id, "kind": "decision", "text": event, "reason": "Player action in Night Shop"},
        )
        saved_refs = saved.get("records", [])
    prepared = powercontext_post(
        "/v1/context/prepare",
        {"scope_id": scope_id, "query": "便利店 红伞 借走 归还", "max_bytes": 4000},
    )
    return {
        "player_id": player_id,
        "memory_status": prepared.get("status", "unknown"),
        "memory": prepared.get("content") or "",
        "event": event or "",
        "saved_records": saved_refs,
        "scene": "雨夜便利店；老板叫阿墨，店内只有一把红伞。",
    }


class Handler(BaseHTTPRequestHandler):
    def reply(self, status: int, data: dict) -> None:
        content = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        if self.path == "/health":
            self.reply(200, {"status": "live"})
        else:
            self.reply(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/v1/turn":
            self.reply(404, {"error": "not found"})
            return
        token = self.headers.get("X-Game-Token", "")
        if not GAME_GATEWAY_TOKEN or not hmac.compare_digest(token, GAME_GATEWAY_TOKEN):
            self.reply(401, {"error": "unauthorized"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size < 1 or size > 8192:
                raise ValueError("invalid body size")
            request = json.loads(self.rfile.read(size))
            if not isinstance(request, dict):
                raise ValueError("body must be a JSON object")
            player_id, message = request.get("player_id"), request.get("message")
            if not isinstance(player_id, str) or not isinstance(message, str):
                raise ValueError("player_id and message must be strings")
            self.reply(200, play_turn(player_id, message))
        except (ValueError, json.JSONDecodeError) as error:
            self.reply(400, {"error": str(error)})
        except RuntimeError as error:
            self.reply(502, {"error": str(error)})


if __name__ == "__main__":
    if not GAME_GATEWAY_TOKEN:
        raise SystemExit("Set GAME_GATEWAY_TOKEN before starting the gateway")
    server = ThreadingHTTPServer((GAME_BIND, GAME_PORT), Handler)
    print(f"Night Shop gateway listening on {GAME_BIND}:{GAME_PORT}", flush=True)
    server.serve_forever()

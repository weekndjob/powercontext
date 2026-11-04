"""Integration check against a running gateway and PowerContext server."""

import json
import os
import secrets
from urllib.request import Request, urlopen


base = os.environ.get("GAME_GATEWAY_URL", "http://127.0.0.1:8765").rstrip("/")
token = os.environ["GAME_GATEWAY_TOKEN"]
player = "guest_" + secrets.token_hex(5)


def turn(player_id: str, message: str) -> dict:
    request = Request(
        base + "/v1/turn",
        data=json.dumps({"player_id": player_id, "message": message}, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json", "X-Game-Token": token},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        return json.load(response)


first = turn(player, "老板，我想借走红伞")
assert first["event"] and first["saved_records"], first
print("borrow:", first["memory_status"], first["event"])

second = turn(player, "老板，我又来了")
assert not second["event"] and "红伞" in second["memory"], second
print("new conversation:", second["memory_status"], second["memory"][:200])

other = turn(player + "_other", "老板，我又来了")
assert "借走红伞" not in other["memory"], other
print("other player:", other["memory_status"])

returned = turn(player, "我来归还红伞")
assert returned["event"] and returned["saved_records"], returned
print("return:", returned["memory_status"], returned["event"])
print("PASS: PowerContext write, recall, isolation and return")

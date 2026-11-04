"""Gateway HTTP behavior with a small in-memory PowerContext contract stub."""

import json
import os
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

os.environ["GAME_GATEWAY_TOKEN"] = "test-only-token"
import game_gateway as game  # noqa: E402


class GatewayTest(unittest.TestCase):
    def setUp(self):
        self.memories = {}

        def fake_powercontext(path, payload):
            if path == "/v1/scopes":
                return {"scope_id": payload["idempotency_key"]}
            scope = payload["scope_id"]
            if path == "/v1/memory/remember":
                self.memories.setdefault(scope, []).append(payload["text"])
                return {"records": [{"artifact_id": str(len(self.memories[scope]))}]}
            if path == "/v1/context/prepare":
                items = self.memories.get(scope, [])
                return {"status": "ready" if items else "empty", "content": "\n".join(items) if items else None}
            raise AssertionError(path)

        self.mock = patch.object(game, "powercontext_post", side_effect=fake_powercontext)
        self.mock.start()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), game.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.mock.stop()

    def turn(self, player, message, token="test-only-token"):
        request = Request(
            f"http://127.0.0.1:{self.server.server_port}/v1/turn",
            data=json.dumps({"player_id": player, "message": message}, ensure_ascii=False).encode(),
            headers={"Content-Type": "application/json", "X-Game-Token": token},
            method="POST",
        )
        with urlopen(request, timeout=3) as response:
            return json.load(response)

    def test_cross_session_recall_and_isolation(self):
        first = self.turn("player_001", "老板，我想借走红伞")
        self.assertTrue(first["saved_records"])
        recalled = self.turn("player_001", "老板，我又来了")
        self.assertEqual(recalled["memory_status"], "ready")
        self.assertIn("红伞", recalled["memory"])
        self.assertEqual(recalled["event"], "")
        other = self.turn("player_002", "老板，我又来了")
        self.assertEqual(other["memory_status"], "empty")

    def test_auth_and_invalid_player(self):
        with self.assertRaises(HTTPError) as error:
            self.turn("player_001", "你好", token="wrong")
        self.assertEqual(error.exception.code, 401)
        error.exception.close()
        with self.assertRaises(HTTPError) as error:
            self.turn("not a valid player", "你好")
        self.assertEqual(error.exception.code, 400)
        error.exception.close()


if __name__ == "__main__":
    unittest.main()

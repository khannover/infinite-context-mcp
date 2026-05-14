from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib import parse, request

from infinite_context_mcp.config import Settings
from infinite_context_mcp.server import create_server


class ServerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings = Settings(
            host="127.0.0.1",
            port=0,
            data_path=str(Path(self.temp_dir.name) / "contexts.json"),
            signing_key="test-signing-key",
            token_ttl_seconds=3600,
            clients={
                "grok": {
                    "secret": "grok-secret",
                    "agent_id": "grok",
                    "scopes": ["contexts.read", "contexts.write"],
                },
                "copilot": {
                    "secret": "copilot-secret",
                    "agent_id": "copilot",
                    "scopes": ["contexts.read", "contexts.write"],
                },
            },
        )
        self.server = create_server(self.settings)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        time.sleep(0.05)

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)
        self.temp_dir.cleanup()

    def token_for(self, client_id: str, client_secret: str) -> str:
        encoded = parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            }
        ).encode("utf-8")
        req = request.Request(
            f"{self.base_url}/oauth/token",
            data=encoded,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with request.urlopen(req) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload["access_token"]

    def mcp_call(self, token: str, method: str, params: dict[str, object] | None = None) -> dict[str, object]:
        req = request.Request(
            f"{self.base_url}/mcp",
            data=json.dumps(
                {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
            ).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with request.urlopen(req) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_private_contexts_are_isolated_by_agent(self) -> None:
        grok_token = self.token_for("grok", "grok-secret")
        copilot_token = self.token_for("copilot", "copilot-secret")

        self.mcp_call(
            grok_token,
            "tools/call",
            {
                "name": "context_upsert",
                "arguments": {
                    "space": "planning",
                    "key": "draft",
                    "value": {"topic": "release"},
                },
            },
        )

        grok_private = self.mcp_call(
            grok_token,
            "tools/call",
            {"name": "context_get", "arguments": {"space": "planning", "key": "draft"}},
        )
        self.assertEqual(
            grok_private["result"]["structuredContent"]["value"]["topic"], "release"
        )

        copilot_private = self.mcp_call(
            copilot_token,
            "tools/call",
            {"name": "context_get", "arguments": {"space": "planning", "key": "draft"}},
        )
        self.assertTrue(copilot_private["result"]["isError"])

    def test_contexts_can_be_promoted_to_shared_space(self) -> None:
        grok_token = self.token_for("grok", "grok-secret")
        copilot_token = self.token_for("copilot", "copilot-secret")

        self.mcp_call(
            grok_token,
            "tools/call",
            {
                "name": "context_upsert",
                "arguments": {
                    "space": "handoff",
                    "key": "summary",
                    "value": {"status": "ready"},
                },
            },
        )
        self.mcp_call(
            grok_token,
            "tools/call",
            {
                "name": "context_change_visibility",
                "arguments": {
                    "space": "handoff",
                    "key": "summary",
                    "from_visibility": "private",
                    "to_visibility": "shared",
                },
            },
        )

        grok_private = self.mcp_call(
            grok_token,
            "tools/call",
            {
                "name": "context_get",
                "arguments": {
                    "space": "handoff",
                    "key": "summary",
                    "visibility": "private",
                },
            },
        )
        self.assertTrue(grok_private["result"]["isError"])

        shared = self.mcp_call(
            copilot_token,
            "tools/call",
            {
                "name": "context_get",
                "arguments": {
                    "space": "handoff",
                    "key": "summary",
                    "visibility": "shared",
                },
            },
        )
        self.assertEqual(shared["result"]["structuredContent"]["value"]["status"], "ready")

    def test_grok_connector_and_mcp_metadata_are_exposed(self) -> None:
        with request.urlopen(f"{self.base_url}/.well-known/oauth-authorization-server") as response:
            oauth_metadata = json.loads(response.read().decode("utf-8"))
        self.assertEqual(
            oauth_metadata["token_endpoint"], f"{self.base_url}/oauth/token"
        )

        with request.urlopen(f"{self.base_url}/connectors/grok") as response:
            grok_connector = json.loads(response.read().decode("utf-8"))
        self.assertEqual(grok_connector["auth"]["token_url"], f"{self.base_url}/oauth/token")

        token = self.token_for("grok", "grok-secret")
        tools = self.mcp_call(token, "tools/list")
        tool_names = {tool["name"] for tool in tools["result"]["tools"]}
        self.assertIn("context_change_visibility", tool_names)


if __name__ == "__main__":
    unittest.main()

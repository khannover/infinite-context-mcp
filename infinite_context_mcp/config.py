from __future__ import annotations

import json
import os
from dataclasses import dataclass


DEFAULT_CLIENTS = {
    "grok": {
        "secret": "grok-secret",
        "agent_id": "grok",
        "scopes": ["contexts.read", "contexts.write"],
    }
}


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    data_path: str
    signing_key: str
    token_ttl_seconds: int
    clients: dict[str, dict[str, object]]
    grok_public_client_enabled: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        raw_clients = os.environ.get("MCP_CLIENTS")
        clients = DEFAULT_CLIENTS
        if raw_clients:
            clients = json.loads(raw_clients)
        return cls(
            host=os.environ.get("HOST", "127.0.0.1"),
            port=int(os.environ.get("PORT", "8080")),
            data_path=os.environ.get("DATA_PATH", "data/contexts.json"),
            signing_key=os.environ.get("OAUTH_SIGNING_KEY", "local-dev-signing-key"),
            token_ttl_seconds=int(os.environ.get("TOKEN_TTL_SECONDS", "3600")),
            clients=clients,
            grok_public_client_enabled=os.environ.get(
                "GROK_PUBLIC_CLIENT_ENABLED", ""
            ).lower()
            in {"1", "true", "yes", "on"},
        )

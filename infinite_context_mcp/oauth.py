from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(raw: str) -> bytes:
    padding = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw + padding)


def issue_token(payload: dict[str, object], secret: str) -> str:
    body = _b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    signature = _b64encode(
        hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    )
    return f"{body}.{signature}"


def build_access_token(
    *,
    client_id: str,
    agent_id: str,
    scopes: list[str],
    ttl_seconds: int,
    secret: str,
) -> str:
    now = int(time.time())
    return issue_token(
        {
            "client_id": client_id,
            "sub": agent_id,
            "scope": " ".join(scopes),
            "iat": now,
            "exp": now + ttl_seconds,
        },
        secret,
    )


def verify_token(token: str, secret: str) -> dict[str, object]:
    body, signature = token.split(".", 1)
    expected = _b64encode(
        hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(expected, signature):
        raise ValueError("Invalid token signature")
    payload = json.loads(_b64decode(body).decode("utf-8"))
    if int(payload["exp"]) < int(time.time()):
        raise ValueError("Token expired")
    return payload

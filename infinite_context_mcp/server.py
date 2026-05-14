from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .config import Settings
from .oauth import build_access_token, verify_token
from .storage import ContextStore


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: object) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, object]:
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length) if length else b"{}"
    return json.loads(raw.decode("utf-8") or "{}")


def _request_base_url(handler: BaseHTTPRequestHandler) -> str:
    proto = handler.headers.get("X-Forwarded-Proto", "http")
    host = handler.headers.get("Host", f"{handler.server.server_name}:{handler.server.server_port}")
    return f"{proto}://{host}"


def _server_capabilities(base_url: str) -> dict[str, object]:
    return {
        "name": "infinite-context-mcp",
        "version": "0.1.0",
        "transport": "streamable-http",
        "mcp_endpoint": f"{base_url}/mcp",
        "oauth_metadata": f"{base_url}/.well-known/oauth-authorization-server",
    }


def _tool_definitions() -> list[dict[str, object]]:
    return [
        {
            "name": "context_list",
            "description": "List all private contexts for the calling AI plus every shared context.",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "context_get",
            "description": "Read a context entry from a private or shared space.",
            "inputSchema": {
                "type": "object",
                "required": ["space", "key"],
                "properties": {
                    "space": {"type": "string"},
                    "key": {"type": "string"},
                    "visibility": {"type": "string", "enum": ["private", "shared"]},
                },
            },
        },
        {
            "name": "context_upsert",
            "description": "Create or update a context entry in a private or shared space.",
            "inputSchema": {
                "type": "object",
                "required": ["space", "key", "value"],
                "properties": {
                    "space": {"type": "string"},
                    "key": {"type": "string"},
                    "value": {},
                    "visibility": {"type": "string", "enum": ["private", "shared"]},
                },
            },
        },
        {
            "name": "context_change_visibility",
            "description": "Move or copy a context entry between the calling AI's private space and shared spaces.",
            "inputSchema": {
                "type": "object",
                "required": ["space", "key", "from_visibility", "to_visibility"],
                "properties": {
                    "space": {"type": "string"},
                    "target_space": {"type": "string"},
                    "key": {"type": "string"},
                    "from_visibility": {"type": "string", "enum": ["private", "shared"]},
                    "to_visibility": {"type": "string", "enum": ["private", "shared"]},
                    "remove_source": {"type": "boolean"},
                },
            },
        },
    ]


def _tool_result(result: object) -> dict[str, object]:
    return {
        "content": [{"type": "text", "text": json.dumps(result)}],
        "structuredContent": result,
        "isError": False,
    }


def _tool_error(message: str) -> dict[str, object]:
    return {
        "content": [{"type": "text", "text": message}],
        "isError": True,
    }


def create_handler(settings: Settings, store: ContextStore):
    class InfiniteContextHandler(BaseHTTPRequestHandler):
        server_version = "InfiniteContextMCP/0.1.0"

        def do_GET(self) -> None:  # noqa: N802
            base_url = _request_base_url(self)
            if self.path == "/health":
                _json_response(self, HTTPStatus.OK, {"status": "ok"})
                return
            if self.path == "/.well-known/oauth-authorization-server":
                _json_response(
                    self,
                    HTTPStatus.OK,
                    {
                        "issuer": base_url,
                        "token_endpoint": f"{base_url}/oauth/token",
                        "grant_types_supported": ["client_credentials"],
                        "response_types_supported": ["token"],
                        "token_endpoint_auth_methods_supported": ["client_secret_post"],
                        "scopes_supported": ["contexts.read", "contexts.write"],
                    },
                )
                return
            if self.path == "/connectors/grok":
                _json_response(
                    self,
                    HTTPStatus.OK,
                    {
                        "name": "grok",
                        "type": "custom",
                        "auth": {
                            "grant_type": "client_credentials",
                            "token_url": f"{base_url}/oauth/token",
                        },
                        "mcp": _server_capabilities(base_url),
                    },
                )
                return
            if self.path == "/":
                _json_response(
                    self,
                    HTTPStatus.OK,
                    {
                        "service": "infinite-context-mcp",
                        "description": "OAuth2-protected MCP context service with private and shared spaces.",
                        "connectors": {"grok": f"{base_url}/connectors/grok"},
                        "mcp": _server_capabilities(base_url),
                    },
                )
                return
            _json_response(self, HTTPStatus.NOT_FOUND, {"error": "Not found"})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/oauth/token":
                self._handle_token()
                return
            if parsed.path == "/mcp":
                self._handle_mcp()
                return
            _json_response(self, HTTPStatus.NOT_FOUND, {"error": "Not found"})

        def _handle_token(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8")
            payload = parse_qs(raw)
            client_id = payload.get("client_id", [""])[0]
            client_secret = payload.get("client_secret", [""])[0]
            grant_type = payload.get("grant_type", [""])[0]
            if grant_type != "client_credentials":
                _json_response(
                    self,
                    HTTPStatus.BAD_REQUEST,
                    {"error": "unsupported_grant_type"},
                )
                return
            client = settings.clients.get(client_id)
            if not client or client.get("secret") != client_secret:
                _json_response(
                    self,
                    HTTPStatus.UNAUTHORIZED,
                    {"error": "invalid_client"},
                )
                return
            token = build_access_token(
                client_id=client_id,
                agent_id=str(client.get("agent_id", client_id)),
                scopes=list(client.get("scopes", ["contexts.read", "contexts.write"])),
                ttl_seconds=settings.token_ttl_seconds,
                secret=settings.signing_key,
            )
            _json_response(
                self,
                HTTPStatus.OK,
                {
                    "access_token": token,
                    "token_type": "Bearer",
                    "expires_in": settings.token_ttl_seconds,
                    "scope": " ".join(client.get("scopes", ["contexts.read", "contexts.write"])),
                },
            )

        def _handle_mcp(self) -> None:
            auth = self.headers.get("Authorization", "")
            if not auth.startswith("Bearer "):
                _json_response(
                    self,
                    HTTPStatus.UNAUTHORIZED,
                    {"error": "missing_bearer_token"},
                )
                return
            try:
                token_payload = verify_token(auth.split(" ", 1)[1], settings.signing_key)
            except (ValueError, KeyError):
                _json_response(
                    self,
                    HTTPStatus.UNAUTHORIZED,
                    {"error": "invalid_token"},
                )
                return
            request = _read_json(self)
            response = {
                "jsonrpc": "2.0",
                "id": request.get("id"),
            }
            try:
                response["result"] = self._dispatch_mcp(
                    method=str(request["method"]),
                    params=request.get("params") or {},
                    agent_id=str(token_payload["sub"]),
                )
            except KeyError as error:
                response["error"] = {"code": -32602, "message": str(error)}
            except ValueError as error:
                response["error"] = {"code": -32600, "message": str(error)}
            _json_response(self, HTTPStatus.OK, response)

        def _dispatch_mcp(
            self, *, method: str, params: dict[str, object], agent_id: str
        ) -> dict[str, object] | list[dict[str, object]]:
            if method == "initialize":
                base_url = _request_base_url(self)
                return {
                    "protocolVersion": "2025-03-26",
                    "serverInfo": {
                        "name": "infinite-context-mcp",
                        "version": "0.1.0",
                    },
                    "capabilities": {"tools": {}},
                    "instructions": (
                        "Use context_upsert for private/shared writes, context_get for reads, "
                        "and context_change_visibility when a user asks to share or privatize context."
                    ),
                    "transport": _server_capabilities(base_url),
                }
            if method == "tools/list":
                return {"tools": _tool_definitions()}
            if method != "tools/call":
                raise ValueError(f"Unsupported MCP method '{method}'")
            tool_name = str(params["name"])
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                raise ValueError("Tool arguments must be an object")
            if tool_name == "context_list":
                return _tool_result(store.list_accessible(agent_id=agent_id))
            if tool_name == "context_get":
                space = str(arguments["space"])
                key = str(arguments["key"])
                requested_visibility = arguments.get("visibility")
                visibilities = [str(requested_visibility)] if requested_visibility else ["private", "shared"]
                for visibility in visibilities:
                    result = store.get(
                        agent_id=agent_id,
                        visibility=visibility,
                        space=space,
                        key=key,
                    )
                    if result is not None:
                        return _tool_result(result)
                return _tool_error(f"Context '{key}' was not found in space '{space}'")
            if tool_name == "context_upsert":
                result = store.upsert(
                    agent_id=agent_id,
                    visibility=str(arguments.get("visibility", "private")),
                    space=str(arguments["space"]),
                    key=str(arguments["key"]),
                    value=arguments["value"],
                )
                return _tool_result(result)
            if tool_name == "context_change_visibility":
                result = store.change_visibility(
                    agent_id=agent_id,
                    from_visibility=str(arguments["from_visibility"]),
                    to_visibility=str(arguments["to_visibility"]),
                    space=str(arguments["space"]),
                    target_space=str(arguments.get("target_space", arguments["space"])),
                    key=str(arguments["key"]),
                    remove_source=bool(arguments.get("remove_source", True)),
                )
                return _tool_result(result)
            raise ValueError(f"Unknown tool '{tool_name}'")

        def log_message(self, format: str, *args: object) -> None:
            return

    return InfiniteContextHandler


def create_server(settings: Settings | None = None) -> ThreadingHTTPServer:
    app_settings = settings or Settings.from_env()
    store = ContextStore(app_settings.data_path)
    handler = create_handler(app_settings, store)
    return ThreadingHTTPServer((app_settings.host, app_settings.port), handler)


def main() -> None:
    server = create_server()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

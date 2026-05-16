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


def _html_response(handler: BaseHTTPRequestHandler, status: int, body: str) -> None:
    raw = body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


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


UI_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Infinite Context Manager</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f7fb;
      --card: #ffffff;
      --text: #1f2937;
      --muted: #607086;
      --line: #d7dce5;
      --brand: #2563eb;
      --brand-soft: #dbeafe;
      --danger: #b42318;
      --danger-soft: #fee4e2;
      --ok: #067647;
      --ok-soft: #d1fadf;
      --shadow: 0 10px 30px rgba(15, 23, 42, 0.08);
      --radius: 14px;
    }

    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
      background: radial-gradient(circle at top right, #e0ecff, var(--bg) 35%);
      color: var(--text);
      line-height: 1.45;
    }

    .page {
      max-width: 1200px;
      margin: 2rem auto 3rem;
      padding: 0 1rem;
    }

    .hero {
      background: linear-gradient(135deg, #1d4ed8, #2563eb 55%, #1e40af);
      color: #fff;
      border-radius: var(--radius);
      padding: 1.3rem 1.4rem;
      box-shadow: var(--shadow);
      margin-bottom: 1rem;
    }
    .hero h1 { margin: 0 0 0.35rem; font-size: 1.6rem; }
    .hero p { margin: 0; opacity: 0.95; }

    .hint {
      background: #eef4ff;
      border: 1px solid #c7dbff;
      color: #123768;
      border-radius: 12px;
      padding: 0.8rem 0.9rem;
      margin-top: 0.9rem;
      font-size: 0.95rem;
    }

    .layout {
      display: grid;
      grid-template-columns: minmax(300px, 1fr) minmax(380px, 1.4fr);
      gap: 1rem;
      align-items: start;
    }

    .card {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      padding: 1rem;
    }

    h2 {
      margin: 0 0 0.25rem;
      font-size: 1.2rem;
    }

    .subtitle {
      margin: 0 0 0.9rem;
      color: var(--muted);
      font-size: 0.92rem;
    }

    .row {
      display: flex;
      gap: 0.7rem;
      flex-wrap: wrap;
      margin-bottom: 0.75rem;
    }

    label {
      display: grid;
      gap: 0.3rem;
      color: var(--muted);
      font-weight: 600;
      font-size: 0.85rem;
      min-width: 120px;
      flex: 1;
    }

    input, select, textarea, button {
      font: inherit;
      border-radius: 10px;
      border: 1px solid var(--line);
      padding: 0.55rem 0.6rem;
      background: #fff;
      color: var(--text);
    }

    input:focus, select:focus, textarea:focus {
      outline: 2px solid #bfd6ff;
      border-color: #82adff;
    }

    textarea {
      min-width: 260px;
      min-height: 130px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 0.9rem;
      resize: vertical;
    }

    .grow { flex: 1; min-width: 220px; }
    .small { min-width: 180px; max-width: 250px; }

    button {
      cursor: pointer;
      font-weight: 650;
      transition: background-color 0.12s ease, border-color 0.12s ease, color 0.12s ease;
    }
    button:hover { filter: brightness(0.98); }

    .primary {
      background: var(--brand);
      border-color: var(--brand);
      color: #fff;
    }
    .secondary {
      background: #f8f9fc;
      color: #1f2a3d;
    }
    .danger {
      background: var(--danger-soft);
      border-color: #fecdca;
      color: var(--danger);
    }

    .status {
      display: inline-block;
      border-radius: 999px;
      padding: 0.35rem 0.7rem;
      font-size: 0.85rem;
      background: #eef2f7;
      color: #344054;
    }
    .status.ok {
      background: var(--ok-soft);
      color: var(--ok);
    }
    .status.error {
      background: var(--danger-soft);
      color: var(--danger);
    }

    table {
      width: 100%;
      border-collapse: collapse;
      border-radius: 12px;
      overflow: hidden;
      border: 1px solid var(--line);
      background: #fff;
    }
    th, td {
      border-bottom: 1px solid #edf0f5;
      padding: 0.6rem;
      text-align: left;
      vertical-align: top;
      font-size: 0.92rem;
    }
    th {
      background: #f8fafc;
      color: #344054;
      font-weight: 700;
      font-size: 0.82rem;
      text-transform: uppercase;
      letter-spacing: 0.02em;
    }
    tr:last-child td { border-bottom: 0; }
    td pre {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      max-width: 420px;
      font-size: 0.82rem;
      background: #f8f9fb;
      border: 1px solid #eceff4;
      border-radius: 8px;
      padding: 0.45rem 0.5rem;
    }

    .token-help {
      margin: 0.35rem 0 0;
      color: var(--muted);
      font-size: 0.84rem;
    }

    .table-tools {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.8rem;
      margin-bottom: 0.65rem;
      flex-wrap: wrap;
    }

    @media (max-width: 960px) {
      .layout { grid-template-columns: 1fr; }
      .page { margin-top: 1rem; }
    }
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <h1>Infinite Context Manager</h1>
      <p>Manage private and shared context entries for all registered AI agents.</p>
      <div class="hint">
        Quick start: create a token from <code>/oauth/token</code>, paste it below, then save entries.
      </div>
    </section>

    <section class="card" style="margin-bottom: 1rem;">
      <h2>1) Connect with your token</h2>
      <p class="subtitle">You need a bearer token with <code>contexts.read</code> and <code>contexts.write</code>.</p>
      <label class="grow">OAuth token
        <input id="authToken" class="grow" placeholder="Paste token here (example: abc.def)" />
      </label>
      <p class="token-help">Tip: token is saved in your browser on this computer only.</p>
    </section>

    <section class="layout">
      <section class="card">
        <h2>2) Create or edit an entry</h2>
        <p class="subtitle">Fill the fields and click <strong>Save entry</strong>.</p>
        <div class="row">
          <label class="small">Visibility
            <select id="visibility">
              <option value="private">private</option>
              <option value="shared">shared</option>
            </select>
          </label>
          <label class="grow">Agent ID (required for private)
            <input id="agentId" placeholder="Example: grok" />
          </label>
        </div>
        <div class="row">
          <label class="grow">Space
            <input id="space" class="grow" placeholder="Example: planning" />
          </label>
          <label class="grow">Key
            <input id="key" class="grow" placeholder="Example: summary" />
          </label>
        </div>
        <div class="row">
          <label class="grow">JSON value
            <textarea id="value">{}</textarea>
          </label>
        </div>
        <div class="row" style="align-items: center;">
          <button id="saveBtn" class="primary">Save entry</button>
          <span id="saveMessage" class="status">Waiting for action</span>
        </div>
      </section>

      <section class="card">
        <div class="table-tools">
          <div>
            <h2 style="margin-bottom: 0;">3) Browse entries</h2>
            <p class="subtitle" style="margin-bottom: 0;">Use filter/search and click refresh.</p>
          </div>
          <span id="entryCount" class="status">0 entries</span>
        </div>
        <div class="row">
          <label class="small">Filter by AI
            <select id="filterAi">
              <option value="">All</option>
            </select>
          </label>
          <label class="grow">Search
            <input id="searchQuery" class="grow" placeholder="Search AI, space, key, or JSON value..." />
          </label>
          <button id="refreshBtn" class="secondary">Refresh</button>
        </div>
        <table>
          <thead>
            <tr>
              <th>Visibility</th>
              <th>AI</th>
              <th>Space</th>
              <th>Key</th>
              <th>Value</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody id="entriesBody"></tbody>
        </table>
      </section>
    </section>
  </main>

  <script>
    const visibilityEl = document.getElementById("visibility");
    const authTokenEl = document.getElementById("authToken");
    const agentIdEl = document.getElementById("agentId");
    const spaceEl = document.getElementById("space");
    const keyEl = document.getElementById("key");
    const valueEl = document.getElementById("value");
    const saveBtn = document.getElementById("saveBtn");
    const saveMessage = document.getElementById("saveMessage");
    const filterAiEl = document.getElementById("filterAi");
    const searchQueryEl = document.getElementById("searchQuery");
    const refreshBtn = document.getElementById("refreshBtn");
    const entriesBody = document.getElementById("entriesBody");
    const entryCountEl = document.getElementById("entryCount");

    authTokenEl.value = localStorage.getItem("context_manager_token") || "";
    authTokenEl.addEventListener("input", () => {
      localStorage.setItem("context_manager_token", authTokenEl.value.trim());
    });

    function showMessage(text, level = "") {
      saveMessage.textContent = text;
      saveMessage.classList.remove("ok", "error");
      if (level) saveMessage.classList.add(level);
    }

    function updateAgentRequirement() {
      agentIdEl.disabled = visibilityEl.value === "shared";
      if (agentIdEl.disabled) {
        agentIdEl.value = "";
      }
    }

    function escapeHtml(value) {
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }

    function normalizeToken() {
      const token = authTokenEl.value.trim();
      if (!token || !/^[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+$/.test(token)) {
        return "";
      }
      return token;
    }

    function encodeEntry(entry) {
      const params = new URLSearchParams();
      params.set("visibility", entry.visibility);
      params.set("space", entry.space);
      params.set("key", entry.key);
      if (entry.visibility === "private") {
        params.set("agent_id", entry.agent_id || "");
      }
      return params.toString();
    }

    async function loadEntries() {
      const authToken = normalizeToken();
      if (!authToken) {
        entriesBody.innerHTML = "";
        entryCountEl.textContent = "0 entries";
        showMessage("Set a valid OAuth token to load entries.", "error");
        return;
      }
      const params = new URLSearchParams();
      if (filterAiEl.value) params.set("agent_id", filterAiEl.value);
      if (searchQueryEl.value.trim()) params.set("q", searchQueryEl.value.trim());
      const response = await fetch("/api/contexts?" + params.toString(), {
        headers: { "Authorization": "Bearer " + authToken }
      });
      const payload = await response.json();
      if (!response.ok) {
        entriesBody.innerHTML = "";
        entryCountEl.textContent = "0 entries";
        showMessage(payload.error || "Failed to load entries.", "error");
        return;
      }
      showMessage("Entries loaded.", "ok");

      const existingFilter = filterAiEl.value;
      filterAiEl.innerHTML = '<option value="">All</option>';
      for (const agentId of payload.available_ai || []) {
        const option = document.createElement("option");
        option.value = agentId;
        option.textContent = agentId;
        if (agentId === existingFilter) option.selected = true;
        filterAiEl.appendChild(option);
      }

      entriesBody.innerHTML = "";
      for (const entry of payload.entries || []) {
        const agentDisplay = entry.agent_id ? entry.agent_id : "—";
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${escapeHtml(entry.visibility)}</td>
          <td>${escapeHtml(agentDisplay)}</td>
          <td>${escapeHtml(entry.space)}</td>
          <td>${escapeHtml(entry.key)}</td>
          <td><pre>${escapeHtml(JSON.stringify(entry.value, null, 2))}</pre></td>
          <td>
            <button data-action="edit" class="secondary">Edit</button>
            <button data-action="delete" class="danger">Delete</button>
          </td>
        `;
        tr.querySelector('[data-action="edit"]').addEventListener("click", () => {
          visibilityEl.value = entry.visibility;
          updateAgentRequirement();
          agentIdEl.value = entry.agent_id || "";
          spaceEl.value = entry.space;
          keyEl.value = entry.key;
          valueEl.value = JSON.stringify(entry.value, null, 2);
          window.scrollTo({ top: 0, behavior: "smooth" });
          showMessage("Entry loaded into form. Edit and click Save entry.", "ok");
        });
        tr.querySelector('[data-action="delete"]').addEventListener("click", async () => {
          if (!confirm("Delete this entry?")) return;
          const authToken = normalizeToken();
          if (!authToken) {
            showMessage("A valid OAuth token is required.", "error");
            return;
          }
          const removeResponse = await fetch("/api/contexts?" + encodeEntry(entry), {
            method: "DELETE",
            headers: { "Authorization": "Bearer " + authToken }
          });
          if (!removeResponse.ok) {
            showMessage("Failed to delete entry.", "error");
            return;
          }
          showMessage("Entry deleted.", "ok");
          await loadEntries();
        });
        entriesBody.appendChild(tr);
      }
      const entryCount = (payload.entries || []).length;
      entryCountEl.textContent = `${entryCount} entr${entryCount === 1 ? "y" : "ies"}`;
    }

    async function saveEntry() {
      showMessage("Saving entry...");
      const rawValue = valueEl.value.trim();
      if (!rawValue) {
        showMessage("Value must be valid JSON.", "error");
        return;
      }
      let parsedValue;
      try {
        parsedValue = JSON.parse(rawValue);
      } catch {
        showMessage("Value must be valid JSON.", "error");
        return;
      }
      const payload = {
        visibility: visibilityEl.value,
        agent_id: agentIdEl.value.trim(),
        space: spaceEl.value.trim(),
        key: keyEl.value.trim(),
        value: parsedValue
      };
      const authToken = normalizeToken();
      if (!authToken) {
        showMessage("A valid OAuth token is required.", "error");
        return;
      }
      const response = await fetch("/api/contexts", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": "Bearer " + authToken
        },
        body: JSON.stringify(payload)
      });
      const result = await response.json();
      if (!response.ok) {
        showMessage(result.error || "Failed to save entry.", "error");
        return;
      }
      showMessage("Saved.", "ok");
      await loadEntries();
    }

    visibilityEl.addEventListener("change", updateAgentRequirement);
    saveBtn.addEventListener("click", saveEntry);
    refreshBtn.addEventListener("click", loadEntries);
    searchQueryEl.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        loadEntries();
      }
    });

    updateAgentRequirement();
    loadEntries();
  </script>
</body>
</html>
"""


def create_handler(settings: Settings, store: ContextStore):
    class InfiniteContextHandler(BaseHTTPRequestHandler):
        server_version = "InfiniteContextMCP/0.1.0"

        def do_GET(self) -> None:  # noqa: N802
            base_url = _request_base_url(self)
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                _json_response(self, HTTPStatus.OK, {"status": "ok"})
                return
            if parsed.path == "/.well-known/oauth-authorization-server":
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
            if parsed.path == "/connectors/grok":
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
            if parsed.path == "/ui":
                _html_response(self, HTTPStatus.OK, UI_HTML)
                return
            if parsed.path == "/api/contexts":
                self._handle_contexts_list(parsed)
                return
            if parsed.path == "/":
                _json_response(
                    self,
                    HTTPStatus.OK,
                    {
                        "service": "infinite-context-mcp",
                        "description": "OAuth2-protected MCP context service with private and shared spaces.",
                        "connectors": {"grok": f"{base_url}/connectors/grok"},
                        "ui": f"{base_url}/ui",
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
            if parsed.path == "/api/contexts":
                self._handle_contexts_upsert()
                return
            _json_response(self, HTTPStatus.NOT_FOUND, {"error": "Not found"})

        def do_PUT(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/api/contexts":
                self._handle_contexts_upsert()
                return
            _json_response(self, HTTPStatus.NOT_FOUND, {"error": "Not found"})

        def do_DELETE(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/api/contexts":
                self._handle_contexts_delete(parsed)
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
            token_payload = self._require_token(
                missing_error="missing_bearer_token",
                invalid_error="invalid_token",
            )
            if token_payload is None:
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

        def _require_token(
            self,
            *,
            missing_error: str = "unauthorized",
            invalid_error: str = "unauthorized",
        ) -> dict[str, object] | None:
            auth = self.headers.get("Authorization", "")
            if not auth.startswith("Bearer "):
                _json_response(self, HTTPStatus.UNAUTHORIZED, {"error": missing_error})
                return None
            try:
                return verify_token(auth.split(" ", 1)[1], settings.signing_key)
            except (ValueError, KeyError):
                _json_response(self, HTTPStatus.UNAUTHORIZED, {"error": invalid_error})
                return None

        def _require_scope(self, token_payload: dict[str, object], required_scope: str) -> bool:
            scopes = set(str(token_payload.get("scope", "")).split())
            if required_scope in scopes:
                return True
            _json_response(
                self,
                HTTPStatus.FORBIDDEN,
                {"error": f"missing_scope:{required_scope}"},
            )
            return False

        def _handle_contexts_list(self, parsed) -> None:
            token_payload = self._require_token()
            if token_payload is None or not self._require_scope(token_payload, "contexts.read"):
                return
            query = parse_qs(parsed.query)
            ai_filter = query.get("agent_id", [""])[0].strip()
            search_query = query.get("q", [""])[0].strip().lower()
            visibility_filter = query.get("visibility", [""])[0].strip()

            entries = store.list_all_entries()
            if ai_filter:
                entries = [entry for entry in entries if str(entry["agent_id"] or "") == ai_filter]
            if visibility_filter in {"private", "shared"}:
                entries = [
                    entry
                    for entry in entries
                    if str(entry["visibility"]) == visibility_filter
                ]
            if search_query:
                entries = [
                    entry
                    for entry in entries
                    if search_query
                    in " ".join(
                        [
                            str(entry["visibility"]),
                            str(entry["agent_id"] or ""),
                            str(entry["space"]),
                            str(entry["key"]),
                            json.dumps(entry["value"], sort_keys=True),
                        ]
                    ).lower()
                ]

            entries.sort(
                key=lambda entry: (
                    str(entry["visibility"]),
                    str(entry["agent_id"] or ""),
                    str(entry["space"]),
                    str(entry["key"]),
                )
            )
            available_ai = sorted(
                {
                    str(entry["agent_id"])
                    for entry in store.list_all_entries()
                    if entry["visibility"] == "private" and entry["agent_id"] is not None
                }
            )
            _json_response(
                self,
                HTTPStatus.OK,
                {"entries": entries, "available_ai": available_ai},
            )

        def _handle_contexts_upsert(self) -> None:
            token_payload = self._require_token()
            if token_payload is None or not self._require_scope(token_payload, "contexts.write"):
                return
            payload = _read_json(self)
            try:
                visibility = str(payload.get("visibility", "private"))
                space = str(payload["space"]).strip()
                key = str(payload["key"]).strip()
                if not space or not key:
                    raise ValueError("Fields 'space' and 'key' are required")
                if "value" not in payload:
                    raise ValueError("Field 'value' is required")
                if visibility not in {"private", "shared"}:
                    raise ValueError("Visibility must be 'private' or 'shared'")
                agent_id = str(payload.get("agent_id", "")).strip()
                if visibility == "private" and not agent_id:
                    raise ValueError("Field 'agent_id' is required for private contexts")
                result = store.upsert(
                    agent_id=agent_id,
                    visibility=visibility,
                    space=space,
                    key=key,
                    value=payload["value"],
                )
                response_payload = {
                    **result,
                    "agent_id": agent_id if visibility == "private" else None,
                }
                _json_response(self, HTTPStatus.OK, response_payload)
            except KeyError as error:
                _json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(error)})
            except ValueError as error:
                _json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(error)})

        def _handle_contexts_delete(self, parsed) -> None:
            token_payload = self._require_token()
            if token_payload is None or not self._require_scope(token_payload, "contexts.write"):
                return
            query = parse_qs(parsed.query)
            visibility = query.get("visibility", [""])[0].strip()
            space = query.get("space", [""])[0].strip()
            key = query.get("key", [""])[0].strip()
            agent_id = query.get("agent_id", [""])[0].strip()
            if not visibility or not space or not key:
                _json_response(
                    self,
                    HTTPStatus.BAD_REQUEST,
                    {"error": "Fields 'visibility', 'space', and 'key' are required"},
                )
                return
            if visibility == "private" and not agent_id:
                _json_response(
                    self,
                    HTTPStatus.BAD_REQUEST,
                    {"error": "Field 'agent_id' is required for private contexts"},
                )
                return
            try:
                result = store.delete(
                    agent_id=agent_id,
                    visibility=visibility,
                    space=space,
                    key=key,
                )
                _json_response(self, HTTPStatus.OK, result)
            except KeyError as error:
                _json_response(self, HTTPStatus.NOT_FOUND, {"error": str(error)})
            except ValueError as error:
                _json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(error)})

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

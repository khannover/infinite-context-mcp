# infinite-context-mcp

OAuth2-protected MCP context server for multiple AI agents.

---

## What this service does

Think of this like a **shared notebook for AIs**:

- each AI can have its own private notes
- all AIs can also share notes in shared spaces
- you can manage notes from:
  - MCP API (`/mcp`)
  - HTTP API (`/api/contexts`)
  - browser UI (`/ui`)

---

## Quick start (copy/paste)

### 1) Start the server

```bash
python -m infinite_context_mcp
```

Server defaults:
- host: `127.0.0.1`
- port: `8080`

Open these in your browser:
- Service info: `http://127.0.0.1:8080/`
- UI: `http://127.0.0.1:8080/ui`

---

## Environment variables (simple explanation)

- `HOST` = where server listens (default `127.0.0.1`)
- `PORT` = port number (default `8080`)
- `DATA_PATH` = where data is saved (default `data/contexts.json`)
- `OAUTH_SIGNING_KEY` = secret used to sign tokens
- `TOKEN_TTL_SECONDS` = token lifetime in seconds (default `3600`)
- `MCP_CLIENTS` = list of app login IDs, secrets, and scopes
- `GROK_PUBLIC_CLIENT_ENABLED` = when `true`, `/connectors/grok` uses a Grok-only public token endpoint so Grok can connect without entering a client secret

Example `MCP_CLIENTS`:

```json
{
  "grok": {
    "secret": "grok-secret",
    "agent_id": "grok",
    "scopes": ["contexts.read", "contexts.write"]
  },
  "copilot": {
    "secret": "copilot-secret",
    "agent_id": "copilot",
    "scopes": ["contexts.read", "contexts.write"]
  }
}
```

---

## How to create a token (step-by-step, like you are 5)

You need a token so the UI can talk to the server.

Imagine this token is a **temporary wristband** that says:
“yes, this person can read/write context data.”

### Step A: choose a client

From `MCP_CLIENTS` above, pick:
- `client_id` (example: `grok`)
- `client_secret` (example: `grok-secret`)

### Step B: ask server for token

Run:

```bash
curl -s -X POST http://127.0.0.1:8080/oauth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials&client_id=grok&client_secret=grok-secret"
```

You will get JSON like:

```json
{
  "access_token": "YOUR_TOKEN_HERE",
  "token_type": "Bearer",
  "expires_in": 3600,
  "scope": "contexts.read contexts.write"
}
```

Copy the value inside `access_token`.

### Grok custom connector setup

If Grok does not prompt for a client secret, set:

```bash
export GROK_PUBLIC_CLIENT_ENABLED=true
```

Then use your public connector URL, for example:

```text
https://your-server.example/connectors/grok
```

When this mode is enabled, the built-in Grok connector switches to a Grok-only token endpoint that can mint a bearer token without interactive secret entry. The regular `/oauth/token` endpoint still requires `client_id` and `client_secret` for existing confidential clients.

---

## What to put where in the UI (`/ui`)

Open `http://127.0.0.1:8080/ui`.

### 1) “OAuth token”
- paste `access_token` here

### 2) “Visibility”
- `private` = only one AI's private note
- `shared` = note everyone can read

### 3) “Agent ID”
- required for `private` entries
- leave empty for `shared`
- must match a known AI id (example: `grok`, `copilot`)

### 4) “Space”
- group/folder name (example: `planning`, `handoff`)

### 5) “Key”
- note name inside the space (example: `summary`)

### 6) “JSON value”
- the actual data, must be valid JSON
- example:

```json
{"status":"ready","owner":"grok"}
```

### 7) “Save entry”
- click to create or update entry

### 8) “Browse entries” area
- **Filter by AI**: show only one AI’s entries
- **Search**: text search in AI/space/key/value
- **Refresh**: reload from server
- **Edit** button: load row into form, change and save
- **Delete** button: remove row

---

## Docker

```bash
docker build -t infinite-context-mcp .
docker run --rm -p 8080:8080 \
  -e HOST=0.0.0.0 \
  -e OAUTH_SIGNING_KEY=replace-me \
  -e MCP_CLIENTS='{"grok":{"secret":"grok-secret","agent_id":"grok","scopes":["contexts.read","contexts.write"]}}' \
  -v "$(pwd)/data:/data" \
  infinite-context-mcp
```

Or with Docker Compose:

```bash
# prefer storing these in a local .env file (not committed)
# OAUTH_SIGNING_KEY=REPLACE_WITH_SECURE_KEY  # example: openssl rand -base64 32
# MCP_CLIENTS={"grok":{"secret":"grok-secret","agent_id":"grok","scopes":["contexts.read","contexts.write"]}}
# optional host-side port override (container stays on 8080)
# export HOST_PORT=8080
docker compose up --build
```

---

## Main endpoints

- `POST /oauth/token`
- `POST /mcp`
- `GET /ui`
- `GET|POST|PUT|DELETE /api/contexts`
- `GET /.well-known/oauth-authorization-server`
- `GET /connectors/grok`
- `GET /health`

`POST /api/contexts` and `PUT /api/contexts` both do upsert behavior.

---

## MCP tools

- `context_list`
- `context_get`
- `context_upsert`
- `context_change_visibility`

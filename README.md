# infinite-context-mcp

Dockerized MCP context server with OAuth2 authentication for multiple AI agents.

## What it provides

- OAuth2 client-credentials flow for AI-specific access tokens
- Standard MCP tool interface over HTTP at `/mcp`
- Private context namespaces per AI agent
- Shared spaces that any authenticated AI can read and update
- A visibility-change tool so an AI can move context from private to shared when a user asks
- A Grok-focused connector descriptor at `/connectors/grok` while keeping the main interface generic for any AI client

## Run locally

```bash
python -m infinite_context_mcp
```

## Environment variables

- `HOST` - server bind host, defaults to `127.0.0.1`
- `PORT` - server bind port, defaults to `8080`
- `DATA_PATH` - JSON persistence file, defaults to `data/contexts.json`
- `OAUTH_SIGNING_KEY` - HMAC signing key for bearer tokens
- `TOKEN_TTL_SECONDS` - token lifetime, defaults to `3600`
- `MCP_CLIENTS` - JSON object mapping OAuth client IDs to secrets and agent IDs

Example:

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

Or use Docker Compose:

```bash
# replace this placeholder with your own secure random key
export OAUTH_SIGNING_KEY='YOUR_SECURE_RANDOM_KEY_HERE'
export MCP_CLIENTS='{"grok":{"secret":"grok-secret","agent_id":"grok","scopes":["contexts.read","contexts.write"]}}'
docker compose up --build
```

## Main endpoints

- `POST /oauth/token`
- `POST /mcp`
- `GET /ui`
- `GET|POST|PUT|DELETE /api/contexts`
- `GET /.well-known/oauth-authorization-server`
- `GET /connectors/grok`
- `GET /health`

## Human context manager UI

Open `/ui` in a browser to manage contexts directly.

Features:
- add/update entries in private or shared visibility
- delete entries
- filter by AI identity
- free-text search over AI, space, key, and JSON value
- API calls require a valid bearer token with `contexts.read` or `contexts.write` scope

`POST /api/contexts` and `PUT /api/contexts` both perform upsert behavior.

## MCP tools

- `context_list`
- `context_get`
- `context_upsert`
- `context_change_visibility`

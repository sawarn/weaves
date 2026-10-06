# MCP connector v0

The local product runtime can connect to an allowlisted MCP server over
Streamable HTTP. It speaks the stateless `2026-07-28` protocol. Every request
carries protocol metadata; the client uses `tools/list` and `tools/call`. See the
[MCP transport specification](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)
and [tools specification](https://modelcontextprotocol.io/specification/2026-07-28/server/tools).

## Host allowlist

MCP networking is disabled unless `WEAVES_MCP_ALLOWED_HOSTS` contains the exact
hostname. Values are comma-separated; endpoints must use HTTPS on port 443 and
must not embed credentials, query strings, or fragments. Redirects are not
followed. This is a deployment-owned allowlist and should contain only trusted
MCP service hostnames.

## Connect a server

First inspect its tools. This request does not store the optional bearer token:

```http
POST /api/v0/mcp/discover
Content-Type: application/json

{
  "endpoint_url": "https://tools.example.com/mcp",
  "bearer_token": "<secret>"
}
```

The response shows the tool name, input schema, and whether v0 supports importing
it as a read-only context capability. Supported tools must have an object input
schema that requires only a string `query` argument. Choose trusted read-only
tools from that response and install them explicitly:

```http
POST /api/v0/plugin-installations
Content-Type: application/json

{
  "plugin_id": "mcp",
  "display_name": "Internal documentation",
  "endpoint_url": "https://tools.example.com/mcp",
  "bearer_token": "<secret>",
  "read_only_tool_names": ["search_docs"]
}
```

The bearer token is stored through the configured secret store. Imported tools
are registered as `context.read` capabilities, disabled from agent use unless
included in the agent's capability allowlist, and invoked through the plugin
gateway. Tool schemas are captured at install time; the health check reports an
error if an allowlisted tool disappears. Disable or re-enable individual
capabilities with the existing plugin installation patch endpoint.

## v0 boundaries

- Only Streamable HTTP and protocol version `2026-07-28` are supported. Stdio,
  legacy handshake-based MCP servers, OAuth flows, and MCP write tools are not
  supported.
- An administrator explicitly attests that selected tools are read-only; the
  server's MCP annotations are treated as untrusted metadata.
- Query tools that require only a string `query` are imported. The JSON Schema
  is captured and enforced by the gateway. `x-mcp-header` on the query is
  supported; annotations on other parameters are excluded.
- A successful call is normalized to a bounded text context item. Multimodal
  content, resources, prompts, async tasks, and input-required tool calls are
  not yet exposed to agents.
- MCP discovery and health checks run synchronously in the API process. Agent
  and workflow work can instead be submitted through the durable PostgreSQL
  execution-job API. Approval decisions use a PostgreSQL compare-and-set so
  only one API process can dispatch an approved action; the connector call
  itself remains synchronous, and an uncertain external result still requires
  reconciliation. Verified email, MFA, SSO/OIDC, and MCP OAuth remain outside
  this local v0.

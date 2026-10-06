import json

import httpx
from fastapi.testclient import TestClient

from weaves.product.api import create_app
from weaves.product.runtime import LocalPlatformRuntime
from weaves.product.runtime.mcp import _last_sse_message, _safe_header_value

_TOOL = {
    "name": "search_docs",
    "title": "Search documentation",
    "description": "Search internal docs using a query.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "minLength": 1,
                "x-mcp-header": "Search-Text",
            }
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}


def test_mcp_sse_and_header_values_follow_transport_rules():
    message = _last_sse_message(
        ': keepalive\n\nevent: message\ndata: {"jsonrpc":"2.0",\n'
        'data: "id":"abc","result":{}}\n\n'
    )
    assert message["id"] == "abc"
    assert _safe_header_value("Hello, 世界") == "=?base64?SGVsbG8sIOS4lueVjA==?="
    assert _safe_header_value(" padded ") == "=?base64?IHBhZGRlZCA=?="


def test_mcp_tools_are_allowlisted_governed_and_audited(monkeypatch):
    monkeypatch.setenv("WEAVES_MCP_ALLOWED_HOSTS", "tools.example.com")
    requests = []
    active_tool = json.loads(json.dumps(_TOOL))

    def respond(request):
        body = request.read()
        message = json.loads(body)
        requests.append((request, message))
        assert request.headers["MCP-Protocol-Version"] == "2026-07-28"
        assert request.headers["Mcp-Method"] == message["method"]
        assert request.headers["Authorization"] == "Bearer mcp-secret"
        if message["method"] == "tools/list":
            result = {"resultType": "complete", "tools": [active_tool]}
        elif message["method"] == "tools/call":
            assert request.headers["Mcp-Name"] == "search_docs"
            assert request.headers["Mcp-Param-Search-Text"] == "launch checklist"
            assert message["params"]["arguments"]["query"] == "launch checklist"
            result = {
                "resultType": "complete",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Launch checklist facts. api_key=hiddenvalue "
                            "Bearer hidden-bearer-token"
                        ),
                    }
                ],
            }
        else:
            raise AssertionError(f"unexpected MCP method: {message['method']}")
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": message["id"], "result": result},
        )

    runtime = LocalPlatformRuntime()
    mcp_client = httpx.Client(transport=httpx.MockTransport(respond))
    runtime.mcp_plugin._client = mcp_client
    client = TestClient(create_app(runtime))
    try:
        with client:
            discovered = client.post(
                "/api/v0/mcp/discover",
                json={
                    "endpoint_url": "https://tools.example.com/mcp",
                    "bearer_token": "mcp-secret",
                },
            )
            assert discovered.status_code == 200
            assert discovered.json()[0]["read_tool_supported"] is True

            installation_response = client.post(
                "/api/v0/plugin-installations",
                json={
                    "plugin_id": "mcp",
                    "display_name": "Internal docs",
                    "endpoint_url": "https://tools.example.com/mcp",
                    "bearer_token": "mcp-secret",
                    "read_only_tool_names": ["search_docs"],
                },
            )
            assert installation_response.status_code == 201
            installation = installation_response.json()
            assert "auth_ref" not in installation
            healthcheck = client.post(
                "/api/v0/plugin-installations/"
                f"{installation['plugin_installation_id']}/healthcheck"
            )
            assert healthcheck.status_code == 200
            assert healthcheck.json()["allowlisted_tools"] == "1"
            capability = client.get("/api/v0/capabilities").json()
            imported = next(
                item
                for item in capability
                if item["capability_id"].startswith("mcp.search-docs-")
            )
            assert imported["input_schema"] == _TOOL["inputSchema"]

            agent_response = client.post(
                "/api/v0/agents",
                json={
                    "name": "MCP context agent",
                    "instructions": "Use approved documentation search.",
                    "allowed_capability_ids": [
                        "knowledge.search",
                        imported["capability_id"],
                    ],
                },
            )
            assert agent_response.status_code == 201
            run_response = client.post(
                "/api/v0/runs",
                json={
                    "agent_id": agent_response.json()["id"],
                    "task": "launch checklist",
                },
            )
            assert run_response.status_code == 201
            invocations = run_response.json()["tool_invocations"]
            mcp_invocation = next(
                item
                for item in invocations
                if item["capability_id"] == imported["capability_id"]
            )
            assert mcp_invocation["status"] == "succeeded"
            response_text = run_response.json()["agent_run"]["output_summary"][
                "response"
            ]
            assert "hiddenvalue" not in response_text
            assert "hidden-bearer-token" not in response_text
            assert any(
                event["action"] == "plugin.capability.succeeded"
                and event["target_id"] == mcp_invocation["invocation_id"]
                for event in client.get("/api/v0/audit-events").json()
            )

            active_tool["inputSchema"]["properties"]["query"]["maxLength"] = 400
            schema_drift = client.post(
                "/api/v0/plugin-installations/"
                f"{installation['plugin_installation_id']}/healthcheck"
            )
            assert schema_drift.status_code == 502
            mcp_installations = [
                item
                for item in client.get("/api/v0/plugin-installations").json()
                if item["plugin_id"] == installation["plugin_id"]
            ]
            assert (
                len(mcp_installations) == 1
                and mcp_installations[0]["status"] == "error"
            )

            rejected = client.post(
                "/api/v0/plugin-installations",
                json={
                    "plugin_id": "mcp",
                    "display_name": "Invalid MCP",
                    "endpoint_url": "https://tools.example.com/mcp",
                    "bearer_token": "mcp-secret",
                    "read_only_tool_names": ["write_to_prod"],
                },
            )
            assert rejected.status_code == 422
            assert (
                len([item for item in requests if item[1]["method"] == "tools/call"])
                == 1
            )
            request_count = len(requests)
            rejected_host = client.post(
                "/api/v0/mcp/discover",
                json={"endpoint_url": "https://untrusted.example/mcp"},
            )
            assert rejected_host.status_code == 422
            assert len(requests) == request_count
    finally:
        client.close()
        mcp_client.close()

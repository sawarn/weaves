from fastapi.testclient import TestClient

from weaves.product.api import create_app
from weaves.product.runtime import LocalPlatformRuntime


def test_product_api_configures_agent_runs_and_inspects_platform_records():
    runtime = LocalPlatformRuntime()
    client = TestClient(create_app(runtime))

    with client:
        assert client.get("/api/v0/health").json() == {
            "status": "ok",
            "storage": "memory",
        }
        created = client.post(
            "/api/v0/agents",
            json={
                "name": "Policy helper",
                "description": "Answers policy questions.",
                "instructions": "Use approved handbook context and cite the sources.",
            },
        )
        assert created.status_code == 201
        agent = created.json()
        assert agent["current_version"]["instructions"].startswith("Use approved")
        first_version_id = agent["current_version"]["agent_version_id"]
        updated = client.patch(
            f"/api/v0/agents/{agent['id']}",
            json={"instructions": "Summarize approved context and name the sources."},
        )
        assert updated.status_code == 200
        assert updated.json()["current_version"]["version"] == 2
        assert runtime.agent_versions.get(first_version_id).instructions.startswith(
            "Use approved"
        )

        run_response = client.post(
            "/api/v0/runs",
            json={"agent_id": agent["id"], "task": "Summarize security basics"},
        )
        assert run_response.status_code == 201
        result = run_response.json()
        run_id = result["run"]["run_id"]
        assert result["run"]["status"] == "succeeded"
        assert (
            result["agent_run"]["agent_version_id"]
            == updated.json()["current_version"]["agent_version_id"]
        )
        assert result["artifacts"][0]["provenance"]

        listed = client.get("/api/v0/runs").json()
        assert listed[0]["run_id"] == run_id
        assert listed[0]["tool_invocations"][0]["capability_id"] == "knowledge.search"
        assert (
            client.get(f"/api/v0/runs/{run_id}/artifacts").json()[0]["run_id"] == run_id
        )
        assert client.get("/api/v0/artifacts").json()[0]["run_id"] == run_id
        events = client.get("/api/v0/audit-events").json()
        assert any(event["target_id"] == run_id for event in events)


def test_product_api_bounds_requests_and_rejects_unknown_agents():
    client = TestClient(create_app(LocalPlatformRuntime()))

    with client:
        too_short = client.post(
            "/api/v0/agents",
            json={"name": "A", "instructions": "Do work."},
        )
        assert too_short.status_code == 422
        unknown = client.post(
            "/api/v0/runs",
            json={"agent_id": "missing-agent", "task": "Run this task"},
        )
        assert unknown.status_code == 404

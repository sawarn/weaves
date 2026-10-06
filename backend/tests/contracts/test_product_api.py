import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Barrier, Lock

import httpx
import pytest
from fastapi.testclient import TestClient

from weaves.product.api import create_app
from weaves.product.contracts.v1 import (
    ModelProviderStatus,
    ModelProviderType,
    ModelResponse,
    ModelUsage,
    Permission,
    Principal,
    PrincipalStatus,
    PrincipalType,
    Role,
    RoleBinding,
    Workspace,
    WorkspaceStatus,
)
from weaves.product.runtime import LocalPlatformRuntime
from weaves.product.runtime.model_gateway import ModelGateway


def test_slack_installation_can_opt_in_to_thread_context_without_exposing_token():
    client = TestClient(create_app(LocalPlatformRuntime()))

    with client:
        response = client.post(
            "/api/v0/plugin-installations",
            json={
                "plugin_id": "slack",
                "display_name": "Engineering Slack",
                "user_token": "xoxp-secret-token",
                "channels": ["engineering"],
                "include_thread_replies": True,
            },
        )

    assert response.status_code == 201, response.text
    installation = response.json()
    assert installation["configuration"] == {
        "channels": ["engineering"],
        "include_thread_replies": True,
    }
    assert installation["has_credentials"] is True
    assert "auth_ref" not in installation
    assert "xoxp-secret-token" not in response.text


def test_organization_onboarding_is_rate_limited_per_client_address():
    client = TestClient(create_app(LocalPlatformRuntime()))
    request = {
        "name": "Rate limited org",
        "owner_email": "owner@example.test",
        "owner_display_name": "Owner",
    }

    with client:
        for _ in range(3):
            response = client.post("/api/v0/onboarding/organizations", json=request)
            assert response.status_code == 201, response.text

        limited = client.post("/api/v0/onboarding/organizations", json=request)

    assert limited.status_code == 429
    assert 0 < int(limited.headers["retry-after"]) <= 3600
    assert limited.json()["detail"] == "organization onboarding is temporarily limited"


def test_engineering_agent_template_creates_a_scoped_runnable_agent():
    client = TestClient(create_app(LocalPlatformRuntime()))
    with client:
        onboarded = client.post(
            "/api/v0/onboarding/organizations",
            json={
                "name": "Template test org",
                "owner_email": "template-owner@example.test",
                "owner_display_name": "Template Owner",
            },
        )
        assert onboarded.status_code == 201, onboarded.text
        headers = {"Authorization": f"Bearer {onboarded.json()['access_token']}"}

        templates = client.get("/api/v0/agent-templates", headers=headers)
        assert templates.status_code == 200, templates.text
        template = next(
            item
            for item in templates.json()
            if item["template_id"] == "engineering-assistant"
        )
        assert "github.issues.search" in template["recommended_capability_ids"]
        assert "slack.messages.search" in template["recommended_capability_ids"]
        assert "jira.issues.search" in template["recommended_capability_ids"]

        created = client.post(
            "/api/v0/agent-templates/engineering-assistant/agents",
            headers=headers,
            json={
                "allowed_capability_ids": ["knowledge.search"],
                "max_runtime_seconds": 120,
                "max_tool_calls": 2,
                "max_output_tokens": 600,
            },
        )
        assert created.status_code == 201, created.text
        agent = created.json()
        assert agent["name"] == "Engineering Assistant"
        assert agent["current_version"]["persona"] == (
            "A careful engineering operations assistant."
        )
        assert agent["current_version"]["allowed_capability_ids"] == [
            "knowledge.search"
        ]
        assert agent["current_version"]["budget"]["max_runtime_seconds"] == 120
        assert agent["current_version"]["budget"]["max_tool_calls"] == 2
        assert agent["current_version"]["budget"]["max_output_tokens"] == 600

        updated = client.patch(
            f"/api/v0/agents/{agent['id']}",
            headers=headers,
            json={
                "budget": {
                    "max_runtime_seconds": 180,
                    "max_tool_calls": 1,
                    "max_output_tokens": 300,
                }
            },
        )
        assert updated.status_code == 200, updated.text
        agent = updated.json()
        assert agent["current_version"]["version"] == 2
        assert agent["current_version"]["budget"]["max_runtime_seconds"] == 180
        assert agent["current_version"]["budget"]["max_tool_calls"] == 1

        run = client.post(
            "/api/v0/runs",
            headers=headers,
            json={
                "agent_id": agent["id"],
                "task": "Summarize engineering working agreements",
            },
        )
        assert run.status_code == 201, run.text
        assert run.json()["run"]["status"] == "succeeded"
        assert run.json()["artifacts"]


def test_agent_output_schema_can_be_configured_and_returned_through_api(monkeypatch):
    runtime = LocalPlatformRuntime()

    def complete(request, selected_binding):
        assert '"required": ["answer"]' in request.messages[0].content
        return ModelResponse(
            provider_id=selected_binding.provider.id,
            model_id=selected_binding.profile.model,
            content='{"answer":"approved"}',
            usage=ModelUsage(input_tokens=10, output_tokens=4, total_tokens=14),
        )

    monkeypatch.setattr(runtime.model, "complete", complete)
    client = TestClient(create_app(runtime))
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    }
    with client:
        onboarded = client.post(
            "/api/v0/onboarding/organizations",
            json={
                "name": "Structured output org",
                "owner_email": "structured-owner@example.test",
                "owner_display_name": "Structured Owner",
            },
        )
        assert onboarded.status_code == 201, onboarded.text
        headers = {"Authorization": f"Bearer {onboarded.json()['access_token']}"}
        created = client.post(
            "/api/v0/agents",
            headers=headers,
            json={
                "name": "Structured responder",
                "instructions": "Answer using the configured response shape.",
                "allowed_capability_ids": ["knowledge.search"],
                "output_schema": schema,
            },
        )
        assert created.status_code == 201, created.text
        agent = created.json()
        assert agent["current_version"]["output_schema"] == schema

        run = client.post(
            "/api/v0/runs",
            headers=headers,
            json={"agent_id": agent["id"], "task": "Answer approved"},
        )
        assert run.status_code == 201, run.text
        assert run.json()["agent_run"]["output_summary"]["structured_output"] == {
            "answer": "approved"
        }
        assert json.loads(run.json()["artifacts"][0]["summary"]) == {
            "answer": "approved"
        }

        cleared = client.patch(
            f"/api/v0/agents/{agent['id']}",
            headers=headers,
            json={"output_schema": None},
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["current_version"]["version"] == 2
        assert cleared.json()["current_version"]["output_schema"] is None

        invalid = client.post(
            "/api/v0/agents",
            headers=headers,
            json={
                "name": "Invalid schema agent",
                "instructions": "Return JSON.",
                "allowed_capability_ids": ["knowledge.search"],
                "output_schema": {"type": "unknown"},
            },
        )
        assert invalid.status_code == 422


def test_product_api_bearer_token_gate_preserves_health_check(monkeypatch):
    monkeypatch.setenv("WEAVES_API_TOKEN", "test-platform-token")
    monkeypatch.delenv("WEAVES_API_TOKENS", raising=False)
    client = TestClient(create_app(LocalPlatformRuntime()))

    with client:
        assert client.get("/api/v0/health").status_code == 200
        assert client.get("/api/v0/organizations").status_code == 401
        invalid = client.get(
            "/api/v0/organizations",
            headers={"Authorization": "Bearer incorrect-token"},
        )
        assert invalid.status_code == 401
        assert invalid.headers["www-authenticate"] == "Bearer"
        authorized = client.get(
            "/api/v0/organizations",
            headers={"Authorization": "Bearer test-platform-token"},
        )
        assert authorized.status_code == 200


def test_postgres_mode_fails_closed_without_bearer_but_allows_bootstrap(monkeypatch):
    monkeypatch.delenv("WEAVES_API_TOKEN", raising=False)
    monkeypatch.delenv("WEAVES_API_TOKENS", raising=False)
    runtime = LocalPlatformRuntime()
    runtime.storage_mode = "postgres"
    client = TestClient(create_app(runtime))

    with client:
        assert client.get("/api/v0/health").status_code == 200
        protected = client.get("/api/v0/organizations")
        assert protected.status_code == 401
        assert protected.headers["www-authenticate"] == "Bearer"

        onboarded = client.post(
            "/api/v0/onboarding/organizations",
            json={
                "name": "Fail Closed Org",
                "owner_email": "owner@fail-closed.test",
                "owner_display_name": "Owner",
            },
        )
        assert onboarded.status_code == 201, onboarded.text
        owner_headers = {"Authorization": f"Bearer {onboarded.json()['access_token']}"}
        assert (
            client.get("/api/v0/organizations", headers=owner_headers).status_code
            == 200
        )


def test_organization_onboarding_scopes_requests_and_runs_agent():
    client = TestClient(create_app(LocalPlatformRuntime()))
    with client:
        onboarded = client.post(
            "/api/v0/onboarding/organizations",
            json={
                "name": "Acme Research",
                "owner_email": "Owner@Example.com",
                "owner_display_name": "Acme Owner",
            },
        )
        assert onboarded.status_code == 201, onboarded.text
        payload = onboarded.json()
        org_id = payload["organization"]["id"]
        workspace_id = payload["workspace"]["id"]
        owner_token = payload["access_token"]
        headers = {"Authorization": f"Bearer {owner_token}"}

        organization_list = client.get("/api/v0/organizations", headers=headers)
        assert organization_list.status_code == 200
        assert [item["id"] for item in organization_list.json()] == [org_id]
        workspace_list = client.get("/api/v0/workspaces", headers=headers)
        assert workspace_list.status_code == 200
        assert [item["id"] for item in workspace_list.json()] == [workspace_id]
        installations = client.get("/api/v0/plugin-installations", headers=headers)
        assert installations.status_code == 200
        knowledge_installation_id = installations.json()[0]["plugin_installation_id"]
        knowledge_health = client.post(
            f"/api/v0/plugin-installations/{knowledge_installation_id}/healthcheck",
            headers=headers,
        )
        assert knowledge_health.status_code == 200
        assert knowledge_health.json()["documents"] == "1"

        created_agent = client.post(
            "/api/v0/agents",
            headers=headers,
            json={
                "name": "Research assistant",
                "instructions": "Answer using the workspace knowledge.",
            },
        )
        assert created_agent.status_code == 201, created_agent.text
        agent_id = created_agent.json()["id"]
        run = client.post(
            "/api/v0/runs",
            headers=headers,
            json={"task": "Summarize the workspace guide", "agent_id": agent_id},
        )
        assert run.status_code == 201, run.text
        assert run.json()["run"]["org_id"] == org_id
        assert run.json()["run"]["workspace_id"] == workspace_id
        matching_audit = client.get(
            "/api/v0/audit-events",
            headers=headers,
            params={
                "action": "agent.run.succeeded",
                "actor_principal_id": payload["principal"]["id"],
            },
        )
        assert matching_audit.status_code == 200
        assert matching_audit.json()
        assert all(
            item["action"] == "agent.run.succeeded"
            and item["actor_principal_id"] == payload["principal"]["id"]
            for item in matching_audit.json()
        )
        invalid_audit_range = client.get(
            "/api/v0/audit-events",
            headers=headers,
            params={
                "created_after": "2026-02-02T00:00:00Z",
                "created_before": "2026-02-01T00:00:00Z",
            },
        )
        assert invalid_audit_range.status_code == 422

        policy_list = client.get("/api/v0/approval-policies", headers=headers)
        assert policy_list.status_code == 200
        policy = client.post(
            "/api/v0/approval-policies",
            headers=headers,
            json={
                "name": "High risk requires review",
                "required_risk_levels": ["high", "critical"],
                "allow_self_approval": False,
            },
        )
        assert policy.status_code == 201, policy.text
        policy_id = policy.json()["approval_policy_id"]
        assert policy.json()["workspace_id"] == workspace_id
        fetched_policy = client.get(
            f"/api/v0/approval-policies/{policy_id}", headers=headers
        )
        assert fetched_policy.status_code == 200
        updated_policy = client.patch(
            f"/api/v0/approval-policies/{policy_id}",
            headers=headers,
            json={"allow_self_approval": True},
        )
        assert updated_policy.status_code == 200
        assert updated_policy.json()["allow_self_approval"] is True

        policy_admin = client.post(
            "/api/v0/users",
            headers=headers,
            json={
                "email": "policy-admin@example.com",
                "display_name": "Policy Admin",
                "permissions": ["approval_policies.manage"],
            },
        )
        assert policy_admin.status_code == 201, policy_admin.text
        policy_admin_headers = {
            "Authorization": f"Bearer {policy_admin.json()['access_token']}"
        }
        assert (
            client.get(
                "/api/v0/approval-policies", headers=policy_admin_headers
            ).status_code
            == 200
        )
        policy_created_by_admin = client.post(
            "/api/v0/approval-policies",
            headers=policy_admin_headers,
            json={"name": "Admin managed policy"},
        )
        assert policy_created_by_admin.status_code == 201
        runner_role = client.post(
            "/api/v0/roles",
            headers=headers,
            json={"name": "Workspace runner", "permissions": ["agents.run"]},
        )
        assert runner_role.status_code == 201, runner_role.text

        created_workspace = client.post(
            "/api/v0/workspaces",
            headers=headers,
            json={"name": "Research sandbox", "environment": "test"},
        )
        assert created_workspace.status_code == 201, created_workspace.text
        secondary_workspace_id = created_workspace.json()["id"]
        secondary_headers = {
            **headers,
            "X-Workspace-ID": secondary_workspace_id,
        }
        visible_workspaces = client.get("/api/v0/workspaces", headers=secondary_headers)
        assert {item["id"] for item in visible_workspaces.json()} == {
            workspace_id,
            secondary_workspace_id,
        }
        secondary_agent = client.post(
            "/api/v0/agents",
            headers=secondary_headers,
            json={
                "name": "Sandbox assistant",
                "instructions": "Answer using this workspace's knowledge.",
            },
        )
        assert secondary_agent.status_code == 201, secondary_agent.text
        secondary_run = client.post(
            "/api/v0/runs",
            headers=secondary_headers,
            json={
                "task": "Summarize the workspace guide",
                "agent_id": secondary_agent.json()["id"],
            },
        )
        assert secondary_run.status_code == 201, secondary_run.text
        assert secondary_run.json()["run"]["workspace_id"] == secondary_workspace_id

        member_creation = client.post(
            "/api/v0/users",
            headers=secondary_headers,
            json={
                "email": "member@example.com",
                "display_name": "Workspace Member",
                "role_id": runner_role.json()["id"],
            },
        )
        assert member_creation.status_code == 201, member_creation.text
        member_headers = {
            "Authorization": f"Bearer {member_creation.json()['access_token']}",
        }
        member_password = "member-password-123"
        assert (
            client.put(
                "/api/v0/auth/password",
                headers=member_headers,
                json={"password": member_password},
            ).status_code
            == 204
        )
        member_login = client.post(
            "/api/v0/auth/login",
            json={
                "email": member_creation.json()["user"]["email"],
                "password": member_password,
            },
        )
        assert member_login.status_code == 200, member_login.text
        member_session_headers = {
            "Authorization": f"Bearer {member_login.json()['access_token']}"
        }
        member_workspaces = client.get("/api/v0/workspaces", headers=member_headers)
        assert [item["id"] for item in member_workspaces.json()] == [
            secondary_workspace_id
        ]
        assert (
            client.get(
                "/api/v0/workspaces?include_archived=true", headers=member_headers
            ).status_code
            == 403
        )
        assert client.get("/api/v0/agents", headers=member_headers).status_code == 403
        denied_policy = client.post(
            "/api/v0/approval-policies",
            headers=member_headers,
            json={"name": "Unauthorized policy"},
        )
        assert denied_policy.status_code == 403
        member_run = client.post(
            "/api/v0/runs",
            headers=member_headers,
            json={
                "task": "Summarize the workspace guide",
                "agent_id": secondary_agent.json()["id"],
            },
        )
        assert member_run.status_code == 201, member_run.text
        assert member_run.json()["run"]["workspace_id"] == secondary_workspace_id
        assert (
            client.get("/api/v0/artifacts", headers=member_headers).status_code == 403
        )
        artifact_reader_role = client.post(
            "/api/v0/roles",
            headers=secondary_headers,
            json={
                "name": "Artifact reader",
                "permissions": ["artifacts.read"],
            },
        )
        assert artifact_reader_role.status_code == 201, artifact_reader_role.text
        binding = client.post(
            "/api/v0/role-bindings",
            headers=secondary_headers,
            json={
                "principal_id": member_creation.json()["principal"]["id"],
                "role_id": artifact_reader_role.json()["id"],
                "workspace_id": secondary_workspace_id,
            },
        )
        assert binding.status_code == 201, binding.text
        repeated_binding = client.post(
            "/api/v0/role-bindings",
            headers=secondary_headers,
            json={
                "principal_id": member_creation.json()["principal"]["id"],
                "role_id": artifact_reader_role.json()["id"],
                "workspace_id": secondary_workspace_id,
            },
        )
        assert repeated_binding.status_code == 201
        assert repeated_binding.json()["id"] == binding.json()["id"]
        assert (
            client.get("/api/v0/artifacts", headers=member_headers).status_code == 200
        )
        removed_binding = client.delete(
            f"/api/v0/role-bindings/{binding.json()['id']}",
            headers=secondary_headers,
        )
        assert removed_binding.status_code == 204
        assert (
            client.get("/api/v0/artifacts", headers=member_headers).status_code == 403
        )
        member_cross_workspace = client.get(
            "/api/v0/agents",
            headers={
                **member_headers,
                "X-Workspace-ID": workspace_id,
            },
        )
        assert member_cross_workspace.status_code == 403
        suspended = client.post(
            f"/api/v0/users/{member_creation.json()['user']['id']}/suspend",
            headers=secondary_headers,
        )
        assert suspended.status_code == 200, suspended.text
        assert suspended.json()["status"] == "suspended"
        assert (
            client.get("/api/v0/workspaces", headers=member_headers).status_code == 401
        )
        assert (
            client.get("/api/v0/workspaces", headers=member_session_headers).status_code
            == 401
        )
        reactivated = client.post(
            f"/api/v0/users/{member_creation.json()['user']['id']}/reactivate",
            headers=secondary_headers,
        )
        assert reactivated.status_code == 200, reactivated.text
        reactivated_headers = {
            "Authorization": f"Bearer {reactivated.json()['access_token']}",
        }
        assert (
            client.get("/api/v0/workspaces", headers=member_headers).status_code == 401
        )
        assert (
            client.get("/api/v0/workspaces", headers=member_session_headers).status_code
            == 401
        )
        reactivated_access = client.get(
            "/api/v0/workspaces", headers=reactivated_headers
        )
        assert [item["id"] for item in reactivated_access.json()] == [
            secondary_workspace_id
        ]

        another_org = client.post(
            "/api/v0/onboarding/organizations",
            json={
                "name": "Other Research",
                "owner_email": "other@example.com",
                "owner_display_name": "Other Owner",
            },
        )
        assert another_org.status_code == 201
        other_workspace_id = another_org.json()["workspace"]["id"]
        cross_tenant = client.get(
            "/api/v0/agents",
            headers={**headers, "X-Workspace-ID": other_workspace_id},
        )
        assert cross_tenant.status_code == 403


def test_workspace_lifecycle_requires_admin_and_preserves_active_workspace():
    client = TestClient(create_app(LocalPlatformRuntime()))
    with client:
        onboarded = client.post(
            "/api/v0/onboarding/organizations",
            json={
                "name": "Lifecycle Org",
                "owner_email": "owner@lifecycle.test",
                "owner_display_name": "Owner",
            },
        )
        assert onboarded.status_code == 201, onboarded.text
        owner_headers = {"Authorization": f"Bearer {onboarded.json()['access_token']}"}
        default_workspace_id = onboarded.json()["workspace"]["id"]

        last_workspace_archive = client.patch(
            f"/api/v0/workspaces/{default_workspace_id}",
            headers=owner_headers,
            json={"status": "archived"},
        )
        assert last_workspace_archive.status_code == 422

        created = client.post(
            "/api/v0/workspaces",
            headers=owner_headers,
            json={"name": "Temporary", "environment": "test"},
        )
        assert created.status_code == 201, created.text
        temporary_id = created.json()["id"]

        archived = client.patch(
            f"/api/v0/workspaces/{temporary_id}",
            headers=owner_headers,
            json={"status": "archived"},
        )
        assert archived.status_code == 200, archived.text
        assert archived.json()["status"] == "archived"
        assert {
            item["id"]
            for item in client.get("/api/v0/workspaces", headers=owner_headers).json()
        } == {default_workspace_id}
        all_workspaces = client.get(
            "/api/v0/workspaces?include_archived=true", headers=owner_headers
        )
        assert all_workspaces.status_code == 200
        assert {item["id"] for item in all_workspaces.json()} == {
            default_workspace_id,
            temporary_id,
        }

        restored = client.patch(
            f"/api/v0/workspaces/{temporary_id}",
            headers=owner_headers,
            json={"status": "active", "name": "Restored"},
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["status"] == "active"
        assert restored.json()["name"] == "Restored"
        assert {
            item["id"]
            for item in client.get("/api/v0/workspaces", headers=owner_headers).json()
        } == {default_workspace_id, temporary_id}

        audit = client.get(
            "/api/v0/audit-events",
            headers={
                **owner_headers,
                "X-Workspace-ID": temporary_id,
            },
            params={"action": "workspace.updated", "target_id": temporary_id},
        )
        assert audit.status_code == 200
        assert len(audit.json()) == 2


def test_user_password_login_creates_expiring_revocable_session():
    runtime = LocalPlatformRuntime()
    client = TestClient(create_app(runtime))
    with client:
        onboarded = client.post(
            "/api/v0/onboarding/organizations",
            json={
                "name": "Session Org",
                "owner_email": "owner@sessions.test",
                "owner_display_name": "Owner",
            },
        )
        assert onboarded.status_code == 201, onboarded.text
        user = onboarded.json()["owner"]
        api_key_headers = {
            "Authorization": f"Bearer {onboarded.json()['access_token']}"
        }
        initial_password = "initial-password-123"
        enrollment = client.put(
            "/api/v0/auth/password",
            headers=api_key_headers,
            json={"password": initial_password},
        )
        assert enrollment.status_code == 204
        stored_password = runtime.user_passwords.get(user["id"])
        assert initial_password not in stored_password.password_hash
        assert stored_password.password_hash.startswith("pbkdf2_sha256$")

        invalid_login = client.post(
            "/api/v0/auth/login",
            json={"email": user["email"], "password": "incorrect-password"},
        )
        assert invalid_login.status_code == 401
        login = client.post(
            "/api/v0/auth/login",
            json={"email": user["email"], "password": initial_password},
        )
        assert login.status_code == 200, login.text
        session_token = login.json()["access_token"]
        session_headers = {"Authorization": f"Bearer {session_token}"}
        current_user = client.get("/api/v0/auth/me", headers=session_headers)
        assert current_user.status_code == 200
        assert current_user.json()["user"]["id"] == user["id"]

        changed_password = "replacement-password-456"
        rejected_change = client.put(
            "/api/v0/auth/password",
            headers=api_key_headers,
            json={
                "current_password": "incorrect-current-password",
                "password": changed_password,
            },
        )
        assert rejected_change.status_code == 422
        change = client.put(
            "/api/v0/auth/password",
            headers=api_key_headers,
            json={
                "current_password": initial_password,
                "password": changed_password,
            },
        )
        assert change.status_code == 204
        assert client.get("/api/v0/auth/me", headers=session_headers).status_code == 401

        new_login = client.post(
            "/api/v0/auth/login",
            json={"email": user["email"], "password": changed_password},
        )
        assert new_login.status_code == 200
        new_session_token = new_login.json()["access_token"]
        logout = client.post(
            "/api/v0/auth/logout",
            headers={"Authorization": f"Bearer {new_session_token}"},
        )
        assert logout.status_code == 204
        assert (
            client.get(
                "/api/v0/auth/me",
                headers={"Authorization": f"Bearer {new_session_token}"},
            ).status_code
            == 401
        )

        expiring_login = client.post(
            "/api/v0/auth/login",
            json={"email": user["email"], "password": changed_password},
        )
        assert expiring_login.status_code == 200
        stored_session = runtime.user_sessions.get(expiring_login.json()["session_id"])
        expired_at = datetime.now(timezone.utc)
        runtime.user_sessions.put(
            stored_session.model_copy(
                update={"expires_at": expired_at, "updated_at": expired_at}
            )
        )
        assert (
            client.get(
                "/api/v0/auth/me",
                headers={
                    "Authorization": f"Bearer {expiring_login.json()['access_token']}"
                },
            ).status_code
            == 401
        )


def test_login_api_limits_repeated_failures_without_revealing_account_state():
    runtime = LocalPlatformRuntime()
    runtime.login_rate_limiter.limit = 1
    client = TestClient(create_app(runtime))

    with client:
        onboarded = client.post(
            "/api/v0/onboarding/organizations",
            json={
                "name": "Throttle Org",
                "owner_email": "owner@throttle.test",
                "owner_display_name": "Owner",
            },
        )
        assert onboarded.status_code == 201
        user = onboarded.json()["owner"]
        enrolled = client.put(
            "/api/v0/auth/password",
            headers={"Authorization": f"Bearer {onboarded.json()['access_token']}"},
            json={"password": "throttle-password-123"},
        )
        assert enrolled.status_code == 204

        first_failure = client.post(
            "/api/v0/auth/login",
            json={"email": user["email"], "password": "incorrect-password"},
        )
        throttled = client.post(
            "/api/v0/auth/login",
            json={"email": user["email"], "password": "throttle-password-123"},
        )

    assert first_failure.status_code == 401
    assert throttled.status_code == 429
    assert throttled.json()["detail"] == "Too many sign-in attempts. Try again later."
    assert int(throttled.headers["retry-after"]) > 0


def test_user_invitation_is_one_time_resendable_and_revocable():
    runtime = LocalPlatformRuntime()
    client = TestClient(create_app(runtime))
    with client:
        onboarded = client.post(
            "/api/v0/onboarding/organizations",
            json={
                "name": "Invitation Org",
                "owner_email": "owner@invitations.test",
                "owner_display_name": "Owner",
            },
        )
        assert onboarded.status_code == 201, onboarded.text
        owner_headers = {"Authorization": f"Bearer {onboarded.json()['access_token']}"}

        created = client.post(
            "/api/v0/user-invitations",
            headers=owner_headers,
            json={
                "email": "new.member@invitations.test",
                "display_name": "New Member",
                "permissions": ["agents.run"],
            },
        )
        assert created.status_code == 201, created.text
        first = created.json()
        invitation_id = first["invitation"]["invitation_id"]
        assert first["user"]["status"] == "invited"
        assert first["principal"]["status"] == "disabled"
        assert "token_digest" not in first["invitation"]
        assert "access_token" not in first

        visible = client.get("/api/v0/user-invitations", headers=owner_headers)
        assert visible.status_code == 200
        assert visible.json()[0]["invitation_id"] == invitation_id
        assert "token_digest" not in visible.json()[0]

        resent = client.post(
            f"/api/v0/user-invitations/{invitation_id}/resend",
            headers=owner_headers,
        )
        assert resent.status_code == 200, resent.text
        assert resent.json()["invitation_token"] != first["invitation_token"]

        password = "invited-member-password-123"
        stale_token = client.post(
            "/api/v0/auth/accept-invitation",
            json={
                "invitation_token": first["invitation_token"],
                "password": password,
            },
        )
        assert stale_token.status_code == 400
        accepted = client.post(
            "/api/v0/auth/accept-invitation",
            json={
                "invitation_token": resent.json()["invitation_token"],
                "password": password,
            },
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["user"]["status"] == "active"
        invitee_headers = {"Authorization": f"Bearer {accepted.json()['access_token']}"}
        assert (
            client.get("/api/v0/workspaces", headers=invitee_headers).status_code == 200
        )
        password_login = client.post(
            "/api/v0/auth/login",
            json={"email": first["user"]["email"], "password": password},
        )
        assert password_login.status_code == 200, password_login.text
        replay = client.post(
            "/api/v0/auth/accept-invitation",
            json={
                "invitation_token": resent.json()["invitation_token"],
                "password": password,
            },
        )
        assert replay.status_code == 400
        assert (
            client.post(
                f"/api/v0/user-invitations/{invitation_id}/resend",
                headers=owner_headers,
            ).status_code
            == 409
        )

        revoked = client.post(
            "/api/v0/user-invitations",
            headers=owner_headers,
            json={
                "email": "revoked.member@invitations.test",
                "display_name": "Revoked Member",
                "permissions": ["agents.run"],
            },
        )
        assert revoked.status_code == 201, revoked.text
        revoked_id = revoked.json()["invitation"]["invitation_id"]
        revoke_response = client.delete(
            f"/api/v0/user-invitations/{revoked_id}", headers=owner_headers
        )
        assert revoke_response.status_code == 204
        invalidated = client.post(
            "/api/v0/auth/accept-invitation",
            json={
                "invitation_token": revoked.json()["invitation_token"],
                "password": password,
            },
        )
        assert invalidated.status_code == 400

        replacement = client.post(
            "/api/v0/user-invitations",
            headers=owner_headers,
            json={
                "email": "revoked.member@invitations.test",
                "display_name": "Replacement Member",
                "permissions": ["agents.run"],
            },
        )
        assert replacement.status_code == 201, replacement.text
        replacement_acceptance = client.post(
            "/api/v0/auth/accept-invitation",
            json={
                "invitation_token": replacement.json()["invitation_token"],
                "password": password,
            },
        )
        assert replacement_acceptance.status_code == 200
        replacement_login = client.post(
            "/api/v0/auth/login",
            json={
                "email": "revoked.member@invitations.test",
                "password": password,
            },
        )
        assert replacement_login.status_code == 200

        expired_invite = client.post(
            "/api/v0/user-invitations",
            headers=owner_headers,
            json={
                "email": "expired.member@invitations.test",
                "display_name": "Expired Member",
                "permissions": ["agents.run"],
            },
        )
        assert expired_invite.status_code == 201, expired_invite.text
        expiry = datetime.now(timezone.utc) - timedelta(days=1)
        invitation_record = runtime.user_invitations.get(
            expired_invite.json()["invitation"]["invitation_id"]
        )
        runtime.user_invitations.put(
            invitation_record.model_copy(update={"expires_at": expiry})
        )
        expired_acceptance = client.post(
            "/api/v0/auth/accept-invitation",
            json={
                "invitation_token": expired_invite.json()["invitation_token"],
                "password": password,
            },
        )
        assert expired_acceptance.status_code == 400


def test_workspace_admin_cannot_manage_organization_wide_resources():
    client = TestClient(create_app(LocalPlatformRuntime()))

    with client:
        onboarded = client.post(
            "/api/v0/onboarding/organizations",
            json={
                "name": "Scoped Administration Org",
                "owner_email": "owner@scoped-admin.example",
                "owner_display_name": "Scoped Admin Owner",
            },
        )
        assert onboarded.status_code == 201
        owner_headers = {"Authorization": f"Bearer {onboarded.json()['access_token']}"}

        second_workspace = client.post(
            "/api/v0/workspaces",
            headers=owner_headers,
            json={"name": "Scoped admin workspace"},
        )
        assert second_workspace.status_code == 201
        second_workspace_id = second_workspace.json()["id"]
        second_workspace_owner_headers = {
            **owner_headers,
            "X-Workspace-ID": second_workspace_id,
        }

        provider_response = client.post(
            "/api/v0/model-providers",
            headers=owner_headers,
            json={
                "provider_type": "openai",
                "display_name": "Organization model provider",
                "api_key": "test-model-provider-key",
                "initial_model": "test-model-v1",
            },
        )
        assert provider_response.status_code == 201, provider_response.text
        provider = provider_response.json()
        profiles = client.get("/api/v0/model-profiles", headers=owner_headers).json()
        profile_id = next(
            item["id"] for item in profiles if item["provider_id"] == provider["id"]
        )

        service_account = client.post(
            "/api/v0/service-accounts",
            headers=owner_headers,
            json={"name": "Org service", "permissions": ["agents.run"]},
        )
        assert service_account.status_code == 201
        credential_id = service_account.json()["credential"]["id"]

        workspace_admin = client.post(
            "/api/v0/users",
            headers=second_workspace_owner_headers,
            json={
                "email": "workspace-admin@scoped-admin.example",
                "display_name": "Workspace Admin",
                "permissions": [
                    "models.manage",
                    "roles.manage",
                    "users.manage",
                ],
            },
        )
        assert workspace_admin.status_code == 201, workspace_admin.text
        workspace_admin_headers = {
            "Authorization": f"Bearer {workspace_admin.json()['access_token']}"
        }

        assert (
            client.get(
                "/api/v0/model-providers", headers=workspace_admin_headers
            ).status_code
            == 403
        )
        assert (
            client.get(
                "/api/v0/model-profiles", headers=workspace_admin_headers
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/api/v0/model-providers/{provider['id']}/refresh-models",
                headers=workspace_admin_headers,
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/v0/models/refresh", headers=workspace_admin_headers
            ).status_code
            == 403
        )
        assert (
            client.get(
                "/api/v0/api-credentials", headers=workspace_admin_headers
            ).status_code
            == 403
        )
        assert (
            client.put(
                f"/api/v0/model-providers/{provider['id']}/credential",
                headers=workspace_admin_headers,
                json={"api_key": "unauthorized-replacement-key"},
            ).status_code
            == 403
        )
        assert (
            client.patch(
                f"/api/v0/model-profiles/{profile_id}",
                headers=workspace_admin_headers,
                json={"status": "disabled"},
            ).status_code
            == 403
        )
        assert (
            client.delete(
                f"/api/v0/api-credentials/{credential_id}",
                headers=workspace_admin_headers,
            ).status_code
            == 403
        )
        assert (
            client.put(
                f"/api/v0/api-credentials/{credential_id}/rotate",
                headers=workspace_admin_headers,
            ).status_code
            == 403
        )
        owner_user_id = onboarded.json()["owner"]["id"]
        assert (
            client.post(
                f"/api/v0/users/{owner_user_id}/suspend",
                headers=workspace_admin_headers,
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/api/v0/users/{owner_user_id}/reactivate",
                headers=workspace_admin_headers,
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/v0/service-accounts",
                headers=workspace_admin_headers,
                json={"name": "Not permitted", "permissions": ["agents.run"]},
            ).status_code
            == 403
        )

        visible_bindings = client.get(
            "/api/v0/role-bindings", headers=workspace_admin_headers
        )
        assert visible_bindings.status_code == 200
        assert visible_bindings.json()
        assert all(
            binding["workspace_id"] == second_workspace_id
            for binding in visible_bindings.json()
        )
        visible_users = client.get("/api/v0/users", headers=workspace_admin_headers)
        assert visible_users.status_code == 200
        assert [user["email"] for user in visible_users.json()] == [
            "workspace-admin@scoped-admin.example"
        ]


def test_product_api_token_resolves_principal_and_enforces_assigned_permissions(
    monkeypatch,
):
    runtime = LocalPlatformRuntime()
    runtime.bootstrap()
    now = datetime.now(timezone.utc)
    runtime.principals.create(
        Principal(
            id="reader-principal",
            org_id="local-org",
            principal_type=PrincipalType.SERVICE_ACCOUNT,
            status=PrincipalStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
    )
    runtime.roles.create(
        Role(
            id="run-only-role",
            org_id="local-org",
            name="Run only",
            permissions=[Permission.AGENTS_RUN],
        )
    )
    runtime.role_bindings.create(
        RoleBinding(
            id="reader-role-binding",
            org_id="local-org",
            workspace_id="local-workspace",
            principal_id="reader-principal",
            role_id="run-only-role",
            created_at=now,
        )
    )
    runtime.workspaces.create(
        Workspace(
            id="restricted-hidden-workspace",
            org_id="local-org",
            name="Private workspace",
            status=WorkspaceStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
    )
    monkeypatch.delenv("WEAVES_API_TOKEN", raising=False)
    monkeypatch.setenv(
        "WEAVES_API_TOKENS",
        json.dumps([{"token": "read-only-secret", "principal_id": "reader-principal"}]),
    )
    client = TestClient(create_app(runtime))

    with client:
        assert client.get("/api/v0/runs").status_code == 401
        headers = {"Authorization": "Bearer read-only-secret"}
        assert client.get("/api/v0/runs", headers=headers).status_code == 200
        visible_workspaces = client.get("/api/v0/workspaces", headers=headers)
        assert [item["id"] for item in visible_workspaces.json()] == ["local-workspace"]
        assert client.get("/api/v0/agents", headers=headers).status_code == 403
        denied_workspace = client.post(
            "/api/v0/workspaces",
            headers=headers,
            json={"name": "Unauthorized workspace"},
        )
        assert denied_workspace.status_code == 403
        created = client.post(
            "/api/v0/runs",
            headers=headers,
            json={"task": "Summarize security basics"},
        )
        assert created.status_code == 201
        run_id = created.json()["run"]["run_id"]
        assert created.json()["run"]["requested_by_principal_id"] == "reader-principal"
        assert any(
            item.actor_principal_id == "reader-principal" and item.target_id == run_id
            for item in runtime.audit_events.list()
        )


def test_service_account_api_token_is_one_time_and_revocable(monkeypatch):
    monkeypatch.delenv("WEAVES_API_TOKEN", raising=False)
    monkeypatch.delenv("WEAVES_API_TOKENS", raising=False)
    runtime = LocalPlatformRuntime()
    client = TestClient(create_app(runtime))

    with client:
        created = client.post(
            "/api/v0/service-accounts",
            json={
                "name": "Run service",
                "permissions": ["agents.run"],
                "expires_in_days": 7,
            },
        )
        assert created.status_code == 201
        payload = created.json()
        token = payload["token"]
        credential_id = payload["credential"]["id"]
        assert "token_digest" not in payload["credential"]
        assert payload["credential"]["expires_at"] is not None

        service_headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/v0/runs", headers=service_headers).status_code == 200
        assert client.get("/api/v0/agents", headers=service_headers).status_code == 403
        listed = client.get("/api/v0/api-credentials").json()
        assert len(listed) == 1
        assert "token_digest" not in listed[0]

        rotated = client.put(f"/api/v0/api-credentials/{credential_id}/rotate")
        assert rotated.status_code == 200
        rotation_payload = rotated.json()
        replacement = rotation_payload["credential"]
        replacement_token = rotation_payload["token"]
        assert replacement["principal_id"] == payload["principal"]["id"]
        assert replacement["expires_at"] == payload["credential"]["expires_at"]
        assert "token_digest" not in replacement
        assert client.get("/api/v0/runs", headers=service_headers).status_code == 401
        replacement_headers = {"Authorization": f"Bearer {replacement_token}"}
        assert (
            client.get("/api/v0/runs", headers=replacement_headers).status_code == 200
        )

        replacement_id = replacement["id"]
        revoked = client.delete(f"/api/v0/api-credentials/{replacement_id}")
        assert revoked.status_code == 200
        assert revoked.json()["status"] == "revoked"
        assert (
            client.get("/api/v0/runs", headers=replacement_headers).status_code == 401
        )
        assert (
            client.delete(f"/api/v0/api-credentials/{replacement_id}").status_code
            == 200
        )
        assert (
            client.put(f"/api/v0/api-credentials/{replacement_id}/rotate").status_code
            == 409
        )


def test_execution_job_retry_requires_postgres_storage():
    runtime = LocalPlatformRuntime()
    job, _ = runtime.enqueue_agent_run("Retry requires a durable queue")
    client = TestClient(create_app(runtime))

    with client:
        response = client.post(
            f"/api/v0/execution-jobs/{job.job_id}/retry",
            headers={"Idempotency-Key": "retry-request-1"},
        )

    assert response.status_code == 503


def test_execution_job_cancel_api_exposes_requested_state():
    runtime = LocalPlatformRuntime()
    job, _ = runtime.enqueue_agent_run("Cancel through the API")
    claimed = runtime.execution_jobs.claim_next_queued(
        "api-cancel-worker", job.updated_at, job.org_id, job.workspace_id
    )
    assert claimed is not None
    client = TestClient(create_app(runtime))

    with client:
        response = client.post(f"/api/v0/execution-jobs/{job.job_id}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancel_requested"
    assert response.json()["worker_id"] == "api-cancel-worker"


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


def test_run_idempotency_replays_success_and_rejects_key_reuse():
    runtime = LocalPlatformRuntime()
    client = TestClient(create_app(runtime))
    headers = {"Idempotency-Key": "client-request-001"}

    with client:
        first = client.post(
            "/api/v0/runs",
            json={"task": "Summarize the security basics"},
            headers=headers,
        )
        assert first.status_code == 201
        assert first.json()["replayed"] is False

        repeated = client.post(
            "/api/v0/runs",
            json={"task": "Summarize the security basics"},
            headers=headers,
        )
        assert repeated.status_code == 201
        assert repeated.json()["replayed"] is True
        assert repeated.json()["run"]["run_id"] == first.json()["run"]["run_id"]
        assert len(client.get("/api/v0/runs").json()) == 1
        assert len(runtime.tool_invocations.list()) == 1

        conflict = client.post(
            "/api/v0/runs",
            json={"task": "Summarize the time off policy"},
            headers=headers,
        )
        assert conflict.status_code == 409


def test_api_runs_published_workflow_by_workflow_id():
    client = TestClient(create_app(LocalPlatformRuntime()))

    with client:
        workflows_response = client.get("/api/v0/workflows")
        assert workflows_response.status_code == 200
        workflow_id = workflows_response.json()[0]["workflow_id"]

        response = client.post(
            f"/api/v0/workflows/{workflow_id}/runs",
            json={"task": "Summarize the security basics"},
            headers={"Idempotency-Key": "workflow-run-001"},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["run"]["workflow_id"] == workflow_id
        assert body["run"]["status"] == "succeeded"
        assert body["artifacts"][0]["provenance"]
        assert body["replayed"] is False

        replayed = client.post(
            f"/api/v0/workflows/{workflow_id}/runs",
            json={"task": "Summarize the security basics"},
            headers={"Idempotency-Key": "workflow-run-001"},
        )
        assert replayed.status_code == 201
        assert replayed.json()["replayed"] is True
        assert replayed.json()["run"]["run_id"] == body["run"]["run_id"]

        newer = client.post(
            f"/api/v0/workflows/{workflow_id}/runs",
            json={"task": "Summarize the time off policy"},
        )
        assert newer.status_code == 201
        other_agent = client.post(
            "/api/v0/agents",
            json={"name": "Separate workflow agent", "instructions": "Summarize."},
        )
        assert other_agent.status_code == 201
        other_workflow = client.post(
            "/api/v0/workflows",
            json={
                "name": "Separate workflow",
                "agent_id": other_agent.json()["id"],
            },
        )
        assert other_workflow.status_code == 201
        other_run = client.post(
            f"/api/v0/workflows/{other_workflow.json()['definition']['workflow_id']}/runs",
            json={"task": "Summarize a separate process"},
        )
        assert other_run.status_code == 201

        history = client.get(f"/api/v0/workflows/{workflow_id}/runs")
        assert history.status_code == 200, history.text
        history_items = history.json()["items"]
        assert {item["run_id"] for item in history_items} == {
            newer.json()["run"]["run_id"],
            body["run"]["run_id"],
        }
        assert all(item["workflow_id"] == workflow_id for item in history_items)
        assert history_items == sorted(
            history_items,
            key=lambda item: (item["created_at"], item["run_id"]),
            reverse=True,
        )
        assert history_items[0]["agent_runs"]
        assert history_items[0]["artifacts"]
        assert history_items[0]["tool_invocations"]

        limited = client.get(
            f"/api/v0/workflows/{workflow_id}/runs", params={"limit": 1}
        )
        limited_page = limited.json()
        assert [item["run_id"] for item in limited_page["items"]] == [
            history_items[0]["run_id"]
        ]
        assert limited_page["next_cursor"]
        second_page = client.get(
            f"/api/v0/workflows/{workflow_id}/runs",
            params={"limit": 1, "cursor": limited_page["next_cursor"]},
        )
        assert [item["run_id"] for item in second_page.json()["items"]] == [
            history_items[1]["run_id"]
        ]
        assert second_page.json()["next_cursor"] is None


def test_api_rejects_unknown_workflow_run():
    client = TestClient(create_app(LocalPlatformRuntime()))

    with client:
        response = client.post(
            "/api/v0/workflows/missing-workflow/runs",
            json={"task": "Summarize the security basics"},
        )

    assert response.status_code == 404


def test_api_creates_manages_and_keeps_workflows_bound_to_agent_versions():
    client = TestClient(create_app(LocalPlatformRuntime()))

    with client:
        agent_response = client.post(
            "/api/v0/agents",
            json={"name": "Release helper", "instructions": "Review releases."},
        )
        assert agent_response.status_code == 201
        agent = agent_response.json()
        created = client.post(
            "/api/v0/workflows",
            json={
                "name": "Release risk review",
                "description": "Review an upcoming release.",
                "agent_id": agent["id"],
            },
        )
        assert created.status_code == 201
        workflow = created.json()["definition"]
        workflow_id = workflow["workflow_id"]
        first_workflow_version_id = created.json()["version"]["workflow_version_id"]
        published_agent_version_id = created.json()["version"]["agent_version_ids"][0]
        assert workflow["status"] == "active"

        generated_workflow = next(
            item
            for item in client.get("/api/v0/workflows").json()
            if item["name"] == "Run Release helper"
        )
        generated_version = client.get(
            f"/api/v0/workflows/{generated_workflow['workflow_id']}"
        ).json()["version"]
        assert generated_version["version"] == 2
        assert generated_version["agent_version_ids"] == [published_agent_version_id]

        detail = client.get(f"/api/v0/workflows/{workflow_id}")
        assert detail.status_code == 200
        assert (
            detail.json()["version"]["workflow_version_id"]
            == workflow["current_version_id"]
        )
        first_run = client.post(
            f"/api/v0/workflows/{workflow_id}/runs",
            json={"task": "Review the release notes"},
        )
        assert first_run.status_code == 201
        assert first_run.json()["run"]["workflow_id"] == workflow_id
        assert first_run.json()["run"]["workflow_version_id"] == (
            first_workflow_version_id
        )
        assert first_run.json()["agent_run"]["agent_version_id"] == (
            published_agent_version_id
        )

        updated_agent = client.patch(
            f"/api/v0/agents/{agent['id']}",
            json={"instructions": "Review releases and identify risks."},
        )
        assert updated_agent.status_code == 200
        updated_workflow = client.get(f"/api/v0/workflows/{workflow_id}").json()
        assert updated_workflow["version"]["version"] == 2
        assert updated_workflow["version"]["agent_version_ids"] == [
            updated_agent.json()["current_version"]["agent_version_id"]
        ]
        version_page = client.get(
            f"/api/v0/workflows/{workflow_id}/versions", params={"limit": 1}
        )
        assert version_page.status_code == 200, version_page.text
        assert [item["version"] for item in version_page.json()["items"]] == [2]
        assert version_page.json()["next_before_version"] == 2
        historical_page = client.get(
            f"/api/v0/workflows/{workflow_id}/versions",
            params={"limit": 1, "before_version": 2},
        )
        assert [item["version"] for item in historical_page.json()["items"]] == [1]
        assert historical_page.json()["next_before_version"] is None
        historical = client.get(
            f"/api/v0/workflows/{workflow_id}/versions/{first_workflow_version_id}"
        )
        assert historical.status_code == 200, historical.text
        assert historical.json()["agent_version_ids"] == [published_agent_version_id]
        updated_generated_version = client.get(
            f"/api/v0/workflows/{generated_workflow['workflow_id']}"
        ).json()["version"]
        assert updated_generated_version["version"] == 3
        assert updated_generated_version["agent_version_ids"] == [
            updated_agent.json()["current_version"]["agent_version_id"]
        ]
        cross_workflow = client.get(
            f"/api/v0/workflows/{workflow_id}/versions/"
            f"{updated_generated_version['workflow_version_id']}"
        )
        assert cross_workflow.status_code == 404

        archived = client.patch(
            f"/api/v0/workflows/{workflow_id}", json={"status": "archived"}
        )
        assert archived.status_code == 200
        unavailable = client.post(
            f"/api/v0/workflows/{workflow_id}/runs",
            json={"task": "Review the next release"},
        )
        assert unavailable.status_code == 422

        reactivated = client.patch(
            f"/api/v0/workflows/{workflow_id}", json={"status": "active"}
        )
        assert reactivated.status_code == 200
        second_run = client.post(
            f"/api/v0/workflows/{workflow_id}/runs",
            json={"task": "Review the next release"},
        )
        assert second_run.status_code == 201
        assert second_run.json()["run"]["status"] == "succeeded"


def test_api_runs_linear_multi_agent_workflow_and_replays_all_steps():
    runtime = LocalPlatformRuntime()
    captured_requests = []

    class CapturingModel:
        def complete(self, request, binding):
            captured_requests.append(request)
            step = len(captured_requests)
            return ModelResponse(
                provider_id=binding.provider.id,
                model_id=binding.profile.model,
                content=f"Step {step} output",
                usage=ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2),
            )

    runtime.model_adapters[ModelProviderType.LOCAL] = CapturingModel()
    runtime.model_gateway = ModelGateway(runtime.model_adapters)
    client = TestClient(create_app(runtime))

    with client:
        agent_ids = []
        for name in ("Planner", "Reviewer"):
            created_agent = client.post(
                "/api/v0/agents",
                json={"name": name, "instructions": f"Act as the {name.lower()}."},
            )
            assert created_agent.status_code == 201
            agent_ids.append(created_agent.json()["id"])

        created_workflow = client.post(
            "/api/v0/workflows",
            json={"name": "Plan then review", "agent_ids": agent_ids},
        )
        assert created_workflow.status_code == 201
        workflow_id = created_workflow.json()["definition"]["workflow_id"]
        version = created_workflow.json()["version"]
        assert version["handler_key"] == "agent.sequence"
        assert len(version["agent_version_ids"]) == 2

        headers = {"Idempotency-Key": "linear-workflow-001"}
        response = client.post(
            f"/api/v0/workflows/{workflow_id}/runs",
            json={"task": "Assess this release candidate"},
            headers=headers,
        )
        assert response.status_code == 201
        result = response.json()
        run_id = result["run"]["run_id"]
        assert result["run"]["status"] == "succeeded"
        assert result["run"]["workflow_id"] == workflow_id
        assert [item["agent_id"] for item in result["agent_runs"]] == agent_ids
        assert [
            item["input_summary"]["workflow_step_index"]
            for item in result["agent_runs"]
        ] == [0, 1]
        assert len(result["artifacts"]) == 2
        assert all(item["run_id"] == run_id for item in result["agent_runs"])
        assert all(item["run_id"] == run_id for item in result["artifacts"])
        assert any(
            item["source_ref"] == result["artifacts"][0]["artifact_id"]
            for item in result["artifacts"][1]["provenance"]
        )
        assert "Step 1 output" in captured_requests[1].messages[-1].content
        assert "untrusted reference data" in captured_requests[1].messages[0].content

        detail = client.get(f"/api/v0/runs/{run_id}")
        assert len(detail.json()["agent_runs"]) == 2
        assert len(detail.json()["artifacts"]) == 2

        replay = client.post(
            f"/api/v0/workflows/{workflow_id}/runs",
            json={"task": "Assess this release candidate"},
            headers=headers,
        )
        assert replay.status_code == 201
        assert replay.json()["replayed"] is True
        assert replay.json()["run"]["run_id"] == run_id
        assert len(replay.json()["agent_runs"]) == 2
        assert len(captured_requests) == 2

        updated_agent = client.patch(
            f"/api/v0/agents/{agent_ids[0]}",
            json={"instructions": "Plan the release review with clear criteria."},
        )
        assert updated_agent.status_code == 200
        current_workflow = client.get(f"/api/v0/workflows/{workflow_id}").json()
        assert current_workflow["version"]["version"] == 2
        assert current_workflow["version"]["agent_version_ids"] == [
            updated_agent.json()["current_version"]["agent_version_id"],
            version["agent_version_ids"][1],
        ]
        after_update = client.post(
            f"/api/v0/workflows/{workflow_id}/runs",
            json={"task": "Assess this release candidate"},
            headers={"Idempotency-Key": "linear-workflow-002"},
        )
        assert after_update.status_code == 201
        assert [
            item["agent_id"] for item in after_update.json()["agent_runs"]
        ] == agent_ids
        assert len(captured_requests) == 4


def test_api_replaces_workflow_steps_by_publishing_new_versions():
    client = TestClient(create_app(LocalPlatformRuntime()))
    with client:
        agent_ids = []
        for name in ("Initial", "Reviewer", "Escalation"):
            response = client.post(
                "/api/v0/agents",
                json={"name": name, "instructions": f"Act as {name}."},
            )
            assert response.status_code == 201, response.text
            agent_ids.append(response.json()["id"])

        first = client.post(
            "/api/v0/workflows",
            json={"name": "Initial review", "agent_id": agent_ids[0]},
        )
        second = client.post(
            "/api/v0/workflows",
            json={"name": "Escalation review", "agent_id": agent_ids[2]},
        )
        assert first.status_code == second.status_code == 201
        first_id = first.json()["definition"]["workflow_id"]
        second_id = second.json()["definition"]["workflow_id"]
        previous_first_version = first.json()["version"]["workflow_version_id"]
        previous_second_version = second.json()["version"]["workflow_version_id"]

        replaced = client.put(
            f"/api/v0/workflows/{first_id}/steps",
            json={"agent_ids": [agent_ids[1], agent_ids[2]]},
        )
        assert replaced.status_code == 200, replaced.text
        current = replaced.json()["version"]
        assert current["version"] == 2
        assert current["handler_key"] == "agent.sequence"
        assert [
            client.get(f"/api/v0/agents/{agent_id}").json()["current_version"][
                "agent_version_id"
            ]
            for agent_id in agent_ids[1:]
        ] == current["agent_version_ids"]

        # Publishing a new agent version also advances other workflows that
        # referenced the prior version, without changing their step order.
        changed_second = client.get(f"/api/v0/workflows/{second_id}").json()
        assert changed_second["version"]["version"] == 2
        assert changed_second["version"]["workflow_version_id"] != (
            previous_second_version
        )
        assert changed_second["version"]["agent_version_ids"] == [
            current["agent_version_ids"][1]
        ]
        assert previous_first_version != current["workflow_version_id"]

        run = client.post(
            f"/api/v0/workflows/{first_id}/runs",
            json={"task": "Review this operational change"},
        )
        assert run.status_code == 201, run.text
        assert [item["agent_id"] for item in run.json()["agent_runs"]] == agent_ids[1:]


def test_api_publishes_and_executes_structured_workflow_conditions(monkeypatch):
    runtime = LocalPlatformRuntime()
    responses = iter(['{"route":"escalate"}', "Escalation complete", "Final summary"])

    def complete(request, binding):
        return ModelResponse(
            provider_id=binding.provider.id,
            model_id=binding.profile.model,
            content=next(responses),
            usage=ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2),
        )

    monkeypatch.setattr(runtime.model, "complete", complete)
    client = TestClient(create_app(runtime))
    with client:
        agent_ids = []
        for name in (
            "API Router",
            "Conditional Reviewer",
            "Conditional Escalation",
            "API Summary",
        ):
            request = {
                "name": name,
                "instructions": f"Act as {name}.",
                "allowed_capability_ids": [],
            }
            if name == "API Router":
                request["output_schema"] = {
                    "type": "object",
                    "properties": {"route": {"type": "string"}},
                    "required": ["route"],
                    "additionalProperties": False,
                }
            created = client.post("/api/v0/agents", json=request)
            assert created.status_code == 201, created.text
            agent_ids.append(created.json()["id"])

        created_workflow = client.post(
            "/api/v0/workflows",
            json={"name": "Conditional API workflow", "agent_ids": agent_ids},
        )
        assert created_workflow.status_code == 201, created_workflow.text
        workflow_id = created_workflow.json()["definition"]["workflow_id"]
        published = client.put(
            f"/api/v0/workflows/{workflow_id}/steps",
            json={
                "agent_ids": agent_ids,
                "step_conditions": [
                    {
                        "source_agent_id": agent_ids[0],
                        "target_agent_id": agent_ids[1],
                        "json_pointer": "/route",
                        "operator": "equals",
                        "expected_value": "review",
                    },
                    {
                        "source_agent_id": agent_ids[0],
                        "target_agent_id": agent_ids[2],
                        "json_pointer": "/route",
                        "operator": "equals",
                        "expected_value": "escalate",
                    },
                ],
                "step_dependencies": [
                    {
                        "target_agent_id": agent_ids[1],
                        "depends_on_agent_ids": [agent_ids[0]],
                    },
                    {
                        "target_agent_id": agent_ids[2],
                        "depends_on_agent_ids": [agent_ids[0]],
                    },
                    {
                        "target_agent_id": agent_ids[3],
                        "depends_on_agent_ids": agent_ids[1:3],
                        "join_policy": "any",
                    },
                ],
            },
        )
        assert published.status_code == 200, published.text
        assert [
            condition["target_agent_id"]
            for condition in published.json()["version"]["step_conditions"]
        ] == agent_ids[1:3]
        assert (
            published.json()["version"]["step_dependencies"][2]["join_policy"] == "any"
        )

        executed = client.post(
            f"/api/v0/workflows/{workflow_id}/runs",
            json={"task": "Route this request"},
        )
        assert executed.status_code == 201, executed.text
        assert [item["agent_id"] for item in executed.json()["agent_runs"]] == [
            agent_ids[0],
            agent_ids[2],
            agent_ids[3],
        ]
        assert executed.json()["agent_runs"][2]["input_summary"][
            "previous_step_artifact_ids"
        ] == [executed.json()["artifacts"][1]["artifact_id"]]
        skipped = [
            event
            for event in client.get("/api/v0/audit-events").json()
            if event["action"] == "workflow.step.skipped"
            and event["target_id"] == agent_ids[1]
        ]
        assert len(skipped) == 1
        current_version_id = published.json()["version"]["workflow_version_id"]
        invalid = client.put(
            f"/api/v0/workflows/{workflow_id}/steps",
            json={
                "agent_ids": agent_ids,
                "step_conditions": [
                    {
                        "source_agent_id": agent_ids[1],
                        "target_agent_id": agent_ids[0],
                        "json_pointer": "/route",
                        "operator": "exists",
                    }
                ],
            },
        )
        assert invalid.status_code == 422
        unchanged = client.get(f"/api/v0/workflows/{workflow_id}").json()
        assert unchanged["version"]["workflow_version_id"] == current_version_id
        invalid_graph = client.put(
            f"/api/v0/workflows/{workflow_id}/steps",
            json={
                "agent_ids": agent_ids,
                "step_dependencies": [
                    {
                        "target_agent_id": agent_ids[1],
                        "depends_on_agent_ids": [agent_ids[2]],
                    },
                    {
                        "target_agent_id": agent_ids[2],
                        "depends_on_agent_ids": [agent_ids[0]],
                    },
                    {
                        "target_agent_id": agent_ids[3],
                        "depends_on_agent_ids": agent_ids[1:3],
                        "join_policy": "any",
                    },
                ],
            },
        )
        assert invalid_graph.status_code == 422
        assert (
            client.get(f"/api/v0/workflows/{workflow_id}").json()["version"][
                "workflow_version_id"
            ]
            == current_version_id
        )


def test_api_executes_versioned_parallel_workflow_steps(monkeypatch):
    runtime = LocalPlatformRuntime()
    branch_barrier = Barrier(2)
    call_lock = Lock()
    call_count = 0

    def complete(request, binding):
        nonlocal call_count
        with call_lock:
            call_count += 1
            current_call = call_count
        if current_call in {2, 3}:
            branch_barrier.wait(timeout=5)
        content = {
            1: "Root completed",
            2: "Branch completed",
            3: "Branch completed",
            4: "Joined result",
        }[current_call]
        return ModelResponse(
            provider_id=binding.provider.id,
            model_id=binding.profile.model,
            content=content,
            usage=ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2),
        )

    monkeypatch.setattr(runtime.model, "complete", complete)
    client = TestClient(create_app(runtime))
    with client:
        agent_ids = []
        for name in ("Parallel root", "Parallel reviewer", "Parallel risk", "Join"):
            response = client.post(
                "/api/v0/agents",
                json={
                    "name": name,
                    "instructions": f"Complete the {name} step.",
                    "allowed_capability_ids": [],
                },
            )
            assert response.status_code == 201, response.text
            agent_ids.append(response.json()["id"])

        workflow_response = client.post(
            "/api/v0/workflows",
            json={"name": "Parallel workflow", "agent_ids": agent_ids},
        )
        assert workflow_response.status_code == 201, workflow_response.text
        workflow_id = workflow_response.json()["definition"]["workflow_id"]
        published = client.put(
            f"/api/v0/workflows/{workflow_id}/steps",
            json={
                "agent_ids": agent_ids,
                "parallel_groups": [{"agent_ids": agent_ids[1:3]}],
                "step_dependencies": [
                    {
                        "target_agent_id": agent_ids[2],
                        "depends_on_agent_ids": [agent_ids[0]],
                    },
                    {
                        "target_agent_id": agent_ids[3],
                        "depends_on_agent_ids": agent_ids[1:3],
                        "join_policy": "all",
                    },
                ],
            },
        )
        assert published.status_code == 200, published.text
        assert published.json()["version"]["parallel_groups"] == [
            {"schema_version": 1, "agent_ids": agent_ids[1:3]}
        ]
        root_update = client.patch(
            f"/api/v0/agents/{agent_ids[0]}",
            json={"instructions": "Complete the intake step carefully."},
        )
        assert root_update.status_code == 200, root_update.text
        current_version = client.get(f"/api/v0/workflows/{workflow_id}").json()[
            "version"
        ]
        assert (
            current_version["parallel_groups"]
            == published.json()["version"]["parallel_groups"]
        )
        assert (
            current_version["step_dependencies"]
            == published.json()["version"]["step_dependencies"]
        )

        executed = client.post(
            f"/api/v0/workflows/{workflow_id}/runs",
            json={"task": "Review this release in parallel"},
        )
        assert executed.status_code == 201, executed.text
        body = executed.json()
        assert body["run"]["status"] == "succeeded"
        assert [item["agent_id"] for item in body["agent_runs"]] == agent_ids
        assert call_count == 4
        root_artifact_id = body["artifacts"][0]["artifact_id"]
        assert (
            body["agent_runs"][1]["input_summary"]["previous_step_artifact_ids"] == []
        )
        assert body["agent_runs"][2]["input_summary"]["previous_step_artifact_ids"] == [
            root_artifact_id
        ]
        assert body["agent_runs"][3]["input_summary"]["previous_step_artifact_ids"] == [
            *[item["artifact_id"] for item in body["artifacts"][1:3]],
        ]
        invalid = client.put(
            f"/api/v0/workflows/{workflow_id}/steps",
            json={
                "agent_ids": agent_ids,
                "parallel_groups": [{"agent_ids": agent_ids[:2]}],
            },
        )
        assert invalid.status_code == 422
        assert (
            client.get(f"/api/v0/workflows/{workflow_id}").json()["version"][
                "workflow_version_id"
            ]
            == current_version["workflow_version_id"]
        )


def test_api_requires_workflow_management_permission(monkeypatch):
    runtime = LocalPlatformRuntime()
    runtime.bootstrap()
    now = datetime.now(timezone.utc)
    runtime.principals.create(
        Principal(
            id="workflow-runner",
            org_id="local-org",
            principal_type=PrincipalType.SERVICE_ACCOUNT,
            status=PrincipalStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
    )
    runtime.roles.create(
        Role(
            id="workflow-runner-role",
            org_id="local-org",
            name="Workflow runner",
            permissions=[Permission.WORKFLOWS_RUN],
        )
    )
    runtime.role_bindings.create(
        RoleBinding(
            id="workflow-runner-binding",
            org_id="local-org",
            workspace_id="local-workspace",
            principal_id="workflow-runner",
            role_id="workflow-runner-role",
            created_at=now,
        )
    )
    monkeypatch.setenv(
        "WEAVES_API_TOKENS",
        json.dumps(
            [{"token": "workflow-runner-token", "principal_id": "workflow-runner"}]
        ),
    )
    monkeypatch.delenv("WEAVES_API_TOKEN", raising=False)
    client = TestClient(create_app(runtime))

    with client:
        response = client.post(
            "/api/v0/workflows",
            json={
                "name": "Forbidden workflow",
                "agent_id": "local-assistant",
            },
            headers={"Authorization": "Bearer workflow-runner-token"},
        )

    assert response.status_code == 403


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
        queued = client.post(
            "/api/v0/execution-jobs", json={"task": "Run a durable job"}
        )
        assert queued.status_code == 503
        queued_workflow = client.post(
            "/api/v0/execution-jobs",
            json={
                "task": "Run a durable workflow",
                "workflow_id": "local-assistant-workflow",
            },
        )
        assert queued_workflow.status_code == 503
        ambiguous = client.post(
            "/api/v0/execution-jobs",
            json={
                "task": "Run a durable job",
                "agent_id": "local-assistant",
                "workflow_id": "local-assistant-workflow",
            },
        )
        assert ambiguous.status_code == 422


def test_product_api_manages_memory_and_agent_scope_policy():
    runtime = LocalPlatformRuntime()
    client = TestClient(create_app(runtime))

    with client:
        created_memory = client.post(
            "/api/v0/memory-items",
            json={
                "title": "Release owner",
                "text": "The release owner reviews the release checklist.",
                "scope": "organization",
            },
        )
        assert created_memory.status_code == 201
        memory_id = created_memory.json()["memory_id"]
        assert client.get("/api/v0/memory-items").json()[0]["scope"] == "organization"

        agent_response = client.post(
            "/api/v0/agents",
            json={
                "name": "Org memory helper",
                "instructions": "Answer from approved organization memory.",
                "memory_scopes": ["organization"],
            },
        )
        assert agent_response.status_code == 201
        policy = agent_response.json()["current_version"]["memory_policy"]
        assert policy["allowed_scopes"] == ["organization"]

        run = client.post(
            "/api/v0/runs",
            json={
                "agent_id": agent_response.json()["id"],
                "task": "Who reviews the release checklist?",
            },
        )
        assert run.status_code == 201
        agent_run = run.json()["agent_run"]
        assert f"memory:{memory_id}" in agent_run["output_summary"]["source_ids"]
        assert "Retrieved sources:" in agent_run["output_summary"]["response"]
        assert any(
            item["source_type"] == "memory.item"
            for item in run.json()["artifacts"][0]["provenance"]
        )

        deleted = client.delete(f"/api/v0/memory-items/{memory_id}")
        assert deleted.status_code == 204
        assert client.get("/api/v0/memory-items").json() == []


def test_memory_management_is_limited_to_organization_or_selected_workspace():
    client = TestClient(create_app(LocalPlatformRuntime()))

    with client:
        onboarded = client.post(
            "/api/v0/onboarding/organizations",
            json={
                "name": "Memory Scope Org",
                "owner_email": "owner@memory-scope.example",
                "owner_display_name": "Memory Scope Owner",
            },
        )
        assert onboarded.status_code == 201
        owner_headers = {"Authorization": f"Bearer {onboarded.json()['access_token']}"}
        first_workspace_id = onboarded.json()["workspace"]["id"]
        second_workspace = client.post(
            "/api/v0/workspaces",
            headers=owner_headers,
            json={"name": "Second memory workspace"},
        )
        assert second_workspace.status_code == 201
        second_workspace_id = second_workspace.json()["id"]

        first_user = client.post(
            "/api/v0/users",
            headers={**owner_headers, "X-Workspace-ID": first_workspace_id},
            json={
                "email": "first@memory-scope.example",
                "display_name": "First Workspace Editor",
                "permissions": ["plugins.manage"],
            },
        )
        second_user = client.post(
            "/api/v0/users",
            headers={**owner_headers, "X-Workspace-ID": second_workspace_id},
            json={
                "email": "second@memory-scope.example",
                "display_name": "Second Workspace Editor",
                "permissions": ["plugins.manage"],
            },
        )
        assert first_user.status_code == second_user.status_code == 201
        first_headers = {"Authorization": f"Bearer {first_user.json()['access_token']}"}
        second_headers = {
            "Authorization": f"Bearer {second_user.json()['access_token']}"
        }

        first_memory = client.post(
            "/api/v0/memory-items",
            headers=first_headers,
            json={
                "title": "First space note",
                "text": "First workspace detail.",
                "retention_class": "regulated",
            },
        )
        second_memory = client.post(
            "/api/v0/memory-items",
            headers=second_headers,
            json={"title": "Second space note", "text": "Second workspace detail."},
        )
        assert first_memory.status_code == second_memory.status_code == 201
        assert first_memory.json()["retention_class"] == "regulated"

        shared_memory = client.post(
            "/api/v0/memory-items",
            headers=owner_headers,
            json={
                "title": "Shared organization note",
                "text": "Organization-wide detail.",
                "scope": "organization",
            },
        )
        assert shared_memory.status_code == 201

        first_visible = client.get(
            "/api/v0/memory-items",
            headers={
                **first_headers,
                "X-Workspace-ID": first_workspace_id,
            },
        )
        first_visible_ids = {item["memory_id"] for item in first_visible.json()}
        assert first_visible_ids == {
            first_memory.json()["memory_id"],
            shared_memory.json()["memory_id"],
        }
        assert (
            client.delete(
                f"/api/v0/memory-items/{second_memory.json()['memory_id']}",
                headers=first_headers,
            ).status_code
            == 404
        )
        denied_org_memory = client.post(
            "/api/v0/memory-items",
            headers=first_headers,
            json={
                "title": "Unscoped note",
                "text": "Workspace role must not publish this.",
                "scope": "organization",
            },
        )
        assert denied_org_memory.status_code == 403
        invalid_ephemeral = client.post(
            "/api/v0/memory-items",
            headers={**owner_headers, "X-Workspace-ID": first_workspace_id},
            json={
                "title": "Unbounded ephemeral note",
                "text": "Expiry must be explicit.",
                "retention_class": "ephemeral",
            },
        )
        assert invalid_ephemeral.status_code == 422
        naive_expiry = client.post(
            "/api/v0/memory-items",
            headers={**owner_headers, "X-Workspace-ID": first_workspace_id},
            json={
                "title": "Timezone-less expiry",
                "text": "Expiry must include a timezone.",
                "retention_class": "ephemeral",
                "expires_at": "2030-01-01T00:00:00",
            },
        )
        assert naive_expiry.status_code == 422


def test_model_profile_rates_produce_per_run_cost_estimates():
    client = TestClient(create_app(LocalPlatformRuntime()))

    with client:
        agent = client.post(
            "/api/v0/agents",
            json={
                "name": "Costed assistant",
                "instructions": "Answer with the available handbook context.",
            },
        ).json()
        profile_id = agent["current_version"]["model_profile_id"]
        configured = client.patch(
            f"/api/v0/model-profiles/{profile_id}",
            json={
                "input_cost_per_million_tokens_usd": "2.5",
                "output_cost_per_million_tokens_usd": "10",
            },
        )
        assert configured.status_code == 200

        result = client.post(
            "/api/v0/runs",
            json={"agent_id": agent["id"], "task": "Summarize security basics"},
        )
        assert result.status_code == 201
        agent_run = result.json()["agent_run"]
        expected_cost = (
            Decimal(agent_run["input_tokens"]) * Decimal("2.5")
            + Decimal(agent_run["output_tokens"]) * Decimal("10")
        ) / Decimal(1_000_000)
        assert Decimal(agent_run["estimated_cost_usd"]) == expected_cost


def test_model_profile_cost_budget_records_usage_and_fails_over_budget_run():
    client = TestClient(create_app(LocalPlatformRuntime()))

    with client:
        agent = client.post(
            "/api/v0/agents",
            json={
                "name": "Budgeted assistant",
                "instructions": "Be concise.",
                "max_run_cost_usd": "0.000001",
            },
        ).json()
        profile_id = agent["current_version"]["model_profile_id"]
        configured = client.patch(
            f"/api/v0/model-profiles/{profile_id}",
            json={
                "cost_budget_usd": "0.000001",
                "input_cost_per_million_tokens_usd": "1",
                "output_cost_per_million_tokens_usd": "1",
            },
        )
        assert configured.status_code == 200

        result = client.post(
            "/api/v0/runs",
            json={"agent_id": agent["id"], "task": "Explain the knowledge base"},
        )
        assert result.status_code == 422
        assert "provider request already completed" in result.json()["detail"]

        run = client.get("/api/v0/runs").json()[0]
        assert run["status"] == "failed"
        agent_run = client.get(f"/api/v0/runs/{run['run_id']}").json()["agent_runs"][0]
        assert agent_run["status"] == "failed"
        assert agent_run["input_tokens"] > 0
        assert agent_run["output_tokens"] > 0
        assert Decimal(agent_run["estimated_cost_usd"]) > Decimal("0.000001")


def test_cost_budget_requires_configured_input_and_output_rates():
    client = TestClient(create_app(LocalPlatformRuntime()))

    with client:
        agent = client.post(
            "/api/v0/agents",
            json={"name": "Unpriced assistant", "instructions": "Be concise."},
        ).json()
        profile_id = agent["current_version"]["model_profile_id"]
        configured = client.patch(
            f"/api/v0/model-profiles/{profile_id}",
            json={"cost_budget_usd": "1"},
        )
        assert configured.status_code == 200

        result = client.post(
            "/api/v0/runs",
            json={"agent_id": agent["id"], "task": "Explain the knowledge base"},
        )
        assert result.status_code == 422
        assert "require input and output token rates" in result.json()["detail"]
        assert client.get("/api/v0/runs").json() == []


def test_thread_and_workflow_memory_do_not_cross_execution_scopes():
    client = TestClient(create_app(LocalPlatformRuntime()))

    with client:
        agent = client.post(
            "/api/v0/agents",
            json={
                "name": "Scoped memory helper",
                "instructions": "Use the matching conversation and workflow memory.",
                "memory_scopes": ["thread", "workflow"],
            },
        )
        assert agent.status_code == 201
        agent_id = agent.json()["id"]
        current_version = agent.json()["current_version"]
        workflow_id = current_version["allowed_workflow_ids"][0]
        workflow_memory = client.post(
            "/api/v0/memory-items",
            json={
                "title": "Release calendar",
                "text": "The release checklist owner is Maya.",
                "scope": "workflow",
                "scope_ref": workflow_id,
            },
        )
        assert workflow_memory.status_code == 201

        first_thread = client.post(
            "/api/v0/threads",
            json={"agent_id": agent_id, "title": "Release conversation A"},
        )
        second_thread = client.post(
            "/api/v0/threads",
            json={"agent_id": agent_id, "title": "Release conversation B"},
        )
        assert first_thread.status_code == second_thread.status_code == 201
        thread_memory = client.post(
            "/api/v0/memory-items",
            json={
                "title": "Conversation decision",
                "text": "Conversation A approved the blue release window.",
                "scope": "thread",
                "scope_ref": first_thread.json()["thread_id"],
            },
        )
        assert thread_memory.status_code == 201

        first_run = client.post(
            "/api/v0/runs",
            json={
                "task": "Who owns the release checklist and what is the blue window?",
                "thread_id": first_thread.json()["thread_id"],
            },
        )
        second_run = client.post(
            "/api/v0/runs",
            json={
                "task": "Who owns the release checklist and what is the blue window?",
                "thread_id": second_thread.json()["thread_id"],
            },
        )
        assert first_run.status_code == second_run.status_code == 201
        first_sources = first_run.json()["agent_run"]["output_summary"]["source_ids"]
        second_sources = second_run.json()["agent_run"]["output_summary"]["source_ids"]
        assert f"memory:{thread_memory.json()['memory_id']}" in first_sources
        assert f"memory:{workflow_memory.json()['memory_id']}" in first_sources
        assert f"memory:{thread_memory.json()['memory_id']}" not in second_sources
        assert f"memory:{workflow_memory.json()['memory_id']}" in second_sources
        assert (
            first_run.json()["run"]["trigger_ref"] == first_thread.json()["thread_id"]
        )
        thread_runs = client.get(
            f"/api/v0/threads/{first_thread.json()['thread_id']}/runs"
        )
        assert thread_runs.status_code == 200
        assert len(thread_runs.json()) == 1
        assert thread_runs.json()[0]["run_id"] == first_run.json()["run"]["run_id"]

        closed = client.patch(
            f"/api/v0/threads/{first_thread.json()['thread_id']}",
            json={"status": "closed"},
        )
        assert closed.status_code == 200
        rejected = client.post(
            "/api/v0/runs",
            json={
                "task": "Do not continue a closed conversation.",
                "thread_id": first_thread.json()["thread_id"],
            },
        )
        assert rejected.status_code == 422


def test_product_api_approves_jira_comment_before_sending_it():
    posted_comments = []
    deny_healthcheck = False

    def respond(request):
        if request.url.path.endswith("/project/WEAVES"):
            if deny_healthcheck:
                return httpx.Response(401, json={"error": "unauthorized"})
            return httpx.Response(200, json={"key": "WEAVES"})
        if request.url.path.endswith("/search/jql"):
            return httpx.Response(200, json={"issues": []})
        if request.url.path.endswith("/comment"):
            posted_comments.append(request)
            return httpx.Response(201, json={"id": "comment-77"})
        raise AssertionError(f"unexpected Jira request: {request.url}")

    runtime = LocalPlatformRuntime()
    jira_client = httpx.Client(transport=httpx.MockTransport(respond))
    runtime.jira_plugin._client = jira_client
    client = TestClient(create_app(runtime))
    try:
        with client:
            installation = client.post(
                "/api/v0/plugin-installations",
                json={
                    "plugin_id": "jira",
                    "display_name": "Engineering Jira",
                    "api_token": "jira-test-token",
                    "site_url": "https://example.atlassian.net",
                    "email": "dev@example.com",
                    "project_keys": ["WEAVES"],
                },
            )
            assert installation.status_code == 201
            installation_id = installation.json()["plugin_installation_id"]
            assert "auth_ref" not in installation.json()

            healthcheck = client.post(
                f"/api/v0/plugin-installations/{installation_id}/healthcheck"
            )
            assert healthcheck.status_code == 200
            assert healthcheck.json()["project"] == "WEAVES"
            assert len(posted_comments) == 0

            old_secret_ref = runtime.installations.get(installation_id).auth_ref
            deny_healthcheck = True
            invalid_rotation = client.put(
                f"/api/v0/plugin-installations/{installation_id}/credential",
                json={"api_key": "invalid-test-token"},
            )
            assert invalid_rotation.status_code == 200
            assert "auth_ref" not in invalid_rotation.json()
            failed_healthcheck = client.post(
                f"/api/v0/plugin-installations/{installation_id}/healthcheck"
            )
            assert failed_healthcheck.status_code == 502
            failed_installations = client.get("/api/v0/plugin-installations")
            failed_installation = next(
                item
                for item in failed_installations.json()
                if item["plugin_installation_id"] == installation_id
            )
            assert failed_installation["status"] == "error"
            assert failed_installation["last_healthcheck_at"] is not None
            assert old_secret_ref is not None
            with pytest.raises(KeyError):
                runtime.secret_store.get(old_secret_ref)

            deny_healthcheck = False
            recovered_rotation = client.put(
                f"/api/v0/plugin-installations/{installation_id}/credential",
                json={"api_key": "jira-test-token"},
            )
            assert recovered_rotation.status_code == 200
            recovered_healthcheck = client.post(
                f"/api/v0/plugin-installations/{installation_id}/healthcheck"
            )
            assert recovered_healthcheck.status_code == 200
            assert recovered_healthcheck.json()["status"] == "ok"
            recovered_installations = client.get("/api/v0/plugin-installations")
            assert (
                next(
                    item
                    for item in recovered_installations.json()
                    if item["plugin_installation_id"] == installation_id
                )["status"]
                == "active"
            )

            policies = client.get("/api/v0/approval-policies")
            assert policies.status_code == 200
            policy_id = policies.json()[0]["approval_policy_id"]
            strict_policy = client.patch(
                f"/api/v0/approval-policies/{policy_id}",
                json={"allow_self_approval": False},
            )
            assert strict_policy.status_code == 200

            enabled = client.patch(
                f"/api/v0/plugin-installations/{installation_id}",
                json={
                    "enabled_capability_ids": [
                        "jira.issues.search",
                        "jira.issues.comment",
                    ]
                },
            )
            assert enabled.status_code == 200
            agent = client.post(
                "/api/v0/agents",
                json={
                    "name": "Jira assistant",
                    "instructions": "Use context and suggest next steps.",
                    "allowed_capability_ids": [
                        "knowledge.search",
                        "jira.issues.comment",
                    ],
                },
            )
            assert agent.status_code == 201
            run = client.post(
                "/api/v0/runs",
                json={
                    "agent_id": agent.json()["id"],
                    "task": "Review release readiness",
                },
            )
            assert run.status_code == 201
            run_id = run.json()["run"]["run_id"]

            proposal = client.post(
                f"/api/v0/runs/{run_id}/actions",
                json={
                    "capability_id": "jira.issues.comment",
                    "issue_key": "WEAVES-17",
                    "comment": "The release checklist is ready.",
                },
            )
            assert proposal.status_code == 201
            approval_id = proposal.json()["approval"]["approval_request_id"]
            assert proposal.json()["tool_invocation"]["status"] == "awaiting_approval"
            assert len(posted_comments) == 0

            pending = client.get("/api/v0/approvals?status=pending")
            assert pending.status_code == 200
            assert pending.json()[0]["approval_request_id"] == approval_id

            self_decision = client.post(
                f"/api/v0/approvals/{approval_id}/decision",
                json={"approved": True, "decision_comment": "Self approval denied."},
            )
            assert self_decision.status_code == 403
            assert len(posted_comments) == 0

            reviewer = client.post(
                "/api/v0/users",
                json={
                    "email": "reviewer@example.com",
                    "display_name": "Independent Reviewer",
                    "permissions": ["actions.approve"],
                },
            )
            assert reviewer.status_code == 201, reviewer.text
            reviewer_headers = {
                "Authorization": f"Bearer {reviewer.json()['access_token']}"
            }

            decision = client.post(
                f"/api/v0/approvals/{approval_id}/decision",
                headers=reviewer_headers,
                json={"approved": True, "decision_comment": "Looks good."},
            )
            assert decision.status_code == 200
            assert decision.json()["approval"]["status"] == "approved"
            assert decision.json()["tool_invocation"]["status"] == "succeeded"
            assert len(posted_comments) == 1
    finally:
        jira_client.close()


def test_legacy_model_refresh_selects_a_configured_provider(monkeypatch):
    runtime = LocalPlatformRuntime()
    runtime.create_model_provider(
        provider_type=ModelProviderType.ANTHROPIC,
        display_name="Anthropic test provider",
        api_key="anthropic-test-key",
        initial_model="claude-initial",
    )
    anthropic_adapter = runtime.model_adapters[ModelProviderType.ANTHROPIC]
    monkeypatch.setattr(
        anthropic_adapter,
        "list_models",
        lambda _provider: [{"id": "claude-discovered", "owned_by": "anthropic"}],
    )
    client = TestClient(create_app(runtime))

    with client:
        refreshed = client.post("/api/v0/models/refresh")
        assert refreshed.status_code == 200, refreshed.text
        assert [profile["model"] for profile in refreshed.json()] == [
            "claude-discovered"
        ]

        gemini = runtime.create_model_provider(
            provider_type=ModelProviderType.GEMINI,
            display_name="Gemini test provider",
            api_key="gemini-test-key",
            initial_model="gemini-initial",
        )
        gemini_adapter = runtime.model_adapters[ModelProviderType.GEMINI]
        monkeypatch.setattr(
            gemini_adapter,
            "list_models",
            lambda _provider: [{"id": "gemini-discovered", "owned_by": "google"}],
        )

        ambiguous = client.post("/api/v0/models/refresh")
        assert ambiguous.status_code == 422
        assert "provider_id is required" in ambiguous.json()["detail"]

        selected = client.post(
            "/api/v0/models/refresh", params={"provider_id": gemini.id}
        )
        assert selected.status_code == 200, selected.text
        assert [profile["model"] for profile in selected.json()] == [
            "gemini-discovered"
        ]

        disabled_provider = runtime.providers.get(gemini.id)
        runtime.providers.put(
            disabled_provider.model_copy(
                update={"status": ModelProviderStatus.DISABLED}
            )
        )
        disabled_refresh = client.post(
            "/api/v0/models/refresh", params={"provider_id": gemini.id}
        )
        assert disabled_refresh.status_code == 409
        assert disabled_refresh.json()["detail"] == "Model provider is disabled"

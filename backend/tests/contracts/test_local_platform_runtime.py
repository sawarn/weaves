from datetime import datetime, timezone

import pytest

from weaves.product.contracts.v1 import (
    Principal,
    PrincipalStatus,
    PrincipalType,
    RunStatus,
)
from weaves.product.runtime import LocalPlatformRuntime, PluginGatewayError


def test_local_runtime_bootstraps_and_completes_a_scoped_mock_run():
    runtime = LocalPlatformRuntime()

    runtime.bootstrap()
    result = runtime.run_agent("Summarize our security basics")

    assert result.run.status is RunStatus.SUCCEEDED
    assert result.agent_run.agent_version_id == "local-assistant-v1"
    assert result.agent_run.resolved_provider_id == "local-mock-provider"
    assert result.tool_invocation.capability_id == "knowledge.search"
    assert result.artifact.provenance
    assert "least privilege" in result.artifact.summary
    assert result.audit_event.workspace_id == result.run.workspace_id
    assert runtime.runs.get(result.run.run_id) == result.run
    assert runtime.artifacts.get(result.artifact.artifact_id) == result.artifact


def test_local_runtime_rejects_empty_tasks_without_creating_a_run():
    runtime = LocalPlatformRuntime()

    with pytest.raises(ValueError, match="task must not be empty"):
        runtime.run_agent("  ")

    assert runtime.runs.list() == ()


def test_local_runtime_rejects_oversized_tasks_before_creating_a_run():
    runtime = LocalPlatformRuntime()

    with pytest.raises(ValueError, match="12000 characters"):
        runtime.run_agent("x" * 12_001)

    assert runtime.runs.list() == ()


def test_in_memory_repository_prevents_duplicate_creates():
    runtime = LocalPlatformRuntime()
    runtime.bootstrap()

    with pytest.raises(ValueError, match="already exists"):
        runtime.organizations.create(runtime.organizations.get("local-org"))


def test_repository_does_not_expose_mutable_internal_records():
    runtime = LocalPlatformRuntime()
    runtime.bootstrap()
    first_read = runtime.workspaces.get("local-workspace")
    first_read.name = "Mutated outside repository"

    assert runtime.workspaces.get("local-workspace").name == "Default workspace"


def test_repository_reads_enforce_organization_and_workspace_scope():
    runtime = LocalPlatformRuntime()
    runtime.bootstrap()

    with pytest.raises(KeyError, match="organization scope"):
        runtime.installations.get_scoped(
            "local-knowledge-installation", "another-org", "local-workspace"
        )
    assert runtime.installations.list_scoped("local-org", "local-workspace") == (
        runtime.installations.get("local-knowledge-installation"),
    )
    assert runtime.installations.list_scoped("another-org") == ()


def test_local_runtime_requires_run_permission():
    runtime = LocalPlatformRuntime()
    runtime.bootstrap()
    now = datetime.now(timezone.utc)
    runtime.principals.create(
        Principal(
            id="unassigned-principal",
            org_id="local-org",
            principal_type=PrincipalType.SERVICE_ACCOUNT,
            status=PrincipalStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
    )

    with pytest.raises(PermissionError, match="lacks agents.run permission"):
        runtime.run_agent(
            "Read handbook", requested_by_principal_id="unassigned-principal"
        )

    assert runtime.runs.list() == ()


def test_plugin_denial_fails_run_and_records_invocation_and_audit():
    runtime = LocalPlatformRuntime()
    agent = runtime.create_agent(
        name="No context agent",
        instructions="Answer without using external context.",
        allowed_capability_ids=(),
    )

    with pytest.raises(PluginGatewayError, match="not allowed"):
        runtime.run_agent("Read the handbook", agent_id=agent.id)

    run = runtime.runs.list()[0]
    invocation = runtime.tool_invocations.list()[0]
    assert run.status is RunStatus.FAILED
    assert invocation.status.value == "failed"
    assert invocation.error is not None
    assert runtime.audit_events.list()[-1].action == "agent.run.failed"

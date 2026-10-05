from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from weaves.product.contracts.v1 import (
    CapabilityKind,
    CapabilitySpec,
    PluginDescriptor,
    PluginDescriptorStatus,
    PluginInstallation,
    PluginInstallationBinding,
    PluginInstallationStatus,
    RiskLevel,
    WorkflowBundle,
    WorkflowDefinition,
    WorkflowStatus,
    WorkflowVersion,
)

NOW = datetime.now(timezone.utc)
OBJECT_SCHEMA = {"type": "object", "properties": {}}


def capability(**overrides):
    values = {
        "capability_id": "handbook.search",
        "name": "Search handbook",
        "description": "Find relevant approved handbook material.",
        "kind": CapabilityKind.CONTEXT_READ,
        "risk_level": RiskLevel.LOW,
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        "output_schema": OBJECT_SCHEMA,
        "timeout_seconds": 30,
        "approval_supported": False,
    }
    return CapabilitySpec(**(values | overrides))


def descriptor(**overrides):
    values = {
        "plugin_id": "company-handbook",
        "plugin_type": "knowledge_base",
        "display_name": "Company handbook",
        "description": "Approved company policy and process documents.",
        "capability_manifest": (capability(),),
        "auth_schema": {
            "type": "object",
            "properties": {"api_key": {"type": "string"}},
        },
        "configuration_schema": OBJECT_SCHEMA,
        "status": PluginDescriptorStatus.ACTIVE,
    }
    return PluginDescriptor(**(values | overrides))


def installation(**overrides):
    values = {
        "plugin_installation_id": "installation-a",
        "org_id": "org-a",
        "workspace_id": "workspace-a",
        "plugin_id": "company-handbook",
        "display_name": "People handbook",
        "auth_ref": "vault-ref-a",
        "configuration": {"collection": "employee-handbook"},
        "enabled_capability_ids": ("handbook.search",),
        "status": PluginInstallationStatus.ACTIVE,
        "created_at": NOW,
        "updated_at": NOW,
        "last_healthcheck_at": NOW,
    }
    return PluginInstallation(**(values | overrides))


def workflow_definition(**overrides):
    values = {
        "workflow_id": "support-triage",
        "org_id": "org-a",
        "workspace_id": "workspace-a",
        "name": "Support triage",
        "description": "Classify and summarize a support request.",
        "current_version_id": "support-triage-v1",
        "status": WorkflowStatus.ACTIVE,
        "created_at": NOW,
        "updated_at": NOW,
    }
    return WorkflowDefinition(**(values | overrides))


def workflow_version(**overrides):
    values = {
        "workflow_version_id": "support-triage-v1",
        "workflow_id": "support-triage",
        "org_id": "org-a",
        "workspace_id": "workspace-a",
        "version": 1,
        "handler_key": "support.triage",
        "agent_version_ids": ("support-agent-v3",),
        "required_capability_ids": ("handbook.search",),
        "input_schema": {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
        "output_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
        },
        "configuration": {"locale": "en"},
        "created_at": NOW,
    }
    return WorkflowVersion(**(values | overrides))


def test_plugin_installation_requires_organization_and_workspace_scope():
    with pytest.raises(ValidationError):
        PluginInstallation(
            plugin_installation_id="installation-a",
            plugin_id="company-handbook",
            display_name="Handbook",
            status=PluginInstallationStatus.ACTIVE,
            created_at=NOW,
            updated_at=NOW,
        )


@pytest.mark.parametrize(
    "configuration",
    [
        {"api_key": "raw-secret"},
        {"clientSecret": "raw-secret"},
        {"options": {"refresh_token": "raw-secret"}},
        {"headers": [{"Authorization": "Bearer secret"}]},
    ],
)
def test_plugin_installation_rejects_raw_credentials(configuration):
    with pytest.raises(ValidationError):
        installation(configuration=configuration)


def test_plugin_installation_rejects_credential_fields_outside_config():
    with pytest.raises(ValidationError):
        installation(api_key="raw-secret")


@pytest.mark.parametrize("field", ["input_schema", "output_schema"])
def test_capability_schemas_must_be_valid_json_schema(field):
    with pytest.raises(ValidationError):
        capability(**{field: {"type": "not-a-json-schema-type"}})


@pytest.mark.parametrize(
    "kind", [CapabilityKind.ACTION_WRITE, CapabilityKind.DELIVERY_SEND]
)
def test_write_and_delivery_capabilities_require_risk(kind):
    with pytest.raises(ValidationError):
        capability(kind=kind, risk_level=None)


def test_capability_manifest_rejects_duplicate_ids():
    with pytest.raises(ValidationError):
        descriptor(capability_manifest=(capability(), capability()))


def test_plugin_installation_only_enables_declared_capabilities():
    PluginInstallationBinding(descriptor=descriptor(), installation=installation())
    with pytest.raises(ValidationError):
        PluginInstallationBinding(
            descriptor=descriptor(),
            installation=installation(enabled_capability_ids=("jira.search",)),
        )


def test_workflow_version_is_immutable_including_nested_configuration():
    version = workflow_version()
    with pytest.raises(ValidationError):
        version.handler_key = "changed.handler"
    with pytest.raises(TypeError):
        version.configuration["locale"] = "fr"


@pytest.mark.parametrize("handler_key", ["Support.triage", "not a handler", "x"])
def test_workflow_version_requires_registered_looking_handler_key(handler_key):
    with pytest.raises(ValidationError):
        workflow_version(handler_key=handler_key)


def test_workflow_agent_version_references_must_be_unique():
    with pytest.raises(ValidationError):
        workflow_version(agent_version_ids=("agent-v1", "agent-v1"))


def test_workflow_inputs_and_outputs_must_be_valid_json_schema():
    with pytest.raises(ValidationError):
        workflow_version(output_schema={"type": "not-a-json-schema-type"})


def test_workflow_configuration_cannot_embed_credentials():
    with pytest.raises(ValidationError):
        workflow_version(configuration={"connection": {"access_token": "raw-secret"}})


def test_workflow_bundle_checks_definition_scope_and_version_pointer():
    WorkflowBundle(definition=workflow_definition(), version=workflow_version())
    with pytest.raises(ValidationError):
        WorkflowBundle(
            definition=workflow_definition(workspace_id="workspace-other"),
            version=workflow_version(),
        )
    with pytest.raises(ValidationError):
        WorkflowBundle(
            definition=workflow_definition(current_version_id="old-version"),
            version=workflow_version(),
        )

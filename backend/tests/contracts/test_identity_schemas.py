import json
from pathlib import Path

from weaves.product.contracts.v1 import (
    AgentBudget,
    AgentBundle,
    AgentDefinition,
    AgentRun,
    AgentRunBundle,
    AgentVersion,
    ApprovalRequest,
    Artifact,
    ArtifactProvenance,
    AuditEvent,
    CapabilitySpec,
    ModelMessage,
    ModelProfile,
    ModelProfileBinding,
    ModelProvider,
    ModelRequest,
    ModelResponse,
    ModelUsage,
    Organization,
    PluginDescriptor,
    PluginInstallation,
    PluginInstallationBinding,
    Principal,
    Role,
    RoleBinding,
    ToolInvocation,
    User,
    WorkflowBundle,
    WorkflowDefinition,
    WorkflowRun,
    WorkflowVersion,
    Workspace,
)

SCHEMA_ROOT = Path(__file__).parents[3] / "schemas" / "product" / "v1"
MODELS = {
    "organization": Organization,
    "workspace": Workspace,
    "user": User,
    "principal": Principal,
    "role": Role,
    "role-binding": RoleBinding,
    "model-provider": ModelProvider,
    "model-profile": ModelProfile,
    "model-profile-binding": ModelProfileBinding,
    "model-message": ModelMessage,
    "model-request": ModelRequest,
    "model-response": ModelResponse,
    "model-usage": ModelUsage,
    "agent-definition": AgentDefinition,
    "agent-version": AgentVersion,
    "agent-budget": AgentBudget,
    "agent-bundle": AgentBundle,
    "capability-spec": CapabilitySpec,
    "plugin-descriptor": PluginDescriptor,
    "plugin-installation": PluginInstallation,
    "plugin-installation-binding": PluginInstallationBinding,
    "workflow-definition": WorkflowDefinition,
    "workflow-version": WorkflowVersion,
    "workflow-bundle": WorkflowBundle,
    "workflow-run": WorkflowRun,
    "agent-run": AgentRun,
    "agent-run-bundle": AgentRunBundle,
    "tool-invocation": ToolInvocation,
    "artifact-provenance": ArtifactProvenance,
    "artifact": Artifact,
    "approval-request": ApprovalRequest,
    "audit-event": AuditEvent,
}


def test_checked_in_json_schemas_match_contract_models():
    for name, model in MODELS.items():
        schema_path = SCHEMA_ROOT / f"{name}.schema.json"
        checked_in = json.loads(schema_path.read_text())
        assert checked_in == model.model_json_schema()

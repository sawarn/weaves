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

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "schemas" / "product" / "v1"
CONTRACTS = {
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


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name, contract in CONTRACTS.items():
        path = OUTPUT / f"{name}.schema.json"
        path.write_text(
            json.dumps(contract.model_json_schema(), indent=2, sort_keys=True) + "\n"
        )
        print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

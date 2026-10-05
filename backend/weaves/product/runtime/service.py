"""A local agent path backed by in-memory repositories and pluggable models."""

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

import httpx

from weaves.product.contracts.v1 import (
    AgentDefinition,
    AgentRun,
    AgentStatus,
    AgentVersion,
    Artifact,
    ArtifactProvenance,
    ArtifactSensitivity,
    ArtifactStatus,
    AuditEvent,
    AuditTargetScope,
    CapabilityKind,
    CapabilitySpec,
    ErrorSummary,
    InvocationStatus,
    ModelProfile,
    ModelProfileBinding,
    ModelProfileStatus,
    ModelProviderStatus,
    ModelProviderType,
    Organization,
    OrganizationStatus,
    Permission,
    PluginDescriptor,
    PluginDescriptorStatus,
    PluginInstallation,
    PluginInstallationStatus,
    Principal,
    PrincipalStatus,
    PrincipalType,
    RetentionClass,
    RiskLevel,
    Role,
    RoleBinding,
    RunStatus,
    ToolInvocation,
    User,
    UserStatus,
    WorkflowDefinition,
    WorkflowRun,
    WorkflowStatus,
    WorkflowVersion,
    Workspace,
    WorkspaceStatus,
)
from weaves.product.contracts.v1 import (
    ModelProvider as ModelProviderContract,
)
from weaves.product.contracts.v1.json_data import thaw_json_value
from weaves.product.contracts.v1.model_execution import (
    ModelMessage,
    ModelMessageRole,
    ModelRequest,
)
from weaves.product.runtime.mocks import DeterministicMockModel, MockKnowledgePlugin
from weaves.product.runtime.model_gateway import (
    EnvironmentSecretResolver,
    ModelAdapter,
    ModelGateway,
    ModelGatewayError,
    OpenAICompatibleAdapter,
)
from weaves.product.runtime.plugin_gateway import PluginGateway, PluginGatewayError
from weaves.product.runtime.repositories import InMemoryRepository, PostgresRepository


@dataclass(frozen=True)
class RuntimeResult:
    run: WorkflowRun
    agent_run: AgentRun
    artifact: Artifact
    tool_invocation: ToolInvocation
    audit_event: AuditEvent


class LocalPlatformRuntime:
    """Run the local platform path with mock defaults and optional OpenAI."""

    def __init__(self) -> None:
        database_url = os.environ.get("DATABASE_URL", "").strip()
        self._postgres_store = None
        if database_url:
            # Loaded lazily so memory-only development has no database import or startup.
            from weaves.product.runtime.postgres import ProductPostgresStore

            self._postgres_store = ProductPostgresStore(database_url)
        self.storage_mode = "postgres" if self._postgres_store else "memory"
        self.organizations = self._repository("organizations", "id", Organization)
        self.workspaces = self._repository("workspaces", "id", Workspace)
        self.users = self._repository("users", "id", User)
        self.principals = self._repository("principals", "id", Principal)
        self.roles = self._repository("roles", "id", Role)
        self.role_bindings = self._repository("role_bindings", "id", RoleBinding)
        self.providers = self._repository(
            "model_providers", "id", ModelProviderContract
        )
        self.model_profiles = self._repository("model_profiles", "id", ModelProfile)
        self.plugins = self._repository("plugins", "plugin_id", PluginDescriptor)
        self.installations = self._repository(
            "plugin_installations", "plugin_installation_id", PluginInstallation
        )
        self.agents = self._repository("agents", "id", AgentDefinition)
        self.agent_versions = self._repository(
            "agent_versions", "agent_version_id", AgentVersion
        )
        self.workflows = self._repository(
            "workflows", "workflow_id", WorkflowDefinition
        )
        self.workflow_versions = self._repository(
            "workflow_versions", "workflow_version_id", WorkflowVersion
        )
        self.runs = self._repository("workflow_runs", "run_id", WorkflowRun)
        self.agent_runs = self._repository("agent_runs", "agent_run_id", AgentRun)
        self.tool_invocations = self._repository(
            "tool_invocations", "invocation_id", ToolInvocation
        )
        self.artifacts = self._repository("artifacts", "artifact_id", Artifact)
        self.audit_events = self._repository(
            "audit_events", "audit_event_id", AuditEvent
        )
        self.model = DeterministicMockModel()
        self.default_model_profile_id = "local-model-profile"
        self._model_http_client: Optional[httpx.Client] = None
        self.openai_adapter: Optional[OpenAICompatibleAdapter] = None
        adapters: dict[ModelProviderType, ModelAdapter] = {
            ModelProviderType.LOCAL: self.model
        }
        self.openai_model_name = (
            os.environ.get("MODEL_NAME", "gpt-4o-mini").strip() or "gpt-4o-mini"
        )
        self.openai_base_url = (
            os.environ.get("MODEL_BASE_URL", "https://api.openai.com/v1").strip()
            or "https://api.openai.com/v1"
        )
        self.openai_enabled = bool(os.environ.get("MODEL_API_KEY", "").strip())
        if self.openai_enabled:
            self._model_http_client = httpx.Client()
            self.openai_adapter = OpenAICompatibleAdapter(
                EnvironmentSecretResolver(), self._model_http_client
            )
            adapters[ModelProviderType.OPENAI] = self.openai_adapter
            self.default_model_profile_id = "openai-model-profile"
        self.model_gateway = ModelGateway(adapters)
        self.context = MockKnowledgePlugin()
        self.plugin_gateway = PluginGateway(
            self.plugins,
            self.installations,
            {"local-knowledge": self.context},
        )
        self._bootstrapped = False

    def _repository(self, collection: str, id_field: str, record_type: type):
        if self._postgres_store is None:
            return InMemoryRepository(id_field)
        return PostgresRepository(
            self._postgres_store.pool, collection, id_field, record_type
        )

    @staticmethod
    def _seed(repository, id_field: str, record):
        """Create a deterministic starter record only when it is absent."""
        record_id = str(getattr(record, id_field))
        try:
            return repository.get(record_id)
        except KeyError:
            try:
                return repository.create(record)
            except ValueError:
                # A concurrent API replica may have inserted the same seed.
                return repository.get(record_id)

    def bootstrap(self) -> None:
        """Create a deterministic local org, workspace, model, plugin, and agent."""
        if self._bootstrapped:
            return
        now = _now()
        self._seed(
            self.organizations,
            "id",
            Organization(
                id="local-org",
                name="Local development",
                status=OrganizationStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            ),
        )
        self._seed(
            self.workspaces,
            "id",
            Workspace(
                id="local-workspace",
                org_id="local-org",
                name="Default workspace",
                status=WorkspaceStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            ),
        )
        self._seed(
            self.users,
            "id",
            User(
                id="local-developer-user",
                org_id="local-org",
                email="developer@localhost",
                display_name="Local developer",
                status=UserStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            ),
        )
        self._seed(
            self.principals,
            "id",
            Principal(
                id="local-developer",
                org_id="local-org",
                principal_type=PrincipalType.USER,
                status=PrincipalStatus.ACTIVE,
                user_id="local-developer-user",
                created_at=now,
                updated_at=now,
            ),
        )
        self._seed(
            self.roles,
            "id",
            Role(
                id="local-developer-role",
                org_id="local-org",
                name="Local developer",
                permissions=[
                    Permission.AGENTS_MANAGE,
                    Permission.AGENTS_RUN,
                    Permission.ARTIFACTS_READ,
                    Permission.AUDIT_READ,
                    Permission.MODELS_MANAGE,
                    Permission.PLUGINS_MANAGE,
                    Permission.WORKFLOWS_RUN,
                ],
            ),
        )
        self._seed(
            self.role_bindings,
            "id",
            RoleBinding(
                id="local-developer-binding",
                org_id="local-org",
                principal_id="local-developer",
                role_id="local-developer-role",
                workspace_id="local-workspace",
                created_at=now,
            ),
        )
        self._seed(
            self.providers,
            "id",
            ModelProviderContract(
                id=self.model.provider_id,
                org_id="local-org",
                provider_type=ModelProviderType.LOCAL,
                display_name="Deterministic mock",
                allowed_models=[self.model.model_id],
                status=ModelProviderStatus.ACTIVE,
            ),
        )
        self._seed(
            self.model_profiles,
            "id",
            ModelProfile(
                id="local-model-profile",
                org_id="local-org",
                provider_id=self.model.provider_id,
                model=self.model.model_id,
                display_name="Local mock model",
                status=ModelProfileStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            ),
        )
        if self.openai_enabled:
            self._seed(
                self.providers,
                "id",
                ModelProviderContract(
                    id="openai-provider",
                    org_id="local-org",
                    provider_type=ModelProviderType.OPENAI,
                    display_name="OpenAI",
                    allowed_models=[self.openai_model_name],
                    auth_ref="env:MODEL_API_KEY",
                    base_url=self.openai_base_url,
                    status=ModelProviderStatus.ACTIVE,
                ),
            )
            self._seed(
                self.model_profiles,
                "id",
                ModelProfile(
                    id="openai-model-profile",
                    org_id="local-org",
                    provider_id="openai-provider",
                    model=self.openai_model_name,
                    display_name=f"OpenAI · {self.openai_model_name}",
                    status=ModelProfileStatus.ACTIVE,
                    created_at=now,
                    updated_at=now,
                ),
            )
        search_capability = CapabilitySpec(
            capability_id="knowledge.search",
            name="Search local knowledge",
            kind=CapabilityKind.CONTEXT_READ,
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
            output_schema={"type": "object"},
            timeout_seconds=5,
        )
        self._seed(
            self.plugins,
            "plugin_id",
            PluginDescriptor(
                plugin_id="local-knowledge",
                plugin_type="knowledge_base",
                display_name="Local knowledge",
                capability_manifest=(search_capability,),
                status=PluginDescriptorStatus.ACTIVE,
            ),
        )
        self._seed(
            self.installations,
            "plugin_installation_id",
            PluginInstallation(
                plugin_installation_id="local-knowledge-installation",
                org_id="local-org",
                workspace_id="local-workspace",
                plugin_id="local-knowledge",
                display_name="Local knowledge",
                enabled_capability_ids=("knowledge.search",),
                status=PluginInstallationStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            ),
        )
        version = AgentVersion(
            agent_version_id="local-assistant-v1",
            agent_id="local-assistant",
            org_id="local-org",
            workspace_id="local-workspace",
            version=1,
            persona="A concise, helpful work assistant.",
            instructions="Use only the supplied approved context. State when context is insufficient.",
            model_profile_id=self.default_model_profile_id,
            allowed_capability_ids=("knowledge.search",),
            allowed_workflow_ids=("local-assistant-workflow",),
            created_at=now,
        )
        self._seed(self.agent_versions, "agent_version_id", version)
        self._seed(
            self.agents,
            "id",
            AgentDefinition(
                id="local-assistant",
                org_id="local-org",
                workspace_id="local-workspace",
                name="Local assistant",
                description=(
                    "An OpenAI-backed platform runtime example."
                    if self.openai_enabled
                    else "A deterministic platform runtime example."
                ),
                current_version_id=version.agent_version_id,
                status=AgentStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            ),
        )
        workflow_version = WorkflowVersion(
            workflow_version_id="local-assistant-workflow-v1",
            workflow_id="local-assistant-workflow",
            org_id="local-org",
            workspace_id="local-workspace",
            version=1,
            handler_key="agent.execute",
            agent_version_ids=(version.agent_version_id,),
            required_capability_ids=("knowledge.search",),
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            created_at=now,
        )
        self._seed(self.workflow_versions, "workflow_version_id", workflow_version)
        self._seed(
            self.workflows,
            "workflow_id",
            WorkflowDefinition(
                workflow_id="local-assistant-workflow",
                org_id="local-org",
                workspace_id="local-workspace",
                name="Run local assistant",
                current_version_id=workflow_version.workflow_version_id,
                status=WorkflowStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            ),
        )
        self._bootstrapped = True

    def refresh_openai_model_catalog(self) -> tuple[ModelProfile, ...]:
        """Fetch API-visible model IDs and register selectable local profiles."""
        if not self._bootstrapped:
            self.bootstrap()
        if self.openai_adapter is None:
            raise ModelGatewayError(
                "model.provider_disabled", "OpenAI is not configured for this runtime"
            )
        provider = self.providers.get_scoped("openai-provider", "local-org")
        models = self.openai_adapter.list_models(provider)
        model_ids = tuple(model["id"] for model in models if len(model["id"]) <= 160)
        provider = provider.model_copy(
            update={"allowed_models": list(dict.fromkeys(model_ids))}
        )
        self.providers.put(provider)
        profiles = []
        for model_id in model_ids:
            profile_id = (
                "openai-model-profile"
                if model_id == self.openai_model_name
                else "openai-model-"
                + hashlib.sha256(model_id.encode("utf-8")).hexdigest()[:24]
            )
            try:
                profiles.append(self.model_profiles.get_scoped(profile_id, "local-org"))
                continue
            except KeyError:
                pass
            now = _now()
            profile = ModelProfile(
                id=profile_id,
                org_id="local-org",
                provider_id=provider.id,
                model=model_id,
                display_name=f"OpenAI · {model_id}"[:160],
                status=ModelProfileStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            )
            self.model_profiles.create(profile)
            profiles.append(profile)
        return tuple(profiles)

    def create_agent(
        self,
        *,
        name: str,
        instructions: str,
        description: str = "",
        model_profile_id: Optional[str] = None,
        allowed_capability_ids: tuple[str, ...] = ("knowledge.search",),
        requested_by_principal_id: str = "local-developer",
    ) -> AgentDefinition:
        """Create an agent and immutable executable/workflow versions."""
        if not self._bootstrapped:
            self.bootstrap()
        self.authorize(requested_by_principal_id, Permission.AGENTS_MANAGE)
        profile = self.model_profiles.get_scoped(
            model_profile_id or self.default_model_profile_id, "local-org"
        )
        provider = self.providers.get_scoped(profile.provider_id, "local-org")
        ModelProfileBinding(provider=provider, profile=profile)
        if profile.status is not ModelProfileStatus.ACTIVE:
            raise ValueError("model profile must be active")
        if len(allowed_capability_ids) != len(set(allowed_capability_ids)):
            raise ValueError("allowed capabilities must be unique")
        installation = self.installations.get_scoped(
            "local-knowledge-installation", "local-org", "local-workspace"
        )
        available = set(installation.enabled_capability_ids)
        if not set(allowed_capability_ids).issubset(available):
            raise ValueError(
                "agent capabilities must be enabled on an installed plugin"
            )
        if any(
            capability_id != "knowledge.search"
            for capability_id in allowed_capability_ids
        ):
            raise ValueError("v0 supports the knowledge.search context capability only")

        now = _now()
        agent_id = _id()
        agent_version_id = _id()
        workflow_id = _id()
        workflow_version_id = _id()
        agent_version = AgentVersion(
            agent_version_id=agent_version_id,
            agent_id=agent_id,
            org_id="local-org",
            workspace_id="local-workspace",
            version=1,
            persona="A helpful work assistant.",
            instructions=instructions,
            model_profile_id=profile.id,
            allowed_capability_ids=allowed_capability_ids,
            allowed_workflow_ids=(workflow_id,),
            created_at=now,
        )
        definition = AgentDefinition(
            id=agent_id,
            org_id="local-org",
            workspace_id="local-workspace",
            name=name,
            description=description,
            current_version_id=agent_version_id,
            status=AgentStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        workflow_version = WorkflowVersion(
            workflow_version_id=workflow_version_id,
            workflow_id=workflow_id,
            org_id="local-org",
            workspace_id="local-workspace",
            version=1,
            handler_key="agent.execute",
            agent_version_ids=(agent_version_id,),
            required_capability_ids=allowed_capability_ids,
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            created_at=now,
        )
        workflow = WorkflowDefinition(
            workflow_id=workflow_id,
            org_id="local-org",
            workspace_id="local-workspace",
            name=f"Run {name}",
            current_version_id=workflow_version_id,
            status=WorkflowStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        self.agent_versions.create(agent_version)
        self.agents.create(definition)
        self.workflow_versions.create(workflow_version)
        self.workflows.create(workflow)
        self.audit_events.create(
            AuditEvent(
                audit_event_id=_id(),
                org_id="local-org",
                target_scope=AuditTargetScope.WORKSPACE,
                workspace_id="local-workspace",
                actor_principal_id=requested_by_principal_id,
                action="agent.created",
                target_type="agent",
                target_id=agent_id,
                summary="Agent created",
                request_id=agent_id,
                metadata={"agent_version_id": agent_version_id},
                created_at=now,
            )
        )
        return definition

    def run_agent(
        self,
        task: str,
        requested_by_principal_id: str = "local-developer",
        agent_id: str = "local-assistant",
    ) -> RuntimeResult:
        """Execute a synchronous mock run and persist its contract records."""
        if not self._bootstrapped:
            self.bootstrap()
        task = task.strip()
        if not task:
            raise ValueError("task must not be empty")
        if len(task) > 12_000:
            raise ValueError("task must not exceed 12000 characters")
        self.authorize(requested_by_principal_id, Permission.AGENTS_RUN)
        now = _now()
        run_id, agent_run_id, invocation_id, artifact_id = (_id() for _ in range(4))
        definition = self.agents.get_scoped(agent_id, "local-org", "local-workspace")
        agent_version = self.agent_versions.get_scoped(
            definition.current_version_id or "", "local-org", "local-workspace"
        )
        workflow_id = agent_version.allowed_workflow_ids[0]
        workflow = self.workflows.get_scoped(
            workflow_id, "local-org", "local-workspace"
        )
        profile = self.model_profiles.get_scoped(
            agent_version.model_profile_id, "local-org"
        )
        installation = self.installations.get_scoped(
            "local-knowledge-installation", "local-org", "local-workspace"
        )
        run = WorkflowRun(
            run_id=run_id,
            org_id="local-org",
            workspace_id="local-workspace",
            workflow_id=workflow.workflow_id,
            workflow_version_id=workflow.current_version_id or "",
            requested_by_principal_id=requested_by_principal_id,
            trigger_type="local.runtime",
            status=RunStatus.RUNNING,
            started_at=now,
            created_at=now,
            updated_at=now,
        )
        self.runs.create(run)
        agent_run = AgentRun(
            agent_run_id=agent_run_id,
            run_id=run_id,
            org_id="local-org",
            workspace_id="local-workspace",
            agent_id=definition.id,
            agent_version_id=agent_version.agent_version_id,
            model_profile_id=profile.id,
            resolved_provider_id=self.model.provider_id,
            resolved_model_id=profile.model,
            status=RunStatus.RUNNING,
            input_summary={"task": task},
            started_at=now,
            created_at=now,
            updated_at=now,
        )
        self.agent_runs.create(agent_run)

        try:
            capability_result = self.plugin_gateway.invoke(
                org_id="local-org",
                workspace_id="local-workspace",
                installation_id=installation.plugin_installation_id,
                agent_version=agent_version,
                capability_id="knowledge.search",
                payload={"query": task},
            )
        except PluginGatewayError as exc:
            failed_at = _now()
            self.tool_invocations.create(
                ToolInvocation(
                    invocation_id=invocation_id,
                    run_id=run_id,
                    agent_run_id=agent_run_id,
                    org_id="local-org",
                    workspace_id="local-workspace",
                    plugin_installation_id=installation.plugin_installation_id,
                    capability_id="knowledge.search",
                    status=InvocationStatus.FAILED,
                    risk_level=RiskLevel.LOW,
                    input_summary={"query": task},
                    created_at=now,
                    updated_at=failed_at,
                    started_at=now,
                    finished_at=failed_at,
                    duration_ms=max(0, int((failed_at - now).total_seconds() * 1000)),
                    error=ErrorSummary(code=exc.code, summary=exc.message),
                )
            )
            self._record_run_failure(
                run,
                agent_run,
                requested_by_principal_id,
                exc.code,
                exc.message,
                retryable=False,
            )
            raise
        context = tuple(capability_result.output["documents"])
        invocation = ToolInvocation(
            invocation_id=invocation_id,
            run_id=run_id,
            agent_run_id=agent_run_id,
            org_id="local-org",
            workspace_id="local-workspace",
            plugin_installation_id=installation.plugin_installation_id,
            capability_id="knowledge.search",
            status=InvocationStatus.SUCCEEDED,
            risk_level=RiskLevel.LOW,
            input_summary={"query": task},
            output_summary={"result_count": len(context)},
            created_at=now,
            updated_at=capability_result.finished_at,
            started_at=capability_result.started_at,
            finished_at=capability_result.finished_at,
            duration_ms=capability_result.duration_ms,
        )
        self.tool_invocations.create(invocation)
        provider = self.providers.get_scoped(profile.provider_id, "local-org")
        binding = ModelProfileBinding(provider=provider, profile=profile)
        context_text = "\n".join(
            f"- {item['title']}: {item['text']} (source: {item['source_id']})"
            for item in context
        )
        try:
            model_response = self.model_gateway.complete(
                ModelRequest(
                    messages=(
                        ModelMessage(
                            role=ModelMessageRole.SYSTEM,
                            content=agent_version.instructions,
                        ),
                        ModelMessage(
                            role=ModelMessageRole.USER,
                            content=f"Task:\n{task}\n\nApproved context:\n{context_text}",
                        ),
                    ),
                    temperature=profile.default_temperature,
                    max_output_tokens=min(
                        profile.max_output_tokens,
                        agent_version.budget.max_output_tokens,
                    ),
                    request_id=run_id,
                ),
                binding,
            )
        except ModelGatewayError as exc:
            self._record_run_failure(
                run,
                agent_run,
                requested_by_principal_id,
                exc.code,
                exc.message,
                retryable=exc.retryable,
            )
            raise
        response_text = model_response.content
        finished = _now()
        agent_run = agent_run.model_copy(
            update={
                "status": RunStatus.SUCCEEDED,
                "output_summary": {
                    "response": response_text,
                    "source_ids": [item["source_id"] for item in context],
                },
                "resolved_provider_id": model_response.provider_id,
                "resolved_model_id": model_response.model_id,
                "input_tokens": model_response.usage.input_tokens,
                "output_tokens": model_response.usage.output_tokens,
                "finished_at": finished,
                "updated_at": finished,
            }
        )
        self.agent_runs.put(agent_run)
        run = run.model_copy(
            update={
                "status": RunStatus.SUCCEEDED,
                "finished_at": finished,
                "updated_at": finished,
            }
        )
        self.runs.put(run)

        provenance = tuple(
            ArtifactProvenance(
                source_type="knowledge.document",
                source_ref=item["source_id"],
                recorded_at=finished,
            )
            for item in context
        ) or (
            ArtifactProvenance(
                source_type="agent.run",
                source_ref=agent_run_id,
                recorded_at=finished,
            ),
        )
        artifact = Artifact(
            artifact_id=artifact_id,
            org_id="local-org",
            workspace_id="local-workspace",
            run_id=run_id,
            agent_run_id=agent_run_id,
            artifact_type="agent.response",
            title="Agent response",
            summary=response_text,
            content_ref=f"memory://{artifact_id}",
            content_type="application.json",
            provenance=provenance,
            sensitivity=ArtifactSensitivity.INTERNAL,
            retention_class=RetentionClass.STANDARD,
            status=ArtifactStatus.AVAILABLE,
            created_by_agent_run_id=agent_run_id,
            created_at=finished,
            updated_at=finished,
        )
        self.artifacts.create(artifact)
        audit = AuditEvent(
            audit_event_id=_id(),
            org_id="local-org",
            target_scope=AuditTargetScope.WORKSPACE,
            workspace_id="local-workspace",
            actor_principal_id=requested_by_principal_id,
            action="agent.run.succeeded",
            target_type="workflow_run",
            target_id=run_id,
            summary="Local mock agent run completed",
            request_id=run_id,
            metadata={
                "agent_version_id": agent_version.agent_version_id,
                "artifact_id": artifact_id,
            },
            created_at=finished,
        )
        self.audit_events.create(audit)
        return RuntimeResult(run, agent_run, artifact, invocation, audit)

    def update_agent(
        self,
        agent_id: str,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        instructions: Optional[str] = None,
        model_profile_id: Optional[str] = None,
        requested_by_principal_id: str = "local-developer",
    ) -> AgentDefinition:
        """Update editable metadata and publish a new immutable agent version."""
        if not self._bootstrapped:
            self.bootstrap()
        self.authorize(requested_by_principal_id, Permission.AGENTS_MANAGE)
        current = self.agents.get_scoped(agent_id, "local-org", "local-workspace")
        old_version = self.agent_versions.get_scoped(
            current.current_version_id or "", "local-org", "local-workspace"
        )
        profile_id = model_profile_id or old_version.model_profile_id
        profile = self.model_profiles.get_scoped(profile_id, "local-org")
        provider = self.providers.get_scoped(profile.provider_id, "local-org")
        ModelProfileBinding(provider=provider, profile=profile)
        if profile.status is not ModelProfileStatus.ACTIVE:
            raise ValueError("model profile must be active")
        now = _now()
        next_version = AgentVersion(
            agent_version_id=_id(),
            agent_id=agent_id,
            org_id=current.org_id,
            workspace_id=current.workspace_id,
            version=old_version.version + 1,
            persona=old_version.persona,
            instructions=instructions or old_version.instructions,
            model_profile_id=profile.id,
            allowed_capability_ids=old_version.allowed_capability_ids,
            allowed_workflow_ids=old_version.allowed_workflow_ids,
            approval_policy_id=old_version.approval_policy_id,
            budget_policy_id=old_version.budget_policy_id,
            budget=old_version.budget,
            output_schema=old_version.output_schema,
            created_at=now,
        )
        workflow_id = old_version.allowed_workflow_ids[0]
        workflow = self.workflows.get_scoped(
            workflow_id, current.org_id, current.workspace_id
        )
        old_workflow_version = self.workflow_versions.get_scoped(
            workflow.current_version_id or "", current.org_id, current.workspace_id
        )
        next_workflow_version = WorkflowVersion(
            workflow_version_id=_id(),
            workflow_id=workflow_id,
            org_id=current.org_id,
            workspace_id=current.workspace_id,
            version=old_workflow_version.version + 1,
            handler_key=old_workflow_version.handler_key,
            agent_version_ids=(next_version.agent_version_id,),
            required_capability_ids=old_workflow_version.required_capability_ids,
            input_schema=thaw_json_value(old_workflow_version.input_schema),
            output_schema=thaw_json_value(old_workflow_version.output_schema),
            configuration=thaw_json_value(old_workflow_version.configuration),
            created_at=now,
        )
        updated = current.model_copy(
            update={
                "name": name or current.name,
                "description": description
                if description is not None
                else current.description,
                "current_version_id": next_version.agent_version_id,
                "updated_at": now,
            }
        )
        updated_workflow = workflow.model_copy(
            update={
                "current_version_id": next_workflow_version.workflow_version_id,
                "updated_at": now,
            }
        )
        self.agent_versions.create(next_version)
        self.workflow_versions.create(next_workflow_version)
        self.agents.put(updated)
        self.workflows.put(updated_workflow)
        self.audit_events.create(
            AuditEvent(
                audit_event_id=_id(),
                org_id=current.org_id,
                target_scope=AuditTargetScope.WORKSPACE,
                workspace_id=current.workspace_id,
                actor_principal_id=requested_by_principal_id,
                action="agent.version.published",
                target_type="agent",
                target_id=agent_id,
                summary="Agent version published",
                request_id=next_version.agent_version_id,
                metadata={"agent_version_id": next_version.agent_version_id},
                created_at=now,
            )
        )
        return updated

    def close(self) -> None:
        """Release provider and storage clients owned by this runtime."""
        if self._model_http_client is not None:
            self._model_http_client.close()
            self._model_http_client = None
        if self._postgres_store is not None:
            self._postgres_store.close()

    def check_storage(self) -> None:
        """Check readiness of the selected durable store, if configured."""
        if self._postgres_store is not None:
            self._postgres_store.check()

    def authorize(self, principal_id: str, permission: Permission) -> None:
        principal = self.principals.get_scoped(principal_id, "local-org")
        if principal.status is not PrincipalStatus.ACTIVE:
            raise PermissionError("principal is not active")
        bindings = self.role_bindings.list_scoped("local-org")
        for binding in bindings:
            if binding.principal_id != principal_id:
                continue
            if binding.workspace_id not in {None, "local-workspace"}:
                continue
            role = self.roles.get_scoped(binding.role_id, "local-org")
            if permission in role.permissions:
                return
        raise PermissionError(f"principal lacks {permission.value} permission")

    def _record_run_failure(
        self,
        run: WorkflowRun,
        agent_run: AgentRun,
        actor_principal_id: str,
        error_code: str,
        error_message: str,
        retryable: bool,
    ) -> None:
        finished = _now()
        summary = ErrorSummary(
            code=error_code, summary=error_message, retryable=retryable
        )
        failed_agent_run = agent_run.model_copy(
            update={
                "status": RunStatus.FAILED,
                "error": summary,
                "finished_at": finished,
                "updated_at": finished,
            }
        )
        failed_run = run.model_copy(
            update={
                "status": RunStatus.FAILED,
                "error": summary,
                "finished_at": finished,
                "updated_at": finished,
            }
        )
        self.agent_runs.put(failed_agent_run)
        self.runs.put(failed_run)
        self.audit_events.create(
            AuditEvent(
                audit_event_id=_id(),
                org_id=run.org_id,
                target_scope=AuditTargetScope.WORKSPACE,
                workspace_id=run.workspace_id,
                actor_principal_id=actor_principal_id,
                action="agent.run.failed",
                target_type="workflow_run",
                target_id=run.run_id,
                summary=error_message,
                request_id=run.run_id,
                metadata={"error_code": error_code},
                created_at=finished,
            )
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _id() -> str:
    return str(uuid4())

"""Agent definitions, templates, and capability discovery API routes."""

from decimal import Decimal
from typing import Any, Callable, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from weaves.product.contracts.v1 import AgentBudget, MemoryScope, Permission
from weaves.product.runtime import LocalPlatformRuntime
from weaves.product.runtime.request_identity import (
    effective_org_id,
    effective_workspace_id,
)


class AgentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=2, max_length=160)
    description: str = Field(default="", max_length=1000)
    instructions: str = Field(min_length=1, max_length=12000)
    model_profile_id: Optional[str] = None
    allowed_capability_ids: tuple[str, ...] = ("knowledge.search",)
    memory_scopes: tuple[MemoryScope, ...] = (MemoryScope.WORKSPACE,)
    max_runtime_seconds: int = Field(default=300, ge=1, le=3600)
    max_tool_calls: int = Field(default=10, ge=0, le=100)
    max_output_tokens: int = Field(default=4096, ge=1, le=32768)
    max_run_cost_usd: Optional[Decimal] = Field(
        default=None, gt=0, le=100000, max_digits=18, decimal_places=9
    )
    output_schema: Optional[dict[str, JsonValue]] = None


class AgentTemplateCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: Optional[str] = Field(default=None, min_length=2, max_length=160)
    model_profile_id: Optional[str] = None
    allowed_capability_ids: tuple[str, ...] = Field(min_length=1, max_length=100)
    memory_scopes: tuple[MemoryScope, ...] = (MemoryScope.WORKSPACE,)
    max_runtime_seconds: int = Field(default=300, ge=1, le=3600)
    max_tool_calls: int = Field(default=10, ge=0, le=100)
    max_output_tokens: int = Field(default=4096, ge=1, le=32768)
    max_run_cost_usd: Optional[Decimal] = Field(
        default=None, gt=0, le=100000, max_digits=18, decimal_places=9
    )
    output_schema: Optional[dict[str, JsonValue]] = None


class AgentPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: Optional[str] = Field(default=None, min_length=2, max_length=160)
    description: Optional[str] = Field(default=None, max_length=1000)
    instructions: Optional[str] = Field(default=None, min_length=1, max_length=12000)
    model_profile_id: Optional[str] = None
    allowed_capability_ids: Optional[tuple[str, ...]] = None
    memory_scopes: Optional[tuple[MemoryScope, ...]] = None
    budget: Optional[AgentBudget] = None
    output_schema: Optional[dict[str, JsonValue]] = None


def _agent_view(
    runtime: LocalPlatformRuntime,
    agent: Any,
    dump: Callable[[BaseModel], dict[str, Any]],
) -> dict[str, Any]:
    result = dump(agent)
    if agent.current_version_id:
        result["current_version"] = dump(
            runtime.agent_versions.get_scoped(
                agent.current_version_id, agent.org_id, agent.workspace_id
            )
        )
    return result


def register_agent_routes(
    app: FastAPI,
    platform: LocalPlatformRuntime,
    dump: Callable[[BaseModel], dict[str, Any]],
) -> None:
    """Register agent, template, and capability discovery endpoints."""
    _dump = dump

    def agent_view(agent: Any) -> dict[str, Any]:
        return _agent_view(platform, agent, _dump)

    @app.get("/api/v0/capabilities")
    def list_capabilities() -> list[dict[str, Any]]:
        platform.authorize("local-developer", Permission.PLUGINS_MANAGE)
        descriptors = platform.plugins.list()
        return [
            _dump(capability)
            for descriptor in descriptors
            for capability in descriptor.capability_manifest
        ]

    @app.get("/api/v0/plugin-descriptors")
    def list_plugin_descriptors() -> list[dict[str, Any]]:
        platform.authorize("local-developer", Permission.PLUGINS_MANAGE)
        return [_dump(item) for item in platform.plugins.list()]

    @app.get("/api/v0/agents")
    def list_agents() -> list[dict[str, Any]]:
        platform.authorize("local-developer", Permission.AGENTS_MANAGE)
        return [
            agent_view(item)
            for item in platform.agents.list_scoped(
                effective_org_id(), effective_workspace_id()
            )
        ]

    @app.get("/api/v0/agent-templates")
    def list_agent_templates() -> list[dict[str, Any]]:
        try:
            return [
                {
                    "template_id": item.template_id,
                    "name": item.name,
                    "description": item.description,
                    "recommended_capability_ids": list(item.recommended_capability_ids),
                }
                for item in platform.get_agent_templates()
            ]
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.post("/api/v0/agent-templates/{template_id}/agents", status_code=201)
    def create_agent_from_template(
        template_id: str, request: AgentTemplateCreateRequest
    ) -> dict[str, Any]:
        try:
            agent = platform.create_agent_from_template(
                template_id,
                name=request.name,
                model_profile_id=request.model_profile_id,
                allowed_capability_ids=request.allowed_capability_ids,
                memory_scopes=request.memory_scopes,
                budget=AgentBudget(
                    max_runtime_seconds=request.max_runtime_seconds,
                    max_tool_calls=request.max_tool_calls,
                    max_output_tokens=request.max_output_tokens,
                    max_run_cost_usd=request.max_run_cost_usd,
                ),
                output_schema=request.output_schema,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="Template, model profile, or selected capability not found",
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return agent_view(agent)

    @app.post("/api/v0/agents", status_code=201)
    def create_agent(request: AgentCreateRequest) -> dict[str, Any]:
        try:
            agent = platform.create_agent(
                name=request.name,
                description=request.description,
                instructions=request.instructions,
                model_profile_id=request.model_profile_id,
                allowed_capability_ids=request.allowed_capability_ids,
                memory_scopes=request.memory_scopes,
                budget=AgentBudget(
                    max_runtime_seconds=request.max_runtime_seconds,
                    max_tool_calls=request.max_tool_calls,
                    max_output_tokens=request.max_output_tokens,
                    max_run_cost_usd=request.max_run_cost_usd,
                ),
                output_schema=request.output_schema,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Model profile not found"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return agent_view(agent)

    @app.patch("/api/v0/agents/{agent_id}")
    def update_agent(agent_id: str, patch: AgentPatchRequest) -> dict[str, Any]:
        requested_changes = patch.model_dump(exclude_unset=True)
        changes = {
            key: value for key, value in requested_changes.items() if value is not None
        }
        if "output_schema" in requested_changes:
            changes["clear_output_schema"] = requested_changes["output_schema"] is None
        if not changes:
            raise HTTPException(status_code=400, detail="No changes supplied")
        try:
            agent = platform.update_agent(agent_id, **changes)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Agent or model profile not found"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return agent_view(agent)

    @app.get("/api/v0/agents/{agent_id}")
    def get_agent(agent_id: str) -> dict[str, Any]:
        platform.authorize("local-developer", Permission.AGENTS_MANAGE)
        try:
            agent = platform.agents.get_scoped(
                agent_id, effective_org_id(), effective_workspace_id()
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Agent not found") from exc
        return agent_view(agent)

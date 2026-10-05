"""FastAPI surface for the platform-native local v0."""

import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from weaves.product.contracts.v1 import Permission
from weaves.product.runtime import LocalPlatformRuntime
from weaves.product.runtime.model_gateway import ModelGatewayError
from weaves.product.runtime.plugin_gateway import PluginGatewayError


class AgentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=2, max_length=160)
    description: str = Field(default="", max_length=1000)
    instructions: str = Field(min_length=1, max_length=12000)
    model_profile_id: Optional[str] = None
    allowed_capability_ids: tuple[str, ...] = ("knowledge.search",)


class RunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    task: str = Field(min_length=3, max_length=12000)
    agent_id: str = "local-assistant"


class AgentPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: Optional[str] = Field(default=None, min_length=2, max_length=160)
    description: Optional[str] = Field(default=None, max_length=1000)
    instructions: Optional[str] = Field(default=None, min_length=1, max_length=12000)
    model_profile_id: Optional[str] = None


def create_app(runtime: Optional[LocalPlatformRuntime] = None) -> FastAPI:
    """Create the isolated product API and its local runtime dependency."""
    platform = runtime or LocalPlatformRuntime()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        platform.bootstrap()
        try:
            yield
        finally:
            platform.close()

    app = FastAPI(
        title="Weaves Platform API",
        version="0.1.0",
        description="Local v0 API for configuring and testing the Weaves platform path.",
        lifespan=lifespan,
    )
    allowed_origins = tuple(
        origin.strip().rstrip("/")
        for origin in os.environ.get(
            "CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080,http://127.0.0.1:8080",
        ).split(",")
        if origin.strip()
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
    )
    app.state.platform_runtime = platform

    @app.get("/", include_in_schema=False)
    def api_root() -> RedirectResponse:
        return RedirectResponse(url="/docs")

    @app.get("/api/v0/health")
    def health() -> dict[str, str]:
        try:
            platform.check_storage()
        except Exception as exc:
            raise HTTPException(status_code=503, detail="storage unavailable") from exc
        return {"status": "ok", "storage": platform.storage_mode}

    @app.get("/api/v0/organizations")
    def list_organizations() -> list[dict[str, Any]]:
        return [_dump(platform.organizations.get("local-org"))]

    @app.get("/api/v0/workspaces")
    def list_workspaces() -> list[dict[str, Any]]:
        return [_dump(item) for item in platform.workspaces.list_scoped("local-org")]

    @app.get("/api/v0/model-profiles")
    def list_model_profiles() -> list[dict[str, Any]]:
        platform.authorize("local-developer", Permission.MODELS_MANAGE)
        profiles = sorted(
            platform.model_profiles.list_scoped("local-org"),
            key=lambda item: item.id != platform.default_model_profile_id,
        )
        return [_dump(item) for item in profiles]

    @app.post("/api/v0/models/refresh")
    def refresh_models() -> list[dict[str, Any]]:
        platform.authorize("local-developer", Permission.MODELS_MANAGE)
        try:
            profiles = platform.refresh_openai_model_catalog()
        except ModelGatewayError as exc:
            raise HTTPException(status_code=502, detail=exc.message) from exc
        return [_dump(item) for item in profiles]

    @app.get("/api/v0/plugin-installations")
    def list_plugin_installations() -> list[dict[str, Any]]:
        platform.authorize("local-developer", Permission.PLUGINS_MANAGE)
        return [
            _dump(item)
            for item in platform.installations.list_scoped(
                "local-org", "local-workspace"
            )
        ]

    @app.get("/api/v0/capabilities")
    def list_capabilities() -> list[dict[str, Any]]:
        platform.authorize("local-developer", Permission.PLUGINS_MANAGE)
        descriptors = platform.plugins.list()
        return [
            _dump(capability)
            for descriptor in descriptors
            for capability in descriptor.capability_manifest
        ]

    @app.get("/api/v0/agents")
    def list_agents() -> list[dict[str, Any]]:
        platform.authorize("local-developer", Permission.AGENTS_MANAGE)
        return [
            _agent_view(platform, item)
            for item in platform.agents.list_scoped("local-org", "local-workspace")
        ]

    @app.post("/api/v0/agents", status_code=201)
    def create_agent(request: AgentCreateRequest) -> dict[str, Any]:
        try:
            agent = platform.create_agent(
                name=request.name,
                description=request.description,
                instructions=request.instructions,
                model_profile_id=request.model_profile_id,
                allowed_capability_ids=request.allowed_capability_ids,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Model profile not found"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _agent_view(platform, agent)

    @app.patch("/api/v0/agents/{agent_id}")
    def update_agent(agent_id: str, patch: AgentPatchRequest) -> dict[str, Any]:
        changes = {
            key: value
            for key, value in patch.model_dump(exclude_unset=True).items()
            if value is not None
        }
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
        return _agent_view(platform, agent)

    @app.get("/api/v0/artifacts")
    def list_artifacts(
        limit: int = Query(default=50, ge=1, le=100),
    ) -> list[dict[str, Any]]:
        platform.authorize("local-developer", Permission.ARTIFACTS_READ)
        artifacts = platform.artifacts.list_scoped("local-org", "local-workspace")
        ordered = sorted(artifacts, key=lambda item: item.created_at, reverse=True)[
            :limit
        ]
        return [_dump(item) for item in ordered]

    @app.get("/api/v0/agents/{agent_id}")
    def get_agent(agent_id: str) -> dict[str, Any]:
        platform.authorize("local-developer", Permission.AGENTS_MANAGE)
        try:
            agent = platform.agents.get_scoped(agent_id, "local-org", "local-workspace")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Agent not found") from exc
        return _agent_view(platform, agent)

    @app.get("/api/v0/workflows")
    def list_workflows() -> list[dict[str, Any]]:
        platform.authorize("local-developer", Permission.WORKFLOWS_RUN)
        return [
            _dump(item)
            for item in platform.workflows.list_scoped("local-org", "local-workspace")
        ]

    @app.post("/api/v0/runs", status_code=201)
    def create_run(request: RunCreateRequest) -> dict[str, Any]:
        try:
            result = platform.run_agent(task=request.task, agent_id=request.agent_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Agent or model profile not found"
            ) from exc
        except PluginGatewayError as exc:
            raise HTTPException(status_code=422, detail=exc.message) from exc
        except ModelGatewayError as exc:
            raise HTTPException(status_code=502, detail=exc.message) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "run": _dump(result.run),
            "agent_run": _dump(result.agent_run),
            "tool_invocations": [_dump(result.tool_invocation)],
            "artifacts": [_dump(result.artifact)],
            "audit_event": _dump(result.audit_event),
        }

    @app.get("/api/v0/runs")
    def list_runs(limit: int = Query(default=50, ge=1, le=100)) -> list[dict[str, Any]]:
        platform.authorize("local-developer", Permission.AGENTS_RUN)
        runs = platform.runs.list_scoped("local-org", "local-workspace")
        ordered = sorted(runs, key=lambda item: item.created_at, reverse=True)[:limit]
        return [_run_view(platform, item) for item in ordered]

    @app.get("/api/v0/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        platform.authorize("local-developer", Permission.AGENTS_RUN)
        try:
            run = platform.runs.get_scoped(run_id, "local-org", "local-workspace")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        return _run_view(platform, run)

    @app.get("/api/v0/runs/{run_id}/artifacts")
    def list_run_artifacts(run_id: str) -> list[dict[str, Any]]:
        platform.authorize("local-developer", Permission.ARTIFACTS_READ)
        _require_run(platform, run_id)
        return [
            _dump(item)
            for item in platform.artifacts.list_scoped("local-org", "local-workspace")
            if item.run_id == run_id
        ]

    @app.get("/api/v0/audit-events")
    def list_audit_events(
        limit: int = Query(default=50, ge=1, le=100),
    ) -> list[dict[str, Any]]:
        platform.authorize("local-developer", Permission.AUDIT_READ)
        events = platform.audit_events.list_scoped("local-org", "local-workspace")
        ordered = sorted(events, key=lambda item: item.created_at, reverse=True)[:limit]
        return [_dump(item) for item in ordered]

    return app


def _require_run(runtime: LocalPlatformRuntime, run_id: str) -> None:
    try:
        runtime.runs.get_scoped(run_id, "local-org", "local-workspace")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc


def _agent_view(runtime: LocalPlatformRuntime, agent: Any) -> dict[str, Any]:
    result = _dump(agent)
    if agent.current_version_id:
        result["current_version"] = _dump(
            # Agent definitions and versions are always looked up in their org/workspace.
            runtime.agent_versions.get_scoped(
                agent.current_version_id, agent.org_id, agent.workspace_id
            )
        )
    return result


def _run_view(runtime: LocalPlatformRuntime, run: Any) -> dict[str, Any]:
    result = _dump(run)
    result["agent_runs"] = [
        _dump(item)
        for item in runtime.agent_runs.list_scoped(run.org_id, run.workspace_id)
        if item.run_id == run.run_id
    ]
    result["tool_invocations"] = [
        _dump(item)
        for item in runtime.tool_invocations.list_scoped(run.org_id, run.workspace_id)
        if item.run_id == run.run_id
    ]
    result["artifacts"] = [
        _dump(item)
        for item in runtime.artifacts.list_scoped(run.org_id, run.workspace_id)
        if item.run_id == run.run_id
    ]
    return result


def _dump(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")


app = create_app()

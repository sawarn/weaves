"""Agent run, durable job, artifact history, and audit API routes."""

import json
from datetime import datetime
from typing import Any, Callable, Optional

from fastapi import FastAPI, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from weaves.product.contracts.v1 import Permission
from weaves.product.runtime import (
    AgentRuntimeBudgetExceeded,
    IdempotencyConflict,
    LocalPlatformRuntime,
    RunCostBudgetExceeded,
)
from weaves.product.runtime.model_gateway import ModelGatewayError
from weaves.product.runtime.plugin_gateway import PluginGatewayError
from weaves.product.runtime.request_identity import (
    effective_org_id,
    effective_workspace_id,
)


class RunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    task: str = Field(min_length=3, max_length=12000)
    agent_id: Optional[str] = Field(default=None, max_length=128)
    thread_id: Optional[str] = Field(default=None, max_length=128)


class ExecutionJobCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    task: str = Field(min_length=3, max_length=12000)
    agent_id: Optional[str] = Field(default=None, max_length=128)
    workflow_id: Optional[str] = Field(default=None, max_length=128)
    thread_id: Optional[str] = Field(default=None, max_length=128)


def _require_run(runtime: LocalPlatformRuntime, run_id: str) -> None:
    try:
        runtime.runs.get_scoped(run_id, effective_org_id(), effective_workspace_id())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc


def register_execution_routes(
    app: FastAPI,
    platform: LocalPlatformRuntime,
    dump: Callable[[BaseModel], dict[str, Any]],
    run_view: Callable[[LocalPlatformRuntime, Any], dict[str, Any]],
) -> None:
    """Register agent execution, run inspection, and audit endpoints."""
    _dump = dump
    _run_view = run_view

    @app.post("/api/v0/runs", status_code=201)
    def create_run(
        request: RunCreateRequest,
        idempotency_key: Optional[str] = Header(
            default=None, alias="Idempotency-Key", min_length=1, max_length=128
        ),
    ) -> dict[str, Any]:
        try:
            result = platform.run_agent(
                task=request.task,
                agent_id=request.agent_id,
                thread_id=request.thread_id,
                idempotency_key=idempotency_key,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="Agent, model profile, or conversation thread not found",
            ) from exc
        except PluginGatewayError as exc:
            raise HTTPException(status_code=422, detail=exc.message) from exc
        except ModelGatewayError as exc:
            raise HTTPException(status_code=502, detail=exc.message) from exc
        except RunCostBudgetExceeded as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except AgentRuntimeBudgetExceeded as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "run": _dump(result.run),
            "agent_run": _dump(result.agent_run),
            "agent_runs": [
                _dump(item)
                for item in (result.workflow_agent_runs or (result.agent_run,))
            ],
            "tool_invocations": [_dump(item) for item in result.tool_invocations],
            "artifacts": [
                _dump(item)
                for item in (result.workflow_artifacts or (result.artifact,))
            ],
            "audit_event": _dump(result.audit_event),
            "replayed": result.replayed,
        }

    @app.post("/api/v0/execution-jobs", status_code=202)
    def enqueue_execution_job(
        request: ExecutionJobCreateRequest,
        idempotency_key: Optional[str] = Header(
            default=None, alias="Idempotency-Key", min_length=1, max_length=128
        ),
    ) -> dict[str, Any]:
        if request.agent_id is not None and request.workflow_id is not None:
            raise HTTPException(
                status_code=422, detail="Choose either agent_id or workflow_id"
            )
        if platform.storage_mode != "postgres":
            raise HTTPException(
                status_code=503,
                detail="Durable execution jobs require PostgreSQL-backed storage",
            )
        try:
            job, replayed = platform.enqueue_agent_run(
                task=request.task,
                agent_id=request.agent_id,
                thread_id=request.thread_id,
                idempotency_key=idempotency_key,
                workflow_id=request.workflow_id,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Agent, workflow, or thread not found"
            ) from exc
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"job": _dump(job), "replayed": replayed}

    @app.get("/api/v0/execution-jobs")
    def list_execution_jobs(
        limit: int = Query(default=50, ge=1, le=100),
    ) -> list[dict[str, Any]]:
        return [_dump(item) for item in platform.list_execution_jobs(limit=limit)]

    @app.get("/api/v0/execution-jobs/{job_id}")
    def get_execution_job(job_id: str) -> dict[str, Any]:
        try:
            return _dump(platform.get_execution_job(job_id))
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Execution job not found"
            ) from exc

    @app.post("/api/v0/execution-jobs/{job_id}/cancel")
    def cancel_execution_job(job_id: str) -> dict[str, Any]:
        try:
            return _dump(platform.cancel_execution_job(job_id))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Execution job not found"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v0/execution-jobs/{job_id}/retry", status_code=202)
    def retry_execution_job(
        job_id: str,
        idempotency_key: str = Header(
            alias="Idempotency-Key", min_length=1, max_length=128
        ),
    ) -> dict[str, Any]:
        if platform.storage_mode != "postgres":
            raise HTTPException(
                status_code=503,
                detail="Durable execution job retries require PostgreSQL-backed storage",
            )
        try:
            job, replayed = platform.retry_execution_job(
                job_id, idempotency_key=idempotency_key
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Execution job not found"
            ) from exc
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"job": _dump(job), "replayed": replayed}

    @app.get("/api/v0/artifacts")
    def list_artifacts(
        limit: int = Query(default=50, ge=1, le=100),
    ) -> list[dict[str, Any]]:
        platform.authorize("local-developer", Permission.ARTIFACTS_READ)
        artifacts = platform.artifacts.list_scoped(
            effective_org_id(), effective_workspace_id()
        )
        ordered = sorted(artifacts, key=lambda item: item.created_at, reverse=True)[
            :limit
        ]
        return [_dump(item) for item in ordered]

    @app.get("/api/v0/runs")
    def list_runs(limit: int = Query(default=50, ge=1, le=100)) -> list[dict[str, Any]]:
        platform.authorize("local-developer", Permission.AGENTS_RUN)
        runs = platform.runs.list_scoped(effective_org_id(), effective_workspace_id())
        ordered = sorted(runs, key=lambda item: item.created_at, reverse=True)[:limit]
        return [_run_view(platform, item) for item in ordered]

    @app.get("/api/v0/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        platform.authorize("local-developer", Permission.AGENTS_RUN)
        try:
            run = platform.runs.get_scoped(
                run_id, effective_org_id(), effective_workspace_id()
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        return _run_view(platform, run)

    @app.get("/api/v0/runs/{run_id}/artifacts")
    def list_run_artifacts(run_id: str) -> list[dict[str, Any]]:
        platform.authorize("local-developer", Permission.ARTIFACTS_READ)
        _require_run(platform, run_id)
        return [
            _dump(item)
            for item in platform.artifacts.list_scoped(
                effective_org_id(), effective_workspace_id()
            )
            if item.run_id == run_id
        ]

    @app.get("/api/v0/audit-events")
    def list_audit_events(
        limit: int = Query(default=50, ge=1, le=100),
        action: Optional[str] = Query(default=None, min_length=1, max_length=128),
        target_type: Optional[str] = Query(default=None, min_length=1, max_length=128),
        target_id: Optional[str] = Query(default=None, min_length=1, max_length=128),
        actor_principal_id: Optional[str] = Query(
            default=None, min_length=1, max_length=128
        ),
        created_after: Optional[datetime] = None,
        created_before: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        try:
            events = platform.search_audit_events(
                action=action,
                target_type=target_type,
                target_id=target_id,
                actor_principal_id=actor_principal_id,
                created_after=created_after,
                created_before=created_before,
                limit=limit,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return [_dump(item) for item in events]

    @app.get("/api/v0/audit-events/export")
    def export_audit_events(
        limit: int = Query(default=500, ge=1, le=1000),
        cursor: Optional[str] = Query(default=None, max_length=1024),
        action: Optional[str] = Query(default=None, min_length=1, max_length=128),
        target_type: Optional[str] = Query(default=None, min_length=1, max_length=128),
        target_id: Optional[str] = Query(default=None, min_length=1, max_length=128),
        actor_principal_id: Optional[str] = Query(
            default=None, min_length=1, max_length=128
        ),
        created_after: Optional[datetime] = None,
        created_before: Optional[datetime] = None,
    ) -> Response:
        """Export one bounded NDJSON page; repeat with its cursor to continue."""
        try:
            events = platform.search_audit_events(
                action=action,
                target_type=target_type,
                target_id=target_id,
                actor_principal_id=actor_principal_id,
                created_after=created_after,
                created_before=created_before,
                limit=limit + 1,
                cursor=cursor,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        page = events[:limit]
        headers = {"Cache-Control": "no-store"}
        if len(events) > limit and page:
            headers["X-Next-Cursor"] = platform.audit_event_cursor(page[-1])
        return Response(
            content="".join(
                json.dumps(_dump(event), separators=(",", ":")) + "\n" for event in page
            ),
            media_type="application/x-ndjson",
            headers=headers,
        )

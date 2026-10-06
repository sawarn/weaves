"""Workflow, schedule, and webhook API routes."""

import json
from typing import Any, Callable, Literal, Optional

from fastapi import FastAPI, Header, HTTPException, Query, Request
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    ValidationError,
)

from weaves.product.contracts.v1 import (
    Permission,
    WorkflowConditionOperator,
    WorkflowJoinPolicy,
    WorkflowParallelGroup,
    WorkflowScheduleStatus,
    WorkflowStatus,
    WorkflowStepCondition,
    WorkflowStepDependency,
    WorkflowTriggerStatus,
)
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


class WorkflowRunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    task: str = Field(min_length=3, max_length=12000)
    thread_id: Optional[str] = Field(default=None, max_length=128)


class WorkflowCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=2, max_length=160)
    description: str = Field(default="", max_length=2000)
    agent_id: Optional[str] = Field(default=None, min_length=1, max_length=128)
    agent_ids: Optional[tuple[str, ...]] = Field(
        default=None, min_length=1, max_length=10
    )


class WorkflowPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: Optional[str] = Field(default=None, min_length=2, max_length=160)
    description: Optional[str] = Field(default=None, max_length=2000)
    status: Optional[WorkflowStatus] = None


class WorkflowStepsReplaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    agent_ids: tuple[str, ...] = Field(min_length=1, max_length=10)
    step_conditions: tuple["WorkflowStepConditionRequest", ...] = Field(
        default=(), max_length=10
    )
    parallel_groups: tuple["WorkflowParallelGroupRequest", ...] = Field(
        default=(), max_length=5
    )
    step_dependencies: tuple["WorkflowStepDependencyRequest", ...] = Field(
        default=(), max_length=9
    )


class WorkflowStepConditionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_agent_id: str = Field(min_length=1, max_length=128)
    target_agent_id: str = Field(min_length=1, max_length=128)
    json_pointer: str = Field(max_length=512)
    operator: WorkflowConditionOperator
    expected_value: Optional[JsonValue] = None


class WorkflowParallelGroupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    agent_ids: tuple[str, ...] = Field(min_length=2, max_length=5)


class WorkflowStepDependencyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    target_agent_id: str = Field(min_length=1, max_length=128)
    depends_on_agent_ids: tuple[str, ...] = Field(min_length=1, max_length=9)
    join_policy: Literal["all", "any"] = "all"


class WorkflowTriggerCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=160)
    task_instructions: str = Field(min_length=1, max_length=2000)


class WorkflowTriggerPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: WorkflowTriggerStatus


class WorkflowScheduleCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=160)
    task_instructions: str = Field(min_length=1, max_length=2000)
    interval_seconds: int = Field(ge=60, le=31_536_000)


class WorkflowSchedulePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["active", "disabled"]


def _workflow_trigger_view(trigger: BaseModel) -> dict[str, Any]:
    result = trigger.model_dump(mode="json")
    result.pop("secret_digest", None)
    result["has_secret"] = True
    return result


def register_workflow_routes(
    app: FastAPI,
    platform: LocalPlatformRuntime,
    dump: Callable[[BaseModel], dict[str, Any]],
    run_view: Callable[[LocalPlatformRuntime, Any], dict[str, Any]],
) -> None:
    """Register workflow definitions and trigger/schedule endpoints."""
    _dump = dump
    _run_view = run_view

    @app.get("/api/v0/workflows")
    def list_workflows() -> list[dict[str, Any]]:
        platform.authorize("local-developer", Permission.WORKFLOWS_RUN)
        return [
            _dump(item)
            for item in platform.workflows.list_scoped(
                effective_org_id(), effective_workspace_id()
            )
        ]

    @app.get("/api/v0/workflows/{workflow_id}")
    def get_workflow(workflow_id: str) -> dict[str, Any]:
        platform.authorize("local-developer", Permission.WORKFLOWS_RUN)
        try:
            workflow = platform.workflows.get_scoped(
                workflow_id, effective_org_id(), effective_workspace_id()
            )
            version = platform.workflow_versions.get_scoped(
                workflow.current_version_id or "",
                workflow.org_id,
                workflow.workspace_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Workflow not found") from exc
        return {"definition": _dump(workflow), "version": _dump(version)}

    @app.get("/api/v0/workflows/{workflow_id}/versions")
    def list_workflow_versions(
        workflow_id: str,
        limit: int = Query(default=50, ge=1, le=100),
        before_version: Optional[int] = Query(default=None, ge=1),
    ) -> dict[str, Any]:
        try:
            versions = platform.list_workflow_versions(
                workflow_id, limit=limit + 1, before_version=before_version
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Workflow not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "items": [_dump(item) for item in versions[:limit]],
            "next_before_version": (
                versions[limit - 1].version if len(versions) > limit else None
            ),
        }

    @app.get("/api/v0/workflows/{workflow_id}/versions/{workflow_version_id}")
    def get_workflow_version(
        workflow_id: str, workflow_version_id: str
    ) -> dict[str, Any]:
        try:
            return _dump(
                platform.get_workflow_version(workflow_id, workflow_version_id)
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Workflow version not found"
            ) from exc

    @app.get("/api/v0/workflows/{workflow_id}/runs")
    def list_workflow_runs(
        workflow_id: str,
        limit: int = Query(default=50, ge=1, le=100),
        cursor: Optional[str] = Query(default=None, max_length=1024),
    ) -> dict[str, Any]:
        try:
            runs = platform.list_workflow_runs(
                workflow_id, limit=limit + 1, cursor=cursor
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Workflow not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        page = runs[:limit]
        return {
            "items": [_run_view(platform, item) for item in page],
            "next_cursor": (
                platform.workflow_run_cursor(page[-1])
                if len(runs) > limit and page
                else None
            ),
        }

    @app.post("/api/v0/workflows", status_code=201)
    def create_workflow(request: WorkflowCreateRequest) -> dict[str, Any]:
        if (request.agent_id is None) == (request.agent_ids is None):
            raise HTTPException(
                status_code=422,
                detail="Provide exactly one of agent_id or agent_ids",
            )
        try:
            workflow = platform.create_workflow(**request.model_dump())
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Agent not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        version = platform.workflow_versions.get_scoped(
            workflow.current_version_id or "",
            workflow.org_id,
            workflow.workspace_id,
        )
        return {"definition": _dump(workflow), "version": _dump(version)}

    @app.get("/api/v0/workflow-triggers")
    def list_workflow_triggers() -> list[dict[str, Any]]:
        try:
            return [
                _workflow_trigger_view(item)
                for item in platform.list_workflow_triggers()
            ]
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.post("/api/v0/workflows/{workflow_id}/triggers", status_code=201)
    def create_workflow_trigger(
        workflow_id: str, request: WorkflowTriggerCreateRequest
    ) -> dict[str, Any]:
        if platform.storage_mode != "postgres":
            raise HTTPException(
                status_code=503,
                detail="Webhook workflow triggers require PostgreSQL-backed storage",
            )
        try:
            trigger, token = platform.create_workflow_trigger(
                workflow_id,
                name=request.name,
                task_instructions=request.task_instructions,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Workflow not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "trigger": _workflow_trigger_view(trigger),
            "webhook_url": f"/api/v0/webhooks/{trigger.trigger_id}",
            "secret": token,
        }

    @app.get("/api/v0/workflow-schedules")
    def list_workflow_schedules() -> list[dict[str, Any]]:
        try:
            return [_dump(item) for item in platform.list_workflow_schedules()]
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.post("/api/v0/workflows/{workflow_id}/schedules", status_code=201)
    def create_workflow_schedule(
        workflow_id: str, request: WorkflowScheduleCreateRequest
    ) -> dict[str, Any]:
        if platform.storage_mode != "postgres":
            raise HTTPException(
                status_code=503,
                detail="Workflow schedules require PostgreSQL-backed storage",
            )
        try:
            schedule = platform.create_workflow_schedule(
                workflow_id,
                name=request.name,
                task_instructions=request.task_instructions,
                interval_seconds=request.interval_seconds,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Workflow not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _dump(schedule)

    @app.patch("/api/v0/workflow-schedules/{schedule_id}")
    def update_workflow_schedule(
        schedule_id: str, patch: WorkflowSchedulePatchRequest
    ) -> dict[str, Any]:
        try:
            schedule = platform.update_workflow_schedule(
                schedule_id, WorkflowScheduleStatus(patch.status)
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Workflow schedule not found"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _dump(schedule)

    @app.patch("/api/v0/workflow-triggers/{trigger_id}")
    def update_workflow_trigger(
        trigger_id: str, patch: WorkflowTriggerPatchRequest
    ) -> dict[str, Any]:
        try:
            trigger = platform.update_workflow_trigger(trigger_id, patch.status)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Workflow trigger not found"
            ) from exc
        return _workflow_trigger_view(trigger)

    @app.put("/api/v0/workflow-triggers/{trigger_id}/secret")
    def rotate_workflow_trigger_secret(trigger_id: str) -> dict[str, Any]:
        try:
            trigger, token = platform.rotate_workflow_trigger_secret(trigger_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Workflow trigger not found"
            ) from exc
        return {"trigger": _workflow_trigger_view(trigger), "secret": token}

    @app.patch("/api/v0/workflows/{workflow_id}")
    def update_workflow(
        workflow_id: str, patch: WorkflowPatchRequest
    ) -> dict[str, Any]:
        changes = patch.model_dump(exclude_unset=True)
        if not changes:
            raise HTTPException(status_code=400, detail="No changes supplied")
        try:
            return _dump(platform.update_workflow(workflow_id, **changes))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Workflow not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.put("/api/v0/workflows/{workflow_id}/steps")
    def replace_workflow_steps(
        workflow_id: str, request: WorkflowStepsReplaceRequest
    ) -> dict[str, Any]:
        try:
            condition_contracts: list[WorkflowStepCondition] = []
            for item in request.step_conditions:
                payload = item.model_dump(exclude_unset=True)
                if (
                    item.operator is WorkflowConditionOperator.EXISTS
                    and "expected_value" not in payload
                ):
                    payload["expected_value"] = None
                condition_contracts.append(
                    WorkflowStepCondition.model_validate(payload)
                )
            conditions = tuple(condition_contracts)
            parallel_groups = tuple(
                WorkflowParallelGroup.model_validate(item.model_dump())
                for item in request.parallel_groups
            )
            step_dependencies = tuple(
                WorkflowStepDependency(
                    target_agent_id=item.target_agent_id,
                    depends_on_agent_ids=item.depends_on_agent_ids,
                    join_policy=WorkflowJoinPolicy(item.join_policy),
                )
                for item in request.step_dependencies
            )
            workflow = platform.replace_workflow_agents(
                workflow_id,
                request.agent_ids,
                conditions,
                parallel_groups=parallel_groups,
                step_dependencies=step_dependencies,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Agent or workflow not found"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc
        version = platform.workflow_versions.get_scoped(
            workflow.current_version_id or "",
            workflow.org_id,
            workflow.workspace_id,
        )
        return {"definition": _dump(workflow), "version": _dump(version)}

    @app.post("/api/v0/workflows/{workflow_id}/runs", status_code=201)
    def create_workflow_run(
        workflow_id: str,
        request: WorkflowRunCreateRequest,
        idempotency_key: Optional[str] = Header(
            default=None, alias="Idempotency-Key", min_length=1, max_length=128
        ),
    ) -> dict[str, Any]:
        try:
            result = platform.run_workflow(
                workflow_id=workflow_id,
                task=request.task,
                thread_id=request.thread_id,
                idempotency_key=idempotency_key,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Workflow not found") from exc
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

    @app.post("/api/v0/webhooks/{trigger_id}", status_code=202)
    async def receive_workflow_webhook(
        trigger_id: str,
        request: Request,
        event_id: str = Header(alias="X-Event-ID", min_length=1, max_length=128),
        trigger_secret: str = Header(
            alias="X-Workflow-Trigger-Secret", min_length=1, max_length=512
        ),
    ) -> dict[str, Any]:
        if platform.storage_mode != "postgres":
            raise HTTPException(
                status_code=503,
                detail="Webhook workflow triggers require PostgreSQL-backed storage",
            )
        content_type = request.headers.get("content-type", "").split(";", 1)[0]
        if content_type.strip().casefold() != "application/json":
            raise HTTPException(
                status_code=415, detail="Content-Type must be application/json"
            )
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > 8_192:
                    raise HTTPException(
                        status_code=413, detail="Webhook payload is too large"
                    )
            except ValueError as exc:
                raise HTTPException(
                    status_code=400, detail="Invalid Content-Length"
                ) from exc
        raw_payload = bytearray()
        async for chunk in request.stream():
            raw_payload.extend(chunk)
            if len(raw_payload) > 8_192:
                raise HTTPException(
                    status_code=413, detail="Webhook payload is too large"
                )
        try:
            decoded = json.loads(raw_payload.decode("utf-8"))
            payload = TypeAdapter(dict[str, JsonValue]).validate_python(decoded)
        except (ValueError, RecursionError, ValidationError) as exc:
            raise HTTPException(
                status_code=422, detail="Webhook body must be a JSON object"
            ) from exc
        try:
            job, replayed = platform.enqueue_workflow_trigger_event(
                trigger_id, trigger_secret, event_id, payload
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Workflow trigger not found"
            ) from exc
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"job": _dump(job), "replayed": replayed}

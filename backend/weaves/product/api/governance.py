"""Approval policy and safe-write governance API routes."""

from typing import Any, Callable, Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from weaves.product.contracts.v1 import ApprovalStatus, Permission, RiskLevel
from weaves.product.runtime import LocalPlatformRuntime
from weaves.product.runtime.plugin_gateway import PluginGatewayError
from weaves.product.runtime.request_identity import (
    effective_org_id,
    effective_workspace_id,
)


class ApprovalPolicyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=160)
    required_risk_levels: tuple[RiskLevel, ...] = (
        RiskLevel.MEDIUM,
        RiskLevel.HIGH,
        RiskLevel.CRITICAL,
    )
    allow_self_approval: bool = False
    enabled: bool = True


class ApprovalPolicyPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    required_risk_levels: Optional[tuple[RiskLevel, ...]] = None
    allow_self_approval: Optional[bool] = None
    enabled: Optional[bool] = None


class RunActionProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    capability_id: Literal["jira.issues.comment"]
    issue_key: str = Field(min_length=3, max_length=60)
    comment: str = Field(min_length=1, max_length=4000)
    agent_run_id: Optional[str] = Field(default=None, max_length=128)


class ApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    approved: bool
    decision_comment: Optional[str] = Field(default=None, max_length=1000)


def _require_run(runtime: LocalPlatformRuntime, run_id: str) -> None:
    try:
        runtime.runs.get_scoped(run_id, effective_org_id(), effective_workspace_id())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc


def _approval_view(
    runtime: LocalPlatformRuntime,
    approval: Any,
    dump: Callable[[BaseModel], dict[str, Any]],
) -> dict[str, Any]:
    result = dump(approval)
    result["tool_invocations"] = [
        dump(item)
        for item in runtime.tool_invocations.list_scoped(
            approval.org_id, approval.workspace_id
        )
        if item.approval_request_id == approval.approval_request_id
    ]
    return result


def register_governance_routes(
    app: FastAPI,
    platform: LocalPlatformRuntime,
    dump: Callable[[BaseModel], dict[str, Any]],
) -> None:
    """Register approval policies, proposals, and reviewer decisions."""
    _dump = dump

    @app.get("/api/v0/approval-policies")
    def list_approval_policies() -> list[dict[str, Any]]:
        try:
            return [_dump(item) for item in platform.list_approval_policies()]
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.get("/api/v0/approval-policies/{policy_id}")
    def get_approval_policy(policy_id: str) -> dict[str, Any]:
        try:
            return _dump(platform.get_approval_policy(policy_id))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Approval policy not found"
            ) from exc

    @app.post("/api/v0/approval-policies", status_code=201)
    def create_approval_policy(
        request: ApprovalPolicyCreateRequest,
    ) -> dict[str, Any]:
        try:
            policy = platform.create_approval_policy(**request.model_dump())
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _dump(policy)

    @app.patch("/api/v0/approval-policies/{policy_id}")
    def update_approval_policy(
        policy_id: str, patch: ApprovalPolicyPatchRequest
    ) -> dict[str, Any]:
        changes = patch.model_dump(exclude_unset=True)
        if not changes:
            raise HTTPException(status_code=400, detail="No changes supplied")
        try:
            policy = platform.update_approval_policy(policy_id, **changes)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Approval policy not found"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _dump(policy)

    @app.get("/api/v0/approvals")
    def list_approvals(
        status: Optional[ApprovalStatus] = None,
        limit: int = Query(default=50, ge=1, le=100),
    ) -> list[dict[str, Any]]:
        platform.authorize("local-developer", Permission.ACTIONS_APPROVE)
        approvals = platform.approvals.list_scoped(
            effective_org_id(), effective_workspace_id()
        )
        if status is not None:
            approvals = tuple(item for item in approvals if item.status is status)
        ordered = sorted(approvals, key=lambda item: item.requested_at, reverse=True)[
            :limit
        ]
        return [_approval_view(platform, item, _dump) for item in ordered]

    @app.post("/api/v0/runs/{run_id}/actions", status_code=201)
    def propose_run_action(
        run_id: str, request: RunActionProposalRequest
    ) -> dict[str, Any]:
        try:
            if request.capability_id != "jira.issues.comment":
                raise ValueError("unsupported action capability")
            approval, invocation = platform.propose_jira_comment(
                run_id,
                issue_key=request.issue_key,
                comment=request.comment,
                agent_run_id=request.agent_run_id,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        except PluginGatewayError as exc:
            raise HTTPException(status_code=422, detail=exc.message) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"approval": _dump(approval), "tool_invocation": _dump(invocation)}

    @app.post("/api/v0/approvals/{approval_id}/decision")
    def decide_approval(
        approval_id: str, request: ApprovalDecisionRequest
    ) -> dict[str, Any]:
        try:
            approval, invocation = platform.decide_approval(
                approval_id,
                approved=request.approved,
                decision_comment=request.decision_comment,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Approval request not found"
            ) from exc
        except PluginGatewayError as exc:
            raise HTTPException(status_code=502, detail=exc.message) from exc
        except ValueError as exc:
            status_code = 409 if "already resolved" in str(exc) else 422
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc
        return {"approval": _dump(approval), "tool_invocation": _dump(invocation)}

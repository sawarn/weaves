"""Durable, persistence-agnostic execution and governance contracts."""

import json
import re
from decimal import Decimal
from typing import Any, Optional

from pydantic import (
    AwareDatetime,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from weaves.product.contracts.v1.agents import AgentVersion
from weaves.product.contracts.v1.base import (
    FrozenProductContract,
    MutableWorkspaceScopedContract,
    OpaqueId,
    ProductContract,
    StrEnum,
)
from weaves.product.contracts.v1.json_data import (
    freeze_json_value,
    reject_credential_fields,
    thaw_json_value,
)
from weaves.product.contracts.v1.plugins import Identifier, RiskLevel
from weaves.product.contracts.v1.workflows import WorkflowVersion

MAX_AGENT_RUN_OUTPUT_SUMMARY_BYTES = 2_097_152


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class InvocationStatus(StrEnum):
    PENDING = "pending"
    AWAITING_APPROVAL = "awaiting_approval"
    DENIED = "denied"
    APPROVED = "approved"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    SKIPPED = "skipped"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ApprovalPolicy(MutableWorkspaceScopedContract):
    """Workspace policy deciding which capability risks require human review."""

    approval_policy_id: OpaqueId
    name: str = Field(min_length=1, max_length=160)
    required_risk_levels: tuple[RiskLevel, ...] = Field(
        default=(RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL),
        max_length=4,
    )
    allow_self_approval: bool = False
    enabled: bool = True

    @model_validator(mode="after")
    def risk_levels_are_unique(self) -> "ApprovalPolicy":
        if len(self.required_risk_levels) != len(set(self.required_risk_levels)):
            raise ValueError("required risk levels must be unique")
        return self


class ArtifactStatus(StrEnum):
    AVAILABLE = "available"
    DELETED = "deleted"


class ArtifactSensitivity(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class RetentionClass(StrEnum):
    EPHEMERAL = "ephemeral"
    STANDARD = "standard"
    REGULATED = "regulated"
    LOCKED = "locked"


class AuditTargetScope(StrEnum):
    ORGANIZATION = "organization"
    WORKSPACE = "workspace"


class ErrorSummary(FrozenProductContract):
    """Bounded user-safe error details; stack traces and provider payloads do not belong here."""

    code: Identifier
    summary: str = Field(min_length=1, max_length=1000)
    retryable: bool = False

    @field_validator("summary")
    @classmethod
    def summary_is_sanitized(cls, value: str) -> str:
        if re.search(
            r"(?i)(bearer\s+\S+|(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)\s*[:=]\s*\S+)",
            value,
        ):
            raise ValueError("summary must not contain credential values")
        return value


class WorkflowRun(MutableWorkspaceScopedContract):
    run_id: OpaqueId
    workflow_id: OpaqueId
    workflow_version_id: OpaqueId
    requested_by_principal_id: OpaqueId
    trigger_type: Identifier
    trigger_ref: Optional[OpaqueId] = None
    idempotency_key: Optional[OpaqueId] = None
    status: RunStatus
    started_at: Optional[AwareDatetime] = None
    finished_at: Optional[AwareDatetime] = None
    error: Optional[ErrorSummary] = None

    @model_validator(mode="after")
    def timestamps_match_status(self) -> "WorkflowRun":
        if self.status is RunStatus.QUEUED and (self.started_at or self.finished_at):
            raise ValueError("queued runs cannot have start or finish timestamps")
        if self.status is RunStatus.RUNNING and (
            self.started_at is None or self.finished_at is not None
        ):
            raise ValueError(
                "running runs require started_at and cannot have finished_at"
            )
        if self.status in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}:
            if self.started_at is None or self.finished_at is None:
                raise ValueError("terminal runs require started_at and finished_at")
        if (self.status is RunStatus.FAILED) != (self.error is not None):
            raise ValueError(
                "failed runs require an error summary and other statuses must omit it"
            )
        return self


class ExecutionJob(MutableWorkspaceScopedContract):
    """Durable request envelope for work processed by a separate worker."""

    job_id: OpaqueId
    requested_by_principal_id: OpaqueId
    task: str = Field(min_length=1, max_length=12_000)
    agent_id: Optional[OpaqueId] = None
    workflow_id: Optional[OpaqueId] = None
    workflow_version_id: Optional[OpaqueId] = None
    thread_id: Optional[OpaqueId] = None
    trigger_id: Optional[OpaqueId] = None
    trigger_event_id: Optional[OpaqueId] = None
    schedule_id: Optional[OpaqueId] = None
    schedule_occurrence_at: Optional[AwareDatetime] = None
    evaluation_id: Optional[OpaqueId] = None
    evaluation_suite_id: Optional[OpaqueId] = None
    retry_of_job_id: Optional[OpaqueId] = None
    idempotency_key: Optional[OpaqueId] = None
    status: ExecutionJobStatus
    attempts: int = Field(default=0, ge=0, le=100)
    worker_id: Optional[OpaqueId] = None
    run_id: Optional[OpaqueId] = None
    started_at: Optional[AwareDatetime] = None
    finished_at: Optional[AwareDatetime] = None
    error: Optional[ErrorSummary] = None

    @model_validator(mode="after")
    def fields_match_status(self) -> "ExecutionJob":
        if self.agent_id is not None and self.workflow_id is not None:
            raise ValueError("execution jobs cannot target both an agent and workflow")
        if self.workflow_version_id is not None and self.workflow_id is None:
            raise ValueError("workflow_version_id requires a workflow_id")
        if (self.trigger_id is None) != (self.trigger_event_id is None):
            raise ValueError("trigger jobs require both trigger and event IDs")
        if (self.schedule_id is None) != (self.schedule_occurrence_at is None):
            raise ValueError("scheduled jobs require both schedule and occurrence IDs")
        if (self.evaluation_id is None) != (self.evaluation_suite_id is None):
            raise ValueError("evaluation jobs require both evaluation IDs")
        if (
            sum(
                source is not None
                for source in (self.trigger_id, self.schedule_id, self.evaluation_id)
            )
            > 1
        ):
            raise ValueError("execution jobs cannot have multiple trigger sources")
        if (self.trigger_id is not None or self.schedule_id is not None) and (
            self.workflow_id is None
        ):
            raise ValueError("workflow triggers can only enqueue workflow jobs")
        if self.evaluation_id is not None and (
            self.agent_id is not None or self.workflow_id is not None
        ):
            raise ValueError("evaluation jobs cannot target an agent or workflow")
        if self.retry_of_job_id == self.job_id:
            raise ValueError("execution jobs cannot retry themselves")
        if self.retry_of_job_id is not None and self.idempotency_key is None:
            raise ValueError("retried jobs require an idempotency key")
        if self.status is ExecutionJobStatus.QUEUED:
            if (
                any(
                    value is not None
                    for value in (
                        self.worker_id,
                        self.run_id,
                        self.started_at,
                        self.finished_at,
                        self.error,
                    )
                )
                or self.attempts != 0
            ):
                raise ValueError("queued jobs cannot have execution state")
        elif self.status in {
            ExecutionJobStatus.RUNNING,
            ExecutionJobStatus.CANCEL_REQUESTED,
        }:
            if (
                self.attempts < 1
                or self.worker_id is None
                or self.started_at is None
                or self.finished_at is not None
                or self.error is not None
            ):
                raise ValueError("active jobs require worker and start state")
        elif self.status is ExecutionJobStatus.SUCCEEDED:
            if self.attempts < 1 or self.started_at is None or self.finished_at is None:
                raise ValueError("terminal jobs require execution timestamps")
            if (self.run_id is None) == (self.evaluation_id is None):
                raise ValueError("succeeded jobs require one run or evaluation")
            if self.error is not None:
                raise ValueError("succeeded jobs cannot have an error")
        elif self.status is ExecutionJobStatus.FAILED:
            if self.attempts < 1 or self.started_at is None or self.finished_at is None:
                raise ValueError("terminal jobs require execution timestamps")
            if self.error is None:
                raise ValueError("failed jobs require an error summary")
        elif self.status is ExecutionJobStatus.CANCELLED:
            if self.finished_at is None or self.error is not None:
                raise ValueError("cancelled jobs require a finish time and no error")
            if self.attempts == 0:
                if any(
                    value is not None
                    for value in (self.worker_id, self.run_id, self.started_at)
                ):
                    raise ValueError(
                        "cancelled queued jobs cannot have execution state"
                    )
            elif self.worker_id is None or self.started_at is None:
                raise ValueError(
                    "cancelled running jobs require worker and start state"
                )
        return self


class AgentRun(MutableWorkspaceScopedContract):
    agent_run_id: OpaqueId
    run_id: OpaqueId
    agent_id: OpaqueId
    agent_version_id: OpaqueId
    model_profile_id: OpaqueId
    resolved_provider_id: OpaqueId
    resolved_model_id: OpaqueId
    status: RunStatus
    input_summary: dict[str, Any] = Field(default_factory=dict)
    output_summary: Optional[dict[str, Any]] = None
    input_tokens: Optional[int] = Field(default=None, ge=0)
    output_tokens: Optional[int] = Field(default=None, ge=0)
    estimated_cost_usd: Optional[Decimal] = Field(
        default=None, ge=Decimal("0"), max_digits=18, decimal_places=12
    )
    started_at: Optional[AwareDatetime] = None
    finished_at: Optional[AwareDatetime] = None
    error: Optional[ErrorSummary] = None

    @field_validator("input_summary", "output_summary")
    @classmethod
    def summaries_are_bounded_json(cls, value: Any, info: Any) -> Any:
        if value is None:
            return None
        reject_credential_fields(value, info.field_name)
        frozen = freeze_json_value(value, info.field_name)
        max_bytes = (
            16_384
            if info.field_name == "input_summary"
            else MAX_AGENT_RUN_OUTPUT_SUMMARY_BYTES
        )
        encoded = json.dumps(
            thaw_json_value(frozen), allow_nan=False, ensure_ascii=False
        ).encode("utf-8")
        if len(encoded) > max_bytes:
            raise ValueError(
                f"{info.field_name} must not exceed {max_bytes} serialized bytes"
            )
        return frozen

    @field_serializer("input_summary", "output_summary")
    def serialize_summaries(self, value: Any) -> Any:
        return thaw_json_value(value) if value is not None else None

    @model_validator(mode="after")
    def timestamps_match_status(self) -> "AgentRun":
        _validate_execution_timestamps(
            self.status, self.started_at, self.finished_at, self.error
        )
        return self


class ToolInvocation(MutableWorkspaceScopedContract):
    invocation_id: OpaqueId
    run_id: OpaqueId
    agent_run_id: Optional[OpaqueId] = None
    plugin_installation_id: OpaqueId
    capability_id: Identifier
    status: InvocationStatus
    risk_level: RiskLevel
    approval_request_id: Optional[OpaqueId] = None
    input_artifact_ids: tuple[OpaqueId, ...] = Field(
        default_factory=tuple, max_length=100
    )
    output_artifact_ids: tuple[OpaqueId, ...] = Field(
        default_factory=tuple, max_length=100
    )
    input_summary: dict[str, Any] = Field(default_factory=dict)
    output_summary: Optional[dict[str, Any]] = None
    created_at: AwareDatetime
    started_at: Optional[AwareDatetime] = None
    finished_at: Optional[AwareDatetime] = None
    duration_ms: Optional[int] = Field(default=None, ge=0, le=86_400_000)
    error: Optional[ErrorSummary] = None

    @field_validator("input_summary", "output_summary")
    @classmethod
    def summaries_are_bounded_json(cls, value: Any, info: Any) -> Any:
        if value is None:
            return None
        reject_credential_fields(value, info.field_name)
        frozen = freeze_json_value(value, info.field_name)
        if len(json.dumps(thaw_json_value(frozen), allow_nan=False)) > 16_384:
            raise ValueError(f"{info.field_name} must not exceed 16 KiB")
        return frozen

    @field_serializer("input_summary", "output_summary")
    def serialize_summaries(self, value: Any) -> Any:
        return thaw_json_value(value) if value is not None else None

    @model_validator(mode="after")
    def invocation_fields_match_outcome(self) -> "ToolInvocation":
        execution_terminal = self.status in {
            InvocationStatus.SUCCEEDED,
            InvocationStatus.FAILED,
            InvocationStatus.TIMED_OUT,
        }
        terminal = execution_terminal or self.status in {
            InvocationStatus.DENIED,
            InvocationStatus.SKIPPED,
        }
        if terminal and self.finished_at is None:
            raise ValueError("terminal invocations require finished_at")
        if not terminal and self.finished_at is not None:
            raise ValueError("non-terminal invocations cannot have finished_at")
        if self.status is InvocationStatus.EXECUTING and self.started_at is None:
            raise ValueError("executing invocations require started_at")
        if execution_terminal and (self.started_at is None or self.duration_ms is None):
            raise ValueError("completed executions require started_at and duration_ms")
        if (
            self.status in {InvocationStatus.FAILED, InvocationStatus.TIMED_OUT}
            and self.error is None
        ):
            raise ValueError(
                "failed and timed-out invocations require an error summary"
            )
        if (
            self.status not in {InvocationStatus.FAILED, InvocationStatus.TIMED_OUT}
            and self.error is not None
        ):
            raise ValueError(
                "only failed and timed-out invocations may include an error summary"
            )
        if (
            self.status
            in {
                InvocationStatus.AWAITING_APPROVAL,
                InvocationStatus.DENIED,
                InvocationStatus.APPROVED,
            }
            and self.approval_request_id is None
        ):
            raise ValueError(
                "approval-related invocation states require approval_request_id"
            )
        if (
            self.started_at is not None
            and self.finished_at is not None
            and self.finished_at < self.started_at
        ):
            raise ValueError("finished_at cannot precede started_at")
        return self


class ArtifactProvenance(FrozenProductContract):
    source_type: Identifier
    source_ref: str = Field(min_length=1, max_length=256)
    recorded_at: AwareDatetime


class Artifact(MutableWorkspaceScopedContract):
    artifact_id: OpaqueId
    run_id: OpaqueId
    agent_run_id: Optional[OpaqueId] = None
    artifact_type: Identifier
    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(default="", max_length=120_000)
    content_ref: OpaqueId
    content_type: Identifier
    checksum: Optional[str] = Field(default=None, max_length=256)
    provenance: tuple[ArtifactProvenance, ...] = Field(min_length=1, max_length=50)
    sensitivity: ArtifactSensitivity
    retention_class: RetentionClass
    status: ArtifactStatus
    created_by_agent_run_id: Optional[OpaqueId] = None
    created_at: AwareDatetime
    deleted_at: Optional[AwareDatetime] = None

    @model_validator(mode="after")
    def deletion_timestamp_matches_status(self) -> "Artifact":
        if (self.status is ArtifactStatus.DELETED) != (self.deleted_at is not None):
            raise ValueError(
                "deleted artifacts require deleted_at; available artifacts must omit it"
            )
        return self


class ApprovalRequest(MutableWorkspaceScopedContract):
    approval_request_id: OpaqueId
    run_id: OpaqueId
    requested_by_agent_run_id: Optional[OpaqueId] = None
    requested_by_principal_id: OpaqueId
    capability_id: Identifier
    action_summary: str = Field(min_length=1, max_length=1000)
    risk_level: RiskLevel
    status: ApprovalStatus
    requested_at: AwareDatetime
    resolved_by_principal_id: Optional[OpaqueId] = None
    resolved_at: Optional[AwareDatetime] = None
    decision_comment: Optional[str] = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def decision_has_actor_and_time(self) -> "ApprovalRequest":
        resolved = self.status is not ApprovalStatus.PENDING
        if resolved != (
            self.resolved_by_principal_id is not None and self.resolved_at is not None
        ):
            raise ValueError("resolved approvals require both decision actor and time")
        if not resolved and (
            self.resolved_by_principal_id is not None or self.resolved_at is not None
        ):
            raise ValueError("pending approvals cannot have decision actor or time")
        return self


class AuditEvent(FrozenProductContract):
    audit_event_id: OpaqueId
    org_id: OpaqueId
    target_scope: AuditTargetScope
    workspace_id: Optional[OpaqueId] = None
    actor_principal_id: OpaqueId
    action: Identifier
    target_type: Identifier
    target_id: OpaqueId
    summary: str = Field(default="", max_length=1000)
    request_id: OpaqueId
    correlation_id: Optional[OpaqueId] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: AwareDatetime

    @field_validator("metadata")
    @classmethod
    def metadata_is_bounded_and_non_secret(cls, value: dict[str, Any]) -> Any:
        reject_credential_fields(value, "metadata")
        frozen = freeze_json_value(value, "metadata")
        if len(json.dumps(thaw_json_value(frozen), allow_nan=False)) > 8192:
            raise ValueError("metadata must not exceed 8 KiB")
        return frozen

    @field_serializer("metadata")
    def serialize_metadata(self, value: Any) -> Any:
        return thaw_json_value(value)

    @model_validator(mode="after")
    def workspace_target_is_scoped(self) -> "AuditEvent":
        if (self.target_scope is AuditTargetScope.WORKSPACE) != (
            self.workspace_id is not None
        ):
            raise ValueError(
                "workspace targets require workspace_id; organization targets must omit it"
            )
        return self


class WorkflowRunBundle(ProductContract):
    run: WorkflowRun
    workflow_version: WorkflowVersion

    @model_validator(mode="after")
    def run_references_exact_version(self) -> "WorkflowRunBundle":
        if self.run.workflow_version_id != self.workflow_version.workflow_version_id:
            raise ValueError("run must reference the supplied exact workflow version")
        if self.run.workflow_id != self.workflow_version.workflow_id:
            raise ValueError(
                "run and workflow version must reference the same workflow"
            )
        _validate_workspace_scope(self.run, self.workflow_version)
        return self


class AgentRunBundle(ProductContract):
    run: AgentRun
    agent_version: AgentVersion

    @model_validator(mode="after")
    def run_references_exact_agent_version(self) -> "AgentRunBundle":
        if self.run.agent_version_id != self.agent_version.agent_version_id:
            raise ValueError(
                "agent run must reference the supplied exact agent version"
            )
        if self.run.agent_id != self.agent_version.agent_id:
            raise ValueError("agent run and version must reference the same agent")
        _validate_workspace_scope(self.run, self.agent_version)
        return self


def _validate_workspace_scope(left: Any, right: Any) -> None:
    if left.org_id != right.org_id or left.workspace_id != right.workspace_id:
        raise ValueError(
            "execution record and definition version must share organization and workspace"
        )


def _validate_execution_timestamps(
    status: RunStatus,
    started_at: Optional[AwareDatetime],
    finished_at: Optional[AwareDatetime],
    error: Optional[ErrorSummary],
) -> None:
    if status is RunStatus.QUEUED and (
        started_at is not None or finished_at is not None
    ):
        raise ValueError("queued runs cannot have start or finish timestamps")
    if status is RunStatus.RUNNING and (started_at is None or finished_at is not None):
        raise ValueError("running runs require started_at and cannot have finished_at")
    if status in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}:
        if started_at is None or finished_at is None:
            raise ValueError("terminal runs require started_at and finished_at")
    if (status is RunStatus.FAILED) != (error is not None):
        raise ValueError(
            "failed runs require an error summary and other statuses must omit it"
        )


__all__ = [
    "AgentRunBundle",
    "ApprovalRequest",
    "ApprovalStatus",
    "Artifact",
    "ArtifactProvenance",
    "ArtifactSensitivity",
    "ArtifactStatus",
    "AuditEvent",
    "AuditTargetScope",
    "ErrorSummary",
    "InvocationStatus",
    "RetentionClass",
    "RunStatus",
    "ToolInvocation",
    "WorkflowRun",
    "WorkflowRunBundle",
]

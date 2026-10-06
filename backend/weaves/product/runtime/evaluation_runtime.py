"""Evaluation suite lifecycle and durable execution behavior."""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from datetime import datetime
from threading import Event, RLock
from typing import TYPE_CHECKING, Optional

from weaves.product.contracts.v1 import (
    AgentDefinition,
    AgentRun,
    AgentStatus,
    Artifact,
    AuditEvent,
    AuditTargetScope,
    ErrorSummary,
    EvaluationExecution,
    EvaluationExecutionStatus,
    EvaluationReport,
    EvaluationReportRecord,
    EvaluationSuite,
    EvaluationSuiteRecord,
    ExecutionJob,
    ExecutionJobStatus,
    Permission,
    RunStatus,
    ToolInvocation,
    WorkflowRun,
)
from weaves.product.evaluation import score_evaluation_case
from weaves.product.runtime.errors import ExecutionCancelled, IdempotencyConflict
from weaves.product.runtime.repositories import (
    IdempotencyKeyAlreadyExists,
    Repository,
)
from weaves.product.runtime.request_identity import (
    effective_org_id,
    effective_principal_id,
    effective_workspace_id,
    reset_request_principal,
    set_request_identity,
)
from weaves.product.runtime.time_utils import new_id as _id
from weaves.product.runtime.time_utils import utc_now as _now

if TYPE_CHECKING:
    from weaves.product.runtime.service import RuntimeResult


class EvaluationRuntimeHost(ABC):
    """Typed runtime capabilities required by evaluation operations."""

    _bootstrapped: bool
    _idempotency_guard: RLock
    _execution_job_idempotency_locks: dict[tuple[str, str], RLock]
    agents: Repository[AgentDefinition]
    artifacts: Repository[Artifact]
    agent_runs: Repository[AgentRun]
    audit_events: Repository[AuditEvent]
    evaluation_executions: Repository[EvaluationExecution]
    evaluation_reports: Repository[EvaluationReportRecord]
    evaluation_suites: Repository[EvaluationSuiteRecord]
    execution_jobs: Repository[ExecutionJob]
    runs: Repository[WorkflowRun]
    tool_invocations: Repository[ToolInvocation]

    @abstractmethod
    def bootstrap(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def authorize(self, principal_id: str, permission: Permission) -> None:
        raise NotImplementedError

    @abstractmethod
    def _unit_of_work(self) -> AbstractContextManager[None]:
        raise NotImplementedError

    @abstractmethod
    def cancel_execution_job(
        self, job_id: str, requested_by_principal_id: str = "local-developer"
    ) -> ExecutionJob:
        raise NotImplementedError

    @abstractmethod
    def _execution_cancellation_requested(
        self, job_id: str, cancellation_requested: Event
    ) -> bool:
        raise NotImplementedError

    @abstractmethod
    def run_agent(
        self,
        task: str,
        requested_by_principal_id: str = "local-developer",
        agent_id: Optional[str] = None,
        thread_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        *,
        workflow_id: Optional[str] = None,
    ) -> RuntimeResult:
        raise NotImplementedError


class EvaluationRuntimeMixin(EvaluationRuntimeHost):
    """Evaluation operations composed into the public runtime facade."""

    def create_evaluation_suite(
        self,
        definition: EvaluationSuite,
        requested_by_principal_id: str = "local-developer",
    ) -> EvaluationSuiteRecord:
        """Save a deterministic evaluation definition in the active workspace."""
        if not self._bootstrapped:
            self.bootstrap()
        actor = effective_principal_id(requested_by_principal_id)
        self.authorize(actor, Permission.AGENTS_MANAGE)
        agent = self.agents.get_scoped(
            definition.agent_id, effective_org_id(), effective_workspace_id()
        )
        if agent.status is not AgentStatus.ACTIVE:
            raise ValueError("evaluation suites require an active agent")
        timestamp = _now()
        record = EvaluationSuiteRecord(
            suite_id=definition.suite_id,
            definition=definition,
            org_id=effective_org_id(),
            workspace_id=effective_workspace_id(),
            created_by_principal_id=actor,
            updated_by_principal_id=actor,
            created_at=timestamp,
            updated_at=timestamp,
        )
        with self._unit_of_work():
            self.evaluation_suites.create(record)
            self.audit_events.create(
                AuditEvent(
                    audit_event_id=_id(),
                    org_id=record.org_id,
                    target_scope=AuditTargetScope.WORKSPACE,
                    workspace_id=record.workspace_id,
                    actor_principal_id=actor,
                    action="evaluation.suite.created",
                    target_type="evaluation_suite",
                    target_id=record.suite_id,
                    summary="Evaluation suite created",
                    request_id=record.suite_id,
                    metadata={"agent_id": definition.agent_id},
                    created_at=timestamp,
                )
            )
        return record

    def list_evaluation_suites(self) -> tuple[EvaluationSuiteRecord, ...]:
        if not self._bootstrapped:
            self.bootstrap()
        self.authorize(
            effective_principal_id("local-developer"), Permission.AGENTS_MANAGE
        )
        records = self.evaluation_suites.list_scoped(
            effective_org_id(), effective_workspace_id()
        )
        return tuple(sorted(records, key=lambda item: item.updated_at, reverse=True))

    def get_evaluation_suite(
        self,
        suite_id: str,
        requested_by_principal_id: str = "local-developer",
        *,
        manage: bool = False,
    ) -> EvaluationSuiteRecord:
        if not self._bootstrapped:
            self.bootstrap()
        actor = effective_principal_id(requested_by_principal_id)
        self.authorize(
            actor,
            Permission.AGENTS_MANAGE if manage else Permission.AGENTS_RUN,
        )
        return self.evaluation_suites.get_scoped(
            suite_id, effective_org_id(), effective_workspace_id()
        )

    def update_evaluation_suite(
        self,
        suite_id: str,
        definition: EvaluationSuite,
        requested_by_principal_id: str = "local-developer",
    ) -> EvaluationSuiteRecord:
        if not self._bootstrapped:
            self.bootstrap()
        actor = effective_principal_id(requested_by_principal_id)
        self.authorize(actor, Permission.AGENTS_MANAGE)
        if definition.suite_id != suite_id:
            raise ValueError("suite ID cannot be changed")
        agent = self.agents.get_scoped(
            definition.agent_id, effective_org_id(), effective_workspace_id()
        )
        if agent.status is not AgentStatus.ACTIVE:
            raise ValueError("evaluation suites require an active agent")
        current = self.evaluation_suites.get_scoped(
            suite_id, effective_org_id(), effective_workspace_id()
        )
        timestamp = _now()
        updated = EvaluationSuiteRecord.model_validate(
            current.model_copy(
                update={
                    "definition": definition,
                    "updated_by_principal_id": actor,
                    "updated_at": timestamp,
                }
            ).model_dump()
        )
        with self._unit_of_work():
            self.evaluation_suites.put(updated)
            self.audit_events.create(
                AuditEvent(
                    audit_event_id=_id(),
                    org_id=updated.org_id,
                    target_scope=AuditTargetScope.WORKSPACE,
                    workspace_id=updated.workspace_id,
                    actor_principal_id=actor,
                    action="evaluation.suite.updated",
                    target_type="evaluation_suite",
                    target_id=updated.suite_id,
                    summary="Evaluation suite updated",
                    request_id=updated.suite_id,
                    metadata={"agent_id": definition.agent_id},
                    created_at=timestamp,
                )
            )
        return updated

    def store_evaluation_report(
        self,
        definition: EvaluationSuite,
        report: EvaluationReport,
        requested_by_principal_id: str = "local-developer",
    ) -> EvaluationReportRecord:
        """Store runner results after checking suite and referenced run scope."""
        if not self._bootstrapped:
            self.bootstrap()
        actor = effective_principal_id(requested_by_principal_id)
        self.authorize(actor, Permission.AGENTS_RUN)
        suite = self.evaluation_suites.get_scoped(
            report.suite_id, effective_org_id(), effective_workspace_id()
        )
        if definition != suite.definition:
            raise ValueError("evaluation suite changed while the report was running")
        case_ids = tuple(case.case_id for case in definition.cases)
        result_case_ids = tuple(result.case_id for result in report.results)
        if len(set(result_case_ids)) != len(result_case_ids) or set(
            result_case_ids
        ) != set(case_ids):
            raise ValueError("report results must match the suite cases exactly")
        cases_by_id = {case.case_id: case for case in definition.cases}
        agent_runs_by_run = {
            run.run_id: run
            for run in self.agent_runs.list_scoped(
                effective_org_id(), effective_workspace_id()
            )
            if run.agent_id == suite.definition.agent_id
        }
        artifacts_by_run: dict[str, list[Artifact]] = {}
        for artifact in self.artifacts.list_scoped(
            effective_org_id(), effective_workspace_id()
        ):
            artifacts_by_run.setdefault(artifact.run_id, []).append(artifact)
        invocations_by_run: dict[str, list[ToolInvocation]] = {}
        for invocation in self.tool_invocations.list_scoped(
            effective_org_id(), effective_workspace_id()
        ):
            invocations_by_run.setdefault(invocation.run_id, []).append(invocation)
        referenced_run_ids = tuple(
            result.run_id for result in report.results if result.run_id is not None
        )
        if len(set(referenced_run_ids)) != len(referenced_run_ids):
            raise ValueError("each evaluation case must reference a distinct run")
        for result in report.results:
            if result.run_id is None:
                if result.passed:
                    raise ValueError("a passing result must reference a completed run")
                continue
            run = self.runs.get_scoped(
                result.run_id, effective_org_id(), effective_workspace_id()
            )
            if run.status in {RunStatus.QUEUED, RunStatus.RUNNING}:
                raise ValueError("evaluation reports require completed runs")
            if run.requested_by_principal_id != actor:
                self.authorize(actor, Permission.USERS_MANAGE)
            agent_run = agent_runs_by_run.get(result.run_id)
            if agent_run is None:
                raise ValueError(
                    "evaluation results may reference only runs for the suite agent"
                )
            artifacts = artifacts_by_run.get(result.run_id, [])
            invocations = invocations_by_run.get(result.run_id, [])
            expected = score_evaluation_case(
                cases_by_id[result.case_id],
                status=run.status.value,
                run_id=result.run_id,
                summaries=tuple(artifact.summary for artifact in artifacts),
                cited_sources=tuple(
                    provenance.source_ref
                    for artifact in artifacts
                    for provenance in artifact.provenance
                ),
                tool_call_count=len(invocations),
                input_tokens=agent_run.input_tokens,
                output_tokens=agent_run.output_tokens,
                estimated_cost_usd=agent_run.estimated_cost_usd,
                duration_ms=result.duration_ms,
            )
            if (
                result.passed != expected.passed
                or result.checks != expected.checks
                or result.input_tokens != expected.input_tokens
                or result.output_tokens != expected.output_tokens
                or result.estimated_cost_usd != expected.estimated_cost_usd
            ):
                raise ValueError(
                    "submitted result does not match the persisted run evidence"
                )
        timestamp = _now()
        record = EvaluationReportRecord(
            evaluation_id=report.evaluation_id,
            suite_id=report.suite_id,
            agent_id=suite.definition.agent_id,
            definition=definition,
            report=report,
            org_id=suite.org_id,
            workspace_id=suite.workspace_id,
            submitted_by_principal_id=actor,
            created_at=timestamp,
        )
        with self._unit_of_work():
            self.evaluation_reports.create(record)
            self.audit_events.create(
                AuditEvent(
                    audit_event_id=_id(),
                    org_id=record.org_id,
                    target_scope=AuditTargetScope.WORKSPACE,
                    workspace_id=record.workspace_id,
                    actor_principal_id=actor,
                    action="evaluation.report.submitted",
                    target_type="evaluation_report",
                    target_id=record.evaluation_id,
                    summary="Evaluation report submitted",
                    request_id=record.evaluation_id,
                    metadata={
                        "suite_id": record.suite_id,
                        "passed_cases": report.passed_cases,
                        "total_cases": report.total_cases,
                    },
                    created_at=timestamp,
                )
            )
        return record

    def list_evaluation_reports(self) -> tuple[EvaluationReportRecord, ...]:
        if not self._bootstrapped:
            self.bootstrap()
        self.authorize(
            effective_principal_id("local-developer"), Permission.ARTIFACTS_READ
        )
        records = self.evaluation_reports.list_scoped(
            effective_org_id(), effective_workspace_id()
        )
        return tuple(sorted(records, key=lambda item: item.created_at, reverse=True))

    def get_evaluation_report(self, evaluation_id: str) -> EvaluationReportRecord:
        if not self._bootstrapped:
            self.bootstrap()
        self.authorize(
            effective_principal_id("local-developer"), Permission.ARTIFACTS_READ
        )
        return self.evaluation_reports.get_scoped(
            evaluation_id, effective_org_id(), effective_workspace_id()
        )

    def enqueue_evaluation_run(
        self,
        suite_id: str,
        *,
        idempotency_key: str,
        requested_by_principal_id: str = "local-developer",
        _idempotency_lock_held: bool = False,
    ) -> tuple[EvaluationExecution, bool]:
        """Queue a saved suite for execution by the durable product worker."""
        if not self._bootstrapped:
            self.bootstrap()
        actor = effective_principal_id(requested_by_principal_id)
        key = idempotency_key.strip()
        if not key or len(key) > 128:
            raise ValueError("Idempotency-Key must contain 1 to 128 characters")
        if not _idempotency_lock_held:
            lock_key = (actor, key)
            with self._idempotency_guard:
                lock = self._execution_job_idempotency_locks.setdefault(
                    lock_key, RLock()
                )
            with lock:
                return self.enqueue_evaluation_run(
                    suite_id,
                    idempotency_key=key,
                    requested_by_principal_id=actor,
                    _idempotency_lock_held=True,
                )

        self.authorize(actor, Permission.AGENTS_RUN)
        suite = self.evaluation_suites.get_scoped(
            suite_id, effective_org_id(), effective_workspace_id()
        )
        agent = self.agents.get_scoped(
            suite.definition.agent_id, effective_org_id(), effective_workspace_id()
        )
        if agent.status is not AgentStatus.ACTIVE:
            raise ValueError("evaluation suites require an active agent")
        existing = self.execution_jobs.find_by_idempotency_key(
            key, actor, effective_org_id(), effective_workspace_id()
        )
        if existing is not None:
            if (
                existing.evaluation_suite_id != suite_id
                or existing.evaluation_id is None
            ):
                raise IdempotencyConflict(
                    "Idempotency-Key was already used for a different execution request"
                )
            return (
                self.evaluation_executions.get_scoped(
                    existing.evaluation_id,
                    effective_org_id(),
                    effective_workspace_id(),
                ),
                True,
            )

        timestamp = _now()
        evaluation_id = _id()
        job_id = _id()
        evaluation = EvaluationExecution(
            evaluation_id=evaluation_id,
            suite_id=suite.suite_id,
            agent_id=suite.definition.agent_id,
            execution_job_id=job_id,
            requested_by_principal_id=actor,
            definition=suite.definition,
            org_id=suite.org_id,
            workspace_id=suite.workspace_id,
            status=EvaluationExecutionStatus.QUEUED,
            created_at=timestamp,
            updated_at=timestamp,
        )
        job = ExecutionJob(
            job_id=job_id,
            org_id=suite.org_id,
            workspace_id=suite.workspace_id,
            requested_by_principal_id=actor,
            task=f"Run evaluation suite {suite_id}",
            evaluation_id=evaluation_id,
            evaluation_suite_id=suite_id,
            idempotency_key=key,
            status=ExecutionJobStatus.QUEUED,
            created_at=timestamp,
            updated_at=timestamp,
        )
        try:
            with self._unit_of_work():
                self.evaluation_executions.create(evaluation)
                self.execution_jobs.create(job)
                self.audit_events.create(
                    AuditEvent(
                        audit_event_id=_id(),
                        org_id=suite.org_id,
                        target_scope=AuditTargetScope.WORKSPACE,
                        workspace_id=suite.workspace_id,
                        actor_principal_id=actor,
                        action="evaluation.execution.queued",
                        target_type="evaluation_execution",
                        target_id=evaluation_id,
                        summary="Evaluation suite queued for execution",
                        request_id=job_id,
                        metadata={
                            "suite_id": suite_id,
                            "execution_job_id": job_id,
                        },
                        created_at=timestamp,
                    )
                )
        except IdempotencyKeyAlreadyExists:
            existing = self.execution_jobs.find_by_idempotency_key(
                key, actor, effective_org_id(), effective_workspace_id()
            )
            if (
                existing is None
                or existing.evaluation_suite_id != suite_id
                or existing.evaluation_id is None
            ):
                raise IdempotencyConflict(
                    "Idempotency-Key was already used for a different execution request"
                )
            return (
                self.evaluation_executions.get_scoped(
                    existing.evaluation_id,
                    effective_org_id(),
                    effective_workspace_id(),
                ),
                True,
            )
        return evaluation, False

    def list_evaluation_executions(
        self, requested_by_principal_id: str = "local-developer", limit: int = 50
    ) -> tuple[EvaluationExecution, ...]:
        if not self._bootstrapped:
            self.bootstrap()
        actor = effective_principal_id(requested_by_principal_id)
        self.authorize(actor, Permission.AGENTS_RUN)
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        records = self.evaluation_executions.list_scoped(
            effective_org_id(), effective_workspace_id()
        )
        try:
            self.authorize(actor, Permission.USERS_MANAGE)
            is_admin = True
        except PermissionError:
            is_admin = False
        visible = [
            record
            for record in records
            if is_admin or record.requested_by_principal_id == actor
        ]
        return tuple(
            sorted(visible, key=lambda item: item.created_at, reverse=True)[:limit]
        )

    def get_evaluation_execution(
        self,
        evaluation_id: str,
        requested_by_principal_id: str = "local-developer",
    ) -> EvaluationExecution:
        if not self._bootstrapped:
            self.bootstrap()
        actor = effective_principal_id(requested_by_principal_id)
        self.authorize(actor, Permission.AGENTS_RUN)
        execution = self.evaluation_executions.get_scoped(
            evaluation_id, effective_org_id(), effective_workspace_id()
        )
        try:
            self.authorize(actor, Permission.USERS_MANAGE)
        except PermissionError:
            if execution.requested_by_principal_id != actor:
                raise KeyError("evaluation execution not found")
        return execution

    def cancel_evaluation_run(
        self,
        evaluation_id: str,
        requested_by_principal_id: str = "local-developer",
    ) -> EvaluationExecution:
        execution = self.get_evaluation_execution(
            evaluation_id, requested_by_principal_id
        )
        self.cancel_execution_job(execution.execution_job_id, requested_by_principal_id)
        return self.get_evaluation_execution(evaluation_id, requested_by_principal_id)

    def _execute_queued_evaluation(
        self, job: ExecutionJob, cancellation_requested: Event
    ) -> EvaluationReport:
        if job.evaluation_id is None:
            raise ValueError("execution job is not an evaluation")
        evaluation = self.evaluation_executions.get_scoped(
            job.evaluation_id, job.org_id, job.workspace_id
        )
        if evaluation.status is not EvaluationExecutionStatus.QUEUED:
            raise ValueError("evaluation is not queued")
        started_at = _now()
        running = EvaluationExecution.model_validate(
            evaluation.model_copy(
                update={
                    "status": EvaluationExecutionStatus.RUNNING,
                    "started_at": started_at,
                    "updated_at": started_at,
                }
            ).model_dump()
        )
        with self._unit_of_work():
            self.evaluation_executions.put(running)

        results = list(running.results)
        case_results = {result.case_id: result for result in results}
        for case in running.definition.cases:
            if self._execution_cancellation_requested(
                job.job_id, cancellation_requested
            ):
                raise ExecutionCancelled("Evaluation cancellation was requested")
            if case.case_id in case_results:
                continue
            result = self.run_agent(
                task=case.task,
                requested_by_principal_id=running.requested_by_principal_id,
                agent_id=running.agent_id,
                idempotency_key=(
                    "evalcase_"
                    + hashlib.sha256(
                        f"{running.evaluation_id}\0{case.case_id}".encode("utf-8")
                    ).hexdigest()
                ),
            )
            artifacts = (result.artifact, *result.workflow_artifacts)
            duration_ms = None
            if result.agent_run.started_at and result.agent_run.finished_at:
                duration_ms = int(
                    (
                        result.agent_run.finished_at - result.agent_run.started_at
                    ).total_seconds()
                    * 1000
                )
            case_result = score_evaluation_case(
                case,
                status=result.run.status.value,
                run_id=result.run.run_id,
                summaries=tuple(artifact.summary for artifact in artifacts),
                cited_sources=tuple(
                    provenance.source_ref
                    for artifact in artifacts
                    for provenance in artifact.provenance
                ),
                tool_call_count=len(result.tool_invocations),
                input_tokens=result.agent_run.input_tokens,
                output_tokens=result.agent_run.output_tokens,
                estimated_cost_usd=result.agent_run.estimated_cost_usd,
                duration_ms=duration_ms,
            )
            results.append(case_result)
            case_results[case.case_id] = case_result
            current = self.evaluation_executions.get_scoped(
                job.evaluation_id, job.org_id, job.workspace_id
            )
            updated = EvaluationExecution.model_validate(
                current.model_copy(
                    update={
                        "results": tuple(results),
                        "updated_at": _now(),
                    }
                ).model_dump()
            )
            with self._unit_of_work():
                self.evaluation_executions.put(updated)

        if cancellation_requested.is_set():
            raise ExecutionCancelled("Evaluation cancellation was requested")
        passed_cases = sum(result.passed for result in results)
        return EvaluationReport(
            suite_id=running.suite_id,
            evaluation_id=running.evaluation_id,
            passed_cases=passed_cases,
            total_cases=len(results),
            pass_rate=passed_cases / len(results),
            results=tuple(results),
        )

    def _finish_queued_evaluation(
        self,
        job: ExecutionJob,
        *,
        status: ExecutionJobStatus,
        report: Optional[EvaluationReport],
        error: Optional[ErrorSummary],
        finished_at: datetime,
    ) -> None:
        if job.evaluation_id is None:
            return
        current = self.evaluation_executions.get_scoped(
            job.evaluation_id, job.org_id, job.workspace_id
        )
        if status is ExecutionJobStatus.SUCCEEDED:
            if report is None:
                raise ValueError("completed evaluation has no report")
            identity_token = set_request_identity(
                current.requested_by_principal_id,
                current.org_id,
                current.workspace_id,
            )
            try:
                self.store_evaluation_report(current.definition, report)
            finally:
                reset_request_principal(identity_token)
            evaluation_status = EvaluationExecutionStatus.SUCCEEDED
        elif status is ExecutionJobStatus.CANCELLED:
            evaluation_status = EvaluationExecutionStatus.CANCELLED
        else:
            evaluation_status = EvaluationExecutionStatus.FAILED
            if error is None:
                error = ErrorSummary(
                    code="evaluation.failed",
                    summary="Evaluation execution failed.",
                    retryable=False,
                )
        updated = EvaluationExecution.model_validate(
            current.model_copy(
                update={
                    "status": evaluation_status,
                    "error": error
                    if evaluation_status is EvaluationExecutionStatus.FAILED
                    else None,
                    "finished_at": finished_at,
                    "updated_at": finished_at,
                    **({"results": report.results} if report is not None else {}),
                }
            ).model_dump()
        )
        self.evaluation_executions.put(updated)

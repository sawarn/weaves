"""Real PostgreSQL checks for flows whose guarantees cross API processes.

Set WEAVES_TEST_DATABASE_URL to a disposable database URL. Each test creates
and drops its own schema, so it does not touch the database's public schema.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Event
from typing import Iterator, Optional
from uuid import uuid4

import pytest

from weaves.product.contracts.v1 import (
    ApprovalRequest,
    ApprovalStatus,
    EvaluationCase,
    EvaluationExecutionStatus,
    EvaluationReport,
    EvaluationSuite,
    ExecutionJob,
    ExecutionJobStatus,
    RiskLevel,
    RunStatus,
    WorkflowConditionOperator,
    WorkflowJoinPolicy,
    WorkflowParallelGroup,
    WorkflowRun,
    WorkflowSchedule,
    WorkflowScheduleStatus,
    WorkflowStepCondition,
    WorkflowStepDependency,
    WorkflowTriggerStatus,
)
from weaves.product.evaluation import score_evaluation_case
from weaves.product.runtime import LocalPlatformRuntime
from weaves.product.runtime.auth_throttle import (
    PostgresLoginRateLimiter,
    login_bucket_key,
)
from weaves.product.runtime.postgres import ProductPostgresStore
from weaves.product.runtime.repositories import (
    IdempotencyKeyAlreadyExists,
    PostgresRepository,
)


@pytest.fixture
def isolated_postgres_url() -> Iterator[str]:
    database_url = os.environ.get("WEAVES_TEST_DATABASE_URL", "").strip()
    if not database_url:
        pytest.skip("set WEAVES_TEST_DATABASE_URL to run PostgreSQL integration tests")

    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    schema = f"weaves_it_{uuid4().hex}"
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated_url = make_conninfo(
        database_url, options=f"-c search_path={schema},public"
    )
    try:
        yield isolated_url
    finally:
        with psycopg.connect(database_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema)
                )
            )


def test_postgres_login_throttle_is_shared_across_independent_pools(
    isolated_postgres_url,
):
    first_store = ProductPostgresStore(isolated_postgres_url)
    second_store = ProductPostgresStore(isolated_postgres_url)
    try:
        first = PostgresLoginRateLimiter(first_store.pool, limit=3, window_seconds=60)
        second = PostgresLoginRateLimiter(second_store.pool, limit=3, window_seconds=60)
        now = datetime.now(timezone.utc)
        bucket = login_bucket_key("account", "owner@example.test")

        assert first.consume(bucket, now).allowed
        assert second.consume(bucket, now).allowed
        assert first.consume(bucket, now).allowed
        locked = second.consume(bucket, now)

        assert not locked.allowed
        assert locked.retry_after_seconds == 60
        first.clear(bucket)
        assert second.consume(bucket, now).allowed
    finally:
        second_store.close()
        first_store.close()


def test_postgres_schema_migrations_are_ordered_and_idempotent(
    isolated_postgres_url,
):
    first_store = ProductPostgresStore(isolated_postgres_url)
    try:
        with first_store.connection() as connection:
            versions = tuple(
                row[0]
                for row in connection.execute(
                    "SELECT version FROM product_schema_migrations ORDER BY version"
                ).fetchall()
            )
        assert versions == tuple(range(1, 13))

        # A second API/worker startup must observe the applied history and leave
        # the migration ledger unchanged.
        second_store = ProductPostgresStore(isolated_postgres_url)
        try:
            with second_store.connection() as connection:
                reapplied_versions = tuple(
                    row[0]
                    for row in connection.execute(
                        "SELECT version FROM product_schema_migrations ORDER BY version"
                    ).fetchall()
                )
            assert reapplied_versions == versions
        finally:
            second_store.close()
    finally:
        first_store.close()


def test_postgres_workflow_step_replacement_persists_published_versions(
    isolated_postgres_url, monkeypatch
):
    monkeypatch.setenv("DATABASE_URL", isolated_postgres_url)
    monkeypatch.delenv("WEAVES_SECRET_ENCRYPTION_KEY", raising=False)
    runtime = LocalPlatformRuntime()
    try:
        runtime.bootstrap()
        first = runtime.create_agent(name="Existing step", instructions="Review.")
        second = runtime.create_agent(name="New step", instructions="Summarize.")
        third = runtime.create_agent(name="Parallel step", instructions="Check risks.")
        fourth = runtime.create_agent(
            name="Parallel step two", instructions="Check scope."
        )
        workflow = runtime.create_workflow(name="Versioned sequence", agent_id=first.id)
        prior_version_id = workflow.current_version_id
        queued_job, replayed = runtime.enqueue_agent_run(
            "Run the originally accepted workflow",
            workflow_id=workflow.workflow_id,
            idempotency_key="workflow-version-pin",
        )
        assert replayed is False
        assert queued_job.workflow_version_id == prior_version_id

        condition = WorkflowStepCondition(
            source_agent_id=first.id,
            target_agent_id=second.id,
            json_pointer="/route",
            operator=WorkflowConditionOperator.EXISTS,
            expected_value=None,
        )
        updated = runtime.replace_workflow_agents(
            workflow.workflow_id,
            (first.id, second.id, third.id, fourth.id),
            (condition,),
            parallel_groups=(WorkflowParallelGroup(agent_ids=(third.id, fourth.id)),),
            step_dependencies=(
                WorkflowStepDependency(
                    target_agent_id=second.id, depends_on_agent_ids=(first.id,)
                ),
                WorkflowStepDependency(
                    target_agent_id=third.id, depends_on_agent_ids=(first.id,)
                ),
                WorkflowStepDependency(
                    target_agent_id=fourth.id, depends_on_agent_ids=(first.id,)
                ),
            ),
        )
        assert updated.current_version_id != prior_version_id
        version = runtime.workflow_versions.get_scoped(
            updated.current_version_id, updated.org_id, updated.workspace_id
        )
        assert version.version == 2
        assert len(version.agent_version_ids) == 4
        assert version.step_conditions == (condition,)
        assert version.parallel_groups == (
            WorkflowParallelGroup(agent_ids=(third.id, fourth.id)),
        )
        assert version.step_dependencies[0].join_policy is WorkflowJoinPolicy.ALL
    finally:
        runtime.close()

    reopened = LocalPlatformRuntime()
    try:
        reopened.bootstrap()
        persisted = reopened.workflows.get_scoped(
            workflow.workflow_id, workflow.org_id, workflow.workspace_id
        )
        persisted_version = reopened.workflow_versions.get_scoped(
            persisted.current_version_id or "",
            persisted.org_id,
            persisted.workspace_id,
        )
        assert persisted_version.workflow_version_id == updated.current_version_id
        assert len(persisted_version.agent_version_ids) == 4
        assert persisted_version.step_conditions == (condition,)
        assert persisted_version.parallel_groups == (
            WorkflowParallelGroup(agent_ids=(third.id, fourth.id)),
        )
        assert persisted_version.step_dependencies == version.step_dependencies
        claimed = reopened.process_next_execution_job("workflow-version-test-worker")
        assert claimed is not None
        assert claimed.status.value == "succeeded"
        completed_run = reopened.runs.get(claimed.run_id or "")
        assert completed_run.workflow_version_id == queued_job.workflow_version_id
        parallel_job, _ = reopened.enqueue_agent_run(
            "Run the new parallel workflow",
            workflow_id=workflow.workflow_id,
            idempotency_key="workflow-parallel-version",
        )
        assert parallel_job.workflow_version_id == persisted_version.workflow_version_id
        parallel_completed = reopened.process_next_execution_job(
            "workflow-parallel-test-worker"
        )
        assert parallel_completed is not None
        assert parallel_completed.status.value == "succeeded"
        parallel_run = reopened.runs.get(parallel_completed.run_id or "")
        parallel_agent_runs = [
            item
            for item in reopened.agent_runs.list_scoped(
                parallel_run.org_id, parallel_run.workspace_id
            )
            if item.run_id == parallel_run.run_id
        ]
        assert {item.agent_id for item in parallel_agent_runs} == {
            first.id,
            third.id,
            fourth.id,
        }
    finally:
        reopened.close()


def test_postgres_approval_compare_and_set_allows_one_concurrent_decision(
    isolated_postgres_url,
):
    first_store = ProductPostgresStore(isolated_postgres_url)
    second_store = ProductPostgresStore(isolated_postgres_url)
    try:
        first = PostgresRepository(
            first_store.pool,
            "approval_requests",
            "approval_request_id",
            ApprovalRequest,
        )
        second = PostgresRepository(
            second_store.pool,
            "approval_requests",
            "approval_request_id",
            ApprovalRequest,
        )
        now = datetime.now(timezone.utc)
        pending = ApprovalRequest(
            approval_request_id="approval-race",
            org_id="org-race",
            workspace_id="workspace-race",
            run_id="run-race",
            requested_by_principal_id="requester-race",
            capability_id="jira.issues.comment",
            action_summary="Comment on the release issue",
            risk_level=RiskLevel.MEDIUM,
            status=ApprovalStatus.PENDING,
            requested_at=now,
            created_at=now,
            updated_at=now,
        )
        first.create(pending)
        resolved_at = now + timedelta(seconds=1)
        approved = ApprovalRequest.model_validate(
            pending.model_copy(
                update={
                    "status": ApprovalStatus.APPROVED,
                    "resolved_by_principal_id": "approver-a",
                    "resolved_at": resolved_at,
                    "updated_at": resolved_at,
                }
            ).model_dump()
        )
        rejected = ApprovalRequest.model_validate(
            pending.model_copy(
                update={
                    "status": ApprovalStatus.REJECTED,
                    "resolved_by_principal_id": "approver-b",
                    "resolved_at": resolved_at,
                    "updated_at": resolved_at,
                }
            ).model_dump()
        )

        def resolve(
            repository: PostgresRepository[ApprovalRequest], record: ApprovalRequest
        ) -> bool:
            return repository.put_if_status_and_stale(
                record,
                expected_status=ApprovalStatus.PENDING.value,
                # The repository's indexed updated_at column is set by the
                # database when a record is inserted, a few moments after
                # this client timestamp was captured.
                updated_before=now + timedelta(seconds=1),
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = tuple(
                executor.map(
                    lambda args: resolve(*args),
                    ((first, approved), (second, rejected)),
                )
            )

        assert sorted(outcomes) == [False, True]
        assert first.get(pending.approval_request_id).status in {
            ApprovalStatus.APPROVED,
            ApprovalStatus.REJECTED,
        }
    finally:
        second_store.close()
        first_store.close()


def test_postgres_run_idempotency_is_shared_across_independent_pools(
    isolated_postgres_url,
):
    first_store = ProductPostgresStore(isolated_postgres_url)
    second_store = ProductPostgresStore(isolated_postgres_url)
    try:
        first = PostgresRepository(
            first_store.pool, "workflow_runs", "run_id", WorkflowRun
        )
        second = PostgresRepository(
            second_store.pool, "workflow_runs", "run_id", WorkflowRun
        )
        now = datetime.now(timezone.utc)
        runs = tuple(
            WorkflowRun(
                run_id=f"run-idempotent-{index}",
                org_id="org-idempotent",
                workspace_id="workspace-idempotent",
                workflow_id="workflow-idempotent",
                workflow_version_id="workflow-version-idempotent",
                requested_by_principal_id="principal-idempotent",
                trigger_type="api.request",
                idempotency_key="request-idempotent",
                status=RunStatus.RUNNING,
                started_at=now,
                created_at=now,
                updated_at=now,
            )
            for index in range(2)
        )

        def create(
            repository: PostgresRepository[WorkflowRun], run: WorkflowRun
        ) -> bool:
            try:
                repository.create(run)
                return True
            except IdempotencyKeyAlreadyExists:
                return False

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = tuple(executor.map(create, (first, second), runs))

        assert sorted(outcomes) == [False, True]
        persisted = second.find_by_idempotency_key(
            "request-idempotent",
            "principal-idempotent",
            "org-idempotent",
            "workspace-idempotent",
        )
        assert persisted is not None
        assert persisted.run_id in {run.run_id for run in runs}
    finally:
        second_store.close()
        first_store.close()


def test_postgres_execution_job_is_claimed_once_across_worker_pools(
    isolated_postgres_url,
):
    first_store = ProductPostgresStore(isolated_postgres_url)
    second_store = ProductPostgresStore(isolated_postgres_url)
    try:
        first = PostgresRepository(
            first_store.pool, "execution_jobs", "job_id", ExecutionJob
        )
        second = PostgresRepository(
            second_store.pool, "execution_jobs", "job_id", ExecutionJob
        )
        now = datetime.now(timezone.utc)
        first.create(
            ExecutionJob(
                job_id="job-claim-race",
                org_id="org-claim-race",
                workspace_id="workspace-claim-race",
                requested_by_principal_id="principal-claim-race",
                task="Run the integration test task",
                idempotency_key="request-claim-race",
                status=ExecutionJobStatus.QUEUED,
                created_at=now,
                updated_at=now,
            )
        )

        def claim(
            repository: PostgresRepository[ExecutionJob], worker_id: str
        ) -> Optional[ExecutionJob]:
            return repository.claim_next_queued(
                worker_id,
                datetime.now(timezone.utc),
                "org-claim-race",
                "workspace-claim-race",
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            claims = tuple(
                executor.map(claim, (first, second), ("worker-a", "worker-b"))
            )

        winners = tuple(job for job in claims if job is not None)
        assert len(winners) == 1
        assert winners[0].status is ExecutionJobStatus.RUNNING
        assert winners[0].attempts == 1
        assert winners[0].worker_id in {"worker-a", "worker-b"}
        assert first.get("job-claim-race").status is ExecutionJobStatus.RUNNING
    finally:
        second_store.close()
        first_store.close()


def test_postgres_webhook_delivery_idempotency_is_shared_across_pools(
    isolated_postgres_url,
):
    first_store = ProductPostgresStore(isolated_postgres_url)
    second_store = ProductPostgresStore(isolated_postgres_url)
    try:
        first = PostgresRepository(
            first_store.pool, "execution_jobs", "job_id", ExecutionJob
        )
        second = PostgresRepository(
            second_store.pool, "execution_jobs", "job_id", ExecutionJob
        )
        now = datetime.now(timezone.utc)
        event_job = ExecutionJob(
            job_id="job-webhook-event-1",
            org_id="org-webhook-event",
            workspace_id="workspace-webhook-event",
            requested_by_principal_id="principal-webhook-event",
            task="Process the untrusted webhook event.",
            workflow_id="workflow-webhook-event",
            trigger_id="trigger-webhook-event",
            trigger_event_id="provider-delivery-123",
            idempotency_key="webhook-unique-event-digest",
            status=ExecutionJobStatus.QUEUED,
            created_at=now,
            updated_at=now,
        )
        first.create(event_job)
        duplicate = event_job.model_copy(update={"job_id": "job-webhook-event-2"})

        with pytest.raises(IdempotencyKeyAlreadyExists):
            second.create(duplicate)

        persisted = second.find_by_idempotency_key(
            event_job.idempotency_key,
            event_job.requested_by_principal_id,
            event_job.org_id,
            event_job.workspace_id,
        )
        assert persisted is not None
        assert persisted.job_id == event_job.job_id
        assert persisted.trigger_id == event_job.trigger_id
        assert persisted.trigger_event_id == event_job.trigger_event_id
    finally:
        second_store.close()
        first_store.close()


def test_postgres_trigger_disable_serializes_with_delivery_across_runtime_pools(
    isolated_postgres_url, monkeypatch
):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("DATABASE_URL", isolated_postgres_url)
    monkeypatch.setenv(
        "WEAVES_SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii")
    )
    first = LocalPlatformRuntime()
    second = LocalPlatformRuntime()
    first.bootstrap()
    second.bootstrap()
    trigger, token = first.create_workflow_trigger(
        "local-assistant-workflow",
        name="Cross-pool event",
        task_instructions="Summarize the event.",
    )
    enqueue_entered = Event()
    allow_enqueue = Event()
    disable_started = Event()
    disable_finished = Event()
    actual_enqueue = first.enqueue_agent_run

    def paused_enqueue(*args, **kwargs):
        enqueue_entered.set()
        assert allow_enqueue.wait(timeout=5)
        return actual_enqueue(*args, **kwargs)

    first.enqueue_agent_run = paused_enqueue

    def disable_trigger():
        disable_started.set()
        updated = second.update_workflow_trigger(
            trigger.trigger_id, WorkflowTriggerStatus.DISABLED
        )
        disable_finished.set()
        return updated

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            delivery = executor.submit(
                first.enqueue_workflow_trigger_event,
                trigger.trigger_id,
                token,
                "cross-pool-delivery-1",
                {"issue": "REL-42"},
            )
            assert enqueue_entered.wait(timeout=5)
            disablement = executor.submit(disable_trigger)
            assert disable_started.wait(timeout=5)
            assert not disable_finished.wait(timeout=0.1)
            allow_enqueue.set()
            job, replayed = delivery.result(timeout=5)
            disabled = disablement.result(timeout=5)

        assert not replayed
        assert job.trigger_id == trigger.trigger_id
        assert disabled.status is WorkflowTriggerStatus.DISABLED
        with pytest.raises(KeyError, match="not found"):
            first.enqueue_workflow_trigger_event(
                trigger.trigger_id,
                token,
                "cross-pool-delivery-2",
                {"issue": "REL-43"},
            )
    finally:
        allow_enqueue.set()
        second.close()
        first.close()


def test_postgres_schedule_occurrence_is_queued_once_across_runtime_pools(
    isolated_postgres_url, monkeypatch
):
    """Two independent workers must not enqueue the same due occurrence."""
    from cryptography.fernet import Fernet

    monkeypatch.setenv("DATABASE_URL", isolated_postgres_url)
    monkeypatch.setenv(
        "WEAVES_SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii")
    )
    first = LocalPlatformRuntime()
    second = LocalPlatformRuntime()
    first.bootstrap()
    second.bootstrap()
    schedule = first.create_workflow_schedule(
        "local-assistant-workflow",
        name="Cross-pool recurring summary",
        task_instructions="Summarize the open issue queue.",
        interval_seconds=60,
    )
    now = datetime.now(timezone.utc)
    due = WorkflowSchedule.model_validate(
        schedule.model_copy(
            update={"next_run_at": now - timedelta(seconds=1)}
        ).model_dump()
    )
    first.workflow_schedules.put(due)
    start = Barrier(3)

    def dispatch(runtime: LocalPlatformRuntime):
        start.wait(timeout=5)
        return runtime.dispatch_due_workflow_schedules(now=now)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first_dispatch = executor.submit(dispatch, first)
            second_dispatch = executor.submit(dispatch, second)
            start.wait(timeout=5)
            jobs = first_dispatch.result(timeout=10) + second_dispatch.result(
                timeout=10
            )

        assert len(jobs) == 1
        assert jobs[0].schedule_id == schedule.schedule_id
        assert jobs[0].schedule_occurrence_at == due.next_run_at
        persisted = second.workflow_schedules.get(schedule.schedule_id)
        assert persisted.status is WorkflowScheduleStatus.ACTIVE
        assert persisted.last_run_at == due.next_run_at
        assert persisted.next_run_at == now + timedelta(
            seconds=schedule.interval_seconds
        )
    finally:
        second.close()
        first.close()


def test_postgres_evaluation_suite_and_report_are_shared_across_runtime_pools(
    isolated_postgres_url, monkeypatch
):
    """Saved definitions and immutable reports survive API pool boundaries."""
    from cryptography.fernet import Fernet

    monkeypatch.setenv("DATABASE_URL", isolated_postgres_url)
    monkeypatch.setenv(
        "WEAVES_SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii")
    )
    first = LocalPlatformRuntime()
    second = LocalPlatformRuntime()
    first.bootstrap()
    second.bootstrap()
    definition = EvaluationSuite(
        suite_id="postgres-evaluation-smoke",
        agent_id="local-assistant",
        cases=(EvaluationCase(case_id="provider-unavailable", task="Check status."),),
    )
    try:
        stored_suite = first.create_evaluation_suite(definition)
        result = score_evaluation_case(
            definition.cases[0],
            status=None,
            run_id=None,
            request_error="Run API returned HTTP 503.",
            duration_ms=12,
        )
        report = EvaluationReport(
            suite_id=definition.suite_id,
            evaluation_id="postgres-evaluation-report-1",
            passed_cases=0,
            total_cases=1,
            pass_rate=0.0,
            results=(result,),
        )
        first.store_evaluation_report(definition, report)

        reloaded_suite = second.get_evaluation_suite(definition.suite_id)
        reloaded_report = second.get_evaluation_report(report.evaluation_id)
        assert reloaded_suite.definition == stored_suite.definition
        assert reloaded_report.report == report
        assert reloaded_report.definition == definition
        assert reloaded_report.submitted_by_principal_id == "local-developer"
    finally:
        second.close()
        first.close()


def test_postgres_queued_evaluation_runs_across_runtime_pools(
    isolated_postgres_url, monkeypatch
):
    """A separate worker pool can finish a durable evaluation submitted elsewhere."""
    from cryptography.fernet import Fernet

    monkeypatch.setenv("DATABASE_URL", isolated_postgres_url)
    monkeypatch.setenv(
        "WEAVES_SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii")
    )
    api_runtime = LocalPlatformRuntime()
    worker_runtime = LocalPlatformRuntime()
    api_runtime.bootstrap()
    worker_runtime.bootstrap()
    definition = EvaluationSuite(
        suite_id="postgres-queued-evaluation",
        agent_id="local-assistant",
        cases=(
            EvaluationCase(
                case_id="marker-a",
                task="Return the LOCAL-SMOKE-OK marker.",
                must_contain=("LOCAL-SMOKE-OK",),
            ),
            EvaluationCase(
                case_id="marker-b",
                task="Return the LOCAL-SMOKE-OK marker again.",
                must_contain=("LOCAL-SMOKE-OK",),
            ),
        ),
    )
    try:
        api_runtime.create_evaluation_suite(definition)
        start = Barrier(3)

        def submit(runtime: LocalPlatformRuntime):
            start.wait(timeout=5)
            return runtime.enqueue_evaluation_run(
                definition.suite_id,
                idempotency_key="postgres-evaluation-job-001",
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            first_submission = executor.submit(submit, api_runtime)
            second_submission = executor.submit(submit, worker_runtime)
            start.wait(timeout=5)
            submissions = (
                first_submission.result(timeout=10),
                second_submission.result(timeout=10),
            )
        submitted = [execution for execution, _ in submissions]
        replay_states = [was_replayed for _, was_replayed in submissions]
        assert sorted(replay_states) == [False, True]
        assert submitted[0].evaluation_id == submitted[1].evaluation_id
        queued = submitted[0]
        assert (
            worker_runtime.get_evaluation_execution(queued.evaluation_id).status
            is EvaluationExecutionStatus.QUEUED
        )

        completed_job = worker_runtime.process_next_execution_job(
            "postgres-evaluation-worker"
        )

        assert completed_job is not None
        assert completed_job.evaluation_id == queued.evaluation_id
        assert completed_job.status is ExecutionJobStatus.SUCCEEDED
        completed = api_runtime.get_evaluation_execution(queued.evaluation_id)
        report = api_runtime.get_evaluation_report(queued.evaluation_id)
        assert completed.status is EvaluationExecutionStatus.SUCCEEDED
        assert [result.case_id for result in completed.results] == [
            "marker-a",
            "marker-b",
        ]
        assert all(result.passed for result in completed.results)
        assert report.report.pass_rate == 1.0
    finally:
        worker_runtime.close()
        api_runtime.close()

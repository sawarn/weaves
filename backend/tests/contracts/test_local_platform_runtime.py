import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Event

import pytest

from weaves.product.contracts.v1 import (
    AgentBudget,
    AgentVersion,
    ErrorSummary,
    ExecutionJob,
    ExecutionJobStatus,
    MemoryPolicy,
    MemoryRetentionClass,
    MemoryScope,
    ModelProviderType,
    ModelResponse,
    ModelUsage,
    Permission,
    PluginInstallationStatus,
    Principal,
    PrincipalStatus,
    PrincipalType,
    RunStatus,
    WorkflowConditionOperator,
    WorkflowParallelGroup,
    WorkflowStepCondition,
    WorkspaceStatus,
)
from weaves.product.runtime import LocalPlatformRuntime, PluginGatewayError
from weaves.product.runtime.model_gateway import ModelGateway, ModelGatewayError
from weaves.product.runtime.request_identity import (
    effective_org_id,
    effective_workspace_id,
    reset_request_principal,
    set_request_identity,
)
from weaves.product.runtime.service import (
    AgentRuntimeBudgetExceeded,
    IdempotencyConflict,
)


def test_conversation_thread_sends_bounded_prior_turns_to_model():
    runtime = LocalPlatformRuntime()
    captured_requests = []

    class CapturingModel:
        def complete(self, request, binding):
            captured_requests.append(request)
            return ModelResponse(
                provider_id=binding.provider.id,
                model_id=binding.profile.model,
                content="Acknowledged.",
                usage=ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2),
            )

    runtime.bootstrap()
    runtime.model_adapters[ModelProviderType.LOCAL] = CapturingModel()
    runtime.model_gateway = ModelGateway(runtime.model_adapters)
    thread = runtime.create_conversation_thread(title="Follow up")

    runtime.run_agent("My team is called Atlas", thread_id=thread.thread_id)
    runtime.run_agent("What is my team called?", thread_id=thread.thread_id)

    messages = captured_requests[-1].messages
    assert messages[1].role.value == "user"
    assert messages[1].content == "My team is called Atlas"
    assert messages[2].role.value == "assistant"
    assert messages[2].content.startswith("Acknowledged.")
    assert messages[-1].content.startswith("Task:\nWhat is my team called?")


def test_agent_run_persists_responses_longer_than_old_artifact_summary_limit():
    runtime = LocalPlatformRuntime()
    runtime.bootstrap()
    response_text = "Detailed result. " * 1500

    class LongResponseModel:
        def complete(self, request, binding):
            return ModelResponse(
                provider_id=binding.provider.id,
                model_id=binding.profile.model,
                content=response_text,
                usage=ModelUsage(input_tokens=1, output_tokens=2000, total_tokens=2001),
            )

    runtime.model_adapters[ModelProviderType.LOCAL] = LongResponseModel()
    runtime.model_gateway = ModelGateway(runtime.model_adapters)

    result = runtime.run_agent("Return a detailed working agreement")

    assert len(result.artifact.summary) > 20_000
    assert result.agent_run.output_summary is not None
    assert len(result.agent_run.output_summary["response"]) > 20_000


def test_agent_context_is_bounded_to_model_and_artifact_contracts():
    runtime = LocalPlatformRuntime()
    agent = runtime.create_agent(
        name="Large context agent",
        instructions="Use the supplied release context.",
    )
    version = runtime.agent_versions.get(agent.current_version_id or "")
    runtime.agent_versions.put(
        AgentVersion.model_validate(
            version.model_copy(
                update={
                    "memory_policy": MemoryPolicy(
                        allowed_scopes=(MemoryScope.WORKSPACE,), max_items=50
                    )
                }
            ).model_dump()
        )
    )
    source_ref_prefix = "external-memory-source-"
    for index in range(50):
        runtime.create_memory_item(
            title=f"Release guidance {index}",
            text="release deployment guidance " * 350,
            source_ref=f"{source_ref_prefix}{index}-" + "x" * 180,
        )

    captured = []

    class CapturingModel:
        def complete(self, request, binding):
            captured.append(request)
            return ModelResponse(
                provider_id=binding.provider.id,
                model_id=binding.profile.model,
                content="Bounded context response.",
                usage=ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2),
            )

    runtime.model_adapters[ModelProviderType.LOCAL] = CapturingModel()
    runtime.model_gateway = ModelGateway(runtime.model_adapters)

    result = runtime.run_agent("Summarize release guidance", agent_id=agent.id)

    user_message = captured[0].messages[-1].content
    context_json = user_message.split("Retrieved context records (JSON):\n", 1)[1]
    context_records = json.loads(context_json)
    assert len(user_message) < 100_000
    assert len(context_records) == runtime.MAX_AGENT_CONTEXT_RECORDS
    assert len(result.artifact.provenance) <= 50
    assert len(result.agent_run.output_summary["omitted_context_source_ids"]) > 0
    assert any(
        item.source_ref.startswith(source_ref_prefix)
        for item in result.artifact.provenance
    )


def test_ten_step_workflow_bounds_prior_artifacts_in_model_requests():
    runtime = LocalPlatformRuntime()
    agents = tuple(
        runtime.create_agent(
            name=f"Workflow step {index}",
            instructions="Review the previous engineering result.",
        )
        for index in range(10)
    )
    workflow = runtime.create_workflow(
        name="Long-result workflow", agent_ids=tuple(item.id for item in agents)
    )
    captured = []

    class LongWorkflowModel:
        def complete(self, request, binding):
            captured.append(request)
            return ModelResponse(
                provider_id=binding.provider.id,
                model_id=binding.profile.model,
                content="step result " * 2000,
                usage=ModelUsage(input_tokens=1, output_tokens=2000, total_tokens=2001),
            )

    runtime.model_adapters[ModelProviderType.LOCAL] = LongWorkflowModel()
    runtime.model_gateway = ModelGateway(runtime.model_adapters)

    result = runtime.run_workflow(workflow.workflow_id, "Review the release")

    assert len(captured) == 10
    assert len(captured[-1].messages[-1].content) < 100_000
    assert len(result.artifact.provenance) <= 50


@pytest.mark.parametrize(
    ("route", "operator", "expected_value", "expected_agents"),
    [
        (
            "review",
            WorkflowConditionOperator.EQUALS,
            "review",
            ("Router", "Reviewer", "Summarizer"),
        ),
        (
            "skip",
            WorkflowConditionOperator.EQUALS,
            "review",
            ("Router", "Summarizer"),
        ),
        (
            "skip",
            WorkflowConditionOperator.NOT_EQUALS,
            "review",
            ("Router", "Reviewer", "Summarizer"),
        ),
        (
            "skip",
            WorkflowConditionOperator.EXISTS,
            None,
            ("Router", "Reviewer", "Summarizer"),
        ),
    ],
)
def test_workflow_condition_routes_steps_from_structured_agent_output(
    route, operator, expected_value, expected_agents
):
    runtime = LocalPlatformRuntime()
    schema = {
        "type": "object",
        "properties": {"route": {"type": "string"}},
        "required": ["route"],
        "additionalProperties": False,
    }
    router = runtime.create_agent(
        name="Router",
        instructions="Classify the request and return a route.",
        allowed_capability_ids=(),
        output_schema=schema,
    )
    reviewer = runtime.create_agent(
        name="Reviewer",
        instructions="Review the request.",
        allowed_capability_ids=(),
    )
    summarizer = runtime.create_agent(
        name="Summarizer",
        instructions="Summarize the request.",
        allowed_capability_ids=(),
    )
    workflow = runtime.create_workflow(
        name="Conditional review",
        agent_ids=(router.id, reviewer.id, summarizer.id),
    )
    condition = WorkflowStepCondition(
        source_agent_id=router.id,
        target_agent_id=reviewer.id,
        json_pointer="/route",
        operator=operator,
        expected_value=expected_value,
    )
    workflow = runtime.replace_workflow_agents(
        workflow.workflow_id,
        (router.id, reviewer.id, summarizer.id),
        (condition,),
    )
    runtime.update_agent(router.id, instructions="Route the request carefully.")
    workflow = runtime.workflows.get(workflow.workflow_id)
    current_workflow_version = runtime.workflow_versions.get(
        workflow.current_version_id or ""
    )
    assert current_workflow_version.step_conditions == (condition,)

    class ConditionalModel:
        calls = 0

        def complete(self, request, binding):
            self.calls += 1
            content = (
                json.dumps({"route": route})
                if self.calls == 1
                else f"{expected_agents[self.calls - 1]} completed"
            )
            return ModelResponse(
                provider_id=binding.provider.id,
                model_id=binding.profile.model,
                content=content,
                usage=ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2),
            )

    runtime.model_adapters[ModelProviderType.LOCAL] = ConditionalModel()
    runtime.model_gateway = ModelGateway(runtime.model_adapters)
    result = runtime.run_workflow(workflow.workflow_id, "Review this request")

    assert result.run.status is RunStatus.SUCCEEDED
    assert result.run.workflow_version_id == workflow.current_version_id
    agents_by_name = {agent.name: agent for agent in (router, reviewer, summarizer)}
    assert tuple(item.agent_id for item in result.workflow_agent_runs) == tuple(
        agents_by_name[name].id for name in expected_agents
    )
    assert [
        item.input_summary["workflow_step_index"] for item in result.workflow_agent_runs
    ] == ([0, 2] if len(expected_agents) == 2 else [0, 1, 2])
    skipped_events = tuple(
        item
        for item in runtime.audit_events.list()
        if item.action == "workflow.step.skipped"
    )
    assert len(skipped_events) == (0 if len(expected_agents) == 3 else 1)


def test_invalid_provider_response_is_sanitized_and_fails_the_run():
    runtime = LocalPlatformRuntime()
    agent = runtime.create_agent(
        name="Malformed provider response",
        instructions="Answer from approved context.",
    )

    class OversizedResponseModel:
        def complete(self, request, binding):
            return ModelResponse(
                provider_id=binding.provider.id,
                model_id=binding.profile.model,
                content="x" * 100_001,
                usage=ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2),
            )

    runtime.model_adapters[ModelProviderType.LOCAL] = OversizedResponseModel()
    runtime.model_gateway = ModelGateway(runtime.model_adapters)

    with pytest.raises(ModelGatewayError) as captured_error:
        runtime.run_agent("Summarize security basics", agent_id=agent.id)

    assert captured_error.value.code == "model.invalid_response"
    assert "100001" not in captured_error.value.message
    failed_run = runtime.runs.list()[-1]
    failed_agent_run = next(
        item for item in runtime.agent_runs.list() if item.run_id == failed_run.run_id
    )
    assert failed_run.status is RunStatus.FAILED
    assert failed_agent_run.status is RunStatus.FAILED


def test_agent_tool_call_budget_skips_excess_context_capabilities():
    runtime = LocalPlatformRuntime()
    agent = runtime.create_agent(
        name="No context calls",
        instructions="Answer from the request alone.",
        allowed_capability_ids=("knowledge.search",),
        budget=AgentBudget(max_tool_calls=0),
    )

    result = runtime.run_agent("Summarize the working agreements", agent_id=agent.id)

    assert result.tool_invocations == ()
    assert result.agent_run.output_summary is not None
    assert result.agent_run.output_summary["budget_skipped_capability_ids"] == [
        "knowledge.search"
    ]
    assert "tool-call budget was reached" in result.artifact.summary


def test_agent_runtime_budget_fails_at_safe_boundary_and_audits(monkeypatch):
    runtime = LocalPlatformRuntime()
    agent = runtime.create_agent(
        name="Short runtime",
        instructions="Answer using connected context.",
        budget=AgentBudget(max_runtime_seconds=1),
    )
    ticks = iter((100.0, 102.0))
    monkeypatch.setattr("weaves.product.runtime.service.monotonic", lambda: next(ticks))

    with pytest.raises(AgentRuntimeBudgetExceeded, match="safe boundary"):
        runtime.run_agent("Summarize security basics", agent_id=agent.id)

    failed_run = runtime.runs.list()[-1]
    assert failed_run.status is RunStatus.FAILED
    assert failed_run.error is not None
    assert failed_run.error.code == "agent.runtime_budget_exceeded"
    assert any(
        event.action == "agent.run.failed" and event.target_id == failed_run.run_id
        for event in runtime.audit_events.list()
    )


def test_runtime_timeout_after_model_completion_retains_reported_usage(monkeypatch):
    runtime = LocalPlatformRuntime()
    agent = runtime.create_agent(
        name="Provider timeout",
        instructions="Answer using connected context.",
        budget=AgentBudget(max_runtime_seconds=1),
    )

    class SlowModel:
        def complete(self, request, binding):
            return ModelResponse(
                provider_id=binding.provider.id,
                model_id=binding.profile.model,
                content="A completed response.",
                usage=ModelUsage(input_tokens=3, output_tokens=4, total_tokens=7),
            )

    runtime.model_adapters[ModelProviderType.LOCAL] = SlowModel()
    runtime.model_gateway = ModelGateway(runtime.model_adapters)
    ticks = iter((100.0, 100.0, 100.0, 102.0))
    monkeypatch.setattr("weaves.product.runtime.service.monotonic", lambda: next(ticks))

    with pytest.raises(AgentRuntimeBudgetExceeded):
        runtime.run_agent("Summarize security basics", agent_id=agent.id)

    failed_run = runtime.runs.list()[-1]
    agent_run = next(
        item for item in runtime.agent_runs.list() if item.run_id == failed_run.run_id
    )
    assert agent_run.input_tokens == 3
    assert agent_run.output_tokens == 4
    assert agent_run.resolved_provider_id == "local-mock-provider"


def test_bootstrap_recovers_stale_running_records_after_interruption():
    runtime = LocalPlatformRuntime()
    result = runtime.run_agent("Summarize security basics")
    stale_at = datetime.now(timezone.utc) - timedelta(hours=5)
    runtime.runs.put(
        type(result.run).model_validate(
            result.run.model_copy(
                update={
                    "status": RunStatus.RUNNING,
                    "error": None,
                    "finished_at": None,
                    "updated_at": stale_at,
                }
            ).model_dump()
        )
    )
    runtime.agent_runs.put(
        type(result.agent_run).model_validate(
            result.agent_run.model_copy(
                update={
                    "status": RunStatus.RUNNING,
                    "error": None,
                    "finished_at": None,
                    "updated_at": stale_at,
                }
            ).model_dump()
        )
    )
    runtime.runs.create(
        type(result.run)(
            run_id="orphaned-running-record",
            org_id=result.run.org_id,
            workspace_id=result.run.workspace_id,
            workflow_id=result.run.workflow_id,
            workflow_version_id=result.run.workflow_version_id,
            requested_by_principal_id=result.run.requested_by_principal_id,
            trigger_type="local.runtime",
            status=RunStatus.RUNNING,
            started_at=stale_at,
            created_at=stale_at,
            updated_at=stale_at,
        )
    )
    runtime._bootstrapped = False

    runtime.bootstrap()

    failed_run = runtime.runs.get(result.run.run_id)
    failed_agent_run = runtime.agent_runs.get(result.agent_run.agent_run_id)
    assert failed_run.status is RunStatus.FAILED
    assert failed_run.error is not None
    assert failed_run.error.code == "runtime.interrupted"
    assert failed_agent_run.status is RunStatus.FAILED
    orphan = runtime.runs.get("orphaned-running-record")
    assert orphan.status is RunStatus.FAILED
    assert any(
        event.action == "agent.run.recovered" and event.target_id == result.run.run_id
        for event in runtime.audit_events.list()
    )


def test_stale_run_recovery_preserves_recent_active_runs():
    runtime = LocalPlatformRuntime()
    result = runtime.run_agent("Summarize security basics")
    current = datetime.now(timezone.utc)
    running = type(result.run).model_validate(
        result.run.model_copy(
            update={
                "status": RunStatus.RUNNING,
                "error": None,
                "finished_at": None,
                "updated_at": current,
            }
        ).model_dump()
    )
    runtime.runs.put(running)

    recovered = runtime.recover_stale_runs(now=current, stale_after_seconds=120)

    assert recovered == ()
    assert runtime.runs.get(result.run.run_id).status is RunStatus.RUNNING


def test_concurrent_stale_recovery_claims_and_audits_a_run_once():
    runtime = LocalPlatformRuntime()
    result = runtime.run_agent("Summarize security basics")
    stale_at = datetime.now(timezone.utc) - timedelta(hours=5)
    runtime.runs.put(
        type(result.run).model_validate(
            result.run.model_copy(
                update={
                    "status": RunStatus.RUNNING,
                    "error": None,
                    "finished_at": None,
                    "updated_at": stale_at,
                }
            ).model_dump()
        )
    )

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = tuple(executor.map(lambda _: runtime.recover_stale_runs(), range(8)))

    assert (
        sum(run_id == result.run.run_id for recovery in results for run_id in recovery)
        == 1
    )
    recovery_events = [
        event
        for event in runtime.audit_events.list()
        if event.action == "agent.run.recovered"
        and event.target_id == result.run.run_id
    ]
    assert len(recovery_events) == 1
    runtime.audit_events.delete(recovery_events[0].audit_event_id)

    runtime.recover_stale_runs()

    assert (
        sum(
            event.action == "agent.run.recovered"
            and event.target_id == result.run.run_id
            for event in runtime.audit_events.list()
        )
        == 1
    )


def test_execution_job_queue_is_idempotent_and_worker_completes_a_run():
    runtime = LocalPlatformRuntime()
    job, replayed = runtime.enqueue_agent_run(
        "Summarize security basics", idempotency_key="queued-request-1"
    )
    assert replayed is False
    assert job.status is ExecutionJobStatus.QUEUED

    same_job, replayed = runtime.enqueue_agent_run(
        "Summarize security basics", idempotency_key="queued-request-1"
    )
    assert replayed is True
    assert same_job.job_id == job.job_id
    with pytest.raises(IdempotencyConflict):
        runtime.enqueue_agent_run(
            "Summarize another topic", idempotency_key="queued-request-1"
        )

    completed = runtime.process_next_execution_job("worker-test")
    assert completed is not None
    assert completed.job_id == job.job_id
    assert completed.status is ExecutionJobStatus.SUCCEEDED
    assert completed.attempts == 1
    assert completed.worker_id == "worker-test"
    assert completed.run_id is not None
    assert runtime.runs.get(completed.run_id).status is RunStatus.SUCCEEDED
    assert runtime.process_next_execution_job("worker-test") is None


def test_execution_job_worker_renews_lease_during_long_run(monkeypatch):
    runtime = LocalPlatformRuntime()
    job, _ = runtime.enqueue_agent_run("Keep the execution lease alive")
    runtime.EXECUTION_JOB_HEARTBEAT_SECONDS = 0.005
    original_run_agent = runtime.run_agent
    heartbeat_calls = []

    def slow_run_agent(*args, **kwargs):
        time.sleep(0.04)
        return original_run_agent(*args, **kwargs)

    original_heartbeat = runtime.heartbeat_execution_job

    def observed_heartbeat(job_id, *, worker_id, attempts):
        result = original_heartbeat(job_id, worker_id=worker_id, attempts=attempts)
        heartbeat_calls.append(result)
        return result

    monkeypatch.setattr(runtime, "run_agent", slow_run_agent)
    monkeypatch.setattr(runtime, "heartbeat_execution_job", observed_heartbeat)

    completed = runtime.process_next_execution_job("worker-with-heartbeat")

    assert completed is not None
    assert completed.job_id == job.job_id
    assert completed.status is ExecutionJobStatus.SUCCEEDED
    assert heartbeat_calls
    assert any(heartbeat_calls)


def test_queued_execution_job_can_be_cancelled_idempotently():
    runtime = LocalPlatformRuntime()
    job, _ = runtime.enqueue_agent_run("Cancel this queued request")

    cancelled = runtime.cancel_execution_job(job.job_id)

    assert cancelled.status is ExecutionJobStatus.CANCELLED
    assert cancelled.attempts == 0
    assert cancelled.finished_at is not None
    assert runtime.cancel_execution_job(job.job_id) == cancelled
    assert runtime.process_next_execution_job("worker-test") is None
    events = [
        event
        for event in runtime.audit_events.list()
        if event.action == "agent.execution_job.cancelled"
        and event.target_id == job.job_id
    ]
    assert len(events) == 1


def test_running_execution_job_records_cancel_request():
    runtime = LocalPlatformRuntime()
    job, _ = runtime.enqueue_agent_run("Already claimed request")
    claimed = runtime.execution_jobs.claim_next_queued(
        "worker-test", job.updated_at, job.org_id, job.workspace_id
    )
    assert claimed is not None

    requested = runtime.cancel_execution_job(job.job_id)

    assert requested.status is ExecutionJobStatus.CANCEL_REQUESTED
    assert requested.worker_id == claimed.worker_id
    assert requested.attempts == claimed.attempts
    assert runtime.heartbeat_execution_job(
        job.job_id, worker_id=claimed.worker_id or "", attempts=claimed.attempts
    )


def test_worker_finishes_running_job_as_cancelled_when_requested(monkeypatch):
    runtime = LocalPlatformRuntime()
    job, _ = runtime.enqueue_agent_run("Cancel this active request")
    runtime.EXECUTION_JOB_HEARTBEAT_SECONDS = 0.005
    original_run_agent = runtime.run_agent

    def slow_run_agent(*args, **kwargs):
        time.sleep(0.05)
        return original_run_agent(*args, **kwargs)

    monkeypatch.setattr(runtime, "run_agent", slow_run_agent)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(runtime.process_next_execution_job, "cancel-worker")
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            current = runtime.execution_jobs.get(job.job_id)
            if current.status is ExecutionJobStatus.RUNNING:
                break
            time.sleep(0.002)
        else:
            pytest.fail("worker did not claim the queued job")

        requested = runtime.cancel_execution_job(job.job_id)
        assert requested.status is ExecutionJobStatus.CANCEL_REQUESTED
        completed = future.result(timeout=3)

    assert completed is not None
    assert completed.status is ExecutionJobStatus.CANCELLED
    assert completed.run_id is not None
    assert runtime.runs.get(completed.run_id).status is RunStatus.CANCELLED
    cancelled_agent_runs = [
        item for item in runtime.agent_runs.list() if item.run_id == completed.run_id
    ]
    assert len(cancelled_agent_runs) == 1
    assert cancelled_agent_runs[0].status is RunStatus.CANCELLED


def test_worker_preserves_success_if_cancel_races_after_run_completion(monkeypatch):
    runtime = LocalPlatformRuntime()
    job, _ = runtime.enqueue_agent_run("Cancel at the completion boundary")
    repository = runtime.execution_jobs
    original_put_if_owned = repository.put_if_execution_job_owned
    injected = False

    def inject_cancel_request(
        record, *, worker_id, attempts, expected_status="running"
    ):
        nonlocal injected
        if (
            not injected
            and record.status is ExecutionJobStatus.SUCCEEDED
            and expected_status == ExecutionJobStatus.RUNNING.value
        ):
            injected = True
            current = repository.get(record.job_id)
            request = ExecutionJob.model_validate(
                current.model_copy(
                    update={
                        "status": ExecutionJobStatus.CANCEL_REQUESTED,
                        "updated_at": current.updated_at + timedelta(microseconds=1),
                    }
                ).model_dump()
            )
            assert original_put_if_owned(
                request,
                worker_id=worker_id,
                attempts=attempts,
                expected_status=expected_status,
            )
            return False
        return original_put_if_owned(
            record,
            worker_id=worker_id,
            attempts=attempts,
            expected_status=expected_status,
        )

    monkeypatch.setattr(repository, "put_if_execution_job_owned", inject_cancel_request)

    completed = runtime.process_next_execution_job("racing-cancel-worker")

    assert injected
    assert completed is not None
    assert completed.status is ExecutionJobStatus.SUCCEEDED
    assert completed.run_id is not None
    assert runtime.runs.get(completed.run_id).status is RunStatus.SUCCEEDED


def test_agent_job_cancellation_stops_before_model_after_context_call(monkeypatch):
    runtime = LocalPlatformRuntime()
    job, _ = runtime.enqueue_agent_run("Cancel after collecting context")
    original_invoke = runtime.plugin_gateway.invoke
    original_complete = runtime.model_gateway.complete
    model_calls = []

    def cancel_after_context(*args, **kwargs):
        result = original_invoke(*args, **kwargs)
        runtime.cancel_execution_job(job.job_id)
        return result

    def observe_model_call(*args, **kwargs):
        model_calls.append(True)
        return original_complete(*args, **kwargs)

    monkeypatch.setattr(runtime.plugin_gateway, "invoke", cancel_after_context)
    monkeypatch.setattr(runtime.model_gateway, "complete", observe_model_call)

    completed = runtime.process_next_execution_job("agent-cancel-worker")

    assert completed is not None
    assert completed.status is ExecutionJobStatus.CANCELLED
    assert completed.run_id is not None
    assert runtime.runs.get(completed.run_id).status is RunStatus.CANCELLED
    assert model_calls == []
    assert any(
        event.action == "agent.run.cancelled" and event.target_id == completed.run_id
        for event in runtime.audit_events.list()
    )


def test_agent_job_finishes_successfully_if_cancel_arrives_during_final_model_call(
    monkeypatch,
):
    runtime = LocalPlatformRuntime()
    job, _ = runtime.enqueue_agent_run("Finish the active model call")
    original_complete = runtime.model_gateway.complete

    def cancel_during_model(*args, **kwargs):
        runtime.cancel_execution_job(job.job_id)
        return original_complete(*args, **kwargs)

    monkeypatch.setattr(runtime.model_gateway, "complete", cancel_during_model)

    completed = runtime.process_next_execution_job("agent-late-cancel-worker")

    assert completed is not None
    assert completed.status is ExecutionJobStatus.SUCCEEDED
    assert completed.run_id is not None
    assert runtime.runs.get(completed.run_id).status is RunStatus.SUCCEEDED


def test_workflow_cancellation_stops_between_steps(monkeypatch):
    runtime = LocalPlatformRuntime()
    first = runtime.create_agent(name="Cancel first", instructions="Prepare a plan.")
    second = runtime.create_agent(name="Cancel second", instructions="Review the plan.")
    workflow = runtime.create_workflow(
        name="Cancellable workflow", agent_ids=(first.id, second.id)
    )
    cancellation_requested = Event()
    original_step = runtime._execute_agent_run
    executed_steps = []

    def execute_first_step(*args, **kwargs):
        result = original_step(*args, **kwargs)
        executed_steps.append(result)
        cancellation_requested.set()
        return result

    monkeypatch.setattr(runtime, "_execute_agent_run", execute_first_step)
    result = runtime.run_workflow(
        workflow.workflow_id,
        "Prepare and review a release",
        _cancellation_event=cancellation_requested,
    )

    assert len(executed_steps) == 1
    assert len(result.workflow_agent_runs) == 1
    assert result.run.status is RunStatus.CANCELLED
    assert result.run.finished_at is not None
    assert (
        sum(
            event.action == "workflow.run.cancelled"
            and event.target_id == result.run.run_id
            for event in runtime.audit_events.list()
        )
        == 1
    )


def test_worker_checks_persisted_workflow_cancellation_between_steps(monkeypatch):
    runtime = LocalPlatformRuntime()
    first = runtime.create_agent(name="Persisted cancel first", instructions="Plan.")
    second = runtime.create_agent(
        name="Persisted cancel second", instructions="Review."
    )
    workflow = runtime.create_workflow(
        name="Persisted cancellation workflow", agent_ids=(first.id, second.id)
    )
    job, _ = runtime.enqueue_agent_run(
        "Plan and review a change", workflow_id=workflow.workflow_id
    )
    original_step = runtime._execute_agent_run
    executed_steps = []

    def cancel_after_first_step(*args, **kwargs):
        result = original_step(*args, **kwargs)
        executed_steps.append(result)
        runtime.cancel_execution_job(job.job_id)
        return result

    monkeypatch.setattr(runtime, "_execute_agent_run", cancel_after_first_step)
    monkeypatch.setattr(runtime, "_renew_execution_job_lease", lambda *args: None)

    completed = runtime.process_next_execution_job("workflow-cancel-worker")

    assert completed is not None
    assert completed.status is ExecutionJobStatus.CANCELLED
    assert completed.run_id is not None
    workflow_run = runtime.runs.get(completed.run_id)
    assert workflow_run.status is RunStatus.CANCELLED
    assert len(executed_steps) == 1


def test_parallel_workflow_cancellation_waits_for_started_branches(monkeypatch):
    runtime = LocalPlatformRuntime()
    agents = tuple(
        runtime.create_agent(
            name=f"Parallel cancellation {index}",
            instructions="Complete the assigned review step.",
            allowed_capability_ids=(),
        )
        for index in range(4)
    )
    workflow = runtime.create_workflow(
        name="Parallel cancellation workflow",
        agent_ids=tuple(agent.id for agent in agents),
    )
    runtime.replace_workflow_agents(
        workflow.workflow_id,
        tuple(agent.id for agent in agents),
        parallel_groups=(
            WorkflowParallelGroup(agent_ids=(agents[1].id, agents[2].id)),
        ),
    )
    job, _ = runtime.enqueue_agent_run(
        "Review the change", workflow_id=workflow.workflow_id
    )
    branch_barrier = Barrier(2)
    original_step = runtime._execute_agent_run

    def cancel_during_group(*args, **kwargs):
        result = original_step(*args, **kwargs)
        step_index = kwargs.get("workflow_step_index")
        if step_index in {1, 2}:
            branch_barrier.wait(timeout=5)
            if step_index == 1:
                runtime.cancel_execution_job(job.job_id)
        return result

    monkeypatch.setattr(runtime, "_execute_agent_run", cancel_during_group)
    monkeypatch.setattr(runtime, "_renew_execution_job_lease", lambda *args: None)

    completed = runtime.process_next_execution_job("parallel-cancel-worker")

    assert completed is not None
    assert completed.status is ExecutionJobStatus.CANCELLED
    assert completed.run_id is not None
    workflow_run = runtime.runs.get(completed.run_id)
    assert workflow_run.status is RunStatus.CANCELLED
    agent_runs = [
        item for item in runtime.agent_runs.list() if item.run_id == workflow_run.run_id
    ]
    assert {item.agent_id for item in agent_runs} == {
        agents[0].id,
        agents[1].id,
        agents[2].id,
    }


def test_retryable_execution_job_retries_with_lineage_and_idempotency():
    runtime = LocalPlatformRuntime()
    original, _ = runtime.enqueue_agent_run("Retry this failed request")
    started = original.updated_at
    finished = started + timedelta(seconds=1)
    failed = ExecutionJob.model_validate(
        original.model_copy(
            update={
                "status": ExecutionJobStatus.FAILED,
                "attempts": 1,
                "started_at": started,
                "finished_at": finished,
                "updated_at": finished,
                "error": ErrorSummary(
                    code="provider.timeout",
                    summary="The model provider timed out.",
                    retryable=True,
                ),
            }
        ).model_dump()
    )
    runtime.execution_jobs.put(failed)

    retry, replayed = runtime.retry_execution_job(
        original.job_id, idempotency_key="retry-request-1"
    )
    assert replayed is False
    assert retry.status is ExecutionJobStatus.QUEUED
    assert retry.retry_of_job_id == original.job_id
    assert retry.task == original.task
    assert retry.agent_id == original.agent_id

    replay, replayed = runtime.retry_execution_job(
        original.job_id, idempotency_key="retry-request-1"
    )
    assert replayed is True
    assert replay.job_id == retry.job_id

    completed = runtime.process_next_execution_job("retry-worker")
    assert completed is not None
    assert completed.job_id == retry.job_id
    assert completed.status is ExecutionJobStatus.SUCCEEDED
    assert (
        runtime.execution_jobs.get(original.job_id).status is ExecutionJobStatus.FAILED
    )
    assert any(
        event.action == "agent.execution_job.retry_queued"
        and event.target_id == retry.job_id
        for event in runtime.audit_events.list()
    )


def test_non_retryable_execution_job_cannot_be_retried():
    runtime = LocalPlatformRuntime()
    original, _ = runtime.enqueue_agent_run("Do not retry this request")
    started = original.updated_at
    finished = started + timedelta(seconds=1)
    runtime.execution_jobs.put(
        ExecutionJob.model_validate(
            original.model_copy(
                update={
                    "status": ExecutionJobStatus.FAILED,
                    "attempts": 1,
                    "started_at": started,
                    "finished_at": finished,
                    "updated_at": finished,
                    "error": ErrorSummary(
                        code="agent.configuration_invalid",
                        summary="The agent configuration is invalid.",
                        retryable=False,
                    ),
                }
            ).model_dump()
        )
    )

    with pytest.raises(ValueError, match="not marked retryable"):
        runtime.retry_execution_job(original.job_id, idempotency_key="retry-request-2")


def test_concurrent_api_credential_rotation_leaves_one_active_replacement():
    runtime = LocalPlatformRuntime()
    principal, _, original, _ = runtime.create_service_account(
        name="Rotatable service",
        permissions=(Permission.AGENTS_RUN,),
    )

    def rotate() -> bool:
        try:
            runtime.rotate_api_credential(original.id)
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: rotate(), range(2)))

    assert sum(outcomes) == 1
    credentials = runtime.api_credentials.list_scoped(principal.org_id)
    active = [
        item
        for item in credentials
        if item.principal_id == principal.id and item.status.value == "active"
    ]
    assert len(active) == 1
    assert runtime.api_credentials.get(original.id).status.value == "revoked"


def test_execution_job_worker_runs_a_published_workflow():
    runtime = LocalPlatformRuntime()
    first_agent = runtime.create_agent(
        name="Workflow planner",
        instructions="Plan the requested release review.",
    )
    second_agent = runtime.create_agent(
        name="Workflow reviewer",
        instructions="Review the plan and identify risks.",
    )
    workflow = runtime.create_workflow(
        name="Queued release review", agent_ids=(first_agent.id, second_agent.id)
    )
    job, replayed = runtime.enqueue_agent_run(
        "Review the latest release",
        workflow_id=workflow.workflow_id,
        idempotency_key="queued-workflow-request",
    )

    assert replayed is False
    assert job.workflow_id == workflow.workflow_id
    assert job.workflow_version_id == workflow.current_version_id
    assert job.agent_id is None
    pinned_workflow_version_id = job.workflow_version_id
    pinned_first_agent_version_id = runtime.agents.get(
        first_agent.id
    ).current_version_id

    # A queued request must keep the published definition it accepted even if
    # the admin publishes a newer agent and workflow version before execution.
    runtime.update_agent(
        first_agent.id, instructions="Plan the requested review with more detail."
    )
    assert (
        runtime.workflows.get(workflow.workflow_id).current_version_id
        != pinned_workflow_version_id
    )
    replay, replayed = runtime.enqueue_agent_run(
        "Review the latest release",
        workflow_id=workflow.workflow_id,
        idempotency_key="queued-workflow-request",
    )
    assert replayed is True
    assert replay.job_id == job.job_id
    with pytest.raises(IdempotencyConflict):
        runtime.enqueue_agent_run(
            "Review the latest release",
            agent_id=first_agent.id,
            idempotency_key="queued-workflow-request",
        )
    completed = runtime.process_next_execution_job("workflow-worker")

    assert completed is not None
    assert completed.status is ExecutionJobStatus.SUCCEEDED
    assert completed.workflow_id == workflow.workflow_id
    assert completed.run_id is not None
    run = runtime.runs.get(completed.run_id)
    assert run.workflow_id == workflow.workflow_id
    assert run.workflow_version_id == pinned_workflow_version_id
    agent_runs = tuple(
        item
        for item in runtime.agent_runs.list_scoped(run.org_id, run.workspace_id)
        if item.run_id == run.run_id
    )
    assert len(agent_runs) == 2
    assert [item.agent_id for item in agent_runs] == [first_agent.id, second_agent.id]
    assert agent_runs[0].agent_version_id == pinned_first_agent_version_id


def test_linear_workflow_failure_marks_parent_and_current_step_failed():
    runtime = LocalPlatformRuntime()
    first_agent = runtime.create_agent(
        name="First step agent", instructions="Prepare a release plan."
    )
    second_agent = runtime.create_agent(
        name="Second step agent", instructions="Review the release plan."
    )
    workflow = runtime.create_workflow(
        name="Failing linear workflow", agent_ids=(first_agent.id, second_agent.id)
    )

    class FailOnSecondCall:
        calls = 0

        def complete(self, request, binding):
            self.calls += 1
            if self.calls == 2:
                raise ModelGatewayError("test.failure", "Second step failed")
            return ModelResponse(
                provider_id=binding.provider.id,
                model_id=binding.profile.model,
                content="First step result",
                usage=ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2),
            )

    runtime.model_adapters[ModelProviderType.LOCAL] = FailOnSecondCall()
    runtime.model_gateway = ModelGateway(runtime.model_adapters)

    with pytest.raises(ModelGatewayError, match="Second step failed"):
        runtime.run_workflow(workflow.workflow_id, "Review the release")

    run = runtime.runs.list()[0]
    agent_runs = tuple(
        sorted(
            (item for item in runtime.agent_runs.list() if item.run_id == run.run_id),
            key=lambda item: int(item.input_summary["workflow_step_index"]),
        )
    )
    assert run.status is RunStatus.FAILED
    assert run.error is not None
    assert len(agent_runs) == 2
    assert [item.status for item in agent_runs] == [
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
    ]


def test_execution_job_worker_claims_jobs_once_across_threads():
    runtime = LocalPlatformRuntime()
    jobs = [
        runtime.enqueue_agent_run(f"Queue request {index}")[0] for index in range(2)
    ]
    with ThreadPoolExecutor(max_workers=2) as executor:
        claimed = tuple(
            executor.map(
                lambda worker: runtime.execution_jobs.claim_next_queued(
                    worker,
                    datetime.now(timezone.utc),
                    "local-org",
                    "local-workspace",
                ),
                ("worker-a", "worker-b"),
            )
        )
    assert {item.job_id for item in claimed if item is not None} == {
        job.job_id for job in jobs
    }
    assert all(item.status is ExecutionJobStatus.RUNNING for item in claimed)


def test_recovery_fails_a_job_abandoned_by_worker():
    runtime = LocalPlatformRuntime()
    job, _ = runtime.enqueue_agent_run("Queue request")
    claimed = runtime.execution_jobs.claim_next_queued(
        "worker-crashed",
        datetime.now(timezone.utc) - timedelta(hours=5),
        "local-org",
        "local-workspace",
    )
    assert claimed is not None
    current = datetime.now(timezone.utc)

    recovered = runtime.recover_stale_execution_jobs(
        now=current, stale_after_seconds=60
    )

    assert recovered == (job.job_id,)
    stored = runtime.execution_jobs.get(job.job_id)
    assert stored.status is ExecutionJobStatus.FAILED
    assert stored.error is not None
    assert stored.error.code == "runtime.interrupted"


def test_recovery_finalizes_cancel_requested_job_after_worker_interruption():
    runtime = LocalPlatformRuntime()
    job, _ = runtime.enqueue_agent_run("Cancel and recover this job")
    claimed = runtime.execution_jobs.claim_next_queued(
        "worker-crashed",
        datetime.now(timezone.utc) - timedelta(hours=5),
        "local-org",
        "local-workspace",
    )
    assert claimed is not None
    requested = runtime.cancel_execution_job(job.job_id)
    assert requested.status is ExecutionJobStatus.CANCEL_REQUESTED

    current = datetime.now(timezone.utc)
    stale = ExecutionJob.model_validate(
        requested.model_copy(
            update={"updated_at": current - timedelta(minutes=5)}
        ).model_dump()
    )
    runtime.execution_jobs.put(stale)

    recovered = runtime.recover_stale_execution_jobs(
        now=current, stale_after_seconds=60
    )

    assert recovered == (job.job_id,)
    completed = runtime.execution_jobs.get(job.job_id)
    assert completed.status is ExecutionJobStatus.CANCELLED
    assert completed.run_id is None
    assert completed.error is None


def test_execution_job_lease_heartbeat_is_fenced_to_current_claim():
    runtime = LocalPlatformRuntime()
    job, _ = runtime.enqueue_agent_run("Lease renewal request")
    claimed = runtime.execution_jobs.claim_next_queued(
        "worker-current",
        datetime.now(timezone.utc),
        "local-org",
        "local-workspace",
    )
    assert claimed is not None

    assert not runtime.heartbeat_execution_job(
        job.job_id, worker_id="worker-other", attempts=claimed.attempts
    )
    assert not runtime.heartbeat_execution_job(
        job.job_id, worker_id="worker-current", attempts=claimed.attempts + 1
    )
    assert runtime.heartbeat_execution_job(
        job.job_id, worker_id="worker-current", attempts=claimed.attempts
    )
    refreshed = runtime.execution_jobs.get(job.job_id)
    assert refreshed.updated_at >= claimed.updated_at

    recovered = runtime.recover_stale_execution_jobs(
        now=refreshed.updated_at + timedelta(seconds=61), stale_after_seconds=60
    )
    assert recovered == (job.job_id,)
    assert not runtime.execution_jobs.put_if_execution_job_owned(
        claimed, worker_id="worker-current", attempts=claimed.attempts
    )


def test_invitation_acceptance_rolls_back_all_records_when_audit_write_fails(
    monkeypatch,
):
    runtime = LocalPlatformRuntime()
    user, principal, _, invitation, token = runtime.create_user_invitation(
        email="transactional-invite@example.com",
        display_name="Transactional Invite",
        permissions=(Permission.AGENTS_RUN,),
    )
    create_audit = runtime.audit_events.create

    def fail_acceptance_audit(event):
        if event.action == "user.invitation_accepted":
            raise RuntimeError("simulated audit failure")
        return create_audit(event)

    monkeypatch.setattr(runtime.audit_events, "create", fail_acceptance_audit)
    with pytest.raises(RuntimeError, match="simulated audit failure"):
        runtime.accept_user_invitation(token, "transactional-invite-password")

    assert (
        runtime.user_invitations.get(invitation.invitation_id).status.value == "pending"
    )
    assert runtime.users.get(user.id).status.value == "invited"
    assert runtime.principals.get(principal.id).status.value == "disabled"
    with pytest.raises(KeyError):
        runtime.user_passwords.get(user.id)
    assert not any(
        session.principal_id == principal.id for session in runtime.user_sessions.list()
    )


def test_concurrent_workspace_archives_preserve_one_active_workspace():
    runtime = LocalPlatformRuntime()
    runtime.bootstrap()
    workspaces = [runtime.workspaces.get("local-workspace")]
    workspaces.extend(
        runtime.create_workspace(name=f"Concurrent workspace {index}")
        for index in range(9)
    )

    def archive(workspace_id):
        try:
            runtime.update_workspace(workspace_id, status=WorkspaceStatus.ARCHIVED)
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=len(workspaces)) as executor:
        results = tuple(executor.map(lambda item: archive(item.id), workspaces))

    assert sum(results) == len(workspaces) - 1
    active = tuple(
        item
        for item in runtime.workspaces.list_scoped("local-org")
        if item.status.value == "active"
    )
    assert len(active) == 1


def test_local_runtime_bootstraps_and_completes_a_scoped_mock_run():
    runtime = LocalPlatformRuntime()

    runtime.bootstrap()
    result = runtime.run_agent("Summarize our security basics")

    assert result.run.status is RunStatus.SUCCEEDED
    assert result.agent_run.agent_version_id == "local-assistant-v1"
    assert result.agent_run.resolved_provider_id == "local-mock-provider"
    assert result.tool_invocation.capability_id == "knowledge.search"
    assert result.artifact.provenance
    assert "least privilege" in result.artifact.summary
    assert result.audit_event.workspace_id == result.run.workspace_id
    assert runtime.runs.get(result.run.run_id) == result.run
    assert runtime.artifacts.get(result.artifact.artifact_id) == result.artifact


def test_local_runtime_rejects_empty_tasks_without_creating_a_run():
    runtime = LocalPlatformRuntime()

    with pytest.raises(ValueError, match="task must not be empty"):
        runtime.run_agent("  ")

    assert runtime.runs.list() == ()


def test_local_runtime_rejects_oversized_tasks_before_creating_a_run():
    runtime = LocalPlatformRuntime()

    with pytest.raises(ValueError, match="12000 characters"):
        runtime.run_agent("x" * 12_001)

    assert runtime.runs.list() == ()


def test_in_memory_repository_prevents_duplicate_creates():
    runtime = LocalPlatformRuntime()
    runtime.bootstrap()

    with pytest.raises(ValueError, match="already exists"):
        runtime.organizations.create(runtime.organizations.get("local-org"))


def test_in_memory_unit_of_work_rolls_back_all_repository_changes():
    runtime = LocalPlatformRuntime()
    runtime.bootstrap()
    workspace = runtime.workspaces.get("local-workspace")
    role = runtime.roles.get("local-developer-role")

    with pytest.raises(RuntimeError, match="rollback transaction"):
        with runtime._unit_of_work():
            runtime.workspaces.put(
                workspace.model_copy(update={"name": "Uncommitted workspace"})
            )
            runtime.roles.delete(role.id)
            raise RuntimeError("rollback transaction")

    assert runtime.workspaces.get("local-workspace").name == "Default workspace"
    assert runtime.roles.get("local-developer-role") == role


def test_memory_changes_roll_back_when_the_audit_write_fails(monkeypatch):
    runtime = LocalPlatformRuntime()
    original_audit_create = runtime.audit_events.create
    prior_memory_ids = {
        item.memory_id for item in runtime.memory_items.list_scoped("local-org")
    }

    def fail_audit_create(_record):
        raise RuntimeError("simulated audit store failure")

    monkeypatch.setattr(runtime.audit_events, "create", fail_audit_create)
    with pytest.raises(RuntimeError, match="simulated audit store failure"):
        runtime.create_memory_item(
            title="Atomic create", text="Keep the record audited."
        )
    assert {
        item.memory_id for item in runtime.memory_items.list_scoped("local-org")
    } == prior_memory_ids

    monkeypatch.setattr(runtime.audit_events, "create", original_audit_create)
    created = runtime.create_memory_item(
        title="Atomic delete", text="Keep the deletion audited."
    )
    monkeypatch.setattr(runtime.audit_events, "create", fail_audit_create)
    with pytest.raises(RuntimeError, match="simulated audit store failure"):
        runtime.delete_memory_item(created.memory_id)
    assert runtime.memory_items.get(created.memory_id) == created


def test_expired_memory_is_deleted_and_audited():
    runtime = LocalPlatformRuntime()
    expiry = datetime.now(timezone.utc) + timedelta(seconds=1)
    item = runtime.create_memory_item(
        title="Temporary context",
        text="This should be removed when it expires.",
        retention_class=MemoryRetentionClass.EPHEMERAL,
        expires_at=expiry,
    )

    assert runtime.purge_expired_memory_items(now=expiry) == (item.memory_id,)
    with pytest.raises(KeyError):
        runtime.memory_items.get(item.memory_id)
    events = [
        event
        for event in runtime.audit_events.list()
        if event.action == "memory_item.expired" and event.target_id == item.memory_id
    ]
    assert len(events) == 1
    assert events[0].actor_principal_id == "system:memory-retention"
    assert runtime.purge_expired_memory_items(now=expiry) == ()


def test_concurrent_memory_purge_audits_an_expired_item_once():
    runtime = LocalPlatformRuntime()
    expiry = datetime.now(timezone.utc) + timedelta(seconds=1)
    item = runtime.create_memory_item(
        title="Concurrent expiry",
        text="Only one maintenance worker should remove this.",
        retention_class=MemoryRetentionClass.EPHEMERAL,
        expires_at=expiry,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _: runtime.purge_expired_memory_items(now=expiry), range(2)
            )
        )

    assert [memory_id for result in results for memory_id in result] == [item.memory_id]
    assert (
        sum(
            event.action == "memory_item.expired" and event.target_id == item.memory_id
            for event in runtime.audit_events.list()
        )
        == 1
    )


def test_repository_does_not_expose_mutable_internal_records():
    runtime = LocalPlatformRuntime()
    runtime.bootstrap()
    first_read = runtime.workspaces.get("local-workspace")
    first_read.name = "Mutated outside repository"

    assert runtime.workspaces.get("local-workspace").name == "Default workspace"


def test_repository_reads_enforce_organization_and_workspace_scope():
    runtime = LocalPlatformRuntime()
    runtime.bootstrap()

    with pytest.raises(KeyError, match="organization scope"):
        runtime.installations.get_scoped(
            "local-knowledge-installation", "another-org", "local-workspace"
        )
    assert runtime.installations.list_scoped("local-org", "local-workspace") == (
        runtime.installations.get("local-knowledge-installation"),
    )
    assert runtime.installations.list_scoped("another-org") == ()


def test_local_runtime_requires_run_permission():
    runtime = LocalPlatformRuntime()
    runtime.bootstrap()
    now = datetime.now(timezone.utc)
    runtime.principals.create(
        Principal(
            id="unassigned-principal",
            org_id="local-org",
            principal_type=PrincipalType.SERVICE_ACCOUNT,
            status=PrincipalStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
    )

    with pytest.raises(PermissionError, match="lacks agents.run permission"):
        runtime.run_agent(
            "Read handbook", requested_by_principal_id="unassigned-principal"
        )

    assert runtime.runs.list() == ()


def test_plugin_denial_fails_run_and_records_invocation_and_audit():
    runtime = LocalPlatformRuntime()
    agent = runtime.create_agent(
        name="No context agent",
        instructions="Answer without using external context.",
        allowed_capability_ids=("knowledge.search",),
    )
    runtime.update_plugin_installation(
        "local-knowledge-installation",
        status=PluginInstallationStatus.DISABLED,
    )

    with pytest.raises(PluginGatewayError, match="disabled"):
        runtime.run_agent("Read the handbook", agent_id=agent.id)

    run = runtime.runs.list()[0]
    invocation = runtime.tool_invocations.list()[0]
    assert run.status is RunStatus.FAILED
    assert invocation.status.value == "failed"
    assert invocation.error is not None
    assert runtime.audit_events.list()[-1].action == "agent.run.failed"


def test_worker_claims_and_runs_job_using_the_jobs_tenant_scope():
    runtime = LocalPlatformRuntime()
    organization, workspace, _, owner, _ = runtime.create_organization(
        name="Worker Tenant",
        email="owner@worker.example",
        display_name="Worker Owner",
    )
    identity = set_request_identity(owner.id, organization.id, workspace.id)
    try:
        agent = runtime.create_agent(
            name="Tenant worker agent",
            instructions="Summarize the available workspace guide.",
        )
        queued, replayed = runtime.enqueue_agent_run(
            "Summarize the available workspace guide.",
            agent_id=agent.id,
        )
    finally:
        reset_request_principal(identity)

    assert not replayed
    completed = runtime.process_next_execution_job("tenant-worker")

    assert completed is not None
    assert completed.job_id == queued.job_id
    assert completed.status is ExecutionJobStatus.SUCCEEDED
    assert completed.org_id == organization.id
    assert completed.workspace_id == workspace.id
    assert effective_org_id() == "local-org"
    assert effective_workspace_id() == "local-workspace"


def test_local_knowledge_search_uses_its_installation_tenant_scope():
    runtime = LocalPlatformRuntime()
    organization, workspace, _, _, _ = runtime.create_organization(
        name="Knowledge Tenant",
        email="owner@knowledge.example",
        display_name="Knowledge Owner",
    )
    installation = runtime.installations.list_scoped(organization.id, workspace.id)[0]
    result = runtime.context.invoke_for_installation(
        "knowledge.search",
        {"query": "getting started"},
        installation,
    )

    assert [item["source_id"] for item in result["documents"]] == [
        f"onboarding:{organization.id}"
    ]

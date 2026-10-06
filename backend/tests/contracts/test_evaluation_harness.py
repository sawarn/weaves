import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from threading import Event

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from scripts import run_evaluations
from weaves.product.api import create_app
from weaves.product.contracts.v1 import (
    EvaluationExecution,
    EvaluationExecutionStatus,
    ExecutionJob,
    ExecutionJobStatus,
)
from weaves.product.evaluation import (
    EvaluationCase,
    EvaluationReport,
    EvaluationSuite,
    score_evaluation_case,
)
from weaves.product.runtime import LocalPlatformRuntime


def test_evaluation_suite_requires_unique_case_ids():
    with pytest.raises(ValidationError, match="case IDs must be unique"):
        EvaluationSuite(
            suite_id="engineering-smoke",
            agent_id="assistant",
            cases=(
                EvaluationCase(case_id="case-a", task="Find the release owner."),
                EvaluationCase(case_id="case-a", task="Find the incident owner."),
            ),
        )


def test_checked_in_local_evaluation_example_matches_the_contract():
    suite_path = (
        Path(__file__).resolve().parents[2] / "examples" / "local-smoke-evaluation.json"
    )
    suite = EvaluationSuite.model_validate_json(suite_path.read_text())
    assert suite.agent_id == "local-assistant"
    assert suite.cases[0].must_contain == ("LOCAL-SMOKE-OK",)


def test_local_smoke_suite_runs_through_product_api_and_scoring():
    suite_path = (
        Path(__file__).resolve().parents[2] / "examples" / "local-smoke-evaluation.json"
    )
    suite = EvaluationSuite.model_validate_json(suite_path.read_text())
    case = suite.cases[0]
    with TestClient(create_app(LocalPlatformRuntime())) as client:
        response = client.post(
            "/api/v0/runs", json={"agent_id": suite.agent_id, "task": case.task}
        )

    assert response.status_code == 201, response.text
    result = run_evaluations.score_run_response(case, response.json(), duration_ms=10)
    assert result.passed
    assert result.run_id == response.json()["run"]["run_id"]


def test_evaluation_rejects_conflicting_phrase_assertions():
    with pytest.raises(ValidationError, match="both required and forbidden"):
        EvaluationCase(
            case_id="conflict",
            task="Summarize the release.",
            must_contain=("Ready",),
            must_not_contain=("ready",),
        )


def test_evaluation_case_scores_output_sources_and_tool_usage():
    case = EvaluationCase(
        case_id="release-status",
        task="Find the release status.",
        must_contain=("Ready for launch",),
        must_not_contain=("blocked",),
        required_sources=("jira:REL-42",),
        minimum_tool_calls=1,
    )
    result = score_evaluation_case(
        case,
        status="succeeded",
        run_id="run-123",
        summaries=("The release is READY for launch.",),
        cited_sources=("jira:REL-42",),
        tool_call_count=1,
        input_tokens=220,
        output_tokens=80,
        estimated_cost_usd=Decimal("0.00042"),
        duration_ms=1700,
    )

    assert result.passed
    assert result.run_id == "run-123"
    assert result.input_tokens == 220
    assert result.estimated_cost_usd == Decimal("0.00042")
    assert all(check.passed for check in result.checks)


def test_evaluation_case_reports_missing_requirements_without_output_capture():
    case = EvaluationCase(
        case_id="release-status",
        task="Find the release status.",
        must_contain=("Ready for launch",),
        required_sources=("jira:REL-42",),
        minimum_tool_calls=1,
    )
    result = score_evaluation_case(
        case,
        status="failed",
        run_id="run-456",
        summaries=("Temporary provider response text",),
        cited_sources=(),
        tool_call_count=0,
    )

    assert not result.passed
    assert {check.name for check in result.checks if not check.passed} == {
        "run_succeeded",
        "contains:Ready for launch",
        "required_sources",
        "minimum_tool_calls",
    }
    assert "Temporary provider response text" not in result.model_dump_json()


def test_evaluation_report_counts_must_match_case_results():
    result = score_evaluation_case(
        EvaluationCase(case_id="healthy", task="Check the service."),
        status="succeeded",
        run_id="run-789",
    )
    with pytest.raises(ValidationError, match="passed_cases must match"):
        EvaluationReport(
            suite_id="health-suite",
            evaluation_id="evaluation-1",
            passed_cases=0,
            total_cases=1,
            pass_rate=0.0,
            results=(result,),
        )


def test_runner_maps_api_response_to_a_privacy_bounded_result(monkeypatch):
    suite = EvaluationSuite(
        suite_id="engineering-smoke",
        agent_id="assistant",
        cases=(
            EvaluationCase(
                case_id="release-ticket",
                task="Summarize release REL-42.",
                must_contain=("release ready",),
                required_sources=("jira:REL-42",),
                minimum_tool_calls=1,
            ),
        ),
    )
    payload = {
        "run": {"run_id": "run-eval-1", "status": "succeeded"},
        "agent_run": {
            "input_tokens": 120,
            "output_tokens": 40,
            "estimated_cost_usd": "0.00025",
        },
        "artifacts": [
            {
                "summary": "Release ready for launch.",
                "provenance": [{"source_ref": "jira:REL-42"}],
            }
        ],
        "tool_invocations": [{"invocation_id": "invocation-1"}],
    }

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(payload).encode()

    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeResponse()

    monkeypatch.setattr(run_evaluations, "urlopen", fake_urlopen)
    result = run_evaluations._run_case(
        "http://localhost:8001", "test-token", suite, suite.cases[0], "eval-123"
    )

    assert result.passed
    assert result.run_id == "run-eval-1"
    assert result.estimated_cost_usd == Decimal("0.00025")
    assert len(requests) == 1
    request, timeout = requests[0]
    assert request.get_header("Authorization") == "Bearer test-token"
    assert (
        request.get_header("Idempotency-key") == "weaves-eval-eval-123-release-ticket"
    )
    assert timeout == 180
    assert "Release ready for launch" not in result.model_dump_json()


def test_product_api_persists_suite_and_runner_report_with_run_scope():
    suite = EvaluationSuite(
        suite_id="api-smoke",
        agent_id="local-assistant",
        cases=(
            EvaluationCase(
                case_id="local-marker",
                task="Return the LOCAL-SMOKE-OK marker.",
                must_contain=("LOCAL-SMOKE-OK",),
            ),
        ),
    )
    runtime = LocalPlatformRuntime()
    client = TestClient(create_app(runtime))

    with client:
        created = client.post(
            "/api/v0/evaluation-suites",
            json={"definition": suite.model_dump(mode="json")},
        )
        assert created.status_code == 201, created.text
        assert created.json()["definition"]["suite_id"] == suite.suite_id

        fetched = client.get(f"/api/v0/evaluation-suites/{suite.suite_id}")
        assert fetched.status_code == 200, fetched.text
        assert (
            EvaluationSuite.model_validate_json(
                json.dumps(fetched.json()["definition"])
            )
            == suite
        )

        run_response = client.post(
            "/api/v0/runs",
            json={"agent_id": suite.agent_id, "task": suite.cases[0].task},
        )
        assert run_response.status_code == 201, run_response.text
        result = run_evaluations.score_run_response(
            suite.cases[0], run_response.json(), duration_ms=12
        )
        report = EvaluationReport(
            suite_id=suite.suite_id,
            evaluation_id="evaluation-api-smoke",
            passed_cases=int(result.passed),
            total_cases=1,
            pass_rate=float(result.passed),
            results=(result,),
        )
        submitted = client.post(
            "/api/v0/evaluation-reports",
            json={
                "definition": suite.model_dump(mode="json"),
                "report": report.model_dump(mode="json"),
            },
        )
        assert submitted.status_code == 201, submitted.text
        assert submitted.json()["report"]["pass_rate"] == 1.0
        assert submitted.json()["definition"]["cases"][0]["case_id"] == (
            suite.cases[0].case_id
        )

        reports = client.get("/api/v0/evaluation-reports")
        assert reports.status_code == 200, reports.text
        assert [item["evaluation_id"] for item in reports.json()] == [
            report.evaluation_id
        ]
        loaded = client.get(f"/api/v0/evaluation-reports/{report.evaluation_id}")
        assert loaded.status_code == 200, loaded.text
        assert loaded.json()["submitted_by_principal_id"] == "local-developer"


def test_evaluation_report_must_match_the_saved_suite_cases():
    suite = EvaluationSuite(
        suite_id="scope-smoke",
        agent_id="local-assistant",
        cases=(EvaluationCase(case_id="case-a", task="Check this run."),),
    )
    other_suite = EvaluationSuite(
        suite_id="other-smoke",
        agent_id="local-assistant",
        cases=(EvaluationCase(case_id="case-b", task="Check another run."),),
    )
    runtime = LocalPlatformRuntime()
    client = TestClient(create_app(runtime))

    with client:
        for definition in (suite, other_suite):
            response = client.post(
                "/api/v0/evaluation-suites",
                json={"definition": definition.model_dump(mode="json")},
            )
            assert response.status_code == 201
        run = client.post(
            "/api/v0/runs",
            json={"agent_id": suite.agent_id, "task": other_suite.cases[0].task},
        )
        assert run.status_code == 201
        result = score_evaluation_case(
            other_suite.cases[0],
            status="succeeded",
            run_id=run.json()["run"]["run_id"],
        )
        report = EvaluationReport(
            suite_id=suite.suite_id,
            evaluation_id="evaluation-invalid-run",
            passed_cases=int(result.passed),
            total_cases=1,
            pass_rate=float(result.passed),
            results=(result,),
        )
        response = client.post(
            "/api/v0/evaluation-reports",
            json={
                "definition": suite.model_dump(mode="json"),
                "report": report.model_dump(mode="json"),
            },
        )

    assert response.status_code == 422
    assert "suite cases" in response.json()["detail"]


def test_cli_fetches_saved_suite_runs_cases_and_persists_report(monkeypatch):
    suite = EvaluationSuite.model_validate_json(
        (
            Path(__file__).resolve().parents[2]
            / "examples"
            / "local-smoke-evaluation.json"
        ).read_text()
    )
    run_payload = {
        "run": {"run_id": "run-cli-eval", "status": "succeeded"},
        "agent_run": {"input_tokens": 5, "output_tokens": 7},
        "artifacts": [
            {
                "summary": "LOCAL-SMOKE-OK",
                "provenance": [{"source_ref": "knowledge:local-smoke"}],
            }
        ],
        "tool_invocations": [],
    }
    requests = []

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(self.payload).encode()

    def fake_urlopen(request, timeout):
        requests.append(request)
        if request.full_url.endswith("/api/v0/evaluation-suites/local-assistant-smoke"):
            payload = {"definition": suite.model_dump(mode="json")}
        elif request.full_url.endswith("/api/v0/runs"):
            payload = run_payload
        else:
            payload = {"evaluation_id": "saved"}
        return FakeResponse(payload)

    monkeypatch.setattr(run_evaluations, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_evaluations.py",
            "--suite-id",
            suite.suite_id,
            "--base-url",
            "http://localhost:8001",
            "--token",
            "test-token",
            "--persist-report",
        ],
    )

    assert run_evaluations.main() == 0

    assert [request.get_method() for request in requests] == ["GET", "POST", "POST"]
    submitted = json.loads(requests[-1].data)
    assert submitted["definition"]["suite_id"] == suite.suite_id
    assert submitted["report"]["passed_cases"] == 1
    assert submitted["report"]["results"][0]["run_id"] == "run-cli-eval"


def test_queued_evaluation_runs_cases_and_persists_a_verified_report():
    suite = EvaluationSuite(
        suite_id="queued-smoke",
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
    runtime = LocalPlatformRuntime()
    runtime.create_evaluation_suite(suite)

    queued, replayed = runtime.enqueue_evaluation_run(
        suite.suite_id, idempotency_key="queued-evaluation-001"
    )
    replay, was_replayed = runtime.enqueue_evaluation_run(
        suite.suite_id, idempotency_key="queued-evaluation-001"
    )
    assert not replayed
    assert was_replayed
    assert replay.evaluation_id == queued.evaluation_id
    assert queued.status is EvaluationExecutionStatus.QUEUED

    job = runtime.process_next_execution_job("evaluation-worker-1")
    assert job is not None
    assert job.evaluation_id == queued.evaluation_id
    assert job.run_id is None
    assert job.status.value == "succeeded"

    completed = runtime.get_evaluation_execution(queued.evaluation_id)
    report = runtime.get_evaluation_report(queued.evaluation_id)
    assert completed.status is EvaluationExecutionStatus.SUCCEEDED
    assert [result.case_id for result in completed.results] == [
        "marker-a",
        "marker-b",
    ]
    assert all(result.passed for result in completed.results)
    assert report.report.pass_rate == 1.0


def test_queued_evaluation_can_be_cancelled_before_a_worker_claims_it():
    runtime = LocalPlatformRuntime()
    suite = EvaluationSuite(
        suite_id="queued-cancel",
        agent_id="local-assistant",
        cases=(EvaluationCase(case_id="case-a", task="Check the status."),),
    )
    runtime.create_evaluation_suite(suite)
    queued, _ = runtime.enqueue_evaluation_run(
        suite.suite_id, idempotency_key="queued-evaluation-cancel"
    )

    cancelled = runtime.cancel_evaluation_run(queued.evaluation_id)

    assert cancelled.status is EvaluationExecutionStatus.CANCELLED
    assert cancelled.finished_at is not None
    assert cancelled.results == ()
    assert runtime.process_next_execution_job("evaluation-worker-2") is None


def test_running_evaluation_cancels_between_cases_and_keeps_completed_progress(
    monkeypatch,
):
    runtime = LocalPlatformRuntime()
    runtime.EXECUTION_JOB_HEARTBEAT_SECONDS = 0.01
    suite = EvaluationSuite(
        suite_id="running-evaluation-cancel",
        agent_id="local-assistant",
        cases=(
            EvaluationCase(case_id="case-a", task="Return LOCAL-SMOKE-OK."),
            EvaluationCase(case_id="case-b", task="Return LOCAL-SMOKE-OK again."),
        ),
    )
    runtime.create_evaluation_suite(suite)
    queued, _ = runtime.enqueue_evaluation_run(
        suite.suite_id, idempotency_key="running-evaluation-cancel-001"
    )
    first_case_completed = Event()
    release_first_case = Event()
    original_run_agent = runtime.run_agent
    run_count = 0

    def pause_after_first_case(*args, **kwargs):
        nonlocal run_count
        result = original_run_agent(*args, **kwargs)
        run_count += 1
        if run_count == 1:
            first_case_completed.set()
            assert release_first_case.wait(timeout=3)
        return result

    monkeypatch.setattr(runtime, "run_agent", pause_after_first_case)
    # Keep heartbeat signaling out of the test so cancellation must be observed
    # directly from the durable job state at the next case boundary.
    monkeypatch.setattr(runtime, "_renew_execution_job_lease", lambda *args: None)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            runtime.process_next_execution_job, "evaluation-cancel-worker"
        )
        assert first_case_completed.wait(timeout=3)
        requested = runtime.cancel_evaluation_run(queued.evaluation_id)
        assert requested.status is EvaluationExecutionStatus.CANCEL_REQUESTED
        release_first_case.set()
        completed_job = future.result(timeout=5)

    completed = runtime.get_evaluation_execution(queued.evaluation_id)
    assert completed_job is not None
    assert completed_job.status.value == "cancelled"
    assert completed.status is EvaluationExecutionStatus.CANCELLED
    assert [result.case_id for result in completed.results] == ["case-a"]
    assert run_count == 1
    with pytest.raises(KeyError, match="not found"):
        runtime.get_evaluation_report(queued.evaluation_id)


def test_interrupted_partial_evaluation_recovers_as_non_retryable_failure():
    runtime = LocalPlatformRuntime()
    suite = EvaluationSuite(
        suite_id="partial-recovery-smoke",
        agent_id="local-assistant",
        cases=(
            EvaluationCase(case_id="case-a", task="Check the first status."),
            EvaluationCase(case_id="case-b", task="Check the second status."),
        ),
    )
    runtime.create_evaluation_suite(suite)
    queued, _ = runtime.enqueue_evaluation_run(
        suite.suite_id, idempotency_key="partial-recovery-001"
    )
    now = datetime.now(timezone.utc)
    stale_at = now - timedelta(seconds=5)
    claimed = runtime.execution_jobs.claim_next_queued(
        "interrupted-worker", stale_at, queued.org_id, queued.workspace_id
    )
    assert claimed is not None
    runtime.execution_jobs.put(
        ExecutionJob.model_validate(
            claimed.model_copy(update={"updated_at": stale_at}).model_dump()
        )
    )
    evaluation = runtime.evaluation_executions.get(queued.evaluation_id)
    partial_result = score_evaluation_case(
        suite.cases[0],
        status=None,
        run_id=None,
        request_error="Worker stopped after the first case.",
    )
    runtime.evaluation_executions.put(
        EvaluationExecution.model_validate(
            evaluation.model_copy(
                update={
                    "status": EvaluationExecutionStatus.RUNNING,
                    "started_at": stale_at,
                    "updated_at": stale_at,
                    "results": (partial_result,),
                }
            ).model_dump()
        )
    )

    recovered = runtime.recover_stale_execution_jobs(stale_after_seconds=1, now=now)

    assert recovered == (queued.execution_job_id,)
    job = runtime.execution_jobs.get(queued.execution_job_id)
    failed = runtime.get_evaluation_execution(queued.evaluation_id)
    assert job.status is ExecutionJobStatus.FAILED
    assert job.error is not None and not job.error.retryable
    assert failed.status is EvaluationExecutionStatus.FAILED
    assert failed.error is not None and failed.error.code == "runtime.interrupted"
    assert [result.case_id for result in failed.results] == ["case-a"]
    with pytest.raises(ValueError, match="evaluation jobs cannot be retried"):
        runtime.retry_execution_job(
            queued.execution_job_id, idempotency_key="partial-recovery-retry"
        )


def test_interrupted_evaluation_with_all_saved_cases_recovers_report():
    runtime = LocalPlatformRuntime()
    suite = EvaluationSuite(
        suite_id="complete-recovery-smoke",
        agent_id="local-assistant",
        cases=(
            EvaluationCase(case_id="case-a", task="Check the first status."),
            EvaluationCase(case_id="case-b", task="Check the second status."),
        ),
    )
    runtime.create_evaluation_suite(suite)
    queued, _ = runtime.enqueue_evaluation_run(
        suite.suite_id, idempotency_key="complete-recovery-001"
    )
    now = datetime.now(timezone.utc)
    stale_at = now - timedelta(seconds=5)
    claimed = runtime.execution_jobs.claim_next_queued(
        "interrupted-worker", stale_at, queued.org_id, queued.workspace_id
    )
    assert claimed is not None
    runtime.execution_jobs.put(
        ExecutionJob.model_validate(
            claimed.model_copy(update={"updated_at": stale_at}).model_dump()
        )
    )
    evaluation = runtime.evaluation_executions.get(queued.evaluation_id)
    results = tuple(
        score_evaluation_case(
            case,
            status=None,
            run_id=None,
            request_error="Provider was unavailable for this completed case.",
        )
        for case in suite.cases
    )
    runtime.evaluation_executions.put(
        EvaluationExecution.model_validate(
            evaluation.model_copy(
                update={
                    "status": EvaluationExecutionStatus.RUNNING,
                    "started_at": stale_at,
                    "updated_at": stale_at,
                    "results": results,
                }
            ).model_dump()
        )
    )

    recovered = runtime.recover_stale_execution_jobs(stale_after_seconds=1, now=now)

    assert recovered == (queued.execution_job_id,)
    job = runtime.execution_jobs.get(queued.execution_job_id)
    completed = runtime.get_evaluation_execution(queued.evaluation_id)
    report = runtime.get_evaluation_report(queued.evaluation_id)
    assert job.status is ExecutionJobStatus.SUCCEEDED
    assert completed.status is EvaluationExecutionStatus.SUCCEEDED
    assert report.report.total_cases == 2
    assert report.report.passed_cases == 0
    assert report.report.pass_rate == 0.0


def test_cancel_requested_evaluation_recovers_cancelled_after_worker_loss():
    runtime = LocalPlatformRuntime()
    suite = EvaluationSuite(
        suite_id="cancel-recovery-smoke",
        agent_id="local-assistant",
        cases=(EvaluationCase(case_id="case-a", task="Check the service."),),
    )
    runtime.create_evaluation_suite(suite)
    queued, _ = runtime.enqueue_evaluation_run(
        suite.suite_id, idempotency_key="cancel-recovery-001"
    )
    now = datetime.now(timezone.utc)
    stale_at = now - timedelta(seconds=5)
    claimed = runtime.execution_jobs.claim_next_queued(
        "interrupted-worker", stale_at, queued.org_id, queued.workspace_id
    )
    assert claimed is not None
    running = runtime.evaluation_executions.get(queued.evaluation_id)
    runtime.evaluation_executions.put(
        EvaluationExecution.model_validate(
            running.model_copy(
                update={
                    "status": EvaluationExecutionStatus.RUNNING,
                    "started_at": stale_at,
                    "updated_at": stale_at,
                }
            ).model_dump()
        )
    )
    runtime.cancel_evaluation_run(queued.evaluation_id)
    requested_job = runtime.execution_jobs.get(queued.execution_job_id)
    requested_evaluation = runtime.evaluation_executions.get(queued.evaluation_id)
    runtime.execution_jobs.put(
        ExecutionJob.model_validate(
            requested_job.model_copy(update={"updated_at": stale_at}).model_dump()
        )
    )
    runtime.evaluation_executions.put(
        EvaluationExecution.model_validate(
            requested_evaluation.model_copy(
                update={"updated_at": stale_at}
            ).model_dump()
        )
    )

    recovered = runtime.recover_stale_execution_jobs(stale_after_seconds=1, now=now)

    assert recovered == (queued.execution_job_id,)
    assert (
        runtime.execution_jobs.get(queued.execution_job_id).status
        is ExecutionJobStatus.CANCELLED
    )
    cancelled = runtime.get_evaluation_execution(queued.evaluation_id)
    assert cancelled.status is EvaluationExecutionStatus.CANCELLED
    assert cancelled.finished_at is not None
    assert cancelled.results == ()


def test_evaluation_run_api_enqueues_replays_and_cancels(monkeypatch):
    monkeypatch.setenv("WEAVES_API_TOKEN", "evaluation-api-test-token")
    monkeypatch.delenv("WEAVES_API_TOKENS", raising=False)
    runtime = LocalPlatformRuntime()
    suite = EvaluationSuite(
        suite_id="api-queued-smoke",
        agent_id="local-assistant",
        cases=(EvaluationCase(case_id="case-a", task="Check the status."),),
    )
    runtime.create_evaluation_suite(suite)
    client = TestClient(
        create_app(runtime),
        headers={"Authorization": "Bearer evaluation-api-test-token"},
    )

    with client:
        unavailable = client.post(
            f"/api/v0/evaluation-suites/{suite.suite_id}/runs",
            headers={"Idempotency-Key": "api-queued-eval-001"},
        )
        assert unavailable.status_code == 503

        # The HTTP route requires durable storage. Mark the test runtime as
        # PostgreSQL-backed to exercise its request/response contract without
        # requiring a live database in this unit test.
        runtime.storage_mode = "postgres"
        submitted = client.post(
            f"/api/v0/evaluation-suites/{suite.suite_id}/runs",
            headers={"Idempotency-Key": "api-queued-eval-001"},
        )
        assert submitted.status_code == 202, submitted.text
        evaluation_id = submitted.json()["evaluation"]["evaluation_id"]
        assert submitted.json()["evaluation"]["status"] == "queued"
        assert submitted.json()["replayed"] is False

        replay = client.post(
            f"/api/v0/evaluation-suites/{suite.suite_id}/runs",
            headers={"Idempotency-Key": "api-queued-eval-001"},
        )
        assert replay.status_code == 202, replay.text
        assert replay.json()["evaluation"]["evaluation_id"] == evaluation_id
        assert replay.json()["replayed"] is True

        listed = client.get("/api/v0/evaluation-runs")
        assert listed.status_code == 200, listed.text
        assert [item["evaluation_id"] for item in listed.json()] == [evaluation_id]

        fetched = client.get(f"/api/v0/evaluation-runs/{evaluation_id}")
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["status"] == "queued"

        cancelled = client.post(f"/api/v0/evaluation-runs/{evaluation_id}/cancel")
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "cancelled"

"""Evaluation suite and report HTTP routes."""

import json
from typing import Any, Callable

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, ValidationError

from weaves.product.contracts.v1 import EvaluationReport, EvaluationSuite
from weaves.product.runtime import IdempotencyConflict, LocalPlatformRuntime


class EvaluationSuiteWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition: dict[str, Any]


class EvaluationReportSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition: dict[str, Any]
    report: dict[str, Any]


def _parse_evaluation_suite(payload: dict[str, Any]) -> EvaluationSuite:
    try:
        return EvaluationSuite.model_validate_json(json.dumps(payload))
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=json.loads(exc.json())) from exc


def _parse_evaluation_report(payload: dict[str, Any]) -> EvaluationReport:
    try:
        return EvaluationReport.model_validate_json(json.dumps(payload))
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=json.loads(exc.json())) from exc


def register_evaluation_routes(
    app: FastAPI,
    platform: LocalPlatformRuntime,
    dump: Callable[[BaseModel], dict[str, Any]],
) -> None:
    """Register evaluation routes on the product API application."""
    _dump = dump

    @app.get("/api/v0/evaluation-suites")
    def list_evaluation_suites() -> list[dict[str, Any]]:
        try:
            return [_dump(item) for item in platform.list_evaluation_suites()]
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.post("/api/v0/evaluation-suites", status_code=201)
    def create_evaluation_suite(
        request: EvaluationSuiteWriteRequest,
    ) -> dict[str, Any]:
        try:
            definition = _parse_evaluation_suite(request.definition)
            return _dump(platform.create_evaluation_suite(definition))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Agent not found") from exc
        except ValueError as exc:
            status_code = 409 if "already exists" in str(exc) else 422
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    @app.get("/api/v0/evaluation-suites/{suite_id}")
    def get_evaluation_suite(suite_id: str) -> dict[str, Any]:
        try:
            return _dump(platform.get_evaluation_suite(suite_id))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Evaluation suite not found"
            ) from exc

    @app.put("/api/v0/evaluation-suites/{suite_id}")
    def update_evaluation_suite(
        suite_id: str, request: EvaluationSuiteWriteRequest
    ) -> dict[str, Any]:
        try:
            definition = _parse_evaluation_suite(request.definition)
            return _dump(platform.update_evaluation_suite(suite_id, definition))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Evaluation suite not found"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/v0/evaluation-reports")
    def list_evaluation_reports() -> list[dict[str, Any]]:
        try:
            return [_dump(item) for item in platform.list_evaluation_reports()]
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.post("/api/v0/evaluation-reports", status_code=201)
    def submit_evaluation_report(
        request: EvaluationReportSubmitRequest,
    ) -> dict[str, Any]:
        try:
            definition = _parse_evaluation_suite(request.definition)
            report = _parse_evaluation_report(request.report)
            return _dump(platform.store_evaluation_report(definition, report))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Evaluation suite or referenced run not found"
            ) from exc
        except ValueError as exc:
            status_code = 409 if "already exists" in str(exc) else 422
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    @app.get("/api/v0/evaluation-reports/{evaluation_id}")
    def get_evaluation_report(evaluation_id: str) -> dict[str, Any]:
        try:
            return _dump(platform.get_evaluation_report(evaluation_id))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Evaluation report not found"
            ) from exc

    @app.post("/api/v0/evaluation-suites/{suite_id}/runs", status_code=202)
    def enqueue_evaluation_run(
        suite_id: str,
        idempotency_key: str = Header(
            alias="Idempotency-Key", min_length=1, max_length=128
        ),
    ) -> dict[str, Any]:
        if platform.storage_mode != "postgres":
            raise HTTPException(
                status_code=503,
                detail="Queued evaluations require PostgreSQL-backed storage",
            )
        try:
            evaluation, replayed = platform.enqueue_evaluation_run(
                suite_id, idempotency_key=idempotency_key
            )
            return {"evaluation": _dump(evaluation), "replayed": replayed}
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Evaluation suite not found"
            ) from exc
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/v0/evaluation-runs")
    def list_evaluation_runs(
        limit: int = Query(default=50, ge=1, le=100),
    ) -> list[dict[str, Any]]:
        try:
            return [
                _dump(item) for item in platform.list_evaluation_executions(limit=limit)
            ]
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.get("/api/v0/evaluation-runs/{evaluation_id}")
    def get_evaluation_run(evaluation_id: str) -> dict[str, Any]:
        try:
            return _dump(platform.get_evaluation_execution(evaluation_id))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Evaluation run not found"
            ) from exc

    @app.post("/api/v0/evaluation-runs/{evaluation_id}/cancel")
    def cancel_evaluation_run(evaluation_id: str) -> dict[str, Any]:
        try:
            return _dump(platform.cancel_evaluation_run(evaluation_id))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Evaluation run not found"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

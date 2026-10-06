"""Contracts and scoring helpers for repeatable agent evaluations."""

from decimal import Decimal
from typing import Optional

from weaves.product.contracts.v1.evaluations import (
    EvaluationCase,
    EvaluationCaseResult,
    EvaluationCheck,
    EvaluationReport,
    EvaluationSuite,
)
from weaves.product.contracts.v1.executions import RunStatus


def score_evaluation_case(
    case: EvaluationCase,
    *,
    status: Optional[str],
    run_id: Optional[str],
    summaries: tuple[str, ...] = (),
    cited_sources: tuple[str, ...] = (),
    tool_call_count: int = 0,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    estimated_cost_usd: Optional[Decimal] = None,
    duration_ms: Optional[int] = None,
    request_error: Optional[str] = None,
) -> EvaluationCaseResult:
    """Score a completed API response without retaining its full model output."""
    combined_output = "\n".join(summaries).casefold()
    cited = set(cited_sources)
    checks = [
        EvaluationCheck(
            name="run_succeeded",
            passed=status == RunStatus.SUCCEEDED.value,
            detail=(
                "Run completed successfully."
                if status == RunStatus.SUCCEEDED.value
                else request_error
                or f"Expected a succeeded run; received {status or 'no response'}."
            ),
        )
    ]
    checks.extend(
        EvaluationCheck(
            name=f"contains:{phrase[:64]}",
            passed=phrase.casefold() in combined_output,
            detail=(
                f"Expected phrase was present: {phrase[:120]}"
                if phrase.casefold() in combined_output
                else f"Expected phrase was missing: {phrase[:120]}"
            ),
        )
        for phrase in case.must_contain
    )
    checks.extend(
        EvaluationCheck(
            name=f"excludes:{phrase[:64]}",
            passed=phrase.casefold() not in combined_output,
            detail=(
                f"Forbidden phrase was absent: {phrase[:120]}"
                if phrase.casefold() not in combined_output
                else f"Forbidden phrase was present: {phrase[:120]}"
            ),
        )
        for phrase in case.must_not_contain
    )
    missing_sources = tuple(
        source for source in case.required_sources if source not in cited
    )
    checks.append(
        EvaluationCheck(
            name="required_sources",
            passed=not missing_sources,
            detail=(
                "All required sources were cited."
                if not missing_sources
                else "Missing cited sources: "
                + ", ".join(source[:64] for source in missing_sources[:5])
            ),
        )
    )
    checks.append(
        EvaluationCheck(
            name="minimum_tool_calls",
            passed=tool_call_count >= case.minimum_tool_calls,
            detail=(
                f"Observed {tool_call_count} tool calls; required at least "
                f"{case.minimum_tool_calls}."
            ),
        )
    )
    return EvaluationCaseResult(
        case_id=case.case_id,
        passed=all(check.passed for check in checks),
        checks=tuple(checks),
        run_id=run_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost_usd=estimated_cost_usd,
        duration_ms=duration_ms,
    )


__all__ = [
    "EvaluationCase",
    "EvaluationCaseResult",
    "EvaluationCheck",
    "EvaluationReport",
    "EvaluationSuite",
    "score_evaluation_case",
]

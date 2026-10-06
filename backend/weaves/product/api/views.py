"""Shared API response projections for runtime execution records."""

from typing import Any, cast

from weaves.product.runtime import LocalPlatformRuntime


def execution_run_view(
    runtime: LocalPlatformRuntime,
    run: Any,
) -> dict[str, Any]:
    """Serialize a run with its related agent, tool, and artifact history."""
    result = cast(dict[str, Any], run.model_dump(mode="json"))
    result["agent_runs"] = [
        item.model_dump(mode="json")
        for item in runtime.agent_runs.list_scoped(run.org_id, run.workspace_id)
        if item.run_id == run.run_id
    ]
    result["tool_invocations"] = [
        item.model_dump(mode="json")
        for item in runtime.tool_invocations.list_scoped(run.org_id, run.workspace_id)
        if item.run_id == run.run_id
    ]
    result["artifacts"] = [
        item.model_dump(mode="json")
        for item in runtime.artifacts.list_scoped(run.org_id, run.workspace_id)
        if item.run_id == run.run_id
    ]
    return result

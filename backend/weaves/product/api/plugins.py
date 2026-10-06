"""Plugin installation and MCP discovery API routes."""

from typing import Any, Callable, Literal, Optional, Union

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from weaves.product.api.common import ProviderCredentialRequest
from weaves.product.contracts.v1 import Permission, PluginInstallationStatus
from weaves.product.runtime import LocalPlatformRuntime
from weaves.product.runtime.plugin_gateway import PluginGatewayError
from weaves.product.runtime.request_identity import (
    effective_org_id,
    effective_workspace_id,
)
from weaves.product.runtime.secrets import SecretStoreUnavailable


class PluginInstallationPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled_capability_ids: Optional[tuple[str, ...]] = None
    status: Optional[PluginInstallationStatus] = None


class GitHubInstallationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    plugin_id: Literal["github"]
    display_name: str = Field(min_length=2, max_length=160)
    api_token: SecretStr = Field(min_length=1, max_length=4096)
    repositories: tuple[str, ...] = Field(min_length=1, max_length=50)


class SlackInstallationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    plugin_id: Literal["slack"]
    display_name: str = Field(min_length=2, max_length=160)
    user_token: SecretStr = Field(min_length=1, max_length=4096)
    channels: tuple[str, ...] = Field(min_length=1, max_length=50)
    include_thread_replies: bool = False


class JiraInstallationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    plugin_id: Literal["jira"]
    display_name: str = Field(min_length=2, max_length=160)
    api_token: SecretStr = Field(min_length=1, max_length=4096)
    site_url: str = Field(
        min_length=12,
        max_length=256,
        pattern=r"^https://[A-Za-z0-9-]+\.atlassian\.net/?$",
    )
    email: str = Field(min_length=3, max_length=320)
    project_keys: tuple[str, ...] = Field(min_length=1, max_length=50)


class McpToolDiscoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    endpoint_url: str = Field(min_length=12, max_length=2048)
    bearer_token: Optional[SecretStr] = Field(default=None, max_length=4096)


class McpInstallationCreateRequest(McpToolDiscoverRequest):
    plugin_id: Literal["mcp"]
    display_name: str = Field(min_length=2, max_length=160)
    read_only_tool_names: tuple[str, ...] = Field(min_length=1, max_length=100)


def _installation_view(
    installation: Any, dump: Callable[[BaseModel], dict[str, Any]]
) -> dict[str, Any]:
    result = dump(installation)
    result.pop("auth_ref", None)
    result["has_credentials"] = bool(installation.auth_ref)
    return result


def register_plugin_routes(
    app: FastAPI,
    platform: LocalPlatformRuntime,
    dump: Callable[[BaseModel], dict[str, Any]],
) -> None:
    """Register plugin installation, credential, health, and MCP endpoints."""
    _dump = dump

    def installation_view(installation: Any) -> dict[str, Any]:
        return _installation_view(installation, _dump)

    @app.get("/api/v0/plugin-installations")
    def list_plugin_installations() -> list[dict[str, Any]]:
        platform.authorize("local-developer", Permission.PLUGINS_MANAGE)
        return [
            installation_view(item)
            for item in platform.installations.list_scoped(
                effective_org_id(), effective_workspace_id()
            )
        ]

    @app.post("/api/v0/mcp/discover")
    def discover_mcp_tools(request: McpToolDiscoverRequest) -> list[dict[str, Any]]:
        try:
            return list(
                platform.discover_mcp_tools(
                    endpoint_url=request.endpoint_url,
                    bearer_token=(
                        request.bearer_token.get_secret_value()
                        if request.bearer_token
                        else None
                    ),
                )
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v0/plugin-installations", status_code=201)
    def create_plugin_installation(
        request: Union[
            GitHubInstallationCreateRequest,
            SlackInstallationCreateRequest,
            JiraInstallationCreateRequest,
            McpInstallationCreateRequest,
        ],
    ) -> dict[str, Any]:
        try:
            if isinstance(request, GitHubInstallationCreateRequest):
                installation = platform.create_github_installation(
                    display_name=request.display_name,
                    api_token=request.api_token.get_secret_value(),
                    repositories=request.repositories,
                )
            elif isinstance(request, SlackInstallationCreateRequest):
                installation = platform.create_slack_installation(
                    display_name=request.display_name,
                    user_token=request.user_token.get_secret_value(),
                    channels=request.channels,
                    include_thread_replies=request.include_thread_replies,
                )
            elif isinstance(request, McpInstallationCreateRequest):
                installation = platform.create_mcp_installation(
                    display_name=request.display_name,
                    endpoint_url=request.endpoint_url,
                    bearer_token=(
                        request.bearer_token.get_secret_value()
                        if request.bearer_token
                        else None
                    ),
                    read_only_tool_names=request.read_only_tool_names,
                )
            else:
                installation = platform.create_jira_installation(
                    display_name=request.display_name,
                    api_token=request.api_token.get_secret_value(),
                    site_url=request.site_url,
                    email=request.email,
                    project_keys=request.project_keys,
                )
        except SecretStoreUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return installation_view(installation)

    @app.put("/api/v0/plugin-installations/{installation_id}/credential")
    def rotate_plugin_credential(
        installation_id: str, request: ProviderCredentialRequest
    ) -> dict[str, Any]:
        try:
            installation = platform.rotate_plugin_credential(
                installation_id, request.api_key.get_secret_value()
            )
        except SecretStoreUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Plugin installation not found"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return installation_view(installation)

    @app.post("/api/v0/plugin-installations/{installation_id}/healthcheck")
    def healthcheck_plugin_installation(installation_id: str) -> dict[str, str]:
        try:
            details = platform.healthcheck_plugin_installation(installation_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Plugin installation not found"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except PluginGatewayError as exc:
            raise HTTPException(status_code=502, detail=exc.message) from exc
        return {"status": "ok", **details}

    @app.patch("/api/v0/plugin-installations/{installation_id}")
    def update_plugin_installation(
        installation_id: str, patch: PluginInstallationPatchRequest
    ) -> dict[str, Any]:
        changes = patch.model_dump(exclude_unset=True)
        if not changes:
            raise HTTPException(status_code=400, detail="No changes supplied")
        try:
            installation = platform.update_plugin_installation(
                installation_id, **changes
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Plugin installation not found"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return installation_view(installation)

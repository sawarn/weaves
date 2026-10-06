"""Read-only GitHub search capability, bound to a workspace installation."""

from __future__ import annotations

import re
from time import monotonic
from typing import Any, Protocol

import httpx

from weaves.product.contracts.v1 import PluginInstallation
from weaves.product.contracts.v1.json_data import thaw_json_value
from weaves.product.runtime.plugin_gateway import PluginGatewayError


class _Resolver(Protocol):
    def resolve(self, auth_ref: str) -> str: ...


class GitHubReadPlugin:
    """Search issues and pull requests within configured repositories only."""

    def __init__(
        self,
        secret_resolver: _Resolver,
        client: httpx.Client,
        *,
        api_base_url: str = "https://api.github.com",
        timeout_seconds: float = 15.0,
    ) -> None:
        self._secrets = secret_resolver
        self._client = client
        self._api_base_url = api_base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def healthcheck(self, installation: PluginInstallation) -> dict[str, str]:
        token = self._resolve_token(installation)
        configuration = thaw_json_value(installation.configuration)
        repositories = configuration.get("repositories", [])
        if not repositories:
            raise PluginGatewayError(
                "plugin.configuration_invalid",
                "GitHub installation has no repositories",
            )
        repository = repositories[0]
        if (
            not isinstance(repository, str)
            or re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is None
        ):
            raise PluginGatewayError(
                "plugin.configuration_invalid",
                "GitHub repository configuration is invalid",
            )
        try:
            response = self._client.get(
                f"{self._api_base_url}/repos/{repository}",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {token}",
                    "X-GitHub-Api-Version": "2026-03-10",
                },
                timeout=self._timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise PluginGatewayError(
                "plugin.timeout", "GitHub request timed out"
            ) from exc
        except httpx.HTTPError as exc:
            raise PluginGatewayError(
                "plugin.transport_error", "GitHub request failed"
            ) from exc
        if response.is_error:
            raise PluginGatewayError(
                "plugin.upstream_error", f"GitHub returned HTTP {response.status_code}"
            )
        try:
            full_name = response.json().get("full_name")
        except (ValueError, AttributeError) as exc:
            raise PluginGatewayError(
                "plugin.invalid_response", "GitHub returned an invalid response"
            ) from exc
        if not isinstance(full_name, str) or not full_name:
            raise PluginGatewayError(
                "plugin.invalid_response", "GitHub returned an invalid response"
            )
        return {"repository": full_name}

    def invoke_for_installation(
        self,
        capability_id: str,
        payload: dict[str, Any],
        installation: PluginInstallation,
    ) -> dict[str, Any]:
        if capability_id != "github.issues.search":
            raise PluginGatewayError(
                "plugin.capability_unknown", "GitHub capability is not supported"
            )
        configuration = thaw_json_value(installation.configuration)
        repositories = configuration.get("repositories", [])
        if not repositories:
            raise PluginGatewayError(
                "plugin.configuration_invalid",
                "GitHub installation has no repositories",
            )
        token = self._resolve_token(installation)

        query = payload["query"].strip()
        if not query:
            raise PluginGatewayError(
                "plugin.input_invalid", "GitHub search query is invalid"
            )
        if re.search(r"(?i)\b(?:repo|org|user):", query):
            raise PluginGatewayError(
                "plugin.query_scope_denied",
                "Repository scope is controlled by the installation",
            )
        documents: list[dict[str, Any]] = []
        deadline = monotonic() + self._timeout_seconds
        for repository in repositories:
            if len(documents) >= 5:
                break
            remaining = deadline - monotonic()
            if remaining <= 0:
                break
            try:
                response = self._client.get(
                    f"{self._api_base_url}/search/issues",
                    params={
                        "q": f"repo:{repository} {query}",
                        "per_page": min(5 - len(documents), 5),
                    },
                    headers={
                        "Accept": "application/vnd.github+json",
                        "Authorization": f"Bearer {token}",
                        "X-GitHub-Api-Version": "2026-03-10",
                    },
                    timeout=min(5.0, remaining),
                )
            except httpx.TimeoutException as exc:
                raise PluginGatewayError(
                    "plugin.timeout", "GitHub request timed out"
                ) from exc
            except httpx.HTTPError as exc:
                raise PluginGatewayError(
                    "plugin.transport_error", "GitHub request failed"
                ) from exc
            if response.is_error:
                raise PluginGatewayError(
                    "plugin.upstream_error",
                    f"GitHub returned HTTP {response.status_code}",
                )
            try:
                items = response.json()["items"]
            except (ValueError, KeyError, TypeError) as exc:
                raise PluginGatewayError(
                    "plugin.invalid_response", "GitHub returned an invalid response"
                ) from exc
            for item in items:
                if not isinstance(item, dict):
                    continue
                number = item.get("number")
                title = item.get("title")
                url = item.get("html_url")
                body = item.get("body") or ""
                if not isinstance(number, int) or not isinstance(title, str):
                    continue
                if not isinstance(body, str):
                    body = ""
                state = item.get("state", "unknown")
                text = (
                    f"Issue or pull request state: {state}. "
                    f"URL: {url or 'unavailable'}.\n{body[:1500]}"
                )[:2000]
                documents.append(
                    {
                        "source_id": f"github:{repository}#{number}",
                        "title": f"{repository} #{number}: {title}"[:160],
                        "text": text,
                    }
                )
                if len(documents) >= 5:
                    break
        return {"documents": documents}

    def _resolve_token(self, installation: PluginInstallation) -> str:
        if not installation.auth_ref:
            raise PluginGatewayError(
                "plugin.credential_missing", "GitHub installation has no credential"
            )
        try:
            token = self._secrets.resolve(installation.auth_ref)
        except Exception as exc:
            raise PluginGatewayError(
                "plugin.credential_unavailable",
                "GitHub credential could not be resolved",
            ) from exc
        if not token:
            raise PluginGatewayError(
                "plugin.credential_unavailable",
                "GitHub credential could not be resolved",
            )
        return token

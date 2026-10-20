"""Browser-based authorization for supported first-party connectors."""

from __future__ import annotations

import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, cast
from urllib.parse import urlencode, urlparse

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from weaves.product.contracts.v1 import OAuthAuthorizationState, Permission
from weaves.product.runtime import LocalPlatformRuntime
from weaves.product.runtime.request_identity import (
    effective_org_id,
    effective_principal_id,
    effective_workspace_id,
    set_request_identity,
)


class _OAuthStart(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    display_name: str = Field(min_length=2, max_length=160)
    repositories: tuple[str, ...] = Field(default=(), max_length=50)
    channels: tuple[str, ...] = Field(default=(), max_length=50)
    include_thread_replies: bool = False
    site_url: str | None = Field(default=None, min_length=12, max_length=256)
    project_keys: tuple[str, ...] = Field(default=(), max_length=50)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _state_string(record: OAuthAuthorizationState, key: str) -> str:
    value = record.configuration.get(key)
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail="OAuth state configuration is invalid")
    return value


def _state_strings(record: OAuthAuthorizationState, key: str) -> tuple[str, ...]:
    value = record.configuration.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise HTTPException(status_code=400, detail="OAuth state configuration is invalid")
    return tuple(cast(list[str], value))


def _state_bool(record: OAuthAuthorizationState, key: str) -> bool:
    value = record.configuration.get(key)
    if not isinstance(value, bool):
        raise HTTPException(status_code=400, detail="OAuth state configuration is invalid")
    return value


def register_oauth_routes(app: FastAPI, platform: LocalPlatformRuntime) -> None:
    """Register authenticated start routes and unauthenticated OAuth callbacks."""
    client = httpx.Client()
    api_base = os.environ.get("WEAVES_PUBLIC_API_BASE_URL", "").strip().rstrip("/")
    frontend = os.environ.get("WEAVES_PUBLIC_FRONTEND_URL", "https://app.weave-studio.in").strip().rstrip("/")

    def callback_url(path: str) -> str:
        if not api_base:
            raise HTTPException(status_code=503, detail="Connector OAuth is not configured")
        return f"{api_base}/api/v0/oauth/{path}"

    def state_record(
        provider: Literal["github", "slack", "jira"],
        configuration: dict[str, Any],
        *,
        step: Literal["authorize", "github_install"] = "authorize",
        secret_ref: str | None = None,
    ) -> OAuthAuthorizationState:
        principal = platform.authenticate_principal("local-developer")
        principal = effective_principal_id(principal)
        platform.authorize(principal, Permission.PLUGINS_MANAGE)
        now = _now()
        for expired in platform.oauth_authorization_states.list():
            if expired.expires_at <= now:
                try:
                    platform.oauth_authorization_states.delete(expired.oauth_state_id)
                except KeyError:
                    pass
        record = OAuthAuthorizationState(
            oauth_state_id=secrets.token_urlsafe(32), provider=provider, step=step,
            principal_id=principal, org_id=effective_org_id(), workspace_id=effective_workspace_id(),
            configuration=configuration, secret_ref=secret_ref,
            created_at=now, expires_at=now + timedelta(minutes=10),
        )
        platform.oauth_authorization_states.create(record)
        return record

    def take_state(
        value: str,
        provider: Literal["github", "slack", "jira"],
        step: Literal["authorize", "github_install"] = "authorize",
    ) -> OAuthAuthorizationState:
        try:
            record = platform.oauth_authorization_states.consume(value)
        except KeyError as exc:
            raise HTTPException(status_code=400, detail="Authorization state is invalid or already used") from exc
        if record.provider != provider or record.step != step or record.expires_at <= _now():
            raise HTTPException(status_code=400, detail="Authorization state is invalid or expired")
        return record

    def discard_state(value: str, provider: Literal["github", "slack", "jira"]) -> None:
        try:
            take_state(value, provider)
        except HTTPException:
            return

    def request_as(record: OAuthAuthorizationState) -> None:
        set_request_identity(record.principal_id, record.org_id, record.workspace_id)
        platform.authorize(record.principal_id, Permission.PLUGINS_MANAGE)

    def finish(provider: str, status: str) -> RedirectResponse:
        return RedirectResponse(
            f"{frontend}/?connector_oauth={status}&provider={provider}#connections",
            status_code=303,
        )

    def exchange(
        url: str,
        *,
        data: dict[str, str],
        auth: tuple[str, str] | None = None,
        json_payload: bool = False,
    ) -> dict[str, Any]:
        try:
            request_data: dict[str, Any] = {
                "headers": {"Accept": "application/json"},
                "timeout": 20,
            }
            if json_payload:
                request_data["json"] = data
            else:
                request_data["data"] = data
            if auth is not None:
                request_data["auth"] = auth
            response = client.post(url, **request_data)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(status_code=502, detail="OAuth provider token exchange failed") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=502, detail="OAuth provider returned an invalid response")
        return payload

    def token_bundle(provider: str, payload: dict[str, Any], *, access_token: str | None = None) -> str:
        token = access_token or payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise HTTPException(status_code=502, detail="OAuth provider did not return an access token")
        expires_in = payload.get("expires_in", 3600)
        if not isinstance(expires_in, (int, float)):
            expires_in = 3600
        return json.dumps({
            "weaves_oauth": True, "provider": provider, "access_token": token,
            "refresh_token": payload.get("refresh_token"),
            "expires_at": (_now() + timedelta(seconds=int(expires_in))).isoformat(),
        }, separators=(",", ":"))

    @app.get("/api/v0/oauth/providers")
    def oauth_providers() -> dict[str, bool]:
        platform.authorize("local-developer", Permission.PLUGINS_MANAGE)
        public_api_configured = bool(os.environ.get("WEAVES_PUBLIC_API_BASE_URL", "").strip())
        return {
            "github": public_api_configured and bool(os.environ.get("WEAVES_GITHUB_APP_CLIENT_ID", "").strip() and os.environ.get("WEAVES_GITHUB_APP_CLIENT_SECRET", "").strip() and os.environ.get("WEAVES_GITHUB_APP_SLUG", "").strip() and os.environ.get("WEAVES_GITHUB_APP_ID", "").strip() and os.environ.get("WEAVES_GITHUB_APP_PRIVATE_KEY", "").strip()),
            "slack": public_api_configured and bool(os.environ.get("WEAVES_SLACK_OAUTH_CLIENT_ID", "").strip() and os.environ.get("WEAVES_SLACK_OAUTH_CLIENT_SECRET", "").strip()),
            "jira": public_api_configured and bool(os.environ.get("WEAVES_ATLASSIAN_OAUTH_CLIENT_ID", "").strip() and os.environ.get("WEAVES_ATLASSIAN_OAUTH_CLIENT_SECRET", "").strip()),
        }

    @app.post("/api/v0/oauth/{provider}/start")
    def start_oauth(provider: str, request: _OAuthStart) -> dict[str, str]:
        platform.authorize("local-developer", Permission.PLUGINS_MANAGE)
        client_id = ""
        configuration: dict[str, Any] = {"display_name": request.display_name}
        if provider == "github":
            client_id = os.environ.get("WEAVES_GITHUB_APP_CLIENT_ID", "").strip()
            if not all((
                client_id,
                os.environ.get("WEAVES_GITHUB_APP_CLIENT_SECRET", "").strip(),
                os.environ.get("WEAVES_GITHUB_APP_SLUG", "").strip(),
                os.environ.get("WEAVES_GITHUB_APP_ID", "").strip(),
                os.environ.get("WEAVES_GITHUB_APP_PRIVATE_KEY", "").strip(),
            )):
                raise HTTPException(status_code=503, detail="GitHub App OAuth is not configured")
            if not request.repositories:
                raise HTTPException(status_code=422, detail="Select at least one repository")
            configuration["repositories"] = list(request.repositories)
            redirect = callback_url("github/callback")
            state = state_record("github", configuration)
            return {"authorization_url": "https://github.com/login/oauth/authorize?" + urlencode({"client_id": client_id, "redirect_uri": redirect, "state": state.oauth_state_id})}
        if provider == "slack":
            client_id = os.environ.get("WEAVES_SLACK_OAUTH_CLIENT_ID", "").strip()
            if not client_id or not os.environ.get("WEAVES_SLACK_OAUTH_CLIENT_SECRET", "").strip():
                raise HTTPException(status_code=503, detail="Slack OAuth is not configured")
            if not request.channels:
                raise HTTPException(status_code=422, detail="Select at least one Slack channel")
            configuration.update({"channels": list(request.channels), "include_thread_replies": request.include_thread_replies})
            redirect = callback_url("slack/callback")
            state = state_record("slack", configuration)
            scopes = "search:read,channels:history,groups:history"
            params = {"client_id": client_id, "redirect_uri": redirect, "state": state.oauth_state_id, "user_scope": scopes}
            return {"authorization_url": "https://slack.com/oauth/v2/authorize?" + urlencode(params)}
        if provider == "jira":
            client_id = os.environ.get("WEAVES_ATLASSIAN_OAUTH_CLIENT_ID", "").strip()
            if not client_id or not os.environ.get("WEAVES_ATLASSIAN_OAUTH_CLIENT_SECRET", "").strip():
                raise HTTPException(status_code=503, detail="Atlassian OAuth is not configured")
            site_url = (request.site_url or "").rstrip("/")
            if re.fullmatch(r"https://[A-Za-z0-9-]+\.atlassian\.net", site_url) is None:
                raise HTTPException(status_code=422, detail="Enter a valid Atlassian site URL")
            if not request.project_keys:
                raise HTTPException(status_code=422, detail="Select at least one Jira project")
            configuration.update({"site_url": site_url, "project_keys": list(request.project_keys)})
            redirect = callback_url("jira/callback")
            state = state_record("jira", configuration)
            params = {"audience": "api.atlassian.com", "client_id": client_id, "scope": "read:jira-work write:jira-work offline_access", "redirect_uri": redirect, "state": state.oauth_state_id, "response_type": "code", "prompt": "consent"}
            return {"authorization_url": "https://auth.atlassian.com/authorize?" + urlencode(params)}
        raise HTTPException(status_code=404, detail="OAuth connector is not supported")

    @app.get("/api/v0/oauth/github/callback", include_in_schema=False)
    def github_callback(code: str | None = None, state: str = Query(...), error: str | None = None) -> RedirectResponse:
        if error or not code:
            discard_state(state, "github")
            return finish("github", "failed")
        record = take_state(state, "github")
        request_as(record)
        app_id = os.environ["WEAVES_GITHUB_APP_CLIENT_ID"].strip()
        app_secret = os.environ["WEAVES_GITHUB_APP_CLIENT_SECRET"].strip()
        try:
            payload = exchange("https://github.com/login/oauth/access_token", data={"client_id": app_id, "client_secret": app_secret, "code": code, "redirect_uri": callback_url("github/callback"), "state": state})
        except HTTPException:
            return finish("github", "failed")
        user_token = payload.get("access_token")
        if not isinstance(user_token, str):
            return finish("github", "failed")
        secret_ref = platform.secret_store.put(user_token)
        try:
            install_state = state_record("github", dict(record.configuration), step="github_install", secret_ref=secret_ref)
        except Exception:
            platform.secret_store.delete(secret_ref)
            return finish("github", "failed")
        slug = os.environ["WEAVES_GITHUB_APP_SLUG"].strip()
        return RedirectResponse(f"https://github.com/apps/{slug}/installations/new?state={install_state.oauth_state_id}", status_code=303)

    @app.get("/api/v0/oauth/github/installation", include_in_schema=False)
    def github_installation(installation_id: str = Query(...), state: str = Query(...), setup_action: str = Query(default="install")) -> RedirectResponse:
        record = take_state(state, "github", "github_install")
        if setup_action != "install":
            if record.secret_ref:
                platform.secret_store.delete(record.secret_ref)
            return finish("github", "failed")
        request_as(record)
        if not record.secret_ref:
            return finish("github", "failed")
        user_token = platform.secret_store.get(record.secret_ref)
        try:
            response = client.get("https://api.github.com/user/installations?per_page=100", headers={"Authorization": f"Bearer {user_token}", "Accept": "application/vnd.github+json"}, timeout=15)
            response.raise_for_status()
            installations = response.json().get("installations", [])
            while response.links.get("next"):
                response = client.get(response.links["next"]["url"], headers={"Authorization": f"Bearer {user_token}", "Accept": "application/vnd.github+json"}, timeout=15)
                response.raise_for_status()
                installations.extend(response.json().get("installations", []))
        except (httpx.HTTPError, ValueError, AttributeError):
            platform.secret_store.delete(record.secret_ref)
            return finish("github", "failed")
        if not any(str(item.get("id")) == installation_id for item in installations if isinstance(item, dict)):
            platform.secret_store.delete(record.secret_ref)
            return finish("github", "failed")
        repos = _state_strings(record, "repositories")
        try:
            token = platform.github_app_token_provider.installation_token(installation_id, repos)
            response = client.get("https://api.github.com/installation/repositories?per_page=100", headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}, timeout=15)
            response.raise_for_status()
            repository_rows = response.json().get("repositories", [])
            while response.links.get("next"):
                response = client.get(response.links["next"]["url"], headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}, timeout=15)
                response.raise_for_status()
                repository_rows.extend(response.json().get("repositories", []))
            available = {item.get("full_name") for item in repository_rows if isinstance(item, dict)}
            if not set(repos).issubset(available):
                raise ValueError("requested repo outside installation")
            platform.create_github_app_installation(
                display_name=_state_string(record, "display_name"),
                github_installation_id=installation_id,
                repositories=repos,
                requested_by_principal_id=record.principal_id,
            )
        except Exception:
            platform.secret_store.delete(record.secret_ref)
            return finish("github", "failed")
        platform.secret_store.delete(record.secret_ref)
        return finish("github", "success")

    @app.get("/api/v0/oauth/slack/callback", include_in_schema=False)
    def slack_callback(code: str | None = None, state: str = Query(...), error: str | None = None) -> RedirectResponse:
        if error or not code:
            discard_state(state, "slack")
            return finish("slack", "failed")
        record = take_state(state, "slack")
        request_as(record)
        client_id = os.environ["WEAVES_SLACK_OAUTH_CLIENT_ID"].strip()
        client_secret = os.environ["WEAVES_SLACK_OAUTH_CLIENT_SECRET"].strip()
        redirect = callback_url("slack/callback")
        try:
            payload = exchange("https://slack.com/api/oauth.v2.access", data={"code": code, "redirect_uri": redirect}, auth=(client_id, client_secret))
        except HTTPException:
            return finish("slack", "failed")
        if payload.get("ok") is not True:
            return finish("slack", "failed")
        user = payload.get("authed_user") or {}
        access_token = user.get("access_token") if isinstance(user, dict) else None
        if not isinstance(access_token, str):
            return finish("slack", "failed")
        bundle = token_bundle("slack", user, access_token=access_token)
        try:
            platform.create_slack_oauth_installation(
                display_name=_state_string(record, "display_name"), token_bundle=bundle,
                channels=_state_strings(record, "channels"),
                include_thread_replies=_state_bool(record, "include_thread_replies"),
                requested_by_principal_id=record.principal_id,
            )
        except Exception:
            return finish("slack", "failed")
        return finish("slack", "success")

    @app.get("/api/v0/oauth/jira/callback", include_in_schema=False)
    def jira_callback(code: str | None = None, state: str = Query(...), error: str | None = None) -> RedirectResponse:
        if error or not code:
            discard_state(state, "jira")
            return finish("jira", "failed")
        record = take_state(state, "jira")
        request_as(record)
        client_id = os.environ["WEAVES_ATLASSIAN_OAUTH_CLIENT_ID"].strip()
        client_secret = os.environ["WEAVES_ATLASSIAN_OAUTH_CLIENT_SECRET"].strip()
        redirect = callback_url("jira/callback")
        try:
            payload = exchange("https://auth.atlassian.com/oauth/token", data={"grant_type": "authorization_code", "client_id": client_id, "client_secret": client_secret, "code": code, "redirect_uri": redirect}, json_payload=True)
        except HTTPException:
            return finish("jira", "failed")
        access = payload.get("access_token")
        if not isinstance(access, str):
            return finish("jira", "failed")
        try:
            response = client.get("https://api.atlassian.com/oauth/token/accessible-resources", headers={"Authorization": f"Bearer {access}", "Accept": "application/json"}, timeout=15)
            response.raise_for_status()
            resources = response.json()
        except (httpx.HTTPError, ValueError):
            return finish("jira", "failed")
        site_url = _state_string(record, "site_url")
        expected_host = urlparse(site_url).hostname
        resource = next((item for item in resources if isinstance(item, dict) and urlparse(item.get("url", "")).hostname == expected_host), None)
        if not resource or not isinstance(resource.get("id"), str):
            return finish("jira", "failed")
        try:
            platform.create_jira_oauth_installation(
                display_name=_state_string(record, "display_name"), token_bundle=token_bundle("jira", payload),
                site_url=site_url, cloud_id=resource["id"],
                project_keys=_state_strings(record, "project_keys"),
                requested_by_principal_id=record.principal_id,
            )
        except Exception:
            return finish("jira", "failed")
        return finish("jira", "success")

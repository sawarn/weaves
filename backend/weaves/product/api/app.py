"""FastAPI surface for the platform-native local v0."""

import hashlib
import hmac
import json
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from starlette.responses import JSONResponse

from weaves.product.api.agents import register_agent_routes
from weaves.product.api.context import register_context_routes
from weaves.product.api.evaluations import register_evaluation_routes
from weaves.product.api.executions import register_execution_routes
from weaves.product.api.governance import register_governance_routes
from weaves.product.api.identity import register_identity_routes
from weaves.product.api.models import register_model_routes
from weaves.product.api.plugins import register_plugin_routes
from weaves.product.api.views import execution_run_view
from weaves.product.api.workflows import register_workflow_routes
from weaves.product.runtime import (
    LocalPlatformRuntime,
)
from weaves.product.runtime.request_identity import (
    reset_request_principal,
    set_request_identity,
)


def create_app(runtime: Optional[LocalPlatformRuntime] = None) -> FastAPI:
    """Create the isolated product API and its local runtime dependency."""
    platform = runtime or LocalPlatformRuntime()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        platform.bootstrap()
        platform.purge_expired_memory_items()
        try:
            yield
        finally:
            platform.close()

    app = FastAPI(
        title="Weaves Platform API",
        version="0.1.0",
        description="Local v0 API for configuring and testing the Weaves platform path.",
        lifespan=lifespan,
    )

    @app.exception_handler(PermissionError)
    async def permission_error_handler(_: Any, exc: PermissionError) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    api_tokens: dict[str, str] = {}
    raw_api_tokens = os.environ.get("WEAVES_API_TOKENS", "").strip()
    if raw_api_tokens:
        try:
            configured_tokens = json.loads(raw_api_tokens)
        except json.JSONDecodeError as exc:
            raise ValueError("WEAVES_API_TOKENS must contain a JSON array") from exc
        if not isinstance(configured_tokens, list):
            raise ValueError("WEAVES_API_TOKENS must contain a JSON array")
        for item in configured_tokens:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("token"), str)
                or not item["token"].strip()
                or not isinstance(item.get("principal_id"), str)
                or not item["principal_id"].strip()
            ):
                raise ValueError(
                    "Each WEAVES_API_TOKENS item needs token and principal_id strings"
                )
            digest = hashlib.sha256(item["token"].encode("utf-8")).hexdigest()
            if digest in api_tokens:
                raise ValueError("WEAVES_API_TOKENS contains a duplicate token")
            api_tokens[digest] = item["principal_id"].strip()
    legacy_api_token = os.environ.get("WEAVES_API_TOKEN", "").strip()
    if legacy_api_token:
        digest = hashlib.sha256(legacy_api_token.encode("utf-8")).hexdigest()
        api_tokens.setdefault(digest, "local-developer")

    @app.middleware("http")
    async def require_api_token(request: Any, call_next: Any) -> Any:
        """Authenticate configured bearer tokens and propagate their principal."""
        if (
            request.method == "OPTIONS"
            or request.url.path == "/api/v0/health"
            or request.url.path == "/api/v0/onboarding/organizations"
            or request.url.path == "/api/v0/auth/login"
            or request.url.path == "/api/v0/auth/accept-invitation"
            or request.url.path.startswith("/api/v0/webhooks/")
            or not request.url.path.startswith("/api/v0/")
        ):
            return await call_next(request)
        principal_id = "local-developer"
        authorization = request.headers.get("authorization", "")
        if platform.storage_mode == "postgres" and not authorization.strip():
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing bearer token"},
                headers={"WWW-Authenticate": "Bearer"},
            )
        if api_tokens or authorization:
            scheme, separator, supplied_token = authorization.partition(" ")
            digest = hashlib.sha256(supplied_token.encode("utf-8")).hexdigest()
            mapped_principal = next(
                (
                    candidate
                    for configured_digest, candidate in api_tokens.items()
                    if hmac.compare_digest(digest, configured_digest)
                ),
                None,
            )
            if not separator or scheme.casefold() != "bearer":
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid or missing bearer token"},
                    headers={"WWW-Authenticate": "Bearer"},
                )
            try:
                if mapped_principal is not None:
                    principal_id = platform.authenticate_principal(mapped_principal)
                else:
                    principal_id = (
                        platform.authenticate_api_token(supplied_token)
                        or platform.authenticate_user_session(supplied_token)
                        or ""
                    )
                if not principal_id:
                    raise PermissionError("unknown or revoked token")
            except (KeyError, PermissionError):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid or disabled bearer token subject"},
                    headers={"WWW-Authenticate": "Bearer"},
                )
        try:
            org_id, workspace_id = platform.resolve_principal_scope(
                principal_id, request.headers.get("x-workspace-id")
            )
        except (KeyError, PermissionError):
            return JSONResponse(
                status_code=403,
                content={"detail": "Principal cannot access the requested workspace"},
            )
        identity_token = set_request_identity(principal_id, org_id, workspace_id)
        try:
            return await call_next(request)
        finally:
            reset_request_principal(identity_token)

    allowed_origins = tuple(
        origin.strip().rstrip("/")
        for origin in os.environ.get(
            "CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080,http://127.0.0.1:8080",
        ).split(",")
        if origin.strip()
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Workspace-ID"],
    )
    app.state.platform_runtime = platform

    @app.get("/", include_in_schema=False)
    def api_root() -> RedirectResponse:
        return RedirectResponse(url="/docs")

    @app.get("/api/v0/health")
    def health() -> dict[str, str]:
        try:
            platform.check_storage()
        except Exception as exc:
            raise HTTPException(status_code=503, detail="storage unavailable") from exc
        return {"status": "ok", "storage": platform.storage_mode}

    register_identity_routes(app, platform, _dump)

    register_model_routes(app, platform, _dump)

    register_plugin_routes(app, platform, _dump)

    register_context_routes(app, platform, _dump, execution_run_view)

    register_agent_routes(app, platform, _dump)

    register_evaluation_routes(app, platform, _dump)

    register_workflow_routes(app, platform, _dump, execution_run_view)

    register_execution_routes(app, platform, _dump, execution_run_view)

    register_governance_routes(app, platform, _dump)

    return app


def _dump(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")


app = create_app()

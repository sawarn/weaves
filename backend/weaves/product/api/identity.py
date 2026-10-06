"""Organization identity, access, and credential API routes."""

import hmac
import os
from typing import Any, Callable, Optional

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from weaves.product.contracts.v1 import Permission, WorkspaceStatus
from weaves.product.runtime import LocalPlatformRuntime
from weaves.product.runtime.auth_throttle import LoginThrottled, RateLimitExceeded
from weaves.product.runtime.request_identity import (
    effective_org_id,
    effective_principal_id,
)


class ServiceAccountCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=2, max_length=160)
    permissions: list[Permission] = Field(min_length=1, max_length=20)
    expires_in_days: Optional[int] = Field(default=None, ge=1, le=365)


class OrganizationOnboardingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=2, max_length=160)
    owner_email: str = Field(min_length=3, max_length=320)
    owner_display_name: str = Field(min_length=1, max_length=160)


class UserLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    password: SecretStr = Field(min_length=12, max_length=1024)
    organization_id: Optional[str] = Field(default=None, min_length=1, max_length=128)


class UserPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: SecretStr = Field(min_length=12, max_length=1024)
    current_password: Optional[SecretStr] = Field(default=None, max_length=1024)


class WorkspaceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=160)
    environment: str = Field(default="default", min_length=1, max_length=160)


class WorkspacePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    environment: Optional[str] = Field(default=None, min_length=1, max_length=160)
    status: Optional[WorkspaceStatus] = None


class WorkspaceUserCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=160)
    permissions: Optional[list[Permission]] = Field(default=None, max_length=20)
    role_id: Optional[str] = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def has_one_role_source(self) -> "WorkspaceUserCreateRequest":
        if (self.role_id is None) == (not self.permissions):
            raise ValueError("provide exactly one of role_id or permissions")
        return self


class UserInvitationCreateRequest(WorkspaceUserCreateRequest):
    """A user with either an existing organization role or explicit permissions."""


class UserInvitationAcceptanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invitation_token: SecretStr = Field(min_length=20, max_length=256)
    password: SecretStr = Field(min_length=12, max_length=1024)


class RoleCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=160)
    permissions: list[Permission] = Field(min_length=1, max_length=20)


class RoleBindingCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    principal_id: str = Field(min_length=1, max_length=128)
    role_id: str = Field(min_length=1, max_length=128)
    workspace_id: Optional[str] = Field(default=None, min_length=1, max_length=128)


def _credential_view(credential: Any) -> dict[str, Any]:
    return {
        "id": credential.id,
        "principal_id": credential.principal_id,
        "status": credential.status.value,
        "expires_at": (
            credential.expires_at.isoformat() if credential.expires_at else None
        ),
        "revoked_at": (
            credential.revoked_at.isoformat() if credential.revoked_at else None
        ),
        "created_at": credential.created_at.isoformat(),
        "updated_at": credential.updated_at.isoformat(),
    }


def register_identity_routes(
    app: FastAPI,
    platform: LocalPlatformRuntime,
    dump: Callable[[BaseModel], dict[str, Any]],
) -> None:
    """Register organization, workspace, user, session, and token endpoints."""
    _dump = dump

    def _invitation_view(invitation: Any) -> dict[str, Any]:
        result = _dump(invitation)
        result.pop("token_digest", None)
        return result

    @app.get("/api/v0/organizations")
    def list_organizations() -> list[dict[str, Any]]:
        return [_dump(platform.organizations.get(effective_org_id()))]

    @app.get("/api/v0/workspaces")
    def list_workspaces(
        include_archived: bool = Query(default=False),
    ) -> list[dict[str, Any]]:
        principal_id = effective_principal_id("local-developer")
        if include_archived:
            try:
                return [
                    _dump(item)
                    for item in platform.list_managed_workspaces(principal_id)
                ]
            except PermissionError as exc:
                raise HTTPException(status_code=403, detail=str(exc)) from exc
        return [
            _dump(item) for item in platform.list_principal_workspaces(principal_id)
        ]

    @app.post("/api/v0/workspaces", status_code=201)
    def create_workspace(request: WorkspaceCreateRequest) -> dict[str, Any]:
        try:
            workspace = platform.create_workspace(
                name=request.name,
                environment=request.environment,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _dump(workspace)

    @app.patch("/api/v0/workspaces/{workspace_id}")
    def update_workspace(
        workspace_id: str, patch: WorkspacePatchRequest
    ) -> dict[str, Any]:
        changes = patch.model_dump(exclude_unset=True)
        try:
            workspace = platform.update_workspace(workspace_id, **changes)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Workspace not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _dump(workspace)

    @app.get("/api/v0/roles")
    def list_roles() -> list[dict[str, Any]]:
        try:
            return [_dump(role) for role in platform.list_roles()]
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.post("/api/v0/roles", status_code=201)
    def create_role(request: RoleCreateRequest) -> dict[str, Any]:
        try:
            role = platform.create_role(
                name=request.name,
                permissions=tuple(request.permissions),
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _dump(role)

    @app.get("/api/v0/role-bindings")
    def list_role_bindings() -> list[dict[str, Any]]:
        try:
            return [_dump(item) for item in platform.list_role_bindings()]
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.post("/api/v0/role-bindings", status_code=201)
    def create_role_binding(
        request: RoleBindingCreateRequest,
    ) -> dict[str, Any]:
        try:
            binding = platform.create_role_binding(
                principal_id=request.principal_id,
                role_id=request.role_id,
                workspace_id=request.workspace_id,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Principal or role not found"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _dump(binding)

    @app.delete("/api/v0/role-bindings/{binding_id}", status_code=204)
    def delete_role_binding(binding_id: str) -> Response:
        try:
            platform.delete_role_binding(binding_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Role binding not found"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return Response(status_code=204)

    @app.get("/api/v0/users")
    def list_users() -> list[dict[str, Any]]:
        platform.authorize("local-developer", Permission.USERS_MANAGE)
        return [_dump(user) for user in platform.list_workspace_users()]

    @app.post("/api/v0/users", status_code=201)
    def create_workspace_user(
        request: WorkspaceUserCreateRequest,
    ) -> dict[str, Any]:
        try:
            user, principal, role, credential, token = platform.create_workspace_user(
                email=request.email,
                display_name=request.display_name,
                permissions=tuple(request.permissions or ()),
                role_id=request.role_id,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "user": _dump(user),
            "principal": _dump(principal),
            "role": _dump(role),
            "credential": _credential_view(credential),
            "access_token": token,
        }

    @app.get("/api/v0/user-invitations")
    def list_user_invitations() -> list[dict[str, Any]]:
        try:
            return [
                _invitation_view(invitation)
                for invitation in platform.list_user_invitations()
            ]
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.post("/api/v0/user-invitations", status_code=201)
    def create_user_invitation(
        request: UserInvitationCreateRequest,
    ) -> dict[str, Any]:
        try:
            user, principal, role, invitation, token = platform.create_user_invitation(
                email=request.email,
                display_name=request.display_name,
                permissions=tuple(request.permissions or ()),
                role_id=request.role_id,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Role not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "user": _dump(user),
            "principal": _dump(principal),
            "role": _dump(role),
            "invitation": _invitation_view(invitation),
            "invitation_token": token,
        }

    @app.post("/api/v0/user-invitations/{invitation_id}/resend")
    def resend_user_invitation(invitation_id: str) -> dict[str, Any]:
        try:
            invitation, token = platform.resend_user_invitation(invitation_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Invitation not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "invitation": _invitation_view(invitation),
            "invitation_token": token,
        }

    @app.delete("/api/v0/user-invitations/{invitation_id}", status_code=204)
    def revoke_user_invitation(invitation_id: str) -> Response:
        try:
            platform.revoke_user_invitation(invitation_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Invitation not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return Response(status_code=204)

    @app.post("/api/v0/users/{user_id}/suspend")
    def suspend_workspace_user(user_id: str) -> dict[str, Any]:
        try:
            user = platform.suspend_workspace_user(user_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="User not found") from exc
        return _dump(user)

    @app.post("/api/v0/users/{user_id}/reactivate")
    def reactivate_workspace_user(user_id: str) -> dict[str, Any]:
        try:
            user, credential, token = platform.reactivate_workspace_user(user_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="User not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "user": _dump(user),
            "credential": _credential_view(credential),
            "access_token": token,
        }

    @app.post("/api/v0/onboarding/organizations", status_code=201)
    def create_organization(
        request: Request,
        onboarding_request: OrganizationOnboardingRequest,
        onboarding_token: Optional[str] = Header(
            default=None, alias="X-Weaves-Onboarding-Token"
        ),
    ) -> dict[str, Any]:
        if os.environ.get("WEAVES_ALLOW_ORGANIZATION_ONBOARDING", "true").lower() not in {
            "1",
            "true",
            "yes",
            "on",
        }:
            raise HTTPException(
                status_code=404,
                detail="Organization onboarding is disabled",
            )
        expected_onboarding_token = os.environ.get(
            "WEAVES_ORGANIZATION_ONBOARDING_TOKEN", ""
        ).strip()
        if expected_onboarding_token and not hmac.compare_digest(
            onboarding_token or "", expected_onboarding_token
        ):
            raise HTTPException(status_code=404, detail="Organization not found")
        try:
            platform.check_onboarding_rate_limit(
                request.client.host if request.client else None
            )
            organization, workspace, user, principal, token = (
                platform.create_organization(
                    name=onboarding_request.name,
                    email=onboarding_request.owner_email,
                    display_name=onboarding_request.owner_display_name,
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RateLimitExceeded as exc:
            raise HTTPException(
                status_code=429,
                detail="organization onboarding is temporarily limited",
                headers={"Retry-After": str(exc.retry_after_seconds)},
            ) from exc
        return {
            "organization": _dump(organization),
            "workspace": _dump(workspace),
            "owner": _dump(user),
            "principal": _dump(principal),
            "access_token": token,
        }

    @app.post("/api/v0/auth/accept-invitation")
    def accept_user_invitation(
        request: UserInvitationAcceptanceRequest,
    ) -> dict[str, Any]:
        try:
            user, principal, session, token = platform.accept_user_invitation(
                request.invitation_token.get_secret_value(),
                request.password.get_secret_value(),
            )
            platform.resolve_principal_scope(principal.id)
        except PermissionError as exc:
            raise HTTPException(
                status_code=400,
                detail="Invitation is invalid, expired, or no longer has workspace access",
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "user": _dump(user),
            "principal": _dump(principal),
            "session_id": session.id,
            "access_token": token,
            "token_type": "bearer",
            "expires_at": session.expires_at,
        }

    @app.post("/api/v0/auth/login")
    def login_user(payload: UserLoginRequest, request: Request) -> dict[str, Any]:
        try:
            user, principal = platform.authenticate_user_password(
                payload.email,
                payload.password.get_secret_value(),
                org_id=payload.organization_id,
                client_address=(request.client.host if request.client else None),
            )
            platform.resolve_principal_scope(principal.id)
            session, token = platform.create_user_session(principal)
        except LoginThrottled as exc:
            raise HTTPException(
                status_code=429,
                detail="Too many sign-in attempts. Try again later.",
                headers={"Retry-After": str(exc.retry_after_seconds)},
            ) from exc
        except PermissionError as exc:
            raise HTTPException(
                status_code=401,
                detail="Invalid email, password, or account access",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        return {
            "session_id": session.id,
            "access_token": token,
            "token_type": "bearer",
            "expires_at": session.expires_at,
            "user": _dump(user),
            "principal": _dump(principal),
        }

    @app.put("/api/v0/auth/password", status_code=204)
    def set_authenticated_user_password(request: UserPasswordRequest) -> Response:
        try:
            platform.set_user_password(
                request.password.get_secret_value(),
                current_password=(
                    request.current_password.get_secret_value()
                    if request.current_password is not None
                    else None
                ),
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return Response(status_code=204)

    @app.get("/api/v0/auth/me")
    def get_authenticated_user() -> dict[str, Any]:
        principal = platform.principals.get(effective_principal_id("local-developer"))
        user = (
            platform.users.get_scoped(principal.user_id, principal.org_id)
            if principal.user_id is not None
            else None
        )
        return {"principal": _dump(principal), "user": _dump(user) if user else None}

    @app.post("/api/v0/auth/logout", status_code=204)
    def logout_user(authorization: Optional[str] = Header(default=None)) -> Response:
        scheme, separator, supplied_token = (authorization or "").partition(" ")
        if not separator or scheme.casefold() != "bearer":
            raise HTTPException(status_code=401, detail="A bearer session is required")
        try:
            platform.revoke_user_session(
                supplied_token,
                requested_by_principal_id=effective_principal_id("local-developer"),
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=400,
                detail="The supplied bearer credential is not an active user session",
            ) from exc
        return Response(status_code=204)

    @app.post("/api/v0/service-accounts", status_code=201)
    def create_service_account(request: ServiceAccountCreateRequest) -> dict[str, Any]:
        try:
            principal, role, credential, token = platform.create_service_account(
                name=request.name,
                permissions=tuple(request.permissions),
                expires_in_days=request.expires_in_days,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "principal": _dump(principal),
            "role": _dump(role),
            "credential": _credential_view(credential),
            "token": token,
        }

    @app.get("/api/v0/api-credentials")
    def list_api_credentials() -> list[dict[str, Any]]:
        platform.authorize_organization("local-developer", Permission.USERS_MANAGE)
        credentials = sorted(
            platform.api_credentials.list_scoped(effective_org_id()),
            key=lambda item: item.created_at,
            reverse=True,
        )
        return [_credential_view(item) for item in credentials]

    @app.delete("/api/v0/api-credentials/{credential_id}")
    def revoke_api_credential(credential_id: str) -> dict[str, Any]:
        try:
            credential = platform.revoke_api_credential(credential_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Credential not found") from exc
        return _credential_view(credential)

    @app.put("/api/v0/api-credentials/{credential_id}/rotate")
    def rotate_api_credential(credential_id: str) -> dict[str, Any]:
        try:
            credential, token = platform.rotate_api_credential(credential_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Credential not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"credential": _credential_view(credential), "token": token}

"""Model provider and profile configuration API routes."""

from decimal import Decimal
from typing import Any, Callable, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from weaves.product.api.common import ProviderCredentialRequest
from weaves.product.contracts.v1 import (
    ModelProfileStatus,
    ModelProviderStatus,
    ModelProviderType,
    Permission,
)
from weaves.product.runtime import LocalPlatformRuntime
from weaves.product.runtime.model_gateway import ModelGatewayError
from weaves.product.runtime.request_identity import effective_org_id
from weaves.product.runtime.secrets import SecretStoreUnavailable


class ModelProviderCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    provider_type: ModelProviderType
    display_name: str = Field(min_length=2, max_length=160)
    api_key: SecretStr = Field(min_length=1, max_length=4096)
    base_url: Optional[str] = Field(default=None, min_length=8, max_length=2048)
    initial_model: Optional[str] = Field(default=None, min_length=1, max_length=160)


class ModelProfilePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    max_output_tokens: Optional[int] = Field(default=None, ge=1, le=32768)
    cost_budget_usd: Optional[Decimal] = Field(
        default=None, gt=0, le=100000, max_digits=18, decimal_places=9
    )
    input_cost_per_million_tokens_usd: Optional[Decimal] = Field(
        default=None, ge=0, le=100000, max_digits=18, decimal_places=9
    )
    output_cost_per_million_tokens_usd: Optional[Decimal] = Field(
        default=None, ge=0, le=100000, max_digits=18, decimal_places=9
    )
    status: Optional[ModelProfileStatus] = None


def _model_catalog_error(exc: ModelGatewayError) -> HTTPException:
    if exc.code in {"model.provider_disabled", "model.catalog_unsupported"}:
        return HTTPException(status_code=409, detail=exc.message)
    return HTTPException(status_code=502, detail=exc.message)


def _provider_view(
    provider: Any, dump: Callable[[BaseModel], dict[str, Any]]
) -> dict[str, Any]:
    result = dump(provider)
    result.pop("auth_ref", None)
    result["has_credentials"] = bool(provider.auth_ref)
    return result


def register_model_routes(
    app: FastAPI,
    platform: LocalPlatformRuntime,
    dump: Callable[[BaseModel], dict[str, Any]],
) -> None:
    """Register model profile and provider configuration endpoints."""
    _dump = dump

    def provider_view(provider: Any) -> dict[str, Any]:
        return _provider_view(provider, _dump)

    @app.get("/api/v0/model-profiles")
    def list_model_profiles() -> list[dict[str, Any]]:
        platform.authorize_organization("local-developer", Permission.MODELS_MANAGE)
        profiles = sorted(
            platform.model_profiles.list_scoped(effective_org_id()),
            key=lambda item: item.id != platform.default_model_profile_id,
        )
        return [_dump(item) for item in profiles]

    @app.patch("/api/v0/model-profiles/{profile_id}")
    def update_model_profile(
        profile_id: str, patch: ModelProfilePatchRequest
    ) -> dict[str, Any]:
        changes = patch.model_dump(exclude_unset=True)
        if not changes:
            raise HTTPException(status_code=400, detail="No changes supplied")
        try:
            profile = platform.update_model_profile(profile_id, **changes)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Model profile not found"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _dump(profile)

    @app.get("/api/v0/model-providers")
    def list_model_providers() -> list[dict[str, Any]]:
        platform.authorize_organization("local-developer", Permission.MODELS_MANAGE)
        return [
            provider_view(item)
            for item in platform.providers.list_scoped(effective_org_id())
        ]

    @app.post("/api/v0/model-providers", status_code=201)
    def create_model_provider(request: ModelProviderCreateRequest) -> dict[str, Any]:
        try:
            provider = platform.create_model_provider(
                provider_type=request.provider_type,
                display_name=request.display_name,
                api_key=request.api_key.get_secret_value(),
                base_url=request.base_url,
                initial_model=request.initial_model,
            )
        except SecretStoreUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return provider_view(provider)

    @app.post("/api/v0/model-providers/{provider_id}/refresh-models")
    def refresh_provider_models(provider_id: str) -> dict[str, Any]:
        platform.authorize_organization("local-developer", Permission.MODELS_MANAGE)
        try:
            profiles = platform.refresh_provider_model_catalog(provider_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Model provider not found"
            ) from exc
        except ModelGatewayError as exc:
            raise _model_catalog_error(exc) from exc
        return {"models": [_dump(item) for item in profiles]}

    @app.put("/api/v0/model-providers/{provider_id}/credential")
    def rotate_provider_credential(
        provider_id: str, request: ProviderCredentialRequest
    ) -> dict[str, Any]:
        try:
            provider = platform.rotate_model_provider_credential(
                provider_id, request.api_key.get_secret_value()
            )
        except SecretStoreUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Model provider not found"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return provider_view(provider)

    @app.post("/api/v0/models/refresh")
    def refresh_models(
        provider_id: Optional[str] = Query(default=None, min_length=1, max_length=128),
    ) -> list[dict[str, Any]]:
        platform.authorize_organization("local-developer", Permission.MODELS_MANAGE)
        if provider_id is None:
            configured_providers = [
                item
                for item in platform.providers.list_scoped(effective_org_id())
                if item.status is ModelProviderStatus.ACTIVE
                and item.provider_type is not ModelProviderType.LOCAL
            ]
            if len(configured_providers) != 1:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "provider_id is required when there is not exactly one "
                        "active external provider"
                    ),
                )
            provider_id = configured_providers[0].id
        try:
            profiles = platform.refresh_provider_model_catalog(provider_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Model provider not found"
            ) from exc
        except ModelGatewayError as exc:
            raise _model_catalog_error(exc) from exc
        return [_dump(item) for item in profiles]

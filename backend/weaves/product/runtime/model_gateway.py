"""Model gateway ports, routing, and OpenAI-compatible HTTP adapters."""

import os
import re
from typing import Mapping, Protocol

import httpx

from weaves.product.contracts.v1 import (
    ModelProfileBinding,
    ModelProfileStatus,
    ModelProvider,
    ModelProviderStatus,
    ModelProviderType,
)
from weaves.product.contracts.v1.model_execution import (
    ModelRequest,
    ModelResponse,
    ModelUsage,
)


class ModelGatewayError(RuntimeError):
    """Safe model failure details suitable for a run error summary."""

    def __init__(self, code: str, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class SecretResolver(Protocol):
    def resolve(self, auth_ref: str) -> str: ...


class EnvironmentSecretResolver:
    """Resolve the one explicitly supported local-development secret reference."""

    def resolve(self, auth_ref: str) -> str:
        if auth_ref != "env:MODEL_API_KEY":
            raise KeyError("unsupported environment secret reference")
        return os.environ.get("MODEL_API_KEY", "")


class ModelAdapter(Protocol):
    def complete(
        self, request: ModelRequest, binding: ModelProfileBinding
    ) -> ModelResponse: ...


class ModelGateway:
    """Routes a provider-neutral request through the selected provider adapter."""

    def __init__(self, adapters: Mapping[ModelProviderType, ModelAdapter]) -> None:
        self._adapters = dict(adapters)

    def complete(
        self, request: ModelRequest, binding: ModelProfileBinding
    ) -> ModelResponse:
        provider = binding.provider
        profile = binding.profile
        if profile.model not in provider.allowed_models:
            raise ModelGatewayError(
                "model.not_allowed", "Model is not allowed by provider"
            )
        if (
            profile.status is not ModelProfileStatus.ACTIVE
            or provider.status is not ModelProviderStatus.ACTIVE
        ):
            raise ModelGatewayError(
                "model.disabled", "Model profile or provider is disabled"
            )
        try:
            adapter = self._adapters[provider.provider_type]
        except KeyError as exc:
            raise ModelGatewayError(
                "model.adapter_missing",
                "No adapter is registered for the selected provider",
            ) from exc
        response = adapter.complete(request, binding)
        if response.provider_id != provider.id:
            raise ModelGatewayError(
                "model.provider_mismatch",
                "Model adapter response did not match the selected provider",
            )
        return response


class OpenAICompatibleAdapter:
    """Chat-completions adapter that resolves credentials only at request time."""

    def __init__(
        self,
        secret_resolver: SecretResolver,
        client: httpx.Client,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._secret_resolver = secret_resolver
        self._client = client
        self._timeout_seconds = timeout_seconds

    def list_models(self, provider: ModelProvider) -> tuple[dict[str, str], ...]:
        """Return models visible to a provider credential, without prompt usage."""
        if provider.provider_type not in {
            ModelProviderType.OPENAI,
            ModelProviderType.OPENAI_COMPATIBLE,
        }:
            raise ModelGatewayError(
                "model.provider_unsupported",
                "Provider is not supported by this adapter",
            )
        if not provider.auth_ref:
            raise ModelGatewayError(
                "model.auth_ref_missing",
                "Provider has no configured credential reference",
            )
        base_url = provider.base_url or "https://api.openai.com/v1"
        secret = self._resolve_secret(provider.auth_ref)
        try:
            response = self._client.get(
                f"{base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {secret}"},
                timeout=self._timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise ModelGatewayError(
                "model.timeout", "Model provider request timed out", retryable=True
            ) from exc
        except httpx.HTTPError as exc:
            raise ModelGatewayError(
                "model.transport_error", "Model provider request failed", retryable=True
            ) from exc
        if response.is_error:
            self._raise_upstream_error(response)
        try:
            data = response.json()["data"]
            models = tuple(
                {"id": item["id"], "owned_by": item.get("owned_by", "unknown")}
                for item in data
                if isinstance(item, dict)
                and isinstance(item.get("id"), str)
                and item["id"]
            )
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise ModelGatewayError(
                "model.invalid_response", "Model provider returned an invalid response"
            ) from exc
        return tuple(sorted(models, key=lambda model: model["id"]))

    def complete(
        self, request: ModelRequest, binding: ModelProfileBinding
    ) -> ModelResponse:
        provider = binding.provider
        if provider.provider_type not in {
            ModelProviderType.OPENAI,
            ModelProviderType.OPENAI_COMPATIBLE,
        }:
            raise ModelGatewayError(
                "model.provider_unsupported",
                "Provider is not supported by this adapter",
            )
        if not provider.auth_ref:
            raise ModelGatewayError(
                "model.auth_ref_missing",
                "Provider has no configured credential reference",
            )
        base_url = provider.base_url or "https://api.openai.com/v1"
        secret = self._resolve_secret(provider.auth_ref)

        body = {
            "model": binding.profile.model,
            "messages": [
                {"role": message.role.value, "content": message.content}
                for message in request.messages
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
        }
        try:
            response = self._client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {secret}"},
                timeout=self._timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise ModelGatewayError(
                "model.timeout", "Model provider request timed out", retryable=True
            ) from exc
        except httpx.HTTPError as exc:
            raise ModelGatewayError(
                "model.transport_error", "Model provider request failed", retryable=True
            ) from exc

        if response.is_error:
            self._raise_upstream_error(response)
        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
            usage = payload.get("usage", {})
            input_tokens = int(usage.get("prompt_tokens", 0))
            output_tokens = int(usage.get("completion_tokens", 0))
            model_id = payload.get("model", binding.profile.model)
            finish_reason = payload["choices"][0].get("finish_reason")
        except (AttributeError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise ModelGatewayError(
                "model.invalid_response", "Model provider returned an invalid response"
            ) from exc
        if not isinstance(content, str) or not content:
            raise ModelGatewayError(
                "model.empty_response", "Model provider returned no text content"
            )
        if not isinstance(model_id, str) or not 1 <= len(model_id.strip()) <= 128:
            model_id = binding.profile.model
        else:
            model_id = model_id.strip()
        request_id = response.headers.get("x-request-id")
        if request_id is not None and not 1 <= len(request_id.strip()) <= 128:
            request_id = None
        elif request_id is not None:
            request_id = request_id.strip()
        return ModelResponse(
            provider_id=provider.id,
            model_id=model_id,
            content=content,
            usage=ModelUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
            ),
            finish_reason=finish_reason,
            upstream_request_id=request_id,
        )

    def _resolve_secret(self, auth_ref: str) -> str:
        try:
            secret = self._secret_resolver.resolve(auth_ref)
        except Exception as exc:
            raise ModelGatewayError(
                "model.credential_unavailable",
                "Provider credential could not be resolved",
            ) from exc
        if not secret:
            raise ModelGatewayError(
                "model.credential_unavailable",
                "Provider credential could not be resolved",
            )
        return secret

    @staticmethod
    def _raise_upstream_error(response: httpx.Response) -> None:
        """Expose only a validated provider error code, never its raw message."""
        code = None
        try:
            error = response.json().get("error", {})
            candidate = error.get("code") or error.get("type")
            if isinstance(candidate, str) and re.fullmatch(
                r"[A-Za-z0-9_.-]{1,80}", candidate
            ):
                code = candidate
        except (AttributeError, ValueError):
            pass
        suffix = f" ({code})" if code else ""
        retryable = response.status_code == 429 or response.status_code >= 500
        raise ModelGatewayError(
            "model.upstream_error",
            f"Model provider returned HTTP {response.status_code}{suffix}",
            retryable=retryable,
        )

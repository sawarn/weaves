import json
from datetime import datetime, timezone

import httpx
import pytest
from pydantic import ValidationError

from weaves.product.contracts.v1 import (
    ModelMessageRole,
    ModelProfile,
    ModelProfileBinding,
    ModelProfileStatus,
    ModelProvider,
    ModelProviderStatus,
    ModelProviderType,
    ModelRequest,
    RunStatus,
)
from weaves.product.contracts.v1.model_execution import ModelUsage
from weaves.product.runtime import LocalPlatformRuntime
from weaves.product.runtime.model_gateway import (
    ModelGateway,
    ModelGatewayError,
    OpenAICompatibleAdapter,
)


def binding(**provider_overrides):
    provider = ModelProvider(
        id="provider-a",
        org_id="org-a",
        provider_type=ModelProviderType.OPENAI_COMPATIBLE,
        display_name="Compatible test provider",
        allowed_models=["model-a"],
        auth_ref="vault://provider-a",
        base_url="https://models.example/v1",
        status=ModelProviderStatus.ACTIVE,
        **provider_overrides,
    )
    profile = ModelProfile(
        id="profile-a",
        org_id="org-a",
        provider_id="provider-a",
        model="model-a",
        display_name="Test model",
        status=ModelProfileStatus.ACTIVE,
        created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    return ModelProfileBinding(provider=provider, profile=profile)


def request():
    return ModelRequest(
        messages=(
            {"role": ModelMessageRole.SYSTEM, "content": "Answer concisely."},
            {"role": ModelMessageRole.USER, "content": "Summarize the context."},
        ),
        request_id="run-a",
    )


class TestSecretResolver:
    def resolve(self, auth_ref: str) -> str:
        assert auth_ref == "vault://provider-a"
        return "test-secret"


def test_openai_compatible_adapter_sends_profile_and_returns_sanitized_response():
    sent = {}

    def handler(http_request):
        sent["url"] = str(http_request.url)
        sent["headers"] = dict(http_request.headers)
        sent["body"] = json.loads(http_request.content)
        return httpx.Response(
            200,
            headers={"x-request-id": "upstream-request-a"},
            json={
                "model": "model-a-2026-01",
                "choices": [
                    {
                        "message": {"content": "A concise response."},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 5},
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OpenAICompatibleAdapter(TestSecretResolver(), client)
    result = adapter.complete(request(), binding())

    assert sent["url"] == "https://models.example/v1/chat/completions"
    assert sent["headers"]["authorization"] == "Bearer test-secret"
    assert sent["body"]["model"] == "model-a"
    assert result.content == "A concise response."
    assert result.usage.total_tokens == 17
    assert result.model_id == "model-a-2026-01"
    assert "test-secret" not in result.model_dump_json()
    client.close()


def test_gateway_rejects_disabled_or_unapproved_model_profiles():
    compatible = binding()
    gateway = ModelGateway({})
    with pytest.raises(ModelGatewayError, match="No adapter"):
        gateway.complete(request(), compatible)
    with pytest.raises(ValidationError, match="must be allowed"):
        unapproved_provider = ModelProvider(
            id="provider-a",
            org_id="org-a",
            provider_type=ModelProviderType.OPENAI_COMPATIBLE,
            display_name="Compatible test provider",
            allowed_models=["different-model"],
            auth_ref="vault://provider-a",
            base_url="https://models.example/v1",
            status=ModelProviderStatus.ACTIVE,
        )
        ModelProfileBinding(provider=unapproved_provider, profile=compatible.profile)


def test_model_usage_totals_are_consistent():
    with pytest.raises(ValidationError, match="total_tokens"):
        ModelUsage(input_tokens=3, output_tokens=2, total_tokens=4)


def test_adapter_errors_do_not_expose_provider_response_bodies_or_secrets():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(401, text="test-secret must not be copied")
        )
    )
    adapter = OpenAICompatibleAdapter(TestSecretResolver(), client)

    with pytest.raises(ModelGatewayError) as error:
        adapter.complete(request(), binding())

    assert "HTTP 401" in str(error.value)
    assert "test-secret" not in str(error.value)
    client.close()


def test_gateway_failure_is_recorded_on_run_and_agent_run():
    runtime = LocalPlatformRuntime()
    runtime.model_gateway = ModelGateway({})

    with pytest.raises(ModelGatewayError):
        runtime.run_agent("Summarize the handbook")

    run = runtime.runs.list()[0]
    agent_run = runtime.agent_runs.list()[0]
    assert run.status is RunStatus.FAILED
    assert agent_run.status is RunStatus.FAILED
    assert run.error is not None
    assert run.error.code == "model.adapter_missing"
    assert runtime.audit_events.list()[0].action == "agent.run.failed"

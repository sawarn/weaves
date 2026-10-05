"""Local, in-memory runtime for exercising the product contracts."""

from weaves.product.runtime.model_gateway import (
    EnvironmentSecretResolver,
    ModelGateway,
    ModelGatewayError,
    OpenAICompatibleAdapter,
    SecretResolver,
)
from weaves.product.runtime.plugin_gateway import (
    CapabilityResult,
    PluginGateway,
    PluginGatewayError,
)
from weaves.product.runtime.service import LocalPlatformRuntime, RuntimeResult

__all__ = [
    "LocalPlatformRuntime",
    "CapabilityResult",
    "EnvironmentSecretResolver",
    "ModelGateway",
    "ModelGatewayError",
    "OpenAICompatibleAdapter",
    "PluginGateway",
    "PluginGatewayError",
    "RuntimeResult",
    "SecretResolver",
]

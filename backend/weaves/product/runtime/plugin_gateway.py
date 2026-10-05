"""Governed dispatch for registered context-read capabilities."""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Mapping, Protocol

from jsonschema import Draft202012Validator
from pydantic import ValidationError

from weaves.product.contracts.v1 import (
    AgentVersion,
    CapabilityKind,
    InvocationStatus,
    PluginDescriptorStatus,
    PluginInstallationBinding,
    PluginInstallationStatus,
)
from weaves.product.contracts.v1.base import OpaqueId
from weaves.product.contracts.v1.json_data import (
    freeze_json_value,
    reject_credential_fields,
    thaw_json_value,
)
from weaves.product.runtime.repositories import Repository


class CapabilityProvider(Protocol):
    def invoke(self, capability_id: str, payload: dict[str, Any]) -> dict[str, Any]: ...


class PluginGatewayError(RuntimeError):
    """Safe dispatch errors that never expose connector payloads or credentials."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class CapabilityResult:
    output: dict[str, Any]
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    status: InvocationStatus = InvocationStatus.SUCCEEDED


class PluginGateway:
    """Resolve, authorize, schema-check, and dispatch a capability invocation."""

    def __init__(
        self,
        descriptors: Repository[Any],
        installations: Repository[Any],
        providers: Mapping[str, CapabilityProvider],
    ) -> None:
        self._descriptors = descriptors
        self._installations = installations
        self._providers = dict(providers)

    def invoke(
        self,
        *,
        org_id: OpaqueId,
        workspace_id: OpaqueId,
        installation_id: OpaqueId,
        agent_version: AgentVersion,
        capability_id: str,
        payload: dict[str, Any],
    ) -> CapabilityResult:
        if agent_version.org_id != org_id or agent_version.workspace_id != workspace_id:
            raise PluginGatewayError(
                "plugin.scope_mismatch", "Agent is outside the requested scope"
            )
        if capability_id not in agent_version.allowed_capability_ids:
            raise PluginGatewayError(
                "plugin.capability_denied",
                "Agent is not allowed to use this capability",
            )
        try:
            installation = self._installations.get_scoped(
                installation_id, org_id, workspace_id
            )
        except KeyError as exc:
            raise PluginGatewayError(
                "plugin.installation_not_found", "Plugin installation was not found"
            ) from exc
        if installation.status is not PluginInstallationStatus.ACTIVE:
            raise PluginGatewayError(
                "plugin.installation_disabled", "Plugin installation is disabled"
            )
        if capability_id not in installation.enabled_capability_ids:
            raise PluginGatewayError(
                "plugin.capability_disabled",
                "Capability is not enabled for this installation",
            )
        try:
            descriptor = self._descriptors.get(installation.plugin_id)
        except KeyError as exc:
            raise PluginGatewayError(
                "plugin.descriptor_not_found", "Plugin descriptor was not found"
            ) from exc
        if descriptor.status is not PluginDescriptorStatus.ACTIVE:
            raise PluginGatewayError("plugin.descriptor_disabled", "Plugin is disabled")
        try:
            binding = PluginInstallationBinding(
                descriptor=descriptor, installation=installation
            )
        except ValidationError as exc:
            raise PluginGatewayError(
                "plugin.binding_invalid", "Plugin installation is invalid"
            ) from exc
        capability = next(
            (
                item
                for item in binding.descriptor.capability_manifest
                if item.capability_id == capability_id
            ),
            None,
        )
        if capability is None:
            raise PluginGatewayError(
                "plugin.capability_unknown", "Capability is not registered"
            )
        if capability.kind is not CapabilityKind.CONTEXT_READ:
            raise PluginGatewayError(
                "plugin.action_not_supported",
                "Only context-read capabilities are enabled in v0",
            )
        _validate_payload(capability.input_schema, payload, "input")
        try:
            provider = self._providers[descriptor.plugin_id]
        except KeyError as exc:
            raise PluginGatewayError(
                "plugin.provider_missing", "No provider is registered for this plugin"
            ) from exc

        started_at = datetime.now(timezone.utc)
        started = perf_counter()
        try:
            output = provider.invoke(capability_id, payload)
        except Exception as exc:
            raise PluginGatewayError(
                "plugin.provider_error", "Capability provider failed"
            ) from exc
        finished_at = datetime.now(timezone.utc)
        if not isinstance(output, dict):
            raise PluginGatewayError(
                "plugin.output_invalid", "Capability returned an invalid output"
            )
        try:
            _validate_payload(capability.output_schema, output, "output")
        except PluginGatewayError as exc:
            raise PluginGatewayError(
                "plugin.output_invalid", "Capability returned an invalid output"
            ) from exc
        return CapabilityResult(
            output=thaw_json_value(freeze_json_value(output, "output")),
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=max(0, int((perf_counter() - started) * 1000)),
        )


def _validate_payload(
    schema: dict[str, Any], payload: dict[str, Any], label: str
) -> None:
    try:
        reject_credential_fields(payload, label)
        freeze_json_value(payload, label)
        limit = 16_384 if label == "input" else 65_536
        if len(json.dumps(payload, allow_nan=False)) > limit:
            raise ValueError(f"{label} exceeds size limit")
        Draft202012Validator(schema).validate(payload)
    except Exception as exc:
        raise PluginGatewayError(
            f"plugin.{label}_invalid", f"Capability {label} is invalid"
        ) from exc

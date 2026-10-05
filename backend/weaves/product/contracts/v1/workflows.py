from typing import Any, Optional

from pydantic import (
    Field,
    ValidationInfo,
    field_serializer,
    field_validator,
    model_validator,
)
from typing_extensions import Annotated

from weaves.product.contracts.v1.base import (
    DisplayName,
    ImmutableWorkspaceVersionContract,
    MutableWorkspaceScopedContract,
    OpaqueId,
    ProductContract,
    StrEnum,
)
from weaves.product.contracts.v1.json_data import (
    freeze_json_value,
    reject_credential_fields,
    thaw_json_value,
    validate_json_schema,
)
from weaves.product.contracts.v1.plugins import Identifier, JsonObject

PositiveVersion = Annotated[int, Field(ge=1)]


class WorkflowStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class WorkflowDefinition(MutableWorkspaceScopedContract):
    workflow_id: OpaqueId
    name: DisplayName
    description: str = Field(default="", max_length=2000)
    current_version_id: Optional[OpaqueId] = None
    status: WorkflowStatus

    @model_validator(mode="after")
    def active_workflow_has_published_version(
        self: "WorkflowDefinition",
    ) -> "WorkflowDefinition":
        if self.status is WorkflowStatus.ACTIVE and self.current_version_id is None:
            raise ValueError("active workflows require a current published version")
        return self


class WorkflowVersion(ImmutableWorkspaceVersionContract):
    workflow_version_id: OpaqueId
    workflow_id: OpaqueId
    version: PositiveVersion
    handler_key: Identifier
    agent_version_ids: tuple[OpaqueId, ...] = Field(min_length=1, max_length=50)
    required_capability_ids: tuple[Identifier, ...] = Field(
        default_factory=tuple, max_length=200
    )
    input_schema: JsonObject
    output_schema: JsonObject
    configuration: JsonObject = Field(default_factory=dict)

    @field_validator("input_schema", "output_schema")
    @classmethod
    def schemas_are_valid_and_frozen(
        cls: type["WorkflowVersion"], value: JsonObject, info: ValidationInfo
    ) -> Any:
        return validate_json_schema(value, info.field_name or "schema")

    @field_validator("configuration")
    @classmethod
    def configuration_is_json_and_frozen(
        cls: type["WorkflowVersion"], value: JsonObject
    ) -> Any:
        reject_credential_fields(value, "configuration")
        return freeze_json_value(value, "configuration")

    @field_serializer("input_schema", "output_schema", "configuration")
    def serialize_json_values(self: "WorkflowVersion", value: Any) -> Any:
        return thaw_json_value(value)

    @model_validator(mode="after")
    def referenced_ids_are_unique(self: "WorkflowVersion") -> "WorkflowVersion":
        if len(self.agent_version_ids) != len(set(self.agent_version_ids)):
            raise ValueError("agent_version_ids must be unique")
        if len(self.required_capability_ids) != len(set(self.required_capability_ids)):
            raise ValueError("required_capability_ids must be unique")
        return self


class WorkflowBundle(ProductContract):
    definition: WorkflowDefinition
    version: WorkflowVersion

    @model_validator(mode="after")
    def version_matches_definition(self: "WorkflowBundle") -> "WorkflowBundle":
        if self.version.workflow_id != self.definition.workflow_id:
            raise ValueError("workflow version must reference the supplied definition")
        if self.version.org_id != self.definition.org_id:
            raise ValueError("workflow definition and version must share org_id")
        if self.version.workspace_id != self.definition.workspace_id:
            raise ValueError("workflow definition and version must share workspace_id")
        if self.definition.current_version_id != self.version.workflow_version_id:
            raise ValueError("workflow definition current version pointer must match")
        return self


__all__ = ["WorkflowBundle", "WorkflowDefinition", "WorkflowStatus", "WorkflowVersion"]

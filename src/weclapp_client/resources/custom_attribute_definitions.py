"""
The ``/customAttributeDefinition`` resource (read-only in this client).
"""

from typing import ClassVar

from weclapp_client._http import HttpTransport
from weclapp_client.exceptions import CustomAttributeDefinitionError
from weclapp_client.models.custom_attribute import CustomAttributeDefinition, CustomAttributeType
from weclapp_client.resources.base import ReadResource

# property names according to the weclapp OpenAPI specification (v2)
_PROPERTIES = frozenset(
    {
        "active",
        "attributeDescription",
        "attributeEntityType",
        "attributeKey",
        "attributeLabels",
        "attributeType",
        "conditions",
        "createdDate",
        "defaultBooleanValue",
        "defaultDateValue",
        "defaultNumberValue",
        "defaultStringValue",
        "entities",
        "groupName",
        "id",
        "inheritOnCopy",
        "label",
        "lastModifiedDate",
        "legacyEntities",
        "mandatory",
        "permissions",
        "publicPageTypes",
        "readOnly",
        "selectableValues",
        "showAttributeEntityType",
        "showInOverview",
        "showOnCreationDialog",
        "systemCustomAttribute",
        "version",
    }
)
_NOT_FILTERABLE = frozenset(
    {
        "attributeLabels",
        "conditions",
        "legacyEntities",
        "permissions",
        "publicPageTypes",
        "selectableValues",
        "showAttributeEntityType",
    }
)


class CustomAttributeDefinitionsResource(ReadResource[CustomAttributeDefinition]):
    """Definitions of custom attributes. They rarely change, so :meth:`get_by_key` caches them."""

    path = "customAttributeDefinition"
    entity_model = CustomAttributeDefinition
    known_properties: ClassVar[frozenset[str]] = _PROPERTIES
    filterable_properties: ClassVar[frozenset[str]] = _PROPERTIES - _NOT_FILTERABLE

    def __init__(self, transport: HttpTransport) -> None:
        super().__init__(transport)
        self._by_key: dict[str, CustomAttributeDefinition] | None = None

    def get_by_key(
        self,
        attribute_key: str,
        *,
        expected_type: CustomAttributeType | None = None,
        refresh: bool = False,
    ) -> CustomAttributeDefinition:
        """
        Returns the definition with the given ``attributeKey``, e.g. ``"personalnummer"``.

        All definitions are loaded once and cached; pass ``refresh=True`` to reload them.

        :param expected_type: if given, the definition must have this type
        :raises CustomAttributeDefinitionError: if there is no such definition or its type does not match
        """
        if refresh or self._by_key is None:
            self._by_key = {
                definition.attribute_key: definition for definition in self.iterate() if definition.attribute_key
            }
        definition = self._by_key.get(attribute_key)
        if definition is None:
            raise CustomAttributeDefinitionError(f"There is no custom attribute with the key {attribute_key!r}")
        if expected_type is not None and definition.attribute_type != expected_type:
            raise CustomAttributeDefinitionError(
                f"The custom attribute {attribute_key!r} has the type {definition.attribute_type}, "
                f"expected {expected_type}"
            )
        return definition

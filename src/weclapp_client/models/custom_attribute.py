"""
Custom attributes: user-defined fields that weclapp tenants can add to entities such as users.
"""

from enum import StrEnum
from typing import Self

from pydantic import Field

from weclapp_client.models.base import WeclappEntity, WeclappModel


class CustomAttributeType(StrEnum):
    """Type of a custom attribute definition (``attributeType``)."""

    BOOLEAN = "BOOLEAN"
    DATE = "DATE"
    DECIMAL = "DECIMAL"
    ENTITY = "ENTITY"
    INTEGER = "INTEGER"
    LARGE_TEXT = "LARGE_TEXT"
    LIST = "LIST"
    MULTISELECT_LIST = "MULTISELECT_LIST"
    REFERENCE = "REFERENCE"
    STRING = "STRING"
    URL = "URL"


class CustomAttribute(WeclappModel):
    """
    The value of one custom attribute of an entity.

    Only string values are modelled so far; values of other types are ignored when reading.
    In partial updates weclapp merges custom attributes per attribute: attributes that are not sent keep their value.
    """

    attribute_definition_id: str
    string_value: str | None = None

    @classmethod
    def of_string(cls, definition_id: str, value: str | None) -> Self:
        """Creates the value of a custom attribute of type ``STRING``; ``None`` clears the value."""
        return cls(attribute_definition_id=definition_id, string_value=value)


class CustomAttributeDefinition(WeclappEntity):
    """The definition of a custom attribute (``/customAttributeDefinition``)."""

    attribute_key: str | None = None
    """technical key of the attribute, e.g. ``personalnummer``"""
    attribute_type: CustomAttributeType | str | None = Field(default=None, union_mode="left_to_right")
    label: str | None = None
    active: bool | None = None
    attribute_entity_type: str | None = None
    entities: list[str] = Field(default_factory=list)

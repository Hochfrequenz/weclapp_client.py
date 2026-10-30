"""
Custom attributes: user-defined fields that weclapp tenants can add to entities such as users.
"""

from decimal import Decimal
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

    Text, number and list values are modelled; values of other types (e.g. boolean or date) are ignored when reading.
    Create the values with :meth:`of_string`, :meth:`of_number` or :meth:`of_selection`: they set only the field of
    their type, so a partial update does not clear the others.
    In partial updates weclapp merges custom attributes per attribute: attributes that are not sent keep their value.
    """

    attribute_definition_id: str
    string_value: str | None = None
    number_value: Decimal | None = None
    """for the types ``DECIMAL`` and ``INTEGER``; weclapp transfers it as a string, e.g. ``"59"``"""
    selected_value_id: str | None = None
    """for the type ``LIST``: the id of the selected value"""

    @classmethod
    def of_string(cls, definition_id: str, value: str | None) -> Self:
        """Creates the value of a custom attribute of type ``STRING``; ``None`` clears the value."""
        return cls(attribute_definition_id=definition_id, string_value=value)

    @classmethod
    def of_number(cls, definition_id: str, value: Decimal | int | str | None) -> Self:
        """Creates the value of a custom attribute of type ``DECIMAL`` or ``INTEGER``; ``None`` clears the value."""
        return cls(attribute_definition_id=definition_id, number_value=None if value is None else Decimal(value))

    @classmethod
    def of_selection(cls, definition_id: str, value_id: str | None) -> Self:
        """Creates the value of a custom attribute of type ``LIST`` from the id of the selected value."""
        return cls(attribute_definition_id=definition_id, selected_value_id=value_id)


class CustomAttributeListValue(WeclappModel):
    """A value to choose from in a custom attribute of type ``LIST`` (``selectableValues`` of the definition)."""

    id: str
    """the id to pass to :meth:`CustomAttribute.of_selection`"""
    value: str | None = None
    """the label shown in weclapp, e.g. ``Bayern``"""
    active: bool | None = None
    default_value: bool | None = None
    position_number: int | None = None


class CustomAttributeDefinition(WeclappEntity):
    """The definition of a custom attribute (``/customAttributeDefinition``)."""

    attribute_key: str | None = None
    """technical key of the attribute, e.g. ``personalnummer``"""
    attribute_type: CustomAttributeType | str | None = Field(default=None, union_mode="left_to_right")
    label: str | None = None
    active: bool | None = None
    attribute_entity_type: str | None = None
    """for attributes of type ``ENTITY``: the type of the referenced entity (e.g. ``party``); empty otherwise"""
    entities: list[str] = Field(default_factory=list)
    """the entities the attribute belongs to, e.g. ``["user"]``"""
    selectable_values: list[CustomAttributeListValue] = Field(default_factory=list)
    """for attributes of type ``LIST``: the values to choose from; weclapp rejects the id of any other value"""

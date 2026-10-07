"""
Filters for list queries.

A filter becomes a query parameter of the form ``<property>-<operator>=<value>``, e.g. ``email-eq=a@example.com``.
Property names are the camelCase names used by weclapp. The resources check them before sending a request, because
weclapp silently ignores filters on unknown properties, which would turn a lookup into a query for all entities.
"""

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum

from weclapp_client._converters import date_to_ms, datetime_to_ms
from weclapp_client.exceptions import InvalidQueryError

FilterValue = str | int | float | bool | date | datetime | Enum
"""values that can be used in filters; dates and datetimes are converted to weclapp timestamps"""

_CUSTOM_ATTRIBUTE_ID_PATTERN = re.compile(r"^[0-9A-Za-z_]+$")


def _json_value(value: FilterValue) -> str | int | float | bool:
    if isinstance(value, Enum):
        return _json_value(value.value)
    if isinstance(value, datetime):
        return datetime_to_ms(value)
    if isinstance(value, date):
        return date_to_ms(value)
    return value


def _param_value(value: FilterValue) -> str:
    converted = _json_value(value)
    if isinstance(converted, bool):
        return "true" if converted else "false"
    return str(converted)


@dataclass(frozen=True)
class Filter:
    """A filter condition; create it with one of the class methods, e.g. ``Filter.eq("email", "a@example.com")``."""

    property_name: str
    """camelCase property name as used by weclapp, e.g. ``userId``"""
    operator: str
    value: str = ""
    is_custom_attribute: bool = False
    """``True`` for filters on custom attributes, whose property name is ``customAttribute<definition id>``"""

    def to_query_param(self) -> tuple[str, str]:
        """Returns name and value of the query parameter."""
        return f"{self.property_name}-{self.operator}", self.value

    @classmethod
    def _create(cls, property_name: str, operator: str, value: str = "") -> "Filter":
        if not property_name:
            raise InvalidQueryError("The property name of a filter must not be empty")
        return cls(property_name=property_name, operator=operator, value=value)

    @classmethod
    def eq(cls, property_name: str, value: FilterValue) -> "Filter":
        """property equals value"""
        return cls._create(property_name, "eq", _param_value(value))

    @classmethod
    def ne(cls, property_name: str, value: FilterValue) -> "Filter":
        """property does not equal value"""
        return cls._create(property_name, "ne", _param_value(value))

    @classmethod
    def lt(cls, property_name: str, value: FilterValue) -> "Filter":
        """property is less than value"""
        return cls._create(property_name, "lt", _param_value(value))

    @classmethod
    def le(cls, property_name: str, value: FilterValue) -> "Filter":
        """property is less than or equal to value"""
        return cls._create(property_name, "le", _param_value(value))

    @classmethod
    def gt(cls, property_name: str, value: FilterValue) -> "Filter":
        """property is greater than value"""
        return cls._create(property_name, "gt", _param_value(value))

    @classmethod
    def ge(cls, property_name: str, value: FilterValue) -> "Filter":
        """property is greater than or equal to value"""
        return cls._create(property_name, "ge", _param_value(value))

    @classmethod
    def like(cls, property_name: str, pattern: str) -> "Filter":
        """SQL-like pattern match (``%`` and ``_`` as placeholders), case-sensitive"""
        return cls._create(property_name, "like", pattern)

    @classmethod
    def ilike(cls, property_name: str, pattern: str) -> "Filter":
        """SQL-like pattern match (``%`` and ``_`` as placeholders), ignoring case"""
        return cls._create(property_name, "ilike", pattern)

    @classmethod
    def in_(cls, property_name: str, values: Iterable[FilterValue]) -> "Filter":
        """property is one of the values"""
        return cls._create(property_name, "in", json.dumps([_json_value(value) for value in values]))

    @classmethod
    def not_in(cls, property_name: str, values: Iterable[FilterValue]) -> "Filter":
        """property is none of the values"""
        return cls._create(property_name, "notin", json.dumps([_json_value(value) for value in values]))

    @classmethod
    def null(cls, property_name: str) -> "Filter":
        """property is null"""
        return cls._create(property_name, "null")

    @classmethod
    def not_null(cls, property_name: str) -> "Filter":
        """property is not null"""
        return cls._create(property_name, "notnull")

    @classmethod
    def custom_attribute_eq(cls, definition_id: str, value: FilterValue) -> "Filter":
        """the custom attribute with the given definition id has the value"""
        if not _CUSTOM_ATTRIBUTE_ID_PATTERN.fullmatch(definition_id):
            raise InvalidQueryError(f"Invalid custom attribute definition id: {definition_id!r}")
        return cls(
            property_name=f"customAttribute{definition_id}",
            operator="eq",
            value=_param_value(value),
            is_custom_attribute=True,
        )


def validate_filters(filters: Iterable[Filter], filterable_properties: frozenset[str], resource: str) -> None:
    """Raises :class:`InvalidQueryError` if a filter uses a property that cannot be filtered for the resource."""
    for condition in filters:
        if not condition.is_custom_attribute and condition.property_name not in filterable_properties:
            raise InvalidQueryError(f"Property {condition.property_name!r} cannot be used in filters of {resource}")

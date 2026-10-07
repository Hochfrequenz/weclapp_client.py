"""
Base classes of the models.

- Read models (:class:`WeclappEntity`) describe entities returned by weclapp. They guarantee ``id`` and ``version``;
  all other fields are optional because weclapp omits properties whose value is ``null``. Unknown properties are
  ignored, so extensions of the weclapp API do not break the client.
- Write models (:class:`WeclappCreateModel`, :class:`WeclappUpdateModel`) only contain writable properties, so
  read-only properties can never be sent (weclapp answers those with HTTP 400).
"""

from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from weclapp_client._converters import WeclappDateTime


class WeclappModel(BaseModel):
    """Maps the snake_case field names to the camelCase property names of weclapp (``first_name`` ↔ ``firstName``)."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
        extra="ignore",
    )


class WeclappEntity(WeclappModel):
    """An entity as returned by weclapp."""

    id: str
    version: str
    """used for optimistic locking; updates send it back, so concurrent changes are detected"""
    created_date: WeclappDateTime | None = None
    last_modified_date: WeclappDateTime | None = None


class WeclappCreateModel(WeclappModel):
    """The data for creating an entity. Fields that are ``None`` are not sent."""

    model_config = ConfigDict(extra="forbid")

    def to_payload(self) -> dict[str, Any]:
        """Returns the JSON body for the ``POST`` request."""
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)


class WeclappUpdateModel(WeclappModel):
    """
    The changes for a partial update. Only fields that were set explicitly are sent; setting a field to ``None``
    explicitly clears it in weclapp.
    """

    model_config = ConfigDict(extra="forbid")

    def to_payload(self) -> dict[str, Any]:
        """Returns the JSON body for the ``PUT`` request (without ``version``, the resource adds it)."""
        return self.model_dump(mode="json", by_alias=True, exclude_unset=True)

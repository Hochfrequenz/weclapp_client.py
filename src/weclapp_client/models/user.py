"""
Users (``/user``): the weclapp accounts that carry name and e-mail address of an employee.
"""

from enum import StrEnum

from pydantic import Field

from weclapp_client.models.base import WeclappCreateModel, WeclappEntity, WeclappUpdateModel
from weclapp_client.models.custom_attribute import CustomAttribute

_NAME_MAX_LENGTH = 50
_EMAIL_MAX_LENGTH = 256


class UserStatus(StrEnum):
    """Status of a user account."""

    ACTIVE = "ACTIVE"
    DEPARTURE = "DEPARTURE"
    NOT_ACTIVE = "NOT_ACTIVE"


class User(WeclappEntity):
    """A user as returned by weclapp."""

    username: str | None = None
    """assigned by weclapp, read-only"""
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    status: UserStatus | str | None = Field(default=None, union_mode="left_to_right")
    """a :class:`UserStatus`, or the raw value if weclapp introduces a new status"""
    can_edit_dashboard: bool | None = None
    custom_attributes: list[CustomAttribute] = Field(default_factory=list)

    def custom_attribute(self, definition_id: str) -> CustomAttribute | None:
        """Returns the value of the custom attribute with the given definition id, if the user has one."""
        return next(
            (attribute for attribute in self.custom_attributes if attribute.attribute_definition_id == definition_id),
            None,
        )


class UserCreate(WeclappCreateModel):
    """The data for creating a user. ``email``, ``status`` and ``can_edit_dashboard`` are required by weclapp."""

    email: str = Field(min_length=1, max_length=_EMAIL_MAX_LENGTH)
    status: UserStatus
    can_edit_dashboard: bool = False
    first_name: str | None = Field(default=None, max_length=_NAME_MAX_LENGTH)
    last_name: str | None = Field(default=None, max_length=_NAME_MAX_LENGTH)
    custom_attributes: list[CustomAttribute] | None = None


class UserUpdate(WeclappUpdateModel):
    """Changes of a user. Only the fields set explicitly are sent."""

    email: str | None = Field(default=None, min_length=1, max_length=_EMAIL_MAX_LENGTH)
    first_name: str | None = Field(default=None, max_length=_NAME_MAX_LENGTH)
    last_name: str | None = Field(default=None, max_length=_NAME_MAX_LENGTH)
    status: UserStatus | None = None
    custom_attributes: list[CustomAttribute] | None = None
    """only the attributes to change; weclapp keeps the values of all other custom attributes"""

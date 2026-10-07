"""
The ``/user`` resource.
"""

from typing import ClassVar

from weclapp_client.exceptions import WeclappError
from weclapp_client.models.user import User, UserCreate, UserUpdate
from weclapp_client.resources.base import WriteResource

# property names according to the weclapp OpenAPI specification (v2)
_PROPERTIES = frozenset(
    {
        "canEditDashboard",
        "createdDate",
        "customAttributes",
        "email",
        "faxNumber",
        "firstName",
        "id",
        "imageId",
        "lastModifiedDate",
        "lastName",
        "licenses",
        "mobilePhoneNumber",
        "phoneNumber",
        "status",
        "superUser",
        "title",
        "userRoles",
        "username",
        "version",
    }
)
_NOT_FILTERABLE = frozenset({"canEditDashboard", "customAttributes", "licenses", "userRoles"})
_ADDITIONAL_FILTERS = frozenset({"hasEmployee"})


class UsersResource(WriteResource[User, UserCreate, UserUpdate]):
    """
    Users: the weclapp accounts that hold name and e-mail address of employees.

    Filter on custom attributes with :meth:`weclapp_client.Filter.custom_attribute_eq`.
    """

    path = "user"
    entity_model = User
    known_properties: ClassVar[frozenset[str]] = _PROPERTIES
    filterable_properties: ClassVar[frozenset[str]] = (_PROPERTIES - _NOT_FILTERABLE) | _ADDITIONAL_FILTERS

    def current(self) -> User:
        """Returns the user the API token belongs to; useful to check the connection and the token."""
        data = self._transport.request_json("GET", f"{self.path}/currentUser")
        if not isinstance(data, dict) or "result" not in data:
            raise WeclappError("weclapp returned an unexpected response for user/currentUser")
        return self._parse(data["result"])

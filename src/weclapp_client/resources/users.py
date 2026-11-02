"""
The ``/user`` resource.
"""

from typing import Any, ClassVar

from weclapp_client._http import entity_path
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
        return self._parse_result(self._transport.request_json("GET", f"{self.path}/currentUser"), "user/currentUser")

    def invite(self, user_id: str) -> User:
        """
        Sends the user the invitation mail of weclapp (``POST user/id/{id}/invite``) and returns the user.

        weclapp has no dry run for this action, so every call really sends a mail. Like other ``POST`` requests, the
        call is not repeated if its outcome is unclear (e.g. after a read timeout), because the mail may have been sent.

        :raises NotFoundError: if there is no such user
        """
        data = self._transport.request_json("POST", f"{entity_path(self.path, user_id)}/invite", json_body={})
        return self._parse_result(data, "user/id/{id}/invite")

    def _parse_result(self, data: Any, action: str) -> User:
        if not isinstance(data, dict) or "result" not in data:
            raise WeclappError(f"weclapp returned an unexpected response for {action}")
        return self._parse(data["result"])

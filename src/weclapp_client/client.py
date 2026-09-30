"""
The entry point of the package: :class:`WeclappClient`.
"""

from types import TracebackType
from typing import Self

import httpx

from weclapp_client._http import HttpTransport
from weclapp_client.config import WeclappConfig
from weclapp_client.resources.custom_attribute_definitions import CustomAttributeDefinitionsResource
from weclapp_client.resources.employees import EmployeesResource
from weclapp_client.resources.users import UsersResource


class WeclappClient:
    """
    Client for the weclapp REST API v2.

    Use it as a context manager, so the HTTP connections are closed afterwards::

        with WeclappClient(WeclappConfig.from_env()) as client:
            user = client.users.current()

    :param http_client: an existing ``httpx.Client``, e.g. with a mock transport for tests; it is not closed by the
        weclapp client
    """

    def __init__(self, config: WeclappConfig, *, http_client: httpx.Client | None = None) -> None:
        self._transport = HttpTransport(config, http_client)
        self.users = UsersResource(self._transport)
        """``/user``: the accounts that hold name and e-mail address of employees"""
        self.employees = EmployeesResource(self._transport)
        """``/employee``: the HR records, each linked to a user"""
        self.custom_attribute_definitions = CustomAttributeDefinitionsResource(self._transport)
        """``/customAttributeDefinition``: the definitions of custom attributes"""

    def close(self) -> None:
        """Closes the HTTP connections (unless the ``httpx.Client`` was passed in)."""
        self._transport.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

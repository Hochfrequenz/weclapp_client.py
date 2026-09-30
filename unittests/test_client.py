import httpx

import weclapp_client
from weclapp_client import WeclappClient

from .helpers import make_config


def test_public_api() -> None:
    from weclapp_client import Filter, WeclappConfig  # noqa: F401, PLC0415
    from weclapp_client.models import (  # noqa: F401, PLC0415
        CustomAttribute,
        Employee,
        EmployeeCreate,
        EmployeeUpdate,
        User,
        UserCreate,
        UserStatus,
        UserUpdate,
    )

    for name in weclapp_client.__all__:
        assert hasattr(weclapp_client, name), name


def test_client_closes_its_own_http_client() -> None:
    with WeclappClient(make_config()) as client:
        transport_client = client._transport._client
        assert not transport_client.is_closed
    assert transport_client.is_closed


def test_client_keeps_an_injected_http_client_open() -> None:
    http_client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200)))
    with WeclappClient(make_config(), http_client=http_client) as client:
        assert client.users.path == "user"
        assert client.employees.path == "employee"
        assert client.custom_attribute_definitions.path == "customAttributeDefinition"
    assert not http_client.is_closed

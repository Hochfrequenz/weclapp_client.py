from collections.abc import Callable
from datetime import date

import httpx
import pytest

from weclapp_client import (
    CustomAttributeDefinitionError,
    Filter,
    InvalidQueryError,
    WeclappClient,
    WeclappError,
)
from weclapp_client.models import CustomAttribute, CustomAttributeType, EmployeeCreate, UserCreate, UserStatus

from .helpers import load_fixture, make_config


class _Router:
    """Answers requests by path and records them."""

    def __init__(self, routes: dict[str, Callable[[httpx.Request], httpx.Response]]) -> None:
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.removeprefix("/webapp/api/v2/")
        return self.routes[path](request)


def _client(router: _Router) -> WeclappClient:
    return WeclappClient(make_config(), http_client=httpx.Client(transport=httpx.MockTransport(router)))


def _json(body: object, status: int = 200) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: httpx.Response(status, json=body)


# ----------------------------------------------------------------------------------------------------------------------
# users


def test_current_user() -> None:
    router = _Router({"user/currentUser": _json({"result": load_fixture("user")})})
    user = _client(router).users.current()
    assert user.id == "4711"


def test_current_user_with_unexpected_response() -> None:
    router = _Router({"user/currentUser": _json(load_fixture("user"))})
    with pytest.raises(WeclappError):
        _client(router).users.current()


def test_find_user_by_personnel_number() -> None:
    router = _Router({"user": _json({"result": [load_fixture("user")]})})
    user = _client(router).users.find_one(Filter.custom_attribute_eq("9001", "00042"))
    assert user is not None
    personnel_number = user.custom_attribute("9001")
    assert personnel_number is not None
    assert personnel_number.string_value == "00042"
    assert router.requests[0].url.params["customAttribute9001-eq"] == "00042"


def test_user_filters_follow_the_specification() -> None:
    users = _client(_Router({"user": _json({"result": []})})).users
    users.list(Filter.eq("hasEmployee", True), Filter.eq("email", "a@example.com"))
    for property_name in ["customAttributes", "licenses", "userRoles", "canEditDashboard", "birthDate"]:
        with pytest.raises(InvalidQueryError):
            users.list(Filter.eq(property_name, "x"))


def test_create_user() -> None:
    router = _Router({"user": _json(load_fixture("user"), status=201)})
    user = _client(router).users.create(
        UserCreate(
            email="erika.musterfrau@example.com",
            first_name="Erika",
            last_name="Musterfrau",
            status=UserStatus.NOT_ACTIVE,
            custom_attributes=[CustomAttribute.of_string("9001", "00042")],
        )
    )
    assert user.username == "erika.musterfrau@example.com"
    assert router.requests[0].method == "POST"


# ----------------------------------------------------------------------------------------------------------------------
# employees


def test_employee_for_user() -> None:
    router = _Router({"employee": _json({"result": [load_fixture("employee")]})})
    employee = _client(router).employees.for_user("4711")
    assert employee is not None
    assert employee.birth_date == date(1985, 4, 12)
    params = router.requests[0].url.params
    assert params["userId-eq"] == "4711"
    assert params["pageSize"] == "2"


def test_employee_for_user_without_employee() -> None:
    router = _Router({"employee": _json({"result": []})})
    assert _client(router).employees.for_user("4711") is None


def test_employee_filters_include_properties_of_the_linked_user() -> None:
    employees = _client(_Router({"employee": _json({"result": []})})).employees
    employees.list(Filter.eq("lastName", "Musterfrau"), Filter.eq("fullUserName", "Erika Musterfrau"))
    with pytest.raises(InvalidQueryError):
        employees.list(Filter.eq("privateAddress", "x"))


def test_create_employee() -> None:
    router = _Router({"employee": _json(load_fixture("employee"), status=201)})
    employee = _client(router).employees.create(EmployeeCreate(user_id="4711", birth_date=date(1985, 4, 12)))
    assert employee.employee_number == "1001"
    assert router.requests[0].content == b'{"userId":"4711","birthDate":482112000000}'


# ----------------------------------------------------------------------------------------------------------------------
# custom attribute definitions


def _definitions_router() -> _Router:
    other = {"id": "9002", "version": "0", "attributeKey": "abteilung", "attributeType": "LIST"}
    without_key = {"id": "9003", "version": "0"}
    return _Router(
        {
            "customAttributeDefinition": _json(
                {"result": [load_fixture("custom_attribute_definition"), other, without_key]}
            )
        }
    )


def test_get_custom_attribute_definition_by_key_is_cached() -> None:
    router = _definitions_router()
    definitions = _client(router).custom_attribute_definitions
    first = definitions.get_by_key("personalnummer", expected_type=CustomAttributeType.STRING)
    second = definitions.get_by_key("abteilung")
    assert first.id == "9001"
    assert second.id == "9002"
    assert len(router.requests) == 1

    definitions.get_by_key("personalnummer", refresh=True)
    assert len(router.requests) == 2


def test_missing_custom_attribute_definition() -> None:
    with pytest.raises(CustomAttributeDefinitionError, match="personalnr"):
        _client(_definitions_router()).custom_attribute_definitions.get_by_key("personalnr")


def test_custom_attribute_definition_with_wrong_type() -> None:
    with pytest.raises(CustomAttributeDefinitionError, match="LIST"):
        _client(_definitions_router()).custom_attribute_definitions.get_by_key(
            "abteilung", expected_type=CustomAttributeType.STRING
        )

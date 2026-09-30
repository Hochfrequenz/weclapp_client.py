from datetime import date
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from weclapp_client import (
    AuthenticationError,
    Filter,
    NotFoundError,
    OptimisticLockError,
    RateLimitError,
    ServerError,
    WeclappApiError,
    WeclappClient,
    WeclappConfig,
    WeclappConnectionError,
    WeclappValidationError,
)
from weclapp_client.models import (
    CustomAttribute,
    CustomAttributeType,
    EmployeeCreate,
    EmployeeUpdate,
    UserCreate,
    UserStatus,
    UserUpdate,
)
from weclapp_client.testing import BASE_URL, DEFAULT_API_TOKEN, FakeWeclapp


def _raw(fake: FakeWeclapp, method: str, path: str, **kwargs: Any) -> httpx.Response:
    """Sends a request to the fake without the client, e.g. to send payloads the client would never send."""
    with httpx.Client(transport=fake.transport, base_url=BASE_URL) as http:
        return http.request(method, path, headers={"AuthenticationToken": DEFAULT_API_TOKEN}, **kwargs)


def _new_user(email: str = "erika.musterfrau@example.com", **fields: Any) -> UserCreate:
    return UserCreate(email=email, status=UserStatus.NOT_ACTIVE, **fields)


@pytest.fixture(name="fake")
def fake_fixture() -> FakeWeclapp:
    return FakeWeclapp()


@pytest.fixture(name="client")
def client_fixture(fake: FakeWeclapp) -> WeclappClient:
    return fake.client()


# ----------------------------------------------------------------------------------------------------------------------
# creating and reading


def test_create_user_assigns_meta_properties(fake: FakeWeclapp, client: WeclappClient) -> None:
    user = client.users.create(_new_user(first_name="Erika", last_name="Musterfrau"))

    assert user.id == "1000"
    assert user.version == "0"
    assert user.username == "erika.musterfrau@example.com"
    assert user.created_date is not None
    assert user.can_edit_dashboard is False
    assert fake.users == [user]
    assert client.users.get(user.id) == user


def test_create_employee_assigns_employee_number(fake: FakeWeclapp, client: WeclappClient) -> None:
    user = fake.add_user(email="a@example.com")
    first = client.employees.create(EmployeeCreate(user_id=user.id, birth_date=date(1950, 1, 1)))
    second_user = fake.add_user(email="b@example.com")
    second = client.employees.create(EmployeeCreate(user_id=second_user.id))

    assert first.employee_number == "1"
    assert first.birth_date == date(1950, 1, 1)
    assert second.employee_number == "2"
    assert client.employees.for_user(user.id) == first


def test_current_user_is_not_part_of_users(fake: FakeWeclapp, client: WeclappClient) -> None:
    assert client.users.current().username == "api-user@example.com"
    assert fake.users == []


def test_empty_strings_are_stored_as_null(client: WeclappClient) -> None:
    user = client.users.create(_new_user(first_name="  "))
    assert user.first_name is None


def test_get_unknown_entity(client: WeclappClient) -> None:
    with pytest.raises(NotFoundError):
        client.employees.get("4711")


# ----------------------------------------------------------------------------------------------------------------------
# queries


@pytest.fixture(name="populated")
def populated_fixture(fake: FakeWeclapp) -> FakeWeclapp:
    definition = fake.add_custom_attribute_definition(attribute_key="personalnummer")
    erika = fake.add_user(
        email="erika@example.com",
        first_name="Erika",
        last_name="Musterfrau",
        custom_attributes={definition.id: "00042"},
    )
    fake.add_user(email="max@example.com", first_name="Max", last_name="Mustermann", status=UserStatus.NOT_ACTIVE)
    fake.add_user(email="john@example.com", first_name="John", last_name="Doe", title="Dr.")
    fake.add_employee(user_id=erika.id, birth_date=date(1985, 4, 12))
    return fake


def _last_names(client: WeclappClient, *filters: Filter, sort: str = "id") -> list[str | None]:
    return [user.last_name for user in client.users.list(*filters, sort=sort)]


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        (Filter.eq("email", "max@example.com"), ["Mustermann"]),
        (Filter.ne("lastName", "Doe"), ["Musterfrau", "Mustermann"]),
        (Filter.eq("status", UserStatus.NOT_ACTIVE), ["Mustermann"]),
        (Filter.in_("firstName", ["Erika", "John"]), ["Musterfrau", "Doe"]),
        (Filter.not_in("firstName", ["Erika", "John"]), ["Mustermann"]),
        (Filter.like("lastName", "Muster%"), ["Musterfrau", "Mustermann"]),
        (Filter.like("lastName", "muster%"), []),
        (Filter.ilike("lastName", "muster_ann"), ["Mustermann"]),
        (Filter.null("title"), ["Musterfrau", "Mustermann"]),
        (Filter.not_null("title"), ["Doe"]),
        (Filter.eq("hasEmployee", True), ["Musterfrau"]),
        (Filter.eq("hasEmployee", False), ["Mustermann", "Doe"]),
        (Filter.gt("id", 1001), ["Mustermann", "Doe"]),
        (Filter.le("id", 1002), ["Musterfrau", "Mustermann"]),
        (Filter.custom_attribute_eq("1000", "00042"), ["Musterfrau"]),
        (Filter.custom_attribute_eq("1000", "99999"), []),
    ],
)
def test_user_filters(populated: FakeWeclapp, condition: Filter, expected: list[str]) -> None:
    assert _last_names(populated.client(), condition) == expected


def test_filters_are_combined_with_and(populated: FakeWeclapp) -> None:
    client = populated.client()
    assert _last_names(client, Filter.like("lastName", "Muster%"), Filter.eq("firstName", "Max")) == ["Mustermann"]


def test_employee_filters_on_properties_of_the_user(populated: FakeWeclapp) -> None:
    client = populated.client()
    assert len(client.employees.list(Filter.eq("lastName", "Musterfrau"))) == 1
    assert len(client.employees.list(Filter.eq("fullUserName", "Erika Musterfrau"))) == 1
    assert client.employees.list(Filter.eq("email", "max@example.com")) == []
    assert len(client.employees.list(Filter.lt("birthDate", date(1990, 1, 1)))) == 1


def test_sort_and_paging(populated: FakeWeclapp) -> None:
    client = populated.client()
    assert _last_names(client, sort="-lastName") == ["Mustermann", "Musterfrau", "Doe"]
    assert _last_names(client, sort="firstName,-id") == ["Musterfrau", "Doe", "Mustermann"]
    assert [user.last_name for user in client.users.iterate(page_size=2)] == ["Musterfrau", "Mustermann", "Doe"]


def test_property_selection(populated: FakeWeclapp) -> None:
    users = populated.client().users.list(properties=["lastName"])
    assert users[0].last_name == "Musterfrau"
    assert users[0].email is None


def test_count(populated: FakeWeclapp) -> None:
    client = populated.client()
    assert client.users.count() == 3
    assert client.users.count(Filter.like("lastName", "Muster%")) == 2


def test_unknown_filters_are_ignored_like_in_weclapp(populated: FakeWeclapp) -> None:
    response = _raw(populated, "GET", "user", params={"emial-eq": "max@example.com", "lastName-between": "x"})
    assert len(response.json()["result"]) == 3


@pytest.mark.parametrize("params", [{"pageSize": "1001"}, {"page": "0"}, {"page": "x"}])
def test_invalid_paging_is_rejected(fake: FakeWeclapp, params: dict[str, str]) -> None:
    assert _raw(fake, "GET", "user", params=params).status_code == 400


def test_custom_attribute_definitions(populated: FakeWeclapp) -> None:
    definition = populated.client().custom_attribute_definitions.get_by_key(
        "personalnummer", expected_type=CustomAttributeType.STRING
    )
    assert definition == populated.custom_attribute_definitions[0]


# ----------------------------------------------------------------------------------------------------------------------
# updates


def test_partial_update_increments_the_version(fake: FakeWeclapp, client: WeclappClient) -> None:
    user = fake.add_user(email="erika@example.com", first_name="Erika", last_name="Musterfrau")
    updated = client.users.update(user, UserUpdate(last_name="Beispiel"))

    assert updated.version == "1"
    assert updated.first_name == "Erika"
    assert updated.last_name == "Beispiel"
    assert updated.last_modified_date is not None
    assert user.last_modified_date is not None
    assert updated.last_modified_date > user.last_modified_date


def test_stale_version_raises_optimistic_lock_error(fake: FakeWeclapp, client: WeclappClient) -> None:
    user = fake.add_user(email="erika@example.com")
    client.users.update(user, UserUpdate(first_name="Erika"))
    with pytest.raises(OptimisticLockError):
        client.users.update(user, UserUpdate(first_name="Erika Maria"))


def test_partial_update_merges_custom_attributes(fake: FakeWeclapp, client: WeclappClient) -> None:
    user = fake.add_user(email="erika@example.com", custom_attributes={"9001": "00042", "9002": "Vertrieb"})
    updated = client.users.update(user, UserUpdate(custom_attributes=[CustomAttribute.of_string("9001", "00043")]))

    assert updated.custom_attribute("9001") == CustomAttribute.of_string("9001", "00043")
    assert updated.custom_attribute("9002") == CustomAttribute.of_string("9002", "Vertrieb")


def test_update_can_clear_a_value(fake: FakeWeclapp, client: WeclappClient) -> None:
    user = fake.add_user(email="erika@example.com")
    employee = fake.add_employee(user_id=user.id, birth_date=date(1985, 4, 12))
    assert client.employees.update(employee, EmployeeUpdate(birth_date=None)).birth_date is None


def test_complete_update_clears_properties_not_sent(fake: FakeWeclapp) -> None:
    user = fake.add_user(email="erika@example.com", first_name="Erika", last_name="Musterfrau")
    response = _raw(fake, "PUT", f"user/id/{user.id}", json={"email": "erika@example.com", "status": "ACTIVE"})

    assert response.status_code == 200
    assert "firstName" not in response.json()
    assert fake.users[0].last_name is None


def test_update_with_mismatching_id_is_rejected(fake: FakeWeclapp) -> None:
    user = fake.add_user(email="erika@example.com")
    response = _raw(fake, "PUT", f"user/id/{user.id}", params={"ignoreMissingProperties": "true"}, json={"id": "1"})
    assert response.status_code == 400


# ----------------------------------------------------------------------------------------------------------------------
# validation


@pytest.mark.parametrize(
    ("body", "location"),
    [
        ({"status": "ACTIVE"}, "email"),
        ({"email": "a@example.com"}, "status"),
        ({"email": "a@example.com", "status": "ACTIVE", "username": "a"}, "username"),
        ({"email": "a@example.com", "status": "ACTIVE", "version": "0"}, "version"),
        ({"email": "a@example.com", "status": "ACTIVE", "nickname": "a"}, "nickname"),
        ({"email": "a@example.com", "status": "RETIRED"}, "status"),
    ],
)
def test_create_user_validation(fake: FakeWeclapp, body: dict[str, str], location: str) -> None:
    response = _raw(fake, "POST", "user", json=body)
    assert response.status_code == 400
    assert location in [issue["location"] for issue in response.json()["validationErrors"]]
    assert fake.users == []


def test_invalid_json_is_rejected(fake: FakeWeclapp) -> None:
    assert _raw(fake, "POST", "user", content=b"{not json").status_code == 400
    assert _raw(fake, "POST", "user", json=["a list"]).status_code == 400
    user = fake.add_user(email="a@example.com")
    assert _raw(fake, "PUT", f"user/id/{user.id}", json=["a list"]).status_code == 400


def test_duplicate_email_is_rejected(fake: FakeWeclapp, client: WeclappClient) -> None:
    fake.add_user(email="Erika@example.com")
    with pytest.raises(WeclappValidationError) as error_info:
        client.users.create(_new_user("erika@example.com"))
    assert error_info.value.validation_errors[0].type == "duplicate"


def test_employee_needs_an_existing_user(client: WeclappClient) -> None:
    with pytest.raises(WeclappValidationError) as error_info:
        client.employees.create(EmployeeCreate(user_id="4711"))
    assert error_info.value.validation_errors[0].location == "userId"


def test_user_can_have_only_one_employee(fake: FakeWeclapp, client: WeclappClient) -> None:
    user = fake.add_user(email="a@example.com")
    client.employees.create(EmployeeCreate(user_id=user.id))
    with pytest.raises(WeclappValidationError):
        client.employees.create(EmployeeCreate(user_id=user.id))


def test_custom_attribute_definitions_are_read_only_via_api(fake: FakeWeclapp) -> None:
    response = _raw(fake, "POST", "customAttributeDefinition", json={"attributeKey": "x", "attributeType": "STRING"})
    assert response.status_code == 405


def test_unknown_resource(fake: FakeWeclapp) -> None:
    assert _raw(fake, "GET", "party").status_code == 404


def test_requests_to_other_hosts_are_not_routed(fake: FakeWeclapp) -> None:
    with httpx.Client(transport=fake.transport) as http:
        response = http.get("https://other.example.test/webapp/api/v2/user", headers={"AuthenticationToken": "x"})
    assert response.status_code == 401
    with httpx.Client(transport=fake.transport) as http:
        response = http.get(
            "https://other.example.test/webapp/api/v2/user", headers={"AuthenticationToken": DEFAULT_API_TOKEN}
        )
    assert response.status_code == 404


def test_wrong_token_is_rejected(fake: FakeWeclapp) -> None:
    config = WeclappConfig(base_url=BASE_URL, api_token=SecretStr("wrong-token"))
    with WeclappClient(config, http_client=httpx.Client(transport=fake.transport)) as client:
        with pytest.raises(AuthenticationError):
            client.users.current()


# ----------------------------------------------------------------------------------------------------------------------
# dry run


def test_dry_run_create_stores_nothing(fake: FakeWeclapp, client: WeclappClient) -> None:
    assert client.users.create(_new_user(), dry_run=True) is None
    assert fake.users == []
    assert fake.write_requests == []

    body = {"email": "a@example.com", "status": "ACTIVE"}
    response = _raw(fake, "POST", "user", params={"dryRun": "true"}, json=body)
    assert response.status_code == 200
    assert "id" not in response.json()


def test_dry_run_still_validates(client: WeclappClient) -> None:
    with pytest.raises(WeclappValidationError):
        client.employees.create(EmployeeCreate(user_id="4711"), dry_run=True)


def test_dry_run_update_changes_nothing(fake: FakeWeclapp, client: WeclappClient) -> None:
    user = fake.add_user(email="a@example.com", first_name="Erika")
    assert client.users.update(user, UserUpdate(first_name="Max"), dry_run=True) is None
    assert fake.users == [user]


# ----------------------------------------------------------------------------------------------------------------------
# recorded requests and injected failures


def test_requests_are_recorded(fake: FakeWeclapp, client: WeclappClient) -> None:
    user = client.users.create(_new_user())
    client.users.list()
    client.users.update(user, UserUpdate(first_name="Erika"), dry_run=True)

    assert [(request.method, request.path) for request in fake.requests] == [
        ("POST", "user"),
        ("GET", "user"),
        ("PUT", f"user/id/{user.id}"),
    ]
    assert [request.method for request in fake.write_requests] == ["POST"]
    assert fake.write_requests[0].body == {
        "email": "erika.musterfrau@example.com",
        "status": "NOT_ACTIVE",
        "canEditDashboard": False,
    }
    fake.clear_requests()
    assert fake.requests == []


def test_injected_429_is_retried(fake: FakeWeclapp, client: WeclappClient) -> None:
    fake.fail_next(429, times=2)
    assert client.users.list() == []
    assert len(fake.requests) == 3


def test_injected_429_until_retries_are_exhausted(fake: FakeWeclapp) -> None:
    fake.fail_next(429, times=3)
    with pytest.raises(RateLimitError):
        fake.client(max_retries=2).users.list()


def test_injected_failure_matches_method_and_path(fake: FakeWeclapp, client: WeclappClient) -> None:
    user = fake.add_user(email="a@example.com")
    fake.fail_next(503, method="POST", path="employee")
    assert client.users.list() != []
    with pytest.raises(ServerError):
        client.employees.create(EmployeeCreate(user_id=user.id))
    assert fake.employees == []
    client.employees.create(EmployeeCreate(user_id=user.id))
    assert len(fake.employees) == 1


def test_injected_exception(fake: FakeWeclapp, client: WeclappClient) -> None:
    fake.fail_next(exception=httpx.ReadTimeout("timeout"), method="POST")
    with pytest.raises(WeclappConnectionError):
        client.users.create(_new_user())
    assert fake.users == []


def test_injected_client_error(fake: FakeWeclapp, client: WeclappClient) -> None:
    fake.fail_next(418)
    with pytest.raises(WeclappApiError) as error_info:
        client.users.list()
    assert error_info.value.status_code == 418


# ----------------------------------------------------------------------------------------------------------------------
# a synchronisation run as the sync repository would implement it


def _upsert(client: WeclappClient, personnel_number: str, first_name: str, birth_date: date) -> None:
    definition = client.custom_attribute_definitions.get_by_key("personalnummer")
    user = client.users.find_one(Filter.custom_attribute_eq(definition.id, personnel_number))
    if user is None:
        user = client.users.create(
            UserCreate(
                email=f"{personnel_number}@example.com",
                first_name=first_name,
                last_name="Musterfrau",
                status=UserStatus.NOT_ACTIVE,
                custom_attributes=[CustomAttribute.of_string(definition.id, personnel_number)],
            )
        )
    elif user.first_name != first_name:
        user = client.users.update(user, UserUpdate(first_name=first_name))
    employee = client.employees.for_user(user.id)
    if employee is None:
        client.employees.create(EmployeeCreate(user_id=user.id, birth_date=birth_date))
    elif employee.birth_date != birth_date:
        client.employees.update(employee, EmployeeUpdate(birth_date=birth_date))


def test_synchronisation_scenario(fake: FakeWeclapp, client: WeclappClient) -> None:
    fake.add_custom_attribute_definition(attribute_key="personalnummer")

    _upsert(client, "00042", "Erika", date(1985, 4, 12))
    assert [(user.first_name, user.status) for user in fake.users] == [("Erika", UserStatus.NOT_ACTIVE)]
    assert [employee.birth_date for employee in fake.employees] == [date(1985, 4, 12)]

    fake.clear_requests()
    _upsert(client, "00042", "Erika", date(1985, 4, 12))
    assert fake.write_requests == []

    _upsert(client, "00042", "Erika Maria", date(1985, 4, 13))
    assert [request.path.split("/")[0] for request in fake.write_requests] == ["user", "employee"]
    assert fake.users[0].first_name == "Erika Maria"
    assert fake.employees[0].birth_date == date(1985, 4, 13)

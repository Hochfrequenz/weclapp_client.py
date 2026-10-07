"""
Tier 1: read-only checks and dry runs, safe for a production tenant.

Probes that explore weclapp's behaviour record their result in the report instead of asserting it, because a dry run
does not necessarily run all checks of a real request. The write tests (tier 2) assert the real behaviour.
"""

import itertools
from collections import Counter
from collections.abc import Callable
from typing import Any

import pytest

from weclapp_client import Filter, NotFoundError, WeclappApiError, WeclappClient, WeclappValidationError
from weclapp_client._http import entity_path
from weclapp_client.models import CustomAttributeDefinition, EmployeeCreate, UserCreate, UserStatus

from .conftest import TEST_LAST_NAME, Cleanup, IntegrationReport

pytestmark = pytest.mark.integration

_DAY_MS = 86_400_000
_HOUR_MS = 3_600_000
_OFFSET_NAMES = {
    0: "Mitternacht UTC",
    _DAY_MS - 1 * _HOUR_MS: "Mitternacht MEZ (UTC+1)",
    _DAY_MS - 2 * _HOUR_MS: "Mitternacht MESZ (UTC+2)",
}


def _raw(client: WeclappClient, method: str, path: str, params: list[tuple[str, str]], body: Any = None) -> Any:
    """Sends a request the client API does not offer (e.g. to inspect the raw response)."""
    return client._transport.request_json(method, path, params=params, json_body=body)


def _rejection(call: Callable[[], object]) -> str:
    """Runs a dry-run call and describes whether weclapp rejected it."""
    try:
        call()
    except WeclappValidationError as error:
        issue_types = sorted({issue.type or "?" for issue in error.validation_errors})
        return f"abgewiesen (400, validationErrors: {', '.join(issue_types) or 'keine'})"
    except WeclappApiError as error:
        return f"abgewiesen (HTTP {error.status_code}, {error.problem_type})"
    return "NICHT abgewiesen"


# ----------------------------------------------------------------------------------------------------------------------
# connection, paging, sorting (P8, P9)


def test_current_user(client: WeclappClient, report: IntegrationReport) -> None:
    user = client.users.current()
    assert user.id
    assert user.version
    report.finding("P9", f"Token gültig, API-User hat die id {user.id}")
    report.manual("P9: minimale Rechte des API-Users durch schrittweises Einschränken seiner Rolle ermitteln")


@pytest.mark.parametrize("resource_name", ["users", "employees"])
def test_iteration_returns_every_entity_once(
    client: WeclappClient, report: IntegrationReport, resource_name: str
) -> None:
    resource = client.users if resource_name == "users" else client.employees
    ids = [entity.id for entity in resource.iterate(properties=["id"])]
    count = resource.count()
    unique = len(set(ids)) == len(ids)
    complete = len(ids) == count
    assert unique, "iterate() returned duplicates"
    assert complete, "iterate() and count() disagree"
    report.finding("P8", f"{resource_name}: {count} Datensätze, Paging mit pageSize=1000 und sort=id vollständig")


def test_small_pages_match_large_pages(client: WeclappClient) -> None:
    small = [user.id for user in itertools.islice(client.users.iterate(properties=["id"], page_size=2), 6)]
    large = [user.id for user in itertools.islice(client.users.iterate(properties=["id"]), 6)]
    assert small == large


# ----------------------------------------------------------------------------------------------------------------------
# custom attributes (P6)


def test_custom_attribute_selection_and_filter(
    client: WeclappClient, report: IntegrationReport, personnel_number_definition: CustomAttributeDefinition
) -> None:
    definition_id = personnel_number_definition.id
    users = client.users.list(properties=["customAttributes"])
    with_value = [
        user for user in users if (attribute := user.custom_attribute(definition_id)) and attribute.string_value
    ]
    report.finding("P6", f"properties=customAttributes funktioniert; {len(with_value)} User haben eine Personalnummer")
    if not with_value:
        report.finding("P6", "Filter customAttribute<id>-eq nicht geprüft (noch kein User mit Personalnummer)")
        return
    sample = with_value[0]
    attribute = sample.custom_attribute(definition_id)
    assert attribute is not None
    assert attribute.string_value is not None
    found = client.users.find_one(Filter.custom_attribute_eq(definition_id, attribute.string_value))
    same_user = found is not None and found.id == sample.id
    assert same_user, "the custom attribute filter did not find the user"
    report.finding("P6", "Filter customAttribute<id>-eq findet den User")


# ----------------------------------------------------------------------------------------------------------------------
# birth dates (P5)


def test_birth_date_convention(client: WeclappClient, report: IntegrationReport) -> None:
    params = [("birthDate-notnull", ""), ("properties", "id,birthDate"), ("page", "1"), ("pageSize", "200")]
    employees = _raw(client, "GET", "employee", params)["result"]
    offsets = Counter(
        _OFFSET_NAMES.get(employee["birthDate"] % _DAY_MS, "andere Uhrzeit")
        for employee in employees
        if isinstance(employee.get("birthDate"), int)
    )
    if not offsets:
        report.finding("P5", "nicht prüfbar, kein Employee mit Geburtsdatum")
        return
    summary = ", ".join(f"{name}: {count}" for name, count in offsets.most_common())
    report.finding("P5", f"gespeicherte Geburtsdaten ({sum(offsets.values())} geprüft): {summary}")
    report.manual("P5: für einen Employee das Geburtsdatum in der Oberfläche mit dem Wert im Client vergleichen")


# ----------------------------------------------------------------------------------------------------------------------
# required properties and validation (P1, P2, P4, P10, P11)


@pytest.fixture(name="verified_dry_run", scope="module")
def verified_dry_run_fixture(
    client: WeclappClient, report: IntegrationReport, new_email: Callable[[], str], cleanup: Cleanup
) -> None:
    """
    Makes sure that a dry run does not store anything, before dry runs with real data (e-mail addresses, user ids)
    are sent. If it does, the leaked test record is removed and all dependent probes fail.
    """
    email = new_email()
    data = UserCreate(email=email, status=UserStatus.NOT_ACTIVE, last_name=TEST_LAST_NAME)
    assert client.users.create(data, dry_run=True) is None
    leaked = client.users.find_one(Filter.eq("email", email))
    if leaked is not None:
        cleanup.add_user(leaked.id)
        report.finding("P1", "ACHTUNG: dryRun=true hat einen User gespeichert, Dry-Run-Proben abgebrochen")
        pytest.fail("dryRun=true stored a user; the dry-run probes are not safe")
    report.finding("P1", "Dry-Run speichert nichts (per Suche nach der Test-E-Mail bestätigt)")


def test_dry_run_create_minimal_user(
    client: WeclappClient, report: IntegrationReport, new_email: Callable[[], str], verified_dry_run: None
) -> None:
    report.finding("P1", "Dry-Run: User mit email, status=NOT_ACTIVE und canEditDashboard=false wird akzeptiert")
    report.finding("P2", "Dry-Run: status NOT_ACTIVE beim Anlegen wird akzeptiert")

    minimal = {"email": new_email(), "status": "NOT_ACTIVE", "lastName": TEST_LAST_NAME}
    outcome = _rejection(lambda: _raw(client, "POST", "user", [("dryRun", "true")], minimal))
    report.finding("P1", f"Dry-Run ohne canEditDashboard: {outcome}")


def test_dry_run_user_without_email_is_rejected(client: WeclappClient, report: IntegrationReport) -> None:
    with pytest.raises(WeclappValidationError) as error_info:
        _raw(client, "POST", "user", [("dryRun", "true")], {"status": "NOT_ACTIVE", "lastName": TEST_LAST_NAME})
    error = error_info.value
    locations = sorted({issue.location or "?" for issue in error.validation_errors})
    report.finding("P1", f"Dry-Run ohne email: abgewiesen, betroffene Felder: {', '.join(locations) or 'keine Angabe'}")
    report.finding("P10", f"400: problem_type={error.problem_type}, {len(error.validation_errors)} validationErrors")


def test_dry_run_duplicate_email(client: WeclappClient, report: IntegrationReport, verified_dry_run: None) -> None:
    existing = next((user for user in client.users.iterate(properties=["email"]) if user.email), None)
    if existing is None or existing.email is None:
        report.finding("P4", "nicht prüfbar, kein User mit E-Mail-Adresse")
        return
    email = existing.email
    for label, candidate in [("gleiche Schreibweise", email), ("andere Groß-/Kleinschreibung", email.swapcase())]:
        data = UserCreate(email=candidate, status=UserStatus.NOT_ACTIVE, last_name=TEST_LAST_NAME)

        def create_in_dry_run(data: UserCreate = data) -> None:
            client.users.create(data, dry_run=True)

        report.finding("P4", f"Dry-Run mit vorhandener E-Mail ({label}): {_rejection(create_in_dry_run)}")


def test_dry_run_second_employee_for_user(
    client: WeclappClient, report: IntegrationReport, verified_dry_run: None
) -> None:
    employee = next((item for item in client.employees.iterate(properties=["userId"]) if item.user_id), None)
    if employee is None or employee.user_id is None:
        report.finding("P11", "nicht prüfbar, kein Employee vorhanden")
        return
    user_id = employee.user_id
    outcome = _rejection(lambda: client.employees.create(EmployeeCreate(user_id=user_id), dry_run=True))
    report.finding("P11", f"Dry-Run: zweite Personalakte für einen User: {outcome}")


def test_unknown_ids_raise_not_found(client: WeclappClient, report: IntegrationReport) -> None:
    with pytest.raises(NotFoundError) as error_info:
        client.employees.get("0")
    report.finding("P10", f"404: problem_type={error_info.value.problem_type}")


# ----------------------------------------------------------------------------------------------------------------------
# partial updates and optimistic locking (P7, P10), probed as dry runs on the API user itself


def test_dry_run_partial_update(client: WeclappClient, report: IntegrationReport) -> None:
    me = client.users.current()
    if me.last_name is None or me.email is None:
        report.finding("P7", "nicht prüfbar, dem API-User fehlen lastName oder email")
        return
    # the value does not change, so even an ignored dryRun would not modify anything
    body: dict[str, Any] = {"version": me.version, "lastName": me.last_name}
    params = [("ignoreMissingProperties", "true"), ("dryRun", "true")]
    response = _raw(client, "PUT", entity_path("user", me.id), params, body)
    other_fields_kept = response.get("email") == me.email
    assert other_fields_kept, "ignoreMissingProperties=true is not honoured: other properties would be cleared"
    report.finding("P7", "ignoreMissingProperties=true bei PUT /user: nicht gesendete Felder bleiben erhalten")

    if len(me.custom_attributes) < 2:
        report.finding("P7", "Zusammenführen der customAttributes nicht prüfbar (API-User hat < 2 Custom Attributes)")
        return
    first, second = me.custom_attributes[:2]
    body = {"version": me.version, "customAttributes": [first.model_dump(mode="json", exclude_none=True)]}
    response = _raw(client, "PUT", entity_path("user", me.id), params, body)
    returned_ids = {attribute.get("attributeDefinitionId") for attribute in response.get("customAttributes", [])}
    merged = second.attribute_definition_id in returned_ids
    report.finding("P7", f"customAttributes werden {'zusammengeführt' if merged else 'NICHT zusammengeführt'}")


def test_dry_run_with_stale_version(client: WeclappClient, report: IntegrationReport) -> None:
    me = client.users.current()
    if me.last_name is None:
        report.finding("P10", "409 nicht prüfbar, dem API-User fehlt lastName")
        return
    stale_version = str(int(me.version) + 1000) if me.version.isdigit() else "stale"
    body = {"version": stale_version, "lastName": me.last_name}
    params = [("ignoreMissingProperties", "true"), ("dryRun", "true")]
    outcome = _rejection(lambda: _raw(client, "PUT", entity_path("user", me.id), params, body))
    report.finding("P10", f"Dry-Run mit veralteter version: {outcome}")

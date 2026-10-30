"""
Tier 1: read-only checks and dry runs, safe for a production tenant.

Probes that explore weclapp's behaviour record their result in the report instead of asserting it, because a dry run
does not necessarily run all checks of a real request. The write tests (tier 2) assert the real behaviour.
"""

import itertools
import re
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import pytest

from weclapp_client import Filter, NotFoundError, WeclappApiError, WeclappClient, WeclappValidationError
from weclapp_client._converters import date_to_ms, ms_to_date
from weclapp_client._http import entity_path
from weclapp_client.models import (
    CustomAttribute,
    CustomAttributeDefinition,
    CustomAttributeType,
    EmployeeCreate,
    User,
    UserCreate,
    UserStatus,
)

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
        issue_types = sorted(
            {
                f"{issue.type or '?'} ({issue.error_code})" if issue.error_code else issue.type or "?"
                for issue in error.validation_errors
            }
        )
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
# date-only fields (P5)


def _time_of_day(timestamp_ms: int) -> str:
    offset = timestamp_ms % _DAY_MS
    return _OFFSET_NAMES.get(offset, f"{offset / _HOUR_MS:g}:00 UTC")


@pytest.mark.parametrize(("property_name", "label"), [("birthDate", "Geburtsdatum"), ("entryDate", "Eintrittsdatum")])
def test_date_convention(client: WeclappClient, report: IntegrationReport, property_name: str, label: str) -> None:
    params = [
        (f"{property_name}-notnull", ""),
        ("properties", f"id,{property_name}"),
        ("page", "1"),
        ("pageSize", "200"),
    ]
    employees = _raw(client, "GET", "employee", params)["result"]
    offsets = Counter(
        _time_of_day(employee[property_name]) for employee in employees if isinstance(employee.get(property_name), int)
    )
    if not offsets:
        report.finding("P5", f"{property_name} nicht prüfbar, kein Employee mit {label}")
        return
    summary = ", ".join(f"{name}: {count}" for name, count in offsets.most_common())
    report.finding("P5", f"gespeicherte Werte von {property_name} ({sum(offsets.values())} geprüft): {summary}")
    report.manual(f"P5: für einen Employee das {label} in der Oberfläche mit dem Wert im Client vergleichen")


@pytest.mark.parametrize("property_name", ["birthDate", "entryDate"])
def test_date_filters(client: WeclappClient, report: IntegrationReport, property_name: str) -> None:
    """Date filters find a record whatever time of day weclapp holds for the date (one record per time of day)."""
    params = [
        (f"{property_name}-notnull", ""),
        ("properties", f"id,{property_name}"),
        ("page", "1"),
        ("pageSize", "200"),
    ]
    samples: dict[str, dict[str, Any]] = {}
    for employee in _raw(client, "GET", "employee", params)["result"]:
        if isinstance(employee.get(property_name), int):
            samples.setdefault(_time_of_day(employee[property_name]), employee)
    if not samples:
        pytest.skip(f"no employee with {property_name}")
    for time_of_day, employee in samples.items():
        day = ms_to_date(employee[property_name])
        same_employee = Filter.eq("id", employee["id"])
        counts = {
            name: client.employees.count(same_employee, condition)
            for name, condition in [
                ("eq", Filter.eq(property_name, day)),
                ("le", Filter.le(property_name, day)),
                ("ge", Filter.ge(property_name, day)),
                ("ne", Filter.ne(property_name, day)),
                ("lt", Filter.lt(property_name, day)),
                ("gt", Filter.gt(property_name, day)),
                ("eq next day", Filter.eq(property_name, day + timedelta(days=1))),
            ]
        }
        expected = {"eq": 1, "le": 1, "ge": 1, "ne": 0, "lt": 0, "gt": 0, "eq next day": 0}
        assert counts == expected, time_of_day
    report.finding("P5", f"Datumsfilter auf {property_name} treffen gespeicherte Werte um {', '.join(samples)}")


# ----------------------------------------------------------------------------------------------------------------------
# conventions in the existing data (P1, P3, P4, P11); only counts are reported


def _username_convention(username: str | None, email: str | None) -> str:
    if not username:
        return "ohne username"
    if not email:
        return "ohne E-Mail"
    if username == email:
        return "gleich der E-Mail-Adresse"
    if username == email.lower():
        return "gleich der E-Mail-Adresse in Kleinschreibung"
    if username.lower() == email.lower():
        return "gleich der E-Mail-Adresse in anderer Schreibweise"
    if "@" not in username:
        return "ohne @ gebildet"
    return "eine andere E-Mail-Adresse"


def test_existing_usernames_and_emails(client: WeclappClient, report: IntegrationReport) -> None:
    users = client.users.list(properties=["username", "email", "status"])
    conventions = Counter(_username_convention(user.username, user.email) for user in users)
    summary = ", ".join(f"{name}: {count}" for name, count in conventions.most_common())
    report.finding("P4", f"username bestehender User ({len(users)}): {summary}")

    by_email: defaultdict[str, list[User]] = defaultdict(list)
    for user in users:
        if user.email:
            by_email[user.email.lower()].append(user)
    groups = [group for group in by_email.values() if len(group) > 1]
    if not groups:
        report.finding("P4", "keine E-Mail-Adresse kommt (ohne Groß-/Kleinschreibung) mehrfach vor")
        return
    same_spelling = sum(1 for group in groups if len({user.email for user in group}) < len(group))
    statuses = Counter(str(user.status or "ohne Status") for group in groups for user in group)
    status_summary = ", ".join(f"{name}: {count}" for name, count in statuses.most_common())
    report.finding(
        "P4",
        f"{len(groups)} E-Mail-Adressen kommen mehrfach vor ({same_spelling} davon in gleicher Schreibweise); "
        f"Status der betroffenen User: {status_summary}",
    )


def test_existing_employee_records(client: WeclappClient, report: IntegrationReport) -> None:
    status_by_user = {user.id: user.status for user in client.users.iterate(properties=["status"])}
    employees = client.employees.list(properties=["userId"])
    per_user = Counter(employee.user_id for employee in employees if employee.user_id)

    without_user = len(employees) - sum(per_user.values())
    report.finding("P1", f"bestehende Personalakten ohne userId: {without_user} von {len(employees)}")

    statuses = Counter(
        str(status_by_user[user_id] or "ohne Status") if user_id in status_by_user else "User nicht gefunden"
        for user_id in per_user
    )
    summary = ", ".join(f"{name}: {count}" for name, count in statuses.most_common())
    report.finding("P3", f"Status der User mit Personalakte: {summary or 'keine Personalakten'}")

    several = sum(1 for count in per_user.values() if count > 1)
    if several:
        report.finding("P11", f"ACHTUNG: {several} User haben mehr als eine Personalakte, FakeWeclapp anpassen")
    else:
        report.finding("P11", "in den bestehenden Daten hat kein User mehr als eine Personalakte")


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


def test_dry_run_username_cannot_be_set(
    client: WeclappClient, report: IntegrationReport, new_email: Callable[[], str], verified_dry_run: None
) -> None:
    email = new_email()
    body = {"email": email, "status": "NOT_ACTIVE", "lastName": TEST_LAST_NAME, "username": email}
    outcome = _rejection(lambda: _raw(client, "POST", "user", [("dryRun", "true")], body))
    report.finding("P4", f"Dry-Run mit username gleich der E-Mail-Adresse: {outcome}")


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


def test_dry_run_start_date_of_work_schedule(client: WeclappClient, report: IntegrationReport) -> None:
    # for a user that already has an employee record, so weclapp rejects the request in any case
    user_id = next((item.user_id for item in client.employees.iterate(properties=["userId"]) if item.user_id), None)
    profile = next(iter(client.work_schedule_profiles.list()), None)
    if user_id is None or profile is None:
        report.finding("P5", "Startdatum nicht prüfbar, kein Employee oder kein Arbeitszeitprofil vorhanden")
        return
    for label, start_date in [
        ("Mitternacht deutscher Zeit (wie der Client)", date_to_ms(date(2026, 11, 1))),
        ("Mitternacht UTC", date_to_ms(date(2026, 11, 1)) + _HOUR_MS),
    ]:
        assignment = {"workScheduleProfileId": profile.id, "startDate": start_date}
        body = {"userId": user_id, "workScheduleProfileAssignments": [assignment]}
        try:
            _raw(client, "POST", "employee", [("dryRun", "true")], body)
        except WeclappValidationError as error:
            rejected = any("startDate" in (issue.location or "") for issue in error.validation_errors)
            report.finding(
                "P5", f"Startdatum eines Arbeitszeitprofils als {label}: {'abgewiesen' if rejected else 'ok'}"
            )


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


# ----------------------------------------------------------------------------------------------------------------------
# mobile phone number (P12) and the values of list attributes (P13); phone numbers are only reported by their shape


def _shape(phone_number: str) -> str:
    """the form of a phone number without its digits, e.g. ``+99 999 99999999``"""
    return re.sub(r"[0-9]", "9", phone_number)


def test_existing_mobile_phone_numbers(client: WeclappClient, report: IntegrationReport) -> None:
    users = client.users.iterate(Filter.not_null("mobilePhoneNumber"), properties=["mobilePhoneNumber"])
    shapes = Counter(_shape(user.mobile_phone_number) for user in users if user.mobile_phone_number)
    summary = ", ".join(f"{shape}: {count}" for shape, count in shapes.most_common(5)) or "keine"
    report.finding("P12", f"Formen von mobilePhoneNumber bestehender User ({shapes.total()}): {summary}")


def test_dry_run_mobile_phone_number(
    client: WeclappClient, report: IntegrationReport, new_email: Callable[[], str], verified_dry_run: None
) -> None:
    number = "+49 151 12345678"
    data = UserCreate(
        email=new_email(), status=UserStatus.NOT_ACTIVE, last_name=TEST_LAST_NAME, mobile_phone_number=number
    )
    answer = _raw(client, "POST", "user", [("dryRun", "true")], data.to_payload())
    assert answer.get("mobilePhoneNumber") == number
    report.finding("P12", "Dry-Run mit mobilePhoneNumber im Format +49 151 …: akzeptiert, unverändert zurückgegeben")

    too_long = data.to_payload() | {"mobilePhoneNumber": "+49 " + "1" * 97}
    outcome = _rejection(lambda: _raw(client, "POST", "user", [("dryRun", "true")], too_long))
    assert outcome.startswith("abgewiesen")
    report.finding("P12", f"Dry-Run mit 101 Zeichen: {outcome}")


@pytest.fixture(name="list_definitions", scope="module")
def list_definitions_fixture(client: WeclappClient) -> list[CustomAttributeDefinition]:
    return client.custom_attribute_definitions.list(Filter.eq("attributeType", CustomAttributeType.LIST))


def test_selectable_values(report: IntegrationReport, list_definitions: list[CustomAttributeDefinition]) -> None:
    values = [value for definition in list_definitions for value in definition.selectable_values]
    assert all(value.id and value.value is not None for value in values)
    first_positions = sorted(
        {min(v.position_number or 0 for v in d.selectable_values) for d in list_definitions if d.selectable_values}
    )
    report.finding(
        "P13",
        f"{len(list_definitions)} LIST-Definitionen mit {len(values)} Auswahlwerten, alle mit id und value; "
        f"positionNumber beginnt bei {', '.join(map(str, first_positions)) or '-'}",
    )


def test_dry_run_selected_value(
    client: WeclappClient,
    report: IntegrationReport,
    new_email: Callable[[], str],
    verified_dry_run: None,
    list_definitions: list[CustomAttributeDefinition],
) -> None:
    definition = next((d for d in list_definitions if "user" in d.entities and d.selectable_values), None)
    if definition is None:
        pytest.skip("no list attribute with values for users")
    foreign = next((v.id for d in list_definitions if d.id != definition.id for v in d.selectable_values), None)

    def create(value_id: str) -> None:
        attribute = CustomAttribute.of_selection(definition.id, value_id)
        data = UserCreate(
            email=new_email(), status=UserStatus.NOT_ACTIVE, last_name=TEST_LAST_NAME, custom_attributes=[attribute]
        )
        client.users.create(data, dry_run=True)

    create(definition.selectable_values[0].id)
    report.finding("P13", "Dry-Run mit einem Auswahlwert der Definition: akzeptiert")
    for label, value_id in [("einer unbekannten id", "1"), ("dem Auswahlwert einer anderen Definition", foreign)]:
        if value_id is None:
            continue
        with pytest.raises(WeclappValidationError) as error_info:
            create(value_id)
        error = error_info.value
        detail = (error.detail or "").replace(value_id, "<id>")
        report.finding(
            "P13", f"Dry-Run mit {label}: abgewiesen ({detail}, {len(error.validation_errors)} validationErrors)"
        )

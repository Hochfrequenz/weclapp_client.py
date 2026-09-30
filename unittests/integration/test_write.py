"""
Tier 2: creates, changes and cleans up clearly marked test records (``WECLAPP_ALLOW_WRITES=1``).

In a production tenant, run these tests only after agreement: employees consume numbers of the employee number range,
and users can only be removed via ``softDelete``, which leaves records behind.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import pytest

from weclapp_client import Filter, OptimisticLockError, WeclappClient, WeclappValidationError
from weclapp_client._http import entity_path
from weclapp_client.models import (
    CustomAttribute,
    CustomAttributeDefinition,
    Employee,
    EmployeeCreate,
    EmployeeUpdate,
    User,
    UserCreate,
    UserStatus,
    UserUpdate,
)

from .conftest import TEST_LAST_NAME, Cleanup, IntegrationReport

pytestmark = pytest.mark.integration_write

_BIRTH_DATE = date(1950, 1, 1)
"""before 1970, so negative timestamps are covered as well"""


@dataclass(frozen=True)
class _TestRecords:
    user: User
    employee: Employee
    email: str
    personnel_number: str
    definition: CustomAttributeDefinition


@pytest.fixture(name="records", scope="module")
def records_fixture(
    client: WeclappClient,
    cleanup: Cleanup,
    new_email: Callable[[], str],
    run_id: str,
    personnel_number_definition: CustomAttributeDefinition,
    report: IntegrationReport,
) -> _TestRecords:
    email = new_email()
    personnel_number = f"IT-{run_id}"
    user = client.users.create(
        UserCreate(
            email=email,
            first_name=f"IT-{run_id}",
            last_name=TEST_LAST_NAME,
            status=UserStatus.NOT_ACTIVE,
            custom_attributes=[CustomAttribute.of_string(personnel_number_definition.id, personnel_number)],
        )
    )
    cleanup.add_user(user.id)
    employee = client.employees.create(EmployeeCreate(user_id=user.id, birth_date=_BIRTH_DATE))
    cleanup.add_employee(employee.id)
    report.manual(f"P2: im Test-Postfach prüfen, ob für {email} eine Mail angekommen ist")
    report.manual(f"P3: Personalakte {employee.id} in der Oberfläche öffnen und prüfen, ob sie nutzbar ist")
    report.manual(f"P5: in der Oberfläche prüfen, dass Personalakte {employee.id} den 01.01.1950 zeigt")
    return _TestRecords(user, employee, email, personnel_number, personnel_number_definition)


def test_user_is_created_as_not_active(records: _TestRecords, report: IntegrationReport) -> None:
    assert records.user.status is UserStatus.NOT_ACTIVE
    assert records.user.custom_attribute(records.definition.id) == CustomAttribute.of_string(
        records.definition.id, records.personnel_number
    )
    username = records.user.username or ""
    if username == records.email:
        convention = "entspricht der E-Mail-Adresse"
    elif username == records.email.lower():
        convention = "entspricht der E-Mail-Adresse in Kleinschreibung"
    else:
        convention = "wird anders gebildet (Beispiel ansehen)"
    report.finding("P2", "User mit status NOT_ACTIVE angelegt")
    report.finding("P4", f"username {convention}")


def test_employee_is_created_with_birth_date(
    client: WeclappClient, records: _TestRecords, report: IntegrationReport
) -> None:
    employee = client.employees.get(records.employee.id)
    assert employee.user_id == records.user.id
    assert employee.birth_date == _BIRTH_DATE
    raw = client._transport.request_json("GET", entity_path("employee", employee.id))
    offset_hours = (raw["birthDate"] % 86_400_000) / 3_600_000
    report.finding("P3", f"Personalakte für NOT_ACTIVE-User angelegt, employeeNumber {employee.employee_number!r}")
    report.finding("P5", f"vom Client geschriebenes Geburtsdatum kommt zurück mit Uhrzeit {offset_hours:g}:00 UTC")


def test_find_user_by_personnel_number(client: WeclappClient, records: _TestRecords, report: IntegrationReport) -> None:
    found = client.users.find_one(Filter.custom_attribute_eq(records.definition.id, records.personnel_number))
    assert found is not None
    assert found.id == records.user.id
    assert client.employees.for_user(records.user.id) is not None
    report.finding("P6", "neu angelegter User wird über die Personalnummer gefunden")


def test_partial_update_keeps_other_properties(
    client: WeclappClient, records: _TestRecords, report: IntegrationReport
) -> None:
    current = client.users.get(records.user.id)
    updated = client.users.update(current, UserUpdate(first_name=f"{current.first_name}-geändert"))
    assert updated.version != current.version
    assert updated.last_name == TEST_LAST_NAME
    assert updated.email == current.email
    assert updated.custom_attribute(records.definition.id) == current.custom_attribute(records.definition.id)
    report.finding("P7", "partielles PUT /user ändert nur die gesendeten Felder, customAttributes bleiben erhalten")


def test_custom_attribute_can_be_changed(client: WeclappClient, records: _TestRecords) -> None:
    current = client.users.get(records.user.id)
    new_value = f"{records.personnel_number}-2"
    changes = UserUpdate(custom_attributes=[CustomAttribute.of_string(records.definition.id, new_value)])
    updated = client.users.update(current, changes)
    attribute = updated.custom_attribute(records.definition.id)
    assert attribute is not None
    assert attribute.string_value == new_value
    restore = UserUpdate(custom_attributes=[CustomAttribute.of_string(records.definition.id, records.personnel_number)])
    client.users.update(updated, restore)


def test_employee_update(client: WeclappClient, records: _TestRecords, report: IntegrationReport) -> None:
    current = client.employees.get(records.employee.id)
    updated = client.employees.update(current, EmployeeUpdate(birth_date=date(1950, 1, 2)))
    assert updated.birth_date == date(1950, 1, 2)
    restored = client.employees.update(updated, EmployeeUpdate(birth_date=_BIRTH_DATE))
    assert restored.birth_date == _BIRTH_DATE
    report.finding("P7", "partielles PUT /employee funktioniert")


def test_stale_version_raises_optimistic_lock_error(
    client: WeclappClient, records: _TestRecords, report: IntegrationReport
) -> None:
    stale = client.users.get(records.user.id)
    client.users.update(stale, UserUpdate(first_name=f"{stale.first_name}-a"))
    with pytest.raises(OptimisticLockError) as error_info:
        client.users.update(stale, UserUpdate(first_name=f"{stale.first_name}-b"))
    report.finding("P10", f"409: problem_type={error_info.value.problem_type}")


def test_second_employee_for_the_same_user(
    client: WeclappClient, records: _TestRecords, cleanup: Cleanup, report: IntegrationReport
) -> None:
    try:
        duplicate = client.employees.create(EmployeeCreate(user_id=records.user.id))
    except WeclappValidationError:
        report.finding("P11", "zweite Personalakte für denselben User wird abgewiesen (wie im Fake angenommen)")
        return
    cleanup.add_employee(duplicate.id)
    report.finding("P11", "ACHTUNG: zweite Personalakte für denselben User ist möglich, FakeWeclapp anpassen")
    pytest.fail("weclapp allows several employees per user, the fake assumes the opposite")


@pytest.mark.parametrize("variant", ["same", "swapped_case"])
def test_duplicate_email_is_rejected(
    client: WeclappClient, records: _TestRecords, cleanup: Cleanup, report: IntegrationReport, variant: str
) -> None:
    email = records.email if variant == "same" else records.email.swapcase()
    try:
        duplicate = client.users.create(UserCreate(email=email, status=UserStatus.NOT_ACTIVE, last_name=TEST_LAST_NAME))
    except WeclappValidationError:
        report.finding("P4", f"doppelte E-Mail ({variant}) wird abgewiesen (wie im Fake angenommen)")
        return
    cleanup.add_user(duplicate.id)
    report.finding("P4", f"ACHTUNG: doppelte E-Mail ({variant}) ist möglich, FakeWeclapp anpassen")
    pytest.fail("weclapp accepts a duplicate e-mail address, the fake assumes the opposite")


def test_dry_run_create_stores_nothing(
    client: WeclappClient, new_email: Callable[[], str], report: IntegrationReport
) -> None:
    email = new_email()
    assert client.users.create(UserCreate(email=email, status=UserStatus.NOT_ACTIVE), dry_run=True) is None
    assert client.users.find_one(Filter.eq("email", email)) is None
    report.finding("P1", "Dry-Run beim Anlegen speichert nichts")

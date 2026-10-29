"""
Tier 2: creates one clearly marked test user with one employee record (``WECLAPP_ALLOW_WRITES=1``).

The run creates exactly these two records and changes nothing else; everything beyond that is checked with reads and
dry runs. That keeps it acceptable for a production tenant: an employee consumes a number of the employee number
range, and a user may leave a remnant in weclapp. The records are kept for the manual checks (mailbox, user
interface); remove them afterwards with the cleanup (``test_cleanup.py``).
"""

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import pytest

from weclapp_client import Filter, WeclappClient
from weclapp_client._converters import date_to_ms
from weclapp_client._http import entity_path
from weclapp_client.models import (
    CustomAttribute,
    CustomAttributeDefinition,
    Employee,
    EmployeeCreate,
    User,
    UserCreate,
    UserStatus,
)

from .conftest import ENV_USER_STATUS, TEST_LAST_NAME, IntegrationReport

pytestmark = pytest.mark.integration_write

_BIRTH_DATE = date(1950, 1, 1)
"""before 1970, so negative timestamps are covered as well"""
_ENTRY_DATE = date(2020, 4, 1)
_DAY_MS = 86_400_000
_HOUR_MS = 3_600_000


@dataclass(frozen=True)
class _TestRecords:
    user: User
    employee: Employee
    email: str
    personnel_number: str
    status: UserStatus
    definition: CustomAttributeDefinition


@pytest.fixture(name="records", scope="module")
def records_fixture(
    client: WeclappClient,
    new_email: Callable[[], str],
    run_id: str,
    personnel_number_definition: CustomAttributeDefinition,
    report: IntegrationReport,
) -> _TestRecords:
    status = UserStatus(os.environ.get(ENV_USER_STATUS, "").strip() or UserStatus.NOT_ACTIVE)
    email = new_email()
    personnel_number = f"IT-{run_id}"
    user = client.users.create(
        UserCreate(
            email=email,
            first_name=f"IT-{run_id}",
            last_name=TEST_LAST_NAME,
            status=status,
            custom_attributes=[CustomAttribute.of_string(personnel_number_definition.id, personnel_number)],
        )
    )
    report.cleanup.append(f"User {user.id} angelegt und behalten")
    employee = client.employees.create(EmployeeCreate(user_id=user.id, birth_date=_BIRTH_DATE, entry_date=_ENTRY_DATE))
    report.cleanup.append(f"Personalakte {employee.id} angelegt und behalten, aufräumen mit -m integration_cleanup")
    report.manual(f"P2: im Postfach von {email} prüfen, ob eine Mail von weclapp angekommen ist")
    report.manual(f"P3: Personalakte {employee.id} in der Oberfläche öffnen und prüfen, ob sie nutzbar ist")
    report.manual(
        f"P5: in der Oberfläche prüfen, dass Personalakte {employee.id} als Geburtsdatum den 01.01.1950 "
        "und als Eintrittsdatum den 01.04.2020 zeigt"
    )
    return _TestRecords(user, employee, email, personnel_number, status, personnel_number_definition)


def test_user_is_created(records: _TestRecords, report: IntegrationReport) -> None:
    assert records.user.status == records.status
    assert records.user.custom_attribute(records.definition.id) == CustomAttribute.of_string(
        records.definition.id, records.personnel_number
    )
    username = records.user.username or ""
    if username == records.email:
        convention = "gleich der E-Mail-Adresse, Groß-/Kleinschreibung bleibt erhalten"
    elif username == records.email.lower():
        convention = "gleich der E-Mail-Adresse in Kleinschreibung"
    else:
        convention = "anders gebildet (Beispiel ansehen)"
    report.finding("P2", f"User mit status {records.status} angelegt")
    report.finding("P4", f"username eines per API angelegten Users: {convention}")


def test_employee_is_created_with_dates(
    client: WeclappClient, records: _TestRecords, report: IntegrationReport
) -> None:
    employee = client.employees.get(records.employee.id)
    assert employee.user_id == records.user.id
    assert employee.birth_date == _BIRTH_DATE
    assert employee.entry_date == _ENTRY_DATE
    assert employee.employee_number
    raw = client._transport.request_json("GET", entity_path("employee", employee.id))
    times = {name: (raw[name] % _DAY_MS) / _HOUR_MS for name in ("birthDate", "entryDate")}
    report.finding("P3", f"Personalakte für einen User mit status {records.status} angelegt, employeeNumber vergeben")
    report.finding(
        "P5",
        "vom Client geschriebene Daten kommen zurück mit Uhrzeit "
        + ", ".join(f"{name} {hours:g}:00 UTC" for name, hours in times.items()),
    )


def test_find_user_by_personnel_number(client: WeclappClient, records: _TestRecords, report: IntegrationReport) -> None:
    found = client.users.find_one(Filter.custom_attribute_eq(records.definition.id, records.personnel_number))
    assert found is not None
    assert found.id == records.user.id
    assert client.employees.for_user(records.user.id) is not None
    report.finding("P6", "neu angelegter User wird über die Personalnummer gefunden")


def test_dry_run_partial_employee_update(
    client: WeclappClient, records: _TestRecords, report: IntegrationReport
) -> None:
    current = client.employees.get(records.employee.id)
    body = {"version": current.version, "birthDate": date_to_ms(date(1950, 1, 2))}
    params = [("ignoreMissingProperties", "true"), ("dryRun", "true")]
    response = client._transport.request_json("PUT", entity_path("employee", current.id), params=params, json_body=body)
    assert response.get("birthDate") == date_to_ms(date(1950, 1, 2))
    assert response.get("userId") == records.user.id, "ignoreMissingProperties=true is not honoured"
    assert response.get("entryDate") == date_to_ms(_ENTRY_DATE), "ignoreMissingProperties=true is not honoured"
    assert client.employees.get(current.id).birth_date == _BIRTH_DATE, "the dry run stored the change"
    report.finding("P7", "ignoreMissingProperties=true bei PUT /employee: nicht gesendete Felder bleiben erhalten")

"""
Integration tests against a real weclapp tenant (implementation plan, AP 6). See docs/integrationstests.md.

Two tiers:

- ``integration``: only reads and dry runs, safe for a production tenant.
- ``integration_write``: creates, changes and cleans up clearly marked test records; additionally needs
  ``WECLAPP_ALLOW_WRITES=1``.

Without ``WECLAPP_API_TOKEN`` and ``WECLAPP_BASE_URL``/``WECLAPP_TENANT`` all tests are skipped (e.g. in CI).

The tests must not output personal data: assertions only compare ids, counts and flags, and the summary at the end
only contains structural findings.
"""

import itertools
import os
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

import pytest

from weclapp_client import WeclappClient, WeclappConfig, WeclappError
from weclapp_client._http import entity_path
from weclapp_client.config import ENV_API_TOKEN, ENV_BASE_URL, ENV_TENANT
from weclapp_client.exceptions import CustomAttributeDefinitionError
from weclapp_client.models import CustomAttributeDefinition, CustomAttributeType

ENV_ALLOW_WRITES = "WECLAPP_ALLOW_WRITES"
ENV_PERSONNEL_NUMBER_KEY = "WECLAPP_IT_PERSONNEL_NUMBER_KEY"
ENV_EMAIL_TEMPLATE = "WECLAPP_IT_EMAIL_TEMPLATE"
DEFAULT_PERSONNEL_NUMBER_KEY = "personalnummer"
DEFAULT_EMAIL_TEMPLATE = "weclapp-client-it+{id}@example.com"
TEST_LAST_NAME = "ZZ-Test weclapp-client"
"""last name of all test records, so they can be found (and removed) in weclapp"""


def _is_configured() -> bool:
    has_token = bool(os.environ.get(ENV_API_TOKEN, "").strip())
    has_target = bool(os.environ.get(ENV_BASE_URL, "").strip() or os.environ.get(ENV_TENANT, "").strip())
    return has_token and has_target


def _writes_allowed() -> bool:
    return os.environ.get(ENV_ALLOW_WRITES, "").strip().lower() in {"1", "true", "yes"}


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    not_configured = pytest.mark.skip(reason=f"{ENV_API_TOKEN} and {ENV_BASE_URL} or {ENV_TENANT} are not set")
    no_writes = pytest.mark.skip(reason=f"write tests need {ENV_ALLOW_WRITES}=1")
    for item in items:
        is_read = item.get_closest_marker("integration") is not None
        is_write = item.get_closest_marker("integration_write") is not None
        if (is_read or is_write) and not _is_configured():
            item.add_marker(not_configured)
        elif is_write and not _writes_allowed():
            item.add_marker(no_writes)


@dataclass
class IntegrationReport:
    """Collects the findings of a run; printed at the end of the pytest output."""

    findings: list[tuple[str, str]] = field(default_factory=list)
    manual_checks: list[str] = field(default_factory=list)
    cleanup: list[str] = field(default_factory=list)

    def finding(self, check: str, text: str) -> None:
        """Adds a finding for a check point of the plan (e.g. ``"P5"``); ``text`` must not contain personal data."""
        self.findings.append((check, text))

    def manual(self, text: str) -> None:
        if text not in self.manual_checks:
            self.manual_checks.append(text)


REPORT = IntegrationReport()


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    if not (REPORT.findings or REPORT.manual_checks or REPORT.cleanup):
        return
    terminalreporter.section("weclapp: Ergebnisse der Prüfpunkte (AP 6)")
    for check, text in sorted(REPORT.findings, key=lambda finding: int(finding[0].removeprefix("P"))):
        terminalreporter.write_line(f"{check}: {text}")
    if REPORT.manual_checks:
        terminalreporter.write_line("")
        terminalreporter.write_line("Noch manuell zu prüfen:")
        for text in REPORT.manual_checks:
            terminalreporter.write_line(f"  - {text}")
    if REPORT.cleanup:
        terminalreporter.write_line("")
        terminalreporter.write_line("Aufräumen der Testdatensätze:")
        for text in REPORT.cleanup:
            terminalreporter.write_line(f"  - {text}")


@pytest.fixture(name="report", scope="session")
def report_fixture() -> IntegrationReport:
    return REPORT


@pytest.fixture(name="client", scope="session")
def client_fixture() -> Iterator[WeclappClient]:
    with WeclappClient(WeclappConfig.from_env()) as client:
        yield client


@pytest.fixture(name="run_id", scope="session")
def run_id_fixture() -> str:
    """identifies the test records of this run"""
    return uuid.uuid4().hex[:8]


@pytest.fixture(name="new_email", scope="session")
def new_email_fixture(run_id: str) -> Callable[[], str]:
    """Returns a function that creates a new, unique e-mail address for a test record."""
    template = os.environ.get(ENV_EMAIL_TEMPLATE, "").strip() or DEFAULT_EMAIL_TEMPLATE
    if "{id}" not in template:
        raise ValueError(f"{ENV_EMAIL_TEMPLATE} must contain the placeholder {{id}}")
    counter = itertools.count(1)
    return lambda: template.format(id=f"{run_id}-{next(counter)}")


@pytest.fixture(name="personnel_number_definition", scope="session")
def personnel_number_definition_fixture(client: WeclappClient) -> CustomAttributeDefinition:
    key = os.environ.get(ENV_PERSONNEL_NUMBER_KEY, "").strip() or DEFAULT_PERSONNEL_NUMBER_KEY
    try:
        return client.custom_attribute_definitions.get_by_key(key, expected_type=CustomAttributeType.STRING)
    except CustomAttributeDefinitionError as error:
        pytest.skip(f"Custom attribute for the personnel number is not set up: {error}")


class Cleanup:
    """
    Removes the test records at the end of the session: employees via ``DELETE``, users via ``softDelete``
    (weclapp v2 cannot delete users). These operations are not part of the public client API.
    """

    def __init__(self, client: WeclappClient) -> None:
        self._client = client
        self._employee_ids: list[str] = []
        self._user_ids: list[str] = []

    def add_employee(self, employee_id: str) -> None:
        self._employee_ids.append(employee_id)

    def add_user(self, user_id: str) -> None:
        self._user_ids.append(user_id)

    def run(self) -> None:
        transport = self._client._transport
        for employee_id in reversed(self._employee_ids):
            try:
                transport.request("DELETE", entity_path("employee", employee_id))
                REPORT.cleanup.append(f"Employee {employee_id}: gelöscht")
            except WeclappError as error:
                REPORT.cleanup.append(f"Employee {employee_id}: NICHT gelöscht ({type(error).__name__})")
        for user_id in reversed(self._user_ids):
            try:
                transport.request("POST", entity_path("user", user_id) + "/softDelete", json_body={})
                REPORT.cleanup.append(f"User {user_id}: per softDelete entfernt (Rest bleibt in weclapp)")
            except WeclappError as error:
                REPORT.cleanup.append(f"User {user_id}: NICHT entfernt ({type(error).__name__})")


@pytest.fixture(name="cleanup", scope="session")
def cleanup_fixture(client: WeclappClient) -> Iterator[Cleanup]:
    tracker = Cleanup(client)
    yield tracker
    tracker.run()

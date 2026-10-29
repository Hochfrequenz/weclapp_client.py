"""
Removes the test records of tier 2 after the manual checks (``WECLAPP_ALLOW_WRITES=1`` and ``WECLAPP_IT_CLEANUP=1``).

Test records are the users with the last name ``ZZ-Test weclapp-client`` and their employee records. Employee records
are deleted. API v2 can only soft-delete users, which leaves a remnant in weclapp, so the cleanup first tries the
``DELETE`` of API v1 (as a dry run, then for real) and falls back to ``softDelete`` if weclapp refuses.
"""

from collections.abc import Iterator

import pytest

from weclapp_client import Filter, NotFoundError, WeclappApiError, WeclappClient, WeclappConfig
from weclapp_client._http import HttpTransport, entity_path

from .conftest import TEST_LAST_NAME, IntegrationReport

pytestmark = pytest.mark.integration_cleanup

_MAX_TEST_USERS = 5
"""more test users than this hints at a problem (e.g. an ignored filter); then nothing is removed"""


@pytest.fixture(name="v1_transport")
def v1_transport_fixture() -> Iterator[HttpTransport]:
    config = WeclappConfig.from_env()
    if "/api/v2/" not in config.base_url:
        pytest.skip("the base URL does not point to API v2, so the URL of API v1 is unknown")
    v1_config = config.model_copy(update={"base_url": config.base_url.replace("/api/v2/", "/api/v1/")})
    with WeclappClient(v1_config) as v1_client:
        yield v1_client._transport


def _remove_user(client: WeclappClient, v1_transport: HttpTransport, user_id: str) -> str:
    path = entity_path("user", user_id)
    try:
        v1_transport.request("DELETE", path, params=[("dryRun", "true")])
        v1_transport.request("DELETE", path)
    except NotFoundError:
        return "mit DELETE (API v1) gelöscht, schon beim Dry-Run"
    except WeclappApiError as error:
        refused = f"DELETE (API v1) abgewiesen (HTTP {error.status_code}, {error.problem_type}: {error.detail})"
    else:
        try:
            client.users.get(user_id)
        except NotFoundError:
            return "mit DELETE (API v1) vollständig gelöscht"
        refused = "DELETE (API v1) ohne Fehler, aber der User ist noch abrufbar"
    client._transport.request("POST", f"{path}/softDelete", json_body={})
    return f"{refused}; per softDelete entfernt, ein Rest bleibt in weclapp"


def test_remove_test_records(client: WeclappClient, v1_transport: HttpTransport, report: IntegrationReport) -> None:
    candidates = client.users.list(Filter.eq("lastName", TEST_LAST_NAME), properties=["lastName"])
    users = [user for user in candidates if user.last_name == TEST_LAST_NAME]
    assert len(users) == len(candidates), "the filter on lastName returned other users, nothing was removed"
    assert len(users) <= _MAX_TEST_USERS, f"{len(users)} test users found, nothing was removed"
    if not users:
        report.cleanup.append("keine Testdatensätze gefunden")
        return
    for user in users:
        for employee in client.employees.list(Filter.eq("userId", user.id), properties=["userId"]):
            client._transport.request("DELETE", entity_path("employee", employee.id))
            report.cleanup.append(f"Personalakte {employee.id}: gelöscht")
        report.cleanup.append(f"User {user.id}: {_remove_user(client, v1_transport, user.id)}")

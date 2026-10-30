# weclapp-client

![Unittests status badge](https://github.com/Hochfrequenz/weclapp_client.py/workflows/Unittests/badge.svg)
![Coverage status badge](https://github.com/Hochfrequenz/weclapp_client.py/workflows/Coverage/badge.svg)
![Linting status badge](https://github.com/Hochfrequenz/weclapp_client.py/workflows/Linting/badge.svg)
![Formatting status badge](https://github.com/Hochfrequenz/weclapp_client.py/workflows/Formatting/badge.svg)

A typed Python client for the [weclapp REST API v2](https://www.weclapp.com/api/).
It deliberately covers only the endpoints needed to synchronise employee master data into weclapp:
`/user`, `/employee`, `/customAttributeDefinition`, `/workScheduleProfile` and `/user/currentUser`.

The synchronisation logic itself (matching, diffing, reporting) lives in a separate repository that uses this package
as a dependency.

> **Status:** early `0.x` version. The client is fully tested against mocks and an in-memory fake and has been
> checked against a real weclapp tenant with reads and dry runs. A test that creates records is still pending
> ([#9](https://github.com/Hochfrequenz/weclapp_client.py/issues/9)), so the API may still change. See the [implementation plan](https://github.com/Hochfrequenz/weclapp_client.py/blob/main/docs/umsetzungsplan.md)
> and the [API analysis](https://github.com/Hochfrequenz/weclapp_client.py/blob/main/docs/weclapp_api_analyse.md)
> (both German) and the [open issues](https://github.com/Hochfrequenz/weclapp_client.py/issues).

## Installation

The releases are pre-releases (`0.1.0a1`, `0.1.0a2`, ...): the client has been checked against a real weclapp tenant
with reads and dry runs, but creating records has not been tested there yet. pip and uv only install pre-releases if the
version specifier names one:

```bash
uv add "weclapp-client>=0.1.0a1,<0.2"
```

or `pip install "weclapp-client>=0.1.0a1,<0.2"`. Once `0.1.0` is released, the same specifier picks it up.
As long as the version is `0.x`, minor versions may contain breaking changes, so keep the upper bound.

## Usage

```python
from datetime import date
from decimal import Decimal

from weclapp_client import Filter, WeclappClient, WeclappConfig
from weclapp_client.models import (
    CustomAttribute,
    EmployeeCreate,
    IdReference,
    UserCreate,
    UserStatus,
    WorkScheduleProfileAssignment,
)

# the ids of custom attributes, list values, user roles and work schedule profiles differ from tenant to tenant
PERSONNEL_NUMBER_ATTRIBUTE_ID, COST_RATE_ATTRIBUTE_ID = "1001", "1002"
STATE_ATTRIBUTE_ID, TIME_TRACKING_ROLE_ID, FULL_TIME_PROFILE_ID = "1003", "1004", "1005"

# reads WECLAPP_API_TOKEN and WECLAPP_BASE_URL (or WECLAPP_TENANT)
with WeclappClient(WeclappConfig.from_env()) as client:
    definition = client.custom_attribute_definitions.get(PERSONNEL_NUMBER_ATTRIBUTE_ID)
    user = client.users.find_one(Filter.custom_attribute_eq(definition.id, "00042"))
    if user is None:
        state = client.custom_attribute_definitions.get(STATE_ATTRIBUTE_ID)
        bavaria = next(value for value in state.selectable_values if value.value == "Bayern")
        user = client.users.create(
            UserCreate(
                email="erika.musterfrau@example.com",
                first_name="Erika",
                last_name="Musterfrau",
                mobile_phone_number="+49 151 12345678",
                status=UserStatus.ACTIVE,
                licenses=["WECLAPP_PROJECT"],
                user_roles=[IdReference(id=TIME_TRACKING_ROLE_ID)],
                custom_attributes=[
                    CustomAttribute.of_string(definition.id, "00042"),
                    CustomAttribute.of_number(COST_RATE_ATTRIBUTE_ID, Decimal("59")),
                    CustomAttribute.of_selection(state.id, bavaria.id),
                ],
            )
        )
    if client.employees.for_user(user.id) is None:
        full_time = WorkScheduleProfileAssignment(work_schedule_profile_id=FULL_TIME_PROFILE_ID, start_date=date(2026, 11, 1))
        client.employees.create(EmployeeCreate(user_id=user.id, work_schedule_profile_assignments=[full_time]))
```

- `iterate()`/`list()` page through all entities; `properties=[...]` loads only the given properties
  (`id` and `version` are always included).
- `find_one()` returns `None` if nothing matches and raises `AmbiguousResultError` if more than one entity matches.
  weclapp does not require unique e-mail addresses, so a lookup by e-mail can match several users.
- `get_by_key()` needs the key of the custom attribute. weclapp may generate it (a random string) when the attribute
  is created in the user interface; in that case, load the definition by its id with `get()`.
- `create()` and `update()` accept `dry_run=True`: weclapp validates the data without storing it, and the method
  returns `None` (weclapp does not assign ids in dry runs).
- weclapp assigns the `username` of a user itself; it is read-only and usually equals the e-mail address.
- weclapp stores `mobile_phone_number` as sent, without checking or normalising the format (at most 100 characters).
- `CustomAttributeDefinition.selectable_values` lists the values of a `LIST` attribute with id and label (`value`).
  weclapp rejects the id of a value that belongs to another attribute.
- The entry date of an employee is usually the start date of the first work schedule profile
  (`Employee.work_schedule_profile_assignments`); `entry_date` is often empty. `client.work_schedule_profiles` lists
  the profiles with their weekly working time, e.g. to check configured profile ids.
- Read models (`User`, `Employee`, ...) guarantee `id` and `version`. Write models (`UserCreate`, `UserUpdate`, ...)
  only contain writable properties.

### Behaviour guarantees

- **A `POST` is not retried if its outcome is unclear** (read timeout, HTTP 502–504), because the entity might
  already exist. Look up an entity before creating it, so that a repeated run does not create duplicates.
  `429 Too Many Requests` and failed connection attempts are retried for all methods, `GET`/`PUT` also on
  gateway errors and timeouts (exponential backoff with jitter, `max_retries` in `WeclappConfig`).
- **Updates are partial** (`ignoreMissingProperties=true`) and send the `version` of the entity passed in. If the
  entity changed in the meantime, `OptimisticLockError` is raised: read it again and re-apply the changes.
- **Custom attributes:** an update only sends the attributes passed in; weclapp keeps the values of all others.
- **Filters are checked before a request is sent.** weclapp silently ignores filters on unknown properties, which
  would turn a lookup into a query for all entities; the client raises `InvalidQueryError` instead.
- **No personal data in logs:** the logger `weclapp_client` only logs method, path and status. The API token never
  appears in logs, `repr` or exceptions.
- Unknown properties in responses are ignored, unknown enum values are kept as strings.
- **Date-only fields** (`birth_date`, `entry_date`, the dates of work schedule profiles) are written as midnight
  German time (Europe/Berlin), like the weclapp user interface stores them; weclapp rejects anything else as the start
  date of a work schedule profile. When reading, timestamps are rounded to the nearest midnight, so dates stored as
  midnight UTC are read correctly as well. Filters with a `date` (e.g. `Filter.eq("birthDate", date(1985, 4, 12))`)
  match both forms.

### Exceptions

All exceptions derive from `WeclappError`. Errors returned by weclapp derive from `WeclappApiError`
(with `status_code`, `problem_type`, `detail` and `validation_errors`).

| Exception                  | Cause                                           | Typically                   |
|----------------------------|-------------------------------------------------|-----------------------------|
| `WeclappConnectionError`   | network error or timeout after all retries      | systemic, abort the run     |
| `AuthenticationError`      | HTTP 401, invalid token                         | systemic                    |
| `PermissionDeniedError`    | HTTP 403                                        | systemic                    |
| `RateLimitError`           | HTTP 429 after all retries                      | systemic                    |
| `ServerError`              | HTTP 5xx                                        | systemic                    |
| `WeclappValidationError`   | HTTP 400, see `validation_errors`               | concerns one record         |
| `NotFoundError`            | HTTP 404                                        | concerns one record         |
| `OptimisticLockError`      | HTTP 409, entity changed in the meantime        | concerns one record, retry  |
| `ConflictError`            | other HTTP 409                                  | concerns one record         |
| `InvalidQueryError`        | unknown property in a filter, sort or selection | programming error           |
| `AmbiguousResultError`     | `find_one()` matched several entities           | data problem                |

## Testing without a weclapp tenant

`weclapp_client.testing.FakeWeclapp` is an in-memory fake of the endpoints above. It assigns ids, versions, usernames
and employee numbers, evaluates filters, sorting and paging, merges custom attributes in partial updates, detects stale
versions (`OptimisticLockError`), validates required, read-only and unknown properties and supports dry runs.

```python
from datetime import date

import httpx

from weclapp_client.testing import FakeWeclapp


def test_employee_is_created() -> None:
    fake = FakeWeclapp()
    definition = fake.add_custom_attribute_definition(attribute_key="personalnummer")
    fake.add_user(email="max@example.com", last_name="Mustermann", custom_attributes={definition.id: "00007"})

    with fake.client() as client:
        run_sync(client, records)  # the code under test

    assert [user.last_name for user in fake.users] == ["Mustermann", "Musterfrau"]
    assert fake.employees[-1].birth_date == date(1985, 4, 12)


def test_second_run_changes_nothing() -> None:
    fake = FakeWeclapp()
    ...
    fake.clear_requests()
    with fake.client() as client:
        run_sync(client, records)
    assert fake.write_requests == []


def test_timeout_while_creating_an_employee() -> None:
    fake = FakeWeclapp()
    fake.fail_next(exception=httpx.ReadTimeout("timeout"), method="POST", path="employee")
    ...
```

- `add_user()`, `add_employee()`, `add_custom_attribute_definition()` and `add_work_schedule_profile()` arrange test
  data without validation, so inconsistent states (e.g. duplicate personnel numbers) can be tested as well. Like
  weclapp, the fake rejects employees with an unknown work schedule profile, so add the profiles your code uses.
  `add_custom_attribute_definition(attribute_type=CustomAttributeType.LIST, selectable_values=["Bayern", ...])` adds
  a list attribute; like weclapp, the fake then rejects the id of any value that does not belong to it.
- `users`, `employees`, `requests` and `write_requests` show the state and the requests received.
- `fail_next()` lets the next matching request fail with a status code or an exception.
- Like weclapp, the fake accepts several users with the same e-mail address, so check for an existing user yourself
  before creating one. A user has at most one employee.

## Development

This project uses [uv](https://docs.astral.sh/uv/) to manage the Python interpreter, the virtual environment and the
dependencies. Create the dev environment with:

```bash
uv sync --group dev
```

The checks that run in CI:

```bash
uv run pytest
uv run ruff check src/weclapp_client unittests
uv run ruff format --check .
uv run mypy --show-error-codes src/weclapp_client --strict
uv run mypy --show-error-codes unittests --strict
uv run codespell --ignore-words=domain-specific-terms.txt src README.md
```

Integration tests against a real weclapp tenant live in `unittests/integration/` and are skipped unless
`WECLAPP_API_TOKEN` and `WECLAPP_BASE_URL` (or `WECLAPP_TENANT`) are set. Tests marked `integration` only read and
send dry runs; tests marked `integration_write` create one test user with an employee record and additionally need
`WECLAPP_ALLOW_WRITES=1`. The records are kept for manual checks; `integration_cleanup` removes them afterwards and
also needs `WECLAPP_IT_CLEANUP=1`.
See [docs/integrationstests.md](https://github.com/Hochfrequenz/weclapp_client.py/blob/main/docs/integrationstests.md)
(German).

## Releasing

Versions are derived from git tags (`v0.1.0`, `v0.1.1`, ...) via hatch-vcs. Publishing a GitHub release with a `v*` tag
runs [`python-publish.yml`](https://github.com/Hochfrequenz/weclapp_client.py/blob/main/.github/workflows/python-publish.yml),
which tests, builds and uploads the package to PyPI via trusted publishing.

One-time setup:

1. Create a GitHub environment named `release`. If its deployment branches are restricted, add a rule of type *Tag*
   matching `v*`, because a release deploys from the tag, not from a branch.
2. Register the trusted publisher on PyPI (project `weclapp-client`, owner `Hochfrequenz`,
   repository `weclapp_client.py`, workflow `python-publish.yml`, environment `release`). For the first release,
   this is a "pending publisher", because the project does not exist on PyPI yet.

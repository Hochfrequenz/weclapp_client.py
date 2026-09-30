# weclapp-client

![Unittests status badge](https://github.com/Hochfrequenz/weclapp_client.py/workflows/Unittests/badge.svg)
![Coverage status badge](https://github.com/Hochfrequenz/weclapp_client.py/workflows/Coverage/badge.svg)
![Linting status badge](https://github.com/Hochfrequenz/weclapp_client.py/workflows/Linting/badge.svg)
![Formatting status badge](https://github.com/Hochfrequenz/weclapp_client.py/workflows/Formatting/badge.svg)

A typed Python client for the [weclapp REST API v2](https://www.weclapp.com/api/).
It deliberately covers only the endpoints needed to synchronise employee master data into weclapp:
`/user`, `/employee`, `/customAttributeDefinition` and `/user/currentUser`.

The synchronisation logic itself (matching, diffing, reporting) lives in a separate repository that uses this package
as a dependency.

> **Status:** under development, see the [implementation plan](docs/umsetzungsplan.md) (German).
> The [API analysis](docs/weclapp_api_analyse.md) (German) explains which endpoints are relevant and why.

## Installation

The package is not released yet. Once it is, install it from PyPI:

```bash
uv add weclapp-client
```

Until then, a pre-release can be installed from a git tag:

```bash
uv add "weclapp-client @ git+https://github.com/Hochfrequenz/weclapp_client.py@v0.1.0a1"
```

## Usage

```python
from datetime import date

from weclapp_client import Filter, WeclappClient, WeclappConfig
from weclapp_client.models import CustomAttribute, EmployeeCreate, EmployeeUpdate, UserCreate, UserStatus

# reads WECLAPP_API_TOKEN and WECLAPP_BASE_URL (or WECLAPP_TENANT)
with WeclappClient(WeclappConfig.from_env()) as client:
    definition = client.custom_attribute_definitions.get_by_key("personalnummer")
    user = client.users.find_one(Filter.custom_attribute_eq(definition.id, "00042"))
    if user is None:
        user = client.users.create(
            UserCreate(
                email="erika.musterfrau@example.com",
                first_name="Erika",
                last_name="Musterfrau",
                status=UserStatus.NOT_ACTIVE,
                custom_attributes=[CustomAttribute.of_string(definition.id, "00042")],
            )
        )
    employee = client.employees.for_user(user.id)
    if employee is None:
        client.employees.create(EmployeeCreate(user_id=user.id, birth_date=date(1985, 4, 12)))
    elif employee.birth_date != date(1985, 4, 12):
        client.employees.update(employee, EmployeeUpdate(birth_date=date(1985, 4, 12)))
```

- `iterate()`/`list()` page through all entities; `properties=[...]` loads only the given properties
  (`id` and `version` are always included).
- `find_one()` returns `None` if nothing matches and raises `AmbiguousResultError` if more than one entity matches.
- `create()` and `update()` accept `dry_run=True`: weclapp validates the data without storing it, and the method
  returns `None` (weclapp does not assign ids in dry runs).
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
- Date-only fields (e.g. `birth_date`) are written as midnight UTC; when reading, timestamps are rounded to the
  nearest midnight, so dates stored at local midnight (e.g. Europe/Berlin) are read correctly.

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

- `add_user()`, `add_employee()` and `add_custom_attribute_definition()` arrange test data without validation, so
  inconsistent states (e.g. duplicate personnel numbers) can be tested as well.
- `users`, `employees`, `requests` and `write_requests` show the state and the requests received.
- `fail_next()` lets the next matching request fail with a status code or an exception.
- Some rules of the fake are assumptions until they are verified against a real tenant: e-mail addresses are unique
  (case-insensitive) and a user has at most one employee.

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
send dry runs; tests marked `integration_write` create test records and additionally need `WECLAPP_ALLOW_WRITES=1`.
See [docs/integrationstests.md](docs/integrationstests.md) (German).

## Releasing

Versions are derived from git tags (`v0.1.0`, `v0.1.0a1`, ...) via hatch-vcs.
Publishing to PyPI uses trusted publishing via [`.github/workflows/python-publish.yml`](.github/workflows/python-publish.yml),
which still needs to be activated:

1. Uncomment the workflow.
2. Create a GitHub environment named `release`. If its deployment branches are restricted, add a rule of type *Tag*
   matching `v*`, because a release deploys from the tag, not from a branch.
3. Register the trusted publisher on PyPI (project `weclapp-client`, owner `Hochfrequenz`,
   repository `weclapp_client.py`, workflow `python-publish.yml`, environment `release`).
4. Create a GitHub release with a `v*` tag.

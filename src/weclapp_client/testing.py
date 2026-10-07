"""
In-memory fake of the weclapp endpoints used by this client, for tests without a weclapp tenant.

The fake implements ``/user``, ``/employee``, ``/customAttributeDefinition`` and ``/user/currentUser`` as an
``httpx.MockTransport`` and mimics the behaviour of the real API where it matters for synchronisation logic:

- ids, ``version`` (incremented with every change), ``createdDate``/``lastModifiedDate``, ``username`` and
  ``employeeNumber`` are assigned by the fake
- filters (``eq``, ``ne``, ``lt``, ``le``, ``gt``, ``ge``, ``like``, ``ilike``, ``in``, ``notin``, ``null``,
  ``notnull``, ``customAttribute<id>-eq``), ``sort``, ``properties`` and paging; like weclapp, it silently ignores
  filters on unknown properties
- partial updates (``ignoreMissingProperties=true``) merge ``customAttributes`` per attribute; a stale ``version``
  is answered with ``409 optimistic_lock``
- validation: missing required properties, read-only or unknown properties, duplicate e-mail addresses, a second
  employee for the same user and references to unknown users are answered with ``400``
- ``dryRun=true`` validates without storing and answers without meta properties

Some rules are assumptions until they are verified against a real tenant (see the implementation plan, AP 6):
e-mail addresses are unique (case-insensitive) and every user has at most one employee.

Example::

    fake = FakeWeclapp()
    definition = fake.add_custom_attribute_definition(attribute_key="personalnummer")
    with fake.client() as client:
        run_sync(client, records)
    assert [user.last_name for user in fake.users] == ["Musterfrau"]
"""

import copy
import itertools
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from pydantic import SecretStr
from pydantic.alias_generators import to_camel

from weclapp_client._converters import date_to_ms, datetime_to_ms
from weclapp_client.client import WeclappClient
from weclapp_client.config import WeclappConfig
from weclapp_client.models import CustomAttributeDefinition, CustomAttributeType, Employee, User, UserStatus
from weclapp_client.resources.custom_attribute_definitions import CustomAttributeDefinitionsResource
from weclapp_client.resources.employees import EmployeesResource
from weclapp_client.resources.users import UsersResource

__all__ = ["BASE_URL", "DEFAULT_API_TOKEN", "FakeWeclapp", "RecordedRequest"]

BASE_URL = "https://fake.weclapp.test/webapp/api/v2/"
"""base URL of the fake; requests to other hosts are not routed to it"""
DEFAULT_API_TOKEN = "fake-api-token"

_PATH_PREFIX = "/webapp/api/v2/"
_ERROR_TYPE = "/webapp/view/api/errors.html#!/errors/"
_VALIDATION_TYPE = "/webapp/view/api/errors.html#!/validation/"
_META_PROPERTIES = frozenset({"id", "version", "createdDate", "lastModifiedDate"})
_OPERATORS = frozenset(
    {"eq", "ne", "lt", "le", "gt", "ge", "like", "notlike", "ilike", "notilike", "in", "notin", "null", "notnull"}
)
_RESERVED_PARAMETERS = frozenset(
    {
        "page",
        "pageSize",
        "offset",
        "sort",
        "orderBy",
        "properties",
        "filter",
        "serializeNulls",
        "includeReferencedEntities",
        "additionalProperties",
        "dryRun",
        "ignoreMissingProperties",
    }
)
_CUSTOM_ATTRIBUTE_FILTER = re.compile(r"^customAttribute([0-9A-Za-z_]+)$")
_USER_PROPERTIES_ON_EMPLOYEE = frozenset({"email", "firstName", "lastName", "title"})
_MAX_PAGE_SIZE = 1000
_DEFAULT_PAGE_SIZE = 100


@dataclass(frozen=True)
class _ResourceRules:
    known: frozenset[str]
    read_only: frozenset[str]
    required: frozenset[str]
    filterable: frozenset[str]
    defaults: Mapping[str, Any]
    writable_via_api: bool = True

    @property
    def writable(self) -> frozenset[str]:
        return self.known - self.read_only


_RULES: Mapping[str, _ResourceRules] = {
    "user": _ResourceRules(
        known=UsersResource.known_properties,
        read_only=frozenset({"createdDate", "id", "imageId", "lastModifiedDate", "superUser", "username", "version"}),
        required=frozenset({"email", "status"}),
        filterable=UsersResource.filterable_properties,
        defaults={
            "canEditDashboard": False,
            "customAttributes": [],
            "licenses": [],
            "userRoles": [],
            "superUser": False,
        },
    ),
    "employee": _ResourceRules(
        known=EmployeesResource.known_properties,
        read_only=frozenset({"createdDate", "employeeNumber", "id", "lastModifiedDate", "version"}),
        required=frozenset({"userId"}),
        filterable=EmployeesResource.filterable_properties,
        defaults={},
    ),
    "customAttributeDefinition": _ResourceRules(
        known=CustomAttributeDefinitionsResource.known_properties,
        read_only=frozenset({"createdDate", "id", "lastModifiedDate", "systemCustomAttribute", "version"}),
        required=frozenset({"attributeKey", "attributeType"}),
        filterable=CustomAttributeDefinitionsResource.filterable_properties,
        defaults={},
        writable_via_api=False,
    ),
}


@dataclass(frozen=True)
class RecordedRequest:
    """A request received by the fake."""

    method: str
    path: str
    """path relative to the base URL, e.g. ``user/id/1000``"""
    params: tuple[tuple[str, str], ...]
    body: Any
    """the decoded JSON body, ``None`` if there was none"""

    @property
    def is_dry_run(self) -> bool:
        return ("dryRun", "true") in self.params

    @property
    def is_write(self) -> bool:
        """``True`` for requests that change data (``POST``/``PUT``/``DELETE`` without ``dryRun``)."""
        return self.method in {"POST", "PUT", "DELETE"} and not self.is_dry_run


@dataclass
class _Failure:
    method: str | None
    path: str | None
    status_code: int
    exception: Exception | None
    remaining: int

    def matches(self, method: str, path: str) -> bool:
        method_matches = self.method is None or self.method == method
        path_matches = self.path is None or path == self.path or path.startswith(self.path + "/")
        return method_matches and path_matches


class _InvalidBody:
    """marker for a request body that is not valid JSON"""


_INVALID_BODY = _InvalidBody()


def _problem(status: int, problem_type: str, title: str, *, issues: Sequence[Mapping[str, str]] = ()) -> httpx.Response:
    body: dict[str, Any] = {"status": status, "title": title, "type": _ERROR_TYPE + problem_type, "detail": title}
    if issues:
        body["validationErrors"] = list(issues)
    return httpx.Response(status, json=body)


def _issue(location: str, kind: str, title: str) -> dict[str, str]:
    return {"location": location, "type": _VALIDATION_TYPE + kind, "title": title, "detail": title}


def _validation_failed(issues: Sequence[Mapping[str, str]]) -> httpx.Response:
    return _problem(400, "validation", "validation failed", issues=issues)


def _without_nulls(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _without_nulls(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_without_nulls(item) for item in value]
    return value


def _normalize(value: Any) -> Any:
    """weclapp interprets empty strings (also whitespace only) as ``null``"""
    if isinstance(value, str) and not value.strip():
        return None
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


def _coerce(raw: str, like: Any) -> Any:
    if isinstance(like, bool):
        return raw.lower() == "true"
    if isinstance(like, int):
        return int(raw)
    if isinstance(like, float):
        return float(raw)
    return raw


def _as_parameter(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _pattern_matches(actual: Any, pattern: str, ignore_case: bool) -> bool:
    regex = "".join(".*" if char == "%" else "." if char == "_" else re.escape(char) for char in pattern)
    return re.fullmatch(regex, str(actual), re.IGNORECASE | re.DOTALL if ignore_case else re.DOTALL) is not None


def _condition_matches(actual: Any, operator: str, raw: str) -> bool:
    if operator == "null":
        return actual is None
    if operator == "notnull":
        return actual is not None
    if actual is None:
        return False  # like SQL: comparisons with null are never true
    if operator in {"in", "notin"}:
        try:
            options = json.loads(raw)
        except ValueError:
            return False
        if not isinstance(options, list):
            return False
        contained = any(_equals(actual, _as_parameter(option)) for option in options)
        return contained if operator == "in" else not contained
    if operator in {"like", "notlike", "ilike", "notilike"}:
        matched = _pattern_matches(actual, raw, ignore_case=operator in {"ilike", "notilike"})
        return matched if operator in {"like", "ilike"} else not matched
    try:
        expected = _coerce(raw, actual)
    except ValueError:
        return False
    comparisons = {
        "eq": lambda: actual == expected,
        "ne": lambda: actual != expected,
        "lt": lambda: actual < expected,
        "le": lambda: actual <= expected,
        "gt": lambda: actual > expected,
        "ge": lambda: actual >= expected,
    }
    return bool(comparisons[operator]())


def _equals(actual: Any, raw: str) -> bool:
    try:
        return bool(actual == _coerce(raw, actual))
    except ValueError:
        return False


def _sort_key(value: Any) -> tuple[bool, int, int, str]:
    if value is None:
        return (True, 0, 0, "")
    if isinstance(value, bool | int):
        return (False, 0, int(value), "")
    if isinstance(value, str) and value.isdigit():
        return (False, 0, int(value), "")
    return (False, 1, 0, str(value))


class FakeWeclapp:
    """
    In-memory weclapp for tests. Use :meth:`client` to get a :class:`WeclappClient` connected to it.

    :param api_token: the token the fake accepts; requests with another token get ``401``
    :param start_time: the fake clock starts here and advances by one second per change
    """

    def __init__(
        self,
        *,
        api_token: str = DEFAULT_API_TOKEN,
        start_time: datetime = datetime(2026, 1, 1, tzinfo=UTC),
    ) -> None:
        self.api_token = api_token
        self.current_user = User(
            id="1",
            version="0",
            username="api-user@example.com",
            email="api-user@example.com",
            first_name="API",
            last_name="User",
            status=UserStatus.ACTIVE,
        )
        """the user returned by ``/user/currentUser``; it is not part of :attr:`users`"""
        self.transport = httpx.MockTransport(self.handle)
        """the ``httpx`` transport that routes requests to the fake"""
        self._now = start_time
        self._ids = itertools.count(1000)
        self._employee_numbers = itertools.count(1)
        self._store: dict[str, dict[str, dict[str, Any]]] = {resource: {} for resource in _RULES}
        self._failures: list[_Failure] = []
        self._requests: list[RecordedRequest] = []

    # ------------------------------------------------------------------------------------------------------------------
    # test API

    def client(self, **settings: Any) -> WeclappClient:
        """
        Returns a client connected to the fake. Retries do not wait.

        :param settings: further fields of :class:`WeclappConfig`, e.g. ``max_retries``
        """
        options: dict[str, Any] = {"backoff_initial_seconds": 0.0}
        options.update(settings)
        config = WeclappConfig(base_url=BASE_URL, api_token=SecretStr(self.api_token), **options)
        return WeclappClient(config, http_client=httpx.Client(transport=self.transport))

    def add_user(
        self,
        *,
        email: str,
        first_name: str | None = None,
        last_name: str | None = None,
        status: UserStatus | str = UserStatus.ACTIVE,
        custom_attributes: Mapping[str, str | None] | None = None,
        **properties: Any,
    ) -> User:
        """
        Adds a user without validation, so that also inconsistent data (e.g. duplicates) can be arranged.

        :param custom_attributes: string values by custom attribute definition id
        :param properties: further properties in snake_case, e.g. ``title="Dr."``
        """
        data: dict[str, Any] = {
            "email": email,
            "firstName": first_name,
            "lastName": last_name,
            "status": str(status),
            "customAttributes": [
                {"attributeDefinitionId": definition_id, "stringValue": value}
                for definition_id, value in (custom_attributes or {}).items()
            ],
        }
        data.update({to_camel(name): value for name, value in properties.items()})
        return User.model_validate(self._render(self._insert("user", data)))

    def add_employee(self, *, user_id: str, birth_date: date | None = None, **properties: Any) -> Employee:
        """
        Adds an employee without validation.

        :param properties: further properties in snake_case, e.g. ``employment_status="ACTIVE"``
        """
        data: dict[str, Any] = {"userId": user_id, "birthDate": date_to_ms(birth_date) if birth_date else None}
        data.update({to_camel(name): value for name, value in properties.items()})
        return Employee.model_validate(self._render(self._insert("employee", data)))

    def add_custom_attribute_definition(
        self,
        *,
        attribute_key: str,
        attribute_type: CustomAttributeType | str = CustomAttributeType.STRING,
        label: str | None = None,
        entity: str = "user",
    ) -> CustomAttributeDefinition:
        """Adds the definition of a custom attribute (by default of type ``STRING`` for users)."""
        data = {
            "attributeKey": attribute_key,
            "attributeType": str(attribute_type),
            "label": label or attribute_key,
            "active": True,
            "mandatory": False,
            "attributeEntityType": entity,
            "entities": [entity],
        }
        stored = self._insert("customAttributeDefinition", data)
        return CustomAttributeDefinition.model_validate(self._render(stored))

    @property
    def users(self) -> list[User]:
        """all users, ordered by id (without :attr:`current_user`)"""
        return [User.model_validate(self._render(entity)) for entity in self._sorted("user")]

    @property
    def employees(self) -> list[Employee]:
        """all employees, ordered by id"""
        return [Employee.model_validate(self._render(entity)) for entity in self._sorted("employee")]

    @property
    def custom_attribute_definitions(self) -> list[CustomAttributeDefinition]:
        """all custom attribute definitions, ordered by id"""
        return [
            CustomAttributeDefinition.model_validate(self._render(entity))
            for entity in self._sorted("customAttributeDefinition")
        ]

    @property
    def requests(self) -> list[RecordedRequest]:
        """all requests received so far"""
        return list(self._requests)

    @property
    def write_requests(self) -> list[RecordedRequest]:
        """the requests that changed (or tried to change) data, i.e. ``POST``/``PUT``/``DELETE`` without dry run"""
        return [request for request in self._requests if request.is_write]

    def clear_requests(self) -> None:
        """Forgets the recorded requests, e.g. after arranging the test data via the client."""
        self._requests.clear()

    def fail_next(
        self,
        status_code: int = 503,
        *,
        exception: Exception | None = None,
        method: str | None = None,
        path: str | None = None,
        times: int = 1,
    ) -> None:
        """
        Lets the next matching request(s) fail instead of being processed.

        :param status_code: HTTP status of the error response
        :param exception: raise this exception instead, e.g. ``httpx.ReadTimeout("timeout")``
        :param method: only fail requests with this method, e.g. ``"POST"``
        :param path: only fail requests to this path or below, e.g. ``"employee"``
        :param times: how many requests fail
        """
        self._failures.append(
            _Failure(
                method=method.upper() if method else None,
                path=path.strip("/") if path else None,
                status_code=status_code,
                exception=exception,
                remaining=times,
            )
        )

    # ------------------------------------------------------------------------------------------------------------------
    # request handling

    def handle(self, request: httpx.Request) -> httpx.Response:
        """Processes a request; this is the handler of :attr:`transport`."""
        method = request.method.upper()
        url_path = request.url.path
        path = url_path.removeprefix(_PATH_PREFIX).strip("/")
        body = self._decode_body(request)
        params = tuple(request.url.params.multi_items())
        self._requests.append(RecordedRequest(method, path, params, None if body is _INVALID_BODY else body))

        failure = next((failure for failure in self._failures if failure.matches(method, path)), None)
        if failure is not None:
            failure.remaining -= 1
            if failure.remaining <= 0:
                self._failures.remove(failure)
            if failure.exception is not None:
                raise failure.exception
            return _problem(failure.status_code, "injected", "failure injected by the test")

        if request.headers.get("AuthenticationToken") != self.api_token:
            return _problem(401, "unauthorized", "missing or invalid API token")
        if not url_path.startswith(_PATH_PREFIX) or request.url.host != httpx.URL(BASE_URL).host:
            return _problem(404, "not_found", "resource not found")
        if body is _INVALID_BODY:
            return _problem(400, "invalid_json", "invalid json")
        return self._route(method, path.split("/"), request.url.params, body)

    def _route(self, method: str, parts: list[str], params: httpx.QueryParams, body: Any) -> httpx.Response:
        resource = parts[0]
        if resource not in _RULES:
            return _problem(404, "not_found", "resource not found")
        rules = _RULES[resource]
        if parts == ["user", "currentUser"] and method == "GET":
            return httpx.Response(200, json={"result": self.current_user.model_dump(mode="json", exclude_none=True)})
        if len(parts) == 1 and method == "GET":
            return self._list(resource, rules, params)
        if len(parts) == 1 and method == "POST" and rules.writable_via_api:
            return self._create(resource, rules, body, dry_run=params.get("dryRun") == "true")
        if parts[1:] == ["count"] and method == "GET":
            return httpx.Response(200, json={"result": len(self._filtered(resource, rules, params))})
        if len(parts) == 3 and parts[1] == "id":
            entity = self._store[resource].get(parts[2])
            if entity is None:
                return _problem(404, "not_found", "entity not found")
            if method == "GET":
                return httpx.Response(200, json=self._render(entity))
            if method == "PUT" and rules.writable_via_api:
                return self._update(resource, rules, entity, body, params)
        return _problem(405, "method_not_allowed", "operation not supported by the fake")

    def _list(self, resource: str, rules: _ResourceRules, params: httpx.QueryParams) -> httpx.Response:
        try:
            page = int(params.get("page", "1"))
            page_size = int(params.get("pageSize", str(_DEFAULT_PAGE_SIZE)))
        except ValueError:
            return _validation_failed([_issue("page", "type", "invalid paging parameter")])
        if page < 1 or not 1 <= page_size <= _MAX_PAGE_SIZE:
            return _validation_failed([_issue("pageSize", "max", "invalid paging parameter")])
        entities = self._filtered(resource, rules, params)
        for key in reversed([key.strip() for key in params.get("sort", "").split(",") if key.strip()]):
            descending = key.startswith("-")
            name = key.removeprefix("-")
            entities.sort(key=lambda entity: _sort_key(entity.get(name)), reverse=descending)
        selected = entities[(page - 1) * page_size : page * page_size]
        properties = [name for name in params.get("properties", "").split(",") if name]
        return httpx.Response(200, json={"result": [self._render(entity, properties) for entity in selected]})

    def _filtered(self, resource: str, rules: _ResourceRules, params: httpx.QueryParams) -> list[dict[str, Any]]:
        conditions: list[tuple[str, str, str]] = []
        for name, value in params.multi_items():
            if name in _RESERVED_PARAMETERS:
                continue
            property_name, separator, operator = name.rpartition("-")
            if not separator or operator not in _OPERATORS:
                continue
            is_custom_attribute = resource == "user" and _CUSTOM_ATTRIBUTE_FILTER.fullmatch(property_name)
            if property_name in rules.filterable or is_custom_attribute:
                conditions.append((property_name, operator, value))
            # like weclapp, filters on unknown properties are silently ignored
        return [
            entity
            for entity in self._sorted(resource)
            if all(
                _condition_matches(self._value(resource, entity, name), operator, raw)
                for name, operator, raw in conditions
            )
        ]

    def _value(self, resource: str, entity: Mapping[str, Any], property_name: str) -> Any:
        custom_attribute = _CUSTOM_ATTRIBUTE_FILTER.fullmatch(property_name)
        if custom_attribute:
            definition_id = custom_attribute.group(1)
            for attribute in entity.get("customAttributes") or []:
                if attribute.get("attributeDefinitionId") == definition_id:
                    return attribute.get("stringValue")
            return None
        if resource == "user" and property_name == "hasEmployee":
            return any(employee.get("userId") == entity["id"] for employee in self._store["employee"].values())
        if resource == "employee" and property_name in _USER_PROPERTIES_ON_EMPLOYEE | {"fullUserName"}:
            user = self._store["user"].get(entity.get("userId") or "")
            if user is None:
                return None
            if property_name == "fullUserName":
                return " ".join(part for part in (user.get("firstName"), user.get("lastName")) if part) or None
            return user.get(property_name)
        return entity.get(property_name)

    def _create(self, resource: str, rules: _ResourceRules, body: Any, *, dry_run: bool) -> httpx.Response:
        if not isinstance(body, dict):
            return _problem(400, "invalid_json", "the request body must be a JSON object")
        issues = self._check_properties(rules, body, allowed_meta=frozenset())
        if issues:
            return _validation_failed(issues)
        entity = {**copy.deepcopy(dict(rules.defaults)), **_normalize(body)}
        issues = self._check_content(resource, rules, entity, own_id=None)
        if issues:
            return _validation_failed(issues)
        if dry_run:
            return httpx.Response(200, json=self._render(entity, exclude=_META_PROPERTIES))
        return httpx.Response(201, json=self._render(self._insert(resource, entity)))

    def _update(
        self,
        resource: str,
        rules: _ResourceRules,
        current: dict[str, Any],
        body: Any,
        params: httpx.QueryParams,
    ) -> httpx.Response:
        if not isinstance(body, dict):
            return _problem(400, "invalid_json", "the request body must be a JSON object")
        issues = self._check_properties(rules, body, allowed_meta=frozenset({"id", "version"}))
        if body.get("id") not in (None, current["id"]):
            issues.append(_issue("id", "consistency", "the id does not match the entity"))
        if issues:
            return _validation_failed(issues)
        if body.get("version") is not None and str(body["version"]) != current["version"]:
            return _problem(409, "optimistic_lock", "optimistic lock error")

        changes = _normalize({key: value for key, value in body.items() if key not in {"id", "version"}})
        if params.get("ignoreMissingProperties") == "true":
            updated = copy.deepcopy(current)
            for key, value in changes.items():
                if key == "customAttributes" and isinstance(value, list):
                    updated[key] = self._merge_custom_attributes(updated.get(key) or [], value)
                else:
                    updated[key] = value
        else:
            # a complete update: all properties that are not sent become null
            updated = {key: value for key, value in current.items() if key in rules.read_only}
            updated.update(changes)
        issues = self._check_content(resource, rules, updated, own_id=current["id"])
        if issues:
            return _validation_failed(issues)
        if params.get("dryRun") == "true":
            return httpx.Response(200, json=self._render(updated, exclude=_META_PROPERTIES))
        updated["version"] = str(int(current["version"]) + 1)
        updated["lastModifiedDate"] = self._tick()
        self._store[resource][current["id"]] = updated
        return httpx.Response(200, json=self._render(updated))

    @staticmethod
    def _merge_custom_attributes(existing: list[dict[str, Any]], changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged = {attribute.get("attributeDefinitionId"): attribute for attribute in existing}
        for attribute in changes:
            merged[attribute.get("attributeDefinitionId")] = attribute
        return list(merged.values())

    @staticmethod
    def _check_properties(
        rules: _ResourceRules, body: Mapping[str, Any], *, allowed_meta: frozenset[str]
    ) -> list[dict[str, str]]:
        issues: list[dict[str, str]] = []
        for key in body:
            if key in allowed_meta:
                continue
            if key in rules.read_only:
                issues.append(_issue(key, "read_only", f"property {key} is read-only"))
            elif key not in rules.writable:
                issues.append(_issue(key, "unknown_property", f"unknown property {key}"))
        return issues

    def _check_content(
        self, resource: str, rules: _ResourceRules, entity: Mapping[str, Any], *, own_id: str | None
    ) -> list[dict[str, str]]:
        issues = [
            _issue(name, "not_empty", f"{name} must not be empty")
            for name in sorted(rules.required)
            if not entity.get(name)
        ]
        others = [other for other_id, other in self._store[resource].items() if other_id != own_id]
        if resource == "user":
            if entity.get("status") and entity["status"] not in {status.value for status in UserStatus}:
                issues.append(_issue("status", "enum", "unsupported value"))
            email = str(entity.get("email") or "").lower()
            if email and any(str(other.get("email") or "").lower() == email for other in others):
                issues.append(_issue("email", "duplicate", "a user with this e-mail address already exists"))
        if resource == "employee" and entity.get("userId"):
            if entity["userId"] not in self._store["user"]:
                issues.append(_issue("userId", "reference", "referenced entity not found"))
            elif any(other.get("userId") == entity["userId"] for other in others):
                issues.append(_issue("userId", "duplicate", "the user already has an employee record"))
        return issues

    # ------------------------------------------------------------------------------------------------------------------
    # storage

    def _insert(self, resource: str, data: Mapping[str, Any]) -> dict[str, Any]:
        rules = _RULES[resource]
        entity = {**copy.deepcopy(dict(rules.defaults)), **copy.deepcopy(dict(data))}
        now = self._tick()
        entity.update(id=str(next(self._ids)), version="0", createdDate=now, lastModifiedDate=now)
        if resource == "user":
            entity["username"] = str(entity.get("email") or "").lower() or None
        if resource == "employee":
            entity["employeeNumber"] = str(next(self._employee_numbers))
        self._store[resource][entity["id"]] = entity
        return entity

    def _sorted(self, resource: str) -> list[dict[str, Any]]:
        return sorted(self._store[resource].values(), key=lambda entity: _sort_key(entity["id"]))

    def _tick(self) -> int:
        self._now += timedelta(seconds=1)
        return datetime_to_ms(self._now)

    @staticmethod
    def _render(
        entity: Mapping[str, Any], properties: Sequence[str] = (), exclude: frozenset[str] = frozenset()
    ) -> dict[str, Any]:
        data: dict[str, Any] = _without_nulls(copy.deepcopy(dict(entity)))
        if properties:
            data = {name: data[name] for name in properties if name in data}
        return {name: value for name, value in data.items() if name not in exclude}

    @staticmethod
    def _decode_body(request: httpx.Request) -> Any:
        if not request.content:
            return None
        try:
            return json.loads(request.content)
        except ValueError:
            return _INVALID_BODY

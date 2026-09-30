import json
from typing import Any, ClassVar

import httpx
import pytest

from weclapp_client import AmbiguousResultError, InvalidQueryError, NotFoundError, WeclappError
from weclapp_client.models import User, UserCreate, UserStatus, UserUpdate
from weclapp_client.query import Filter
from weclapp_client.resources.base import WriteResource

from .helpers import make_transport, problem


class _ExampleResource(WriteResource[User, UserCreate, UserUpdate]):
    path = "user"
    entity_model = User
    known_properties: ClassVar[frozenset[str]] = frozenset({"id", "version", "email", "lastName", "lastModifiedDate"})
    filterable_properties: ClassVar[frozenset[str]] = frozenset({"id", "email", "lastName"})


class _Recorder:
    """Answers list requests from a list of users and records all requests."""

    def __init__(self, total: int = 0, response: httpx.Response | None = None) -> None:
        self.users = [{"id": str(index), "version": "0", "email": f"user{index}@example.com"} for index in range(total)]
        self.response = response
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.response is not None:
            return self.response
        page = int(request.url.params.get("page", "1"))
        page_size = int(request.url.params.get("pageSize", "100"))
        start = (page - 1) * page_size
        return httpx.Response(200, json={"result": self.users[start : start + page_size]})

    def params(self, index: int = 0) -> list[tuple[str, str]]:
        return list(self.requests[index].url.params.multi_items())

    def body(self, index: int = 0) -> Any:
        return json.loads(self.requests[index].content)


def _resource(recorder: _Recorder) -> _ExampleResource:
    transport, _ = make_transport(recorder)
    return _ExampleResource(transport)


@pytest.mark.parametrize(("total", "expected_requests"), [(0, 1), (1, 1), (1000, 2), (2500, 3)])
def test_iterate_fetches_all_pages(total: int, expected_requests: int) -> None:
    recorder = _Recorder(total)
    users = _resource(recorder).list()
    assert [user.id for user in users] == [str(index) for index in range(total)]
    assert len(recorder.requests) == expected_requests
    assert recorder.params(0) == [("sort", "id"), ("page", "1"), ("pageSize", "1000")]


def test_iterate_with_small_pages() -> None:
    recorder = _Recorder(5)
    assert len(list(_resource(recorder).iterate(page_size=2))) == 5
    assert [request.url.params["page"] for request in recorder.requests] == ["1", "2", "3"]


@pytest.mark.parametrize("page_size", [0, 1001])
def test_invalid_page_size_is_rejected(page_size: int) -> None:
    with pytest.raises(ValueError, match="page_size"):
        _resource(_Recorder()).iterate(page_size=page_size)


def test_query_parameters_for_filters_sort_and_properties() -> None:
    recorder = _Recorder()
    _resource(recorder).list(
        Filter.eq("email", "a@example.com"),
        Filter.custom_attribute_eq("9001", "00042"),
        properties=["email", "id"],
        sort="-lastModifiedDate, id",
    )
    assert recorder.params() == [
        ("email-eq", "a@example.com"),
        ("customAttribute9001-eq", "00042"),
        ("sort", "-lastModifiedDate,id"),
        ("properties", "id,version,email"),
        ("page", "1"),
        ("pageSize", "1000"),
    ]


def test_empty_sort_sends_no_sort_parameter() -> None:
    recorder = _Recorder()
    _resource(recorder).list(sort="")
    assert ("sort", "") not in recorder.params()
    assert [name for name, _ in recorder.params()] == ["page", "pageSize"]


@pytest.mark.parametrize(
    "call",
    [
        lambda resource: resource.iterate(Filter.eq("emial", "x")),
        lambda resource: resource.iterate(properties=["emial"]),
        lambda resource: resource.iterate(sort="-emial"),
        lambda resource: resource.count(Filter.eq("lastModifiedDate", 1)),
        lambda resource: resource.find_one(Filter.eq("emial", "x")),
    ],
)
def test_invalid_queries_are_rejected_before_sending(call: Any) -> None:
    recorder = _Recorder()
    with pytest.raises(InvalidQueryError):
        call(_resource(recorder))
    assert recorder.requests == []


def test_count() -> None:
    recorder = _Recorder(response=httpx.Response(200, json={"result": 42}))
    assert _resource(recorder).count(Filter.eq("lastName", "Musterfrau")) == 42
    assert recorder.requests[0].url.path.endswith("/user/count")
    assert recorder.params() == [("lastName-eq", "Musterfrau")]


def test_unexpected_count_response_raises() -> None:
    with pytest.raises(WeclappError):
        _resource(_Recorder(response=httpx.Response(200, json={"result": "many"}))).count()


def test_unexpected_list_response_raises() -> None:
    with pytest.raises(WeclappError):
        _resource(_Recorder(response=httpx.Response(200, json=[{"id": "1"}]))).list()


def test_get() -> None:
    recorder = _Recorder(response=httpx.Response(200, json={"id": "4711", "version": "2"}))
    user = _resource(recorder).get("4711")
    assert user.id == "4711"
    assert recorder.requests[0].url.path.endswith("/user/id/4711")


def test_get_unknown_id_raises() -> None:
    recorder = _Recorder(response=problem(404, "not_found", "resource not found"))
    with pytest.raises(NotFoundError):
        _resource(recorder).get("1")


@pytest.mark.parametrize(("total", "expected_id"), [(0, None), (1, "0")])
def test_find_one(total: int, expected_id: str | None) -> None:
    recorder = _Recorder(total)
    user = _resource(recorder).find_one(Filter.eq("lastName", "Musterfrau"))
    assert (user.id if user else None) == expected_id
    assert recorder.params() == [("lastName-eq", "Musterfrau"), ("sort", "id"), ("page", "1"), ("pageSize", "2")]


def test_find_one_with_several_matches_raises() -> None:
    with pytest.raises(AmbiguousResultError):
        _resource(_Recorder(3)).find_one(Filter.eq("lastName", "Musterfrau"))


def test_find_one_needs_a_filter() -> None:
    with pytest.raises(InvalidQueryError):
        _resource(_Recorder()).find_one()


# ----------------------------------------------------------------------------------------------------------------------
# create and update


def test_create() -> None:
    recorder = _Recorder(response=httpx.Response(201, json={"id": "4711", "version": "0", "email": "a@example.com"}))
    user = _resource(recorder).create(UserCreate(email="a@example.com", status=UserStatus.NOT_ACTIVE))
    assert user.id == "4711"
    assert recorder.requests[0].method == "POST"
    assert recorder.params() == []
    assert recorder.body() == {"email": "a@example.com", "status": "NOT_ACTIVE", "canEditDashboard": False}


def test_create_dry_run() -> None:
    recorder = _Recorder(response=httpx.Response(200, json={"email": "a@example.com"}))
    result = _resource(recorder).create(UserCreate(email="a@example.com", status=UserStatus.ACTIVE), dry_run=True)
    assert result is None
    assert recorder.params() == [("dryRun", "true")]


_CURRENT = User(id="4711", version="3", email="a@example.com", last_name="Musterfrau")


def test_update_is_partial_and_uses_the_version() -> None:
    recorder = _Recorder(response=httpx.Response(200, json={"id": "4711", "version": "4", "lastName": "Neu"}))
    updated = _resource(recorder).update(_CURRENT, UserUpdate(last_name="Neu"))
    assert updated.version == "4"
    request = recorder.requests[0]
    assert request.method == "PUT"
    assert request.url.path.endswith("/user/id/4711")
    assert recorder.params() == [("ignoreMissingProperties", "true")]
    assert recorder.body() == {"lastName": "Neu", "version": "3"}


def test_update_dry_run() -> None:
    recorder = _Recorder(response=httpx.Response(200, json={"lastName": "Neu"}))
    assert _resource(recorder).update(_CURRENT, UserUpdate(last_name="Neu"), dry_run=True) is None
    assert recorder.params() == [("ignoreMissingProperties", "true"), ("dryRun", "true")]


@pytest.mark.parametrize("dry_run", [False, True])
def test_update_without_changes_sends_nothing(dry_run: bool) -> None:
    recorder = _Recorder()
    result = _resource(recorder).update(_CURRENT, UserUpdate(), dry_run=dry_run)
    assert result is (None if dry_run else _CURRENT)
    assert recorder.requests == []

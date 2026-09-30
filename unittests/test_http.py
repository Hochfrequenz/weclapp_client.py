import logging

import httpx
import pytest

from weclapp_client import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    OptimisticLockError,
    PermissionDeniedError,
    RateLimitError,
    ServerError,
    WeclappApiError,
    WeclappConnectionError,
    WeclappError,
    WeclappValidationError,
)
from weclapp_client._http import HttpTransport, entity_path, error_from_response

from .helpers import API_TOKEN, BASE_URL, make_config, make_transport, problem


def test_request_uses_base_url_and_headers() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"result": []})

    transport, _ = make_transport(handler)
    assert transport.request_json("GET", "user", params=[("page", "1")]) == {"result": []}

    request = seen[0]
    assert str(request.url) == BASE_URL + "user?page=1"
    assert request.headers["AuthenticationToken"] == API_TOKEN
    assert request.headers["Accept"] == "application/json"
    assert request.headers["User-Agent"].startswith("weclapp-client-py/")


def test_json_body_is_sent() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"id": "1"})

    transport, _ = make_transport(handler, user_agent="sync-job/1.0")
    transport.request_json("POST", "/user", json_body={"email": "a@example.com"})

    assert seen[0].headers["Content-Type"] == "application/json"
    assert seen[0].content == b'{"email":"a@example.com"}'
    assert seen[0].headers["User-Agent"] == "sync-job/1.0"


def test_entity_path_encodes_the_id() -> None:
    assert entity_path("user", "4711") == "user/id/4711"
    assert entity_path("user", "a/b?c") == "user/id/a%2Fb%3Fc"


def test_invalid_json_in_success_response_raises() -> None:
    transport, _ = make_transport(lambda request: httpx.Response(200, text="not json"))
    with pytest.raises(WeclappError, match="invalid JSON"):
        transport.request_json("GET", "user")


# ----------------------------------------------------------------------------------------------------------------------
# error mapping


def test_validation_error_with_details() -> None:
    response = problem(
        400,
        "validation",
        "entity validation failed",
        detail="customer not found",
        error="customer not found",
        validationErrors=[
            {
                "detail": "referenced entity not found",
                "instance": "salesOrder",
                "location": "customerId",
                "title": "referenced entity not found",
                "type": "/webapp/view/api/errors.html#!/validation/reference",
                "errorCode": "E123",
                "allowed": ["A", "B"],
            },
            "unexpected entry",
        ],
    )
    error = error_from_response(response)

    assert isinstance(error, WeclappValidationError)
    assert error.status_code == 400
    assert error.problem_type == "validation"
    assert error.message == "customer not found"
    assert str(error) == "customer not found (HTTP 400)"
    assert len(error.validation_errors) == 1
    issue = error.validation_errors[0]
    assert issue.type == "reference"
    assert issue.location == "customerId"
    assert issue.error_code == "E123"
    assert issue.allowed == ("A", "B")


@pytest.mark.parametrize(
    ("status", "problem_type", "expected_class"),
    [
        (401, "unauthorized", AuthenticationError),
        (403, "forbidden", PermissionDeniedError),
        (404, "not_found", NotFoundError),
        (409, "optimistic_lock", OptimisticLockError),
        (409, "persistence", ConflictError),
        (429, "too_many_requests", RateLimitError),
        (500, "unexpected", ServerError),
        (503, "unexpected", ServerError),
        (418, "teapot", WeclappApiError),
    ],
)
def test_status_codes_map_to_exception_classes(
    status: int, problem_type: str, expected_class: type[WeclappApiError]
) -> None:
    error = error_from_response(problem(status, problem_type, "something failed"))
    assert type(error) is expected_class
    assert error.problem_type == problem_type
    assert error.title == "something failed"


def test_optimistic_lock_is_a_conflict() -> None:
    assert isinstance(error_from_response(problem(409, "optimistic_lock", "optimistic lock error")), ConflictError)


def test_plain_text_error_body_becomes_the_message() -> None:
    error = error_from_response(httpx.Response(400, text=" bad request "))
    assert isinstance(error, WeclappValidationError)
    assert error.message == "bad request"
    assert error.problem_type is None


def test_empty_error_body_falls_back_to_reason_phrase() -> None:
    assert error_from_response(httpx.Response(404)).message == "Not Found"


def test_long_messages_are_truncated() -> None:
    error = error_from_response(httpx.Response(400, text="x" * 2000))
    assert len(error.message) == 503
    assert error.message.endswith("...")


def test_error_response_raises_mapped_exception() -> None:
    transport, _ = make_transport(lambda request: problem(404, "not_found", "resource not found"))
    with pytest.raises(NotFoundError):
        transport.request("GET", "user/id/1")


# ----------------------------------------------------------------------------------------------------------------------
# retries


class _Sequence:
    """Answers the requests with the given responses (or raises the given exceptions) in order."""

    def __init__(self, *outcomes: httpx.Response | Exception) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_429_is_retried_with_exponential_backoff() -> None:
    handler = _Sequence(httpx.Response(429), httpx.Response(429), httpx.Response(200, json={}))
    transport, sleep = make_transport(handler)
    transport.request("GET", "user")
    assert handler.calls == 3
    assert sleep.delays == [1.0, 2.0]


def test_post_is_retried_after_429() -> None:
    handler = _Sequence(httpx.Response(429), httpx.Response(201, json={}))
    transport, _ = make_transport(handler)
    transport.request("POST", "user", json_body={})
    assert handler.calls == 2


def test_retries_stop_after_max_retries() -> None:
    handler = _Sequence(*[httpx.Response(429) for _ in range(3)])
    transport, sleep = make_transport(handler, max_retries=2)
    with pytest.raises(RateLimitError):
        transport.request("GET", "user")
    assert handler.calls == 3
    assert len(sleep.delays) == 2


def test_backoff_is_capped() -> None:
    handler = _Sequence(*[httpx.Response(503) for _ in range(5)], httpx.Response(200, json={}))
    transport, sleep = make_transport(handler, backoff_initial_seconds=4, backoff_max_seconds=10)
    transport.request("GET", "user")
    assert sleep.delays == [4.0, 8.0, 10.0, 10.0, 10.0]


def test_jitter_shortens_the_delay() -> None:
    handler = _Sequence(httpx.Response(429), httpx.Response(200, json={}))
    delays: list[float] = []
    transport = HttpTransport(
        make_config(backoff_initial_seconds=2),
        httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=delays.append,
        jitter=lambda: 0.0,
    )
    transport.request("GET", "user")
    assert delays == [1.0]


@pytest.mark.parametrize("method", ["GET", "PUT"])
def test_idempotent_requests_are_retried_on_gateway_errors_and_timeouts(method: str) -> None:
    handler = _Sequence(
        httpx.Response(502), httpx.ReadTimeout("timeout"), httpx.Response(504), httpx.Response(200, json={})
    )
    transport, _ = make_transport(handler)
    transport.request(method, "user/id/1", json_body={} if method == "PUT" else None)
    assert handler.calls == 4


def test_post_is_not_retried_on_gateway_errors() -> None:
    handler = _Sequence(httpx.Response(503), httpx.Response(201, json={}))
    transport, _ = make_transport(handler)
    with pytest.raises(ServerError):
        transport.request("POST", "user", json_body={})
    assert handler.calls == 1


def test_post_is_not_retried_on_read_timeout() -> None:
    handler = _Sequence(httpx.ReadTimeout("timeout"), httpx.Response(201, json={}))
    transport, _ = make_transport(handler)
    with pytest.raises(WeclappConnectionError, match="ReadTimeout"):
        transport.request("POST", "user", json_body={})
    assert handler.calls == 1


@pytest.mark.parametrize("error", [httpx.ConnectError("refused"), httpx.ConnectTimeout("timeout")])
def test_post_is_retried_if_the_connection_failed(error: Exception) -> None:
    handler = _Sequence(error, httpx.Response(201, json={}))
    transport, _ = make_transport(handler)
    transport.request("POST", "user", json_body={})
    assert handler.calls == 2


def test_connection_errors_raise_after_all_retries() -> None:
    handler = _Sequence(*[httpx.ConnectError("refused") for _ in range(2)])
    transport, _ = make_transport(handler, max_retries=1)
    with pytest.raises(WeclappConnectionError):
        transport.request("GET", "user")


# ----------------------------------------------------------------------------------------------------------------------
# logging and secrets


def test_logs_contain_neither_query_parameters_nor_the_token(caplog: pytest.LogCaptureFixture) -> None:
    handler = _Sequence(httpx.Response(429), httpx.Response(200, json={}))
    transport, _ = make_transport(handler)
    with caplog.at_level(logging.DEBUG, logger="weclapp_client"):
        transport.request("GET", "user", params=[("email-eq", "erika.musterfrau@example.com")])
    assert "GET user -> 200" in caplog.text
    assert "erika" not in caplog.text
    assert API_TOKEN not in caplog.text


def test_token_is_not_part_of_error_messages() -> None:
    transport, _ = make_transport(lambda request: problem(401, "unauthorized", "unauthorized"))
    with pytest.raises(AuthenticationError) as error_info:
        transport.request("GET", "user")
    assert API_TOKEN not in str(error_info.value)
    assert API_TOKEN not in repr(error_info.value)


@pytest.mark.parametrize(("wait_ms", "expected_level"), [("6000", logging.WARNING), ("120", logging.DEBUG)])
def test_weclapp_wait_headers_are_logged(caplog: pytest.LogCaptureFixture, wait_ms: str, expected_level: int) -> None:
    headers = {"X-Weclapp-Wait-Ms": wait_ms, "X-Weclapp-Wait-Reason": "concurrency"}
    transport, _ = make_transport(lambda request: httpx.Response(200, json={}, headers=headers))
    with caplog.at_level(logging.DEBUG, logger="weclapp_client"):
        transport.request("GET", "user")
    records = [record for record in caplog.records if "delayed" in record.getMessage()]
    assert len(records) == 1
    assert records[0].levelno == expected_level
    assert "concurrency" in records[0].getMessage()


# ----------------------------------------------------------------------------------------------------------------------
# lifecycle


def test_close_keeps_an_injected_client_open() -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200)))
    HttpTransport(make_config(), client).close()
    assert not client.is_closed


def test_close_closes_the_own_client() -> None:
    transport = HttpTransport(make_config())
    transport.close()
    assert transport._client.is_closed

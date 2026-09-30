"""
HTTP transport: authentication, headers, timeouts, retries and the mapping of error responses to exceptions.

Retry rules (with exponential backoff and jitter):

- ``429 Too Many Requests`` and failed connection attempts are retried for every method, because weclapp did not
  process these requests.
- ``502``/``503``/``504`` and other network errors (e.g. read timeouts) are only retried for idempotent methods
  (``GET``, ``PUT``, ``DELETE``). A ``POST`` might already have created the entity, so it is not repeated; callers
  should look up an entity before creating it.
"""

import logging
import random
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from urllib.parse import quote

import httpx

from weclapp_client._version import __version__
from weclapp_client.config import WeclappConfig
from weclapp_client.exceptions import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    OptimisticLockError,
    PermissionDeniedError,
    RateLimitError,
    ServerError,
    ValidationIssue,
    WeclappApiError,
    WeclappConnectionError,
    WeclappError,
    WeclappValidationError,
)

_logger = logging.getLogger("weclapp_client")

QueryParams = Sequence[tuple[str, str]]

_IDEMPOTENT_METHODS = frozenset({"GET", "PUT", "DELETE"})
_RETRY_STATUS_ALWAYS = frozenset({429})
_RETRY_STATUS_IDEMPOTENT = frozenset({429, 502, 503, 504})
_NOT_SENT_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
"""transport errors that occur before the request reached weclapp"""
_IDEMPOTENT_RETRY_ERRORS = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)
_WAIT_WARNING_THRESHOLD_MS = 5000
_MAX_MESSAGE_LENGTH = 500

_ERROR_CLASSES: Mapping[int, type[WeclappApiError]] = {
    400: WeclappValidationError,
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    429: RateLimitError,
}


def entity_path(resource_path: str, entity_id: str) -> str:
    """Returns the path of a single entity, e.g. ``user/id/4711``; the id is URL-encoded."""
    return f"{resource_path}/id/{quote(entity_id, safe='')}"


def _last_path_segment(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value.rsplit("/", 1)[-1]


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _parse_validation_issue(raw: object) -> ValidationIssue | None:
    if not isinstance(raw, dict):
        return None
    allowed = raw.get("allowed")
    return ValidationIssue(
        type=_last_path_segment(raw.get("type")),
        title=_optional_str(raw.get("title")),
        detail=_optional_str(raw.get("detail")),
        error_code=_optional_str(raw.get("errorCode")),
        instance=_optional_str(raw.get("instance")),
        location=_optional_str(raw.get("location")),
        allowed=tuple(str(item) for item in allowed) if isinstance(allowed, list) else (),
    )


def error_from_response(response: httpx.Response) -> WeclappApiError:
    """Maps an error response of the weclapp API to the matching :class:`WeclappApiError` subclass."""
    status = response.status_code
    body: object = None
    try:
        body = response.json()
    except ValueError:
        body = None
    problem: Mapping[str, Any] = body if isinstance(body, dict) else {}

    problem_type = _last_path_segment(problem.get("type"))
    title = _optional_str(problem.get("title"))
    detail = _optional_str(problem.get("detail"))
    raw_issues = problem.get("validationErrors")
    issues = tuple(
        issue for issue in map(_parse_validation_issue, raw_issues if isinstance(raw_issues, list) else []) if issue
    )
    text = response.text.strip() if not problem else ""
    message = detail or title or _optional_str(problem.get("error")) or text or response.reason_phrase or "error"
    if len(message) > _MAX_MESSAGE_LENGTH:
        message = message[:_MAX_MESSAGE_LENGTH] + "..."

    if status == 409 and problem_type == "optimistic_lock":
        error_class: type[WeclappApiError] = OptimisticLockError
    elif status >= 500:
        error_class = ServerError
    else:
        error_class = _ERROR_CLASSES.get(status, WeclappApiError)
    return error_class(
        message,
        status_code=status,
        problem_type=problem_type,
        title=title,
        detail=detail,
        instance=_optional_str(problem.get("instance")),
        validation_errors=issues,
    )


class HttpTransport:
    """
    Sends requests to the weclapp API. Internal; use :class:`weclapp_client.WeclappClient` instead.

    :param http_client: an existing client (e.g. with a mock transport for tests); it is not closed by :meth:`close`
    :param sleep: used to wait between retries (injectable for tests)
    :param jitter: returns a random number in ``[0, 1)`` that randomises the backoff (injectable for tests)
    """

    def __init__(
        self,
        config: WeclappConfig,
        http_client: httpx.Client | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self._config = config
        self._timeout = httpx.Timeout(config.timeout_seconds, connect=config.connect_timeout_seconds)
        self._owns_client = http_client is None
        self._client = http_client if http_client is not None else httpx.Client(timeout=self._timeout)
        self._sleep = sleep
        self._jitter = jitter
        self._headers = {
            "AuthenticationToken": config.api_token.get_secret_value(),
            "Accept": "application/json",
            "User-Agent": config.user_agent or f"weclapp-client-py/{__version__}",
        }

    def close(self) -> None:
        """Closes the underlying HTTP client if this transport created it."""
        if self._owns_client:
            self._client.close()

    def request_json(
        self,
        method: str,
        path: str,
        *,
        params: QueryParams = (),
        json_body: Mapping[str, Any] | None = None,
    ) -> Any:
        """Sends a request and returns the decoded JSON body of the successful response."""
        response = self.request(method, path, params=params, json_body=json_body)
        try:
            return response.json()
        except ValueError as error:
            raise WeclappError(f"weclapp returned an invalid JSON body for {method} {path}") from error

    def request(
        self,
        method: str,
        path: str,
        *,
        params: QueryParams = (),
        json_body: Mapping[str, Any] | None = None,
    ) -> httpx.Response:
        """
        Sends a request, retries it where that is safe and returns the successful response.

        :param path: path relative to the base URL, e.g. ``user/id/4711``
        :raises WeclappApiError: (or a subclass) if weclapp answers with an error status
        :raises WeclappConnectionError: if weclapp cannot be reached
        """
        method = method.upper()
        idempotent = method in _IDEMPOTENT_METHODS
        retry_status = _RETRY_STATUS_IDEMPOTENT if idempotent else _RETRY_STATUS_ALWAYS
        url = self._config.base_url + path.lstrip("/")
        attempt = 0
        while True:
            try:
                response = self._client.request(
                    method,
                    url,
                    params=list(params),
                    json=json_body,
                    headers=self._headers,
                    timeout=self._timeout,
                )
            except httpx.TransportError as error:
                retryable = isinstance(error, _NOT_SENT_ERRORS) or (
                    idempotent and isinstance(error, _IDEMPOTENT_RETRY_ERRORS)
                )
                if retryable and attempt < self._config.max_retries:
                    self._wait_before_retry(method, path, attempt, type(error).__name__)
                    attempt += 1
                    continue
                raise WeclappConnectionError(f"{method} {path} failed: {type(error).__name__}") from error

            self._log_response(method, path, response)
            if response.status_code in retry_status and attempt < self._config.max_retries:
                self._wait_before_retry(method, path, attempt, f"HTTP {response.status_code}")
                attempt += 1
                continue
            if response.is_error:
                raise error_from_response(response)
            return response

    def _wait_before_retry(self, method: str, path: str, attempt: int, reason: str) -> None:
        delay = min(self._config.backoff_max_seconds, self._config.backoff_initial_seconds * 2**attempt)
        delay *= 0.5 + 0.5 * self._jitter()
        _logger.warning(
            "Retrying %s %s after %s in %.1f s (retry %d of %d)",
            method,
            path,
            reason,
            delay,
            attempt + 1,
            self._config.max_retries,
        )
        self._sleep(delay)

    @staticmethod
    def _log_response(method: str, path: str, response: httpx.Response) -> None:
        # only method, path and status are logged: query parameters and bodies may contain personal data
        _logger.debug("%s %s -> %d", method, path, response.status_code)
        wait_ms = response.headers.get("X-Weclapp-Wait-Ms")
        if wait_ms is None or not wait_ms.isdigit():
            return
        level = logging.WARNING if int(wait_ms) >= _WAIT_WARNING_THRESHOLD_MS else logging.DEBUG
        _logger.log(
            level,
            "weclapp delayed %s %s by %s ms (reason: %s)",
            method,
            path,
            wait_ms,
            response.headers.get("X-Weclapp-Wait-Reason", "unknown"),
        )

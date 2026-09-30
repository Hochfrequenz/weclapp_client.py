"""
Exceptions raised by the weclapp client.

All exceptions derive from :class:`WeclappError`. Errors returned by the weclapp API derive from
:class:`WeclappApiError` and carry the parsed problem details (weclapp uses a structure based on RFC 7807).
"""

from dataclasses import dataclass


class WeclappError(Exception):
    """Base class of all errors raised by this package."""


class WeclappConfigurationError(WeclappError):
    """The client configuration is incomplete or invalid (e.g. a missing environment variable)."""


class WeclappConnectionError(WeclappError):
    """The weclapp API could not be reached (network error or timeout), even after all retries."""


class InvalidQueryError(WeclappError, ValueError):
    """
    A query uses a property that is unknown or not filterable/sortable for the resource.

    weclapp silently ignores unknown filter parameters, so such a query is rejected before it is sent.
    """


class AmbiguousResultError(WeclappError):
    """A lookup that expects at most one result matched several entities."""


class CustomAttributeDefinitionError(WeclappError):
    """A custom attribute definition does not exist or does not have the expected type."""


@dataclass(frozen=True, kw_only=True)
class ValidationIssue:
    """One entry of the ``validationErrors`` list of a weclapp error response."""

    type: str | None = None
    """the problem type, i.e. the part of the weclapp ``type`` URI after the last ``/`` (e.g. ``"reference"``)"""
    title: str | None = None
    detail: str | None = None
    error_code: str | None = None
    instance: str | None = None
    location: str | None = None
    """JSON path of the affected property"""
    allowed: tuple[str, ...] = ()


class WeclappApiError(WeclappError):
    """The weclapp API answered with an HTTP error status."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        problem_type: str | None = None,
        title: str | None = None,
        detail: str | None = None,
        instance: str | None = None,
        validation_errors: tuple[ValidationIssue, ...] = (),
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.problem_type = problem_type
        """the part of the weclapp ``type`` URI after the last ``/`` (e.g. ``"optimistic_lock"``)"""
        self.title = title
        self.detail = detail
        self.instance = instance
        self.validation_errors = validation_errors

    def __str__(self) -> str:
        return f"{self.message} (HTTP {self.status_code})"


class AuthenticationError(WeclappApiError):
    """HTTP 401: the API token is missing or invalid."""


class PermissionDeniedError(WeclappApiError):
    """HTTP 403: the API user lacks the permission for the requested operation or property."""


class NotFoundError(WeclappApiError):
    """HTTP 404: the requested entity or resource does not exist."""


class WeclappValidationError(WeclappApiError):
    """HTTP 400: the request was rejected, see :attr:`validation_errors` for the affected properties."""


class ConflictError(WeclappApiError):
    """HTTP 409: the operation is not possible in the current state of the entity."""


class OptimisticLockError(ConflictError):
    """HTTP 409 ``optimistic_lock``: the entity was changed in the meantime, re-read it and try again."""


class RateLimitError(WeclappApiError):
    """HTTP 429: weclapp rejected the request due to load, even after all retries."""


class ServerError(WeclappApiError):
    """HTTP 5xx: weclapp failed to process the request."""

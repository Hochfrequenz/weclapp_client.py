"""
Typed Python client for the weclapp REST API v2, focused on the endpoints needed to synchronise employee master data.
"""

from weclapp_client._version import __version__
from weclapp_client.config import WeclappConfig
from weclapp_client.exceptions import (
    AmbiguousResultError,
    AuthenticationError,
    ConflictError,
    CustomAttributeDefinitionError,
    InvalidQueryError,
    NotFoundError,
    OptimisticLockError,
    PermissionDeniedError,
    RateLimitError,
    ServerError,
    ValidationIssue,
    WeclappApiError,
    WeclappConfigurationError,
    WeclappConnectionError,
    WeclappError,
    WeclappValidationError,
)

__all__ = [
    "AmbiguousResultError",
    "AuthenticationError",
    "ConflictError",
    "CustomAttributeDefinitionError",
    "InvalidQueryError",
    "NotFoundError",
    "OptimisticLockError",
    "PermissionDeniedError",
    "RateLimitError",
    "ServerError",
    "ValidationIssue",
    "WeclappApiError",
    "WeclappConfig",
    "WeclappConfigurationError",
    "WeclappConnectionError",
    "WeclappError",
    "WeclappValidationError",
    "__version__",
]

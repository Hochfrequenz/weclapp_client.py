"""
Configuration of the weclapp client.
"""

import os
import re
from collections.abc import Mapping
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from weclapp_client.exceptions import WeclappConfigurationError

_TENANT_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")

ENV_BASE_URL = "WECLAPP_BASE_URL"
ENV_TENANT = "WECLAPP_TENANT"
ENV_API_TOKEN = "WECLAPP_API_TOKEN"


def tenant_base_url(tenant: str) -> str:
    """
    Returns the base URL of the REST API v2 of the given weclapp tenant, e.g. ``"acme"`` becomes
    ``"https://acme.weclapp.com/webapp/api/v2/"``.
    """
    normalized = tenant.strip().lower()
    if not _TENANT_PATTERN.fullmatch(normalized):
        raise WeclappConfigurationError(f"Invalid weclapp tenant name: {tenant!r}")
    return f"https://{normalized}.weclapp.com/webapp/api/v2/"


class WeclappConfig(BaseModel):
    """
    Connection settings for the weclapp REST API v2.

    The API token is stored as :class:`~pydantic.SecretStr`, so it does not show up in ``repr``, logs or exceptions.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    base_url: str
    """base URL of the REST API v2, e.g. ``https://<tenant>.weclapp.com/webapp/api/v2/``"""
    api_token: SecretStr
    """API token of the (technical) weclapp user, sent in the ``AuthenticationToken`` header"""
    timeout_seconds: float = Field(default=60.0, gt=0)
    """timeout for a single request; weclapp recommends at least one minute"""
    connect_timeout_seconds: float = Field(default=10.0, gt=0)
    """timeout for establishing the connection"""
    max_retries: int = Field(default=5, ge=0)
    """how often a request is retried if that is safe (see the README for the retry rules)"""
    backoff_initial_seconds: float = Field(default=1.0, ge=0)
    """delay before the first retry; it doubles with every further retry"""
    backoff_max_seconds: float = Field(default=30.0, ge=0)
    """upper limit for the delay between two retries"""
    user_agent: str | None = None
    """value of the ``User-Agent`` header; defaults to ``weclapp-client-py/<version>``"""

    @field_validator("base_url")
    @classmethod
    def _normalize_base_url(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.startswith(("https://", "http://")):
            raise ValueError("base_url must start with https:// (or http:// for local test servers)")
        return normalized.rstrip("/") + "/"

    @classmethod
    def for_tenant(cls, tenant: str, api_token: str | SecretStr, **settings: Any) -> Self:
        """
        Creates the configuration for the weclapp tenant ``https://<tenant>.weclapp.com``.

        :param settings: further fields of this class, e.g. ``timeout_seconds``
        """
        token = api_token if isinstance(api_token, SecretStr) else SecretStr(api_token)
        return cls(base_url=tenant_base_url(tenant), api_token=token, **settings)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None, **settings: Any) -> Self:
        """
        Creates the configuration from environment variables:

        - ``WECLAPP_API_TOKEN`` (required)
        - ``WECLAPP_BASE_URL`` or, alternatively, ``WECLAPP_TENANT``

        :param environ: the variables to read from; defaults to :data:`os.environ`
        :param settings: further fields of this class, e.g. ``timeout_seconds``
        """
        variables = os.environ if environ is None else environ
        api_token = variables.get(ENV_API_TOKEN, "").strip()
        if not api_token:
            raise WeclappConfigurationError(f"Environment variable {ENV_API_TOKEN} is not set")
        base_url = variables.get(ENV_BASE_URL, "").strip()
        if base_url:
            return cls(base_url=base_url, api_token=SecretStr(api_token), **settings)
        tenant = variables.get(ENV_TENANT, "").strip()
        if tenant:
            return cls.for_tenant(tenant, api_token, **settings)
        raise WeclappConfigurationError(f"Neither {ENV_BASE_URL} nor {ENV_TENANT} is set")

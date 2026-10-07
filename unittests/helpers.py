"""
Helpers shared by the unit tests.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from pydantic import SecretStr

from weclapp_client._http import HttpTransport
from weclapp_client.config import WeclappConfig

BASE_URL = "https://test.weclapp.test/webapp/api/v2/"
API_TOKEN = "test-token-1234"

Handler = Callable[[httpx.Request], httpx.Response]


def make_config(**overrides: Any) -> WeclappConfig:
    settings: dict[str, Any] = {"backoff_initial_seconds": 1.0, "backoff_max_seconds": 30.0}
    settings.update(overrides)
    return WeclappConfig(base_url=BASE_URL, api_token=SecretStr(API_TOKEN), **settings)


class RecordingSleep:
    """Replaces ``time.sleep`` and records the requested delays."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def make_transport(handler: Handler, **config_overrides: Any) -> tuple[HttpTransport, RecordingSleep]:
    """Creates a transport that sends all requests to ``handler``; the jitter is fixed, so delays are predictable."""
    sleep = RecordingSleep()
    transport = HttpTransport(
        make_config(**config_overrides),
        httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=sleep,
        jitter=lambda: 1.0,
    )
    return transport, sleep


def problem(status: int, problem_type: str, title: str, **extra: Any) -> httpx.Response:
    """An error response in the (RFC 7807 based) structure used by weclapp."""
    body: dict[str, Any] = {
        "status": status,
        "title": title,
        "type": f"/webapp/view/api/errors.html#!/errors/{problem_type}",
    }
    body.update(extra)
    return httpx.Response(status, json=body)


FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    """Loads a synthetic example response from ``unittests/fixtures/<name>.json``."""
    result: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return result

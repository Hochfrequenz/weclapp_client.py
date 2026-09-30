import pytest
from pydantic import SecretStr, ValidationError

from weclapp_client import WeclappConfig, WeclappConfigurationError
from weclapp_client.config import tenant_base_url


def test_base_url_gets_a_trailing_slash() -> None:
    config = WeclappConfig(base_url=" https://acme.weclapp.com/webapp/api/v2 ", api_token=SecretStr("t"))
    assert config.base_url == "https://acme.weclapp.com/webapp/api/v2/"


def test_base_url_requires_http_scheme() -> None:
    with pytest.raises(ValidationError):
        WeclappConfig(base_url="acme.weclapp.com/webapp/api/v2", api_token=SecretStr("t"))


def test_for_tenant_builds_the_v2_base_url() -> None:
    config = WeclappConfig.for_tenant("Acme", "secret", timeout_seconds=90)
    assert config.base_url == "https://acme.weclapp.com/webapp/api/v2/"
    assert config.api_token.get_secret_value() == "secret"
    assert config.timeout_seconds == 90


@pytest.mark.parametrize("tenant", ["", "evil.com/", "acme.weclapp.com", "-acme", "ac me"])
def test_invalid_tenant_names_are_rejected(tenant: str) -> None:
    with pytest.raises(WeclappConfigurationError):
        tenant_base_url(tenant)


def test_from_env_prefers_the_base_url() -> None:
    config = WeclappConfig.from_env(
        {
            "WECLAPP_API_TOKEN": "secret",
            "WECLAPP_BASE_URL": "https://custom.example.test/webapp/api/v2/",
            "WECLAPP_TENANT": "acme",
        }
    )
    assert config.base_url == "https://custom.example.test/webapp/api/v2/"


def test_from_env_falls_back_to_the_tenant() -> None:
    config = WeclappConfig.from_env({"WECLAPP_API_TOKEN": "secret", "WECLAPP_TENANT": "acme"}, max_retries=1)
    assert config.base_url == "https://acme.weclapp.com/webapp/api/v2/"
    assert config.max_retries == 1


def test_from_env_reads_os_environ_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WECLAPP_API_TOKEN", "secret")
    monkeypatch.setenv("WECLAPP_TENANT", "acme")
    monkeypatch.delenv("WECLAPP_BASE_URL", raising=False)
    assert WeclappConfig.from_env().base_url == "https://acme.weclapp.com/webapp/api/v2/"


@pytest.mark.parametrize(
    "environ",
    [
        {"WECLAPP_TENANT": "acme"},
        {"WECLAPP_API_TOKEN": "  ", "WECLAPP_TENANT": "acme"},
        {"WECLAPP_API_TOKEN": "secret"},
    ],
)
def test_from_env_reports_missing_variables(environ: dict[str, str]) -> None:
    with pytest.raises(WeclappConfigurationError):
        WeclappConfig.from_env(environ)


def test_token_is_hidden_in_repr_and_str() -> None:
    config = WeclappConfig.for_tenant("acme", "super-secret-token")
    assert "super-secret-token" not in repr(config)
    assert "super-secret-token" not in str(config)

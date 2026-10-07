import weclapp_client


def test_version_is_available() -> None:
    assert weclapp_client.__version__
    assert weclapp_client.__version__ != "0.0.0"

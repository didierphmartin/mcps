import pytest

from config import Config
from errors import ConnectorError

FULL = {"SN_INSTANCE": "https://dev1.service-now.com/", "SN_CLIENT_ID": "abc", "SN_CLIENT_SECRET": "s3cr$t!+#x",
        "SN_GROUP": "SynergyAI", "SN_TAG_PREFIX": "synergyai:"}


def code(env):
    with pytest.raises(ConnectorError) as e:
        Config.from_env(env)
    return f"{e.value.code}|{e.value}"


def test_loads_the_settings():
    c = Config.from_env(FULL)
    assert c.instance == "https://dev1.service-now.com"
    assert c.client_secret == "s3cr$t!+#x"
    assert (c.group, c.tag_prefix, c.timeout) == ("SynergyAI", "synergyai:", 20)
    assert not c.is_mock


def test_environment():
    assert Config.from_env(FULL).environment == "prod"
    assert Config.from_env({**FULL, "SN_ENVIRONMENT": "test"}).environment == "test"
    assert code({**FULL, "SN_ENVIRONMENT": "staging"}).startswith("bad_config|")
    assert Config.mock().environment == "dev"


def test_mock_needs_nothing_else():
    c = Config.from_env({"SN_INSTANCE": "mock"})
    assert c.is_mock
    assert (c.group, c.tag_prefix, c.environment) == ("SynergyAI", "synergyai:", "dev")


def test_mock_keeps_its_deploy_token():
    assert Config.from_env({"SN_INSTANCE": "mock", "SN_DEPLOY_TOKEN": "t"}).deploy_token == "t"


def test_nothing_set():
    assert code({}).startswith("bad_config|missing SN_INSTANCE")


def test_names_missing_keys_never_values():
    msg = code({"SN_INSTANCE": "https://x.service-now.com", "SN_CLIENT_SECRET": "topsecret"})
    assert "SN_CLIENT_ID" in msg
    assert "topsecret" not in msg


def test_rejects_plain_http_and_caret_values():
    assert code({**FULL, "SN_INSTANCE": "http://dev1.service-now.com"}).startswith("bad_config|")
    assert code({**FULL, "SN_GROUP": "Synergy^ORactive=true"}).startswith("bad_config|")
    assert code({**FULL, "SN_TAG_PREFIX": "x^y"}).startswith("bad_config|")


@pytest.mark.parametrize("extra,expected", [
    ({}, (5, 120)),
    ({"SN_WAIT_INTERVAL_S": "2", "SN_WAIT_WINDOW_S": "30"}, (2, 30)),
    ({"SN_WAIT_INTERVAL_S": "0", "SN_WAIT_WINDOW_S": "999"}, (5, 140)),     # 0 -> default; window capped
    ({"SN_WAIT_INTERVAL_S": "abc"}, (5, 120)),                              # text -> default
    ({"SN_WAIT_INTERVAL_S": "10", "SN_WAIT_WINDOW_S": "4"}, (10, 10)),     # window never shorter than one interval
    ({"SN_WAIT_INTERVAL_S": "300"}, (140, 140)),                            # interval capped too
])
def test_wait_settings_defaults_and_clamps(extra, expected):
    c = Config.from_env({**FULL, **extra})
    assert (c.wait_interval, c.wait_window) == expected


def test_mock_wait_defaults():
    assert (Config.mock().wait_interval, Config.mock().wait_window) == (5, 120)


def test_optional_settings():
    c = Config.from_env({**FULL, "SN_TIMEOUT": "7", "SN_NPX": "/opt/node/bin/npx", "SN_INSTALL_USER": "u",
                         "SN_INSTALL_PASSWORD": "p", "SN_DEPLOY_TOKEN": "t"})
    assert (c.timeout, c.npx, c.install_user, c.install_password, c.deploy_token) == (7, "/opt/node/bin/npx", "u", "p", "t")
    assert Config.from_env({**FULL, "SN_NPX": ""}).npx == "npx"

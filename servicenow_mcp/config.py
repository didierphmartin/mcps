"""One ServiceNow instance, from the environment (run.sh loads .env), or the built-in fake one (SN_INSTANCE=mock)."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

from errors import ConnectorError

REQUIRED = ("SN_INSTANCE", "SN_CLIENT_ID", "SN_CLIENT_SECRET", "SN_GROUP", "SN_TAG_PREFIX")
_DIGITS = re.compile(r"[0-9]+")


@dataclass(frozen=True)
class Config:
    instance: str
    client_id: str = ""
    client_secret: str = ""
    group: str = "SynergyAI"
    tag_prefix: str = "synergyai:"
    timeout: int = 20
    wait_interval: int = 5
    wait_window: int = 120
    environment: str = "prod"
    install_user: str = ""
    install_password: str = ""
    npx: str = "npx"
    deploy_token: str = ""

    @property
    def is_mock(self) -> bool:
        return self.instance == "mock"

    @classmethod
    def mock(cls, deploy_token: str = "") -> "Config":
        return cls(instance="mock", environment="dev", deploy_token=deploy_token)

    @classmethod
    def from_env(cls, env: dict | None = None) -> "Config":
        """The settings in `env` (default os.environ); a bad or missing one is a bad_config error."""
        v = {k: str(x) for k, x in (os.environ if env is None else env).items()}
        if v.get("SN_INSTANCE", "") == "mock":
            return cls.mock(v.get("SN_DEPLOY_TOKEN", ""))
        missing = [k for k in REQUIRED if v.get(k, "") == ""]
        if missing:
            raise ConnectorError("bad_config", "missing " + ", ".join(missing))
        if not v["SN_INSTANCE"].startswith("https://"):
            raise ConnectorError("bad_config", "SN_INSTANCE must start with https:// (or be mock)")
        for k in ("SN_GROUP", "SN_TAG_PREFIX"):
            if "^" in v[k]:
                raise ConnectorError("bad_config", f"{k} must not contain '^'")
        environment = v.get("SN_ENVIRONMENT", "") or "prod"
        if environment not in ("dev", "test", "prod"):
            raise ConnectorError("bad_config", "SN_ENVIRONMENT must be dev, test or prod")
        digits = lambda k: _DIGITS.fullmatch(v.get(k, "")) is not None  # noqa: E731
        timeout = max(1, int(v["SN_TIMEOUT"])) if digits("SN_TIMEOUT") else 20
        interval = min(140, int(v["SN_WAIT_INTERVAL_S"])) if digits("SN_WAIT_INTERVAL_S") and int(v["SN_WAIT_INTERVAL_S"]) >= 1 else 5
        window = int(v["SN_WAIT_WINDOW_S"]) if digits("SN_WAIT_WINDOW_S") and int(v["SN_WAIT_WINDOW_S"]) >= 1 else 120
        window = min(140, max(window, interval))
        return cls(instance=v["SN_INSTANCE"].rstrip("/"), client_id=v["SN_CLIENT_ID"], client_secret=v["SN_CLIENT_SECRET"],
                   group=v["SN_GROUP"], tag_prefix=v["SN_TAG_PREFIX"], timeout=timeout, wait_interval=interval,
                   wait_window=window, environment=environment, install_user=v.get("SN_INSTALL_USER", ""),
                   install_password=v.get("SN_INSTALL_PASSWORD", ""), npx=v.get("SN_NPX", "") or "npx",
                   deploy_token=v.get("SN_DEPLOY_TOKEN", ""))

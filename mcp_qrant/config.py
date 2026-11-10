from __future__ import annotations

import os
from dataclasses import dataclass

_DEFAULT_PROVIDERS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "providers")


@dataclass
class AppConfig:
    providers_dir: str = _DEFAULT_PROVIDERS_DIR
    host: str = "127.0.0.1"
    port: int = 8008

    @classmethod
    def from_env(cls) -> "AppConfig":
        return cls(
            providers_dir=os.environ.get("MCPQ_PROVIDERS_DIR", _DEFAULT_PROVIDERS_DIR),
            host=os.environ.get("MCPQ_HOST", "127.0.0.1"),
            port=int(os.environ.get("MCPQ_PORT", "8008")),
        )

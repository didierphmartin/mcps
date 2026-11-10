from __future__ import annotations

import os
from dataclasses import dataclass, field


_DEFAULT_PROVIDERS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "providers")


@dataclass
class AppConfig:
    allowed_roots: list[str]
    providers_dir: str = ""
    cursor_ttl_seconds: int = 3600
    host: str = "127.0.0.1"
    port: int = 8077

    def __post_init__(self):
        if not self.providers_dir:
            self.providers_dir = _DEFAULT_PROVIDERS_DIR

    @classmethod
    def from_env(cls) -> "AppConfig":
        roots_raw = os.environ.get("LANGFS_ROOTS", "").strip()
        roots = [r.strip() for r in roots_raw.split(":") if r.strip()] if roots_raw else []
        return cls(
            allowed_roots=roots,
            providers_dir=os.environ.get("LANGFS_PROVIDERS_DIR", _DEFAULT_PROVIDERS_DIR),
            cursor_ttl_seconds=int(os.environ.get("LANGFS_CURSOR_TTL", "3600")),
            host=os.environ.get("LANGFS_HOST", "127.0.0.1"),
            port=int(os.environ.get("LANGFS_PORT", "8077")),
        )

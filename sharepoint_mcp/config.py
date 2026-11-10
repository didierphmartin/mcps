"""SharePoint MCP server settings, from the environment (run.sh loads .env)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from cryptography.fernet import Fernet


@dataclass(frozen=True)
class AppConfig:
    client_id: str                      # Entra ID app registration (any org + personal accounts)
    secret_key: str                     # Fernet key: encrypts refresh tokens at rest
    db_path: str
    client_secret: str = ""             # redirect fallback with a confidential app only
    public_url: str = ""                # https://... or http://localhost...: enables the redirect fallback
    authority: str = "https://login.microsoftonline.com/common"
    graph_base: str = "https://graph.microsoft.com/v1.0"
    host: str = "127.0.0.1"
    port: int = 8771
    site: str = ""                      # default site, "contoso.sharepoint.com:/sites/Team"; tool args override
    library: str = ""                   # default document library name; tool args override
    mock_graph: bool = False

    SCOPES: ClassVar[str] = "openid profile offline_access User.Read Sites.ReadWrite.All"

    @staticmethod
    def new_secret_key() -> str:
        return Fernet.generate_key().decode()

    @classmethod
    def from_env(cls) -> "AppConfig":
        env = os.environ
        mock = env.get("SHAREPOINT_MOCK_GRAPH", "") == "1"
        if not mock:
            missing = [n for n in ("SHAREPOINT_CLIENT_ID", "SHAREPOINT_SECRET_KEY") if not env.get(n)]
            if missing:
                raise SystemExit(f"missing in .env: {', '.join(missing)} (see README)")
        return cls(
            client_id=env.get("SHAREPOINT_CLIENT_ID", "mock-client"),
            secret_key=env.get("SHAREPOINT_SECRET_KEY") or cls.new_secret_key(),
            db_path=env.get("SHAREPOINT_DB_PATH") or str(Path.home() / "Documents" / "synergyAI" / "sharepoint_mcp.sqlite"),
            client_secret=env.get("SHAREPOINT_CLIENT_SECRET", ""),
            public_url=env.get("SHAREPOINT_PUBLIC_URL", "").rstrip("/"),
            host=env.get("SHAREPOINT_HOST", "127.0.0.1"),
            port=int(env.get("SHAREPOINT_PORT", "8771")),
            site=env.get("SHAREPOINT_SITE", ""),
            library=env.get("SHAREPOINT_LIBRARY", ""),
            mock_graph=mock,
        )

"""Paths, credentials and WHOOP API constants."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# WHOOP API v2. If WHOOP changes a path, this is the only place to fix it.
API_BASE = "https://api.prod.whoop.com/developer"
AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"

PATH_PROFILE = "/v2/user/profile/basic"
PATH_BODY = "/v2/user/measurement/body"
PATH_CYCLES = "/v2/cycle"
PATH_RECOVERY = "/v2/recovery"
PATH_SLEEP = "/v2/activity/sleep"
PATH_WORKOUT = "/v2/activity/workout"

# "offline" is what makes WHOOP return a refresh token.
SCOPES = [
    "offline",
    "read:profile",
    "read:body_measurement",
    "read:cycles",
    "read:recovery",
    "read:sleep",
    "read:workout",
]


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader so the project needs no extra dependency."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class Settings:
    client_id: str
    client_secret: str
    redirect_uri: str
    home: Path

    @property
    def token_file(self) -> Path:
        return self.home / "tokens.json"

    @property
    def db_file(self) -> Path:
        return self.home / "whoop_mcp.db"


def load_settings() -> Settings:
    _load_dotenv(Path.cwd() / ".env")
    home = Path(os.environ.get("WHOOP_MCP_HOME", "~/.whoop-mcp")).expanduser()
    _load_dotenv(home / ".env")
    home.mkdir(parents=True, exist_ok=True)
    return Settings(
        client_id=os.environ.get("WHOOP_CLIENT_ID", ""),
        client_secret=os.environ.get("WHOOP_CLIENT_SECRET", ""),
        redirect_uri=os.environ.get("WHOOP_REDIRECT_URI", "http://localhost:8765/callback"),
        home=home,
    )

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
    timezone: str = "Europe/Lisbon"
    # Remote mode only: secret that goes in the MCP URL, and the server's public https URL.
    access_key: str = ""
    public_url: str = ""
    # Postgres URL. When set, food log, profile and WHOOP tokens go there instead of files.
    database_url: str = ""

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
    try:
        home.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass  # read-only filesystem (serverless); fine when DATABASE_URL is set
    public_url = os.environ.get("PUBLIC_URL", "")
    # Hosts that announce their own domain: Vercel, Railway, Render.
    for var in ("VERCEL_PROJECT_PRODUCTION_URL", "RAILWAY_PUBLIC_DOMAIN"):
        if not public_url and os.environ.get(var):
            public_url = "https://" + os.environ[var]
    if not public_url and os.environ.get("RENDER_EXTERNAL_URL"):
        public_url = os.environ["RENDER_EXTERNAL_URL"]
    public_url = public_url.rstrip("/")
    default_redirect = f"{public_url}/whoop/callback" if public_url else "http://localhost:8765/callback"
    return Settings(
        client_id=os.environ.get("WHOOP_CLIENT_ID", ""),
        client_secret=os.environ.get("WHOOP_CLIENT_SECRET", ""),
        redirect_uri=os.environ.get("WHOOP_REDIRECT_URI", default_redirect),
        home=home,
        timezone=os.environ.get("TIMEZONE", "Europe/Lisbon"),
        access_key=os.environ.get("ACCESS_KEY", ""),
        public_url=public_url,
        database_url=os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL", ""),
    )

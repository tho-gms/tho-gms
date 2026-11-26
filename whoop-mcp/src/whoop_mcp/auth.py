"""OAuth 2.0 authorization-code flow and token storage for WHOOP."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx

from .config import AUTH_URL, SCOPES, TOKEN_URL, Settings


class AuthError(RuntimeError):
    pass


class TokenStore:
    """Keeps WHOOP tokens in a file (local) or in the database (`storage`, for serverless hosts)."""

    KEY = "whoop_tokens"

    def __init__(self, path: Path | None = None, storage=None):
        self.path = path
        self.storage = storage

    def _read(self) -> str | None:
        if self.storage is not None:
            return self.storage.kv_get(self.KEY)
        return self.path.read_text() if self.path and self.path.is_file() else None

    def _write(self, text: str) -> None:
        if self.storage is not None:
            self.storage.kv_set(self.KEY, text)
            return
        self.path.write_text(text)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def load(self) -> dict | None:
        text = self._read()
        return json.loads(text) if text else None

    def save(self, payload: dict) -> dict:
        data = {
            "access_token": payload["access_token"],
            # WHOOP rotates refresh tokens: keep the old one only if no new one came back.
            "refresh_token": payload.get("refresh_token") or (self.load() or {}).get("refresh_token"),
            "expires_at": time.time() + int(payload.get("expires_in", 3600)) - 60,
        }
        self._write(json.dumps(data, indent=2))
        return data

    @property
    def location(self) -> str:
        return "database" if self.storage is not None else str(self.path)


def make_state(secret: str) -> str:
    """OAuth state signed with `secret`, so no server memory is needed to check it."""
    body = f"{int(time.time())}.{secrets.token_urlsafe(12)}"
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{body}.{sig}"


def check_state(secret: str, state: str, max_age: int = 600) -> bool:
    try:
        ts, nonce, sig = state.split(".")
        age = time.time() - int(ts)
    except ValueError:
        return False
    expected = hmac.new(secret.encode(), f"{ts}.{nonce}".encode(), hashlib.sha256).hexdigest()[:32]
    return hmac.compare_digest(sig, expected) and 0 <= age <= max_age


def _exchange(settings: Settings, data: dict) -> dict:
    body = {"client_id": settings.client_id, "client_secret": settings.client_secret, **data}
    resp = httpx.post(TOKEN_URL, data=body, timeout=30)
    if resp.status_code >= 400:
        raise AuthError(f"Token request failed ({resp.status_code}): {resp.text}")
    return resp.json()


def refresh(settings: Settings, store: TokenStore) -> dict:
    tokens = store.load()
    if not tokens or not tokens.get("refresh_token"):
        raise AuthError("No WHOOP refresh token stored. Reconnect with whoop_connect_link or `whoop-mcp auth`.")
    payload = _exchange(
        settings,
        {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "scope": "offline"},
    )
    return store.save(payload)


def get_access_token(settings: Settings, store: TokenStore) -> str:
    tokens = store.load()
    if not tokens:
        raise AuthError("Not connected to WHOOP yet. Use the whoop_connect_link tool (phone) or run `whoop-mcp auth` (computer).")
    if time.time() >= tokens.get("expires_at", 0):
        tokens = refresh(settings, store)
    return tokens["access_token"]


def build_auth_url(settings: Settings, state: str) -> str:
    if not settings.client_id or not settings.client_secret:
        raise AuthError("Set WHOOP_CLIENT_ID and WHOOP_CLIENT_SECRET (see .env.example).")
    return AUTH_URL + "?" + urllib.parse.urlencode(
        {
            "client_id": settings.client_id,
            "redirect_uri": settings.redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "state": state,
        }
    )


def exchange_code(settings: Settings, store: TokenStore, code: str) -> None:
    payload = _exchange(
        settings, {"grant_type": "authorization_code", "code": code, "redirect_uri": settings.redirect_uri}
    )
    store.save(payload)


def run_auth_flow(settings: Settings, store: TokenStore) -> None:
    """Local mode: open the browser, wait for the redirect on localhost, store tokens."""
    redirect = urllib.parse.urlparse(settings.redirect_uri)
    if redirect.hostname not in ("localhost", "127.0.0.1"):
        raise AuthError("WHOOP_REDIRECT_URI must point to localhost for the local auth flow.")

    state = secrets.token_urlsafe(16)
    url = build_auth_url(settings, state)
    result: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != redirect.path:
                self.send_response(404)
                self.end_headers()
                return
            qs = urllib.parse.parse_qs(parsed.query)
            result["code"] = (qs.get("code") or [None])[0]
            result["state"] = (qs.get("state") or [None])[0]
            result["error"] = (qs.get("error_description") or qs.get("error") or [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = "Autorizado. Podes fechar esta janela." if result["code"] else "Falhou a autorização."
            self.wfile.write(f"<h2>{msg}</h2>".encode())

        def log_message(self, *args):
            pass

    server = HTTPServer((redirect.hostname, redirect.port or 80), Handler)
    print("A abrir o browser para autorizar a WHOOP. Se não abrir, visita:\n" + url)
    webbrowser.open(url)
    while "code" not in result:
        server.handle_request()
    server.server_close()

    if result.get("error") or not result.get("code"):
        raise AuthError(f"Authorization failed: {result.get('error')}")
    if result.get("state") != state:
        raise AuthError("State mismatch in OAuth callback; aborting.")
    exchange_code(settings, store, result["code"])
    print(f"Tokens guardados em {store.location}")

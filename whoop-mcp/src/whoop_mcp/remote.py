"""Remote mode: serve the MCP tools over HTTP so the Claude phone app can use them.

URLs (ACCESS_KEY is a long random secret you choose):
  {PUBLIC_URL}/{ACCESS_KEY}/mcp           MCP endpoint, added as a custom connector in Claude
  {PUBLIC_URL}/{ACCESS_KEY}/whoop/login   opens the WHOOP login
  {PUBLIC_URL}/whoop/callback             WHOOP redirects here after login
"""

from __future__ import annotations

import html
import os
import secrets
import sys
import time

from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from .auth import AuthError, TokenStore, build_auth_url, exchange_code
from .config import load_settings
from .server import mcp

_STATE_TTL = 600
_pending_states: dict[str, float] = {}


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
        "<body style='font-family:system-ui;max-width:32rem;margin:3rem auto;padding:0 1rem;line-height:1.5'>"
        f"<h2>{html.escape(title)}</h2><p>{body}</p></body>",
        status_code=status,
    )


def create_app():
    settings = load_settings()
    if len(settings.access_key) < 24:
        sys.exit("Set ACCESS_KEY to a random string of at least 24 characters.")
    if not settings.public_url:
        sys.exit("Set PUBLIC_URL to the server's https address.")
    key = settings.access_key
    store = TokenStore(settings.token_file)

    @mcp.custom_route("/", methods=["GET"], include_in_schema=False)
    async def health(request: Request):
        return PlainTextResponse("ok")

    @mcp.custom_route(f"/{key}/whoop/login", methods=["GET"], include_in_schema=False)
    async def login(request: Request):
        now = time.time()
        for s, t in list(_pending_states.items()):
            if now - t > _STATE_TTL:
                _pending_states.pop(s, None)
        state = secrets.token_urlsafe(16)
        _pending_states[state] = now
        try:
            return RedirectResponse(build_auth_url(settings, state))
        except AuthError as e:
            return _page("Configuração em falta", html.escape(str(e)), 500)

    @mcp.custom_route("/whoop/callback", methods=["GET"], include_in_schema=False)
    async def callback(request: Request):
        q = request.query_params
        state = q.get("state", "")
        if state not in _pending_states:
            return _page("Link expirado", "Volta a abrir o link de ligação à WHOOP.", 400)
        _pending_states.pop(state, None)
        if q.get("error") or not q.get("code"):
            msg = html.escape(q.get("error_description") or q.get("error") or "sem código")
            return _page("A WHOOP recusou a ligação", msg, 400)
        try:
            exchange_code(settings, store, q["code"])
        except AuthError as e:
            return _page("Falhou a ligação", html.escape(str(e)), 502)
        return _page("WHOOP ligada", "Podes fechar esta página e voltar ao Claude.")

    return mcp.streamable_http_app(
        streamable_http_path=f"/{key}/mcp",
        host="0.0.0.0",
        # Public server behind a secret path; Host-header checks are for localhost servers.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )


def run() -> None:
    import uvicorn

    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8000")),
                proxy_headers=True, forwarded_allow_ips="*")

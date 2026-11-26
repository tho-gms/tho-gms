"""Remote mode: serve the MCP tools over HTTP so the Claude phone app can use them.

URLs (ACCESS_KEY is a long random secret you choose):
  {PUBLIC_URL}/{ACCESS_KEY}/mcp           MCP endpoint, added as a custom connector in Claude
  {PUBLIC_URL}/{ACCESS_KEY}/whoop/login   opens the WHOOP login
  {PUBLIC_URL}/whoop/callback             WHOOP redirects here after login

Every MCP request is handled on its own (stateless, JSON responses), so this runs on
serverless hosts such as Vercel, where nothing stays in memory between requests and the
ASGI lifespan may never run.
"""

from __future__ import annotations

import html
import os

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from starlette.routing import Route

from .auth import AuthError, build_auth_url, check_state, exchange_code, make_state
from .config import load_settings
from .server import mcp, service

# Public server behind a secret path; Host-header checks only matter for localhost servers.
_SECURITY = TransportSecuritySettings(enable_dns_rebinding_protection=False)


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
        "<body style='font-family:system-ui;max-width:32rem;margin:3rem auto;padding:0 1rem;line-height:1.5'>"
        f"<h2>{html.escape(title)}</h2><p>{body}</p></body>",
        status_code=status,
    )


def _config_error(msg: str):
    async def app(scope, receive, send):
        if scope["type"] == "http":
            await PlainTextResponse(f"whoop-mcp is not configured: {msg}", status_code=500)(scope, receive, send)
    return app


def create_app():
    settings = load_settings()
    if len(settings.access_key) < 24:
        return _config_error("set ACCESS_KEY to a random string of at least 24 letters and digits.")
    if not settings.public_url:
        return _config_error("set PUBLIC_URL to the server's https address.")
    key = settings.access_key
    mcp_path = f"/{key}/mcp"

    async def health(request: Request):
        return PlainTextResponse("ok")

    async def login(request: Request):
        try:
            return RedirectResponse(build_auth_url(settings, make_state(key)))
        except AuthError as e:
            return _page("Configuração em falta", html.escape(str(e)), 500)

    async def callback(request: Request):
        q = request.query_params
        if not check_state(key, q.get("state", "")):
            return _page("Link expirado", "Volta a pedir ao Claude o link de ligação à WHOOP.", 400)
        if q.get("error") or not q.get("code"):
            msg = html.escape(q.get("error_description") or q.get("error") or "sem código")
            return _page("A WHOOP recusou a ligação", msg, 400)
        try:
            exchange_code(settings, service().client.store, q["code"])
        except AuthError as e:
            return _page("Falhou a ligação", html.escape(str(e)), 502)
        return _page("WHOOP ligada", "Podes fechar esta página e voltar ao Claude.")

    pages = Starlette(routes=[
        Route("/", health),
        Route(f"/{key}/whoop/login", login),
        Route("/whoop/callback", callback),
    ])

    async def app(scope, receive, send):
        if scope["type"] == "http" and scope["path"].rstrip("/") == mcp_path:
            manager = StreamableHTTPSessionManager(
                app=mcp._lowlevel_server, stateless=True, json_response=True, security_settings=_SECURITY
            )
            async with manager.run():
                await manager.handle_request(scope, receive, send)
        else:
            await pages(scope, receive, send)

    return app


def run() -> None:
    import uvicorn

    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8000")),
                proxy_headers=True, forwarded_allow_ips="*")

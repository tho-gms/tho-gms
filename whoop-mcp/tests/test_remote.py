import urllib.parse

import httpx
import respx
from starlette.testclient import TestClient

from whoop_mcp import config, server

KEY = "k" * 32


def test_whoop_login_and_callback_store_tokens(tmp_path, monkeypatch):
    monkeypatch.setenv("ACCESS_KEY", KEY)
    monkeypatch.setenv("PUBLIC_URL", "https://example.test")
    monkeypatch.setenv("WHOOP_CLIENT_ID", "cid")
    monkeypatch.setenv("WHOOP_CLIENT_SECRET", "sec")
    monkeypatch.setenv("WHOOP_MCP_HOME", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(server, "_service", None)

    from whoop_mcp.remote import create_app

    client = TestClient(create_app())
    assert client.get(f"/wrong/whoop/login", follow_redirects=False).status_code == 404

    r = client.get(f"/{KEY}/whoop/login", follow_redirects=False)
    assert r.status_code == 307
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(r.headers["location"]).query)
    assert qs["redirect_uri"] == ["https://example.test/whoop/callback"]

    with respx.mock(assert_all_called=True) as mock:
        token = mock.post(config.TOKEN_URL).mock(return_value=httpx.Response(
            200, json={"access_token": "at", "refresh_token": "rt", "expires_in": 3600}))
        r = client.get("/whoop/callback", params={"state": qs["state"][0], "code": "the-code"})
    assert r.status_code == 200 and "WHOOP ligada" in r.text
    assert b"code=the-code" in token.calls[0].request.content
    assert server.service().client.store.load()["refresh_token"] == "rt"

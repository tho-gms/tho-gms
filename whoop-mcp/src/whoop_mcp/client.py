"""Thin WHOOP API v2 client with token refresh and pagination."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from . import config
from .auth import TokenStore, get_access_token, refresh
from .config import Settings


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class WhoopClient:
    def __init__(self, settings: Settings, http: httpx.Client | None = None):
        self.settings = settings
        self.store = TokenStore(settings.token_file)
        self.http = http or httpx.Client(base_url=config.API_BASE, timeout=30)

    def _get(self, path: str, params: dict | None = None) -> dict:
        token = get_access_token(self.settings, self.store)
        resp = self.http.get(path, params=params, headers={"Authorization": f"Bearer {token}"})
        if resp.status_code == 401:
            token = refresh(self.settings, self.store)["access_token"]
            resp = self.http.get(path, params=params, headers={"Authorization": f"Bearer {token}"})
        resp.raise_for_status()
        return resp.json()

    def _collection(self, path: str, start: datetime, end: datetime) -> list[dict]:
        records: list[dict] = []
        params = {"start": _iso(start), "end": _iso(end), "limit": 25}
        while True:
            page = self._get(path, params)
            records.extend(page.get("records", []))
            token = page.get("next_token") or page.get("nextToken")
            if not token:
                return records
            params = {**params, "nextToken": token}

    def profile(self) -> dict:
        return self._get(config.PATH_PROFILE)

    def body_measurement(self) -> dict:
        return self._get(config.PATH_BODY)

    def cycles(self, start: datetime, end: datetime) -> list[dict]:
        return self._collection(config.PATH_CYCLES, start, end)

    def recoveries(self, start: datetime, end: datetime) -> list[dict]:
        return self._collection(config.PATH_RECOVERY, start, end)

    def sleeps(self, start: datetime, end: datetime) -> list[dict]:
        return self._collection(config.PATH_SLEEP, start, end)

    def workouts(self, start: datetime, end: datetime) -> list[dict]:
        return self._collection(config.PATH_WORKOUT, start, end)

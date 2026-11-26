"""Store for food intake, weight entries, profile and WHOOP tokens.

WHOOP has no nutrition API, so what you eat lives here. Uses SQLite for a file path
and Postgres for a postgres:// URL (for hosts without a persistent disk).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS food (
    id {id_col},
    day TEXT NOT NULL,
    logged_at TEXT NOT NULL,
    description TEXT NOT NULL,
    kcal {real} NOT NULL,
    protein_g {real},
    carbs_g {real},
    fat_g {real},
    meal TEXT
);
CREATE INDEX IF NOT EXISTS food_day ON food(day);
CREATE TABLE IF NOT EXISTS weight (
    day TEXT PRIMARY KEY,
    kg {real} NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual'
);
CREATE TABLE IF NOT EXISTS profile (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

PROFILE_DEFAULTS = {
    "sex": None,  # "male" | "female"
    "birth_date": None,  # "YYYY-MM-DD"
    "height_cm": None,  # falls back to WHOOP body measurement
    "job_activity": "sedentary",  # sedentary | light | moderate | heavy
    "expenditure_correction_pct": 0.0,  # calibrate WHOOP calories, e.g. -10
    "target_deficit_kcal": 500,
}


class Storage:
    def __init__(self, target: Path | str):
        target = str(target)
        self.is_pg = target.startswith(("postgres://", "postgresql://"))
        self._target = target
        self._lock = threading.Lock()
        self.conn = None
        self._connect()
        if self.is_pg:
            schema = SCHEMA.format(id_col="BIGSERIAL PRIMARY KEY", real="DOUBLE PRECISION")
        else:
            schema = SCHEMA.format(id_col="INTEGER PRIMARY KEY AUTOINCREMENT", real="REAL")
        for stmt in schema.split(";"):
            if stmt.strip():
                self._run(stmt)

    def _connect(self) -> None:
        if self.is_pg:
            import psycopg
            from psycopg.rows import dict_row

            self.conn = psycopg.connect(self._target, autocommit=True, row_factory=dict_row)
        else:
            self.conn = sqlite3.connect(self._target, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row

    def _run(self, sql: str, params: tuple = ()) -> tuple[list[dict], int]:
        """Execute one statement; return (rows as dicts, rowcount)."""
        if self.is_pg:
            sql = sql.replace("?", "%s")
        with self._lock:
            for attempt in (0, 1):
                try:
                    cur = self.conn.execute(sql, params)
                    rows = [dict(r) for r in cur.fetchall()] if cur.description else []
                    if not self.is_pg:
                        self.conn.commit()
                    return rows, cur.rowcount
                except Exception as e:  # noqa: BLE001
                    # Serverless Postgres drops idle connections: reconnect once.
                    if self.is_pg and attempt == 0 and type(e).__name__ in ("OperationalError", "InterfaceError"):
                        self._connect()
                        continue
                    raise
        raise RuntimeError("unreachable")

    # key-value (WHOOP tokens) -----------------------------------------
    def kv_get(self, key: str) -> str | None:
        rows, _ = self._run("SELECT value FROM kv WHERE key = ?", (key,))
        return rows[0]["value"] if rows else None

    def kv_set(self, key: str, value: str) -> None:
        self._run(
            "INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    # food -------------------------------------------------------------
    def add_food(
        self,
        day: date,
        description: str,
        kcal: float,
        protein_g: float | None = None,
        carbs_g: float | None = None,
        fat_g: float | None = None,
        meal: str | None = None,
    ) -> int:
        rows, _ = self._run(
            "INSERT INTO food (day, logged_at, description, kcal, protein_g, carbs_g, fat_g, meal)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
            (day.isoformat(), datetime.now().isoformat(timespec="seconds"), description, kcal,
             protein_g, carbs_g, fat_g, meal),
        )
        return int(rows[0]["id"])

    def delete_food(self, entry_id: int) -> bool:
        _, count = self._run("DELETE FROM food WHERE id = ?", (entry_id,))
        return count > 0

    def food_for_day(self, day: date) -> list[dict]:
        rows, _ = self._run("SELECT * FROM food WHERE day = ? ORDER BY id", (day.isoformat(),))
        return rows

    def food_totals(self, start: date, end: date) -> dict[str, dict]:
        rows, _ = self._run(
            "SELECT day, SUM(kcal) AS kcal, SUM(protein_g) AS protein_g, SUM(carbs_g) AS carbs_g,"
            " SUM(fat_g) AS fat_g, COUNT(*) AS entries FROM food WHERE day BETWEEN ? AND ? GROUP BY day",
            (start.isoformat(), end.isoformat()),
        )
        return {r["day"]: r for r in rows}

    # weight -----------------------------------------------------------
    def set_weight(self, day: date, kg: float, source: str = "manual") -> None:
        self._run(
            "INSERT INTO weight (day, kg, source) VALUES (?, ?, ?)"
            " ON CONFLICT(day) DO UPDATE SET kg = excluded.kg, source = excluded.source",
            (day.isoformat(), kg, source),
        )

    def weights(self, start: date, end: date) -> list[dict]:
        rows, _ = self._run(
            "SELECT day, kg, source FROM weight WHERE day BETWEEN ? AND ? ORDER BY day",
            (start.isoformat(), end.isoformat()),
        )
        return rows

    def latest_weight(self) -> dict | None:
        rows, _ = self._run("SELECT day, kg, source FROM weight ORDER BY day DESC LIMIT 1")
        return rows[0] if rows else None

    # profile ----------------------------------------------------------
    def get_profile(self) -> dict:
        profile = dict(PROFILE_DEFAULTS)
        for r in self._run("SELECT key, value FROM profile")[0]:
            profile[r["key"]] = json.loads(r["value"])
        return profile

    def update_profile(self, **values) -> dict:
        for key, value in values.items():
            if key not in PROFILE_DEFAULTS:
                raise ValueError(f"Unknown profile field: {key}")
            if value is None:
                continue
            self._run(
                "INSERT INTO profile (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)),
            )
        return self.get_profile()

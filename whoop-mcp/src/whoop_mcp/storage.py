"""Local SQLite store for food intake, weight entries and user profile.

WHOOP has no nutrition API, so what you eat lives here.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS food (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    logged_at TEXT NOT NULL,
    description TEXT NOT NULL,
    kcal REAL NOT NULL,
    protein_g REAL,
    carbs_g REAL,
    fat_g REAL,
    meal TEXT
);
CREATE INDEX IF NOT EXISTS food_day ON food(day);
CREATE TABLE IF NOT EXISTS weight (
    day TEXT PRIMARY KEY,
    kg REAL NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual'
);
CREATE TABLE IF NOT EXISTS profile (
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
    def __init__(self, path: Path | str):
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

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
        cur = self.conn.execute(
            "INSERT INTO food (day, logged_at, description, kcal, protein_g, carbs_g, fat_g, meal)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (day.isoformat(), datetime.now().isoformat(timespec="seconds"), description, kcal,
             protein_g, carbs_g, fat_g, meal),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def delete_food(self, entry_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM food WHERE id = ?", (entry_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def food_for_day(self, day: date) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM food WHERE day = ? ORDER BY id", (day.isoformat(),))
        return [dict(r) for r in rows]

    def food_totals(self, start: date, end: date) -> dict[str, dict]:
        rows = self.conn.execute(
            "SELECT day, SUM(kcal) kcal, SUM(protein_g) protein_g, SUM(carbs_g) carbs_g,"
            " SUM(fat_g) fat_g, COUNT(*) entries FROM food WHERE day BETWEEN ? AND ? GROUP BY day",
            (start.isoformat(), end.isoformat()),
        )
        return {r["day"]: dict(r) for r in rows}

    # weight -----------------------------------------------------------
    def set_weight(self, day: date, kg: float, source: str = "manual") -> None:
        self.conn.execute(
            "INSERT INTO weight (day, kg, source) VALUES (?, ?, ?)"
            " ON CONFLICT(day) DO UPDATE SET kg = excluded.kg, source = excluded.source",
            (day.isoformat(), kg, source),
        )
        self.conn.commit()

    def weights(self, start: date, end: date) -> list[dict]:
        rows = self.conn.execute(
            "SELECT day, kg, source FROM weight WHERE day BETWEEN ? AND ? ORDER BY day",
            (start.isoformat(), end.isoformat()),
        )
        return [dict(r) for r in rows]

    def latest_weight(self) -> dict | None:
        row = self.conn.execute("SELECT day, kg, source FROM weight ORDER BY day DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    # profile ----------------------------------------------------------
    def get_profile(self) -> dict:
        profile = dict(PROFILE_DEFAULTS)
        for r in self.conn.execute("SELECT key, value FROM profile"):
            profile[r["key"]] = json.loads(r["value"])
        return profile

    def update_profile(self, **values) -> dict:
        for key, value in values.items():
            if key not in PROFILE_DEFAULTS:
                raise ValueError(f"Unknown profile field: {key}")
            if value is None:
                continue
            self.conn.execute(
                "INSERT INTO profile (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)),
            )
        self.conn.commit()
        return self.get_profile()

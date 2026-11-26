"""MCP tools. `whoop-mcp serve` runs them over stdio, `whoop-mcp http` over HTTP (see remote.py)."""

from __future__ import annotations

from datetime import date, timedelta

from mcp.server.mcpserver import MCPServer

from .auth import AuthError
from .client import WhoopClient
from .config import load_settings
from .energy import JOB_PAL, slope_per_day
from .service import Service
from .storage import Storage

mcp = MCPServer(
    "whoop-energy",
    instructions=(
        "Tracks caloric deficit: energy burned (WHOOP) minus energy eaten (local food log). "
        "WHOOP has no nutrition data, so log every meal with log_food. When the user describes food "
        "without numbers, estimate kcal and macros yourself, say it is an estimate, then log it. "
        "Deficit = expenditure - intake; positive means a deficit. Today's WHOOP cycle is still open, "
        "so today's expenditure is a projection to end of day. Run set_profile once (sex, birth date, "
        "job activity) so BMR and the fallback formula work."
    ),
)

_service: Service | None = None


def service() -> Service:
    global _service
    if _service is None:
        settings = load_settings()
        _service = Service(WhoopClient(settings), Storage(settings.db_file), tz=settings.timezone)
    return _service


def _day(value: str | None) -> date:
    return date.fromisoformat(value) if value else service().today()


def _guard(fn):
    try:
        return fn()
    except AuthError as e:
        return {"error": str(e)}


@mcp.tool()
def whoop_status() -> dict:
    """Check the WHOOP connection and show the WHOOP profile and body measurements."""
    def run():
        s = service()
        return {"profile": s.client.profile(), "body": s.client.body_measurement(),
                "local_profile": s.storage.get_profile()}
    return _guard(run)


@mcp.tool()
def whoop_connect_link() -> dict:
    """Link to connect (or reconnect) the WHOOP account. Give it to the user to open in a browser."""
    settings = load_settings()
    if not settings.public_url or not settings.access_key:
        return {"error": "Server is not running in remote mode. On a computer, run `whoop-mcp auth`."}
    return {"url": f"{settings.public_url}/{settings.access_key}/whoop/login"}


@mcp.tool()
def set_profile(
    sex: str | None = None,
    birth_date: str | None = None,
    height_cm: float | None = None,
    job_activity: str | None = None,
    target_deficit_kcal: int | None = None,
    expenditure_correction_pct: float | None = None,
) -> dict:
    """Save personal data used for BMR and targets. Only the fields given are changed.

    sex: "male" or "female". birth_date: YYYY-MM-DD. height_cm: overrides WHOOP height.
    job_activity: sedentary (desk), light (on feet part of the day), moderate (walking most
    of the day), heavy (manual labour). Exclude gym/sport: WHOOP counts workouts separately.
    target_deficit_kcal: daily deficit goal (500 is about 0.5 kg/week).
    expenditure_correction_pct: adjust WHOOP calories, e.g. -10 if WHOOP overestimates.
    Prefer calibrate_metabolism to set it from real weight data.
    """
    if sex is not None and sex not in ("male", "female"):
        return {"error": "sex must be 'male' or 'female'"}
    if job_activity is not None and job_activity not in JOB_PAL:
        return {"error": f"job_activity must be one of {sorted(JOB_PAL)}"}
    if birth_date is not None:
        date.fromisoformat(birth_date)
    return service().storage.update_profile(
        sex=sex, birth_date=birth_date, height_cm=height_cm, job_activity=job_activity,
        target_deficit_kcal=target_deficit_kcal, expenditure_correction_pct=expenditure_correction_pct,
    )


@mcp.tool()
def log_food(
    description: str,
    kcal: float,
    protein_g: float | None = None,
    carbs_g: float | None = None,
    fat_g: float | None = None,
    meal: str | None = None,
    day: str | None = None,
) -> dict:
    """Log something eaten or drunk. day defaults to today (YYYY-MM-DD).

    meal: breakfast, lunch, dinner, snack (free text). Include drinks with calories (alcohol too).
    """
    if kcal < 0:
        return {"error": "kcal cannot be negative"}
    d = _day(day)
    entry_id = service().storage.add_food(d, description, kcal, protein_g, carbs_g, fat_g, meal)
    totals = service().storage.food_totals(d, d).get(d.isoformat(), {})
    return {"id": entry_id, "day": d.isoformat(), "day_total_kcal": round(totals.get("kcal", 0))}


@mcp.tool()
def get_food_log(day: str | None = None) -> list[dict]:
    """List food entries for a day (default today)."""
    return service().storage.food_for_day(_day(day))


@mcp.tool()
def delete_food(entry_id: int) -> dict:
    """Delete a food entry by id (ids come from get_food_log)."""
    return {"deleted": service().storage.delete_food(entry_id)}


@mcp.tool()
def log_weight(kg: float, day: str | None = None) -> dict:
    """Record body weight. Weigh in the morning, after the toilet, before eating, for a clean trend."""
    d = _day(day)
    service().storage.set_weight(d, kg)
    return {"day": d.isoformat(), "kg": kg}


@mcp.tool()
def get_weight_trend(days: int = 30) -> dict:
    """Weight entries and trend (kg/week) over the last N days."""
    s = service()
    end = s.today()
    start = end - timedelta(days=days - 1)
    rows = s.storage.weights(start, end)
    slope = slope_per_day([(date.fromisoformat(r["day"]), r["kg"]) for r in rows])
    return {"entries": rows, "trend_kg_per_week": round(slope * 7, 2) if slope is not None else None}


@mcp.tool()
def get_energy_balance(day: str | None = None) -> dict:
    """Full energy balance for one day (default today).

    Returns intake, expenditure (WHOOP, corrected; projected to end of day if the cycle is
    still open; BMR x job formula as fallback), deficit, kcal left to hit the target,
    macros, workouts, strain, recovery and sleep.
    """
    return _guard(lambda: service().daily_balance(_day(day)))


@mcp.tool()
def get_deficit_summary(days: int = 7, end_day: str | None = None) -> dict:
    """Per-day deficit over a period plus totals, averages, expected fat change and the
    observed weight trend. days: length of the period, ending on end_day (default today)."""
    def run():
        end = _day(end_day)
        return service().summary(end - timedelta(days=days - 1), end)
    return _guard(run)


@mcp.tool()
def calibrate_metabolism(days: int = 21, apply: bool = False) -> dict:
    """Estimate your real expenditure from food log + weight trend and compare it with WHOOP.

    Uses the last N complete days. Suggests expenditure_correction_pct; with apply=true it saves it.
    Needs ~2-4 weeks of complete food logs and several weigh-ins.
    """
    return _guard(lambda: service().calibrate(days, apply))


def run() -> None:
    mcp.run()

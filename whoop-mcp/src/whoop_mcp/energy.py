"""Energy-balance math. Pure functions, no I/O."""

from __future__ import annotations

from datetime import date, datetime, timedelta

KJ_PER_KCAL = 4.184
# Energy in 1 kg of body fat tissue, the usual approximation.
KCAL_PER_KG_FAT = 7700

# Physical activity level for the job, excluding logged workouts
# (WHOOP counts those separately).
JOB_PAL = {
    "sedentary": 1.2,  # desk job, little walking
    "light": 1.375,  # on your feet part of the day (teacher, retail)
    "moderate": 1.55,  # walking most of the day (waiter, nurse)
    "heavy": 1.725,  # manual labour (construction, warehouse)
}


def kj_to_kcal(kj: float | None) -> float | None:
    return None if kj is None else kj / KJ_PER_KCAL


def age_on(birth_date: date, on: date) -> int:
    years = on.year - birth_date.year
    if (on.month, on.day) < (birth_date.month, birth_date.day):
        years -= 1
    return years


def bmr_mifflin_st_jeor(weight_kg: float, height_cm: float, age: int, sex: str) -> float:
    """Resting metabolic rate in kcal/day (Mifflin-St Jeor, 1990)."""
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    if sex == "male":
        return base + 5
    if sex == "female":
        return base - 161
    raise ValueError("sex must be 'male' or 'female'")


def formula_tdee(bmr: float, job_activity: str, workout_kcal: float = 0.0) -> float:
    """Formula-based daily expenditure: BMR x job PAL + workouts."""
    pal = JOB_PAL.get(job_activity)
    if pal is None:
        raise ValueError(f"job_activity must be one of {sorted(JOB_PAL)}")
    return bmr * pal + workout_kcal


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_offset(offset: str | None) -> timedelta:
    """WHOOP timezone_offset looks like '+01:00' or '-05:00'."""
    if not offset:
        return timedelta(0)
    sign = -1 if offset.startswith("-") else 1
    hours, _, minutes = offset.lstrip("+-").partition(":")
    return sign * timedelta(hours=int(hours), minutes=int(minutes or 0))


def local_day(record: dict) -> date:
    """Calendar day a WHOOP record belongs to, in the user's local time at the time."""
    start = parse_ts(record["start"])
    return (start + parse_offset(record.get("timezone_offset"))).date()


def project_open_cycle(kcal_so_far: float, start: datetime, now: datetime, bmr: float, pal: float) -> float:
    """Estimate the full-day expenditure of a cycle that has not ended yet.

    Adds the formula rate (BMR x PAL) for the hours left until 24h after the cycle start.
    """
    elapsed_h = (now - start).total_seconds() / 3600
    remaining_h = max(0.0, 24 - elapsed_h)
    return kcal_so_far + bmr * pal / 24 * remaining_h


def slope_per_day(points: list[tuple[date, float]]) -> float | None:
    """Least-squares slope (units per day). Needs two distinct days."""
    if len(points) < 2:
        return None
    x0 = points[0][0]
    xs = [(d - x0).days for d, _ in points]
    ys = [v for _, v in points]
    n = len(points)
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den


def tdee_from_weight_trend(avg_intake_kcal: float, kg_per_day: float) -> float:
    """Expenditure implied by intake and observed weight change.

    If you eat X kcal/day and lose L kg/day, you burned X + L * 7700.
    """
    return avg_intake_kcal - kg_per_day * KCAL_PER_KG_FAT


def round_or_none(value: float | None, ndigits: int = 0):
    if value is None:
        return None
    r = round(value, ndigits)
    return int(r) if ndigits == 0 else r

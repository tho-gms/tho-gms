from datetime import date, datetime, timedelta, timezone

import pytest

from whoop_mcp import energy as E
from whoop_mcp.service import Service
from whoop_mcp.storage import Storage


def test_bmr_mifflin():
    # 80 kg, 180 cm, 30 y male: 800 + 1125 - 150 + 5
    assert E.bmr_mifflin_st_jeor(80, 180, 30, "male") == 1780
    assert E.bmr_mifflin_st_jeor(60, 165, 30, "female") == pytest.approx(1320.25)


def test_local_day_uses_offset():
    rec = {"start": "2026-11-20T23:30:00.000Z", "timezone_offset": "+01:00"}
    assert E.local_day(rec) == date(2026, 11, 21)


def test_slope_and_tdee():
    pts = [(date(2026, 11, 1) + timedelta(days=i), 80 - 0.1 * i) for i in range(10)]
    slope = E.slope_per_day(pts)
    assert slope == pytest.approx(-0.1)
    assert E.tdee_from_weight_trend(2000, slope) == pytest.approx(2770)


def kj(kcal):
    return kcal * E.KJ_PER_KCAL


def cycle(cid, day, kcal, end=True):
    start = datetime(day.year, day.month, day.day, 7, tzinfo=timezone.utc)
    return {
        "id": cid,
        "start": start.isoformat().replace("+00:00", "Z"),
        "end": (start + timedelta(hours=24)).isoformat().replace("+00:00", "Z") if end else None,
        "timezone_offset": "+00:00",
        "score_state": "SCORED",
        "score": {"kilojoule": kj(kcal), "strain": 12.3},
    }


class FakeClient:
    def __init__(self, cycles, workouts=(), recoveries=(), sleeps=()):
        self._c, self._w, self._r, self._s = list(cycles), list(workouts), list(recoveries), list(sleeps)

    def body_measurement(self):
        return {"height_meter": 1.8, "weight_kilogram": 80, "max_heart_rate": 190}

    def profile(self):
        return {"user_id": 1}

    def cycles(self, lo, hi):
        return self._c

    def workouts(self, lo, hi):
        return self._w

    def recoveries(self, lo, hi):
        return self._r

    def sleeps(self, lo, hi):
        return self._s


@pytest.fixture
def storage(tmp_path):
    s = Storage(tmp_path / "t.db")
    s.update_profile(sex="male", birth_date="1996-01-01", job_activity="sedentary")
    return s


def test_daily_balance_complete_day(storage):
    d = date(2026, 11, 20)
    client = FakeClient(
        [cycle(1, d, 2600)],
        workouts=[{"start": "2026-11-20T18:00:00Z", "timezone_offset": "+00:00", "sport_name": "running",
                   "score": {"kilojoule": kj(500), "strain": 10}}],
        recoveries=[{"cycle_id": 1, "sleep_id": "s1", "score": {"recovery_score": 70, "resting_heart_rate": 50,
                                                                  "hrv_rmssd_milli": 60}}],
        sleeps=[{"id": "s1", "nap": False, "score": {"stage_summary": {
            "total_light_sleep_time_milli": 3 * 3_600_000, "total_slow_wave_sleep_time_milli": 2 * 3_600_000,
            "total_rem_sleep_time_milli": 2 * 3_600_000}}}],
    )
    storage.add_food(d, "lunch", 900, protein_g=50)
    storage.add_food(d, "dinner", 1100, protein_g=70)
    svc = Service(client, storage, now=lambda: datetime(2026, 11, 22, 12, tzinfo=timezone.utc))

    r = svc.daily_balance(d)
    assert r["whoop_status"] == "complete"
    assert r["intake_kcal"] == 2000
    assert r["expenditure_kcal"] == 2600
    assert r["deficit_kcal"] == 600
    assert r["kcal_left_to_hit_target"] == 100  # 2600 - 500 target - 2000 eaten
    assert r["workouts"][0]["kcal"] == 500
    assert r["recovery"]["score_pct"] == 70
    assert r["sleep"]["hours_asleep"] == 7
    assert r["protein_g_per_kg"] == 1.5


def test_open_cycle_is_projected(storage):
    d = date(2026, 11, 22)
    client = FakeClient([cycle(1, d, 1000, end=False)])
    # 5 hours into the cycle, 19 hours left
    svc = Service(client, storage, now=lambda: datetime(2026, 11, 22, 12, tzinfo=timezone.utc))
    r = svc.daily_balance(d)
    assert r["whoop_status"] == "in_progress"
    bmr = E.bmr_mifflin_st_jeor(80, 180, 30, "male")
    assert r["expenditure_kcal"] == round(1000 + bmr * 1.2 / 24 * 19)


def test_correction_and_formula_fallback(storage):
    d1, d2 = date(2026, 11, 20), date(2026, 11, 21)
    storage.update_profile(expenditure_correction_pct=-10)
    storage.add_food(d1, "x", 2000)
    storage.add_food(d2, "x", 2000)
    svc = Service(FakeClient([cycle(1, d1, 3000)]), storage,
                  now=lambda: datetime(2026, 11, 23, tzinfo=timezone.utc))
    s = svc.summary(d1, d2)
    assert s["days"][0]["expenditure_kcal"] == 2700
    assert s["days"][1]["expenditure_basis"] == "formula_bmr_x_job_pal"
    assert s["days_counted"] == 2


def test_calibrate_suggests_correction(storage):
    today = date(2026, 11, 30)
    days = [today - timedelta(days=i) for i in range(1, 22)]
    # WHOOP says 3000/day, she eats 2500, but weight drops only 0.05 kg/day -> real TDEE 2885
    cycles = [cycle(i, d, 3000) for i, d in enumerate(days)]
    for d in days:
        storage.add_food(d, "x", 2500)
    for i, d in enumerate(sorted(days)):
        storage.set_weight(d, 80 - 0.05 * i)
    svc = Service(FakeClient(cycles), storage, now=lambda: datetime(2026, 11, 30, 12, tzinfo=timezone.utc))
    r = svc.calibrate(21, apply=True)
    assert r["tdee_from_weight_trend_kcal"] == 2885
    assert r["suggested_correction_pct"] == pytest.approx(-3.8)
    assert storage.get_profile()["expenditure_correction_pct"] == pytest.approx(-3.8)

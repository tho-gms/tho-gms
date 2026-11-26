"""Combines WHOOP data, the local food log and the profile into energy-balance reports."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo

from . import energy as E
from .storage import Storage


class Service:
    def __init__(self, client, storage: Storage, now=None, tz: tzinfo | str = "Europe/Lisbon"):
        self.client = client
        self.storage = storage
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.tz = ZoneInfo(tz) if isinstance(tz, str) else tz

    # helpers ------------------------------------------------------------
    def today(self) -> date:
        return self._now().astimezone(self.tz).date()

    def _window(self, start: date, end: date) -> tuple[datetime, datetime]:
        # Pad by a day on each side: cycles start at wake-up and timezones shift the edges.
        lo = datetime.combine(start - timedelta(days=1), time.min, tzinfo=self.tz)
        hi = datetime.combine(end + timedelta(days=2), time.min, tzinfo=self.tz)
        return lo, hi

    def body(self) -> dict:
        try:
            return self.client.body_measurement() or {}
        except Exception:  # noqa: BLE001 - body data is optional for every report
            return {}

    def current_weight(self, body: dict | None = None) -> tuple[float | None, str | None]:
        latest = self.storage.latest_weight()
        if latest:
            return latest["kg"], f"log ({latest['day']})"
        body = self.body() if body is None else body
        if body.get("weight_kilogram"):
            return body["weight_kilogram"], "whoop"
        return None, None

    def metabolism(self, on: date, body: dict | None = None) -> dict:
        """BMR and formula expenditure inputs, with what is missing."""
        profile = self.storage.get_profile()
        body = self.body() if body is None else body
        weight, weight_src = self.current_weight(body)
        height = profile.get("height_cm") or (body.get("height_meter") or 0) * 100 or None
        missing = [k for k, v in {
            "sex": profile.get("sex"),
            "birth_date": profile.get("birth_date"),
            "weight": weight,
            "height": height,
        }.items() if not v]
        out = {
            "weight_kg": weight,
            "weight_source": weight_src,
            "height_cm": E.round_or_none(height, 1),
            "job_activity": profile["job_activity"],
            "job_pal": E.JOB_PAL.get(profile["job_activity"]),
            "bmr_kcal": None,
            "missing_for_bmr": missing,
        }
        if not missing:
            age = E.age_on(date.fromisoformat(profile["birth_date"]), on)
            out["age"] = age
            out["bmr_kcal"] = E.bmr_mifflin_st_jeor(weight, height, age, profile["sex"])
        return out

    def _whoop_days(self, start: date, end: date) -> dict[date, dict]:
        lo, hi = self._window(start, end)
        cycles = self.client.cycles(lo, hi)
        workouts = self.client.workouts(lo, hi)
        recoveries = {r.get("cycle_id"): r for r in self.client.recoveries(lo, hi)}
        sleeps = {s.get("id"): s for s in self.client.sleeps(lo, hi) if not s.get("nap")}

        days: dict[date, dict] = {}
        for c in cycles:
            d = E.local_day(c)
            if not (start <= d <= end):
                continue
            # If two cycles land on one day (travel, very short night), keep the longer one.
            prev_kj = (days[d]["cycle"].get("score") or {}).get("kilojoule") or 0 if d in days else None
            if prev_kj is not None and prev_kj >= ((c.get("score") or {}).get("kilojoule") or 0):
                continue
            rec = recoveries.get(c.get("id"))
            days[d] = {
                "cycle": c,
                "recovery": rec,
                "sleep": sleeps.get(rec.get("sleep_id")) if rec else None,
                "workouts": [],
            }
        for w in workouts:
            d = E.local_day(w)
            if d in days:
                days[d]["workouts"].append(w)
        return days

    def _day_report(self, d: date, wd: dict | None, food: dict | None, met: dict, detailed: bool) -> dict:
        profile = self.storage.get_profile()
        correction = 1 + float(profile.get("expenditure_correction_pct") or 0) / 100
        intake = food["kcal"] if food else None

        whoop_kcal = None
        status = "no_whoop_data"
        projected = None
        workout_kcal = 0.0
        if wd:
            c = wd["cycle"]
            score = c.get("score") or {}
            whoop_kcal = E.kj_to_kcal(score.get("kilojoule"))
            workout_kcal = sum(E.kj_to_kcal((w.get("score") or {}).get("kilojoule")) or 0 for w in wd["workouts"])
            if c.get("score_state") != "SCORED" or whoop_kcal is None:
                status = "not_scored"
            elif c.get("end") is None:
                status = "in_progress"
                if met["bmr_kcal"]:
                    projected = E.project_open_cycle(
                        whoop_kcal, E.parse_ts(c["start"]), self._now(), met["bmr_kcal"], met["job_pal"]
                    )
            else:
                status = "complete"

        formula = E.formula_tdee(met["bmr_kcal"], profile["job_activity"], workout_kcal) if met["bmr_kcal"] else None

        if status == "complete":
            expenditure, basis = whoop_kcal * correction, "whoop"
        elif status == "in_progress" and projected is not None:
            expenditure, basis = projected * correction, "whoop_projected_end_of_day"
        elif formula is not None:
            expenditure, basis = formula, "formula_bmr_x_job_pal"
        else:
            expenditure, basis = None, None

        deficit = expenditure - intake if expenditure is not None and intake is not None else None
        target = profile.get("target_deficit_kcal")
        report = {
            "date": d.isoformat(),
            "intake_kcal": E.round_or_none(intake),
            "food_entries": food["entries"] if food else 0,
            "expenditure_kcal": E.round_or_none(expenditure),
            "expenditure_basis": basis,
            "deficit_kcal": E.round_or_none(deficit),
            "whoop_status": status,
        }
        if not detailed:
            return report

        report.update({
            "whoop_kcal_raw": E.round_or_none(whoop_kcal),
            "whoop_kcal_so_far": E.round_or_none(whoop_kcal) if status == "in_progress" else None,
            "correction_pct": profile.get("expenditure_correction_pct"),
            "formula_tdee_kcal": E.round_or_none(formula),
            "bmr_kcal": E.round_or_none(met["bmr_kcal"]),
            "target_deficit_kcal": target,
            "kcal_left_to_hit_target": E.round_or_none(expenditure - target - (intake or 0))
            if expenditure is not None and target is not None else None,
            "macros_g": {k: E.round_or_none(food[k]) if food else None for k in ("protein_g", "carbs_g", "fat_g")},
        })
        if met["weight_kg"] and food and food.get("protein_g") is not None:
            report["protein_g_per_kg"] = round(food["protein_g"] / met["weight_kg"], 2)
        if wd:
            score = wd["cycle"].get("score") or {}
            report["strain"] = E.round_or_none(score.get("strain"), 1)
            report["workouts"] = [
                {
                    "sport": w.get("sport_name") or w.get("sport_id"),
                    "start": w.get("start"),
                    "kcal": E.round_or_none(E.kj_to_kcal((w.get("score") or {}).get("kilojoule"))),
                    "strain": E.round_or_none((w.get("score") or {}).get("strain"), 1),
                    "avg_hr": (w.get("score") or {}).get("average_heart_rate"),
                }
                for w in wd["workouts"]
            ]
            rec = (wd.get("recovery") or {}).get("score") or {}
            report["recovery"] = {
                "score_pct": rec.get("recovery_score"),
                "resting_hr": rec.get("resting_heart_rate"),
                "hrv_ms": E.round_or_none(rec.get("hrv_rmssd_milli"), 1),
            } if rec else None
            sl = (wd.get("sleep") or {}).get("score") or {}
            stages = sl.get("stage_summary") or {}
            asleep_ms = sum(stages.get(k, 0) for k in (
                "total_light_sleep_time_milli", "total_slow_wave_sleep_time_milli", "total_rem_sleep_time_milli"))
            report["sleep"] = {
                "hours_asleep": round(asleep_ms / 3_600_000, 2) if asleep_ms else None,
                "performance_pct": sl.get("sleep_performance_percentage"),
            } if sl else None
        return report

    # public API used by the MCP tools -------------------------------------
    def daily_balance(self, d: date) -> dict:
        body = self.body()
        met = self.metabolism(d, body)
        wd = self._whoop_days(d, d).get(d)
        food = self.storage.food_totals(d, d).get(d.isoformat())
        report = self._day_report(d, wd, food, met, detailed=True)
        report["metabolism"] = met
        report["food"] = self.storage.food_for_day(d)
        return report

    def summary(self, start: date, end: date) -> dict:
        body = self.body()
        met = self.metabolism(end, body)
        whoop = self._whoop_days(start, end)
        food = self.storage.food_totals(start, end)
        days = []
        d = start
        while d <= end:
            days.append(self._day_report(d, whoop.get(d), food.get(d.isoformat()), met, detailed=False))
            d += timedelta(days=1)

        # Only days with both numbers count toward totals; open/projected days are excluded.
        counted = [x for x in days if x["deficit_kcal"] is not None and x["whoop_status"] != "in_progress"]
        total = sum(x["deficit_kcal"] for x in counted)
        n = len(counted)
        weights = self.storage.weights(start, end)
        slope = E.slope_per_day([(date.fromisoformat(w["day"]), w["kg"]) for w in weights])
        return {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "days": days,
            "days_counted": n,
            "days_missing_food_log": [x["date"] for x in days if x["intake_kcal"] is None],
            "total_deficit_kcal": E.round_or_none(total) if n else None,
            "avg_deficit_kcal": E.round_or_none(total / n) if n else None,
            "avg_intake_kcal": E.round_or_none(sum(x["intake_kcal"] for x in counted) / n) if n else None,
            "avg_expenditure_kcal": E.round_or_none(sum(x["expenditure_kcal"] for x in counted) / n) if n else None,
            "expected_fat_change_kg": round(-total / E.KCAL_PER_KG_FAT, 2) if n else None,
            "observed_weight_trend_kg_per_week": round(slope * 7, 2) if slope is not None else None,
            "weight_entries": len(weights),
        }

    def calibrate(self, days: int, apply: bool) -> dict:
        """Compare WHOOP expenditure to what the weight trend implies."""
        end = self.today() - timedelta(days=1)
        start = end - timedelta(days=days - 1)
        s = self.summary(start, end)
        weights = self.storage.weights(start, end)
        # Only days measured by WHOOP over a full cycle, so the comparison is WHOOP vs reality.
        used = [x for x in s["days"] if x["expenditure_basis"] == "whoop" and x["intake_kcal"] is not None]
        out = {"start": s["start"], "end": s["end"], "days_counted": len(used),
               "weight_entries": len(weights)}
        if len(used) < 10 or len(weights) < 4:
            out["result"] = ("Not enough data. Need at least 10 days with food logged and complete WHOOP cycles, "
                             "and 4+ weigh-ins in the period (14-28 days of data works best).")
            return out

        profile = self.storage.get_profile()
        current_corr = float(profile.get("expenditure_correction_pct") or 0)
        slope = E.slope_per_day([(date.fromisoformat(w["day"]), w["kg"]) for w in weights])
        avg_intake = sum(x["intake_kcal"] for x in used) / len(used)
        real_tdee = E.tdee_from_weight_trend(avg_intake, slope)
        # Reported expenditure already includes the current correction; undo it to get raw WHOOP.
        raw_avg = sum(x["expenditure_kcal"] for x in used) / len(used) / (1 + current_corr / 100)
        suggested = round((real_tdee / raw_avg - 1) * 100, 1)
        out.update({
            "avg_intake_kcal": E.round_or_none(avg_intake),
            "weight_trend_kg_per_week": round(slope * 7, 2),
            "tdee_from_weight_trend_kcal": E.round_or_none(real_tdee),
            "avg_whoop_expenditure_raw_kcal": E.round_or_none(raw_avg),
            "current_correction_pct": current_corr,
            "suggested_correction_pct": suggested,
            "applied": False,
            "caveat": ("Water, salt, carbs and the menstrual cycle move weight day to day. "
                       "The estimate also assumes the food log is complete."),
        })
        if apply:
            self.storage.update_profile(expenditure_correction_pct=suggested)
            out["applied"] = True
        return out

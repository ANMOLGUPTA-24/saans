"""Dose, not index.

An AQI number tells a principal nothing actionable: it is a colour for a
city, for a day. What a child actually takes in is a dose - concentration
multiplied by how long they are out in it, multiplied by how hard they are
breathing. That product is the only quantity a school can actually spend
or save, so it is the quantity Saans budgets.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .school import (
    ACTIVITIES,
    INDOOR_INFILTRATION,
    OUTDOOR_DAY,
    PURIFIER_INFILTRATION,
    Activity,
    Cohort,
)
from .sources import Series

# WHO 2021 Global Air Quality Guideline, PM2.5 24-hour mean.
WHO_PM25_24H = 15.0
# A school week of outdoor time: assembly + recess + games, five days.
OUTDOOR_HOURS_PER_WEEK = sum(a.hours for a in OUTDOOR_DAY) * 5
# One week of outdoor school at the WHO guideline, at rest-equivalent
# breathing. This is the budget. Everything is measured against it.
WEEKLY_BUDGET = WHO_PM25_24H * OUTDOOR_HOURS_PER_WEEK  # µg·h/m³, rest-equivalent


@dataclass(frozen=True)
class Dose:
    """Inhaled dose for one activity, in rest-equivalent µg·h/m³."""

    activity: str
    label: str
    window: str
    mean_pm25: float
    peak_pm25: float
    hours: float
    exertion: float
    indoors: bool
    dose: float
    samples: int

    @property
    def budget_pct(self) -> float:
        return 100.0 * self.dose / WEEKLY_BUDGET


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def activity_dose(
    series: Series,
    day: date,
    activity: Activity,
    indoors: bool = False,
    purifier: bool = False,
) -> Dose | None:
    """Dose a child takes in from one activity on one day.

    Indoors is a reduction, not an escape: an unfiltered Delhi classroom
    still lets roughly half the outdoor particulate in.
    """
    hours = series.between(day, activity.start_h, activity.end_h)
    if not hours:
        return None
    values = [h.pm2_5 for h in hours if h.pm2_5 is not None]
    if not values:
        return None

    mean_out = _mean(values)
    factor = 1.0
    if indoors:
        factor = PURIFIER_INFILTRATION if purifier else INDOOR_INFILTRATION

    exposure = mean_out * factor
    return Dose(
        activity=activity.key,
        label=activity.label,
        window=activity.window,
        mean_pm25=round(mean_out, 1),
        peak_pm25=round(max(values), 1),
        hours=activity.hours,
        exertion=activity.exertion,
        indoors=indoors,
        dose=round(exposure * activity.hours * activity.exertion, 1),
        samples=len(values),
    )


def day_dose(
    series: Series,
    day: date,
    moved_indoors: set[str] | None = None,
    cancelled: set[str] | None = None,
    purifier: bool = False,
) -> tuple[float, list[Dose]]:
    """Total dose for a day under a given protocol decision."""
    moved_indoors = moved_indoors or set()
    cancelled = cancelled or set()
    doses: list[Dose] = []
    for activity in OUTDOOR_DAY:
        if activity.key in cancelled:
            continue
        d = activity_dose(
            series, day, activity, indoors=activity.key in moved_indoors, purifier=purifier
        )
        if d:
            doses.append(d)
    return round(sum(d.dose for d in doses), 1), doses


def budget_burn_days(daily_dose: float) -> float:
    """School days this dose level would take to spend a full week's budget."""
    if daily_dose <= 0:
        return float("inf")
    return round(WEEKLY_BUDGET / daily_dose, 2)


def safest_window(
    series: Series, day: date, length_h: int = 1, earliest: int = 7, latest: int = 14
) -> tuple[int, float] | None:
    """The cleanest slot in the school day.

    When the air is bad all day there is still a best hour to be outside in,
    and moving the games period into it is free. This is the recommendation
    a dashboard never makes.
    """
    hours = {h.hour: h.pm2_5 for h in series.day_hours(day) if h.pm2_5 is not None}
    best: tuple[int, float] | None = None
    for start in range(earliest, latest - length_h + 1):
        window = [hours[h] for h in range(start, start + length_h) if h in hours]
        if len(window) < length_h:
            continue
        avg = _mean(window)
        if best is None or avg < best[1]:
            best = (start, round(avg, 1))
    return best


def cohort_weekly_spend(
    series: Series, days: list[date], cohort: Cohort
) -> dict[str, float]:
    """What this class has already spent, with no protocol in force.

    This is the counterfactual the school is living in today: business as
    usual, every activity held outdoors.
    """
    total = 0.0
    counted = 0
    for day in days:
        d, _ = day_dose(series, day)
        if d:
            total += d
            counted += 1
    return {
        "cohort": cohort.key,
        "days_counted": counted,
        "dose": round(total, 1),
        "budget_pct": round(100.0 * total / WEEKLY_BUDGET, 1) if WEEKLY_BUDGET else 0.0,
    }

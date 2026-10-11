"""What the protocol would have been worth, over real days that happened.

A hackathon project can claim anything about its impact. This module makes
the claim checkable: it replays the protocol over the last fortnight of
real measured air for this location and reports the dose it would have
prevented, per child, with no modelling of its own.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from . import exposure as ex
from .decide import Decision, decide
from .school import TOTAL_CHILDREN, TOTAL_ON_REGISTER
from .sources import Series


@dataclass
class DayOutcome:
    day: str
    weekday: str
    peak_pm25: float
    cpcb_band: str
    dose_business_as_usual: float
    dose_under_protocol: float
    dose_saved: float
    activities_changed: int
    clauses_fired: list[str]

    @property
    def saved_pct(self) -> float:
        if not self.dose_business_as_usual:
            return 0.0
        return round(100.0 * self.dose_saved / self.dose_business_as_usual, 1)


@dataclass
class Replay:
    days: list[DayOutcome]
    school_days: int
    dose_business_as_usual: float
    dose_under_protocol: float
    who_weeks_business_as_usual: float
    who_weeks_under_protocol: float
    clause_counts: dict[str, int]
    quiet_days: int
    children: int
    on_register: int

    @property
    def dose_saved(self) -> float:
        return round(self.dose_business_as_usual - self.dose_under_protocol, 1)

    @property
    def saved_pct(self) -> float:
        if not self.dose_business_as_usual:
            return 0.0
        return round(100.0 * self.dose_saved / self.dose_business_as_usual, 1)

    @property
    def child_hours_saved(self) -> float:
        """Dose prevented across the whole school, in µg·h per child summed."""
        return round(self.dose_saved * self.children, 1)


# CPCB national PM2.5 breakpoints, 24-hour averaging.
BANDS = [
    (30, "Good"),
    (60, "Satisfactory"),
    (90, "Moderate"),
    (120, "Poor"),
    (250, "Very Poor"),
    (10**9, "Severe"),
]


def cpcb_band(pm25: float) -> str:
    for ceiling, name in BANDS:
        if pm25 <= ceiling:
            return name
    return "Severe"


def replay(series: Series, days: list[date] | None = None) -> Replay:
    """Replay the protocol across real days.

    Weekends are skipped: a protocol for a school is only worth anything on
    days the school is open, and counting Sundays would flatter the numbers.
    """
    candidates = days if days is not None else series.days
    outcomes: list[DayOutcome] = []
    clause_counts: dict[str, int] = {}

    for day in candidates:
        if day.weekday() >= 5:
            continue
        if not series.day_hours(day):
            continue
        d: Decision = decide(series, day)
        if not d.cohorts:
            continue

        bau = sum(c.dose_business_as_usual for c in d.cohorts) / len(d.cohorts)
        under = sum(c.dose_under_protocol for c in d.cohorts) / len(d.cohorts)
        changed = sum(len(c.changes) for c in d.cohorts)
        fired: set[str] = set()
        for c in d.cohorts:
            for call in c.changes:
                fired.update(x for x in call.cited if x != "P0")
        for f in fired:
            clause_counts[f] = clause_counts.get(f, 0) + 1

        peak = max(call.peak_pm25 for c in d.cohorts for call in c.calls)
        outcomes.append(
            DayOutcome(
                day=day.isoformat(),
                weekday=day.strftime("%a"),
                peak_pm25=peak,
                cpcb_band=cpcb_band(peak),
                dose_business_as_usual=round(bau, 1),
                dose_under_protocol=round(under, 1),
                dose_saved=round(bau - under, 1),
                activities_changed=changed,
                clauses_fired=sorted(fired),
            )
        )

    bau_total = round(sum(o.dose_business_as_usual for o in outcomes), 1)
    under_total = round(sum(o.dose_under_protocol for o in outcomes), 1)
    return Replay(
        days=outcomes,
        school_days=len(outcomes),
        dose_business_as_usual=bau_total,
        dose_under_protocol=under_total,
        who_weeks_business_as_usual=round(bau_total / ex.WEEKLY_BUDGET, 1),
        who_weeks_under_protocol=round(under_total / ex.WEEKLY_BUDGET, 1),
        clause_counts=dict(sorted(clause_counts.items())),
        quiet_days=sum(1 for o in outcomes if o.activities_changed == 0),
        children=TOTAL_CHILDREN,
        on_register=TOTAL_ON_REGISTER,
    )

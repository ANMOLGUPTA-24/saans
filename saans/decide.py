"""The morning decision.

Before 07:00 someone at the school has to answer four questions: does
assembly happen outside, does the games period happen, do the windows stay
open, who gets a mask. Saans answers them from live forecast evidence,
against the Cedar protocol, and shows its working.

The order matters. Saans does not reach for 'cancel' first. It tries to
hold the activity, then to move it into the cleanest hour of the day, and
only then gives it up. A protocol that only ever says no gets switched off
in a fortnight.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime

from . import exposure as ex
from . import policy as P
from .school import (
    ACTIVITIES,
    COHORTS,
    HAS_AIR_PURIFIERS,
    INDOOR_INFILTRATION,
    SCHOOL_NAME,
    TOTAL_CHILDREN,
    TOTAL_ON_REGISTER,
    Activity,
    Cohort,
)
from .sources import Series

HELD = "held outdoors"
MOVED = "moved to a cleaner hour"
INDOORS = "moved indoors"

MASK_NONE = "none"
MASK_REGISTER = "respiratory register only"
MASK_ALL = "every child"


@dataclass
class Call:
    """What Saans decided about one activity, and why."""

    activity: str
    label: str
    window: str
    verdict: str
    moved_to: str | None
    peak_pm25: float
    mean_pm25: float
    mixing_height_m: float
    exertion: float
    dose_if_outdoors: float
    dose_as_decided: float
    dose_saved: float
    budget_pct_if_outdoors: float
    cited: list[str]
    citation: str
    alternative: str | None

    @property
    def changed(self) -> bool:
        return self.verdict != HELD


@dataclass
class CohortDecision:
    cohort: str
    label: str
    grade: int
    strength: int
    on_register: int
    weekly_spent_pct_before: float
    calls: list[Call]
    windows_open: bool
    windows_citation: str
    masks: str
    masks_citation: str
    dose_business_as_usual: float
    dose_under_protocol: float

    @property
    def dose_saved(self) -> float:
        return round(self.dose_business_as_usual - self.dose_under_protocol, 1)

    @property
    def saved_pct(self) -> float:
        if not self.dose_business_as_usual:
            return 0.0
        return round(100.0 * self.dose_saved / self.dose_business_as_usual, 1)

    @property
    def changes(self) -> list[Call]:
        return [c for c in self.calls if c.changed]


@dataclass
class Decision:
    """One morning's signed decision for the whole school."""

    day: str
    decided_at: str
    school: str
    latitude: float
    longitude: float
    data_source: str
    safest_hour: int | None
    safest_hour_pm25: float | None
    cohorts: list[CohortDecision]
    protocol_sha256: str
    evidence_sha256: str
    notice: str | None = None
    notice_author: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def total_dose_saved(self) -> float:
        """Dose prevented summed over classes. Not a per-child figure."""
        return round(sum(c.dose_saved for c in self.cohorts), 1)

    @property
    def dose_saved_per_child(self) -> float:
        """Dose prevented for the average child, weighted by class size.

        Classes differ: one carries no register and keeps its periods
        outdoors. Averaging over classes rather than summing is the only
        way this number means what it says.
        """
        roll = sum(c.strength for c in self.cohorts)
        if not roll:
            return 0.0
        return round(
            sum(c.dose_saved * c.strength for c in self.cohorts) / roll, 1
        )

    @property
    def child_dose_hours_saved(self) -> float:
        """Dose prevented across the whole school: per-child dose x children."""
        return round(
            sum(c.dose_saved * c.strength for c in self.cohorts), 1
        )

    @property
    def children_affected(self) -> int:
        return sum(c.strength for c in self.cohorts if c.changes)

    @property
    def register_affected(self) -> int:
        return sum(c.on_register for c in self.cohorts if c.changes)

    def to_json(self) -> dict:
        d = asdict(self)
        d["total_dose_saved"] = self.total_dose_saved
        d["dose_saved_per_child"] = self.dose_saved_per_child
        d["child_dose_hours_saved"] = self.child_dose_hours_saved
        d["children_affected"] = self.children_affected
        d["register_affected"] = self.register_affected
        for c, raw in zip(self.cohorts, d["cohorts"]):
            raw["dose_saved"] = c.dose_saved
            raw["saved_pct"] = c.saved_pct
        return d


def _evidence_window(series: Series, day: date, start_h: int, end_h: int):
    hours = series.between(day, start_h, end_h)
    if not hours:
        return None
    pm = [h.pm2_5 for h in hours if h.pm2_5 is not None]
    mix = [h.mixing_height_m for h in hours if h.mixing_height_m is not None]
    return {
        "peak": max(pm),
        "mean": sum(pm) / len(pm),
        # The worst mixing height in the window is the one that matters:
        # that is the hour the air has nowhere to go.
        "mixing": min(mix) if mix else 9999.0,
    }


def _action_for(activity: Activity) -> str:
    return P.HOLD_VIGOROUS if activity.exertion >= 3.0 else P.HOLD_OUTDOORS


def weekly_spent_pct(series: Series, day: date) -> float:
    """What this week has already cost, lived as it actually was.

    Monday to the day before the decision, every activity held outdoors,
    because that is the status quo Saans is being introduced into.
    """
    monday = day.fromordinal(day.toordinal() - day.weekday())
    spent = 0.0
    for d in series.days:
        if monday <= d < day:
            dose, _ = ex.day_dose(series, d)
            spent += dose
    return round(100.0 * spent / ex.WEEKLY_BUDGET, 1)


def _options(
    series: Series, day: date, activity: Activity, safest: tuple[int, float] | None
) -> dict:
    """Cost every option for this activity before asking the protocol anything.

    Cedar can only reason about avoidable dose if the alternatives have
    already been priced, so this runs first: hold it, move it to the
    cleanest hour, or take it indoors.
    """
    outdoor = ex.activity_dose(series, day, activity)
    if outdoor is None:
        return {}

    indoor = ex.activity_dose(
        series, day, activity, indoors=True, purifier=HAS_AIR_PURIFIERS
    )
    moved = None
    moved_activity = None
    if safest and safest[0] != activity.start_h:
        length = max(1, activity.end_h - activity.start_h)
        moved_activity = Activity(
            activity.key,
            activity.label,
            safest[0],
            safest[0] + length,
            activity.hours,
            activity.exertion,
            activity.indoor_alternative,
        )
        moved = ex.activity_dose(series, day, moved_activity)

    candidates = [d.dose for d in (indoor, moved) if d is not None]
    best_alternative = min(candidates) if candidates else outdoor.dose
    return {
        "outdoor": outdoor,
        "indoor": indoor,
        "moved": moved,
        "moved_activity": moved_activity,
        "avoidable": max(0.0, round(outdoor.dose - best_alternative, 1)),
    }


def _call(
    series: Series,
    day: date,
    activity: Activity,
    cohort: Cohort,
    dose_today: float,
    safest: tuple[int, float] | None,
) -> Call | None:
    ev = _evidence_window(series, day, activity.start_h, activity.end_h)
    opts = _options(series, day, activity, safest)
    if not ev or not opts:
        return None

    outdoor = opts["outdoor"]
    action = _action_for(activity)

    def put(evidence: dict, avoidable: float) -> P.Ruling:
        return P.ask(
            action,
            cohort.key,
            cohort.grade,
            cohort.strength,
            cohort.on_register,
            peak_pm25=evidence["peak"],
            mean_pm25=evidence["mean"],
            mixing_height_m=evidence["mixing"],
            avoidable_dose=avoidable,
            dose_today=dose_today,
        )

    base = Call(
        activity=activity.key,
        label=activity.label,
        window=activity.window,
        verdict=HELD,
        moved_to=None,
        peak_pm25=round(ev["peak"], 1),
        mean_pm25=round(ev["mean"], 1),
        mixing_height_m=round(ev["mixing"]),
        exertion=activity.exertion,
        dose_if_outdoors=outdoor.dose,
        dose_as_decided=outdoor.dose,
        dose_saved=0.0,
        budget_pct_if_outdoors=round(outdoor.budget_pct, 1),
        cited=[],
        citation="",
        alternative=None,
    )

    # 1. Hold it where it is, if the protocol allows.
    ruling = put(ev, opts["avoidable"])
    if ruling.allowed:
        base.cited = ruling.clause_ids
        base.citation = ruling.citation
        return base

    # 2. Keep it outdoors by moving it into the cleanest hour of the day.
    #    Same activity, same exertion, different air. Saans tries this
    #    before it tries taking a games period away from a ten-year-old.
    moved, moved_activity = opts["moved"], opts["moved_activity"]
    if moved and moved_activity:
        moved_ev = _evidence_window(
            series, day, moved_activity.start_h, moved_activity.end_h
        )
        indoor_dose = opts["indoor"].dose if opts["indoor"] else float("inf")
        if moved_ev and moved.dose <= indoor_dose:
            # Only prefer the move if it is at least as good as the indoor
            # option. Otherwise relocating is a token gesture that leaves
            # most of the avoidable dose on the table, and the class is
            # better off inside.
            moved_ruling = put(moved_ev, 0.0)
            if moved_ruling.allowed:
                base.verdict = MOVED
                base.moved_to = moved_activity.window
                base.dose_as_decided = moved.dose
                base.dose_saved = round(outdoor.dose - moved.dose, 1)
                base.cited = ruling.clause_ids
                base.citation = ruling.citation
                base.alternative = (
                    f"same activity, {moved_activity.start_h:02d}:00 instead"
                )
                return base

    # 3. Indoors. Not a free win, and the notice says so: an unfiltered shut
    #    classroom still admits about half the outdoor particulate.
    indoor = opts["indoor"]
    base.verdict = INDOORS
    base.dose_as_decided = indoor.dose if indoor else 0.0
    base.dose_saved = round(outdoor.dose - base.dose_as_decided, 1)
    base.cited = ruling.clause_ids
    base.citation = ruling.citation
    base.alternative = activity.indoor_alternative
    return base


def decide(series: Series, day: date) -> Decision:
    """Run the protocol for one school day."""
    safest = ex.safest_window(series, day, length_h=1)
    spent_pct = weekly_spent_pct(series, day)

    cohort_decisions: list[CohortDecision] = []
    for cohort in COHORTS:
        # Chronological, because P6 is a running stop-loss: what a class has
        # already taken this morning changes what it is allowed this afternoon.
        calls: list[Call] = []
        dose_today = 0.0
        for activity in sorted(ACTIVITIES.values(), key=lambda a: a.start_h):
            c = _call(series, day, activity, cohort, dose_today, safest)
            if c:
                calls.append(c)
                dose_today += c.dose_as_decided
        if not calls:
            continue

        day_peak = max(c.peak_pm25 for c in calls)
        windows = P.ask(
            P.KEEP_WINDOWS_OPEN,
            cohort.key,
            cohort.grade,
            cohort.strength,
            cohort.on_register,
            peak_pm25=day_peak,
            mean_pm25=sum(c.mean_pm25 for c in calls) / len(calls),
            mixing_height_m=min(c.mixing_height_m for c in calls),
        )
        masks_ruling = P.ask(
            P.OMIT_MASKS,
            cohort.key,
            cohort.grade,
            cohort.strength,
            cohort.on_register,
            peak_pm25=day_peak,
            mean_pm25=sum(c.mean_pm25 for c in calls) / len(calls),
            mixing_height_m=min(c.mixing_height_m for c in calls),
        )
        if masks_ruling.allowed:
            masks = MASK_NONE
        elif day_peak > 120:
            masks = MASK_ALL
        else:
            masks = MASK_REGISTER

        cohort_decisions.append(
            CohortDecision(
                cohort=cohort.key,
                label=cohort.label,
                grade=cohort.grade,
                strength=cohort.strength,
                on_register=cohort.on_register,
                weekly_spent_pct_before=spent_pct,
                calls=calls,
                windows_open=windows.allowed,
                windows_citation=windows.citation,
                masks=masks,
                masks_citation=masks_ruling.citation,
                dose_business_as_usual=round(sum(c.dose_if_outdoors for c in calls), 1),
                dose_under_protocol=round(sum(c.dose_as_decided for c in calls), 1),
            )
        )

    evidence = json.dumps(
        [
            {
                "t": h.t.isoformat(),
                "pm2_5": h.pm2_5,
                "mix": h.mixing_height_m,
            }
            for h in series.day_hours(day)
        ],
        sort_keys=True,
    )

    return Decision(
        day=day.isoformat(),
        decided_at=datetime.now().isoformat(timespec="seconds"),
        school=SCHOOL_NAME,
        latitude=series.latitude,
        longitude=series.longitude,
        data_source=series.source,
        safest_hour=safest[0] if safest else None,
        safest_hour_pm25=safest[1] if safest else None,
        cohorts=cohort_decisions,
        protocol_sha256=hashlib.sha256(
            P.PROTOCOL_PATH.read_bytes()
        ).hexdigest()[:16],
        evidence_sha256=hashlib.sha256(evidence.encode()).hexdigest()[:16],
        warnings=list(series.notes),
    )

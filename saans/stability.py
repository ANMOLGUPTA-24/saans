"""How wrong can the forecast be before the decision changes?

The obvious challenge to this project is: you are acting on a global
model's forecast, so how do you know it is right. There is no keyless
ground-truth feed for Delhi to validate against, and claiming a skill
score without one would be dishonest.

So Saans answers a better question instead. For a safety tool, what
matters is not whether the forecast is exact - it never is - but whether
the decision survives the forecast being wrong. This perturbs the
evidence across a band of forecast error and reports which decisions
hold and which flip.

A decision that holds across the whole band is safe to act on. One that
flips inside it is marginal, and Saans says so on the notice rather than
projecting a confidence it has not got.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .decide import HELD, Decision, decide
from .sources import Hour, Series

# CAMS global PM2.5 over South Asia is routinely out by tens of percent.
# This band is deliberately wider than the error anyone claims for it.
BAND = (-0.4, -0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3, 0.4)


def scale(series: Series, factor: float) -> Series:
    """The same day with every PM2.5 reading scaled by (1 + factor)."""
    return Series(
        hours=[
            Hour(
                t=h.t,
                pm2_5=None if h.pm2_5 is None else max(0.0, h.pm2_5 * (1 + factor)),
                pm10=h.pm10,
                temp_c=h.temp_c,
                wind_kmh=h.wind_kmh,
                wind_deg=h.wind_deg,
                mixing_height_m=h.mixing_height_m,
            )
            for h in series.hours
        ],
        source=f"{series.source} (scaled {factor:+.0%})",
        fetched_at=series.fetched_at,
        latitude=series.latitude,
        longitude=series.longitude,
        notes=list(series.notes),
    )


@dataclass
class CallStability:
    cohort: str
    activity: str
    verdict: str
    stable: bool
    flips_at: float | None
    verdicts: dict[str, str]

    @property
    def margin(self) -> str:
        if self.stable:
            return "holds across ±40% forecast error"
        return f"flips at {self.flips_at:+.0%} forecast error"


@dataclass
class Stability:
    day: str
    calls: list[CallStability]
    band: list[float]

    @property
    def total(self) -> int:
        return len(self.calls)

    @property
    def stable(self) -> int:
        return sum(1 for c in self.calls if c.stable)

    @property
    def marginal(self) -> list[CallStability]:
        return [c for c in self.calls if not c.stable]

    @property
    def stable_pct(self) -> float:
        if not self.total:
            return 0.0
        return round(100.0 * self.stable / self.total, 1)

    def to_json(self) -> dict:
        return {
            "day": self.day,
            "band": self.band,
            "total": self.total,
            "stable": self.stable,
            "stable_pct": self.stable_pct,
            "marginal": [
                {
                    "cohort": c.cohort,
                    "activity": c.activity,
                    "verdict": c.verdict,
                    "flips_at": c.flips_at,
                    "margin": c.margin,
                    "verdicts": c.verdicts,
                }
                for c in self.marginal
            ],
            "calls": [
                {
                    "cohort": c.cohort,
                    "activity": c.activity,
                    "verdict": c.verdict,
                    "stable": c.stable,
                    "flips_at": c.flips_at,
                    "margin": c.margin,
                }
                for c in self.calls
            ],
        }


def analyse(series: Series, day: date, band: tuple[float, ...] = BAND) -> Stability:
    """Re-decide the day across a band of forecast error."""
    baseline: Decision = decide(series, day)
    truth = {
        (c.cohort, k.activity): k.verdict for c in baseline.cohorts for k in c.calls
    }

    perturbed: dict[float, dict[tuple[str, str], str]] = {}
    for factor in band:
        if factor == 0.0:
            perturbed[factor] = truth
            continue
        d = decide(scale(series, factor), day)
        perturbed[factor] = {
            (c.cohort, k.activity): k.verdict for c in d.cohorts for k in c.calls
        }

    calls: list[CallStability] = []
    for key, verdict in truth.items():
        verdicts = {
            f"{f:+.0%}": perturbed[f].get(key, "—") for f in band
        }
        # The smallest error, either direction, that changes the call.
        flips_at = None
        for f in sorted(band, key=abs):
            if f == 0.0:
                continue
            if perturbed[f].get(key) != verdict:
                flips_at = f
                break
        calls.append(
            CallStability(
                cohort=key[0],
                activity=key[1],
                verdict=verdict,
                stable=flips_at is None,
                flips_at=flips_at,
                verdicts=verdicts,
            )
        )

    return Stability(day=day.isoformat(), calls=calls, band=list(band))

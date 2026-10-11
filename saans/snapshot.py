"""Export everything the engine knows, as one JSON document.

The public site is a presentation layer. It must never hold its own copy
of a number: everything it shows is produced here, by the same Cedar
protocol and the same dose arithmetic that the API serves, so the site
and the engine cannot disagree.

    python -m saans.snapshot          # writes data/snapshot.json
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

from . import exposure as ex
from . import policy as P
from .city import picture
from .decide import decide
from .notice import plain_summary
from .replay import replay
from .school import (
    COHORTS,
    LATITUDE,
    LONGITUDE,
    OUTDOOR_DAY,
    SCHOOL_NAME,
    SCHOOL_NOTE,
    TOTAL_CHILDREN,
    TOTAL_ON_REGISTER,
)
from .sources import fetch, fetch_range
from .stability import analyse

OUT = Path(__file__).resolve().parent.parent / "data" / "snapshot.json"
NOVEMBER = ("2025-11-03", "2025-11-14")


def build(include_city: bool = True) -> dict:
    series = fetch(LATITUDE, LONGITUDE, forecast_days=3, past_days=14)
    today = date.today() if date.today() in series.days else series.days[-1]
    d = decide(series, today)

    recent = replay(series, [x for x in series.days if x <= date.today()])
    november = replay(fetch_range(LATITUDE, LONGITUDE, *NOVEMBER))

    doc: dict = {
        "generated_for": d.day,
        "generated_at": d.decided_at,
        "school": {
            "name": SCHOOL_NAME,
            "note": SCHOOL_NOTE,
            "lat": LATITUDE,
            "lon": LONGITUDE,
            "children": TOTAL_CHILDREN,
            "on_register": TOTAL_ON_REGISTER,
        },
        "who": {
            "weekly_budget": ex.WEEKLY_BUDGET,
            "guideline_24h": ex.WHO_PM25_24H,
            "outdoor_hours_per_week": ex.OUTDOOR_HOURS_PER_WEEK,
        },
        "outdoor_day": [
            {
                "key": a.key,
                "label": a.label,
                "window": a.window,
                "hours": a.hours,
                "exertion": a.exertion,
                "indoor_alternative": a.indoor_alternative,
            }
            for a in OUTDOOR_DAY
        ],
        "protocol": {
            "sha256": d.protocol_sha256,
            "engine": "Cedar (cedarpy), AWS open source",
            "clauses": [
                {"id": c.id, "effect": c.effect, "text": c.text} for c in P.clauses()
            ],
            "source": P.PROTOCOL_PATH.read_text(),
        },
        "today": d.to_json(),
        "plain_summary": plain_summary(d),
        "hours": [
            {
                "hour": h.hour,
                "pm2_5": h.pm2_5,
                "mixing_height_m": h.mixing_height_m,
                "temp_c": h.temp_c,
            }
            for h in series.day_hours(today)
        ],
        "safest": ex.safest_window(series, today, length_h=1),
        "stability": analyse(series, today).to_json(),
        "data_source": series.source,
        "replay": {
            "recent": _replay_json(recent, "the last fortnight at this school"),
            "november": _replay_json(
                november, f"Delhi smog season, {NOVEMBER[0]} to {NOVEMBER[1]}"
            ),
        },
    }

    if include_city:
        city = picture()
        doc["city"] = {
            "summary": city.summary(),
            # Trimmed for the map: every school, only what a point needs.
            "schools": [
                {
                    "n": s.name,
                    "la": s.lat,
                    "lo": s.lon,
                    "pm": s.peak_pm25,
                    "d": s.day_dose,
                    "b": s.cpcb_band,
                    "x": not s.games_allowed,
                }
                for s in city.schools
            ],
            "worst": [asdict(s) for s in city.worst[:8]],
            "best": [asdict(s) for s in city.best[:5]],
        }

    return doc


def _replay_json(r, label: str) -> dict:
    return {
        "label": label,
        "school_days": r.school_days,
        "quiet_days": r.quiet_days,
        "saved_pct": r.saved_pct,
        "who_weeks_business_as_usual": r.who_weeks_business_as_usual,
        "who_weeks_under_protocol": r.who_weeks_under_protocol,
        "clause_counts": r.clause_counts,
        "days": [
            {
                "day": o.day,
                "weekday": o.weekday,
                "peak_pm25": o.peak_pm25,
                "cpcb_band": o.cpcb_band,
                "bau": o.dose_business_as_usual,
                "protocol": o.dose_under_protocol,
                "saved": o.dose_saved,
                "saved_pct": o.saved_pct,
                "clauses": o.clauses_fired,
            }
            for o in r.days
        ],
    }


if __name__ == "__main__":
    doc = build()
    OUT.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
    size = OUT.stat().st_size
    print(f"wrote {OUT} ({size / 1024:.0f} KB)")
    print(f"  day            : {doc['generated_for']}")
    print(f"  city schools   : {doc.get('city', {}).get('summary', {}).get('schools')}")
    print(f"  clauses        : {len(doc['protocol']['clauses'])}")
    print(f"  replay windows : {list(doc['replay'])}")

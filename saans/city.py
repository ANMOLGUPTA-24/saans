"""Delhi, school by school.

One school proves the protocol works. It does not show the size of the
thing. This runs the same protocol across every school in Delhi that
OpenStreetMap has a name and a location for, clipped to the NCT border -
772 real places with real coordinates - and reports what a child's day
costs at each.

The clip matters. A bounding box around Delhi also contains Gurugram,
Noida and Faridabad; 150 of the schools collected were in those, and
calling them Delhi schools would have been false. The map is what caught
it: the points sat visibly outside the border.

The air genuinely varies across the city: on a single morning the spread
between the cleanest and dirtiest corner of Delhi is larger than the
city's mean. So these are 772 different decisions, not one decision
printed 772 times.

Dose is per child by construction - µg·h for one child - so none of this
needs an enrolment figure, and none of it is invented. Where a number
would have to be made up, it is not reported.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path

import httpx

from . import exposure as ex
from . import policy as P
from .replay import cpcb_band
from .school import ACTIVITIES, Cohort
from .sources import AQ_URL, CACHE_DIR, TZ, WX_URL, Hour, Series

DATA = Path(__file__).resolve().parent.parent / "data" / "delhi_schools.json"
BOUNDARY = Path(__file__).resolve().parent.parent / "data" / "delhi_boundary.json"
# Open-Meteo counts every location against its per-minute quota, so 922
# schools across two endpoints is ~1,844 units. Batch, pause, and back off:
# this is a free public service and the whole project depends on it.
BATCH = 100
PAUSE_S = 13.0
MAX_RETRIES = 5
# The city picture is a once-a-day artefact, so it is cached for the day
# rather than for minutes.
CITY_CACHE_TTL_S = 20 * 60 * 60

# The most permissive case: a class with nobody on the respiratory
# register. If the protocol still pulls this class indoors, no class at
# that school is going out.
BASELINE = Cohort("city", "A class with no register", 8, 40, ())


@dataclass(frozen=True)
class SchoolAir:
    osm_id: str
    name: str
    lat: float
    lon: float
    peak_pm25: float
    mean_pm25: float
    cpcb_band: str
    games_dose: float
    day_dose: float
    budget_pct: float
    games_allowed: bool
    clauses: list[str]

    @property
    def over_weekly_budget(self) -> bool:
        """One games period costing more than a child's whole WHO week."""
        return self.games_dose > ex.WEEKLY_BUDGET


@dataclass
class CityPicture:
    day: str
    computed_at: str
    schools: list[SchoolAir]
    source: str
    attribution: str

    @property
    def count(self) -> int:
        return len(self.schools)

    @property
    def worst(self) -> list[SchoolAir]:
        return sorted(self.schools, key=lambda s: -s.day_dose)[:10]

    @property
    def best(self) -> list[SchoolAir]:
        return sorted(self.schools, key=lambda s: s.day_dose)[:10]

    @property
    def grounded(self) -> int:
        """Schools where even a class with no register cannot hold games."""
        return sum(1 for s in self.schools if not s.games_allowed)

    @property
    def over_budget(self) -> int:
        return sum(1 for s in self.schools if s.over_weekly_budget)

    def summary(self) -> dict:
        peaks = [s.peak_pm25 for s in self.schools]
        doses = [s.day_dose for s in self.schools]
        bands: dict[str, int] = {}
        for s in self.schools:
            bands[s.cpcb_band] = bands.get(s.cpcb_band, 0) + 1
        return {
            "day": self.day,
            "computed_at": self.computed_at,
            "schools": self.count,
            "pm25_min": round(min(peaks), 1),
            "pm25_max": round(max(peaks), 1),
            "pm25_mean": round(sum(peaks) / len(peaks), 1),
            "pm25_spread": round(max(peaks) - min(peaks), 1),
            "dose_min": round(min(doses), 1),
            "dose_max": round(max(doses), 1),
            "dose_mean": round(sum(doses) / len(doses), 1),
            "grounded": self.grounded,
            "grounded_pct": round(100 * self.grounded / self.count, 1),
            "over_weekly_budget": self.over_budget,
            "over_weekly_budget_pct": round(100 * self.over_budget / self.count, 1),
            "bands": dict(sorted(bands.items(), key=lambda kv: -kv[1])),
            "who_weekly_budget": ex.WEEKLY_BUDGET,
            "source": self.source,
            "attribution": self.attribution,
        }


def _inside(lon: float, lat: float, rings: list[list[list[float]]]) -> bool:
    """Ray casting against the NCT outline.

    The schools were collected from a bounding box, and a box around Delhi
    also contains Gurugram, Noida and Faridabad. Those are real schools
    with real air, but they are not in Delhi, and saying "922 schools in
    Delhi" while counting them would be false.
    """
    inside = False
    for ring in rings:
        n = len(ring)
        for i in range(n):
            x1, y1 = ring[i]
            x2, y2 = ring[(i + 1) % n]
            if (y1 > lat) != (y2 > lat):
                xint = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
                if lon < xint:
                    inside = not inside
    return inside


def load_schools(clip: bool = True) -> tuple[list[dict], str]:
    """Named schools inside Delhi NCT, with their attribution."""
    doc = json.loads(DATA.read_text())
    schools = doc["schools"]
    attribution = doc["attribution"]
    if clip and BOUNDARY.exists():
        geo = json.loads(BOUNDARY.read_text())
        rings = geo["coordinates"]
        schools = [s for s in schools if _inside(s["lon"], s["lat"], rings)]
    return schools, attribution


def _series_for(
    times: list[str], pm: list[float | None], mix: list[float | None], lat: float, lon: float
) -> Series:
    return Series(
        hours=[
            Hour(
                t=datetime.fromisoformat(t),
                pm2_5=pm[i],
                pm10=None,
                mixing_height_m=mix[i] if i < len(mix) else None,
            )
            for i, t in enumerate(times)
        ],
        source="Open-Meteo CAMS, multi-location",
        fetched_at=datetime.now(),
        latitude=lat,
        longitude=lon,
    )


def _get_json(url: str, params: dict) -> list[dict]:
    """GET with backoff, and a clear error rather than a KeyError later.

    Open-Meteo answers a quota breach with HTTP 200 and an {"error": true}
    body, so the status code alone is not enough to know the call worked.
    """
    delay = PAUSE_S
    last = ""
    for attempt in range(MAX_RETRIES):
        r = httpx.get(url, params=params, timeout=180.0)
        try:
            payload = r.json()
        except Exception:
            last = f"HTTP {r.status_code}, unparseable body"
            payload = None
        if isinstance(payload, dict) and payload.get("error"):
            last = str(payload.get("reason", "unknown error"))
        elif payload is not None and r.status_code == 200:
            return payload if isinstance(payload, list) else [payload]
        else:
            last = f"HTTP {r.status_code}"
        time.sleep(delay)
        delay *= 1.6
    raise RuntimeError(f"Open-Meteo refused after {MAX_RETRIES} tries: {last}")


def _fetch_batch(batch: list[dict]) -> list[tuple[dict, Series]]:
    """One request for up to BATCH schools, air and weather together."""
    la = ",".join(str(s["lat"]) for s in batch)
    lo = ",".join(str(s["lon"]) for s in batch)
    common = {"latitude": la, "longitude": lo, "forecast_days": 1, "timezone": TZ}

    aq = _get_json(AQ_URL, {**common, "hourly": "pm2_5"})
    time.sleep(PAUSE_S)
    wx = _get_json(WX_URL, {**common, "hourly": "boundary_layer_height"})

    out = []
    for school, a, w in zip(batch, aq, wx):
        out.append(
            (
                school,
                _series_for(
                    a["hourly"]["time"],
                    a["hourly"]["pm2_5"],
                    w["hourly"].get("boundary_layer_height", []),
                    school["lat"],
                    school["lon"],
                ),
            )
        )
    return out


def _assess(school: dict, series: Series, day: date) -> SchoolAir | None:
    games = ACTIVITIES["games"]
    hours = series.between(day, games.start_h, games.end_h)
    if not hours:
        return None
    pm = [h.pm2_5 for h in hours if h.pm2_5 is not None]
    if not pm:
        return None
    mixes = [h.mixing_height_m for h in hours if h.mixing_height_m is not None]
    mixing = min(mixes) if mixes else 9999.0

    games_dose = ex.activity_dose(series, day, games)
    day_dose, _ = ex.day_dose(series, day)
    if games_dose is None:
        return None

    indoor = ex.activity_dose(series, day, games, indoors=True)
    avoidable = max(0.0, games_dose.dose - (indoor.dose if indoor else 0.0))

    ruling = P.ask(
        P.HOLD_VIGOROUS,
        BASELINE.key,
        BASELINE.grade,
        BASELINE.strength,
        BASELINE.on_register,
        peak_pm25=max(pm),
        mean_pm25=sum(pm) / len(pm),
        mixing_height_m=mixing,
        avoidable_dose=avoidable,
        dose_today=0.0,
    )

    return SchoolAir(
        osm_id=school["osm_id"],
        name=school["name"],
        lat=school["lat"],
        lon=school["lon"],
        peak_pm25=round(max(pm), 1),
        mean_pm25=round(sum(pm) / len(pm), 1),
        cpcb_band=cpcb_band(max(pm)),
        games_dose=games_dose.dose,
        day_dose=day_dose,
        budget_pct=round(games_dose.budget_pct, 1),
        games_allowed=ruling.allowed,
        clauses=[c for c in ruling.clause_ids if c != "P0"],
    )


def picture(
    day: date | None = None,
    limit: int | None = None,
    progress=None,
) -> CityPicture:
    """Run the protocol across every mapped school in Delhi."""
    target = day or date.today()
    cache = CACHE_DIR / f"city_{target.isoformat()}.json"
    CACHE_DIR.mkdir(exist_ok=True)
    if cache.exists() and time.time() - cache.stat().st_mtime < CITY_CACHE_TTL_S:
        raw = json.loads(cache.read_text())
        return CityPicture(
            day=raw["day"],
            computed_at=raw["computed_at"],
            schools=[SchoolAir(**s) for s in raw["schools"]],
            source=raw["source"],
            attribution=raw["attribution"],
        )

    schools, attribution = load_schools()
    if limit:
        schools = schools[:limit]

    assessed: list[SchoolAir] = []
    batches = range(0, len(schools), BATCH)
    for n, i in enumerate(batches):
        if n:
            time.sleep(PAUSE_S)
        for school, series in _fetch_batch(schools[i : i + BATCH]):
            a = _assess(school, series, target)
            if a:
                assessed.append(a)
        if progress:
            progress(min(i + BATCH, len(schools)), len(schools))

    if not assessed:
        raise RuntimeError("no school could be assessed")

    out = CityPicture(
        day=target.isoformat(),
        computed_at=datetime.now().isoformat(timespec="seconds"),
        schools=assessed,
        source="Open-Meteo CAMS air quality + forecast (no key, free tier)",
        attribution=attribution,
    )
    cache.write_text(
        json.dumps(
            {
                "day": out.day,
                "computed_at": out.computed_at,
                "source": out.source,
                "attribution": out.attribution,
                "schools": [asdict(s) for s in out.schools],
            }
        )
    )
    return out

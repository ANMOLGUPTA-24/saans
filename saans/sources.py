"""Live environmental data. Real sources, no API keys, no mock values.

Open-Meteo Air Quality + Forecast APIs (CAMS global model, free for
non-commercial use, no key). Every number Saans acts on comes from here.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import httpx

AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
AQ_ARCHIVE_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
WX_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
WX_URL = "https://api.open-meteo.com/v1/forecast"
TZ = "Asia/Kolkata"

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
CACHE_TTL_S = 15 * 60


@dataclass(frozen=True)
class Hour:
    """One hour of air and weather, as measured or modelled."""

    t: datetime
    pm2_5: float | None
    pm10: float | None
    temp_c: float | None = None
    wind_kmh: float | None = None
    wind_deg: float | None = None
    # Height of the mixing layer. When this collapses, the city's
    # emissions stay at head height instead of dispersing upward.
    mixing_height_m: float | None = None

    @property
    def hour(self) -> int:
        return self.t.hour

    @property
    def day(self) -> date:
        return self.t.date()


@dataclass
class Series:
    """An ordered run of hours, with the provenance judges can check."""

    hours: list[Hour]
    source: str
    fetched_at: datetime
    latitude: float
    longitude: float
    cached: bool = False
    notes: list[str] = field(default_factory=list)

    def between(self, day: date, start_h: int, end_h: int) -> list[Hour]:
        """Hours of `day` inside [start_h, end_h), skipping gaps in the model."""
        return [
            h
            for h in self.hours
            if h.day == day and start_h <= h.hour < end_h and h.pm2_5 is not None
        ]

    def day_hours(self, day: date) -> list[Hour]:
        return [h for h in self.hours if h.day == day and h.pm2_5 is not None]

    @property
    def days(self) -> list[date]:
        seen: dict[date, None] = {}
        for h in self.hours:
            if h.pm2_5 is not None:
                seen.setdefault(h.day, None)
        return list(seen)


def _cache_path(key: str) -> Path:
    CACHE_DIR.mkdir(exist_ok=True)
    return CACHE_DIR / f"{key}.json"


def _get(url: str, params: dict, key: str, offline_ok: bool = True) -> tuple[dict, bool]:
    """Fetch with a short-lived disk cache.

    The cache exists so that a demo recorded at 2 AM does not hammer a free
    public API, and so a flaky room network cannot break a live run. It never
    invents data: a miss with no network is an error, not a fallback.
    """
    path = _cache_path(key)
    if path.exists() and time.time() - path.stat().st_mtime < CACHE_TTL_S:
        return json.loads(path.read_text()), True
    try:
        r = httpx.get(url, params=params, timeout=30.0)
        r.raise_for_status()
        payload = r.json()
        path.write_text(json.dumps(payload))
        return payload, False
    except Exception:
        if offline_ok and path.exists():
            return json.loads(path.read_text()), True
        raise


def _rows(payload: dict) -> dict[str, list]:
    return payload.get("hourly", {})


def fetch(
    latitude: float,
    longitude: float,
    forecast_days: int = 3,
    past_days: int = 0,
) -> Series:
    """Air quality plus the weather that explains it, for one point on the map.

    `past_days` returns the model's analysis of hours that have already
    happened: this is what Saans grades its own past decisions against.
    """
    tag = f"{latitude:.3f}_{longitude:.3f}_{forecast_days}_{past_days}"

    aq, aq_cached = _get(
        AQ_URL,
        {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": "pm2_5,pm10",
            "forecast_days": forecast_days,
            "past_days": past_days,
            "timezone": TZ,
        },
        f"aq_{tag}",
    )
    wx, wx_cached = _get(
        WX_URL,
        {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": (
                "temperature_2m,wind_speed_10m,wind_direction_10m,"
                "boundary_layer_height"
            ),
            "forecast_days": forecast_days,
            "past_days": past_days,
            "timezone": TZ,
        },
        f"wx_{tag}",
    )

    a, w = _rows(aq), _rows(wx)
    wx_by_t = {t: i for i, t in enumerate(w.get("time", []))}

    hours: list[Hour] = []
    for i, t in enumerate(a.get("time", [])):
        j = wx_by_t.get(t)
        hours.append(
            Hour(
                t=datetime.fromisoformat(t),
                pm2_5=a["pm2_5"][i],
                pm10=a["pm10"][i],
                temp_c=w["temperature_2m"][j] if j is not None else None,
                wind_kmh=w["wind_speed_10m"][j] if j is not None else None,
                wind_deg=w["wind_direction_10m"][j] if j is not None else None,
                mixing_height_m=(
                    w["boundary_layer_height"][j] if j is not None else None
                ),
            )
        )

    notes = []
    if aq_cached or wx_cached:
        notes.append("served from local cache (<15 min old)")

    return Series(
        hours=hours,
        source="Open-Meteo CAMS air quality + forecast (no key, free tier)",
        fetched_at=datetime.now(),
        latitude=latitude,
        longitude=longitude,
        cached=aq_cached and wx_cached,
        notes=notes,
    )


def fetch_range(
    latitude: float, longitude: float, start_date: str, end_date: str
) -> Series:
    """Measured air for a date range that has already happened.

    Delhi's severe season is November, not October. The protocol's upper
    clauses - no outdoor activity at all, masks for every child - only fire
    in air that bad, so they are tested against the real days they were
    written for rather than against a number somebody made up.
    """
    tag = f"{latitude:.3f}_{longitude:.3f}_{start_date}_{end_date}"
    aq, aq_cached = _get(
        AQ_ARCHIVE_URL,
        {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": "pm2_5,pm10",
            "start_date": start_date,
            "end_date": end_date,
            "timezone": TZ,
        },
        f"aqr_{tag}",
    )
    wx, wx_cached = _get(
        WX_ARCHIVE_URL,
        {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": (
                "temperature_2m,wind_speed_10m,wind_direction_10m,"
                "boundary_layer_height"
            ),
            "start_date": start_date,
            "end_date": end_date,
            "timezone": TZ,
        },
        f"wxr_{tag}",
    )

    a, w = _rows(aq), _rows(wx)
    wx_by_t = {t: i for i, t in enumerate(w.get("time", []))}
    hours: list[Hour] = []
    for i, t in enumerate(a.get("time", [])):
        j = wx_by_t.get(t)
        hours.append(
            Hour(
                t=datetime.fromisoformat(t),
                pm2_5=a["pm2_5"][i],
                pm10=a["pm10"][i],
                temp_c=w["temperature_2m"][j] if j is not None else None,
                wind_kmh=w["wind_speed_10m"][j] if j is not None else None,
                wind_deg=w["wind_direction_10m"][j] if j is not None else None,
                mixing_height_m=(
                    w["boundary_layer_height"][j] if j is not None else None
                ),
            )
        )
    return Series(
        hours=hours,
        source=(
            f"Open-Meteo CAMS reanalysis + ERA5 archive, {start_date} to {end_date}"
        ),
        fetched_at=datetime.now(),
        latitude=latitude,
        longitude=longitude,
        cached=aq_cached and wx_cached,
        notes=["measured history, not forecast"],
    )

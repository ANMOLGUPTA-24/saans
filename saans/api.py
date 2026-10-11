"""HTTP surface.

One FastAPI app serving the dashboard, the protocol, the ledger and the
agent. Nothing here makes a decision: every route delegates to the
protocol engine and reports what came back.
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from . import cloud
from . import exposure as ex
from . import policy as P
from .decide import decide
from .notice import render
from .city import picture
from .replay import replay
from .stability import analyse
from .school import (
    COHORTS,
    LATITUDE,
    LONGITUDE,
    OUTDOOR_DAY,
    SCHOOL_NAME,
    SCHOOL_NOTE,
    SHIFT,
    TOTAL_CHILDREN,
    TOTAL_ON_REGISTER,
)
from .sources import fetch, fetch_range

WEB = Path(__file__).resolve().parent.parent / "web"
NOVEMBER = ("2025-11-03", "2025-11-14")

app = FastAPI(title="Saans", docs_url="/api/docs")


@lru_cache(maxsize=4)
def _series(past_days: int):
    return fetch(LATITUDE, LONGITUDE, forecast_days=3, past_days=past_days)


@lru_cache(maxsize=2)
def _november():
    return fetch_range(LATITUDE, LONGITUDE, *NOVEMBER)


def _target_day(series, day: str | None) -> date:
    if day:
        d = date.fromisoformat(day)
    else:
        d = date.today()
        if d not in series.days:
            d = series.days[0]
    if d not in series.days:
        raise HTTPException(404, f"no data covers {d}")
    return d


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/data/{name}")
def data_file(name: str):
    """Serve the committed geographic data the page draws with."""
    if name not in ("delhi_boundary.json", "delhi_schools.json"):
        raise HTTPException(404, "no such file")
    path = Path(__file__).resolve().parent.parent / "data" / name
    if not path.exists():
        raise HTTPException(404, "not built")
    return FileResponse(path, media_type="application/json")


@app.get("/api/school")
def school():
    return {
        "name": SCHOOL_NAME,
        "note": SCHOOL_NOTE,
        "shift": SHIFT,
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "children": TOTAL_CHILDREN,
        "on_register": TOTAL_ON_REGISTER,
        "cohorts": [
            {
                "key": c.key,
                "label": c.label,
                "grade": c.grade,
                "strength": c.strength,
                "on_register": c.on_register,
            }
            for c in COHORTS
        ],
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
        "who_weekly_budget": ex.WEEKLY_BUDGET,
        "outdoor_hours_per_week": ex.OUTDOOR_HOURS_PER_WEEK,
    }


@app.get("/api/protocol")
def protocol():
    return {
        "sha256": P.PROTOCOL_PATH.read_bytes().hex()[:0]
        or __import__("hashlib").sha256(P.PROTOCOL_PATH.read_bytes()).hexdigest()[:16],
        "path": P.PROTOCOL_PATH.name,
        "engine": "Cedar (cedarpy), AWS open source",
        "clauses": [
            {"id": c.id, "effect": c.effect, "text": c.text} for c in P.clauses()
        ],
        "source": P.PROTOCOL_PATH.read_text(),
    }


@app.get("/api/today")
def today(day: str | None = None):
    s = _series(14)
    d = decide(s, _target_day(s, day))
    return d.to_json()


@app.get("/api/hours")
def hours(day: str | None = None):
    """The hour-by-hour air the decision was made from."""
    s = _series(14)
    target = _target_day(s, day)
    return {
        "day": target.isoformat(),
        "source": s.source,
        "hours": [
            {
                "hour": h.hour,
                "pm2_5": h.pm2_5,
                "pm10": h.pm10,
                "mixing_height_m": h.mixing_height_m,
                "temp_c": h.temp_c,
                "wind_kmh": h.wind_kmh,
            }
            for h in s.day_hours(target)
        ],
        "safest": ex.safest_window(s, target, length_h=1),
    }


@app.get("/api/replay")
def api_replay(window: str = "recent"):
    """Impact over real days: the fortnight just gone, or last November."""
    if window == "november":
        r = replay(_november())
        label = f"Delhi smog season, {NOVEMBER[0]} to {NOVEMBER[1]} (measured)"
    else:
        s = _series(14)
        r = replay(s, [d for d in s.days if d <= date.today()])
        label = "the last fortnight at this school (measured + forecast)"
    return {
        "window": window,
        "label": label,
        "school_days": r.school_days,
        "quiet_days": r.quiet_days,
        "dose_business_as_usual": r.dose_business_as_usual,
        "dose_under_protocol": r.dose_under_protocol,
        "dose_saved": r.dose_saved,
        "saved_pct": r.saved_pct,
        "who_weeks_business_as_usual": r.who_weeks_business_as_usual,
        "who_weeks_under_protocol": r.who_weeks_under_protocol,
        "child_hours_saved": r.child_hours_saved,
        "children": r.children,
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
                "changed": o.activities_changed,
                "clauses": o.clauses_fired,
            }
            for o in r.days
        ],
    }


SNAPSHOT = Path(__file__).resolve().parent.parent / "data" / "snapshot.json"
ON_LAMBDA = bool(os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))


@app.get("/api/city")
def city(limit: int | None = None):
    """The same protocol, run across every mapped school in Delhi.

    Deriving this live means ~770 locations across two endpoints, throttled
    to respect a free public API - minutes of work. On Lambda that is
    served from the committed snapshot, which this same engine produced.
    """
    if ON_LAMBDA and SNAPSHOT.exists():
        import json as _json

        doc = _json.loads(SNAPSHOT.read_text())
        c = doc.get("city")
        if c:
            return {
                "summary": c["summary"],
                "schools": c["schools"],
                "worst": [
                    {
                        "name": s["name"],
                        "pm": s["peak_pm25"],
                        "dose": s["day_dose"],
                        "band": s["cpcb_band"],
                    }
                    for s in c["worst"]
                ],
                "best": [
                    {
                        "name": s["name"],
                        "pm": s["peak_pm25"],
                        "dose": s["day_dose"],
                        "band": s["cpcb_band"],
                    }
                    for s in c["best"][:5]
                ],
                "from_snapshot": doc.get("generated_at"),
            }
    try:
        p = picture(limit=limit)
    except Exception as e:
        raise HTTPException(503, f"city picture unavailable: {type(e).__name__}: {e}")
    return {
        "summary": p.summary(),
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
            for s in p.schools
        ],
        "worst": [
            {"name": s.name, "pm": s.peak_pm25, "dose": s.day_dose, "band": s.cpcb_band}
            for s in p.worst
        ],
        "best": [
            {"name": s.name, "pm": s.peak_pm25, "dose": s.day_dose, "band": s.cpcb_band}
            for s in p.best[:5]
        ],
    }


@app.get("/api/stability")
def stability(day: str | None = None):
    """How wrong the forecast can be before today's decisions change."""
    s = _series(14)
    return analyse(s, _target_day(s, day)).to_json()


@app.get("/api/cloud")
def cloud_status():
    st = cloud.ensure_infra()
    return {
        "mode": st.mode,
        "all_up": st.all_up,
        "services": {
            "dynamodb": st.dynamodb,
            "s3": st.s3,
            "eventbridge": st.eventbridge,
            "ses": st.ses,
        },
        "detail": st.detail,
        "table": cloud.TABLE,
        "bucket": cloud.BUCKET,
        "rule": cloud.RULE,
        "schedule": cloud.MORNING_CRON,
    }


class RunRequest(BaseModel):
    day: str | None = None
    recipients: list[str] = [
        "principal@shalimarbagh.edu.in",
        "register-parents@shalimarbagh.edu.in",
    ]
    use_model: bool = True


@app.post("/api/run")
def run(req: RunRequest):
    """The 05:45 job, run on demand.

    Decide, draft the notice, write the ledger, store the notice, send it.
    Returns what each step actually produced so the page can show the
    receipts rather than a success message.
    """
    s = _series(14)
    d = decide(s, _target_day(s, req.day))

    author = "deterministic template"
    rejected = None
    summary = None
    if req.use_model:
        try:
            from .agent import draft_summary

            draft = draft_summary(d)
            summary, author, rejected = draft.text, draft.author, draft.rejected
        except Exception as e:
            rejected = f"{type(e).__name__}: {e}"

    html = render(d, summary=summary, author=author)
    d.notice = summary
    d.notice_author = author

    receipts: dict[str, str] = {}
    errors: dict[str, str] = {}
    try:
        receipts["ledger"] = cloud.put_decision(d.to_json())
    except Exception as e:
        errors["ledger"] = f"{type(e).__name__}"
    try:
        receipts["notice"] = cloud.put_notice(d.day, html)
    except Exception as e:
        errors["notice"] = f"{type(e).__name__}"
    try:
        sent = cloud.send_notice(
            req.recipients, f"Air protocol - {d.day} - {SCHOOL_NAME}", html
        )
        receipts["email"] = f"ses:{sent['message_id'][:20]} -> {len(sent['recipients'])} recipients"
    except Exception as e:
        errors["email"] = f"{type(e).__name__}"

    return {
        "day": d.day,
        "notice_author": author,
        "guard_rejected": rejected,
        "summary": summary,
        "receipts": receipts,
        "errors": errors,
        "decision": d.to_json(),
    }


@app.get("/api/ledger")
def ledger():
    try:
        rows = cloud.ledger(SCHOOL_NAME)
    except Exception as e:
        return JSONResponse(
            {"rows": [], "error": f"ledger unavailable: {type(e).__name__}"},
            status_code=200,
        )
    return {
        "rows": [
            {
                "day": r["day"],
                "decided_at": r["decided_at"],
                "protocol_sha256": r["protocol_sha256"],
                "evidence_sha256": r["evidence_sha256"],
                "dose_saved_per_child": r["record"].get("dose_saved_per_child"),
                "children_affected": r.get("children_affected"),
                "register_affected": r.get("register_affected"),
            }
            for r in rows
        ]
    }


@app.get("/api/notice/{day}", response_class=HTMLResponse)
def notice(day: str):
    stored = cloud.get_notice(day)
    if stored:
        return HTMLResponse(stored)
    s = _series(14)
    return HTMLResponse(render(decide(s, _target_day(s, day))))


@app.get("/api/sent")
def sent():
    return {"messages": cloud.sent_messages()}


class AskRequest(BaseModel):
    question: str


@app.post("/api/ask")
def api_ask(req: AskRequest):
    """Put a question to the Strands agent."""
    try:
        from .agent import ask as agent_ask

        return {"question": req.question, "answer": agent_ask(req.question)}
    except Exception as e:
        raise HTTPException(503, f"agent unavailable: {type(e).__name__}: {e}")


# ----- AWS Lambda entrypoint ---------------------------------------------
#
# The same FastAPI app, served by Lambda behind a Function URL. Nothing
# about the protocol changes: Cedar still decides, the ledger is the real
# DynamoDB table, the notice lands in the real bucket.
#
# Two deliberate differences in this runtime:
#   - There is no local model, so the notice's opening line comes from the
#     deterministic summary. The guard's fallback path is the normal path
#     here rather than an error case.
#   - /api/city serves the committed snapshot instead of re-fetching ~770
#     schools, which would take minutes and hammer a free public API on
#     every cold start.
try:  # pragma: no cover - only meaningful in the deployed runtime
    from mangum import Mangum

    handler = Mangum(app, lifespan="off")
except ImportError:  # local dev without mangum installed
    handler = None

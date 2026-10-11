"""Tests for the parts that would hurt somebody if they were wrong.

Everything here runs offline against synthetic hours, so the suite does not
depend on what Delhi's air happens to be doing today. The one network test
is marked and skipped by default.
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from saans import exposure as ex
from saans import policy as P
from saans.decide import HELD, INDOORS, MOVED, decide
from saans.notice import render
from saans.replay import cpcb_band, replay
from saans.school import COHORTS, OUTDOOR_DAY
from saans.sources import Hour, Series

DAY = date(2026, 11, 12)


def series(pm_by_hour: dict[int, float], mixing: float = 1200.0) -> Series:
    """A day of air, hour by hour, with everything else held constant."""
    return Series(
        hours=[
            Hour(
                t=datetime(DAY.year, DAY.month, DAY.day, h),
                pm2_5=pm,
                pm10=pm * 2,
                temp_c=24.0,
                wind_kmh=6.0,
                wind_deg=300.0,
                mixing_height_m=mixing,
            )
            for h, pm in sorted(pm_by_hour.items())
        ],
        source="synthetic",
        fetched_at=datetime(2026, 11, 12, 5, 45),
        latitude=28.7,
        longitude=77.15,
    )


def flat(pm: float, mixing: float = 1200.0) -> Series:
    return series({h: pm for h in range(6, 16)}, mixing=mixing)


REGISTER = next(c for c in COHORTS if c.on_register)
NO_REGISTER = next(c for c in COHORTS if not c.on_register)


# --- the clause index -----------------------------------------------------


def test_clause_ids_are_parsed_in_file_order():
    """Cedar reports determining policies positionally, so order is load-bearing.

    If the parse and the policy set ever drift apart, every citation on
    every notice silently points at the wrong clause.
    """
    ids = [c.id for c in P.clauses()]
    assert ids == sorted(ids, key=lambda s: int(s[1:]))
    assert ids[0] == "P0"
    assert len(ids) == len(set(ids))


def test_parsed_clause_count_matches_the_policy_file():
    text = P.PROTOCOL_PATH.read_text()
    written = sum(
        1
        for line in text.splitlines()
        if line.strip().startswith(("permit (", "forbid ("))
    )
    assert written == len(P.clauses())


def test_every_clause_is_reachable_by_its_index():
    for clause in P.clauses():
        assert P._clause_for(f"policy{clause.index}") is clause


# --- Cedar contract -------------------------------------------------------


def ask(action, cohort, **ctx):
    base = dict(
        peak_pm25=50.0, mean_pm25=50.0, mixing_height_m=1200.0,
        avoidable_dose=0.0, dose_today=0.0,
    )
    base.update(ctx)
    return P.ask(
        action, cohort.key, cohort.grade, cohort.strength, cohort.on_register, **base
    )


def test_context_reaches_cedar_as_integers():
    """Cedar has no float type; a float silently fails the whole request."""
    r = ask(P.HOLD_OUTDOORS, NO_REGISTER, peak_pm25=63.7, mixing_height_m=512.4)
    assert r.errors == []
    assert all(isinstance(v, int) for v in r.context.values())


def test_clean_air_is_a_normal_school_day():
    r = ask(P.HOLD_VIGOROUS, NO_REGISTER, peak_pm25=25.0)
    assert r.allowed
    assert r.clause_ids == ["P0"]
    assert r.citation == "P0 - normal school day"


@pytest.mark.parametrize(
    "action,cohort,ctx,clause",
    [
        (P.HOLD_VIGOROUS, NO_REGISTER, {"peak_pm25": 95.0}, "P1"),
        (P.HOLD_OUTDOORS, NO_REGISTER, {"peak_pm25": 130.0}, "P2"),
        (P.HOLD_OUTDOORS, REGISTER, {"peak_pm25": 65.0}, "P3"),
        (
            P.HOLD_OUTDOORS,
            NO_REGISTER,
            {"peak_pm25": 65.0, "mixing_height_m": 300.0},
            "P4",
        ),
        (P.HOLD_OUTDOORS, NO_REGISTER, {"avoidable_dose": 80.0}, "P5"),
        (P.HOLD_OUTDOORS, NO_REGISTER, {"dose_today": 140.0}, "P6"),
        (P.KEEP_WINDOWS_OPEN, NO_REGISTER, {"peak_pm25": 75.0}, "P7"),
        (P.OMIT_MASKS, REGISTER, {"peak_pm25": 95.0}, "P8"),
        (P.OMIT_MASKS, NO_REGISTER, {"peak_pm25": 130.0}, "P8"),
    ],
)
def test_each_clause_fires_on_the_case_it_was_written_for(action, cohort, ctx, clause):
    r = ask(action, cohort, **ctx)
    assert not r.allowed
    assert clause in r.clause_ids


@pytest.mark.parametrize(
    "action,cohort,ctx",
    [
        (P.HOLD_VIGOROUS, NO_REGISTER, {"peak_pm25": 90.0}),   # P1 is strictly >
        (P.HOLD_OUTDOORS, NO_REGISTER, {"peak_pm25": 120.0}),  # P2 is strictly >
        (P.HOLD_OUTDOORS, REGISTER, {"peak_pm25": 60.0}),      # P3 is strictly >
        (P.HOLD_OUTDOORS, NO_REGISTER, {"avoidable_dose": 50.0}),
        (P.HOLD_OUTDOORS, NO_REGISTER, {"dose_today": 99.0}),
        (P.KEEP_WINDOWS_OPEN, NO_REGISTER, {"peak_pm25": 60.0}),
    ],
)
def test_clauses_do_not_fire_one_step_below_their_threshold(action, cohort, ctx):
    assert ask(action, cohort, **ctx).allowed


def test_the_register_is_protected_where_other_classes_are_not():
    """The whole reason decisions are taken per class, not per school."""
    ctx = {"peak_pm25": 70.0}
    assert ask(P.HOLD_OUTDOORS, NO_REGISTER, **ctx).allowed
    assert not ask(P.HOLD_OUTDOORS, REGISTER, **ctx).allowed


def test_trapped_air_is_judged_worse_than_the_same_reading_on_a_breezy_day():
    assert ask(P.HOLD_OUTDOORS, NO_REGISTER, peak_pm25=70.0).allowed
    assert not ask(
        P.HOLD_OUTDOORS, NO_REGISTER, peak_pm25=70.0, mixing_height_m=400.0
    ).allowed


def test_an_unevaluable_protocol_fails_closed(monkeypatch):
    """A protocol that cannot be evaluated must never read as permission."""

    class Broken:
        decision = None

        class diagnostics:
            reasons: list[str] = []
            errors = ["entity type not declared"]

    monkeypatch.setattr(P.cedarpy, "is_authorized", lambda *a, **k: Broken)
    r = ask(P.HOLD_OUTDOORS, NO_REGISTER, peak_pm25=10.0)
    assert not r.allowed
    assert r.errors


# --- dose -----------------------------------------------------------------


def test_exertion_multiplies_dose():
    """Same air, same hour: a games period costs three times an assembly."""
    s = flat(100.0)
    assembly = next(a for a in OUTDOOR_DAY if a.key == "assembly")
    games = next(a for a in OUTDOOR_DAY if a.key == "games")
    a = ex.activity_dose(s, DAY, assembly)
    g = ex.activity_dose(s, DAY, games)
    assert a.dose == pytest.approx(100.0 * 0.5 * 1.0)
    assert g.dose == pytest.approx(100.0 * 1.0 * 3.0)
    assert g.dose / a.dose == pytest.approx(6.0)  # 3x exertion, 2x duration


def test_indoors_halves_dose_and_is_not_a_free_win():
    s = flat(100.0)
    games = next(a for a in OUTDOOR_DAY if a.key == "games")
    out = ex.activity_dose(s, DAY, games)
    inside = ex.activity_dose(s, DAY, games, indoors=True)
    assert inside.dose == pytest.approx(out.dose * ex.INDOOR_INFILTRATION)
    assert inside.dose > 0, "an unfiltered classroom is not clean air"


def test_a_purifier_beats_shut_windows_alone():
    s = flat(100.0)
    games = next(a for a in OUTDOOR_DAY if a.key == "games")
    assert (
        ex.activity_dose(s, DAY, games, indoors=True, purifier=True).dose
        < ex.activity_dose(s, DAY, games, indoors=True).dose
    )


def test_weekly_budget_is_the_who_guideline_times_outdoor_hours():
    assert ex.WEEKLY_BUDGET == ex.WHO_PM25_24H * ex.OUTDOOR_HOURS_PER_WEEK
    assert ex.OUTDOOR_HOURS_PER_WEEK == sum(a.hours for a in OUTDOOR_DAY) * 5


def test_safest_window_finds_the_actual_minimum():
    s = series({6: 90, 7: 90, 8: 90, 9: 20, 10: 90, 11: 90, 12: 90, 13: 90, 14: 90})
    assert ex.safest_window(s, DAY, length_h=1) == (9, 20.0)


def test_safest_window_returns_none_when_there_are_no_hours():
    assert ex.safest_window(series({}), DAY) is None


@pytest.mark.parametrize(
    "pm,band",
    [(10, "Good"), (30, "Good"), (45, "Satisfactory"), (75, "Moderate"),
     (110, "Poor"), (200, "Very Poor"), (400, "Severe")],
)
def test_cpcb_bands(pm, band):
    assert cpcb_band(pm) == band


# --- the decision ---------------------------------------------------------


def test_clean_day_changes_nothing_for_anybody():
    """A protocol that fires on a good day gets switched off in a fortnight."""
    d = decide(flat(20.0), DAY)
    assert d.cohorts
    for c in d.cohorts:
        assert c.changes == []
        assert all(k.verdict == HELD for k in c.calls)
        assert c.windows_open
        assert c.dose_saved == 0.0
    assert d.dose_saved_per_child == 0.0


def test_bad_day_moves_periods_indoors_and_cites_a_clause():
    d = decide(flat(140.0), DAY)
    for c in d.cohorts:
        assert c.changes
        assert not c.windows_open
        for call in c.changes:
            assert call.verdict in (MOVED, INDOORS)
            assert [x for x in call.cited if x != "P0"], "a change must cite a clause"
        assert c.dose_under_protocol < c.dose_business_as_usual


def test_a_period_is_relocated_rather_than_lost_when_a_clean_hour_exists():
    """Saans tries to keep the activity before it takes it away."""
    s = series({6: 200, 7: 200, 8: 15, 9: 200, 10: 200, 11: 200,
                12: 200, 13: 200, 14: 200})
    d = decide(s, DAY)
    verdicts = [k.verdict for c in d.cohorts for k in c.calls]
    assert MOVED in verdicts
    moved = next(k for c in d.cohorts for k in c.calls if k.verdict == MOVED)
    assert moved.moved_to is not None
    assert moved.dose_as_decided < moved.dose_if_outdoors


def test_relocation_is_not_preferred_when_indoors_is_genuinely_better():
    """A token move that leaves most of the avoidable dose on the table is
    worse for the child than simply going inside."""
    d = decide(flat(140.0), DAY)
    for c in d.cohorts:
        for k in c.calls:
            if k.verdict == MOVED:
                indoor_equivalent = k.dose_if_outdoors * ex.INDOOR_INFILTRATION
                assert k.dose_as_decided <= indoor_equivalent + 1e-6


def test_the_class_with_no_register_is_treated_differently_on_a_borderline_day():
    d = decide(flat(70.0), DAY)
    by_key = {c.cohort: c for c in d.cohorts}
    assert by_key[NO_REGISTER.key].dose_under_protocol > 0
    assert (
        len(by_key[REGISTER.key].changes) > len(by_key[NO_REGISTER.key].changes)
    ), "the register should bite before a blanket rule does"


def test_dose_today_accumulates_through_the_day():
    """P6 is a running stop-loss, so periods must be decided in order."""
    d = decide(flat(85.0), DAY)
    for c in d.cohorts:
        starts = [k.window for k in c.calls]
        assert starts == sorted(starts), "calls must be chronological"


def test_per_child_figure_is_a_weighted_mean_not_a_sum():
    """Summing per-child savings across classes overstates it by ~4x."""
    d = decide(flat(140.0), DAY)
    assert d.dose_saved_per_child <= max(c.dose_saved for c in d.cohorts) + 1e-6
    assert d.dose_saved_per_child >= min(c.dose_saved for c in d.cohorts) - 1e-6
    roll = sum(c.strength for c in d.cohorts)
    assert d.child_dose_hours_saved == pytest.approx(
        sum(c.dose_saved * c.strength for c in d.cohorts), rel=1e-6
    )
    assert d.child_dose_hours_saved == pytest.approx(
        d.dose_saved_per_child * roll, rel=1e-3
    )


def test_decision_records_what_it_was_decided_from():
    d = decide(flat(100.0), DAY)
    assert len(d.protocol_sha256) == 16
    assert len(d.evidence_sha256) == 16
    assert decide(flat(100.0), DAY).evidence_sha256 == d.evidence_sha256
    assert decide(flat(101.0), DAY).evidence_sha256 != d.evidence_sha256


def test_decision_serialises_with_the_derived_figures():
    j = decide(flat(100.0), DAY).to_json()
    for k in ("dose_saved_per_child", "child_dose_hours_saved", "total_dose_saved"):
        assert k in j
    assert "saved_pct" in j["cohorts"][0]


# --- replay ---------------------------------------------------------------


def test_replay_skips_weekends():
    week = [date(2026, 11, d) for d in range(9, 16)]  # Mon 9 - Sun 15
    s = Series(
        hours=[
            Hour(datetime(d.year, d.month, d.day, h), 100.0, 200.0,
                 24.0, 6.0, 300.0, 1200.0)
            for d in week
            for h in range(6, 16)
        ],
        source="synthetic",
        fetched_at=datetime(2026, 11, 9),
        latitude=28.7,
        longitude=77.15,
    )
    r = replay(s)
    assert r.school_days == 5
    assert all(date.fromisoformat(o.day).weekday() < 5 for o in r.days)


def test_replay_reports_quiet_days_on_clean_air():
    week = [date(2026, 11, d) for d in range(9, 14)]
    s = Series(
        hours=[
            Hour(datetime(d.year, d.month, d.day, h), 15.0, 30.0,
                 24.0, 6.0, 300.0, 1500.0)
            for d in week
            for h in range(6, 16)
        ],
        source="synthetic",
        fetched_at=datetime(2026, 11, 9),
        latitude=28.7,
        longitude=77.15,
    )
    r = replay(s)
    assert r.quiet_days == r.school_days
    assert r.dose_saved == 0.0


# --- the notice and the guard --------------------------------------------


def test_notice_renders_every_class_and_the_provenance():
    d = decide(flat(130.0), DAY)
    html = render(d)
    for c in d.cohorts:
        assert c.label in html
    assert d.protocol_sha256 in html
    assert d.evidence_sha256 in html
    assert "µg·h" in html
    assert "खिड़कियाँ" in html, "the notice is for parents, in Hindi too"


def test_guard_rejects_numbers_the_record_does_not_support():
    from saans.agent import guard

    d = decide(flat(100.0), DAY)
    assert guard("847 children were kept inside today.", d)
    assert guard("The air is poor, so outdoor periods move inside.", d) is None


def test_guard_rejects_the_claim_that_indoors_is_safe():
    from saans.agent import guard

    d = decide(flat(100.0), DAY)
    assert guard("Children are safe indoors today.", d)
    assert guard("The air is safe now.", d)
    # Caring about safety in general is not the same claim.
    assert guard("Periods move inside for the safety of the children.", d) is None


def test_guard_rejects_cancellation_language():
    from saans.agent import guard

    d = decide(flat(100.0), DAY)
    assert guard("The games period has been cancelled.", d)


def test_guard_rejects_overgeneralising_a_mixed_decision():
    from saans.agent import guard

    d = decide(flat(70.0), DAY)
    if any(not c.changes for c in d.cohorts):
        assert guard("All outdoor periods move indoors today.", d)


def test_guard_rejects_index_language():
    from saans.agent import guard

    d = decide(flat(100.0), DAY)
    assert guard("The AQI is very high today.", d)


def test_plain_summary_is_always_available_without_a_model():
    from saans.notice import plain_summary

    assert "clean enough" in plain_summary(decide(flat(15.0), DAY))
    assert plain_summary(decide(flat(140.0), DAY))


@pytest.mark.network
def test_live_sources_return_hours_for_the_school():
    from saans.school import LATITUDE, LONGITUDE
    from saans.sources import fetch

    s = fetch(LATITUDE, LONGITUDE, forecast_days=1, past_days=1)
    assert s.hours
    assert any(h.pm2_5 is not None for h in s.hours)


# --- decision stability under forecast error ------------------------------


def test_a_clean_day_is_stable_whatever_the_forecast_error():
    """20 ug/m3 +40% is still 28: nothing should flip."""
    from saans.stability import analyse

    st = analyse(flat(20.0), DAY)
    assert st.total
    assert st.stable == st.total
    assert st.marginal == []


def test_a_decision_on_a_threshold_is_reported_as_marginal():
    """61 ug/m3 sits one unit over P3's NAAQS threshold of 60."""
    from saans.stability import analyse

    st = analyse(flat(61.0), DAY)
    assert st.marginal, "a call this close to a threshold must not read as certain"
    assert all(m.flips_at is not None for m in st.marginal)


def test_the_games_period_is_the_most_robust_decision():
    """The call that matters most carries 3x the dose, so it should be the
    last one to flip, not the first."""
    from saans.stability import analyse

    st = analyse(flat(85.0), DAY)
    games = [c for c in st.calls if c.activity == "games"]
    assert games
    assert all(c.stable for c in games)


def test_scaling_changes_concentration_and_nothing_else():
    from saans.stability import scale

    s = flat(100.0, mixing=700.0)
    up = scale(s, 0.25)
    assert up.hours[0].pm2_5 == pytest.approx(125.0)
    assert up.hours[0].mixing_height_m == 700.0
    assert len(up.hours) == len(s.hours)


def test_scaling_never_produces_negative_concentration():
    from saans.stability import scale

    assert scale(flat(10.0), -2.0).hours[0].pm2_5 == 0.0


# --- the city -------------------------------------------------------------


def test_the_school_dataset_is_real_and_attributed():
    from saans.city import load_schools

    schools, attribution = load_schools()
    assert len(schools) > 600
    assert "OpenStreetMap" in attribution and "ODbL" in attribution
    for s in schools[:50]:
        assert s["name"].strip()
        assert 28.3 < s["lat"] < 29.0, "inside the Delhi bounding box"
        assert 76.8 < s["lon"] < 77.4
        assert s["osm_id"]


def test_school_coordinates_are_unique_enough_to_be_real_places():
    from saans.city import load_schools

    schools, _ = load_schools()
    coords = {(s["lat"], s["lon"]) for s in schools}
    assert len(coords) > 0.9 * len(schools), "near-duplicate rows suggest bad dedup"


# --- the deployed runtime -------------------------------------------------


def test_the_lambda_handler_is_wired():
    """The deployed entrypoint has to exist, or the deploy ships nothing."""
    from saans import api

    assert api.handler is not None, "mangum handler missing"
    assert callable(api.handler)


def test_lambda_serves_the_city_from_the_snapshot(monkeypatch):
    """Deriving the city live is ~1,800 throttled requests to a free public
    API. On Lambda it must come from the committed snapshot instead."""
    import json

    from fastapi.testclient import TestClient

    from saans import api

    if not api.SNAPSHOT.exists():
        pytest.skip("snapshot not built")
    monkeypatch.setattr(api, "ON_LAMBDA", True)

    def explode(*a, **k):
        raise AssertionError("Lambda must not re-fetch 922 schools")

    monkeypatch.setattr(api, "picture", explode)
    r = TestClient(api.app).get("/api/city")
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["schools"] > 600
    assert body["from_snapshot"]


def test_the_snapshot_carries_every_section_the_public_site_needs():
    """The site renders this file and holds no numbers of its own, so a
    missing key is a broken page, not a missing paragraph."""
    import json

    from saans import api

    if not api.SNAPSHOT.exists():
        pytest.skip("snapshot not built")
    doc = json.loads(api.SNAPSHOT.read_text())
    for key in (
        "generated_for", "school", "who", "outdoor_day", "protocol",
        "today", "hours", "safest", "stability", "replay", "city",
    ):
        assert key in doc, f"snapshot missing {key}"
    assert len(doc["protocol"]["clauses"]) == len(P.clauses())
    assert doc["city"]["summary"]["schools"] == len(doc["city"]["schools"])
    assert doc["stability"]["total"] == len(doc["stability"]["calls"])


def test_lambda_requirements_exclude_the_local_model_stack():
    """strands-agents and ollama cannot run on Lambda and would blow the
    package size. Their absence is deliberate, so it is asserted."""
    from pathlib import Path

    path = (
        Path(__file__).resolve().parent.parent / "deploy" / "requirements-lambda.txt"
    )
    # Only the actual requirement lines; the comments name the excluded
    # packages in order to explain why they are excluded.
    pinned = [
        line.split("#")[0].strip().lower()
        for line in path.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    joined = " ".join(pinned)
    assert "cedarpy" in joined, "Cedar is the protocol engine; it must ship"
    assert "mangum" in joined
    for excluded in ("strands-agents", "ollama", "uvicorn"):
        assert excluded not in joined, f"{excluded} must not ship to Lambda"


def test_schools_are_clipped_to_the_delhi_boundary():
    """A bounding box around Delhi also contains Gurugram, Noida and
    Faridabad. Counting those as Delhi schools would be false, and the
    map made it visible: points sat outside the border."""
    from saans.city import BOUNDARY, load_schools, _inside
    import json

    if not BOUNDARY.exists():
        pytest.skip("boundary not built")
    rings = json.loads(BOUNDARY.read_text())["coordinates"]
    clipped, _ = load_schools(clip=True)
    raw, _ = load_schools(clip=False)
    assert len(clipped) < len(raw), "the clip must actually drop something"
    assert all(_inside(s["lon"], s["lat"], rings) for s in clipped)
    dropped = [s for s in raw if not _inside(s["lon"], s["lat"], rings)]
    assert dropped, "a bbox around Delhi always catches NCR neighbours"


def test_point_in_polygon_agrees_with_a_known_square():
    from saans.city import _inside

    sq = [[[0.0, 0.0], [0.0, 10.0], [10.0, 10.0], [10.0, 0.0]]]
    assert _inside(5, 5, sq)
    assert not _inside(15, 5, sq)
    assert not _inside(5, -5, sq)

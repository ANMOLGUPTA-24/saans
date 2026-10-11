"""The notice that goes home.

This is the only part of Saans a parent ever sees, so it is written for a
parent and not for a judge: Hindi alongside English, the decision first,
the reasoning underneath, and no index numbers anybody has to interpret.

Every figure here is injected from the Decision record. The language model
writes the opening line and nothing else, which is why the facts in this
notice cannot drift from the facts in the ledger.
"""
from __future__ import annotations

from datetime import date

from .decide import HELD, INDOORS, MASK_ALL, MASK_NONE, MASK_REGISTER, MOVED, Decision
from .replay import cpcb_band

BAND_HI = {
    "Good": "अच्छी",
    "Satisfactory": "संतोषजनक",
    "Moderate": "मध्यम",
    "Poor": "ख़राब",
    "Very Poor": "बहुत ख़राब",
    "Severe": "गंभीर",
}
VERDICT_HI = {
    HELD: "बाहर ही होगा",
    MOVED: "समय बदला गया",
    INDOORS: "अंदर होगा",
}
MASKS_HI = {
    MASK_NONE: "ज़रूरत नहीं",
    MASK_REGISTER: "श्वास-रजिस्टर के बच्चों को",
    MASK_ALL: "हर बच्चे को",
}


def plain_summary(d: Decision) -> str:
    """A deterministic one-liner, used when no model is available."""
    changed = [c for c in d.cohorts if c.changes]
    if not changed:
        return (
            "The air is clean enough today. The school day runs outdoors as normal."
        )
    moved = sum(1 for c in d.cohorts for k in c.changes if k.verdict == MOVED)
    inside = sum(1 for c in d.cohorts for k in c.changes if k.verdict == INDOORS)
    bits = []
    if inside:
        bits.append(f"{inside} outdoor periods move inside")
    if moved:
        bits.append(f"{moved} shift to a cleaner hour")
    return (
        f"The air outside is not safe for exertion today, so {' and '.join(bits)}. "
        f"This prevents about {d.dose_saved_per_child:.0f} µg·h of inhaled "
        f"particulate for the average child — "
        f"{100 * d.dose_saved_per_child / 150:.0f}% of a WHO guideline week."
    )


def render(d: Decision, summary: str | None = None, author: str = "template") -> str:
    """The morning notice, bilingual, as HTML."""
    day = date.fromisoformat(d.day)
    peak = max(
        (k.peak_pm25 for c in d.cohorts for k in c.calls), default=0.0
    )
    band = cpcb_band(peak)
    summary = summary or plain_summary(d)

    rows = []
    for c in d.cohorts:
        for k in c.calls:
            when = k.moved_to or k.window
            badge = {
                HELD: "ok",
                MOVED: "moved",
                INDOORS: "inside",
            }.get(k.verdict, "inside")
            cited = ", ".join(x for x in k.cited if x != "P0") or "—"
            rows.append(
                f"""<tr>
<td><b>{c.label}</b><br><span class=sub>{c.strength} children"""
                + (
                    f", {c.on_register} on register" if c.on_register else ""
                )
                + f"""</span></td>
<td>{k.label}<br><span class=sub>{when}</span></td>
<td class="v {badge}">{k.verdict}<br><span class=sub>{VERDICT_HI.get(k.verdict,'')}</span></td>
<td class=num>{k.peak_pm25:.0f}</td>
<td class=num>{k.dose_if_outdoors:.0f} → <b>{k.dose_as_decided:.0f}</b></td>
<td class=sub>{cited}</td>
</tr>"""
            )

    cohort_cards = "".join(
        f"""<div class=card>
  <div class=cl>{c.label}</div>
  <div class=kv><span>Windows / खिड़कियाँ</span><b>{"open" if c.windows_open else "shut / बंद"}</b></div>
  <div class=kv><span>Masks / मास्क</span><b>{c.masks}<br><span class=sub>{MASKS_HI.get(c.masks,'')}</span></b></div>
  <div class=kv><span>Dose today</span><b>{c.dose_under_protocol:.0f} µg·h<br>
     <span class=sub>instead of {c.dose_business_as_usual:.0f}, −{c.saved_pct:.0f}%</span></b></div>
</div>"""
        for c in d.cohorts
    )

    return f"""<!doctype html>
<html lang=en><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Air protocol · {d.day} · {d.school}</title>
<style>
  body{{font:15px/1.55 ui-sans-serif,system-ui,"Noto Sans Devanagari",sans-serif;
       margin:0;background:#f6f7f5;color:#18211c}}
  .wrap{{max-width:860px;margin:0 auto;padding:28px 20px 56px}}
  .mast{{display:flex;justify-content:space-between;align-items:baseline;
        border-bottom:2px solid #18211c;padding-bottom:10px;flex-wrap:wrap;gap:8px}}
  h1{{font-size:20px;margin:0;letter-spacing:-.01em}}
  .date{{font-variant-numeric:tabular-nums;color:#5b6b60;font-size:13px}}
  .band{{display:inline-block;margin:18px 0 0;padding:14px 18px;border-radius:10px;
        background:#fff;border:1px solid #dfe5e0;width:100%;box-sizing:border-box}}
  .pm{{font-size:40px;font-weight:650;letter-spacing:-.03em;font-variant-numeric:tabular-nums}}
  .pm small{{font-size:14px;font-weight:400;color:#5b6b60}}
  .lede{{font-size:16px;margin:16px 0 0;padding:14px 16px;background:#fff;
        border-left:3px solid #2f6b4f;border-radius:0 8px 8px 0}}
  table{{width:100%;border-collapse:collapse;margin-top:22px;background:#fff;
        border:1px solid #dfe5e0;border-radius:10px;overflow:hidden}}
  th{{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.07em;
     color:#5b6b60;padding:10px 12px;background:#eef1ee;font-weight:600}}
  td{{padding:11px 12px;border-top:1px solid #eef1ee;vertical-align:top;font-size:14px}}
  .num{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
  .sub{{color:#6a7a70;font-size:12px}}
  .v{{font-weight:600}} .v.ok{{color:#2f6b4f}} .v.moved{{color:#8a6a1f}} .v.inside{{color:#9c3b2e}}
  .cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));
         gap:12px;margin-top:22px}}
  .card{{background:#fff;border:1px solid #dfe5e0;border-radius:10px;padding:14px}}
  .cl{{font-weight:650;margin-bottom:8px}}
  .kv{{display:flex;justify-content:space-between;gap:10px;font-size:13px;
      padding:6px 0;border-top:1px solid #f2f4f2}}
  .kv span:first-child{{color:#6a7a70}} .kv b{{text-align:right}}
  .foot{{margin-top:26px;font-size:12px;color:#6a7a70;border-top:1px solid #dfe5e0;
        padding-top:14px}}
  code{{background:#eef1ee;padding:1px 5px;border-radius:4px;font-size:11px}}
</style>
<div class=wrap>
  <div class=mast>
    <h1>{d.school} — air protocol</h1>
    <div class=date>{day.strftime('%A, %d %B %Y')} · decided {d.decided_at[11:16]}</div>
  </div>

  <div class=band>
    <div class=pm>{peak:.0f} <small>µg/m³ PM2.5 forecast peak · CPCB {band} / {BAND_HI.get(band,'')}</small></div>
  </div>

  <p class=lede>{summary}</p>

  <table>
    <tr><th>Class</th><th>Period</th><th>Decision</th><th class=num>PM2.5</th>
        <th class=num>Dose µg·h</th><th>Clause</th></tr>
    {''.join(rows)}
  </table>

  <div class=cards>{cohort_cards}</div>

  <div class=foot>
    Decided from {d.data_source}, for {d.latitude:.4f}, {d.longitude:.4f}.
    Protocol <code>{d.protocol_sha256}</code> · evidence <code>{d.evidence_sha256}</code>.
    Dose is inhaled PM2.5 in µg·h/m³, weighted for how hard a child breathes during
    each activity, measured against the WHO guideline week of 150 µg·h.
    Decisions are made by the Cedar protocol, not by a language model;
    the opening line was written by <b>{author}</b>.
  </div>
</div>
</html>"""

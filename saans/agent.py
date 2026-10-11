"""The Strands agent.

Strands Agents SDK is AWS's open-source agent framework, and this is the
Build It path: it runs against a local Ollama model, so the whole project
works with no AWS account, no card and no inference bill.

What the agent is allowed to do is deliberately narrow. It reads evidence,
runs the protocol, looks decisions up in the ledger and writes the one
sentence at the top of the notice that a parent reads first. It cannot
decide whether the games period happens - Cedar does that, and the guard
below checks the agent has not quietly contradicted it.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date

from strands import Agent, tool
from strands.models.ollama import OllamaModel

from . import cloud
from . import policy as P
from .decide import INDOORS, MOVED, Decision, decide
from .notice import plain_summary, render
from .school import LATITUDE, LONGITUDE, SCHOOL_NAME
from .sources import Series, fetch

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
MODEL_ID = os.environ.get("SAANS_MODEL", "llama3.1:8b")

SYSTEM = f"""You write for parents at {SCHOOL_NAME} in Delhi.

You do not make decisions. A Cedar policy engine has already decided what
happens today, and those decisions are fixed. Your only job is to say, in
plain language, what a parent should know and do.

Rules you must follow:
- One or two sentences. No greeting, no sign-off, no bullet points.
- Use only the figures you are given. Never invent or round a number.
- Plain words. A parent with no science background has to understand it
  the first time they read it.
- Never promise that indoors is safe. It is less bad, not safe.
- Do not use the words AQI or index. Talk about the air and the children.
"""


@dataclass
class Draft:
    text: str
    author: str
    rejected: str | None = None


def _model() -> OllamaModel:
    return OllamaModel(host=OLLAMA_HOST, model_id=MODEL_ID, temperature=0.3)


def _numbers(s: str) -> set[int]:
    """Whole numbers a sentence asserts, for the guard below."""
    return {int(x) for x in re.findall(r"\d+", s)}


def guard(text: str, d: Decision) -> str | None:
    """Reject a draft that asserts anything the record does not support.

    The failure this prevents is specific and likely: a small model that
    writes a fluent sentence with a plausible wrong number in it. Any
    figure in the draft has to appear in the decision record, or the
    deterministic summary is used instead.
    """
    if not text or len(text) > 400:
        return "length"
    low = text.lower()
    # The claim that matters is "indoors is safe", which is false in an
    # unfiltered Delhi classroom. Caring about children's safety in general
    # is fine, so match the assertion rather than the word.
    unsafe_claims = (
        "safe indoors",
        "safe inside",
        "indoors is safe",
        "inside is safe",
        "air is safe",
        "completely safe",
        "perfectly safe",
        "will be safe",
        "are safe",
        "is safe from",
    )
    if any(c in low for c in unsafe_claims):
        return "claims indoors is safe"

    # Saans moves and relocates. It never cancels a games period, and
    # saying so would misrepresent the decision to a parent.
    if "cancel" in low:
        return "says cancelled when nothing was cancelled"

    # Overgeneralising is the other thing a small model does to a mixed
    # decision. If any class kept its periods outdoors, a draft claiming
    # every class is inside is wrong, however fluent it reads.
    if any(not c.changes for c in d.cohorts):
        for blanket in ("all outdoor", "every outdoor", "all classes",
                        "every class", "all periods", "all students",
                        "all children", "every child"):
            if blanket in low:
                return f"overgeneralises ({blanket}) when a class stayed outdoors"
    if "aqi" in low or "index" in low:
        return "uses index language"

    allowed: set[int] = {0, 150}
    for c in d.cohorts:
        allowed |= {
            c.strength,
            c.on_register,
            c.grade,
            int(round(c.dose_business_as_usual)),
            int(round(c.dose_under_protocol)),
            int(round(c.dose_saved)),
            int(round(c.saved_pct)),
        }
        for k in c.calls:
            allowed |= {
                int(round(k.peak_pm25)),
                int(round(k.mean_pm25)),
                int(round(k.dose_if_outdoors)),
                int(round(k.dose_as_decided)),
                k.start if hasattr(k, "start") else 0,
            }
    allowed |= {
        int(round(d.dose_saved_per_child)),
        int(round(d.total_dose_saved)),
        d.children_affected,
        d.register_affected,
        d.safest_hour or 0,
        int(round(d.safest_hour_pm25 or 0)),
        len(d.cohorts),
        sum(len(c.changes) for c in d.cohorts),
        date.fromisoformat(d.day).day,
    }
    # Tolerate off-by-one from the model rounding a figure it was given.
    tolerant = set()
    for n in allowed:
        tolerant |= {n - 1, n, n + 1}

    unsupported = _numbers(text) - tolerant
    if unsupported:
        return f"unsupported figures {sorted(unsupported)}"
    return None


def draft_summary(d: Decision) -> Draft:
    """Ask the model for the notice's opening line, and check its work."""
    moved = [k for c in d.cohorts for k in c.changes if k.verdict == MOVED]
    inside = [k for c in d.cohorts for k in c.changes if k.verdict == INDOORS]
    peak = max((k.peak_pm25 for c in d.cohorts for k in c.calls), default=0.0)

    facts = f"""Today: {d.day}.
Forecast peak PM2.5 in school hours: {peak:.0f} micrograms per cubic metre.
Outdoor periods moved indoors: {len(inside)}.
Outdoor periods moved to a cleaner hour: {len(moved)}.
Classes affected: {sum(1 for c in d.cohorts if c.changes)} of {len(d.cohorts)}.
Children affected: {d.children_affected}.
Children on the respiratory register affected: {d.register_affected}.
Inhaled dose prevented for the average child: {d.dose_saved_per_child:.0f} micrograms-hours.
A WHO guideline week is 150 micrograms-hours.
Cleanest hour of the day: {d.safest_hour}:00.
Windows: {'shut' if any(not c.windows_open for c in d.cohorts) else 'open'}.

Write the opening line of today's notice to parents."""

    try:
        agent = Agent(model=_model(), system_prompt=SYSTEM)
        result = agent(facts)
        text = str(result).strip().strip('"')
    except Exception as e:
        return Draft(
            text=plain_summary(d),
            author="deterministic template",
            rejected=f"model unavailable: {type(e).__name__}",
        )

    why = guard(text, d)
    if why:
        return Draft(
            text=plain_summary(d),
            author="deterministic template",
            rejected=why,
        )
    return Draft(text=text, author=f"{MODEL_ID} via Strands Agents SDK")


# ----- tools the agent may call -------------------------------------------


@tool
def todays_air(day: str = "") -> str:
    """Live PM2.5 forecast and mixing-layer height for the school, by hour.

    Args:
        day: ISO date to report, or empty for today.
    """
    s = fetch(LATITUDE, LONGITUDE, forecast_days=2, past_days=2)
    target = date.fromisoformat(day) if day else date.today()
    hours = s.day_hours(target)
    if not hours:
        return f"no data for {target}"
    lines = [
        f"{h.t.strftime('%H:%M')} pm2.5={h.pm2_5:.0f} mixing={h.mixing_height_m or 0:.0f}m"
        for h in hours
        if 6 <= h.hour <= 15
    ]
    return f"{target} at {SCHOOL_NAME}:\n" + "\n".join(lines)


@tool
def run_protocol(day: str = "") -> str:
    """Run the Cedar air protocol for a school day and report the decisions.

    Args:
        day: ISO date to decide, or empty for today.
    """
    s = fetch(LATITUDE, LONGITUDE, forecast_days=2, past_days=14)
    target = date.fromisoformat(day) if day else date.today()
    if target not in s.days:
        return f"no forecast covers {target}"
    d = decide(s, target)
    out = [f"{d.day} - protocol {d.protocol_sha256}"]
    for c in d.cohorts:
        for k in c.calls:
            cites = ",".join(x for x in k.cited if x != "P0") or "P0"
            out.append(
                f"{c.label} / {k.label}: {k.verdict}"
                f"{' to ' + k.moved_to if k.moved_to else ''}"
                f" (pm2.5 {k.peak_pm25:.0f}, dose {k.dose_if_outdoors:.0f}"
                f"->{k.dose_as_decided:.0f}, {cites})"
            )
    out.append(f"dose prevented for the average child: {d.dose_saved_per_child:.0f} ug.h")
    return "\n".join(out)


@tool
def explain_clause(clause_id: str) -> str:
    """The exact text of one numbered clause of the school's protocol.

    Args:
        clause_id: clause identifier such as P3.
    """
    for c in P.clauses():
        if c.id.lower() == clause_id.strip().lower():
            return f"{c.id} ({c.effect}): {c.text}"
    return f"no clause {clause_id}. Clauses: " + ", ".join(c.id for c in P.clauses())


@tool
def lookup_ledger(day: str) -> str:
    """A decision as it was recorded on the day, from the DynamoDB ledger.

    Args:
        day: ISO date of the decision to retrieve.
    """
    rec = cloud.get_decision(SCHOOL_NAME, day)
    if not rec:
        return f"nothing on file for {day}"
    r = rec["record"]
    lines = [
        f"{day} decided {r['decided_at']} under protocol {r['protocol_sha256']}",
        f"dose prevented per child: {r.get('dose_saved_per_child')} ug.h",
    ]
    for c in r["cohorts"]:
        for k in c["calls"]:
            cites = ",".join(x for x in k["cited"] if x != "P0") or "P0"
            lines.append(f"{c['label']} / {k['label']}: {k['verdict']} ({cites})")
    return "\n".join(lines)


TOOLS = [todays_air, run_protocol, explain_clause, lookup_ledger]


def _record_context(day: str | None = None) -> str:
    """Pull the facts a question is likely to need, deterministically.

    A small local model is unreliable at chaining tool calls, and an agent
    that answers "I do not have it on record" when the record is right
    there is worse than useless to a parent. So the record is retrieved
    first and handed over, and the model does what it is good at: putting
    it in a sentence. The tools stay available for anything else.
    """
    s = fetch(LATITUDE, LONGITUDE, forecast_days=2, past_days=14)
    target = date.fromisoformat(day) if day else date.today()
    if target not in s.days:
        target = s.days[-1]
    d = decide(s, target)

    lines = [f"DECISION RECORD for {d.day} at {SCHOOL_NAME}:"]
    fired: set[str] = set()
    for c in d.cohorts:
        for k in c.calls:
            cites = [x for x in k.cited if x != "P0"]
            fired.update(cites)
            lines.append(
                f"- {c.label} ({c.strength} children, {c.on_register} on the "
                f"respiratory register) / {k.label} {k.window}: {k.verdict}"
                f"{' to ' + k.moved_to if k.moved_to else ''}. "
                f"PM2.5 {k.peak_pm25:.0f} ug/m3, mixing layer "
                f"{k.mixing_height_m:.0f} m, breathing rate x{k.exertion}. "
                f"Inhaled dose {k.dose_if_outdoors:.0f} -> "
                f"{k.dose_as_decided:.0f} ug.h. "
                f"Clauses: {', '.join(cites) if cites else 'none (normal day)'}."
            )
        lines.append(
            f"- {c.label}: windows {'open' if c.windows_open else 'shut'}, "
            f"masks {c.masks}."
        )
    lines.append(
        f"Dose prevented for the average child: {d.dose_saved_per_child:.0f} ug.h "
        f"({100 * d.dose_saved_per_child / 150:.0f}% of the WHO guideline week "
        f"of 150 ug.h). Cleanest hour of the day: {d.safest_hour}:00."
    )

    if fired:
        lines.append("")
        lines.append("CLAUSES THAT FIRED, in full:")
        for clause in P.clauses():
            if clause.id in fired:
                lines.append(f'- {clause.id}: "{clause.text}"')
    return "\n".join(lines)


def ask(question: str, day: str | None = None) -> str:
    """Answer a parent's or principal's question from the record only."""
    context = _record_context(day)
    agent = Agent(
        model=_model(),
        tools=TOOLS,
        system_prompt=(
            "You answer questions from parents and staff at "
            f"{SCHOOL_NAME} about the school's air protocol.\n\n"
            "The decision record below is the truth. Answer from it.\n"
            "- Quote the clause text when a decision is questioned.\n"
            "- Never invent a number. Every figure must appear in the record.\n"
            "- Never say indoors is safe; it is less bad, not safe.\n"
            "- Be brief and plain. Two or three sentences.\n"
            "- If the record genuinely does not cover it, say so, and use "
            "your tools to look further.\n\n"
            + context
        ),
    )
    return str(agent(question)).strip()

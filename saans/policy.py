"""The Cedar gate.

Every protocol action passes through here. The rule the project is built on:

    No language model decides anything that affects a child's lungs.

The model drafts the notice that goes home. Cedar decides whether the games
period happens. The two never swap jobs, and the decision record proves it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import cedarpy

PROTOCOL_PATH = Path(__file__).resolve().parent.parent / "protocol" / "school_protocol.cedar"

HOLD_OUTDOORS = "hold_outdoors"
HOLD_VIGOROUS = "hold_vigorous_outdoors"
KEEP_WINDOWS_OPEN = "keep_windows_open"
OMIT_MASKS = "omit_masks"

AGENT = {"type": "Saans::Agent", "id": "morning-protocol"}


@dataclass(frozen=True)
class Clause:
    """One numbered clause of the school's protocol, as written in Cedar."""

    index: int
    id: str
    text: str
    effect: str


@dataclass(frozen=True)
class Ruling:
    """Cedar's answer, with the clauses that produced it."""

    action: str
    cohort: str
    allowed: bool
    clauses: list[Clause]
    context: dict[str, int]
    errors: list[str] = field(default_factory=list)

    @property
    def citation(self) -> str:
        """The one line that goes on the notice board."""
        binding = [c for c in self.clauses if c.effect == "forbid"]
        if not binding:
            return "P0 - normal school day"
        return "; ".join(f"{c.id} - {c.text}" for c in binding)

    @property
    def clause_ids(self) -> list[str]:
        return [c.id for c in self.clauses]


@lru_cache(maxsize=1)
def _protocol_text() -> str:
    return PROTOCOL_PATH.read_text()


@lru_cache(maxsize=1)
def clauses() -> list[Clause]:
    """Parse the protocol's clauses in file order.

    Cedar reports the policies that determined a decision positionally
    (policy0, policy1, ...), so file order is the index. Parsing the
    annotations here lets a denial cite the clause a principal actually
    signed off on, in their words.
    """
    text = _protocol_text()
    out: list[Clause] = []
    pattern = re.compile(
        r'@id\("(?P<id>[^"]+)"\)\s*\n\s*@clause\("(?P<text>(?:[^"\\]|\\.)*)"\)\s*\n\s*'
        r"(?P<effect>permit|forbid)",
        re.MULTILINE,
    )
    for i, m in enumerate(pattern.finditer(text)):
        out.append(
            Clause(
                index=i,
                id=m.group("id"),
                text=m.group("text").replace('\\"', '"'),
                effect=m.group("effect"),
            )
        )
    if not out:
        raise RuntimeError(f"no annotated clauses found in {PROTOCOL_PATH}")
    return out


@lru_cache(maxsize=1)
def _policy_set():
    return cedarpy.PolicySet.from_str(_protocol_text())


def _clause_for(reason: str) -> Clause | None:
    m = re.fullmatch(r"policy(\d+)", reason)
    if not m:
        return None
    idx = int(m.group(1))
    found = clauses()
    return found[idx] if idx < len(found) else None


def _entity(cohort_key: str, grade: int, strength: int, on_register: int) -> list[dict]:
    return [
        {
            "uid": {"type": "Saans::Cohort", "id": cohort_key},
            "attrs": {
                "grade": grade,
                "strength": strength,
                "on_register": on_register,
                "has_register": on_register > 0,
            },
            "parents": [],
        }
    ]


def ask(
    action: str,
    cohort_key: str,
    grade: int,
    strength: int,
    on_register: int,
    *,
    peak_pm25: float,
    mean_pm25: float,
    mixing_height_m: float,
    avoidable_dose: float = 0.0,
    dose_today: float = 0.0,
) -> Ruling:
    """Put one protocol action to Cedar.

    Cedar has no floating-point type, so the evidence is rounded to whole
    µg/m³, metres and percent on the way in. Thresholds are written in those
    same whole units, so nothing is lost that a threshold could turn on.
    """
    context = {
        "peak_pm25": int(round(peak_pm25)),
        "mean_pm25": int(round(mean_pm25)),
        "mixing_height_m": int(round(mixing_height_m)),
        "avoidable_dose": int(round(avoidable_dose)),
        "dose_today": int(round(dose_today)),
    }
    result = cedarpy.is_authorized(
        {
            "principal": AGENT,
            "action": {"type": "Saans::Action", "id": action},
            "resource": {"type": "Saans::Cohort", "id": cohort_key},
            "context": context,
        },
        _policy_set(),
        _entity(cohort_key, grade, strength, on_register),
    )
    errors = list(result.diagnostics.errors or [])
    if errors:
        # A protocol that cannot be evaluated is not a protocol. Fail closed.
        return Ruling(action, cohort_key, False, [], context, errors)

    cited = [c for c in (_clause_for(r) for r in result.diagnostics.reasons) if c]
    return Ruling(
        action=action,
        cohort=cohort_key,
        allowed=result.decision == cedarpy.Decision.Allow,
        clauses=cited,
        context=context,
    )

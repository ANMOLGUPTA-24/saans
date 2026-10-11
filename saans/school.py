"""The school Saans decides for.

Air data in this project is real and live. The roster is synthetic and
labelled as such: inventing health records for a named real school would be
dishonest, and the protocol logic does not depend on the names being real.
Point LATITUDE/LONGITUDE at any school in India and everything else follows.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Shalimar Bagh, North West Delhi. Real coordinates, ~4 km from DTU.
LATITUDE = 28.7045
LONGITUDE = 77.1550
SCHOOL_NAME = "Shalimar Bagh Model School"
SCHOOL_NOTE = "demo roster, real location, real air data"
SHIFT = "morning shift, 07:20 - 13:30"


@dataclass(frozen=True)
class Activity:
    """A block of the school day that happens outdoors."""

    key: str
    label: str
    start_h: int
    end_h: int
    hours: float
    # Minute-ventilation multiplier vs a seated adult-equivalent baseline.
    # A child at vigorous play moves roughly 3x the air through their lungs,
    # so the same µg/m³ delivers roughly 3x the dose.
    exertion: float
    indoor_alternative: str

    @property
    def window(self) -> str:
        return f"{self.start_h:02d}:00-{self.end_h:02d}:00"


OUTDOOR_DAY = [
    Activity("assembly", "Morning assembly", 7, 8, 0.5, 1.0, "corridor assembly, seated"),
    Activity("recess", "Recess", 10, 11, 0.5, 2.0, "classroom recess, windows shut"),
    Activity("games", "Games period", 13, 14, 1.0, 3.0, "indoor games in the hall"),
]
ACTIVITIES = {a.key: a for a in OUTDOOR_DAY}


@dataclass(frozen=True)
class Cohort:
    """One class. Sizes are typical of a Delhi government school."""

    key: str
    label: str
    grade: int
    strength: int
    # Children with a diagnosed respiratory condition on file. Held as a
    # count plus opaque ids: Saans never needs a name to protect a child.
    register: tuple[str, ...] = field(default_factory=tuple)

    @property
    def on_register(self) -> int:
        return len(self.register)

    @property
    def has_register(self) -> bool:
        return bool(self.register)


COHORTS = [
    Cohort("grade_3", "Class 3-A", 3, 48, ("R-3104", "R-3119")),
    Cohort("grade_6", "Class 6-B", 6, 52, ("R-6207", "R-6231", "R-6244")),
    Cohort("grade_9", "Class 9-A", 9, 44, ("R-9102",)),
    # No child on the respiratory register. This class is the control: on a
    # borderline day the protocol lets it outside while the others stay in,
    # which is the policy engine doing its job rather than a blanket ban.
    Cohort("grade_11", "Class 11-C", 11, 39, ()),
]
COHORT_BY_KEY = {c.key: c for c in COHORTS}

TOTAL_CHILDREN = sum(c.strength for c in COHORTS)
TOTAL_ON_REGISTER = sum(c.on_register for c in COHORTS)

# The school's physical reality, and the reason the indoor fallback is not
# a free win: shutting windows in an unfiltered room cuts outdoor particulate
# by roughly half, and no more than that.
HAS_AIR_PURIFIERS = False
INDOOR_INFILTRATION = 0.5  # shut windows, no filtration
PURIFIER_INFILTRATION = 0.15
PRINCIPAL_DECIDES_BY_H = 6  # the call has to be made before 07:00

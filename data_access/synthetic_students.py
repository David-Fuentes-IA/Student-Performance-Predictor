"""
data_access/synthetic_students.py

One simulator behind every synthetic dataset in the project: the model's training set, the
demo data seeded into MongoDB, the in-memory demo groups and the fixed evaluation workbook.

Why it is not "at-risk students get low numbers, the rest get high numbers":
    that version separated the two classes perfectly, so any model scored 1.0 and there was
    no error to analyse. Here the observable data (grades, attendance, participation) are
    noisy consequences of hidden traits, and the outcome depends on those hidden traits plus
    events nobody can observe, so the classes overlap the way real ones do:

        aptitude  (hidden) ──► grades, participation, outcome
        engagement(hidden) ──► attendance, participation, outcome
        drift     (hidden) ──► grade trend, outcome
        shocks    (hidden) ──► outcome only: ~5 % of students hit a crisis (illness, work,
                               dropout) and ~4 % recover with tutoring, whatever their grades

    Consequently some at-risk students look fine (false negatives) and some fine students
    look at risk (false positives). That irreducible error is the point.

``shift`` is a synthetic subgroup used only to audit fairness (DR-3). Evening students attend
less on average for the same underlying engagement (a plausible work-schedule effect), so a
model that leans on attendance can flag them more often. It is a documented test scenario,
not a claim about real students.

Everything is deterministic: the same (n, seed) always gives the same students.
"""

import math
import random
from dataclasses import dataclass

# --- calibration (see docs/evidence/model/ for the resulting metrics) -------------------------
EVENING_SHARE = 0.40
EVENING_ATTENDANCE_PENALTY = 7.0
CRISIS_PROBABILITY = 0.05
RECOVERY_PROBABILITY = 0.04
OUTCOME_INTERCEPT = -1.4      # sets the share of at-risk students (about 27 %)
APTITUDE_WEIGHT = 1.6
ENGAGEMENT_WEIGHT = 0.5
DRIFT_WEIGHT = 0.10
OUTCOME_NOISE = 0.5           # spread of everything the model cannot see
LINK_SHARPNESS = 4.0          # how deterministic the outcome is given the hidden traits

_FIRST_NAMES = [
    "Ana", "Luis", "Maria", "Jose", "Sofia", "Carlos", "Valeria", "Diego", "Camila", "Miguel",
    "Fernanda", "Javier", "Daniela", "Andres", "Paola", "Ricardo", "Regina", "Emilio", "Ximena",
    "Hugo", "Renata", "Mateo", "Natalia", "Sergio", "Lucia", "Oscar", "Abril", "Ivan", "Julia", "Raul",
]
_LAST_NAMES = [
    "Garcia", "Hernandez", "Lopez", "Martinez", "Gonzalez", "Perez", "Rodriguez", "Sanchez",
    "Ramirez", "Cruz", "Flores", "Gomez", "Morales", "Vazquez", "Reyes", "Jimenez", "Torres",
    "Diaz", "Ortiz", "Mendoza", "Castillo", "Romero", "Alvarez", "Ruiz", "Herrera", "Medina",
]


def fake_name(index: int) -> str:
    """Deterministic fictitious name for the n-th synthetic student."""
    first = _FIRST_NAMES[index % len(_FIRST_NAMES)]
    last_1 = _LAST_NAMES[(index * 7 + 3) % len(_LAST_NAMES)]
    last_2 = _LAST_NAMES[(index * 11 + 5) % len(_LAST_NAMES)]
    return f"{first} {last_1} {last_2}"


@dataclass(frozen=True)
class SimulatedStudent:
    student_id: str
    name: str
    grades: list[float]
    attendance_pct: float
    participation_score: float
    shift: str          # "matutino" | "vespertino" (synthetic fairness subgroup)
    at_risk: int        # ground-truth outcome: 1 = ended the term with low performance


def _clip(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def simulate_students(n: int, seed: int = 7, *, id_prefix: str = "S", first_index: int = 1) -> list[SimulatedStudent]:
    """Return `n` simulated students (deterministic for a given seed)."""
    rng = random.Random(seed)
    students = []
    for offset in range(n):
        index = first_index + offset
        evening = rng.random() < EVENING_SHARE

        aptitude = rng.gauss(0, 1)
        engagement = 0.6 * aptitude + 0.8 * rng.gauss(0, 1)
        drift = rng.gauss(0, 5)                      # grade change per partial exam

        n_grades = rng.choices([4, 3, 2], weights=[0.80, 0.13, 0.07])[0]
        base = 70 + 13 * aptitude
        grades = [round(_clip(base + drift * k + rng.gauss(0, 6)), 1) for k in range(n_grades)]
        attendance = round(_clip(84 + 7 * engagement + rng.gauss(0, 9)
                                 - (EVENING_ATTENDANCE_PENALTY if evening else 0.0)), 1)
        participation = round(_clip(68 + 11 * engagement + rng.gauss(0, 14)), 1)

        propensity = (OUTCOME_INTERCEPT - APTITUDE_WEIGHT * aptitude - ENGAGEMENT_WEIGHT * engagement
                      - DRIFT_WEIGHT * drift + rng.gauss(0, OUTCOME_NOISE))
        if rng.random() < CRISIS_PROBABILITY:
            propensity += 2.5
        if rng.random() < RECOVERY_PROBABILITY:
            propensity -= 2.5
        at_risk = int(rng.random() < _sigmoid(LINK_SHARPNESS * propensity))

        students.append(SimulatedStudent(
            student_id=f"{id_prefix}{index:04d}", name=fake_name(index - 1), grades=grades,
            attendance_pct=attendance, participation_score=participation,
            shift="vespertino" if evening else "matutino", at_risk=at_risk,
        ))
    return students

"""
data_pipeline/synthetic_seed.py

Generates clearly-fake students so the system can be demonstrated without
real institutional data. Every record is tagged `source="synthetic"`, so it
can be removed later (`repository.purge_synthetic()`) without touching the
real groups a teacher created or imported.

Deterministic: the same seed always produces the same students, so running
the generator twice never duplicates data (records are upserted by
(group, matricula)).
"""

import random

from data_access.mongo_repository import MongoAcademicRepository
from data_access.student_repository import StudentRecord

DEFAULT_GROUPS = ("301-A", "301-B", "301-C")

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


def generate_records(count: int = 100, *, groups=DEFAULT_GROUPS, seed: int = 42,
                     grade_count: int = 4) -> dict[str, list[StudentRecord]]:
    """~25% of students are generated 'at risk' so the demo shows real alerts."""
    rng = random.Random(seed)
    by_group: dict[str, list[StudentRecord]] = {g: [] for g in groups}

    for i in range(count):
        group_id = groups[i % len(groups)]
        at_risk = rng.random() < 0.25
        if at_risk:
            grades = [rng.uniform(30, 62) for _ in range(grade_count)]
            attendance, participation = rng.uniform(40, 70), rng.uniform(15, 55)
        else:
            grades = [rng.uniform(65, 98) for _ in range(grade_count)]
            attendance, participation = rng.uniform(75, 100), rng.uniform(55, 100)

        by_group[group_id].append(
            StudentRecord(
                student_id=f"S{i + 1:04d}",
                name=fake_name(i),
                grades=[round(g, 1) for g in grades],
                attendance_pct=round(attendance, 1),
                participation_score=round(participation, 1),
            )
        )
    return by_group


def seed_database(repository: MongoAcademicRepository, count: int = 100, *,
                  reset: bool = False, groups=DEFAULT_GROUPS, seed: int = 42) -> dict:
    """Create the demo groups and students. `reset` first removes old synthetic data."""
    purged = repository.purge_synthetic() if reset else None
    created_groups = []
    summary = {"created": 0, "updated": 0, "unchanged": 0}

    for group_id, records in generate_records(count, groups=groups, seed=seed).items():
        if not repository.group_exists(group_id):
            repository.create_group(
                group_id, name="Grupo de prueba", period="Demo", source="synthetic"
            )
            created_groups.append(group_id)
        outcome = repository.upsert_records(group_id, records, source="synthetic")
        for key in summary:
            summary[key] += outcome[key]

    return {"students": count, "groups_created": created_groups, **summary, "purged": purged}

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

from data_access.mongo_repository import MongoAcademicRepository
from data_access.student_repository import DEMO_GROUP_IDS, StudentRecord
from data_access.synthetic_students import simulate_students

DEFAULT_GROUPS = DEMO_GROUP_IDS


def generate_records(count: int = 100, *, groups=DEFAULT_GROUPS, seed: int = 42) -> dict[str, list[StudentRecord]]:
    """Deal `count` simulated students round-robin into `groups`.

    The students come from the noisy simulator (data_access/synthetic_students.py), so the demo
    data show a realistic spread of risk scores instead of only clear-cut cases.
    """
    by_group: dict[str, list[StudentRecord]] = {g: [] for g in groups}
    for i, student in enumerate(simulate_students(count, seed=seed)):
        by_group[groups[i % len(groups)]].append(StudentRecord(
            student_id=student.student_id, name=student.name, grades=student.grades,
            attendance_pct=student.attendance_pct, participation_score=student.participation_score,
        ))
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

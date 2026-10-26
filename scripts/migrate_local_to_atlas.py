"""
scripts/migrate_local_to_atlas.py

One-off migration: copies the synthetic students that were stored in the
LOCAL MongoDB (database `student_predictor`, collection `academic_records`,
old flat schema) into the configured target database (MONGODB_URI -> Atlas)
using the new schema (groups / students / academic_records / history).

    python scripts/migrate_local_to_atlas.py --dry-run     # show what would happen
    python scripts/migrate_local_to_atlas.py               # do it

Safe to run more than once: records are upserted by (group, matricula).
The old data had no names, so deterministic fictitious names are assigned.
Everything migrated is tagged source="synthetic".
"""

import argparse
import re
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pymongo import MongoClient  # noqa: E402

from core import config  # noqa: E402
from core.exception_handler import ValidationError  # noqa: E402
from data_access.mongo_connection import redact_uri  # noqa: E402
from data_access.mongo_repository import MongoAcademicRepository  # noqa: E402
from data_access.student_repository import StudentRecord  # noqa: E402
from data_access.synthetic_students import fake_name  # noqa: E402
from data_pipeline.fail_fast_validator import FailFastValidator  # noqa: E402


def _index_from_id(student_id: str) -> int:
    digits = re.sub(r"\D", "", student_id)
    return (int(digits) - 1) if digits else zlib.crc32(student_id.encode()) % 1000


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate local synthetic students to the target DB.")
    parser.add_argument("--source-uri", default="mongodb://localhost:27017")
    parser.add_argument("--source-db", default="student_predictor")
    parser.add_argument("--source-collection", default="academic_records")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source = MongoClient(args.source_uri, serverSelectionTimeoutMS=5000)
    documents = list(source[args.source_db][args.source_collection].find({}, {"_id": 0}))
    print(f"Source: {redact_uri(args.source_uri)} / {args.source_db}.{args.source_collection}"
          f" -> {len(documents)} documents")
    if not documents:
        print("Nothing to migrate.")
        return

    by_group: dict[str, list[StudentRecord]] = {}
    skipped = 0
    for doc in documents:
        try:
            record = StudentRecord(
                student_id=str(doc["student_id"]),
                name=fake_name(_index_from_id(str(doc["student_id"]))),
                grades=[float(g) for g in doc["grades"]],
                attendance_pct=float(doc["attendance_pct"]),
                participation_score=float(doc["participation_score"]),
            )
            FailFastValidator.validate(record)
            by_group.setdefault(str(doc["group_id"]), []).append(record)
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            skipped += 1
            print(f"  skipped a document: {type(exc).__name__}")

    for group_id, records in sorted(by_group.items()):
        print(f"  group {group_id}: {len(records)} students")
    print(f"Target database: {config.mongodb_db_name()} @ {redact_uri(config.mongodb_uri() or '(not set)')}")

    if args.dry_run:
        print("Dry run - nothing written.")
        return

    target = MongoAcademicRepository()
    totals = {"created": 0, "updated": 0, "unchanged": 0}
    for group_id, records in by_group.items():
        if not target.group_exists(group_id):
            target.create_group(group_id, name="Grupo de prueba", period="Demo", source="synthetic")
        outcome = target.upsert_records(group_id, records, source="synthetic")
        for key in totals:
            totals[key] += outcome[key]

    print(f"Migrated: {totals} (skipped {skipped}).")
    print(target.stats())


if __name__ == "__main__":
    main()

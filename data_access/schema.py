"""
data_access/schema.py

Database schema for the Student Performance Predictor (MongoDB).

Collections
-----------
groups            One document per class group (e.g. "301-A").
students          Identity data (matricula + name). Kept SEPARATE from the
                  academic data so the AI layer never needs it (DR-1).
academic_records  One document per (group, student): grades per partial,
                  attendance and participation. This is what the ML
                  pipeline reads through IAcademicDataRepository.
record_history    Append-only snapshots of academic_records - the "mini
                  history" of a student (one snapshot per change/import).
predictions       Risk predictions persisted by the orchestrator (Step 8
                  of the AI Workflow, section 8).
import_logs       Audit trail of Excel imports (metadata only - no names,
                  no grades - per section 11 Privacy).

Design note:
    `ensure_schema` is idempotent: it can run on every cold start. It
    creates the collections with a $jsonSchema validator (the database
    itself rejects malformed documents - a last Fail-Fast line of defence
    behind FailFastValidator) and the indexes the queries rely on,
    including the unique indexes that make imports idempotent.
"""

from pymongo.database import Database
from pymongo.errors import OperationFailure

from core.logger import get_logger

logger = get_logger(__name__)

GROUPS = "groups"
STUDENTS = "students"
ACADEMIC_RECORDS = "academic_records"
RECORD_HISTORY = "record_history"
PREDICTIONS = "predictions"
IMPORT_LOGS = "import_logs"

ALL_COLLECTIONS = (GROUPS, STUDENTS, ACADEMIC_RECORDS, RECORD_HISTORY, PREDICTIONS, IMPORT_LOGS)

_NUMBER = ["int", "long", "double", "decimal"]

_VALIDATORS: dict[str, dict] = {
    GROUPS: {
        "bsonType": "object",
        "required": ["group_id", "created_at"],
        "properties": {
            "group_id": {"bsonType": "string", "minLength": 1, "maxLength": 32},
            "name": {"bsonType": "string"},
            "period": {"bsonType": "string"},
            "teacher": {"bsonType": "string"},
            "source": {"enum": ["manual", "excel", "synthetic"]},
            "created_at": {"bsonType": "date"},
        },
    },
    STUDENTS: {
        "bsonType": "object",
        "required": ["student_id", "name"],
        "properties": {
            "student_id": {"bsonType": "string", "minLength": 1, "maxLength": 32},
            "name": {"bsonType": "string", "minLength": 1, "maxLength": 120},
        },
    },
    ACADEMIC_RECORDS: {
        "bsonType": "object",
        "required": ["group_id", "student_id", "grades", "attendance_pct", "participation_score"],
        "properties": {
            "group_id": {"bsonType": "string"},
            "student_id": {"bsonType": "string"},
            "grades": {
                "bsonType": "array",
                "minItems": 1,
                "maxItems": 10,
                "items": {"bsonType": _NUMBER, "minimum": 0, "maximum": 100},
            },
            "attendance_pct": {"bsonType": _NUMBER, "minimum": 0, "maximum": 100},
            "participation_score": {"bsonType": _NUMBER, "minimum": 0, "maximum": 100},
            "source": {"enum": ["manual", "excel", "synthetic"]},
        },
    },
}


def ensure_schema(db: Database) -> None:
    """Create collections, validators and indexes (safe to call repeatedly)."""
    existing = set(db.list_collection_names())

    for name, schema in _VALIDATORS.items():
        validator = {"$jsonSchema": schema}
        try:
            if name in existing:
                db.command(
                    "collMod", name,
                    validator=validator, validationLevel="moderate", validationAction="error",
                )
            else:
                db.create_collection(
                    name,
                    validator=validator, validationLevel="moderate", validationAction="error",
                )
        except OperationFailure as exc:
            # Some tiers restrict collMod; the indexes below still protect integrity.
            logger.warning("Could not apply validator on '%s': %s", name, exc.code)

    db[GROUPS].create_index("group_id", unique=True)
    db[STUDENTS].create_index("student_id", unique=True)
    db[ACADEMIC_RECORDS].create_index([("group_id", 1), ("student_id", 1)], unique=True)
    db[ACADEMIC_RECORDS].create_index("student_id")
    db[ACADEMIC_RECORDS].create_index("source")
    db[RECORD_HISTORY].create_index([("group_id", 1), ("student_id", 1), ("created_at", -1)])
    db[PREDICTIONS].create_index([("student_ref", 1), ("recorded_at", -1)])
    db[IMPORT_LOGS].create_index([("created_at", -1)])
    logger.info("Database schema verified (%d collections).", len(ALL_COLLECTIONS))

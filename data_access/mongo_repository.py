"""
data_access/mongo_repository.py

MongoDB implementation of IAcademicDataRepository (traceability: DIP, section 4;
FR-3; section 6.1).

Design note:
    The ML pipeline (ETLProcessor, main_api) only knows the
    `IAcademicDataRepository` abstraction. This class is the "one new class"
    that replaces `InMemoryAcademicRepository` - no business-logic file had
    to change to talk to MongoDB.

    Per the project rules this module ONLY reads/writes the database: no
    cleaning and no Pandas here. Validation of incoming data happens before
    it reaches this layer (FailFastValidator, see
    data_pipeline/group_import_service.py).

    Besides the interface methods, the class exposes the administration
    operations needed by the admin web interface (groups, student rows,
    bulk upsert used by the Excel import, history, stats).
"""

from datetime import datetime, timezone

from pymongo import InsertOne, UpdateOne
from pymongo.errors import BulkWriteError, DuplicateKeyError, PyMongoError

from core.exception_handler import DataAccessError, GroupNotFoundError, ValidationError
from core.logger import get_logger
from data_access import schema
from data_access.mongo_connection import get_database
from data_access.student_repository import (
    IAcademicDataRepository,
    StudentGroup,
    StudentRecord,
)

logger = get_logger(__name__)

VALID_SOURCES = ("manual", "excel", "synthetic")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _db_error(action: str, exc: Exception) -> DataAccessError:
    logger.error("MongoDB error while %s: %s", action, type(exc).__name__)
    return DataAccessError(
        f"MongoDB error while {action}: {type(exc).__name__}",
        user_message="La base de datos no respondio correctamente. Intenta de nuevo.",
    )


class MongoAcademicRepository(IAcademicDataRepository):
    backend = "mongodb"

    def __init__(self, db=None, *, ensure_schema: bool = True) -> None:
        self._db = db if db is not None else get_database()
        if ensure_schema:
            try:
                schema.ensure_schema(self._db)
            except PyMongoError as exc:
                raise _db_error("preparing the schema", exc) from exc

    @property
    def db(self):
        return self._db

    # ------------------------------------------------------------------
    # IAcademicDataRepository (used by the ML pipeline)
    # ------------------------------------------------------------------

    def get_group(self, group_id: str) -> StudentGroup:
        if not group_id or not isinstance(group_id, str):
            raise DataAccessError(
                "get_group called with an empty/invalid group_id",
                user_message="Ingresa un ID de grupo valido.",
            )
        try:
            if self._db[schema.GROUPS].count_documents({"group_id": group_id}, limit=1) == 0:
                raise GroupNotFoundError(
                    f"group '{group_id}' not found",
                    user_message=f"El grupo '{group_id}' no existe en la base de datos.",
                )
            records = list(
                self._db[schema.ACADEMIC_RECORDS]
                .find({"group_id": group_id}, {"_id": 0})
                .sort("student_id", 1)
            )
            names = self._names_for([r["student_id"] for r in records])
        except PyMongoError as exc:
            raise _db_error("reading a group", exc) from exc

        return StudentGroup(
            group_id=group_id,
            students=[self._to_student_record(r, names) for r in records],
        )

    def get_student(self, student_id: str) -> StudentRecord:
        try:
            record = self._db[schema.ACADEMIC_RECORDS].find_one(
                {"student_id": student_id}, {"_id": 0}, sort=[("updated_at", -1)]
            )
            if record is None:
                raise DataAccessError(
                    f"student_id '{student_id}' not found",
                    user_message="No se encontro al alumno solicitado.",
                )
            names = self._names_for([student_id])
        except PyMongoError as exc:
            raise _db_error("reading a student", exc) from exc
        return self._to_student_record(record, names)

    def save_prediction(self, student_ref: str, risk_score: float, risk_label: str) -> None:
        """Best effort: a failure here must not break the report (NFR-5)."""
        try:
            self._db[schema.PREDICTIONS].insert_one(
                {
                    "student_ref": student_ref,
                    "risk_score": float(risk_score),
                    "risk_label": risk_label,
                    "recorded_at": _now(),
                }
            )
        except PyMongoError as exc:
            logger.warning("Prediction could not be persisted: %s", type(exc).__name__)

    def save_predictions(self, predictions: list[tuple[str, float, str]]) -> None:
        """All of a request's predictions in ONE round trip (insert_many) instead of one per student.
        Measured as the main bottleneck of a dashboard request (docs/evidence/performance). Best effort (NFR-5)."""
        if not predictions:
            return
        recorded_at = _now()
        try:
            self._db[schema.PREDICTIONS].insert_many(
                [{"student_ref": ref, "risk_score": float(score), "risk_label": label, "recorded_at": recorded_at}
                 for ref, score, label in predictions],
                ordered=False,
            )
        except PyMongoError as exc:
            logger.warning("Predictions could not be persisted: %s", type(exc).__name__)

    # ------------------------------------------------------------------
    # Groups
    # ------------------------------------------------------------------

    def list_groups(self) -> list[dict]:
        try:
            counts = {
                d["_id"]: d["n"]
                for d in self._db[schema.ACADEMIC_RECORDS].aggregate(
                    [{"$group": {"_id": "$group_id", "n": {"$sum": 1}}}]
                )
            }
            groups = list(self._db[schema.GROUPS].find({}, {"_id": 0}).sort("group_id", 1))
        except PyMongoError as exc:
            raise _db_error("listing groups", exc) from exc
        for group in groups:
            group["student_count"] = counts.get(group["group_id"], 0)
        return groups

    def group_exists(self, group_id: str) -> bool:
        try:
            return self._db[schema.GROUPS].count_documents({"group_id": group_id}, limit=1) > 0
        except PyMongoError as exc:
            raise _db_error("checking a group", exc) from exc

    def create_group(
        self, group_id: str, *, name: str = "", period: str = "", teacher: str = "",
        source: str = "manual",
    ) -> dict:
        document = {
            "group_id": group_id,
            "name": name,
            "period": period,
            "teacher": teacher,
            "source": source if source in VALID_SOURCES else "manual",
            "created_at": _now(),
        }
        try:
            self._db[schema.GROUPS].insert_one(dict(document))
        except DuplicateKeyError as exc:
            raise ValidationError(
                f"group '{group_id}' already exists",
                user_message=f"El grupo '{group_id}' ya existe.",
            ) from exc
        except PyMongoError as exc:
            raise _db_error("creating a group", exc) from exc
        return document

    def delete_group(self, group_id: str) -> dict:
        """Delete a group with its records/history; drop students left orphaned."""
        try:
            student_ids = self._db[schema.ACADEMIC_RECORDS].distinct(
                "student_id", {"group_id": group_id}
            )
            deleted_records = self._db[schema.ACADEMIC_RECORDS].delete_many({"group_id": group_id})
            self._db[schema.RECORD_HISTORY].delete_many({"group_id": group_id})
            deleted_group = self._db[schema.GROUPS].delete_one({"group_id": group_id})
            orphans = self._remove_orphan_students(student_ids)
        except PyMongoError as exc:
            raise _db_error("deleting a group", exc) from exc
        return {
            "group_deleted": deleted_group.deleted_count,
            "records_deleted": deleted_records.deleted_count,
            "students_deleted": orphans,
        }

    # ------------------------------------------------------------------
    # Students / academic records
    # ------------------------------------------------------------------

    def list_group_records(self, group_id: str) -> list[dict]:
        try:
            records = list(
                self._db[schema.ACADEMIC_RECORDS]
                .find({"group_id": group_id}, {"_id": 0})
                .sort("student_id", 1)
            )
            names = self._names_for([r["student_id"] for r in records])
        except PyMongoError as exc:
            raise _db_error("listing students", exc) from exc
        for record in records:
            record["name"] = names.get(record["student_id"], record["student_id"])
        return records

    def upsert_records(
        self,
        group_id: str,
        records: list[StudentRecord],
        *,
        source: str = "manual",
    ) -> dict:
        """
        Insert or update many (group, student) records in 3 round trips
        (students, records, history) - fast enough for serverless limits.
        A history snapshot is appended only when something actually changed.
        """
        if not records:
            return {"created": 0, "updated": 0, "unchanged": 0}
        source = source if source in VALID_SOURCES else "manual"
        now = _now()

        try:
            existing = {
                r["student_id"]: r
                for r in self._db[schema.ACADEMIC_RECORDS].find(
                    {"group_id": group_id, "student_id": {"$in": [r.student_id for r in records]}},
                    {"_id": 0},
                )
            }

            student_ops, record_ops, history_ops = [], [], []
            created = updated = unchanged = 0

            for rec in records:
                grades = [float(g) for g in rec.grades]
                payload = {
                    "grades": grades,
                    "attendance_pct": float(rec.attendance_pct),
                    "participation_score": float(rec.participation_score),
                }
                previous = existing.get(rec.student_id)

                student_ops.append(
                    UpdateOne(
                        {"student_id": rec.student_id},
                        {
                            "$set": {"name": rec.name, "updated_at": now},
                            "$setOnInsert": {"created_at": now},
                        },
                        upsert=True,
                    )
                )

                if previous is not None and all(previous.get(k) == v for k, v in payload.items()):
                    unchanged += 1
                    continue

                created += previous is None
                updated += previous is not None
                record_ops.append(
                    UpdateOne(
                        {"group_id": group_id, "student_id": rec.student_id},
                        {
                            "$set": {**payload, "source": source, "updated_at": now},
                            "$setOnInsert": {"created_at": now},
                        },
                        upsert=True,
                    )
                )
                history_ops.append(
                    InsertOne(
                        {
                            "group_id": group_id,
                            "student_id": rec.student_id,
                            **payload,
                            "source": source,
                            "created_at": now,
                        }
                    )
                )

            self._db[schema.STUDENTS].bulk_write(student_ops, ordered=False)
            if record_ops:
                self._db[schema.ACADEMIC_RECORDS].bulk_write(record_ops, ordered=False)
                self._db[schema.RECORD_HISTORY].bulk_write(history_ops, ordered=False)
        except BulkWriteError as exc:
            raise _db_error("saving records", exc) from exc
        except PyMongoError as exc:
            raise _db_error("saving records", exc) from exc

        return {"created": created, "updated": updated, "unchanged": unchanged}

    def delete_student_record(self, group_id: str, student_id: str) -> bool:
        try:
            result = self._db[schema.ACADEMIC_RECORDS].delete_one(
                {"group_id": group_id, "student_id": student_id}
            )
            self._db[schema.RECORD_HISTORY].delete_many(
                {"group_id": group_id, "student_id": student_id}
            )
            self._remove_orphan_students([student_id])
        except PyMongoError as exc:
            raise _db_error("deleting a student", exc) from exc
        return result.deleted_count > 0

    def clear_group_students(self, group_id: str) -> int:
        """Remove every student row of a group but keep the group itself."""
        try:
            student_ids = self._db[schema.ACADEMIC_RECORDS].distinct(
                "student_id", {"group_id": group_id}
            )
            result = self._db[schema.ACADEMIC_RECORDS].delete_many({"group_id": group_id})
            self._db[schema.RECORD_HISTORY].delete_many({"group_id": group_id})
            self._remove_orphan_students(student_ids)
        except PyMongoError as exc:
            raise _db_error("clearing a group", exc) from exc
        return result.deleted_count

    def get_student_history(self, group_id: str, student_id: str, limit: int = 20) -> list[dict]:
        """Newest-first snapshots - feeds the future per-student mini history."""
        try:
            return list(
                self._db[schema.RECORD_HISTORY]
                .find({"group_id": group_id, "student_id": student_id}, {"_id": 0})
                .sort("created_at", -1)
                .limit(limit)
            )
        except PyMongoError as exc:
            raise _db_error("reading history", exc) from exc

    # ------------------------------------------------------------------
    # Synthetic data housekeeping
    # ------------------------------------------------------------------

    def purge_synthetic(self) -> dict:
        """Delete only data created by the test-data generator."""
        try:
            student_ids = self._db[schema.ACADEMIC_RECORDS].distinct(
                "student_id", {"source": "synthetic"}
            )
            records = self._db[schema.ACADEMIC_RECORDS].delete_many({"source": "synthetic"})
            self._db[schema.RECORD_HISTORY].delete_many({"source": "synthetic"})
            orphans = self._remove_orphan_students(student_ids)

            groups_deleted = 0
            for group in self._db[schema.GROUPS].find({"source": "synthetic"}, {"group_id": 1}):
                has_records = self._db[schema.ACADEMIC_RECORDS].count_documents(
                    {"group_id": group["group_id"]}, limit=1
                )
                if not has_records:
                    self._db[schema.GROUPS].delete_one({"group_id": group["group_id"]})
                    groups_deleted += 1
        except PyMongoError as exc:
            raise _db_error("removing synthetic data", exc) from exc
        return {
            "records_deleted": records.deleted_count,
            "students_deleted": orphans,
            "groups_deleted": groups_deleted,
        }

    # ------------------------------------------------------------------
    # Imports audit log, stats and browsing
    # ------------------------------------------------------------------

    def log_import(self, entry: dict) -> None:
        try:
            self._db[schema.IMPORT_LOGS].insert_one({**entry, "created_at": _now()})
        except PyMongoError as exc:
            logger.warning("Import log could not be saved: %s", type(exc).__name__)

    def recent_imports(self, limit: int = 10) -> list[dict]:
        try:
            return list(
                self._db[schema.IMPORT_LOGS].find({}, {"_id": 0}).sort("created_at", -1).limit(limit)
            )
        except PyMongoError as exc:
            raise _db_error("reading import logs", exc) from exc

    def stats(self) -> dict:
        try:
            counts = {
                name: self._db[name].estimated_document_count() for name in schema.ALL_COLLECTIONS
            }
        except PyMongoError as exc:
            raise _db_error("reading stats", exc) from exc
        return {"database": self._db.name, "collections": counts}

    def browse(self, collection: str, *, limit: int = 50, skip: int = 0) -> dict:
        if collection not in schema.ALL_COLLECTIONS:
            raise ValidationError(
                f"unknown collection '{collection}'",
                user_message="Coleccion no permitida.",
            )
        limit = max(1, min(int(limit), 200))
        skip = max(0, int(skip))
        try:
            total = self._db[collection].estimated_document_count()
            docs = list(self._db[collection].find({}, {"_id": 0}).skip(skip).limit(limit))
        except PyMongoError as exc:
            raise _db_error("browsing a collection", exc) from exc
        return {"collection": collection, "total": total, "skip": skip, "limit": limit, "documents": docs}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _names_for(self, student_ids: list[str]) -> dict[str, str]:
        if not student_ids:
            return {}
        return {
            s["student_id"]: s["name"]
            for s in self._db[schema.STUDENTS].find(
                {"student_id": {"$in": student_ids}}, {"_id": 0, "student_id": 1, "name": 1}
            )
        }

    @staticmethod
    def _to_student_record(record: dict, names: dict[str, str]) -> StudentRecord:
        return StudentRecord(
            student_id=record["student_id"],
            name=names.get(record["student_id"], record["student_id"]),
            grades=[float(g) for g in record["grades"]],
            attendance_pct=float(record["attendance_pct"]),
            participation_score=float(record["participation_score"]),
        )

    def _remove_orphan_students(self, student_ids: list[str]) -> int:
        """Delete students that no longer belong to any group."""
        if not student_ids:
            return 0
        still_enrolled = set(
            self._db[schema.ACADEMIC_RECORDS].distinct(
                "student_id", {"student_id": {"$in": list(student_ids)}}
            )
        )
        orphans = [s for s in set(student_ids) if s not in still_enrolled]
        if not orphans:
            return 0
        return self._db[schema.STUDENTS].delete_many({"student_id": {"$in": orphans}}).deleted_count

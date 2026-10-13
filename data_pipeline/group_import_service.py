"""
data_pipeline/group_import_service.py

Use cases of the "group management" feature, sitting between the admin web
interface and the repository (Business Logic layer):

    - create a group
    - add / update one student manually
    - import a whole group from an Excel file

Design note (traceability: SRP, Fail-Fast, FR-1, FR-2):
    Every write goes through FailFastValidator BEFORE it reaches the
    repository, so the repository stays a pure read/write layer and bad
    data is rejected at the door (FR-2) instead of being stored.
"""

import re

from core.exception_handler import ValidationError
from core.logger import get_logger
from data_access.mongo_repository import MongoAcademicRepository
from data_access.student_repository import StudentRecord
from data_pipeline.excel_importer import MAX_ID_LENGTH, MAX_NAME_LENGTH, parse_workbook
from data_pipeline.fail_fast_validator import FailFastValidator

logger = get_logger(__name__)

_GROUP_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")


def validate_group_id(group_id: str) -> str:
    group_id = (group_id or "").strip()
    if not _GROUP_ID_RE.match(group_id):
        raise ValidationError(
            f"invalid group id '{group_id}'",
            user_message=(
                "ID de grupo invalido. Usa letras, numeros, punto, guion o guion bajo "
                "(maximo 32 caracteres), por ejemplo: 301-A."
            ),
        )
    return group_id


class GroupImportService:
    def __init__(self, repository: MongoAcademicRepository) -> None:
        self._repo = repository

    # ------------------------------------------------------------------
    def create_group(self, group_id: str, *, name: str = "", period: str = "",
                     teacher: str = "", source: str = "manual") -> dict:
        group_id = validate_group_id(group_id)
        return self._repo.create_group(
            group_id,
            name=name.strip()[:120],
            period=period.strip()[:60],
            teacher=teacher.strip()[:120],
            source=source,
        )

    # ------------------------------------------------------------------
    def add_student(self, group_id: str, *, student_id: str, name: str, grades: list,
                    attendance_pct, participation_score) -> dict:
        group_id = validate_group_id(group_id)
        self._require_group(group_id)

        student_id = (student_id or "").strip()
        name = " ".join((name or "").split())
        if not student_id or len(student_id) > MAX_ID_LENGTH:
            raise ValidationError("bad student id", user_message="Matricula invalida o vacia.")
        if not name or len(name) > MAX_NAME_LENGTH:
            raise ValidationError("bad name", user_message="Nombre invalido o vacio.")

        try:
            record = StudentRecord(
                student_id=student_id,
                name=name,
                grades=[float(g) for g in grades],
                attendance_pct=float(attendance_pct),
                participation_score=float(participation_score),
            )
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                "non numeric value",
                user_message="Calificaciones, asistencia y participacion deben ser numeros.",
            ) from exc

        FailFastValidator.validate(record)
        return self._repo.upsert_records(group_id, [record], source="manual")

    # ------------------------------------------------------------------
    def import_excel(self, group_id: str, file_bytes: bytes, *, filename: str = "",
                     mode: str = "partial", create_if_missing: bool = False,
                     group_info: dict | None = None) -> dict:
        """
        mode "partial": valid rows are imported, invalid ones are reported.
        mode "strict":  nothing is imported if any row is invalid.
        """
        group_id = validate_group_id(group_id)
        if mode not in ("partial", "strict"):
            raise ValidationError("bad mode", user_message="Modo de importacion invalido.")

        # File-level Fail-Fast first: nothing is written if the file is unusable.
        parsed = parse_workbook(file_bytes)

        group_created = False
        if not self._repo.group_exists(group_id):
            if not create_if_missing:
                raise ValidationError(
                    f"group '{group_id}' not found",
                    user_message=f"El grupo '{group_id}' no existe. Crealo primero o activa 'crear grupo'.",
                )
            info = group_info or {}
            if parsed.rejected and mode == "strict":
                pass  # do not create an empty group for a rejected strict import
            else:
                self.create_group(
                    group_id,
                    name=info.get("name", ""), period=info.get("period", ""),
                    teacher=info.get("teacher", ""), source="excel",
                )
                group_created = True

        rejected = [
            {"row": r.row, "student_id": r.student_id, "reason": r.reason} for r in parsed.rejected
        ]
        base_log = {
            "group_id": group_id,
            "filename": filename[:120],
            "mode": mode,
            "total_rows": parsed.total_rows,
            "rejected_count": len(rejected),
        }

        if mode == "strict" and rejected:
            self._repo.log_import({**base_log, "status": "rejected",
                                   "created": 0, "updated": 0, "unchanged": 0})
            raise ValidationError(
                f"strict import rejected: {len(rejected)} invalid rows",
                user_message=(
                    f"Importacion cancelada: {len(rejected)} fila(s) invalida(s). "
                    "No se guardo nada (modo estricto)."
                ),
            )

        outcome = self._repo.upsert_records(group_id, parsed.records, source="excel")
        status = "ok" if not rejected else "partial"
        self._repo.log_import({**base_log, "status": status, **outcome})
        logger.info(
            "Excel import into '%s': %d created, %d updated, %d unchanged, %d rejected",
            group_id, outcome["created"], outcome["updated"], outcome["unchanged"], len(rejected),
        )

        return {
            "group_id": group_id,
            "group_created": group_created,
            "filename": filename,
            "mode": mode,
            "total_rows": parsed.total_rows,
            **outcome,
            "rejected": rejected,
        }

    # ------------------------------------------------------------------
    def _require_group(self, group_id: str) -> None:
        if not self._repo.group_exists(group_id):
            raise ValidationError(
                f"group '{group_id}' not found",
                user_message=f"El grupo '{group_id}' no existe.",
            )

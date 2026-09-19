"""
presentation/teacher_report_ui.py

Design note (traceability: FR-6; NFR-6; Report Viewer, Figure 1):
    This is the "Report Viewer" component from the component diagram. Its
    one job is turning a list of RiskResults into something a teacher can
    read in a few seconds, with no ML terminology (NFR-6: "clear,
    non-technical format"). It is the only module in this project allowed
    to re-attach a student's name to a result, since a report with only
    pseudonymous IDs would not be usable by a teacher.
"""

from inference_engine.risk_predictor import RiskResult

_LABEL_DISPLAY = {
    "high": "HIGH RISK",
    "medium": "Monitor",
    "low": "On track",
}


class TeacherReportUI:
    @staticmethod
    def render_group_report(
        group_id: str,
        results: list[RiskResult],
        name_lookup: dict[str, str],
    ) -> str:
        """
        Build a plain-text report, sorted highest-risk-first, with names
        resolved from `name_lookup` (student_id -> name), coming from the
        Data Access layer's records - never from the AI layer.
        """
        ordered = sorted(results, key=lambda r: r.risk_score, reverse=True)

        lines = [
            f"Risk report - Group {group_id}",
            "=" * 40,
        ]

        if not ordered:
            lines.append("No valid student records were available for this group.")
            return "\n".join(lines)

        for result in ordered:
            name = name_lookup.get(result.student_ref, result.student_ref)
            status = _LABEL_DISPLAY.get(result.risk_label, result.risk_label)
            lines.append(f"{name:<20} {status:<12} risk score: {result.risk_score:5.1f}/100")

        at_risk_count = sum(1 for r in ordered if r.risk_label == "high")
        lines.append("-" * 40)
        lines.append(f"{at_risk_count} of {len(ordered)} students at high risk.")

        return "\n".join(lines)

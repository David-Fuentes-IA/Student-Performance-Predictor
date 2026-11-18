"""
scripts/ai_value_experiment.py

Does the AI model add anything to the school's own rule? (Milestone 3 feedback, criterion 3)

    python scripts/ai_value_experiment.py            # writes docs/evidence/model/ai_value.json and ai_value.md

The school rule flags a student whose average is failing (below 60). With the model part of the
application's rule at 75, the model added no correct alert to that rule on the independent set. This
experiment asks the question properly:

1. Same workload. Every method flags the SAME number of students (the number the school rule flags,
   plus 15 / 25 / 35 % of the group), so a method cannot look better just by flagging more students.
   Ranking students by their average grade IS the school rule; a model trained on the average alone
   would rank them identically, so "full model vs. ranking by average" is also the ablation that shows
   what attendance, participation and trend add.
2. A stronger traditional rule: "average below 60 OR attendance below 80" (two indicators, no AI),
   compared with the model at the same workload.
3. Early detection: the same comparisons when only the first partial exam, or the first two, are known.
   This is where a model could matter most: the failing-average rule only fires once the average is
   already failing.
4. Statistics: every comparison is PAIRED (same students): exact McNemar on the students where the two
   methods disagree, and a paired bootstrap interval for the difference in average precision.

Everything here is measured on synthetic students (data/README.md). It shows the method and how the
model behaves on the simulation; it does not show how it would behave with real students.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
from sklearn.metrics import average_precision_score  # noqa: E402

from core import config  # noqa: E402
from data_access.student_repository import StudentRecord  # noqa: E402
from data_access.synthetic_students import simulate_students  # noqa: E402
from feature_store.feature_manager import FeatureManager  # noqa: E402
from learning_module.evaluation_data import DEFAULT_PATH, load_evaluation_workbook  # noqa: E402
from learning_module.model_trainer import ModelTrainer  # noqa: E402
from learning_module.model_validation import (  # noqa: E402
    flag_top,
    out_of_fold_scores,
    paired_bootstrap_difference,
    paired_comparison,
    score_predictions,
)
from learning_module.training_pipeline import DATA_SEED, N_SAMPLES  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "model"
STAGES = {"first_partial_only": 1, "first_two_partials": 2, "all_partials": None}
BUDGET_SHARES = (0.15, 0.25, 0.35)
ATTENDANCE_LIMIT = 80.0
RANKERS = ("average_grade", "logistic_regression", "random_forest")


def truncated(records, partials):
    """The same students as they would look after `partials` exams (None = the whole term).
    Attendance and participation stay at their end-of-term values: the simulation has no weekly record,
    which makes the early stages somewhat optimistic for every method that uses them."""
    return [StudentRecord(r.student_id, r.name, r.grades[:partials] if partials else r.grades,
                          r.attendance_pct, r.participation_score) for r in records]


def features(records):
    return np.asarray([v.as_model_input() for v in FeatureManager.extract_many(records)], dtype=float)


def recall_precision(y, flags):
    m = score_predictions(y, flags)
    return {"recall": round(m["recall"], 4), "precision": round(m["precision"], 4),
            "caught": int(np.sum((np.asarray(y) == 1) & (flags == 1))), "flagged": int(flags.sum())}


def compare_at_budget(y, scores, budget):
    flags = {name: flag_top(scores[name], budget) for name in RANKERS}
    return {
        "budget": int(budget),
        "by_method": {name: recall_precision(y, flags[name]) for name in RANKERS},
        "logistic_vs_average": paired_comparison(y, flags["logistic_regression"], flags["average_grade"]),
        "random_forest_vs_average": paired_comparison(y, flags["random_forest"], flags["average_grade"]),
    }


def analyse(y, X, scores, passing):
    """All comparisons for one dataset (cross-validation or independent) at one stage."""
    y = np.asarray(y)
    failing = (X[:, 0] < passing).astype(int)
    two_indicators = ((X[:, 0] < passing) | (X[:, 2] < ATTENDANCE_LIMIT)).astype(int)
    budgets = {"school_rule_workload": int(failing.sum()),
               **{f"{int(s * 100)}pct_of_group": int(round(s * len(y))) for s in BUDGET_SHARES}}
    two_budget = int(two_indicators.sum())
    model_at_two_budget = flag_top(scores["logistic_regression"], two_budget)
    return {
        "students": int(len(y)),
        "at_risk": int(y.sum()),
        "school_rule": recall_precision(y, failing),
        "at_equal_workload": {name: compare_at_budget(y, scores, b) for name, b in budgets.items()},
        "two_indicator_rule": {
            "rule": f"average < {passing:g} OR attendance < {ATTENDANCE_LIMIT:g}",
            "rule_result": recall_precision(y, two_indicators),
            "logistic_at_same_workload": recall_precision(y, model_at_two_budget),
            "logistic_vs_rule": paired_comparison(y, model_at_two_budget, two_indicators),
        },
        "average_precision": {
            **{name: round(float(average_precision_score(y, scores[name])), 4) for name in RANKERS},
            "logistic_minus_average": paired_bootstrap_difference(
                y, scores["logistic_regression"], scores["average_grade"], average_precision_score),
        },
    }


def run() -> dict:
    passing = config.DEFAULT_PASSING_GRADE
    train_students = simulate_students(N_SAMPLES, seed=DATA_SEED)
    train_records = [StudentRecord(s.student_id, s.name, s.grades, s.attendance_pct, s.participation_score)
                     for s in train_students]
    y_train = np.asarray([s.at_risk for s in train_students])
    evaluation = load_evaluation_workbook(DEFAULT_PATH)
    y_test = np.asarray([evaluation.labels[r.student_id] for r in evaluation.records])

    stages = {}
    for stage, partials in STAGES.items():
        X_train = features(truncated(train_records, partials))
        X_test = features(truncated(evaluation.records, partials))
        scores_cv = {"average_grade": 100 - X_train[:, 0]}
        scores_test = {"average_grade": 100 - X_test[:, 0]}
        for model_type in ("logistic_regression", "random_forest"):
            scores_cv[model_type] = out_of_fold_scores(lambda m=model_type: ModelTrainer.build(m), X_train, y_train)
            scores_test[model_type] = ModelTrainer.fit(model_type, X_train, y_train).predict_proba(X_test)[:, 1] * 100
        stages[stage] = {"partials_known": partials or "all",
                         "cross_validation": analyse(y_train, X_train, scores_cv, passing),
                         "independent": analyse(y_test, X_test, scores_test, passing)}
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "question": "does the AI model find at-risk students that the school's own rules miss, at the same workload?",
        "data": {"training": f"{N_SAMPLES} simulated students (seed {DATA_SEED}), out-of-fold scores",
                 "independent": "data/grupo_evaluacion.xlsx (240 students, seed 2026)",
                 "caveat": "synthetic data: the results describe the simulation, not real students"},
        "statistics": "paired: exact McNemar on discordant students; paired bootstrap (2000) for average precision",
        "stages": stages,
    }


def markdown(results: dict) -> str:
    lines = ["# Does the AI model add value beyond the school rule? (generated by scripts/ai_value_experiment.py)", "",
             "Synthetic data. Recall at the SAME workload (students flagged); p = exact McNemar, model vs ranking "
             "by average (which is the school rule).", ""]
    for stage, body in results["stages"].items():
        lines += [f"## {stage.replace('_', ' ')}", "",
                  "| Data | Workload | Average (school rule) | Logistic Regression | Random Forest | p (LR vs average) |",
                  "|---|---|---|---|---|---|"]
        for data in ("cross_validation", "independent"):
            part = body[data]
            for name, comparison in part["at_equal_workload"].items():
                m = comparison["by_method"]
                lines.append(
                    f"| {data.replace('_', '-')} | {name.replace('_', ' ')} ({comparison['budget']}) | "
                    f"{m['average_grade']['caught']}/{part['at_risk']} ({m['average_grade']['recall']:.3f}) | "
                    f"{m['logistic_regression']['caught']}/{part['at_risk']} ({m['logistic_regression']['recall']:.3f}) | "
                    f"{m['random_forest']['caught']}/{part['at_risk']} ({m['random_forest']['recall']:.3f}) | "
                    f"{comparison['logistic_vs_average']['mcnemar_p_recall']} |")
        lines.append("")
        lines += ["| Data | Average precision: average / LR / RF | LR − average (95 % paired bootstrap) | "
                  "Two-indicator rule vs LR at its workload (caught, p) |", "|---|---|---|---|"]
        for data in ("cross_validation", "independent"):
            ap = body[data]["average_precision"]
            two = body[data]["two_indicator_rule"]
            diff = ap["logistic_minus_average"]
            lines.append(
                f"| {data.replace('_', '-')} | {ap['average_grade']} / {ap['logistic_regression']} / "
                f"{ap['random_forest']} | {diff['difference']:+.3f} [{diff['ci95'][0]:+.3f}, {diff['ci95'][1]:+.3f}] | "
                f"rule {two['rule_result']['caught']} vs LR {two['logistic_at_same_workload']['caught']} "
                f"(flagged {two['rule_result']['flagged']}), p = {two['logistic_vs_rule']['mcnemar_p_recall']} |")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    results = run()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "ai_value.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    report = markdown(results)
    (OUT / "ai_value.md").write_text(report + "\n", encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()

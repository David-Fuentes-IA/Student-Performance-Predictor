import unittest

import numpy as np
from sklearn.linear_model import LogisticRegression

from learning_module.model_validation import (
    ALERT_MIN_PRECISION,
    GATE_MIN_F1,
    GATE_MIN_PRECISION,
    GATE_MIN_RECALL,
    MIN_PRECISION_FOR_SELECTION,
    check_quality_gate,
    confusion_counts,
    cross_validate,
    fairness_report,
    lowest_threshold_with_precision,
    out_of_fold_scores,
    score_predictions,
    select_model,
    threshold_sweep,
    wilson_interval,
)


def result(recall, precision, f2=None, recall_std=0.05):
    return {"mean": {"recall": recall, "precision": precision, "f2": f2 if f2 is not None else recall},
            "std": {"recall": recall_std}}


class MetricTests(unittest.TestCase):
    def test_known_confusion_matrix_gives_known_metrics(self):
        # TP=3, FN=1, FP=2, TN=4
        y_true = [1, 1, 1, 1, 0, 0, 0, 0, 0, 0]
        y_pred = [1, 1, 1, 0, 1, 1, 0, 0, 0, 0]
        self.assertEqual(confusion_counts(y_true, y_pred), {"tn": 4, "fp": 2, "fn": 1, "tp": 3})
        m = score_predictions(y_true, y_pred)
        self.assertAlmostEqual(m["accuracy"], 0.7)
        self.assertAlmostEqual(m["precision"], 0.6)
        self.assertAlmostEqual(m["recall"], 0.75)
        self.assertAlmostEqual(m["f1"], 2 * 0.6 * 0.75 / (0.6 + 0.75))
        self.assertAlmostEqual(m["f2"], 5 * 0.6 * 0.75 / (4 * 0.6 + 0.75))  # F2 leans towards recall

    def test_never_flagging_anyone_gives_zero_not_an_error(self):
        m = score_predictions([1, 0, 1], [0, 0, 0])
        self.assertEqual((m["precision"], m["recall"], m["f1"]), (0.0, 0.0, 0.0))

    def test_confusion_counts_include_empty_classes(self):
        self.assertEqual(confusion_counts([0, 0], [0, 0]), {"tn": 2, "fp": 0, "fn": 0, "tp": 0})


class CrossValidationTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(0)
        self.X = np.vstack([rng.normal(0, 1, (60, 2)), rng.normal(6, 1, (30, 2))])
        self.y = np.array([0] * 60 + [1] * 30)

    def test_separable_data_scores_perfectly_in_every_fold(self):
        cv = cross_validate(lambda: LogisticRegression(), self.X, self.y)
        self.assertEqual(cv["folds"], 5)
        self.assertEqual(len(cv["per_fold"]["recall"]), 5)
        self.assertEqual(cv["mean"]["recall"], 1.0)
        self.assertEqual(cv["confusion_out_of_fold"], {"tn": 60, "fp": 0, "fn": 0, "tp": 30})

    def test_is_reproducible(self):
        a = cross_validate(lambda: LogisticRegression(), self.X, self.y)
        b = cross_validate(lambda: LogisticRegression(), self.X, self.y)
        self.assertEqual(a, b)

    def test_out_of_fold_scores_cover_every_student_in_0_100(self):
        scores = out_of_fold_scores(lambda: LogisticRegression(), self.X, self.y)
        self.assertEqual(len(scores), 90)
        self.assertTrue(((scores >= 0) & (scores <= 100)).all())
        self.assertGreater(scores[self.y == 1].mean(), scores[self.y == 0].mean() + 50)


class ModelSelectionTests(unittest.TestCase):
    def test_clearly_higher_recall_wins(self):
        decision = select_model({"a": result(0.60, 0.9, recall_std=0.02), "b": result(0.80, 0.8, recall_std=0.02)})
        self.assertEqual(decision["selected"], "b")

    def test_a_model_below_the_precision_floor_is_not_eligible(self):
        decision = select_model({"high_recall_useless": result(0.95, MIN_PRECISION_FOR_SELECTION - 0.05),
                                 "balanced": result(0.70, 0.85)})
        self.assertEqual(decision["selected"], "balanced")

    def test_a_tie_within_one_standard_deviation_goes_to_the_better_f2(self):
        decision = select_model({"x": result(0.715, 0.82, f2=0.73, recall_std=0.08),
                                 "y": result(0.733, 0.85, f2=0.75, recall_std=0.06)})
        self.assertEqual(decision["selected"], "y")
        self.assertAlmostEqual(decision["recall_gap_between_models"], 0.018)

    def test_the_decision_states_that_it_was_not_made_on_the_independent_set(self):
        self.assertIn("independent set is not used", select_model({"a": result(0.7, 0.8)})["decided_on"])


class IntervalAndFairnessTests(unittest.TestCase):
    def test_wilson_interval_known_values(self):
        low, high = wilson_interval(5, 10)
        self.assertAlmostEqual(low, 0.2366, places=3)
        self.assertAlmostEqual(high, 0.7634, places=3)
        self.assertEqual(wilson_interval(0, 10)[0], 0.0)
        self.assertEqual(wilson_interval(10, 10)[1], 1.0)
        self.assertIsNone(wilson_interval(0, 0))

    def test_interval_narrows_with_more_data(self):
        small, large = wilson_interval(5, 10), wilson_interval(500, 1000)
        self.assertLess(large[1] - large[0], small[1] - small[0])

    def test_error_rates_and_gaps_per_group(self):
        #            A: 2 negatives (1 flagged), 2 positives (1 missed)   B: 2 negatives (0 flagged), 2 positives (0 missed)
        y_true = [0, 0, 1, 1, 0, 0, 1, 1]
        y_pred = [1, 0, 0, 1, 0, 0, 1, 1]
        groups = ["A", "A", "A", "A", "B", "B", "B", "B"]
        report = fairness_report(y_true, y_pred, groups)
        self.assertEqual(report["by_group"]["A"]["false_positive_rate"], 0.5)
        self.assertEqual(report["by_group"]["A"]["false_negative_rate"], 0.5)
        self.assertEqual(report["by_group"]["B"]["false_positive_rate"], 0.0)
        self.assertEqual(report["by_group"]["A"]["flag_rate"], 0.5)
        self.assertEqual(report["gap"], {"false_positive_rate": 0.5, "false_negative_rate": 0.5, "flag_rate": 0.0})
        self.assertTrue(report["intervals_overlap"]["false_positive_rate"])  # n=2 per group: cannot conclude anything

    def test_a_large_gap_with_plenty_of_data_is_flagged_as_distinguishable(self):
        n = 400
        y_true = [0] * (2 * n)
        y_pred = [1] * 40 + [0] * (n - 40) + [1] * 120 + [0] * (n - 120)   # 10 % vs 30 % false positives
        groups = ["A"] * n + ["B"] * n
        report = fairness_report(y_true, y_pred, groups)
        self.assertAlmostEqual(report["gap"]["false_positive_rate"], 0.2)
        self.assertFalse(report["intervals_overlap"]["false_positive_rate"])

    def test_group_without_positives_has_an_undefined_miss_rate(self):
        report = fairness_report([0, 0, 1], [0, 0, 1], ["A", "A", "B"])
        self.assertIsNone(report["by_group"]["A"]["false_negative_rate"])


class ThresholdTests(unittest.TestCase):
    def setUp(self):
        self.y = [1, 1, 1, 1, 0, 0, 0, 0]
        self.scores = [90, 70, 40, 20, 60, 30, 10, 5]

    def test_recall_never_increases_when_the_threshold_rises(self):
        recalls = [r["recall"] for r in threshold_sweep(self.y, self.scores)]
        self.assertEqual(recalls, sorted(recalls, reverse=True))

    def test_each_row_is_consistent_with_a_manual_count(self):
        row = next(r for r in threshold_sweep(self.y, self.scores, thresholds=[50]))
        self.assertEqual((row["tp"], row["fn"], row["fp"], row["tn"]), (2, 2, 1, 3))
        self.assertAlmostEqual(row["flagged_share"], 3 / 8)

    def test_lowest_threshold_that_keeps_precision(self):
        sweep = threshold_sweep(self.y, self.scores, thresholds=[10, 30, 50, 75])
        # precision by threshold: 10 -> 4/7, 30 -> 3/5, 50 -> 2/3, 75 -> 1/1
        self.assertEqual(lowest_threshold_with_precision(sweep, min_precision=0.55), 10)
        self.assertEqual(lowest_threshold_with_precision(sweep, min_precision=0.65), 50)
        self.assertEqual(lowest_threshold_with_precision(sweep, min_precision=0.7), 75)
        self.assertIsNone(lowest_threshold_with_precision(sweep, min_precision=1.1))
        self.assertGreater(ALERT_MIN_PRECISION, 0.5)


class QualityGateTests(unittest.TestCase):
    GOOD = {"accuracy": 0.87, "precision": 0.77, "recall": 0.73, "f1": 0.75, "f2": 0.74}

    def test_a_good_model_passes(self):
        self.assertEqual(check_quality_gate(self.GOOD), [])

    def test_each_threshold_is_enforced_independently(self):
        for metric, floor in (("recall", GATE_MIN_RECALL), ("precision", GATE_MIN_PRECISION), ("f1", GATE_MIN_F1)):
            with self.subTest(metric):
                problems = check_quality_gate(dict(self.GOOD, **{metric: floor - 0.01}))
                self.assertEqual(len(problems), 1)
                self.assertIn(metric, problems[0])

    def test_boundary_value_passes(self):
        self.assertEqual(check_quality_gate(dict(self.GOOD, recall=GATE_MIN_RECALL)), [])

    def test_a_perfect_score_is_rejected_as_suspicious(self):
        problems = check_quality_gate({"accuracy": 1.0, "precision": 1.0, "recall": 1.0, "f1": 1.0, "f2": 1.0})
        self.assertTrue(any("leakage" in p for p in problems))


if __name__ == "__main__":
    unittest.main()

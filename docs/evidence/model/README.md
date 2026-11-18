# Model validation and error analysis (Milestone 3, criterion 3)

> *Software testing evaluates the software. Model validation evaluates the intelligence of the model.*
> The test suite (`docs/evidence/testing/`) shows the application works. This document asks a different
> question: **are the predictions reliable on students the model has never seen?**

Everything below is produced by one command and recorded in `metrics.json`:

```bash
python scripts/evaluate_models.py          # rewrites this folder
python scripts/evaluate_models.py --gate   # CI quality gate (exit code 1 when the model is not good enough)
```

| File | Content |
|---|---|
| `metrics.json` | every number quoted here |
| `comparison.md` | the comparison table |
| `confusion_matrices.png`, `cv_metrics.png`, `operating_points.png` | figures |
| `errors.csv` | **every** misclassified student of the independent set (31 rows) |
| `ai_value.md`, `ai_value.json` | does the model beat the school rule at the same workload, also early in the term? (`python scripts/ai_value_experiment.py`, about 40 s) |

## 1. Protocol

| | Data | Use |
|---|---|---|
| Training / cross-validation | 600 simulated students (seed 7), 27.5 % at risk | compare the two models and **take every decision** |
| Independent evaluation | 240 simulated students (seed 2026, `data/grupo_evaluacion.xlsx`), 26.7 % at risk | measure the chosen model **once**, on data it never saw |

Positive class = *student at risk*. Cross-validation is stratified 5-fold. The independent set is never used to
choose anything: choosing with it would leak it into the decision and make its numbers optimistic.
The data are synthetic (see `data/README.md`); the difficulty was calibrated on purpose, so these results say
nothing about accuracy on real students.

## 2. Results

| Model | Accuracy | Precision | Recall | F1 | F2 |
|---|---|---|---|---|---|
| Random Forest, 5-fold CV | 0.877 ± 0.015 | 0.822 ± 0.069 | 0.715 ± 0.082 | 0.760 ± 0.035 | 0.731 ± 0.063 |
| Logistic Regression, 5-fold CV | 0.888 ± 0.007 | 0.848 ± 0.067 | 0.733 ± 0.058 | 0.783 ± 0.010 | 0.752 ± 0.039 |
| Random Forest, independent set | 0.863 | 0.772 | 0.688 | 0.727 | 0.703 |
| Logistic Regression, independent set | 0.871 | 0.770 | 0.734 | 0.752 | 0.741 |

Confusion matrices (`confusion_matrices.png`), independent set, cutting at risk score 50:

| | Predicted not at risk | Predicted at risk |
|---|---|---|
| **Random Forest**: actually not at risk | 163 (TN) | 13 (FP) |
| **Random Forest**: actually at risk | 20 (FN) | 44 (TP) |
| **Logistic Regression**: actually not at risk | 162 (TN) | 14 (FP) |
| **Logistic Regression**: actually at risk | 17 (FN) | 47 (TP) |

**What the metrics say.** *Accuracy* (87 %) looks good but is the least informative number here: only 27 % of
students are at risk, so a model that never flagged anyone would already be 73 % "accurate".
*Precision* (0.77): when the system flags a student it is right 77 % of the time, so about 1 alert in 4 is a false alarm.
*Recall* (0.73): it finds 73 % of the students who really end up at risk and misses 27 %.
The model is useful, clearly better than chance, and clearly not perfect.

With 64 at-risk students, one point estimate is not exact: the independent recall of 0.734 (47 / 64) has a 95 %
interval of **0.62–0.83**, and the precision of 0.77 (47 / 61) of **0.65–0.86**.

## 3. Which error matters, and the choice of model

A **false negative** is a struggling student the system calls "on track": no tutoring, possibly failing or dropping
out. A **false positive** is a student who is fine but gets reviewed: some wasted teacher time and possible stigma.
The first is the more harmful error, so **recall is the priority metric**, with precision only required to stay
high enough for alerts to be worth acting on. F2 (recall counts double) is reported as the balanced summary.

**Selection rule**, applied to cross-validation only: highest mean recall among models with mean precision ≥ 0.60;
models whose recall is within one standard deviation of the best are considered tied and the better F2 wins.

**Outcome: Logistic Regression, but it is a tie-break, not a victory.** Its mean recall is 0.018 higher than the Random
Forest's, while the fold-to-fold standard deviation is 0.058–0.082 (`cv_metrics.png`): the models are statistically
indistinguishable on the priority metric. Logistic Regression is chosen because it is (a) at least as good on every
averaged metric, (b) steadier across folds (F1 ± 0.010 against ± 0.035), and (c) a simpler model whose scores are smoother and
whose weights can be inspected (section 5). The independent set points the same way (recall 0.734 against 0.688, 17 against 20
missed students), but a difference of three students on 64 is not evidence by itself.

The paired test says the same (`metrics.json` → `paired_model_comparison`, both models cut at 50 on the same students): on
the independent set 4 at-risk students are caught only by Logistic Regression and 1 only by Random Forest (McNemar p = 0.375);
on the 600 cross-validation students, 7 against 4 (p = 0.55). Neither model is significantly better. A difference this size
would need several hundred at-risk students to be detectable; repeated cross-validation with the corrected t-test (Nadeau and
Bengio) would be the next check on more data.

The decision lives in configuration, not in a document: `core/config.py` (`DEFAULT_MODEL_TYPE`, overridable with `RISK_MODEL`)
decides what `scripts/train_model.py` trains; the model card records `engine_type`; the application builds the matching
engine through `create_risk_engine` (Factory, FR-8). A test fails if this document and the code ever name different models.

## 4. Error analysis

Metrics summarise; error analysis explains. The independent set has **31 errors (12.9 %)**: 17 false negatives and 14
false positives, all listed in `errors.csv`. Profile of each outcome (means):

| Outcome | n | Average grade | Grade trend | Attendance | Participation | Risk score | Fewer than 4 partials | Evening shift |
|---|---|---|---|---|---|---|---|---|
| TP (caught) | 47 | 50.9 | −7.3 | 74.6 | 60.0 | 80.6 | 11 % | 47 % |
| **FN (missed)** | 17 | **66.5** | −3.2 | **82.5** | 66.2 | **23.9** | 29 % | 18 % |
| **FP (false alarm)** | 14 | **57.9** | 0.0 | **70.0** | 55.3 | **72.9** | 21 % | 50 % |
| TN (correctly cleared) | 162 | 77.4 | −0.8 | 83.6 | 74.2 | 8.3 | 19 % | 40 % |

**Pattern 1: most errors are confident, not close calls.** Only 26 % of the errors lie near the decision boundary
(score within ±15 of 50), against 8 % of correct predictions: borderline cases are about three times as error-prone,
but they explain a minority of the mistakes. Three quarters are confident errors.

**Pattern 2: the missed students do not look at risk.** Their attendance (82.5) is practically that of the cleared students
(83.6) and far from the caught ones (74.6); their average grade (66.5) sits between the two groups, somewhat nearer the cleared
ones (77.4) than the caught ones (50.9); only their participation (66.2) is nearer the caught group (60.0). The model gives them an
average score of 23.9. Examples: `E0111` has average 66.4, attendance 96.2, improving grades (+8.2) and a score of 18.2,
yet ended at risk; `E0043`, `E0121` and `E0157` are similar. Nothing in the four features separates these students, which
is what unobserved events (illness, work, family) would look like. The data cannot tell us the cause, and this analysis does not
claim to know it.

**Pattern 3: the model barely uses the grade trend.** In the fitted model, one standard deviation of average grade moves the
risk logit by −3.11, while one standard deviation of trend moves it by +0.53, six times less and with a sign that is
counterintuitive (rising grades slightly raise the risk) because trend and average grade are correlated. Coefficients of
correlated features must not be interpreted causally. The practical consequence: of the 19 at-risk students whose grades fell by 14 or
more points, **5 (26 %) were missed, the same as the overall miss rate (27 %)**, so the trend feature does not help catch them.
`E0054` fell 28 points and received a score of 3.2.

**Pattern 4: low attendance plus low grades triggers false alarms.** Of the 14 false positives, 10 have a score of 70 or more,
and half are evening students although only 40 % of cleared students are (section 7). `E0059` (evening) has average 56.8 and
attendance 60.5 and was flagged at 87.9 despite grades rising 22.8 points; it did not end at risk.

**Pattern 5: students with fewer partial exams are missed more often**: 29 % of the false negatives have fewer than 4
grades against 11 % of the caught students. With 5 of 17 cases this is an indication, not a proof.

**Likely causes**, using the usual list: *insufficient information* (four features and no record of life events are
the main limit), *noise* in grades and attendance, a *minority class* (27 %), a *small dataset* (600), and, specific to this project,
*synthetic data* that may not resemble real students.

### Where the biggest gain is: the alert rule

The figures above cut the score at 50, but **until this phase the application raised its Risk Alert only when the model score
reached 75** (`RISK_THRESHOLD`). Measured on the independent set with the chosen model:

| Flag students with risk score ≥ | Flagged | Precision | Recall (95 % interval) | Missed (FN) | False alarms (FP) |
|---|---|---|---|---|---|
| 75 (the former alert rule) | 15 % | 0.800 | **0.438** (0.32–0.56) | **36** of 64 | 7 |
| 50 (cut used by the metrics above) | 25 % | 0.770 | 0.734 (0.62–0.83) | 17 | 14 |
| 35 (best model-only point, from CV) | 30 % | 0.708 | **0.797** (0.68–0.88) | **13** | 21 |
| 15 (maximum F2) | 45 % | 0.528 | 0.891 | 7 | 51 |

With the model score alone at 75 the alert system **missed more than half of the students who end up at risk**. Both
thresholds judge the same students, so they are compared with a paired test: every student flagged at 75 is also flagged at
35, and 23 at-risk students are caught at 35 and missed at 75 (none the other way round), exact McNemar p = 2.4 × 10⁻⁷. The
difference is real (unlike the model comparison), and cross-validation shows the same shape (`operating_points.png`: the solid curves, computed without the independent set, agree with the dashed ones).
The recommendation is the lowest threshold whose cross-validated precision stays at or above 0.70 (at most about 3 alerts in 10
being false alarms), which cross-validation places at **35** (for the model score used alone; see the decision below). That 0.70 is a **policy assumption** the institution may change;
the maximum-F2 point is shown only as a reference because flagging 45 % of a class is not workable.

### Decision taken: "Alto riesgo" as a school would define it, plus the model

The team chose the definition a school uses: **a student whose average is failing (below 6.0, i.e. 60/100) is high risk**,
whatever the model says, and the model adds the students who still pass but score ≥ 75 (`core/risk_levels.py`; both values are
configurable: `PASSING_GRADE`, `RISK_THRESHOLD`). Alerts, the dashboard's "Alto riesgo", the legend and the PDFs all use this rule,
and every alert states its reason. Measured (`metrics.json` → `application_rule`):

| "Alto riesgo" rule | CV recall (95 % interval) | CV precision | Independent recall (95 % interval) | Independent precision | Flagged |
|---|---|---|---|---|---|
| Model score ≥ 75 alone (before) | 0.527 (0.45–0.60) | 0.897 | **0.438** (0.32–0.56) | 0.800 | 15 % |
| Failing average alone | 0.709 (0.64–0.77) | 0.812 | 0.719 (0.60–0.81) | 0.793 | 24 % |
| **Failing average OR score ≥ 75 (applied)** | **0.709** (0.64–0.77) | 0.807 | **0.719** (0.60–0.81) | 0.780 | 25 % |

The applied rule catches **46 of the 64** students who end up at risk instead of 28, with about the same precision.

*How we know the improvement is real (corrected in Milestone 4).* The Milestone 3 version of this page argued from the two
recall intervals not overlapping. That is the wrong test: both rules judge **the same students**, so the samples are paired, and
only the students on which the rules disagree carry information. The exact McNemar test on those students
(`metrics.json` → `application_rule.paired_tests`):

| Comparison (a vs b) | At-risk caught by a only / by b only | McNemar p (recall) | False alarms a only / b only | McNemar p (false alarms) |
|---|---|---|---|---|
| applied rule vs model ≥ 75 alone, independent set | 18 / 0 | 7.6 × 10⁻⁶ | 6 / 0 | 0.031 |
| applied rule vs model ≥ 75 alone, cross-validation (600) | 30 / 0 | 1.9 × 10⁻⁹ | 18 / 0 | 7.6 × 10⁻⁶ |
| applied rule vs failing average alone, independent set | 0 / 0 | 1.0 | 1 / 0 | 1.0 |
| applied rule vs failing average alone, cross-validation | 0 / 0 | 1.0 | 1 / 0 | 1.0 |

The gain over the old rule is real, and it costs a real increase in false alarms. Against the school criterion alone, the model
part at 75 changes nothing: the two rules never disagree about an at-risk student.

What these numbers also show, and must be said: **with the model part at 75, almost all of the gain comes from the school
criterion.** On the independent set the model adds no extra correct alert to "failing average" (and one false alarm), because in
this simulation the average grade drives most outcomes and a student the model scores ≥ 75 is nearly always already failing. The model's
contribution today is the "En observación" band (score ≥ 40) and the ordering of students by risk. Lowering the model part of the rule
would make it count (`application_rule` → `combined_rule_with_lower_model_threshold`):

| Failing average OR score ≥ … | CV recall | CV precision | Independent recall | Independent precision | Extra at-risk caught vs failing average (McNemar p): CV / independent |
|---|---|---|---|---|---|
| 60 | 0.739 | 0.813 | 0.766 | 0.778 | +5 (p = 0.0625) / +3 (p = 0.25) |
| 50 | 0.770 | 0.804 | 0.781 | 0.746 | +10 (p = 0.002) / +4 (p = 0.125) |

At 60 the gain is not distinguishable from chance. At 50 it is, on the 600 cross-validation students, at the price of more
false alarms (+4 in CV, +5 on the independent set). The next section shows where that gain comes from.

### Does the model add value beyond the school rule? (Milestone 3 feedback)

`python scripts/ai_value_experiment.py` → `ai_value.md`, `ai_value.json`. A method can look better just by flagging more
students, so every method flags **the same number of students** (the number the school rule flags, and 15 / 25 / 35 % of the
group), and the methods are compared on the same students with McNemar. Ranking by average grade *is* the school rule at its
own workload, and a model trained on the average alone would rank students identically, so "model vs. ranking by average" is also
the **ablation** that shows what attendance, participation and trend add. It is repeated when only the **first partial**, or the
first two, are known: early detection is where a model could matter most.

| Partials known | Data | At the school rule's workload: caught by ranking by average / by Logistic Regression | McNemar p | Average precision, LR − average (95 % paired bootstrap) |
|---|---|---|---|---|
| first only | CV (165 at risk) | 108 / 107 | 1.0 | +0.016 [−0.010, +0.041] |
| first only | independent (64) | 33 / 36 | 0.51 | +0.003 [−0.035, +0.044] |
| first two | CV | 111 / 113 | 0.79 | +0.007 [−0.009, +0.025] |
| first two | independent | 39 / 40 | 1.0 | −0.005 [−0.035, +0.024] |
| all | CV | 117 / 121 | 0.45 | +0.013 [−0.007, +0.033] |
| all | independent | 46 / 44 | 0.73 | −0.004 [−0.046, +0.033] |

At 15, 25 and 35 % of the group the picture is the same (no p-value below 0.12), and Random Forest against the average is no
different (no p-value below 0.45). A stronger traditional rule, "average < 60 **or** attendance < 80" (two indicators, no AI),
flags about half of the group; at that same workload the model catches more at-risk students in all six comparisons,
significantly in four
(e.g. first partial, independent set: 61 vs 50, p = 0.003; first two partials, CV: 159 vs 143, p = 0.0004; all partials,
independent set: 60 vs 55, p = 0.125).

**Conclusion (answers the Milestone 3 observation directly).**
1. **In this simulation the model does not identify at-risk students better than the school rule.** At the same workload the
   differences are a few students in either direction, never significant, at any stage of the term. The average grade carries
   almost all the information, which is how the simulator was built (data/README.md). The ablation confirms it: what attendance,
   participation and trend add is not distinguishable from zero.
2. **What the model demonstrably does well is combine indicators.** When the school uses more than one indicator with fixed cut-offs,
   the model's weighted combination catches significantly more students for the same workload.
3. The +10 of "failing average OR score ≥ 50" comes from **flagging more students**, not from finding them better: at equal workload
   ranking by average does as well. Those students are already visible to the teacher in the "En observación" band (score ≥ 40).
4. **Decision: the model part of the rule stays at 75.** Lowering it would raise the workload without evidence that the model ranks
   students better than their average; the "En observación" band already shows them.
5. Whether the model adds value **with real students** cannot be answered with synthetic data. The test is this same experiment on
   historical institutional data, out of time (train on earlier terms, evaluate on the next), with the same paired statistics and
   enough at-risk students: with 64 the recall uncertainty is about ±0.11, so differences of a few points need several hundred.

### Proposed improvements

| Improvement | Problem it addresses | Metric that should improve | Status |
|---|---|---|---|
| "Alto riesgo" = failing average OR model score ≥ 75 | 36 of 64 at-risk students missed with the model score alone at 75 | recall 0.44 → 0.72 (measured), precision 0.80 → 0.78 | **applied** |
| Lower the model part of the rule to about 50–60 | at 75 the model adds nothing beyond the school criterion | recall to about 0.77–0.78 (measured separately), precision about 0.75–0.78 | measured, **not applied**: at equal workload the gain disappears (see the previous section) |
| Features that capture recent change better (last partial grade, lowest grade, missing partials) | the trend is barely used; 26 % of sharply declining students are missed | recall among students with a sharp decline (now 74 % caught) | proposal, **not implemented** |
| Flag students with fewer than 3 partials as "insufficient data" for teacher review instead of scoring them | 29 % of false negatives have incomplete grades | share of false negatives among incomplete records | proposal, not implemented |
| Re-run this script on real historical data and review the threshold each term | everything here uses synthetic students | all of them | needs institutional data |

## 5. What the model relies on

| Feature | Logistic coefficient | Effect of +1 standard deviation (logit) |
|---|---|---|
| average grade | −0.213 | **−3.11** |
| grade trend | +0.033 | +0.53 |
| attendance | −0.030 | −0.35 |
| participation | −0.018 | −0.30 |

The average grade carries almost all the weight. Higher attendance and participation lower the risk slightly; the sign of the
trend is an artefact of its correlation with the average (pattern 3).

## 6. Quality gate (CI)

`python scripts/evaluate_models.py --gate` trains the configured model from scratch, measures it on the independent set
and exits with code 1 if any condition fails, so that the pipeline stops and a worse model never reaches deployment:

| Condition | Threshold | Current value |
|---|---|---|
| recall | ≥ 0.60 | 0.734 |
| precision | ≥ 0.60 | 0.770 |
| F1 | ≥ 0.65 | 0.752 |
| accuracy, precision or recall | ≤ 0.99 | *a perfect score is rejected as suspicious (leakage, or classes that do not overlap)* |

The thresholds sit a little below what the models reach so that normal variation does not break the build but a real
regression does. The gate is tested (`tests/system/test_model_quality_gate.py`, `tests/unit/test_model_validation.py`).

## 7. Fairness audit (DR-3)

Subgroup: *turno* (evening / morning), a **synthetic** attribute built so that evening students attend about 7 points less for
the same engagement (see `data/README.md`). Chosen model, cut at 50:

| Shift | Students | False-positive rate (95 % interval) | False-negative rate (95 % interval) | Share flagged |
|---|---|---|---|---|
| Morning | 143 | 6.7 % (3.3–13.3) | **35.9 %** (22.7–51.6) | 22.4 % |
| Evening | 97 | **9.7 %** (4.8–18.7) | 12.0 % (4.2–30.0) | 29.9 % |
| Gap | | 3.0 points | 23.9 points | 7.5 points |

Evening students receive more false alarms and are flagged more often (30 % against 22 %); morning students who do end
at risk are missed far more often (36 % against 12 %). The direction fits the mechanism built into the data: lower attendance
pushes evening students towards a flag. **But the intervals of both rates overlap**: with 25 to 39 at-risk students per group
the audit cannot tell a real gap from chance, so the honest conclusion is *a possible disparity that this sample cannot confirm*,
not "the model is fair" and not "the model is biased". Larger samples and a repeat audit each term are the proposed follow-up (Milestone 4).

## 8. Limitations

- **Synthetic data.** The students, the labels and the subgroup are simulated. Every result describes this simulation.
- **The difficulty is a design choice.** The generator was calibrated so that a reasonable model is mostly right and visibly imperfect.
- **One independent sample of 240** gives wide intervals (section 2); differences of a few students between models are not evidence.
- **Cross-validation and evaluation come from the same simulated process**, which is more favourable than real data from a different term.
- The `metrics_on_holdout` field of `models/model_card.json` comes from a 120-student split of the training data
  (it is higher, 0.79 recall). **Do not quote it as performance**: this document is the validation.
- The model sees four numbers per student; it cannot know about events that are not recorded.

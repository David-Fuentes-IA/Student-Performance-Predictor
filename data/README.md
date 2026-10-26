# Evaluation dataset

`grupo_evaluacion.xlsx` is a fixed, reproducible group of **240 fictitious students** used to validate
the risk model (Milestone 3, Phase 5) and to demonstrate the application with a realistic class.
Nothing here is real student data.

## Structure (it is the import template, plus one sheet)

| Sheet | Content | Read by the import? |
|---|---|---|
| `Calificaciones` | one row per student: `matricula`, `nombre`, `parcial1..4`, `asistencia_pct`, `participacion` (44 students have fewer than 4 partial exams, as in a term in progress) | yes, validated like any real upload |
| `Instrucciones` | the template's instructions + two lines explaining this file | no |
| `Resultado_real` | `matricula`, `en_riesgo` (1 = the student ended the term with low performance), `turno` (synthetic subgroup for the fairness audit) | **no** |

The file can be imported as a group from the administration panel (`/admin`, "Crear grupo desde Excel"):
all 240 rows are accepted. `Resultado_real` is the ground truth a model must predict; it is what makes
accuracy, precision and recall computable.

## How the data are generated

One simulator, `data_access/synthetic_students.py`, feeds every synthetic dataset in the project
(training set, demo data in MongoDB, in-memory demo groups, this workbook). It is deterministic.

```
hidden traits                      what a teacher sees                     what happens
aptitude   ──────────────────────► partial exam grades ──┐
aptitude + engagement ───────────► participation         ├─ noisy features ─►  model
engagement (− evening penalty) ──► attendance            │
drift (grades rising or falling) ► grade trend ──────────┘
aptitude, engagement, drift ──────────────────────────────► outcome (at risk or not)
unobservable events: ~5 % crisis, ~4 % recovery ─────────────► outcome only
```

The earlier generator gave at-risk students numbers from one range and the rest from another, so the
classes did not overlap and every model scored 1.0, leaving nothing to analyse. Now the classes overlap
and part of the outcome depends on things the model cannot see, so some at-risk students look fine
(false negatives) and some fine students look at risk (false positives).

| | Training set | This workbook |
|---|---|---|
| Students | 600 (`seed 7`) | 240 (`seed 2026`) |
| Share at risk | ≈ 28 % | 26.7 % (64 students) |
| Seen by the model during training | yes | **no** (different seed, verified by a test) |

## Reproduce / verify

```bash
python scripts/build_evaluation_dataset.py          # rewrites data/grupo_evaluacion.xlsx
python scripts/build_evaluation_dataset.py --check  # fails if the committed file differs from the simulator
```

## What this dataset does and does not show

- It gives the validation work real material: with models trained on the generator, the Random Forest
  reaches about 86 % accuracy and 69 % recall on this workbook (20 false negatives, 13 false positives),
  not a perfect score.
- **The difficulty is a design choice.** The simulator's parameters were calibrated so that a reasonable model is
  right most of the time but clearly imperfect. That says nothing about how well the model would do on real
  students, and results must never be presented as evidence of real-world accuracy.
- `turno` is a **synthetic subgroup**. Evening students are simulated to attend about 7 points less for the same
  engagement (a plausible work-schedule effect), so a model that leans on attendance can flag them more
  often. It is a documented test scenario for the fairness audit (DR-3), not a statement about real students.
  With 72 evening and 104 morning students who did not end at risk, differences between the two groups
  are indicative, not statistically conclusive.

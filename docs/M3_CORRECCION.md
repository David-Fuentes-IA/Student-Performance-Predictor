# Milestone 3 report brief: Student Performance Predictor (Team 5)

> **For the assistant who writes the report.** This file gives you, in one place, everything needed for the Milestone 3
> written report and the documentation that goes with it: what was built, what was measured, the exact numbers and
> where each one comes from in the repository. You already have the team's design document (Milestone 2) and its
> context.
>
> **Rules for using this brief**
> 1. Write the report **in English**.
> 2. Use **only** the numbers in this brief. Every one of them was produced by a script in the repository and can be
>    regenerated. Do not round them differently from one section to another, and do not invent new ones.
> 3. Never present something as implemented when this brief lists it as *partial*, *design only* or *future work*.
>    The professor marked "implemented ≠ validated" as a Milestone 2 weakness.
> 4. All data are **synthetic**. Never write that the model works on real students.
> 5. Where a screenshot belongs, write `[SCREENSHOT: description]`; the team will add the images.
> 6. Use the course vocabulary (lessons 17–22): unit / integration / memory profiling / system testing; *software
>    testing evaluates the software, model validation evaluates the intelligence of the model*; CI/CD stages; image vs
>    container; desired vs actual state; *measure first, optimise the bottleneck*.
> 7. The repository is the source of truth. If this brief and the design document disagree, the brief describes the
>    code; section 4 lists the design-document corrections.

Repository: <https://github.com/David-Fuentes-IA/Student-Performance-Predictor>, branch **`milestone-3`** (not yet
merged into `main`). Team: Gabriel de Anda Romero, David Nava Fuentes, Marco Uriel Romero Hurtado, Axel Rubén López
Soto. Course: Software Engineering II, UAEMéx, professor M. en I. Jéssica Cortés. Previous grades: Milestone 1 29/40,
Milestone 2 33.6/40.

---

## 0. Rubric and where each criterion is answered

| # | Criterion (Milestone 3 report, 10 pts) | Pts | Brief section | Main evidence in the repo |
|---|---|---|---|---|
| 1 | Corrections of Milestone 2 with evidence | 1.0 | 3, 4, 5, 6 | this brief, commits in section 13 |
| 2 | Testing strategy: unit, integration, memory profiling, system testing, executed and interpreted | 2.0 | 7 | `docs/evidence/testing/` |
| 3 | Model validation (accuracy, precision, recall, F1) interpreted, plus error analysis | 2.0 | 8 | `docs/evidence/model/` |
| 4 | CI/CD: workflow evidence, each stage explained, how it makes the software reliable | 1.5 | 9 | `.github/workflows/ci.yml`, `docs/evidence/cicd/` |
| 5 | Docker plus deployment explanation; Kubernetes incorporated or justified | 1.5 | 10 | `Dockerfile`, `docker-compose.yml`, `k8s/`, `docs/evidence/docker/` |
| 6 | Scalability and performance: latency, throughput, resources, bottlenecks, justified optimisations | 1.5 | 11 | `docs/evidence/performance/` |
| 7 | Technical evidence consistent with the project | 0.5 | 12 | every `docs/evidence/*` folder |

Suggested report structure: one chapter per criterion, in this order, each ending with a short "interpretation" or
"what this means" paragraph. The professor rewards interpretation over raw numbers.

---

## 1. The system in one paragraph

A decision-support web application for teachers. From each student's partial-exam grades, attendance and
participation it estimates a **risk score (0–100)** of ending the term with low performance, classifies students into
three levels, explains why a student is on alert, and produces group and individual PDF reports. **It never acts on a
student by itself**: every alert is for a teacher to review (DR-2). One Flask application serves the teacher
dashboard (`/`) and the administration panel (`/admin`), backed by MongoDB (local container or the team's Atlas
cluster) or by in-memory demo data when no database is configured.

**Risk levels (the rule the application applies)**

| Level (UI label) | Rule |
|---|---|
| **Alto riesgo** (alert) | average grade **below 6.0** (60/100, a failing average, as schools define it) **or** model risk score ≥ 75 |
| En observación | model risk score ≥ 40 |
| Buen camino | everything else |

Both limits are configuration (`PASSING_GRADE=60`, `RISK_THRESHOLD=75`); every alert states its reason ("promedio
reprobatorio", "riesgo estimado ≥ 75" or both).

**Architecture (4 layers, dependency inversion)**

```
Presentation     webapp/ (Flask app factory: dashboard + admin blueprints) · templates/ · static/ · presentation/ (PDF, text)
Business logic   main_api.py: orchestrator and composition root
AI / prediction  data_pipeline/ (Fail-Fast validation, ETL, Excel import) · feature_store/ · inference_engine/ · learning_module/
Data access      data_access/: IAcademicDataRepository → MongoAcademicRepository | InMemoryAcademicRepository
core/            configuration, PII-safe logging, exceptions, Observer, risk levels
```

| Pattern | Where | Role |
|---|---|---|
| Strategy | `inference_engine/risk_predictor.py` | `IRiskPredictionEngine`: Random Forest and Logistic Regression engines are interchangeable; both predict one student or a whole group (`predict_many`) |
| Factory | `create_risk_engine`, `data_access/repository_factory.py` | configuration decides which engine / repository is built |
| Decorator | `inference_engine/cache_manager.py` | `CachingDecorator` (60 s TTL, keyed by the student's data, bounded to 10,000 entries) wraps `AuditDecorator` (engine, model version, latency, batch size per prediction) wraps the engine |
| Observer | `core/audit_observer.py` | `RiskEventPublisher` → `RiskAlertObserver` (alert with reason) and `ModelMonitoringObserver` (history); a failing observer never stops the report |
| Pipeline (ETL) | `data_pipeline/etl_processor.py` | extract → validate (Fail-Fast) → transform into feature vectors (no names) |
| Dependency inversion | `IAcademicDataRepository` | nothing outside `data_access/` depends on MongoDB |

**AI workflow per report** (`main_api.py`): validate request → *(authorise teacher: not implemented, no login)* → read
the group once → reject invalid records (Fail-Fast) → build feature vectors (ID, no name: DR-1) → predict the whole
group in one call → notify observers (alerts) → store all predictions in one batch (best effort, NFR-5) → render
dashboard / PDF / text.

---

## 2. Implementation status (implemented vs partial vs future)

Use this table for the "implemented vs future architecture" distinction the professor asked for (feedback point 6).
Map each row to the FR/NFR/DR identifiers of the design document, which you have.

| Component / requirement | Status | Where (file) | Evidence |
|---|---|---|---|
| Teacher dashboard: group selector, cards, level overview, per-exam averages, searchable/sortable table, alert reason, student card | **Implemented** | `templates/index.html`, `static/dashboard.js`, `webapp/dashboard.py` | system tests; smoke test |
| Group and individual PDF reports (with alert reason and level legend) | **Implemented** | `presentation/pdf_reports.py` | tests read the PDFs with `pypdf` |
| Text report endpoint `/api/v1/groups/<id>/risk-report` | **Implemented** | `webapp/dashboard.py`, `presentation/` | integration tests |
| Administration: groups and students CRUD, Excel import (partial / strict), template, demo data, database browser, import log | **Implemented** (a student's change history is stored and exposed by the API, but no screen shows it) | `webapp/admin.py`, `templates/admin.html`, `data_pipeline/` | integration tests against real MongoDB |
| Optional admin password (`ADMIN_PASSWORD`) | **Implemented** | admin blueprint | `AdminPasswordTests` |
| Teacher authentication, roles, HTTPS | **Future work** | — | — |
| MongoDB repository with JSON-Schema validators and unique indexes | **Implemented** | `data_access/mongo_repository.py`, `data_access/schema.py` | real-MongoDB tests |
| PostgreSQL + SQLAlchemy (design document) | **Not implemented, replaced** by MongoDB (section 5) | — | — |
| Two models (Random Forest, Logistic Regression) via Strategy + Factory; LR selected | **Implemented and validated** | `inference_engine/`, `learning_module/` | `docs/evidence/model/` |
| XGBoost (design document) | **Not used** | — | — |
| Model trained offline, persisted with a model card; `ModelLoadError` if missing or corrupt | **Implemented** | `learning_module/model_store.py`, `scripts/train_model.py`, `models/model_card.json` | startup-failure system tests |
| Prediction cache and audit trail (latency, model version) | **Implemented** | `inference_engine/cache_manager.py` | unit tests; cache measured in section 11 |
| Risk alerts | **Partial**: written to the log with reason; **not sent** to teachers (no e-mail/SMS) | `core/audit_observer.py` | integration tests |
| Observers in the design document: Notification Service, Compliance Audit Log, Retraining Scheduler, Teacher Dashboard as observer | **Not implemented** (only `RiskAlertObserver`, `ModelMonitoringObserver`) | — | — |
| Fail-Fast validation of records and configuration | **Implemented** | `data_pipeline/fail_fast_validator.py`, `core/config.py` | unit + system tests |
| NFR-1 (≤ 3 s per student, ≤ 10 s per group of 50, 10 concurrent sessions) | **Met and measured** | — | section 11 |
| NFR-5 (a failing secondary service does not stop the report) | **Implemented and tested** | `main_api.py`, `RiskEventPublisher` | `ComponentFailureTests` |
| DR-1 (no personal data in the AI layer or logs) | **Implemented** (`FeatureVector` has an ID, no name; `sanitize()` redacts name/email/CURP keys) | `feature_store/`, `core/logger.py` | test: no student name in any log line |
| DR-2 (human in the loop) | **By design**: the system only recommends; no automatic action exists | UI texts, alerts | — |
| DR-3 (bias audits) | **Implemented** as a fairness audit on a synthetic subgroup | `learning_module/model_validation.py` | section 8.6 |
| Model validation, error analysis, quality gate | **Implemented** | `scripts/evaluate_models.py` | section 8 |
| Docker image + compose, liveness `/health` and readiness `/ready` | **Implemented and drilled** | `Dockerfile`, `docker-compose.yml` | section 10 |
| CI/CD (GitHub Actions) | **Implemented, green** | `.github/workflows/ci.yml` | section 9 |
| Image publication to GitHub Container Registry | **Configured, not exercised** (runs only on `main`) | `deliver` job | — |
| Kubernetes manifests (Deployment, Service, ConfigMap, Secret template, HPA) | **Implemented, deployed in CI** (kind) | `k8s/` | section 10.4 |
| Autoscaling under real load | **Not verified** (kind has no metrics-server) | — | — |
| Vercel deployment | **Configuration present, not verified** | `api/index.py`, `vercel.json` | — |
| Real institutional data | **Future work** (all data synthetic) | — | — |

---

## 3. Corrections of Milestone 2 (criterion 1)

The professor's 8 feedback points, what was changed, and the proof.

| # | Feedback (Milestone 2) | What was done | Evidence |
|---|---|---|---|
| 1 | Do not confuse *implemented* with *validated*; show evidence that it works well | Every claim is now backed by a reproducible script and a results file: 288 automated tests, model validation on an independent set, failure drills, benchmark | `docs/evidence/` (all folders); CI runs it on every push |
| 2 | Show the cache's efficiency with measurements (with vs without) | Cold vs warm cache measured per request and for inference alone (section 11.5): inference ×27 faster with the cache, whole request −16 % to −36 % | `docs/evidence/performance/README.md` §5 |
| 3 | Justify Random Forest vs Logistic Regression with results | Stratified 5-fold CV + independent set + documented selection rule; result: a statistical **tie** on recall, LR chosen by a stated tie-break (steadier, simpler, interpretable) | `docs/evidence/model/README.md` §2–3 |
| 4 | Interpret the metrics, not only compute them | Each metric explained in plain words; confidence intervals; error analysis with 5 patterns; operating-point table; fairness audit | `docs/evidence/model/README.md` §2–7 |
| 5 | The technical manual cited `pytest tests/` but those tests did not exist | Test runner moved to pytest; 4-level suite (`tests/unit`, `integration`, `system`, `performance`) exists and passes; the command in the manual is now true | `docs/evidence/testing/`; commit `82285bb` |
| 6 | Distinguish what is implemented from the future architecture (synthetic data, memory) | Implementation-status table (section 2 of this brief); README section "Implemented and not implemented"; synthetic data stated everywhere | `README.md` §9–10, `data/README.md` |
| 7 | The user manual did not match the real interface | Manual to be rewritten from the unified application (section 14 of this brief gives the real UI) | — |
| 8 | Tests must be in the repository and reproducible | All tests versioned; one command regenerates each evidence folder; CI reruns everything on a clean Linux machine | `scripts/collect_test_evidence.py`, CI run #40241401044 |

Questions the professor asked in the Milestone 2 review, with the current answer:

| Question | Answer now |
|---|---|
| Where are PostgreSQL/SQLAlchemy actually used? | Nowhere: replaced by MongoDB (ADR, section 5) |
| How does the user choose the group? | A selector filled from `GET /api/groups` (real groups from the database); a group created in `/admin` appears without restarting |
| What happens if the model or a dependency fails? | Model missing/corrupt → the application refuses to start with `ModelLoadError` naming the fix. Model crashes during a request → HTTP 503 with a safe message, no traceback. Database down at start-up → refuses to start (no silent fake data). Database down while running → `/ready` 503, data requests 503 with a safe message, container stays alive. Observer or prediction store fails → report still produced (NFR-5). All tested |
| Show an error in the log | e.g. `RISK ALERT | group=… student_ref=… score=… reason=failing average + risk score at/above threshold -> for teacher review (not sent: notifications are not implemented)`, the AUDIT-TRAIL line per prediction, and the start-up error `MONGODB_URI is set but the database is unreachable at start-up…` (`docs/evidence/docker/startup_log.txt`) |
| Run the automated tests | `python -m pytest` (or `scripts/collect_test_evidence.py`); CI does it on every push |
| Full traceability requirement → diagram → code → execution → result | Section 2 table (requirement → file → evidence) plus the evidence folders |

Other defects found and fixed during this milestone (they are also corrections):

| Defect found | Fix |
|---|---|
| Two separate Flask apps (admin and dashboard) that did not share data; the dashboard invented 12 "Demo Student N" for any typed group ID | One application factory with two blueprints and a single repository; unknown group → 404; demo mode only shows 3 fixed demo groups with a visible banner |
| An unknown group answered 503 "try again" | 404 "group not found" (`GroupNotFoundError`) |
| The cache key was only the student ID → stale scores up to 60 s after an import | Key is the full feature vector |
| The model was retrained at every start | Trained offline, persisted, loaded (0.8 ms); `ModelLoadError` |
| All metrics were 1.0 (synthetic classes did not overlap) → no error analysis possible | Noisy simulator with hidden traits and unforeseeable events; fixed evaluation workbook of 240 students |
| One failing observer aborted the whole report (violated NFR-5) | Observers isolated; prediction store best effort |
| A text grade broke the whole group; `True` was accepted as grade 1 | Validator accepts only real numbers in range |
| "High risk" colours ignored the configured threshold | One definition of levels (`core/risk_levels.py`) |
| The alert rule (model score ≥ 75 alone) missed 36 of 64 at-risk students | School rule: failing average OR score ≥ 75 (recall 0.44 → 0.72) |
| `/health` waited 8 s for MongoDB, so Docker marked a healthy container `unhealthy` | Liveness `/health` bounded to 2 s; separate readiness `/ready` |
| Database down at start-up → silently served fake data until the next restart | Fail fast unless `ALLOW_DEMO_FALLBACK=true` |
| One database insert and one model call per student; group read 3 times per request | Batch insert, batch prediction, one read (section 11) |
| Code comments, log lines and documents that contradicted the behaviour: the alert log said "teacher and academic tutor notified" (nothing is sent), docstrings still described SQLAlchemy + PostgreSQL, `docs/DATABASE.md` listed admin routes without their `/admin` prefix and a history screen that does not exist, step 2 of the workflow was called "authorize" with no login | Rewritten to describe what the code does (commits `ff3b946`, `96fd0d0`) |
| Dead code: `generate_synthetic_data.py`, `risk_model.pkl`, `system_audit.log`, an unused Flask app in `main_api.py` | Removed |

---

## 4. Corrections to the design document (list for the team to apply)

| Design document says | Reality (code) | Proposed corrected text |
|---|---|---|
| PostgreSQL + SQLAlchemy | MongoDB (Atlas or local), `pymongo` | "Persistence uses MongoDB through the `IAcademicDataRepository` interface (see ADR)." |
| XGBoost as a candidate model | Not used | "Two candidates were evaluated: Random Forest and Logistic Regression." |
| Observers: Notification Service, Compliance Audit Log, Retraining Scheduler, Teacher Dashboard | Only `RiskAlertObserver` and `ModelMonitoringObserver` | "The prototype implements two observers (risk alert with reason, model monitoring history). Notification, compliance log and retraining scheduler are future work." |
| `AuditDecorator` records latency and model version | Now true | keep (it was false in M2, it is true now) |
| System Boundary Statement: the system does not train models | Training happens **offline** with `scripts/train_model.py`; the running application never trains | "Training is an offline step; the deployed application only loads a persisted model." |
| §11.1 `ModelLoadError` and loading a serialised model | Now true | keep |
| Fail-Fast matrix: the presentation layer validates the request | Group IDs are validated by pattern; records and configuration by `FailFastValidator` and `core/config.py` | state exactly that |
| Technical manual: `tests/` with Factory/Decorator/Orchestrator tests; template `dashboard.html` | Tests exist now (4 levels); the template is `index.html` | update |
| User manual: drop-down of groups, "View report" button | Group selector, *Ver detalle*, *↓ PDF*, *Descargar reporte del grupo* | rewrite from section 14 |
| High risk = model score ≥ threshold | High risk = average < 6.0 OR score ≥ 75 | update the risk-level definition |
| (If mentioned) the model card/metrics on a holdout as performance | The validation is the independent set (section 8) | quote section 8 numbers only |

---

## 5. ADR: PostgreSQL → MongoDB

- **Context.** The design specified PostgreSQL + SQLAlchemy. Groups have a variable number of partial exams, and the team
  needed one shared database without running a server.
- **Decision.** MongoDB: a free Atlas cluster shared by the team, a local `mongo:7` container for development, tests and
  Docker.
- **Why.** Documents fit a variable list of grades; Atlas free tier; no server to maintain.
- **Integrity.** Each collection has a **JSON-Schema validator** (`data_access/schema.py`, 6 collections) and **unique
  indexes** (group ID, student ID, group+student per record). Referential integrity (no foreign keys) is enforced in
  the repository: a record is written only if its group exists, deleting a group deletes its records.
- **Cost of the change.** Thanks to dependency inversion (`IAcademicDataRepository`), adopting MongoDB was **one new
  class**; the ETL, the engines, the observers and the presentation did not change.
- **What is lost.** Transactions across collections and database-level foreign keys; joins are done in code.
- **Security.** The connection string is only in `.env` / environment variables / a Kubernetes Secret, never in the
  repository; connection strings are redacted from logs.

---

## 6. Data used (all synthetic)

| Set | Size | Seed | At risk | Use |
|---|---|---|---|---|
| Training / cross-validation | 600 simulated students | 7 | 27.5 % | compare models, every decision |
| Independent evaluation | 240 students, `data/grupo_evaluacion.xlsx` (built on the team's import template) | 2026 | 26.7 % (64) | measure the chosen model **once** |
| Demo data seeded into MongoDB (Docker, `/admin` → Generar, `seed_demo_data.py`) | 3 groups, 100 students (301-A 34, 301-B 33, 301-C 33) | fixed | — | demonstration |
| Demo mode without a database | 3 in-memory groups of 12 students (301-A, 301-B, 301-C) | fixed | — | demonstration without MongoDB |

The simulator (`data_access/synthetic_students.py`) gives each student hidden traits (aptitude, engagement), noise and
unforeseeable events (5 % crisis, 4 % recovery) so that a reasonable model is mostly right and **visibly imperfect**.
A synthetic attribute *turno* (morning/evening, evening attends about 7 points less for the same engagement) exists
only to exercise the fairness audit. **No real student appears anywhere.** Features used: average grade, grade
trend (last minus first partial), attendance, participation.

---

## 7. Testing strategy (criterion 2)

Final run, 2026-10-25, Windows 10, Python 3.12.3, scikit-learn 1.9.1, MongoDB 7 in Docker, **strict mode** (any failure
or any skipped test fails the run):

| Level | Tests | Parametrised sub-cases | Failed | Skipped |
|---|---|---|---|---|
| Unit | 150 | 52 | 0 | 0 |
| Integration | 61 | 17 | 0 | 0 |
| System | 71 | 16 | 0 | 0 |
| Memory profiling | 6 | 0 | 0 | 0 |
| **Total** | **288** | **85** | **0** | **0** |

373 checks in total, all passing; 33 of the 288 tests run against a real MongoDB. **Statement coverage 94.3 %**
(feature_store 100, learning_module 98.4, inference_engine 98.2, presentation 98.1, data_pipeline 97.8, main_api 96.8,
webapp 96.6, core 96.3, data_access 84.4; the uncovered lines of data_access are mostly database-outage branches).
The same suite runs in CI on Linux. Local times are long (integration 108 s) only because each database test creates
a throw-away database and Docker's disk is on a mechanical drive (3.7 s per schema, measured); in CI the whole suite
takes 2 min 39 s.

**What each level verifies** (pick examples for the report)

- **Unit** ("does this component work correctly?"): validator boundaries 0/100, `None`, `NaN`, `inf`, text, `bool` rejected;
  feature extraction batch = single for 300 random students; Excel importer (template importable, accents, `"85,5"`,
  `"90%"`, empty file, PDF disguised as xlsx, truncated workbook, 1,001 rows, 11 kinds of invalid row reported by row
  number); Factory (unknown type, missing model, crash wrapped in a safe error); Decorators (hit/miss/expiry, key includes
  data, bounded, a cache hit does not reach the audit trail, batch = one-by-one, audit has one line per student); Observer
  (failing observer isolated); risk levels and the school rule; model store round trip / missing / corrupt; log
  redaction.
- **Integration** ("do they work together?"): repository → ETL → engine → observers → persistence → report; **no student
  name in any log line** (DR-1); invalid records skipped and the rest analysed; failing observer / failing store do not stop
  the report (NFR-5); database, model and unexpected failures reach the user as HTTP 503 with a safe message, never a
  traceback, host or path; Excel → MongoDB → dashboard (partial, strict, idempotent re-import, changed values update the
  risk); admin API CRUD, seeding, password protection; **one read, one batch write and one engine call per request**.
- **Memory profiling** (`tracemalloc`, not `sys.getsizeof`): feature extraction 1,000 students: plain loop 0.16 MiB / 8 ms vs
  pandas batch 0.30 MiB / 25 ms; 10,000 students: 1.53 MiB / 78 ms vs 2.88 MiB / 327 ms; model load 21.4 KiB peak, 9 ms;
  largest allowed Excel (1,000 rows) 0.93 MiB, 0.3 s; cache with 15,000 predictions stays bounded (5,000 kept, 3.88 MiB).
  *Interpretation:* memory grows linearly, nothing leaks; the pandas batch is **not** an optimisation at this size (2× memory,
  3–4× time) and is irrelevant in absolute terms; the cache's eviction is crude (drops everything non-expired when full).
- **System** ("does the whole system meet the requirements?"): teacher workflow on real MongoDB (create group → import 50
  students → selector → predictions within NFR-1 → students built to be at risk ranked higher → PDFs contain the on-screen
  data); a worse re-import raises the risk; empty group; Excel error catalogue (8 bad files, each with a meaningful message,
  nothing changed); start-up failures (missing model, corrupt model, invalid `RISK_THRESHOLD`/`PASSING_GRADE`, unreachable
  database) each stop the app with the cause and the fix; static guards on Dockerfile, CI workflow and Kubernetes manifests.

**Defects the tests found** (strong material for "interpreted"): see the table at the end of section 3 (observer aborting
the report, text grade breaking the group, stale cache, threshold ignored in colours, metrics at 1.0, `/health` blocking,
silent fake data).

---

## 8. Model validation and error analysis (criterion 3)

Positive class = *student at risk*. Decisions use cross-validation only; the independent set is measured once.

### 8.1 Results

| Model | Accuracy | Precision | Recall | F1 | F2 |
|---|---|---|---|---|---|
| Random Forest, 5-fold CV | 0.877 ± 0.015 | 0.822 ± 0.069 | 0.715 ± 0.082 | 0.760 ± 0.035 | 0.731 ± 0.063 |
| Logistic Regression, 5-fold CV | 0.888 ± 0.007 | 0.848 ± 0.067 | 0.733 ± 0.058 | 0.783 ± 0.010 | 0.752 ± 0.039 |
| Random Forest, independent set | 0.863 | 0.772 | 0.688 | 0.727 | 0.703 |
| **Logistic Regression, independent set** | **0.871** | **0.770** | **0.734** | **0.752** | 0.741 |

Confusion matrix, LR, independent set (cut at score 50): TN 162, FP 14, FN 17, TP 47. Random Forest: TN 163, FP 13, FN 20, TP 44.
95 % intervals (Wilson): recall 0.734 (47/64) → **0.62–0.83**; precision 0.770 (47/61) → **0.65–0.86**.

**Interpretation.** Accuracy (87 %) is the least informative: a model that flags nobody would already be 73 % accurate.
Precision 0.77: about 1 alert in 4 is a false alarm. Recall 0.73: it finds 73 % of the students who end up at risk and misses
27 %. Useful, clearly better than chance, clearly not perfect.

### 8.2 Which error matters, and the model choice

A false negative (a struggling student called "on track", no tutoring) is worse than a false positive (some teacher time,
possible stigma) → **recall is the priority metric**, precision must stay ≥ 0.60, F2 is the balanced summary. Selection
rule (CV only): highest mean recall with precision ≥ 0.60; models within one standard deviation are tied and the better F2
wins. **Outcome: Logistic Regression by tie-break, not a victory**: +0.018 recall with a fold standard deviation of
0.058–0.082. Reasons: at least as good on every averaged metric, steadier (F1 ± 0.010 vs ± 0.035), simpler and
inspectable. The independent set points the same way (17 vs 20 missed), but 3 students out of 64 are not evidence by
themselves. The choice is configuration (`RISK_MODEL`), recorded in the model card; a test fails if docs and code disagree.

### 8.3 Error analysis: 31 errors (12.9 %): 17 FN, 14 FP (all listed in `errors.csv`)

| Outcome | n | Avg grade | Trend | Attendance | Participation | Score | < 4 partials | Evening |
|---|---|---|---|---|---|---|---|---|
| TP | 47 | 50.9 | −7.3 | 74.6 | 60.0 | 80.6 | 11 % | 47 % |
| **FN (missed)** | 17 | 66.5 | −3.2 | 82.5 | 66.2 | 23.9 | 29 % | 18 % |
| **FP (false alarm)** | 14 | 57.9 | 0.0 | 70.0 | 55.3 | 72.9 | 21 % | 50 % |
| TN | 162 | 77.4 | −0.8 | 83.6 | 74.2 | 8.3 | 19 % | 40 % |

1. **Most errors are confident, not close calls**: only 26 % lie within ±15 of the cut (vs 8 % of correct predictions).
2. **Missed students do not look at risk**: attendance like the cleared students; e.g. `E0111` (average 66.4, attendance 96.2,
   grades rising +8.2, score 18.2) ended at risk. Nothing in the 4 features separates them, which is what unrecorded events
   (illness, work, family) would look like; the data cannot tell the cause.
3. **The model barely uses the grade trend**: +1 SD of average grade moves the logit by −3.11, trend only +0.53 (counter-
   intuitive sign because trend correlates with the average; not causal). Of 19 at-risk students whose grades fell ≥ 14
   points, 5 (26 %) were missed, the same as overall. `E0054` fell 28 points and scored 3.2.
4. **Low attendance + low grades trigger false alarms**: 10 of 14 FPs score ≥ 70; half are evening students. `E0059`
   (evening, average 56.8, attendance 60.5, grades +22.8) flagged at 87.9, did not end at risk.
5. **Fewer partial exams → missed more often**: 29 % of FNs have < 4 grades vs 11 % of TPs (5 of 17: an indication).

Likely causes: insufficient information (4 features, no life events), noise, minority class (27 %), small dataset (600),
synthetic data.

### 8.4 The alert rule: the largest gain

| Flag when score ≥ | Flagged | Precision | Recall (95 % CI) | Missed | False alarms |
|---|---|---|---|---|---|
| 75 (former alert rule) | 15 % | 0.800 | **0.438** (0.32–0.56) | 36 of 64 | 7 |
| 50 | 25 % | 0.770 | 0.734 (0.62–0.83) | 17 | 14 |
| 35 (best model-only point from CV, precision ≥ 0.70) | 30 % | 0.708 | 0.797 (0.68–0.88) | 13 | 21 |
| 15 (max F2, reference only) | 45 % | 0.528 | 0.891 | 7 | 51 |

**Decision taken: "Alto riesgo" = failing average (< 6.0) OR score ≥ 75.**

| Rule | CV recall (95 % CI) | CV precision | Independent recall (95 % CI) | Independent precision | Flagged |
|---|---|---|---|---|---|
| Score ≥ 75 alone (before) | 0.527 (0.45–0.60) | 0.897 | 0.438 (0.32–0.56) | 0.800 | 15 % |
| Failing average alone | 0.709 (0.64–0.77) | 0.812 | 0.719 (0.60–0.81) | 0.793 | 24 % |
| **Failing average OR score ≥ 75 (applied)** | **0.709** (0.64–0.77) | 0.807 | **0.719** (0.60–0.81) | 0.780 | 25 % |

46 of 64 at-risk students caught instead of 28, same precision; the intervals do not overlap, so the gain is real.
**Honest note that must appear:** with the model part at 75, almost all the gain comes from the school criterion; on the
independent set the model adds no extra correct alert to "failing average". The model's contribution today is the "En
observación" band and the ordering by risk. Lowering the model part would make it count (measured, **not applied**, team
decision pending): OR score ≥ 60 → independent recall 0.766 / precision 0.778; OR ≥ 50 → 0.781 / 0.746.

### 8.5 Proposed improvements

| Improvement | Status |
|---|---|
| School rule (above) | **applied** |
| Lower the model part of the rule to 50–60 | measured, not applied |
| Features for recent change (last grade, lowest grade, missing partials) | proposal, not implemented |
| Flag students with < 3 partials as "insufficient data" for teacher review | proposal, not implemented |
| Re-run the validation on real historical data each term | needs institutional data |

### 8.6 Fairness audit (DR-3), synthetic subgroup *turno*, LR cut at 50

| Shift | Students | False-positive rate (95 % CI) | False-negative rate (95 % CI) | Flagged |
|---|---|---|---|---|
| Morning | 143 | 6.7 % (3.3–13.3) | **35.9 %** (22.7–51.6) | 22.4 % |
| Evening | 97 | **9.7 %** (4.8–18.7) | 12.0 % (4.2–30.0) | 29.9 % |

Evening students get more false alarms and are flagged more; morning at-risk students are missed more. The direction fits
the mechanism built into the data, **but the intervals overlap**: "a possible disparity that this sample cannot confirm",
neither "fair" nor "biased". Follow-up for Milestone 4: larger samples, repeat the audit each term.

### 8.7 Quality gate in CI

`scripts/evaluate_models.py --gate` fails the pipeline if recall < 0.60, precision < 0.60, F1 < 0.65, or any of accuracy /
precision / recall > 0.99 (a perfect score is treated as suspicious: leakage or non-overlapping classes). Current values:
0.734 / 0.770 / 0.752.

Do **not** quote `metrics_on_holdout` from `models/model_card.json` (a 120-student split of the training data, 0.79 recall)
as performance; section 8 is the validation.

Figures available: `docs/evidence/model/confusion_matrices.png`, `cv_metrics.png`, `operating_points.png`.

---

## 9. CI/CD (criterion 4)

Tool: **GitHub Actions** (code already on GitHub, no server, free for public repos, MongoDB and Docker on the runners;
Jenkins needs its own server, GitLab would mean moving the repo, Azure DevOps fits Azure organisations). File:
`.github/workflows/ci.yml`. Triggered on every push and pull request.

```
Push → 1. Build → 2. Automated tests → 3. AI model validation → 4. Container → 4b. Kubernetes → 5. Deliver (main only)
```

Each stage `needs` the previous one: a failing stage stops the pipeline and nothing is delivered.

| Stage | What it checks | How it adds reliability |
|---|---|---|
| 1. Build | clean install from `requirements*.txt`, `ruff` lint, model trained from scratch, evaluation dataset matches its generator | the project builds from the repository alone ("works on my machine" eliminated) |
| 2. Automated tests | all 4 levels with coverage against a real, empty MongoDB service; **strict**: any failure or skipped test fails | the whole suite on every change; database tests cannot be silently skipped; reports kept as artefacts |
| 3. AI model validation | quality gate on the 240 unseen students | the **model**, not only the code, is checked; a worse (or suspiciously perfect) model blocks the pipeline |
| 4. Container | `docker compose up --build` + smoke test (15 checks) | the deployable artefact actually starts and serves |
| 4b. Kubernetes | throw-away kind cluster: apply manifests, rollout, smoke test through the Service, delete a Pod and wait for 2 ready replicas | manifests valid; probes, Secret and ConfigMap work together; self-healing shown |
| 5. Deliver | only on push to `main`: image to `ghcr.io` tagged with commit SHA and `latest` | only verified code becomes an image, traceable to its commit |

Safeguards: least-privilege permissions (only `deliver` can write packages, automatic `GITHUB_TOKEN`); no
`continue-on-error`; obsolete runs cancelled; Python 3.12 same as the image; the workflow itself is tested
(`tests/system/test_ci_workflow.py`). This is Continuous **Delivery**, not Continuous Deployment (no automatic server deploy).
Not configured: branch protection on `main` (owner-only setting, recommended).

**Runs (evidence):**

| Run | Commit | Result | Stage durations |
|---|---|---|---|
| [#40238753531](https://github.com/David-Fuentes-IA/Student-Performance-Predictor/actions/runs/40238753531) (first) | `cdfb5dd` | all green, deliver skipped (not main), total 6:04 | build 0:42, tests 3:24, gate 0:46, container 1:02 |
| [#40241401044](https://github.com/David-Fuentes-IA/Student-Performance-Predictor/actions/runs/40241401044) (with Kubernetes) | `c1f41f8` | all green, deliver skipped, total 7:51 | build 0:40, tests 2:39, gate 0:47, container 0:50, **kubernetes 2:44** |
| [#40261774028](https://github.com/David-Fuentes-IA/Student-Performance-Predictor/actions/runs/40261774028) (final consistency review) | `96fd0d0` | all green, deliver skipped | all six stages as above |

Artefacts per run: `trained-model`, `test-evidence`, `model-evidence`.
`[SCREENSHOT: GitHub Actions run #40241401044 with the six jobs]`, `[SCREENSHOT: CI badge in README]`.

---

## 10. Docker, deployment and Kubernetes (criterion 5)

### 10.1 Image and stack

- `Dockerfile`: multi-stage, `python:3.12-slim`, dependencies in their own layer, **model trained at build time** (the app
  never trains at start-up), runs as unprivileged user `app`, `HEALTHCHECK` on `/health`, gunicorn 2 workers × 4 threads,
  port 8000. `.dockerignore` keeps `.env`, `.git`, `venv`, `tests`, `docs` out (verified: none inside).
- `docker-compose.yml`: `app` + `mongo:7` with a named volume; the app starts only when MongoDB is healthy; configuration
  from environment; `restart: unless-stopped`. One command: `docker compose up --build` → http://localhost:8000.

| Measurement | Result |
|---|---|
| Build | 76.5 s cold (`--no-cache`), 11.3 s with cache |
| Image | 739 MB (`linux/amd64`, 9 layers); libraries 435 MB, Debian 88 MB, Python 46 MB, app code 0.8 MB, model < 1 KB |
| Start-up | healthy 11.2 s after `docker compose up -d` returns |
| Smoke test | 15/15 |
| Import of the 240-student workbook through the admin API | 240 created, 0 rejected; 58 high, 11 observation, 171 low |
| Persistence | after `down` + `up` (no `-v`) all groups still there (301-A 34, 301-B 33, 301-C 33, EVAL-240 240) |

### 10.2 Failure drills

- **A. MongoDB stops while running**: `/health` keeps answering 200 (`degraded`, within 2 s), `/ready` answers **503**, data
  API 503 with the safe message after 8.1 s (driver timeout, left as is by team decision), container **healthy in all 10
  samples over 92 s, 0 restarts**; after MongoDB returns, ready again in 6.0 s without restart. *Interpretation:* the
  container is alive (do not restart) but must not get traffic: exactly the liveness/readiness split.
- **B. Container starts with MongoDB down**: refuses to start (`MONGODB_URI is set but the database is unreachable at
  start-up…`), **no demo fallback, no fake data served**; Docker retries; real data served 6.0 s after MongoDB returns;
  smoke 15/15.

### 10.3 Deployment options (explanation)

| Option | Status |
|---|---|
| One machine (classroom/demo): `docker compose up --build` | implemented and tested |
| One faculty server: same compose on a Linux VM + HTTPS reverse proxy + Atlas or volume backups | compose/Atlas implemented; proxy, HTTPS, backups not configured |
| Image from a registry (GHCR, published by CI from `main`) | configured, not exercised yet (`milestone-3` is not merged) |
| Managed container platform (Cloud Run, Azure Container Apps, ECS) | design only |
| Kubernetes | manifests implemented, deployed in CI |

Needed before real use (not done): HTTPS, teacher authentication, managed secrets, backups, central logs, image
vulnerability scan.

### 10.4 Kubernetes (`k8s/`)

| Object | Decision and reason |
|---|---|
| Namespace `student-predictor` | groups every object |
| Deployment `spp-app`, **2 replicas**, rolling update `maxUnavailable 0`, `maxSurge 1` | one Pod can die or be replaced while the other serves (desired vs actual state) |
| `startupProbe` + `livenessProbe` on `/health`, `readinessProbe` on `/ready` | restart only if the process is dead; take out of the Service (not restart) if model/database are unavailable |
| requests 250m / 384 Mi, limits 1 CPU / 768 Mi | based on the measured 285–342 MiB under 10 users |
| Security: non-root (uid 999), read-only root filesystem, all capabilities dropped, seccomp RuntimeDefault; writable paths as `emptyDir` | same hardening as the image |
| ConfigMap `spp-config` (`RISK_THRESHOLD`, `PASSING_GRADE`, `SEED_DEMO "false"`), Secret `spp-secrets` (template with placeholders only; created with `kubectl create secret`) | configuration and secrets outside the image; the real URI is never in the repo |
| Service `spp-app` (port 80 → 8000) | stable address, spreads requests between Pods |
| HPA 2–6 Pods at 70 % CPU | CPU grows with load, memory is flat |
| `mongodb-dev.yaml` (StatefulSet + 1 Gi volume) | **development/CI only**; production database is Atlas |

**Justification (honest):** for **one faculty, Kubernetes is not needed**: one container serves ~200 requests/s and a group
of 50 in 76 ms at p95 with 10 users; compose with health check and restart policy is enough. Kubernetes is worth it for
the whole university (many faculties, peaks at the end of each evaluation period) or zero-downtime updates: replicas,
rolling updates, self-healing, autoscaling. Consequences at that scale: the prediction cache is **per Pod** (correct but
less effective; Redis would fix it, not needed now); MongoDB does not scale with the Pods (Atlas); logs in `emptyDir`
should go to a collector. **Verified in CI:** rollout, smoke test, self-healing (a deleted Pod is replaced). **Not
verified:** the HPA (kind has no metrics-server; checked statically only).

---

## 11. Scalability and performance (criterion 6)

Method (lessons 21–22): measure → find the bottleneck → optimise only the bottleneck → measure again.
Tool: `scripts/benchmark.py` (in-process stage timing against MongoDB + HTTP load against the container, `docker stats`).
Machine: Windows 10, 12 logical CPUs, Docker Desktop; container with gunicorn 2 × 4. Files:
`docs/evidence/performance/benchmark_baseline.json` (before, commit `d1c6b72`) and `benchmark_after.json`.

### 11.1 The four metrics, before → after

**Latency (HTTP p95, ms)**

| Request | Users | Before | After |
|---|---|---|---|
| Group of 50 | 1 | 52.5 | 32.3 (−38 %) |
| Group of 50 | 10 | 330.8 | **75.6 (−77 %)** |
| Group of 240 | 1 | 163.1 | 43.8 (−73 %) |
| Group PDF (50) | 1 | 142.4 | 110.2 (−23 %) |
| Student PDF | 1 | 67.6 | 42.6 (−37 %) |
| Student PDF | 10 | 374.7 | 185.3 (−51 %) |

**Throughput (requests/s):** group of 50, 1 user 23.4 → 40.8 (×1.7); **10 users 46.5 → 201.7 (×4.3)**; group of 240
7.3 → 32.4 (×4.4); student PDF, 10 users 36.4 → 83.6 (×2.3).

**Resources (container, 10 users):** CPU max 336 % → 242 % of one core (after: only 2 samples, indicative); memory
342 → 285 MiB.

**Availability:** 0 failed requests out of 550 in each run; recovery covered by the Docker drills and the Kubernetes
self-healing check.

**NFR-1** (≤ 10 s per group of 50, ≤ 3 s per student, 10 concurrent sessions): met before (331 ms) and now with about
two orders of magnitude of margin (76 ms).

### 11.2 Bottleneck (baseline, median per stage of one request, cold cache)

| Stage | 50 students | 240 students | Calls per request |
|---|---|---|---|
| Store predictions in MongoDB | 31.5 ms (**55.5 %**) | 147.7 ms (**60.4 %**) | one insert **per student** |
| Model inference | 14.5 ms (25.6 %) | 67.9 ms (27.8 %) | one model call **per student** |
| Load group | 7.7 ms (13.6 %) | 16.5 ms (6.8 %) | **3 reads** of the same group |
| Everything else | 3.0 ms (5.3 %) | 11.6 ms (4.7 %) | |
| Total p50 | 56.7 ms | 244.4 ms | |

Same kind of defect three times: N round trips where one is enough. Measured separately, predicting 240 students one by
one costs 25.3 ms (LR) / 1,428 ms (RF); one batch call 0.21 ms / 6.9 ms (**×119 / ×206**). Start-up: training at start
76 ms (LR) / 164 ms (RF) vs loading 0.8 ms / 17 ms.

### 11.3 Optimisations (bottleneck → change → metric → evidence)

| Bottleneck | Optimisation | Pattern kept | Metric that improved |
|---|---|---|---|
| one insert per student | `save_predictions` with one `insert_many(ordered=False)` | Repository | store stage 148 → 46 ms (240 students) |
| one model call per student | `predict_many`: whole group in one `predict_proba`; the cache sends only missing students; audit still one line per student | Strategy + Decorator | inference 14.5 → 3.0 ms (50, cold) |
| group read 3 times | `ETLProcessor.process(group)`: read once, pass down | ETL pipeline | load 7.7 → 2.8 ms (50) |
| training at start-up (earlier phase) | train offline, load persisted model | — | start 76 ms → 0.8 ms |

Not optimised on purpose: validation, observers, PDF rendering, JSON (each < 5 %). Tests lock the properties in
(`RequestEfficiencyTests`, `BatchPredictionTests`, `PredictionPersistenceTests`).

### 11.4 After: where the time goes

Request total p50: **50 students 56.7 → 9.6 ms (6×)**, **240 students 244.4 → 75.9 ms (3.2×)**. For 50 there is no
dominant stage any more (inference 31 %, read 29 %, store 15 %). For 240, storing is still 60 % (46 ms), now limited by
MongoDB writing 240 documents, not by round trips. Next step would be a background write-behind queue; **not
implemented** because 76 ms is far below NFR-1 and it adds a failure mode (predictions lost if the process dies).
In-process figures are higher than HTTP ones (Windows host → Docker port vs container → container, plus timers):
compare before/after inside each table, not across tables.

### 11.5 Cache with vs without (professor's point 2)

| | Before (per-student calls) | After (batch) |
|---|---|---|
| Inference only, 50, cold → warm | 14.5 → 4.8 ms (×3.0) | 3.0 → 0.1 ms (×27) |
| Whole request, 50, cold → warm | 56.7 → 47.9 ms (−16 %) | 9.6 → 6.2 ms (−36 %) |
| Whole request, 240, cold → warm | 244.4 → 197.3 ms (−19 %) | 75.9 → 63.9 ms (−16 %) |

The cache does what it promises for inference, but inference was never most of the request, so its effect on the whole
request is moderate. Kept because it is cheap (bounded, 60 s TTL) and would matter more with a slower model.

### 11.6 Optimisation levels (lesson 22)

Algorithm/code: vectorised batch inference · Data access: batch insert, one read per request · Caching: prediction cache,
5 s cache of the database check in `/health` · Start-up: persisted model · Infrastructure: gunicorn 2 × 4, Kubernetes
2 replicas + HPA to 6.

Limitations: one laptop, one run each (noise of a few %; conclusions rely on ×1.7 or more); local MongoDB, not Atlas
(network latency would make the round-trip savings larger, not measured); load up to 10 users (the NFR target), not a
stress test to breaking point.

---

## 12. Evidence index (criterion 7)

| Evidence | Path | Regenerate with |
|---|---|---|
| Test results per level, coverage, memory profile | `docs/evidence/testing/` (`summary.json`, `pytest_*.txt`, `coverage.txt`, `memory_profile.json`) | `python scripts/collect_test_evidence.py --strict` |
| Model metrics, confusion matrices, figures, every error | `docs/evidence/model/` (`metrics.json`, `comparison.md`, 3 PNG, `errors.csv`) | `python scripts/evaluate_models.py` |
| Evaluation dataset | `data/grupo_evaluacion.xlsx`, `data/README.md` | `python scripts/build_evaluation_dataset.py --check` |
| Docker image, start-up log, smoke test, drills | `docs/evidence/docker/` (`summary.json`, `startup_log.txt`, `smoke_test.txt`, `image_layers.txt`, `compose_ps.txt`) | `python scripts/collect_docker_evidence.py` |
| CI/CD workflow and runs | `.github/workflows/ci.yml`, `docs/evidence/cicd/README.md` | every push |
| Performance before/after | `docs/evidence/performance/` (2 JSON + README) | `python scripts/benchmark.py --label after` |
| Kubernetes manifests and justification | `k8s/*.yaml`, `k8s/README.md` | CI job `kubernetes` |
| Configuration template | `.env.example` (safe defaults, no secrets) | — |

Suggested screenshots: dashboard with a group loaded and an alert tooltip; student card; group PDF; admin import result
with rejected rows; `/health` and `/ready` JSON; terminal with `pytest` summary; GitHub Actions run; `docker compose ps`
healthy; `kubectl get pods` (from CI log); `operating_points.png` and `confusion_matrices.png`.

---

## 13. Commit trail of this milestone (branch `milestone-3`)

| Commit | Content |
|---|---|
| `2253f07` | unify admin panel and dashboard into one Flask app with one repository |
| `fbc1f21` | clean dead files, batch feature extraction in ETL, pytest, deterministic lint |
| `0562cb8` | persisted model with `ModelLoadError`, configurable threshold, richer audit trail |
| `3d66f94`, `21048ce` | "high risk" follows the configured threshold; one definition of levels |
| `6f84fa9` | isolate observer and persistence failures (NFR-5); validator rejects non-numeric values |
| `82285bb` | 4-level test suite with reproducible evidence |
| `a10f13e` | noisy generator and fixed evaluation workbook |
| `6cc1b97` | model validation, error analysis, fairness, quality gate |
| `379694a` | Docker image, compose, liveness/readiness, fail-fast start-up |
| `cf8e946` | school rule for "Alto riesgo", README rewritten |
| `cdfb5dd`, `d1c6b72` | CI/CD pipeline and its first run |
| `c1f41f8` | performance (batch storage, batch prediction, one read) and Kubernetes |
| `f0c4877`, `3971f7a` | CI run with Kubernetes; final regenerated evidence |
| `2bf6723` | this brief; stale counts in the testing evidence corrected |
| `ff3b946`, `96fd0d0` and the commit that adds this file | code and documents made consistent with the behaviour (alerts not sent, MongoDB instead of SQLAlchemy, real admin routes, no teacher login) |

---

## 14. Facts for rewriting the manuals

**Technical manual** (replace the M2 one):
- Requirements: Docker Desktop (option A) or Python 3.12 (option B). Option A: `git clone …`, `git checkout milestone-3`,
  `docker compose up --build`, open http://localhost:8000 and /admin.
- Option B: `python -m venv venv` → `venv\Scripts\python.exe -m pip install -r requirements-dev.txt` →
  `venv\Scripts\python.exe scripts/train_model.py` (writes `models/risk_model.joblib`, not in git, and `model_card.json`) →
  choose data mode (demo: nothing; local MongoDB: `docker run -d --name spp-mongo -p 27018:27017 mongo:7` and
  `MONGODB_URI=mongodb://localhost:27018` in `.env`; Atlas: its URI in `.env`, see `docs/DATABASE.md`) →
  `venv\Scripts\python.exe web_app.py` → http://127.0.0.1:5000 (`admin_app.py` serves the same app on 5001).
- If `MONGODB_URI` is set but MongoDB is down, the app refuses to start (clear message); `ALLOW_DEMO_FALLBACK=true` only for development.
- Configuration: `MONGODB_URI`, `MONGODB_DB` (`student_predictor`), `ALLOW_DEMO_FALLBACK` (false), `ADMIN_PASSWORD` (empty =
  open), `PASSING_GRADE` (60), `RISK_THRESHOLD` (75), `RISK_MODEL` (`logistic_regression`), `MODEL_DIR` (`models/`). Invalid
  values stop the start-up naming the variable.
- Endpoints: `/`, `/admin`; `GET /api/groups`, `GET /api/groups/<id>`; `GET /reports/groups/<id>.pdf`,
  `GET /reports/groups/<id>/students/<student>.pdf`; `GET /api/v1/groups/<id>/risk-report`; `GET /health` (liveness, always
  200); `GET /ready` (readiness, 503 without model or database).
- Tests: `python -m pytest` (database tests need `MONGODB_TEST_URI=mongodb://localhost:27018`), `python -m pytest --cov`,
  `python -m ruff check .`. Scripts listed in section 12. Console demo: `python main_api.py`.
- Project structure: `webapp/`, `templates/` (`index.html`, `admin.html`), `static/`, `presentation/`, `core/`,
  `data_access/`, `data_pipeline/`, `feature_store/`, `learning_module/`, `inference_engine/`, `models/`, `data/`,
  `scripts/`, `tests/{unit,integration,system,performance}`, `docs/`, `k8s/`, `Dockerfile`, `docker-compose.yml`.

**User manual** (the real interface, labels in Spanish as shown on screen):
- Dashboard (`/`): choose the group in the **selector**; **↻ Actualizar** re-reads data (new groups appear without
  restarting). Cards: students, average grade, average attendance, **students on alert** ("Promedio < 6 o riesgo ≥ 75").
  *Panorama del grupo*: students per level, click a level to filter. *Calificaciones por registro*: group average per
  partial. Table: search by name or ID, filter by level, sort by risk, grade or name; **⚠ Alerta** marks high-risk students
  and hovering shows why. *Ver detalle* opens the **student card**; **↓ PDF** downloads the individual report;
  **Descargar reporte del grupo** downloads the whole group (even with filters). In demo mode a yellow banner says so and
  administration is disabled.
- Administration (`/admin`, link "Administrar grupos"): create/delete groups; add, update (save again with the same ID) and
  delete students; **Crear grupo desde Excel** / import with *parcial* (keep valid rows, report the rest with row numbers) or
  *estricto* (nothing imported if any row is invalid); **Descargar plantilla**; *Datos de prueba* → Generar / regenerate /
  remove; database browser; latest imports; optional password.
- How to read the result: the risk score is the model's estimate (0–100), **not a grade**; levels as in section 1; every
  alert is a recommendation for the teacher to review; nothing is sent automatically.

---

## 15. Inputs for Milestone 4 (ethics, bias, privacy, legal), to prepare now

Milestone 4 forbids new features, so these are facts about what already exists.

- **DR-1 in the code:** `FeatureVector` carries an ID (`student_ref`) but no name; `core/logger.py` `sanitize()` redacts
  `name`, `student_name`, `full_name`, `email`, `curp`; a test checks no student name reaches any log line. **But** the
  student ID (matrícula) does appear in AUDIT-TRAIL and RISK ALERT log lines and in the `predictions` collection
  (`student_ref`, score, label, timestamp); names appear, by design, on the dashboard and PDFs for the teacher. There is no
  retention period or deletion policy for predictions and logs (gap to discuss).
- **Alerts are not sent to anyone:** they are logged (`-> for teacher review (not sent: notifications are not implemented)`)
  and shown on the dashboard with their reason. (Corrected in `ff3b946`: the log line used to say "teacher and academic
  tutor notified".)
- **Bias sources:** synthetic data and labels; proxy variables (attendance penalises evening students in the simulation:
  more false alarms for them, more misses for morning students; not statistically confirmed); a fixed threshold;
  students with fewer partials missed more often; the model barely uses the trend.
- **Human oversight (DR-2) that exists:** the system only recommends; each alert states its reason; the teacher sees the
  data behind the score; thresholds are configurable and visible in the legend. **Missing:** teacher login and roles, a way
  to record the teacher's decision/override, notification, appeal by the student.
- **Accessibility facts:** dashboard has `aria-label`s on the logo and close button, `role="status"` / `aria-live` for
  notices, `role="alert"` for errors, a native `<dialog>` for the student card, `aria-busy` while loading; colour plus text
  labels for levels. A contrast and keyboard-navigation review has **not** been done.
- **Security facts:** no secrets in the repository (`.env` ignored, Secret template with placeholders); `/admin` open unless
  `ADMIN_PASSWORD`; no HTTPS or authentication; container non-root, read-only filesystem in Kubernetes.
- **Legal framework (verified by web search on 2026-10-25; confirm the official texts before citing):**
  - Federal: on **20 March 2025** the DOF published a new *Ley General de Protección de Datos Personales en Posesión de
    Sujetos Obligados* (public bodies), together with a new *Ley General de Transparencia* and a new *Ley Federal de
    Protección de Datos Personales en Posesión de los Particulares*. The **INAI was extinguished**; its functions passed to
    the *Secretaría Anticorrupción y Buen Gobierno* (SABG) and its body *Transparencia para el Pueblo*. Sources:
    Cuatrecasas (<https://www.cuatrecasas.com/es/latam/gobierno-corporativo-compliance/art/nuevas-leyesmateriatransparencia-proteccion-datos-personales>),
    EY (<https://www.ey.com/es_mx/technical/tax/boletines-fiscales/nueva-ley-federal-proteccion-datos-personal-posesion-particulares>),
    IAPP (<https://iapp.org/news/a/se-establece-una-nueva-autoridad-en-materia-de-protecci-n-de-datos-personales-en-m-xico>),
    official text: <https://www.diputados.gob.mx/LeyesBiblio/pdf/LGPDPPSO.pdf>.
  - Estado de México (UAEMéx is a public autonomous university of the State, therefore a *sujeto obligado*): according to
    press reports, **Decreto 365** extinguished the **INFOEM**, created **Transparencia Mexiquense** (a body of the State
    Comptroller's office) and issued a new *Ley de Protección de Datos Personales en Posesión de Sujetos Obligados del
    Estado de México y Municipios*. Sources: El Universal Edomex
    (<https://www.eluniversaledomex.com.mx/gobierno/edomex-extingue-al-infoem-y-crea-transparencia-mexiquense/>), La Jornada
    Estado de México (<https://lajornadaestadodemexico.com/publican-nueva-ley-de-transparencia-en-edomex-extinguen-infoem-y-crean-transparencia-mexiquense/>).
    **The official decree and its entry-into-force date were not checked**: look them up in the *Gaceta del Gobierno* before
    citing. Do not cite the 2017 state law as current.
  - Students' academic records are personal data; grades plus an automated risk score may be considered a
    profiling decision: discuss consent/notice (*aviso de privacidad*), purpose limitation and human review.

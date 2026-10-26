# Brief for writing the TECHNICAL MANUAL: Student Performance Predictor (Team 5)

> **For the assistant who writes the manual.** Write a **technical manual for developers and for whoever installs and
> operates the system**. Everything below was checked against the repository (commands, paths, variables, endpoints,
> numbers). Use only this material; do not invent components, commands or options.
>
> **Rules**
> 1. Write in **English**. Commands in code blocks, one command per block.
> 2. The professor criticised the Milestone 2 manual because it cited a `pytest tests/` command whose tests did not exist,
>    a template called `dashboard.html` (it is `index.html`) and tests of Factory/Decorators/Orchestrator that were not
>    there. **Every command and path here exists and was run.** Do not add others.
> 3. Distinguish **implemented / partial / not implemented** (section 15). Never present future work as done.
> 4. All data are **synthetic**; the model is a demonstration model. Never claim accuracy on real students.
> 5. Put `[DIAGRAM: ...]` where a diagram belongs; section 3 gives the content (the team's design document has the
>    original figures, which you already have).
> 6. Suggested chapter order: overview, architecture, requirements and installation, configuration, running, data model,
>    API, model lifecycle, testing, CI/CD, containers and Kubernetes, operations and troubleshooting, security and privacy,
>    extending the system, limitations.

Repository: <https://github.com/David-Fuentes-IA/Student-Performance-Predictor>, branch **`milestone-3`** (not yet merged
into `main`). Python **3.12**. Windows commands use `venv\Scripts\python.exe`; macOS/Linux use `venv/bin/python`.

---

## 1. Overview

A Flask web application that estimates, for each student of a group, a risk score (0–100) from four features, shows it in
a teacher dashboard, produces PDF reports, and lets an administrator manage groups and import Excel files. One process
serves both the dashboard (`/`) and the administration panel (`/admin`). Data live in MongoDB (a local container or
Atlas) or, without a database, in three fixed in-memory demo groups. The model is trained **offline** and loaded at
start-up; the application never trains.

**Risk levels (`core/risk_levels.py`)**: high risk = average grade `< PASSING_GRADE` (60) **or** model score `>= RISK_THRESHOLD`
(75); observation = score `>= 40`; otherwise low. Each alert records its reason (`failing_average`, `high_predicted_risk`).

## 2. Technology stack

| Concern | Choice |
|---|---|
| Language / web | Python 3.12, Flask ≥ 3.0 (application factory + blueprints), gunicorn in containers |
| ML | scikit-learn ≥ 1.4 (Random Forest, Logistic Regression), pandas/numpy, joblib |
| Database | MongoDB 7 via pymongo ≥ 4.6 (+ dnspython for `mongodb+srv://`); **not** PostgreSQL/SQLAlchemy |
| Import / export | openpyxl (Excel), reportlab (PDF) |
| Config | environment variables / `.env` (python-dotenv) |
| Tests | pytest, pytest-cov, ruff, pypdf, matplotlib (`requirements-dev.txt`) |
| Packaging | Docker (multi-stage), docker compose, Kubernetes manifests |
| CI/CD | GitHub Actions |

## 3. Architecture

```
Presentation     webapp/ (create_app: dashboard + admin blueprints) · templates/ · static/ · presentation/ (PDF, text)
     │
Business logic   main_api.py: orchestrator and composition root (_bootstrap wires everything once)
     │
AI / prediction  data_pipeline/ (Fail-Fast validation, ETL, Excel import) · feature_store/ · inference_engine/ · learning_module/
     │
Data access      data_access/: IAcademicDataRepository → MongoAcademicRepository | InMemoryAcademicRepository
core/            configuration, PII-safe logging, exceptions, Observer, risk levels (used by every layer)
```

Dependency inversion: nothing outside `data_access/` depends on MongoDB; the rest uses `IAcademicDataRepository`. Adopting
MongoDB instead of the design document's PostgreSQL required one new class (`MongoAcademicRepository`) and the factory.

### 3.1 Design patterns (where and why)

| Pattern | File | Notes |
|---|---|---|
| Strategy | `inference_engine/risk_predictor.py` | `IRiskPredictionEngine` with `predict_risk` and `predict_many` (whole group in one call); `RandomForestRiskEngine` and `LogisticRegressionRiskEngine` share `_ProbabilisticRiskEngine` |
| Factory | `create_risk_engine` (same file), `data_access/repository_factory.py` | engine type string → class; `MONGODB_URI` → repository |
| Decorator | `inference_engine/cache_manager.py` | `CachingDecorator` (60 s TTL, key = the student's feature data, max 10,000 entries) → `AuditDecorator` (logs engine, model version, latency, batch size, one `AUDIT-TRAIL` line per student) → engine. A cache hit never reaches the audit |
| Observer | `core/audit_observer.py` | `RiskEventPublisher` → `RiskAlertObserver` (logs `RISK ALERT` with reason) and `ModelMonitoringObserver` (in-memory history); a failing observer is isolated and logged (NFR-5) |
| Pipeline (ETL) | `data_pipeline/etl_processor.py` | `process(group)`: validate (Fail-Fast) → extract features in batch; `process_group(id)` reads then processes |
| Repository / DIP | `data_access/student_repository.py` | interface + in-memory implementation; `save_predictions` (batch) has a default loop that MongoDB overrides with `insert_many` |

### 3.2 Request flow (`main_api._run_risk_workflow`, shared by dashboard, PDFs and text report)
1. validate the request (group ID; a requester must be named: **placeholder**, there is no teacher login);
2. read the group **once**; 3. Fail-Fast validation of each record (invalid ones are skipped and logged) and feature
extraction (`average_grade`, `grade_trend` = last − first, `attendance_pct`, `participation_score`; **no name**, DR-1);
4. `predict_many` through the decorators; 5. publish one `RiskEvent` per student; 6. `save_predictions` in one batch
(best effort: a failure is logged, the report still returns); 7. build the response, re-attaching names only in the
presentation layer.

### 3.3 Modules
`core/` config.py, logger.py, exception_handler.py, risk_levels.py, audit_observer.py · `data_access/` mongo_connection.py,
mongo_repository.py, schema.py, repository_factory.py, student_repository.py, synthetic_students.py · `data_pipeline/`
fail_fast_validator.py, etl_processor.py, excel_importer.py, group_import_service.py, synthetic_seed.py · `feature_store/`
feature_manager.py · `inference_engine/` risk_predictor.py, cache_manager.py · `learning_module/` model_trainer.py,
training_pipeline.py, model_store.py, model_evaluator.py, model_validation.py, evaluation_data.py · `presentation/`
pdf_reports.py, report_data.py, teacher_report_ui.py · `webapp/` `__init__.py` (create_app), dashboard.py, admin.py ·
`web_app.py` (port 5000) and `admin_app.py` (port 5001): thin wrappers that start the same application ·
`api/index.py` + `vercel.json` (Vercel entry, **not verified**).

## 4. Requirements and installation

**Requirements:** Git; either Docker Desktop (option A) or Python 3.12 (option B). Docker is optional in option B (only for
a local MongoDB).

### Option A: Docker (recommended)
```bash
git clone https://github.com/David-Fuentes-IA/Student-Performance-Predictor.git
cd Student-Performance-Predictor
git checkout milestone-3
docker compose up --build
```
Dashboard http://localhost:8000, administration http://localhost:8000/admin. First build ≈ 1–2 minutes (measured 76.5 s
cold, 11 s cached; image 739 MB). `docker compose down` keeps the data; `docker compose down -v` deletes it.

### Option B: Python
```powershell
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements-dev.txt
venv\Scripts\python.exe scripts/train_model.py
venv\Scripts\python.exe web_app.py
```
`requirements.txt` alone is enough to run; `requirements-dev.txt` adds the testing tools. `train_model.py` writes
`models/risk_model.joblib` (**not in git**) and `models/model_card.json` (versioned); options `--model {random_forest,logistic_regression}`
and `--out-dir`. The application at http://127.0.0.1:5000 (`/admin` for administration; `admin_app.py` serves the same app on 5001).

Choose the data source:

| Mode | Setup | Result |
|---|---|---|
| Demo (no database) | `MONGODB_URI` empty | 3 in-memory groups (301-A/B/C, 12 students each), banner "Modo demo", administration disabled |
| Local MongoDB | `docker run -d --name spp-mongo -p 27018:27017 mongo:7` and `MONGODB_URI=mongodb://localhost:27018` in `.env` (copy `.env.example`) | full functionality |
| MongoDB Atlas | the Atlas connection string in `.env` (`docs/DATABASE.md`: free M0 cluster, database user, network access, URL-encode special characters in the password) | same, shared database |

Load data: `/admin` → **Datos de prueba** → **Generar**, or:
```powershell
venv\Scripts\python.exe scripts/seed_demo_data.py
```
(`--count N`, `--reset`, `--purge`; only data marked `synthetic` is touched). Realistic group: import
`data/grupo_evaluacion.xlsx` (240 students). **The real connection string is only ever in `.env`/environment variables,
never in code, logs, commits or documents.**

## 5. Configuration (all read at start-up; an invalid value stops the app naming the variable)

| Variable | Default | Effect |
|---|---|---|
| `MONGODB_URI` | empty (demo mode) | MongoDB connection string |
| `MONGODB_DB` | `student_predictor` | database name |
| `ALLOW_DEMO_FALLBACK` | `false` | development only: if `MONGODB_URI` is set but the database is unreachable at start-up, run on demo data instead of stopping |
| `ADMIN_PASSWORD` | empty (open) | password for the administration API (header `X-Admin-Password`) |
| `PASSING_GRADE` | `60` | average below which a student is failing → high risk (0–100) |
| `RISK_THRESHOLD` | `75` | model score from which a student is high risk (0–100) |
| `RISK_MODEL` | `logistic_regression` | which model `scripts/train_model.py` trains (`random_forest` or `logistic_regression`); an invalid value is rejected with a message. The running application does **not** read it: it builds the engine from the `engine_type` stored in `models/model_card.json` |
| `MODEL_DIR` | `models/` | folder with `risk_model.joblib` and `model_card.json` |
| `DOCKER_MONGODB_URI`, `APP_PORT`, `SEED_DEMO` | compose's MongoDB, `8000`, `true` | Docker only. A separate variable from `MONGODB_URI` on purpose: `localhost` inside a container is the container |

`.env.example` documents every variable and is safe by default (`MONGODB_URI` empty). `.env` is git-ignored.

## 6. Data model (MongoDB; `data_access/schema.py`, created idempotently at start)

```
groups            { group_id (unique), name, period, teacher, source, created_at }
students          { student_id (unique), name, created_at, updated_at }       ← identity (the only place with names)
academic_records  { group_id, student_id, grades[], attendance_pct, participation_score, source, created_at, updated_at }   ← unique (group_id, student_id)
record_history    { group_id, student_id, grades[], attendance_pct, participation_score, source, created_at }              ← snapshot per change
predictions       { student_ref, risk_score, risk_label, recorded_at }        ← no name
import_logs       { group_id, filename, mode, total_rows, created, updated, unchanged, rejected_count, status, created_at } ← metadata only
```
Each collection has a `$jsonSchema` validator and the unique indexes above (6 collections, 8 indexes). Referential
integrity (no foreign keys) is kept in the repository: a record is written only if its group exists; deleting a group deletes
its records and history, and students left orphaned. Validators are applied with `collMod` where the tier allows it.
`source` is `excel`, `manual` or `synthetic`. Limits: group ID `^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$`, student ID ≤ 32, name ≤ 120,
grades/attendance/participation 0–100, 1–4 partial grades with no gaps, Excel ≤ 1,000 rows and 4 MB.

## 7. HTTP API

Dashboard and reports (public; **no authentication**):

| Method and path | Purpose |
|---|---|
| `GET /` | dashboard page |
| `GET /api/groups` | list of groups `[{group_id, name, student_count…}]` |
| `GET /api/groups/<id>` | predictions of a group (JSON: `students`, `summary`, `passing_grade`, `risk_threshold`, `risk_levels`) |
| `GET /reports/groups/<id>.pdf`, `GET /reports/groups/<id>/students/<student>.pdf` | PDF reports |
| `GET /api/v1/groups/<id>/risk-report` | plain-text report inside JSON |
| `GET /health` | **liveness**: process alive; always 200; reports `{"status":"ok"\|"degraded","mode","model_loaded","database"}`; the database check is bounded to 2 s and cached 5 s |
| `GET /ready` | **readiness**: 200 `{"ready":true,...}` or **503** if the model or the database is unavailable (demo mode counts as ready) |

Administration (`/admin`, API under `/admin/api`; protected by `ADMIN_PASSWORD` when set, except the three public routes):

| Method and path | Purpose |
|---|---|
| `GET /admin/` | administration page |
| `GET /admin/api/health`, `GET /admin/api/auth-required`, `GET /admin/api/template.xlsx` | public |
| `GET /admin/api/stats` | document count per collection |
| `GET, POST /admin/api/groups` | list / create groups |
| `DELETE /admin/api/groups/<g>` | delete a group and its data |
| `GET, POST, DELETE /admin/api/groups/<g>/students` | list / add or update one student / remove all students |
| `DELETE /admin/api/groups/<g>/students/<s>` | remove one student |
| `GET /admin/api/groups/<g>/students/<s>/history` | change history of a student |
| `POST /admin/api/groups/<g>/import` | import Excel (`multipart`: `file`, `mode` = `partial`\|`strict`, optional `create_group`) |
| `GET /admin/api/imports` | recent imports |
| `POST, DELETE /admin/api/seed` | create / remove synthetic data (`count` 1–500) |
| `GET /admin/api/collections/<name>` | read-only browser (only the 6 known collections; others → 400) |

Error contract: failures return JSON `{"error": "<safe message>"}` with 400 (invalid input), 401 (admin password), 404
(unknown group or student: `GroupNotFoundError`/`NotFoundError`) or 503 (database/model/unexpected). **Never** a
traceback, host name or file path; internal detail goes only to the log. The JSON and PDF responses of the dashboard carry `Cache-Control: no-store`.

## 8. Model lifecycle

- **Features (4):** `average_grade`, `grade_trend` (last − first partial), `attendance_pct`, `participation_score`.
- **Train:** `scripts/train_model.py` → `learning_module/training_pipeline.py`: 600 simulated students (seed 7), stratified
  80/20 split, fit, persist with joblib, write `models/model_card.json` (`model_version` e.g. `logistic_regression-seed7-n600`,
  `engine_type`, hyperparameters, features, data description, library version, `metrics_on_holdout`).
  **Do not quote `metrics_on_holdout` as performance**; the validation is below.
- **Load:** `learning_module/model_store.py::load_model` at start-up. Missing, corrupt or invalid artifacts raise
  `ModelLoadError` and the application **refuses to start**, with a message ending in ``Run `python scripts/train_model.py` to generate it.`` (the fix command is part of the error). No silent retraining.
- **Select the model type:** `RISK_MODEL` or `--model` **when training**; the application then serves whatever the card's `engine_type` says (to switch models, train the other one and restart).
- **Validate:** `python scripts/evaluate_models.py` (rewrites `docs/evidence/model/`): stratified 5-fold cross-validation
  on the 600, then one measurement on the independent 240 (`data/grupo_evaluacion.xlsx`, seed 2026). Chosen model:
  **Logistic Regression** (statistical tie with Random Forest on recall; tie-break: steadier, simpler, interpretable).
  Independent set: accuracy 0.871, precision 0.770, recall 0.734, F1 0.752 (recall 95 % interval 0.62–0.83).
- **Quality gate:** `python scripts/evaluate_models.py --gate` exits 1 if recall < 0.60, precision < 0.60, F1 < 0.65, or any
  metric > 0.99 (perfect scores are suspicious).
- **Application rule:** failing average OR score ≥ 75 catches 46 of 64 at-risk students (recall 0.72) vs 28 with the score
  alone (0.44). With the model part at 75 almost all the gain comes from the average-grade criterion (documented honestly).
- **Fairness audit:** by a synthetic subgroup (`turno`); gaps exist but confidence intervals overlap (cannot be confirmed).
- Details and error analysis: `docs/evidence/model/README.md`. Data origin: `data/README.md`.

## 9. Testing

| Command | What it does |
|---|---|
| `venv\Scripts\python.exe -m pytest` | everything; the 33 tests that need a real MongoDB are skipped unless `MONGODB_TEST_URI` is set |
| `venv\Scripts\python.exe -m pytest tests/unit` | one level (`unit`, `integration`, `system`, `performance`) |
| `venv\Scripts\python.exe -m pytest --cov -q` | with coverage |
| `venv\Scripts\python.exe -m ruff check .` | static analysis |

Database tests (each creates and drops its own throw-away database, so a development container is safe):
```powershell
docker run -d --name spp-mongo-test -p 27018:27017 mongo:7
$env:MONGODB_TEST_URI="mongodb://localhost:27018"
venv\Scripts\python.exe -m pytest
```
`mongomock` is **not** used (it does not support schema validators); tests use a real MongoDB. `tests/conftest.py` clears
`MONGODB_URI`, `RISK_THRESHOLD`, `PASSING_GRADE`, `RISK_MODEL`, `ALLOW_DEMO_FALLBACK` and `ADMIN_PASSWORD` so a developer's
`.env` cannot leak into tests.

**Final run (strict, 2026-10-25):** unit 150 (+52 sub-cases), integration 61 (+17), system 71 (+16), memory profiling 6;
**288 tests, 85 sub-cases, 0 failed, 0 skipped; coverage 94.3 %** (feature_store 100, learning_module 98.4, inference_engine
98.2, presentation 98.1, data_pipeline 97.8, main_api 96.8, webapp 96.6, core 96.3, data_access 84.4). Local integration/
system times are long because each database test creates a schema (≈ 3.7 s on a mechanical disk); CI runs the whole suite
in 2 min 39 s.

Test layout: `tests/unit/` (validator, features, Excel importer, factory/decorators/batch, observer, risk levels, config,
model store, model validation, repositories, synthetic data) · `tests/integration/` (pipeline flow and failures between
components, dashboard routes and levels, admin API on MongoDB, Excel→MongoDB→dashboard, health/readiness, unified app) ·
`tests/system/` (teacher workflow, Excel error catalogue, start-up failures, threshold end to end, quality gate, evaluation
workbook import, static guards for the Dockerfile, the CI workflow and the Kubernetes manifests) · `tests/performance/`
(`tracemalloc` memory profile). Regenerate the evidence folder: `python scripts/collect_test_evidence.py [--strict]`.

## 10. CI/CD (`.github/workflows/ci.yml`, GitHub Actions; on every push and pull request)

`1. Build` (install, ruff, train, dataset check) → `2. Automated tests` (all levels, coverage, real MongoDB service, strict)
→ `3. AI model validation` (quality gate) → `4. Container` (compose up, smoke test, 15 checks) → `4b. Kubernetes` (kind cluster:
rollout, smoke test, delete a Pod and wait for 2 ready replicas) → `5. Deliver` (publish image to `ghcr.io` with commit SHA
and `latest` tags; **only on push to `main`**). Each stage `needs` the previous: a failure stops the pipeline. Least
privilege (only `deliver` can write packages), no `continue-on-error`, obsolete runs cancelled, same Python as the image.
Latest verified run: all stages green (#40261774028; Kubernetes run #40241401044: 7 min 51 s). Not configured: branch
protection on `main` (owner-only setting). Details: `docs/evidence/cicd/README.md`.

## 11. Containers and Kubernetes

**Dockerfile** (multi-stage `python:3.12-slim`): builder installs dependencies into `/opt/venv` (own cached layer); runtime
copies the venv and the code (filtered by `.dockerignore`: no `.env`, `.git`, `venv`, tests, docs), **trains the model at build
time**, strips CRLF from the entrypoint, runs as unprivileged user `app`, `HEALTHCHECK` on `/health` (30 s), exposes 8000, starts
`gunicorn --bind 0.0.0.0:8000 --workers 2 --threads 4 --timeout 60 "webapp:create_app()"`. `docker/entrypoint.sh` seeds demo
data when `SEED_DEMO=true` and `MONGODB_URI` is set, then `exec`s the command (gunicorn is PID 1 and receives SIGTERM).
**docker-compose.yml:** `mongo:7` (volume `mongo_data`, healthcheck) and `app` (starts only when MongoDB is healthy;
`restart: unless-stopped`; env from `.env`).

Useful commands:
```bash
docker compose ps
```
```bash
docker compose logs -f app
```
```bash
python scripts/smoke_test.py http://localhost:8000
```
Measured: healthy ≈ 11 s after `up`; smoke test 15/15; image 739 MB. Evidence and failure drills: `docs/evidence/docker/README.md`.

**Kubernetes (`k8s/`):** `namespace.yaml`; `app.yaml` (ConfigMap `spp-config`; Deployment `spp-app` with **2 replicas**, rolling
update `maxUnavailable 0`/`maxSurge 1`, `startupProbe` + `livenessProbe` on `/health`, `readinessProbe` on `/ready`, requests
250m/384Mi, limits 1 CPU/768Mi, non-root uid 999, read-only root filesystem, capabilities dropped, seccomp RuntimeDefault, `emptyDir`
for `/app/logs`, `/app/.gunicorn`, `/tmp`; Service `spp-app` 80→8000; HPA 2–6 Pods at 70 % CPU); `secret.example.yaml`
(**template with placeholders only**); `mongodb-dev.yaml` (StatefulSet, **development and CI only**).
```bash
kubectl apply -f k8s/namespace.yaml
```
```bash
kubectl -n student-predictor create secret generic spp-secrets --from-literal=MONGODB_URI='<your URI>' --from-literal=ADMIN_PASSWORD='<password>'
```
```bash
kubectl apply -f k8s/app.yaml
```
Verified in CI (kind): rollout, smoke test through the Service, self-healing. **Not verified:** the HPA (kind has no
metrics-server). Honest justification (`k8s/README.md`): for one faculty Docker/compose is enough; Kubernetes pays off
for many faculties, peaks and zero-downtime updates. Consequences: the prediction cache is per Pod; MongoDB does not scale with
the Pods (use Atlas).

## 12. Performance (`docs/evidence/performance/`)

Measured with `python scripts/benchmark.py` (before: `benchmark_baseline.json`, after: `benchmark_after.json`). Bottleneck: one
insert and one model call per student and three reads of the group per request (55–74 % of the request was storing
predictions). Fixes: `save_predictions` (`insert_many`), `predict_many`, one read (`ETLProcessor.process(group)`).
Group of 50, 10 concurrent users: p95 **331 → 76 ms**, throughput **46.5 → 201.7 req/s**; group of 240, 1 user p95 163 → 44 ms;
container memory 342 → 285 MiB; 0 errors out of 550 requests. NFR-1 (≤ 10 s per group of 50, ≤ 3 s per student, 10 sessions)
met with two orders of magnitude of margin. Batch prediction is ×119 (LR) / ×206 (RF) faster than one call per student.
Cache cold→warm: inference ×27, whole request −16 % to −36 %. Next step not implemented: background write of predictions.

## 13. Operations and troubleshooting

**Logs:** console and `logs/spp_YYYYMMDD.log` (console only on read-only filesystems such as Vercel). Format
`time | level | logger | message`. Names are never logged; student IDs are. Useful lines: `AUDIT-TRAIL | engine=… model_version=…
student_ref=… score=… latency_ms=… batch=N`, `RISK ALERT | group=… student_ref=… score=… reason=…` (alerts are only logged, not
sent), `Cache hit for N of M students`, `Model loaded from … (version …)`.

| Symptom | Cause | Fix |
|---|---|---|
| App refuses to start: "required model artifact not found" / "could not be loaded (corrupt files)" | `models/risk_model.joblib` missing or invalid | `python scripts/train_model.py` (Docker trains at build) |
| App refuses to start: "MONGODB_URI is set but the database is unreachable at start-up…" | database down or wrong URI | start MongoDB / fix the URI; or empty `MONGODB_URI` for demo mode; `ALLOW_DEMO_FALLBACK=true` for development only |
| App refuses to start naming a variable | invalid `PASSING_GRADE` or `RISK_THRESHOLD` (also `RISK_MODEL` when training) | use a number 0–100 / a valid model name |
| Yellow "Modo demo" banner, administration disabled | `MONGODB_URI` empty | set it in `.env`, restart |
| Data requests answer 503 after ≈ 8 s | database stopped while running (driver server-selection timeout; left as is) | restore the database; the container stays alive and `/ready` returns 503 meanwhile; no restart needed |
| Container `unhealthy` | `/health` failing (process problem, not the database) | `docker compose logs app` |
| Atlas connection fails | IP not allowed, bad password characters | allow the IP in *Network Access*; URL-encode `@ : / ?` in the password |
| Old scores after an import | none: the cache key includes the student's data | — |
| `docker compose` build fails with "read-only file system" | host disk full (Docker's virtual disk) | free space; a previous incident on this project |
| Database tests skipped | `MONGODB_TEST_URI` not set | set it (section 9) |
| Windows: `gunicorn` not installed | POSIX-only, skipped on Windows by design | use `python web_app.py`, or Docker |
| PowerShell blocks `Activate.ps1` | execution policy | call `venv\Scripts\python.exe` directly |

Probes: use `/health` for liveness and `/ready` for readiness. With the database down, `/health` stays 200 (`degraded`) and
`/ready` is 503: restarting a healthy process cannot fix a database.

## 14. Security and privacy (facts, for the manual's security section)
- **DR-1:** `FeatureVector` carries an ID, never a name; `core/logger.py::sanitize` redacts the keys `name`, `student_name`,
  `full_name`, `email`, `curp`; a test asserts no student name reaches any log line. Student IDs do appear in the audit/alert logs and in
  `predictions`. Names appear on the dashboard and in PDFs (for the teacher). No retention policy for logs/predictions exists.
- **Secrets:** only in `.env`/environment/Kubernetes Secret; connection strings are redacted in logs; the repository history has no
  real URI; `.env` and `*.joblib` are git-ignored.
- **Access control:** dashboard has **no authentication**; `/admin` is open unless `ADMIN_PASSWORD` is set (the password travels in a
  header: use HTTPS in any shared deployment, which the project does not provide). Admin routes return 401 without it.
- **Input safety:** Excel files are validated (extension, size 4 MB, 1,000 rows, per-row rules); group IDs are pattern-checked; the
  database browser only allows the 6 known collections; responses never expose internals.
- **Containers:** non-root user, read-only filesystem and dropped capabilities in Kubernetes.
- DR-2 (human in the loop): the system only recommends. Not done and needed before real use: HTTPS, teacher authentication and roles,
  recording the teacher's decision, notifications, backups, central logs, image vulnerability scan.

## 15. Implemented vs not implemented

| Implemented | Partial | Not implemented / future |
|---|---|---|
| dashboard, PDFs, text report; administration, Excel import, demo data; MongoDB + in-memory repositories; two models, validation, quality gate; offline training and `ModelLoadError`; cache + audit; observers (alert, monitoring); Fail-Fast validation; health/readiness; Docker, compose, CI/CD, Kubernetes manifests (deployed in CI); benchmarks | alerts are logged, not sent; change history stored and exposed by the API but shown in no screen; image publication to GHCR configured but not exercised (only on `main`); Vercel entry present, not verified; drift monitoring history is in memory | teacher login/roles, HTTPS, e-mail/SMS notifications, the design's Notification Service, Compliance Audit Log and Retraining Scheduler observers, XGBoost, PostgreSQL/SQLAlchemy, real institutional data, shared cache between replicas, autoscaling verified under load |

## 16. How to extend (what the code supports)
- **New model type:** add a class derived from `_ProbabilisticRiskEngine` in `inference_engine/risk_predictor.py`, register it in
  `create_risk_engine`, add the name to `MODEL_TYPES` in `core/config.py`, make `learning_module/model_trainer.py` able to build it, train
  (`--model`), validate (`evaluate_models.py`), and add tests. The orchestrator and decorators do not change.
- **New data source:** implement `IAcademicDataRepository` (`get_student`, `get_group`, `save_prediction`, `list_groups`; override
  `save_predictions` to batch) and select it in `data_access/repository_factory.py`.
- **New observer (for example a real notification):** subclass `RiskObserver`, attach it in `main_api._bootstrap`; failures are already isolated.
- **Change the risk rule:** `core/risk_levels.py` is the single definition; thresholds are configuration. Re-run `evaluate_models.py`
  and update the evidence.
- **New Excel column:** `data_pipeline/excel_importer.py` (`TEMPLATE_COLUMNS`, header aliases) and the schema validator.

## 17. Script reference (`scripts/`)
`train_model.py` (train and persist) · `evaluate_models.py` (validation, `--gate`) · `build_evaluation_dataset.py` (`--check`) ·
`seed_demo_data.py` (`--count --reset --purge`) · `smoke_test.py <url>` (15 end-to-end checks) · `benchmark.py` (performance) ·
`collect_test_evidence.py` (`--strict`) · `collect_docker_evidence.py` (`--cold`, runs `docker compose down -v` first) ·
`memory_profile.py` · `migrate_local_to_atlas.py` (copies the demo students from a local MongoDB to Atlas; `--dry-run`).

## 18. Where to find the evidence
`docs/evidence/testing/`, `model/`, `docker/`, `cicd/`, `performance/` (each with a README that interprets the numbers), `k8s/README.md`,
`data/README.md`, `docs/DATABASE.md` (MongoDB/Atlas set-up, in Spanish), `docs/M3_CORRECCION.md` (full Milestone 3 report material).

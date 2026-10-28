# Student Performance Predictor

[![CI/CD](https://github.com/David-Fuentes-IA/Student-Performance-Predictor/actions/workflows/ci.yml/badge.svg?branch=milestone-3)](https://github.com/David-Fuentes-IA/Student-Performance-Predictor/actions/workflows/ci.yml)

**Team 5, Software Engineering II (UAEMéx)**: Gabriel de Anda Romero · David Nava Fuentes · Marco Uriel Romero Hurtado ·
Axel Rubén López Soto

A decision-support prototype for teachers. From each student's partial-exam grades, attendance and participation it
estimates the risk (0–100) of ending the term with low performance, marks the students who need attention and produces
reports. **It never acts on a student by itself**: every alert is for a teacher to review (DR-2).
All the data in this repository are synthetic; no real student appears anywhere.

> Current work lives on the branch `milestone-3`. Evidence for the Milestone 3 report:
> [testing](docs/evidence/testing/README.md) · [model validation](docs/evidence/model/README.md) ·
> [containers and deployment](docs/evidence/docker/README.md) · [CI/CD](docs/evidence/cicd/README.md) ·
> [performance](docs/evidence/performance/README.md) · [Kubernetes](k8s/README.md) · [evaluation dataset](data/README.md)
>
> New to the code? Read [docs/CODE_STRUCTURE.md](docs/CODE_STRUCTURE.md): what each folder does and where to change what (en español: [docs/ESTRUCTURA_DEL_CODIGO.md](docs/ESTRUCTURA_DEL_CODIGO.md)).

---

## 1. Getting started

Pick **one** of the two options. Option A needs nothing but Docker; option B runs the code directly with Python.

### Option A: Docker (one command)

Requirements: Git and [Docker Desktop](https://www.docker.com/products/docker-desktop/) running.

```bash
git clone https://github.com/David-Fuentes-IA/Student-Performance-Predictor.git
cd Student-Performance-Predictor
git checkout milestone-3          # until it is merged into main
docker compose up --build
```

Open **http://localhost:8000** (dashboard) and **http://localhost:8000/admin** (administration).
The first run builds the image (about 1–2 minutes), trains the model inside it, starts a private MongoDB and creates three
demo groups (100 synthetic students). Stop with `Ctrl+C`; `docker compose down` keeps the data, `docker compose down -v` deletes it.

### Option B: Python on your machine

Requirements: Git and **Python 3.12** (the tested version; the Docker image uses it too). Docker Desktop is optional and
only needed for a local MongoDB.

**1. Get the code**

```bash
git clone https://github.com/David-Fuentes-IA/Student-Performance-Predictor.git
cd Student-Performance-Predictor
git checkout milestone-3
```

**2. Create a virtual environment and install the dependencies**

Windows (PowerShell):

```powershell
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

macOS / Linux:

```bash
python3 -m venv venv
venv/bin/python -m pip install -r requirements-dev.txt
```

`requirements-dev.txt` installs the application plus the testing tools; `requirements.txt` alone is enough to run it.
The commands below call the environment's Python directly (`venv\Scripts\python.exe` on Windows, `venv/bin/python` elsewhere),
so activating it is optional. If PowerShell blocks `Activate.ps1`, simply keep using `venv\Scripts\python.exe`.

**3. Train the model (once)**

```bash
venv\Scripts\python.exe scripts/train_model.py
```

This writes `models/risk_model.joblib` (not stored in git) and `models/model_card.json`. The application never trains when it
starts; if the model file is missing it stops with a `ModelLoadError` that names this command.

**4. Choose where the data come from**

| Mode | What to do | What you get |
|---|---|---|
| **Demo** (no database) | nothing | three in-memory groups (301-A, 301-B, 301-C), a yellow "Modo demo" banner, the administration panel disabled |
| **Local MongoDB** (recommended) | `docker run -d --name spp-mongo -p 27018:27017 mongo:7`, then copy `.env.example` to `.env` and set `MONGODB_URI=mongodb://localhost:27018` | everything, including groups, students and Excel import |
| **MongoDB Atlas** (shared team database) | copy `.env.example` to `.env` and set `MONGODB_URI` to the Atlas connection string ([docs/DATABASE.md](docs/DATABASE.md)) | the same, on the shared database |

Copying the file: `copy .env.example .env` (Windows) or `cp .env.example .env` (macOS/Linux).

**5. Start the application**

```bash
venv\Scripts\python.exe web_app.py
```

Open **http://127.0.0.1:5000**; the administration panel is at **/admin**. (`admin_app.py` serves the same application on port 5001.)
Keep the terminal open; `Ctrl+C` stops it.

**6. Load data** (database modes)

- In `/admin` → *Datos de prueba* → **Generar**, or from the terminal: `venv\Scripts\python.exe scripts/seed_demo_data.py`
  (`--count N`, `--reset`, `--purge`; only data marked `synthetic` is ever touched).
- To try a realistic class of 240 students: `/admin` → *Crear grupo desde Excel* with `data/grupo_evaluacion.xlsx`.
- For your own data: *Descargar plantilla*, fill it in and import it.

**Next time**: `docker start spp-mongo` (if you use it), then `venv\Scripts\python.exe web_app.py`.

> If `MONGODB_URI` is set but MongoDB is not running, the application **refuses to start** with a clear message rather than
> showing fake students. Start the database, or empty `MONGODB_URI` to use demo mode.

A console version of the whole pipeline, without a web server: `venv\Scripts\python.exe main_api.py` (text report of the first
group plus the model's metrics).

---

## 2. Using the application

**Dashboard** (`/`)

- Choose the group in the selector; **↻ Actualizar** re-reads the data (new groups created in `/admin` appear without restarting).
- Cards: students, average grade, average attendance and **students on alert**.
- *Panorama del grupo*: number of students per level; click a level to filter the table.
- *Calificaciones por registro*: group average for each partial exam.
- Student table: search by name or ID, filter by level, sort by risk, grade or name. **⚠ Alerta** marks high-risk students; hovering
  shows why. *Ver detalle* opens the student's card; **↓ PDF** downloads the individual report, *Descargar reporte del grupo* the group
  report (always the whole group, even with filters on).

**Risk levels**

| Level | Rule |
|---|---|
| **Alto riesgo** (and alert) | average grade **below 6.0** (60/100, a failing average) **or** model risk score ≥ 75 |
| En observación | model risk score ≥ 40 |
| Buen camino | everything else |

The *risk score* is the model's estimate (0–100) that the student ends the term with low performance; it is **not** a grade.
Both limits are configurable (`PASSING_GRADE`, `RISK_THRESHOLD`). Every alert is written to the log with its reason;
sending it to the teacher by e-mail or SMS is future work.

**Administration** (`/admin`): create and delete groups; add, update (save again with the same ID) and delete students; import
Excel (*partial* mode keeps the valid rows and reports the rest, *strict* mode imports nothing if any row is invalid); download the
template; create, regenerate or remove demo data; browse the database; see the latest imports. Optional password: `ADMIN_PASSWORD`.

**Endpoints**

| Path | Purpose |
|---|---|
| `/`, `/admin` | dashboard, administration |
| `GET /api/groups`, `GET /api/groups/<id>` | groups; one group's predictions (JSON) |
| `GET /reports/groups/<id>.pdf`, `GET /reports/groups/<id>/students/<student>.pdf` | PDF reports |
| `GET /api/v1/groups/<id>/risk-report` | the report as plain text, inside a JSON response |
| `GET /health` | liveness: is the process alive? (always 200, never blocked by the database) |
| `GET /ready` | readiness: can it serve requests? (503 without the model or the database) |

---

## 3. Configuration

Environment variables or a `.env` file (template: [.env.example](.env.example)). They are read at start-up, and an invalid value
stops the application with a message naming the variable.

| Variable | Default | Effect |
|---|---|---|
| `MONGODB_URI` | empty (demo mode) | MongoDB connection string |
| `MONGODB_DB` | `student_predictor` | database name |
| `ALLOW_DEMO_FALLBACK` | `false` | development only: run on demo data when MongoDB is configured but down |
| `ADMIN_PASSWORD` | empty (open) | password for `/admin` |
| `PASSING_GRADE` | `60` | average below which a student is failing, hence high risk (0–100) |
| `RISK_THRESHOLD` | `75` | model score from which a student is high risk (0–100) |
| `RISK_MODEL` | `logistic_regression` | model trained by `scripts/train_model.py` (`random_forest` is the alternative) |
| `MODEL_DIR` | `models/` | where the trained model lives |
| `DOCKER_MONGODB_URI`, `APP_PORT`, `SEED_DEMO` | compose's MongoDB, `8000`, `true` | Docker only, see [docs/evidence/docker](docs/evidence/docker/README.md) |

---

## 4. Tests and evidence

```bash
venv\Scripts\python.exe -m pytest                 # everything; tests that need a real MongoDB are skipped
venv\Scripts\python.exe -m pytest tests/unit      # one level: unit, integration, system, performance
venv\Scripts\python.exe -m pytest --cov           # with coverage
venv\Scripts\python.exe -m ruff check .           # static analysis
```

To include the tests that need a real MongoDB, point `MONGODB_TEST_URI` at one (each test creates and drops its own throw-away
database, so the local container above is safe to use):

```powershell
$env:MONGODB_TEST_URI="mongodb://localhost:27018"; venv\Scripts\python.exe -m pytest
```

| Command | Regenerates |
|---|---|
| `python scripts/collect_test_evidence.py` | `docs/evidence/testing/`: results per level, coverage, memory profile |
| `python scripts/evaluate_models.py` | `docs/evidence/model/`: cross-validation, confusion matrices, error list, fairness audit |
| `python scripts/evaluate_models.py --gate` | quality gate: fails if recall, precision or F1 fall below their minimum |
| `python scripts/collect_docker_evidence.py` | `docs/evidence/docker/`: image, start-up, persistence and failure drills |
| `python scripts/benchmark.py` | `docs/evidence/performance/`: latency, throughput, container resources, time per stage |
| `python scripts/smoke_test.py http://localhost:8000` | end-to-end check of a running instance |
| `python scripts/build_evaluation_dataset.py --check` | verifies `data/grupo_evaluacion.xlsx` against the simulator |

Every push runs all of this automatically on GitHub (`.github/workflows/ci.yml`): build and lint, the whole test suite against a
real MongoDB, the model quality gate, the container smoke test, and a deployment to a throw-away Kubernetes cluster (kind), in
that order; a failing stage stops the pipeline. Pushes to `main` then publish the image to GitHub Container Registry. Details:
[docs/evidence/cicd](docs/evidence/cicd/README.md), [k8s/README.md](k8s/README.md).

Performance (10 concurrent users, group of 50): p95 76 ms, about 200 requests per second from one container, against a
requirement of 10 s. How it was measured, the bottleneck found and the optimisations:
[docs/evidence/performance](docs/evidence/performance/README.md).

---

## 5. Model

Two candidates, **Random Forest** and **Logistic Regression**, over four features: average grade, grade trend (last minus first
partial), attendance and participation. Stratified 5-fold cross-validation on 600 simulated students finds them statistically tied
on recall, the priority metric (a missed at-risk student is the costly error); **Logistic Regression** is used, as a documented
tie-break. Measured once on 240 students it never saw (`data/grupo_evaluacion.xlsx`): accuracy 0.871, precision 0.770, recall
0.734, F1 0.752. With the "Alto riesgo" rule above the application catches 72 % of the students who end up at risk (44 % with the
model score alone at 75). Error analysis, fairness audit and limitations: [docs/evidence/model](docs/evidence/model/README.md).

The data come from a simulator with hidden traits and unforeseeable events (`data_access/synthetic_students.py`), calibrated so
that the model is mostly right but visibly imperfect; **none of these figures describe real students** ([data/README.md](data/README.md)).

---

## 6. Architecture

```
Presentation     webapp/ (Flask app factory: dashboard + admin blueprints) · templates/ · static/ · presentation/ (PDF, text)
     │
Business logic   main_api.py: the orchestrator and composition root (_bootstrap wires everything once)
     │
AI / prediction  data_pipeline/ (validation, ETL, Excel import) · feature_store/ · inference_engine/ · learning_module/
     │
Data access      data_access/: IAcademicDataRepository → MongoAcademicRepository | InMemoryAcademicRepository
core/            configuration, logging (PII-safe), exceptions, Observer, risk levels: used by every layer
```

| Pattern | Where | Role |
|---|---|---|
| Strategy | `inference_engine/risk_predictor.py` | `IRiskPredictionEngine`: Random Forest and Logistic Regression engines are interchangeable |
| Factory | `create_risk_engine`, `data_access/repository_factory.py` | the configured model type and data source decide which class is built |
| Decorator | `inference_engine/cache_manager.py` | `CachingDecorator` (60 s, keyed by the student's data) wraps `AuditDecorator` (latency, model version) wraps the engine |
| Observer | `core/audit_observer.py` | `RiskEventPublisher` → `RiskAlertObserver` (alerts with reason) and `ModelMonitoringObserver` (history); a failing observer never stops the report |
| Pipeline (ETL) | `data_pipeline/etl_processor.py` | extract → validate (Fail-Fast) → transform into feature vectors |
| Dependency inversion | `IAcademicDataRepository` | the rest of the system never depends on MongoDB directly |

**AI workflow** for one report (main_api.py):
1. validate the request · 2. authorize the teacher (*not implemented: there is no login yet*) · 3. read the group ·
4. reject invalid records (Fail-Fast) · 5. build feature vectors (no names: DR-1) · 6. predict the whole group in one call
(Strategy + Decorators) · 7. notify observers (alerts) · 8. store the predictions in one batch (best effort, NFR-5) ·
9. render the dashboard, PDF or text report.

### Project structure

```
├── web_app.py, admin_app.py      entry points (ports 5000 / 5001) for the same application
├── main_api.py                   orchestrator, composition root and console demo
├── webapp/                       app factory, dashboard and admin blueprints, /health, /ready
├── templates/, static/           HTML, CSS and JavaScript of both interfaces
├── presentation/                 PDF reports, shared report data, text report
├── core/                         config, logger, exceptions, Observer, risk levels
├── data_access/                  repositories (MongoDB, in-memory), schema, connection, synthetic students
├── data_pipeline/                Fail-Fast validator, ETL, Excel importer, import service, demo seeding
├── feature_store/                FeatureVector (no personal data) and feature extraction
├── learning_module/              training, model store, evaluation, validation, evaluation dataset loader
├── inference_engine/             prediction engines, Factory, caching and audit decorators
├── models/                       model_card.json (versioned); risk_model.joblib is generated
├── data/                         grupo_evaluacion.xlsx: fixed evaluation group (240 synthetic students)
├── scripts/                      train, seed, evaluate, evidence collection, smoke test, dataset builder, migration
├── tests/                        unit/, integration/, system/, performance/
├── docs/                         DATABASE.md and evidence/ (testing, model, docker, cicd, performance)
├── Dockerfile, docker-compose.yml, docker/entrypoint.sh, .dockerignore
├── k8s/                          Kubernetes manifests (namespace, app, secret template, development MongoDB)
└── api/index.py, vercel.json     Vercel entry point (exports the same application; not verified in this milestone)
```

---

## 7. Dependencies

| Package | Why |
|---|---|
| `flask` | web application and REST endpoints |
| `scikit-learn` | the two models, cross-validation and metrics |
| `numpy`, `pandas` | batch feature extraction. Measured honestly: at 10,000 students it is slower than a plain Python loop, and irrelevant in absolute terms ([testing evidence](docs/evidence/testing/README.md)) |
| `pymongo`, `dnspython` | MongoDB, including Atlas `mongodb+srv://` addresses |
| `openpyxl` | Excel import and template |
| `reportlab` | PDF reports |
| `python-dotenv` | `.env` files in development |
| `gunicorn` | production web server in the Docker image (not installed on Windows) |
| dev: `pytest`, `pytest-cov`, `ruff`, `pypdf`, `matplotlib` | tests, coverage, linting, reading PDFs in tests, evidence charts |

---

## 8. Design decisions

- **MongoDB instead of the PostgreSQL + SQLAlchemy of the design document.** Groups have a variable number of partial exams and the team
  shares a free Atlas cluster. Thanks to `IAcademicDataRepository` the change was one new class; the rest of the code did not change.
- **The model is trained offline and loaded**, with a versioned model card. A missing or broken model stops the application.
- **Personal data stay out of the AI layer and the logs**: feature vectors carry an ID but no name, and `sanitize()` redacts sensitive keys.
- **Fail fast**: invalid data are rejected with a message, invalid configuration stops the start-up, and a configured database that is
  down stops the start-up instead of falling back to fake data.
- **Liveness and readiness are separate**, so a database outage takes the instance out of service without restarting it.

## 9. Implemented and not implemented

| Implemented | Not implemented (future work) |
|---|---|
| dashboard, administration, Excel import, PDF and text reports | teacher authentication and HTTPS |
| MongoDB and demo repositories, schema validation | sending alerts to teachers (only logged now) |
| two models, validation, error analysis, fairness audit, quality gate | real institutional data |
| 4-level test suite, memory profiling, reproducible evidence | publishing the image (configured for `main`, not exercised yet) |
| Docker image and compose, health and readiness probes | autoscaling verified under load (the HPA is only checked statically) |
| Kubernetes manifests, deployed and self-healing checked in CI | a shared prediction cache between replicas |
| performance benchmark, bottleneck analysis, batch inference and batch storage | |
| CI/CD on GitHub Actions: lint, tests with MongoDB, quality gate, container smoke test, Kubernetes deployment | |
| | Vercel deployment (configuration present, not verified) |

## 10. Known limitations

- Synthetic data only; the model's difficulty was calibrated on purpose.
- With MongoDB down while the application runs, data requests take 8 s before answering with an error.
- No login: anyone who can reach the dashboard sees the data, and `/admin` is open unless `ADMIN_PASSWORD` is set.
- Each web-server process keeps its own prediction cache.

Further documentation: [docs/DATABASE.md](docs/DATABASE.md) (MongoDB and Atlas setup, in Spanish) · [docs/evidence](docs/evidence/).

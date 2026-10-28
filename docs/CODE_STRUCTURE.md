# Code structure: a guide for newcomers

This guide is for anyone who has never seen the project: a new teammate, a reviewer, or a teacher. It explains **what
each folder and file is for**, **how a request travels through the code**, and **where to go to change something**. It
assumes no previous knowledge of the project. Everything here matches the repository on branch `milestone-3`.

## 1. The project in one minute

A teacher opens a web page, chooses a group of students, and the application shows who needs attention. For each student
it computes a **risk score from 0 to 100** (an estimate of ending the term with low performance) from four numbers:
the average grade, how the grades changed, attendance and participation. A student is marked **high risk** when the average
is below 6.0 (60/100) **or** the risk score is 75 or more. The application also creates PDF reports and has an
administration page to create groups and import grades from Excel. **It only recommends: a teacher decides.** All data are
synthetic (simulated).

The code is Python (Flask for the web, scikit-learn for the prediction, MongoDB for storage).

## 2. The idea behind the structure: layers

The code is organised in **layers**. Each layer talks only to the one below it, so a change in one place does not break the
rest. A restaurant is a good picture (it is only an analogy):

| Layer | Restaurant | In the code | What it does |
|---|---|---|---|
| Presentation | the waiter and the menu | `webapp/`, `templates/`, `static/`, `presentation/` | shows pages, answers web requests, draws PDFs |
| Business logic | the manager | `main_api.py` | coordinates the steps of one report, in order |
| AI / prediction | the kitchen | `data_pipeline/`, `feature_store/`, `inference_engine/`, `learning_module/` | validates data, turns it into numbers, predicts the risk, trains the model |
| Data access | the pantry | `data_access/` | reads and writes students and predictions (MongoDB, or memory) |
| Shared tools | the rules of the house | `core/` | configuration, logging, errors, alerts, risk levels: used by everyone |

```
Presentation     webapp/ · templates/ · static/ · presentation/
      │ calls
Business logic   main_api.py
      │ calls
AI / prediction  data_pipeline/ · feature_store/ · inference_engine/ · learning_module/
      │ calls
Data access      data_access/            (MongoDB or in-memory)

core/  is used by all of the above
```

**One rule worth remembering:** the prediction layer never sees a student's **name**, only an ID and the four numbers
(requirement DR-1, privacy). Names are added back only when drawing the page or the PDF.

## 3. The journey of one request

What happens when a teacher chooses group `301-A` on the dashboard:

1. **The browser** (`static/dashboard.js`) asks `GET /api/groups/301-A`.
2. **`webapp/dashboard.py`** receives it, checks that the group ID looks valid and calls `main_api`.
3. **`main_api.py`** (`_run_risk_workflow`) runs the steps in order:
   1. *Validate the request* (the group ID is not empty).
   2. *Read the group once* from the repository (`data_access/`).
   3. *Check each student's record* (`data_pipeline/fail_fast_validator.py`): a record with a grade of 150 or text where a
      number belongs is **skipped**, and the rest of the group continues.
   4. *Turn each record into four numbers* (`feature_store/feature_manager.py`): average grade, grade trend (last minus
      first), attendance, participation. The result has no name.
   5. *Predict for the whole group in one call* (`inference_engine/`). A cache remembers recent results and an audit line is
      written to the log for each student.
   6. *Announce each result* to the observers (`core/audit_observer.py`): the alert observer writes a `RISK ALERT` log line
      with the reason when a student is high risk.
   7. *Store the predictions* in one batch (`data_access/`). If this fails, the report is still produced.
4. **`webapp/dashboard.py`** adds names, levels and a summary (`presentation/report_data.py`) and returns JSON.
5. **The browser** draws the cards, the chart and the student table. **↓ PDF** asks `presentation/pdf_reports.py` for a file.

If any step fails in a way the user should know about, the answer is a short, safe message (never a stack trace). The
messages come from the error classes in `core/exception_handler.py`.

## 4. Folder by folder

### Top level

| File / folder | What it is |
|---|---|
| `main_api.py` | **The coordinator.** Builds everything once at start-up (`_bootstrap`: loads the model, creates the repository, wires the cache, the audit and the observers) and exposes `get_group_dashboard_data`, `generate_group_risk_report`. Also runs a text demo if executed directly |
| `web_app.py`, `admin_app.py` | Two tiny launchers. Both start the **same** application (ports 5000 and 5001); they exist so older commands keep working |
| `api/index.py`, `vercel.json` | Entry point for the Vercel service (configured, **not verified**) |
| `requirements.txt`, `requirements-dev.txt` | Libraries to run the app / to also run the tests |
| `pytest.ini`, `ruff.toml`, `.coveragerc` | Settings for the test runner, the code-style checker and the coverage report |
| `.env.example` | Template of the configuration file. Copy it to `.env`; `.env` is never committed |
| `Dockerfile`, `docker-compose.yml`, `docker/entrypoint.sh`, `.dockerignore` | Packaging the app as a container and starting it with its database |
| `k8s/` | Kubernetes manifests (several copies of the app, self-healing) |
| `.github/workflows/ci.yml` | The automatic pipeline that checks every push |
| `README.md` | Start here to install and run |

### `webapp/`: the web application (Presentation)

| File | Role |
|---|---|
| `__init__.py` | `create_app()`: builds the Flask application, registers the two blueprints, sets the 4 MB upload limit and the safe error handlers |
| `dashboard.py` | The teacher side: `/`, `/api/groups`, `/api/groups/<id>`, the PDF routes, `/health` and `/ready` |
| `admin.py` | The administration side under `/admin`: groups, students, Excel import, demo data, database browser. Protected by `ADMIN_PASSWORD` when set |

### `templates/` and `static/`: what the browser receives

| File | Role |
|---|---|
| `templates/index.html` | The dashboard page (labels in Spanish) |
| `static/dashboard.js`, `static/dashboard.css` | Dashboard behaviour (load a group, filter, open the student card, download PDFs) and look |
| `templates/admin.html` | The whole administration page, with its own script and styles inside |

### `presentation/`: reports

| File | Role |
|---|---|
| `report_data.py` | Turns predictions into what the screens need: the group summary, level descriptions, the follow-up suggestions |
| `pdf_reports.py` | Draws the group PDF and the individual PDF (reportlab) |
| `teacher_report_ui.py` | The plain-text report (also used by the console demo) |

### `core/`: shared tools used everywhere

| File | Role |
|---|---|
| `config.py` | Reads settings from environment variables (`MONGODB_URI`, `PASSING_GRADE`, `RISK_THRESHOLD`…) and **stops the start-up with a clear message** if one is invalid |
| `risk_levels.py` | **The single definition** of "high / medium / low" and of the alert reasons. If the rule changes, it changes here |
| `audit_observer.py` | The *Observer* mechanism: after each prediction, listeners are told. One writes alerts, one keeps a history. A listener that fails never stops the report |
| `exception_handler.py` | The project's error types (`ValidationError`, `DataAccessError`, `NotFoundError`, `ModelLoadError`…), each with a safe message for the user |
| `logger.py` | Logging in one format; `sanitize()` hides names and e-mails from log lines |

### `data_access/`: storage (Data access)

| File | Role |
|---|---|
| `student_repository.py` | The **contract** (`IAcademicDataRepository`: get a student, get a group, save predictions, list groups) and the **in-memory demo** version with three fixed groups |
| `mongo_repository.py` | The real implementation on MongoDB, plus the administration operations (create group, import, delete, history) |
| `mongo_connection.py` | Opens the MongoDB connection; hides passwords when logging the address |
| `schema.py` | Defines the six collections, their validation rules and unique indexes |
| `repository_factory.py` | Chooses which repository to use: MongoDB if `MONGODB_URI` is set, memory otherwise. If MongoDB is configured but down, it **stops** instead of showing fake data |
| `synthetic_students.py` | The simulator that creates fictitious students (used for training data, demo data and the evaluation workbook) |

### `data_pipeline/`: checking and preparing data

| File | Role |
|---|---|
| `fail_fast_validator.py` | Rejects a bad record immediately, with the reason |
| `etl_processor.py` | The pipeline: validate each record, then extract the four numbers for the whole group |
| `excel_importer.py` | Reads an `.xlsx`, validates each row, builds the downloadable template. Reports rejected rows with their Excel row number |
| `group_import_service.py` | The use cases of the admin: create a group, add a student, import an Excel (partial or strict mode) |
| `synthetic_seed.py` | Fills the database with demo groups |

### `feature_store/` and `inference_engine/`: from data to a risk score

| File | Role |
|---|---|
| `feature_store/feature_manager.py` | `FeatureVector` (ID + four numbers, **no name**) and the code that computes them |
| `inference_engine/risk_predictor.py` | The *Strategy*: two interchangeable prediction engines (Random Forest, Logistic Regression) and the *Factory* `create_risk_engine` that picks one. Predicts one student or a whole group |
| `inference_engine/cache_manager.py` | Two *Decorators* wrapped around the engine: an **audit** layer (logs model version and time) and a **cache** (remembers results for 60 s) |

### `learning_module/`: creating and checking the model

| File | Role |
|---|---|
| `model_trainer.py` | Builds and fits the two model types; generates the simulated training set |
| `training_pipeline.py` | `run_training`: train, evaluate, save the model and its **model card** |
| `model_store.py` | Saves and loads the model. If the file is missing or corrupt: `ModelLoadError` and the app does not start |
| `model_evaluator.py` | Accuracy, precision, recall, F1 and a fairness check by subgroup |
| `model_validation.py` | Cross-validation, confidence intervals, model selection, threshold analysis, the quality gate |
| `evaluation_data.py` | Loads `data/grupo_evaluacion.xlsx` (the 240 students used to measure the model) |

### `models/`, `data/`, `demo/`

| Path | What it is |
|---|---|
| `models/model_card.json` | Record of the trained model (version, features, data). **Committed** |
| `models/risk_model.joblib` | The trained model itself. **Not committed**: it is generated by `scripts/train_model.py` (Docker does it while building the image) |
| `data/grupo_evaluacion.xlsx`, `data/README.md` | A fixed group of 240 fictitious students with the true outcome, used to validate the model |
| `demo/grupo_con_errores.xlsx` | A small file with deliberate errors to practise the import |

### `scripts/`: commands you run by hand

| Script | What it does |
|---|---|
| `train_model.py` | Trains and saves the model |
| `evaluate_models.py` | Validates the model and rewrites `docs/evidence/model/` (`--gate` is the quality gate) |
| `seed_demo_data.py` | Creates demo students in MongoDB |
| `smoke_test.py` | 15 end-to-end checks against a running instance |
| `benchmark.py` | Measures speed and resources |
| `collect_test_evidence.py`, `collect_docker_evidence.py` | Run everything and rewrite `docs/evidence/testing/` and `docs/evidence/docker/` |
| `build_evaluation_dataset.py`, `memory_profile.py`, `migrate_local_to_atlas.py` | Rebuild the evaluation workbook, measure memory, copy demo data to Atlas |

### `tests/`: the safety net (288 tests)

| Folder | Question it answers |
|---|---|
| `tests/unit/` | Does each piece work **alone**? (validator, features, importer, engines, cache, risk levels…) |
| `tests/integration/` | Do the pieces work **together**, and what if one fails? (the full flow, web routes, the admin API on a real MongoDB) |
| `tests/system/` | Does the **whole system** meet the requirements? (teacher workflow, start-up failures, the quality gate, and checks that the Dockerfile, the CI file and the Kubernetes files keep their safeguards) |
| `tests/performance/` | How much memory do the heavy operations use? |
| `tests/helpers.py`, `tests/conftest.py` | Shared helpers; the conftest clears environment variables so a developer's `.env` cannot change test results |

### `docs/`

| Path | What it is |
|---|---|
| `docs/evidence/{testing,model,docker,cicd,performance}/` | Results of every measurement, each with a README that **interprets** the numbers |
| `docs/DATABASE.md` | MongoDB and Atlas set-up (Spanish) |
| `docs/M3_CORRECCION.md`, `docs/MANUAL_*_BRIEF.md`, `docs/CODE_STRUCTURE.md` | Material for the reports and manuals, and this guide |

## 5. Design patterns, in plain words

| Pattern | The problem it solves | Where |
|---|---|---|
| **Strategy** | We want to swap the prediction model without touching the rest | `inference_engine/risk_predictor.py` |
| **Factory** | "Which engine / which repository do I build?" is decided in one place, from configuration | `create_risk_engine`, `repository_factory.py` |
| **Decorator** | Add a cache and an audit log **around** the engine without changing it | `inference_engine/cache_manager.py` |
| **Observer** | Several parts must react to a prediction (alert, history) without the predictor knowing them | `core/audit_observer.py` |
| **Pipeline (ETL)** | Data goes through fixed steps: extract, validate, transform | `data_pipeline/etl_processor.py` |
| **Dependency inversion** | The rest of the code depends on the *contract* `IAcademicDataRepository`, not on MongoDB. That is why changing the database from PostgreSQL (the original design) to MongoDB meant writing **one new class** | `data_access/` |

## 6. "I want to change X: where do I go?"

| I want to… | Go to |
|---|---|
| Change what counts as high risk (the 6.0 or the 75) | the values are settings: `PASSING_GRADE`, `RISK_THRESHOLD` in `.env`. The rule itself: `core/risk_levels.py` |
| Change a text, button or colour of the dashboard | `templates/index.html`, `static/dashboard.js`, `static/dashboard.css` |
| Change the administration page | `templates/admin.html` (page, script and styles are in the same file) |
| Change what a PDF contains | `presentation/pdf_reports.py` and `presentation/report_data.py` |
| Add a column to the Excel template | `data_pipeline/excel_importer.py` and `data_access/schema.py` |
| Change which rows are rejected as invalid | `data_pipeline/fail_fast_validator.py` (records) and `data_pipeline/excel_importer.py` (rows) |
| Add a new prediction model | `inference_engine/risk_predictor.py`, `core/config.py` (`MODEL_TYPES`), `learning_module/model_trainer.py`; then train, validate and add tests |
| Use another database | implement `IAcademicDataRepository` in `data_access/` and choose it in `repository_factory.py` |
| Really send alerts to teachers | add an observer in `core/audit_observer.py` and attach it in `main_api._bootstrap` (today alerts are only logged) |
| Add a new web route | `webapp/dashboard.py` (teacher) or `webapp/admin.py` (admin) |
| Change a setting's name or default | `core/config.py` and `.env.example` (and the README table) |
| Change how the project is packaged or deployed | `Dockerfile`, `docker-compose.yml`, `k8s/`, `.github/workflows/ci.yml` |

After any change: run `python -m pytest` and `python -m ruff check .`. If you change behaviour that a document describes,
update the document: the project requires code and documentation to agree.

## 7. Conventions

- **Language:** code, comments, commits' bodies, README and reports in English; the screens are in Spanish.
- **Names:** modules and functions in `snake_case`, classes in `CapitalizedWords`; a leading underscore (`_bootstrap`) means
  "internal, do not call from outside".
- **No secrets in the repository:** the real database address lives only in `.env` or environment variables.
- **No personal data in the AI layer or in logs:** ID yes, name no (student IDs do appear in the audit log lines).
- **Error messages for users are short and safe;** the technical detail goes only to the log.
- **Generated files are not committed:** `.env`, `models/risk_model.joblib`, `logs/`, `.coverage`.

## 8. Glossary

| Term | Meaning |
|---|---|
| **Group** | A class identified by an ID such as `301-A` |
| **Matrícula / student ID** | The student's unique identifier |
| **Parcial / registro** | One partial exam (the dashboard calls it "Registro 1, 2…") |
| **Risk score** | The model's estimate, 0 to 100; **not a grade** |
| **Alert** | A high-risk student, shown as "⚠ Alerta" with its reason |
| **Feature** | One of the four numbers the model uses |
| **Model card** | JSON record of how a model was trained |
| **Fail-Fast** | Reject bad data or bad configuration immediately, with a clear message, instead of continuing |
| **Repository** | The class that reads and writes data, hiding where they are stored |
| **Blueprint** | A group of Flask routes (here: the dashboard and the admin) |
| **CI/CD** | The automatic pipeline that builds, tests and packages the project on every push |
| **Synthetic data** | Simulated, not real students |

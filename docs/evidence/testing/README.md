# Testing evidence (Milestone 3, criterion 2)

Every number in this folder is produced by one command and can be regenerated at any time:

```bash
# with the real-MongoDB tests included (a throw-away Mongo, e.g. docker run -d -p 27018:27017 mongo:7)
MONGODB_TEST_URI=mongodb://localhost:27018 python scripts/collect_test_evidence.py
# without MongoDB: the tests that need it are skipped and the summary says so
python scripts/collect_test_evidence.py
```

| File | Content |
|---|---|
| `summary.json` | tests per level, coverage per package, Python / scikit-learn versions, whether real-MongoDB tests ran |
| `pytest_unit.txt`, `pytest_integration.txt`, `pytest_system.txt`, `pytest_performance.txt` | verbose pytest output, one line per test |
| `coverage.txt` | coverage report with the missing line numbers |
| `memory_profile.json` | `tracemalloc` measurements (`scripts/memory_profile.py`) |

> *Software testing evaluates the software. Model validation evaluates the intelligence of the model.*
> This folder covers the first only. Whether the predictions are good (accuracy, precision, recall,
> F1, error analysis) is a different question, answered in `docs/evidence/model/` (Phase 5).

## Result

Run of 2026-10-25 on Windows 10, Python 3.12.3, scikit-learn 1.9.1, MongoDB 7 in Docker:

| Level | Tests | Parametrised sub-cases | Failed | Skipped | Time |
|---|---|---|---|---|---|
| Unit | 106 | 31 | 0 | 0 | 2.3 s |
| Integration | 50 | 17 | 0 | 0 | 7.9 s |
| Memory profiling | 6 | 0 | 0 | 0 | 2.3 s |
| System | 19 | 3 | 0 | 0 | 27.6 s |
| **Total** | **181** | **51** | **0** | **0** | |

181 test functions, plus 51 parametrised cases (`subTest`) executed inside them: 232 checks, all passing.

Statement coverage: **93.7 %** overall.

| Package | Coverage | | Package | Coverage |
|---|---|---|---|---|
| `feature_store` | 100.0 % | | `core` | 95.5 % |
| `presentation` | 98.1 % | | `webapp` | 95.4 % |
| `data_pipeline` | 97.8 % | | `inference_engine` | 96.0 % |
| `main_api` | 96.7 % | | `learning_module` | 98.7 % |
| `data_access` | **84.8 %** | | | |

## The four levels

### 1. Unit testing: "Does this component work correctly?"

One component in isolation, with the cases a tester must always cover: normal, boundary, invalid,
missing, unexpected type, empty and extreme input.

| Component | What is verified |
|---|---|
| `FailFastValidator` | boundaries 0 and 100 accepted; below/above range, `None`, `NaN`, `inf` rejected; **text, `bool` and list values rejected with a `ValidationError`**; stops at the first problem; never modifies the record |
| `FeatureManager` | batch result equals single-record result for 300 random students with 1–8 grades each; single grade gives trend 0; empty input; record without grades is refused |
| Excel importer | the downloadable template is itself importable; header aliases and accents; `123.0`, `"85,5"`, `"90%"` normalised; empty file, PDF content, random text, truncated workbook, missing column, header-only file, 1,001 rows; 11 kinds of invalid row reported with their Excel row number |
| Factory and engines | both strategies built, name case/whitespace tolerant, unknown type, missing model, model crash wrapped in a safe error that hides internals |
| Decorators | cache hit/miss/expiry, key includes the student's data, clear, bounded size, **a cache hit does not reach the audit trail** (Figure 5 order), audit line carries model version and latency |
| Observer | inclusive threshold, no personal-name field in the event, alert only at/above threshold, history returned as a copy, **a failing observer does not stop the others** |
| Risk levels / threshold | label boundaries for default, 90, 50 and 30; the legend text is derived from the threshold; invalid `RISK_THRESHOLD` values (`abc`, `-1`, `101`, `nan`, `inf`) rejected |
| Model store | save/load round trip, missing file, corrupt file, card without version |
| Logging | personal-data keys are redacted case-insensitively without mutating the input |
| Error handling | exception hierarchy; unexpected errors never leak their message to the user |
| Repository, evaluator, connection | demo groups only (no invented groups), seed determinism; metrics for a known confusion matrix; fairness audit per group; passwords redacted from connection strings; fallback to demo mode logs a warning |

**Interpretation.** 90 passing unit tests (plus 29 parametrised cases) say the building blocks honour their contracts, including
the unhappy paths. They say nothing yet about how the blocks behave together or whether the model is good.

### 2. Integration testing: "Do these components work correctly together?"

| Scenario | What is verified |
|---|---|
| Repository → ETL → engine → observers → persistence → report | every student appears in the report; every prediction is persisted and every observer notified; high-risk students raise an alert; **no student name appears in any log line** (DR-1) |
| Data quality | records with a text grade, an out-of-range grade or no grades are skipped and the rest of the group is analysed |
| Component failure (NFR-5) | a failing observer or a failing prediction store does not stop the report |
| Failure reaches the user safely | database error, model error and an unexpected crash all return HTTP 503 with a fixed safe message and **never** a traceback, host name or file path; the PDF endpoints behave the same |
| Flask routes | dashboard, JSON, PDF, 400/404/503, threshold and legend in the API and the PDFs |
| Excel → MongoDB → dashboard *(real MongoDB)* | partial import saves valid rows and reports the rest; re-importing the same file changes nothing; changed values update only that student and the risk follows; strict mode stores nothing; unknown group; import log; invalid group ids |
| Administration API *(real MongoDB)* | group/student CRUD with validation messages, history, seeding is idempotent and its purge leaves real groups alone, database browser refuses unknown collections, `ADMIN_PASSWORD` protects every admin route except the public ones (NFR-2) |

**Interpretation.** The interfaces between layers agree on formats and error types. The
failure tests matter most: they are what a reviewer asks for ("what happens if the AI module or
a dependency fails?") and they are executed, not described.

### 3. Memory profiling: "Is it efficient at scale?"

`sys.getsizeof` measures only the container, so `tracemalloc` is used: it traces every allocation made
while the function runs and reports the peak (`memory_profile.json`).

| Measurement | Result |
|---|---|
| Feature extraction, 1,000 students | pure Python loop 0.16 MiB / 9 ms · `extract_many` (pandas + numpy) 0.30 MiB / 26 ms |
| Feature extraction, 10,000 students | pure Python loop 1.5 MiB / 84 ms · `extract_many` 2.9 MiB / 333 ms |
| Scaling 1,000 → 10,000 students | memory ×9.8 (loop) and ×9.5 (`extract_many`) for ×10 students: linear, no leak |
| Model load | 0.48 MiB file, 1.0 MiB peak, 0.13 MiB retained, 65 ms |
| Largest allowed Excel (1,000 rows, 36 KiB) | 1.1 MiB peak, 0.3 s |
| Prediction cache, 15,000 distinct predictions | bounded: 5,000 entries kept (limit 10,000), 3.9 MiB peak |

**Interpretation.**
- Memory grows **linearly** with the number of students and nothing large is retained: no leak.
- **The pandas/numpy batch uses about 2× the memory and 3–4× the time of a plain Python loop** at these sizes
  (DataFrame construction dominates). It is not an optimisation, and it must not be presented as one.
  It is also irrelevant in absolute terms (10,000 students take 0.33 s and 2.9 MiB), so feature extraction
  is not a bottleneck. *Measure first, optimise second*: the request-level benchmark
  (`docs/evidence/performance/`, Phase 8) decides where effort is worthwhile.
- The cache is bounded, but its eviction is crude: when full it drops everything that has not expired
  (hence 5,000 entries after 15,000 insertions), not the least recently used. Acceptable for one faculty,
  and listed as a limitation.

### 4. System testing: "Does the whole system satisfy the requirements?"

| Scenario | What is verified |
|---|---|
| Teacher workflow *(real MongoDB)* | create group → import a 50-student Excel → the group appears in the selector with 50 students → predictions for all 50, scores in 0–100, **answered within the NFR-1 limit of 10 s** → the model ranks the students built to be at risk above the rest → group PDF and student PDF download and contain the on-screen data |
| Change propagates | re-importing worse grades for a student raises their risk in the next report (cache keyed by data) |
| Edge cases | a group with no students is a valid empty report; `/health` reports database, model and mode |
| Excel error catalogue (lesson 17) | valid file; empty; PDF content disguised as `.xlsx`; truncated file; missing columns; no file; wrong extension; 5 MB file: each answered with a meaningful message, no traceback, no data changed |
| Startup failures | missing model, corrupt model file and invalid `RISK_THRESHOLD` each stop the application with a message naming the cause and the fix; a valid configuration starts |
| Threshold end to end | restarting with `RISK_THRESHOLD=1` produces more high-risk students than the default |

**Interpretation.** The complete flow meets the lesson-17 checklist: valid input accepted, invalid input
rejected with a meaningful message, predictions generated, reports correct, response time within the
requirement.

## Defects found by these tests (and fixed)

| Found by | Defect | Fix |
|---|---|---|
| failure-between-components tests | one failing observer aborted the whole report (violated NFR-5) | `RiskEventPublisher.notify_all` isolates each observer; the prediction store call is best effort |
| unexpected-type tests | a text grade raised `TypeError`, not caught by the ETL, so **one corrupt record broke the group**; `True` was accepted as grade 1 | `FailFastValidator` accepts only real numbers in range |
| startup-failure test | a missing model printed the cause but not how to fix it | the fix command is part of the error message |
| cache tests (earlier) | the cache returned stale scores after an import (key was only the student id) | key is the full feature vector; bounded size |
| threshold tests | "high risk" colours ignored the configured threshold | one definition of the levels (`core/risk_levels.py`) |
| model metrics review | every metric was 1.0 because the synthetic classes did not overlap, so validation had nothing to analyse | noisy simulator with hidden traits and unobservable events, plus a fixed evaluation workbook (`data/README.md`) |

## Limitations (stated, not hidden)

- The real-MongoDB tests (32 of the 181) need `MONGODB_TEST_URI`; without it they are skipped and
  `summary.json` records `real_mongodb_tests_included: false`. The CI workflow provides a Mongo service container.
- Coverage is lowest in `data_access` (84.8 %): the uncovered lines are mostly database-outage branches
  that need a Mongo that fails on demand.
- Measurements come from one development machine; use them for orders of magnitude and for the ratios
  between alternatives, not as absolute guarantees.
- There is no concurrent-load test here; latency, throughput and 10 simultaneous sessions (NFR-1) are measured in
  `docs/evidence/performance/` (Phase 8).
- The data are synthetic; a passing test suite does not make the predictions trustworthy (see Phase 5 and `data/README.md`).

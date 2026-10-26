# Performance and scalability evidence

Rule followed (lessons 21-22): **measure first, find the bottleneck, optimise only the bottleneck, measure again.**

| File | What it is |
|---|---|
| `benchmark_baseline.json` | Run before the optimisations (code of commit `d1c6b72`) |
| `benchmark_after.json` | Same benchmark after the three optimisations below |
| `../../../scripts/benchmark.py` | The benchmark itself; every number in this page comes from those two files |

Reproduce (needs Docker):

```bash
docker compose up -d --build
python scripts/benchmark.py --label after
```

Part 1 runs in process against a MongoDB (default `mongodb://localhost:27018`, database `spp_benchmark`, dropped at the
end) and times every stage of one real dashboard request. Part 2 runs over HTTP against the container
(`http://localhost:8000`) with 1 and 10 concurrent users and samples `docker stats`.

Machine: Windows 10, 12 logical CPUs, Python 3.12.3, Docker Desktop (WSL 2). The container runs gunicorn with
2 workers x 4 threads and talks to the `mongo:7` container of `docker-compose.yml`.

## 1. The four metrics

**Latency** (HTTP, p95, milliseconds)

| Request | Users | Before | After | Change |
|---|---|---|---|---|
| Group of 50 (`/api/groups/BENCH-50`) | 1 | 52.5 | 32.3 | -38 % |
| Group of 50 | 10 | 330.8 | 75.6 | -77 % |
| Group of 240 (`/api/groups/BENCH-240`) | 1 | 163.1 | 43.8 | -73 % |
| Group PDF, 50 students | 1 | 142.4 | 110.2 | -23 % |
| Student PDF | 1 | 67.6 | 42.6 | -37 % |
| Student PDF | 10 | 374.7 | 185.3 | -51 % |

**Throughput** (requests per second, same runs)

| Request | Users | Before | After | Change |
|---|---|---|---|---|
| Group of 50 | 1 | 23.4 | 40.8 | x1.7 |
| Group of 50 | 10 | 46.5 | 201.7 | x4.3 |
| Group of 240 | 1 | 7.3 | 32.4 | x4.4 |
| Student PDF | 10 | 36.4 | 83.6 | x2.3 |

**Resources** (container while serving 10 concurrent users; `docker stats`, 100 % = one core)

| | Before | After |
|---|---|---|
| CPU, maximum sample | 336 % | 242 % |
| Memory | 342 MiB | 285 MiB |

The after run finished in 1.5 s, so `docker stats` (one sample per second or slower) only took 2 samples; the CPU
figure is indicative. The memory figure is the one the Kubernetes requests/limits are based on (384 Mi / 768 Mi,
see `k8s/app.yaml`).

**Availability / errors**: 0 failed requests out of 550 in each run (100 + 300 + 50 + 20 + 20 + 60). Recovery
from a dead instance is covered by: the Docker `HEALTHCHECK` and `restart: unless-stopped`
(`docs/evidence/docker/`), and in Kubernetes by the CI job `kubernetes`, which deletes a Pod and checks that the
Deployment is back to 2 ready replicas.

**NFR-1** (group of 50 in at most 10 s, a student in at most 3 s, 10 concurrent sessions) was already met before the
optimisations (331 ms at p95 with 10 users) and now has about two orders of magnitude of margin (76 ms).

## 2. Finding the bottleneck (baseline)

Median time per stage of one dashboard request, in process, cold prediction cache:

| Stage | 50 students | share | 240 students | share | calls per request |
|---|---|---|---|---|---|
| Store predictions in MongoDB | 31.5 ms | **55.5 %** | 147.7 ms | **60.4 %** | one insert **per student** |
| Model inference (incl. cache, audit) | 14.5 ms | 25.6 % | 67.9 ms | 27.8 % | one model call **per student** |
| Load group from MongoDB | 7.7 ms | 13.6 % | 16.5 ms | 6.8 % | **3 reads** of the same group |
| Everything else (validation, features, observers, JSON) | 3.0 ms | 5.3 % | 11.6 ms | 4.7 % | |
| **Total (p50)** | **56.7 ms** | | **244.4 ms** | | |

Three defects of the same kind, all "N round trips where one is enough":

1. `save_prediction` was called once per student: 240 network round trips to MongoDB per request.
2. The engine received one student at a time, so scikit-learn's `predict_proba` ran 240 times on a one-row matrix.
   Measured separately: 240 one-row calls cost 25.3 ms (Logistic Regression) and 1 428 ms (Random Forest); one call
   with 240 rows costs 0.21 ms and 6.9 ms (x119 and x206).
3. The group document was read three times: by the ETL, by the name lookup and by the dashboard builder.

Training at start-up, which the application did before this milestone, was not a bottleneck per request but delayed
every start: 76 ms (LR) / 164 ms (RF) against 0.8 ms / 17 ms to load the persisted model.

## 3. Optimisations (only the bottleneck)

| # | Change | Where | Pattern kept |
|---|---|---|---|
| 1 | Store all the predictions of a request in one `insert_many(ordered=False)` | `IAcademicDataRepository.save_predictions`, `MongoAcademicRepository.save_predictions` | Repository (the in-memory repository inherits a loop) |
| 2 | Predict the whole group in one model call | `IRiskPredictionEngine.predict_many`, `_ProbabilisticRiskEngine.predict_many` | Strategy; both decorators implement `predict_many`, so the cache only sends the **missing** students to the model and the audit trail still writes one line per student |
| 3 | Read the group once and pass it down | `ETLProcessor.process(group)`, `main_api` | ETL pipeline (`process_group` still exists) |

Not changed: validation, observers, PDF rendering and JSON were below 5 % of the request; optimising them would not
be measurable.

The tests that keep these properties: `tests/integration/test_pipeline_flow.py::RequestEfficiencyTests` (one read,
one write, one engine call per request), `tests/unit/test_factory_and_decorators.py::BatchPredictionTests` (batch
and one-by-one give identical results; the cache keeps the order) and
`tests/integration/test_admin_api_mongo.py::PredictionPersistenceTests` (one round trip against a real MongoDB).

## 4. After: where the time goes now

| Stage | 50 students | share | 240 students | share | calls per request |
|---|---|---|---|---|---|
| Store predictions in MongoDB | 1.4 ms | 14.8 % | 45.8 ms | **60.4 %** | 1 |
| Model inference (incl. cache, audit) | 3.0 ms | 30.7 % | 13.1 ms | 17.3 % | 1 |
| Load group from MongoDB | 2.8 ms | 29.1 % | 6.5 ms | 8.5 % | 1 |
| Everything else | 2.4 ms | 25.4 % | 9.4 ms | 13.8 % | |
| **Total (p50)** | **9.6 ms** (was 56.7) | | **75.9 ms** (was 244.4) | | |

- For a normal class (50) there is no dominant stage any more: the request is 6x faster and the remaining time is
  spread over reading, predicting and storing.
- For a very large group (240) storing is still the largest stage, now limited by MongoDB writing 240 documents and
  not by round trips (148 ms -> 46 ms). The next step would be to write the predictions in the background
  (write-behind queue) instead of inside the request. It is **not** implemented: at 76 ms the request is far below
  NFR-1, and an asynchronous write adds a failure mode (predictions lost if the process dies before writing).
- The in-process figures are higher than the HTTP ones for the same group because the benchmark process reaches
  MongoDB through Docker's published port from Windows, while the container reaches it inside Docker's network, and
  because the benchmark wraps every stage with a timer. Compare before with after inside each table, not across
  tables.

## 5. The cache, with and without (professor's point 2 of Milestone 2)

| | Before (one call per student) | After (one batch call) |
|---|---|---|
| Inference only, 50 students, cold -> warm | 14.5 -> 4.8 ms (x3.0) | 3.0 -> 0.1 ms (x27) |
| Whole request, 50 students, cold -> warm | 56.7 -> 47.9 ms (-16 %) | 9.6 -> 6.2 ms (-36 %) |
| Whole request, 240 students, cold -> warm | 244.4 -> 197.3 ms (-19 %) | 75.9 -> 63.9 ms (-16 %) |

The cache does what it promises for inference, but inference was never most of the request, so its effect on the
whole request is moderate. It is worth keeping because it is cheap (bounded to 10 000 entries, 60 s TTL) and it
protects the model when the same group is opened repeatedly; it would matter more with a slower model (Random
Forest: 6.9 ms per batch of 240 against 0.21 ms for Logistic Regression). Its limitation in a horizontally scaled
deployment is that each Pod has its own cache (see `k8s/README.md`).

## 6. Optimisation levels covered (lesson 22)

| Level | What we did |
|---|---|
| Algorithm / code | Batch inference (vectorised `predict_proba`) |
| Data access | Batch insert with `ordered=False`, one read of the group per request |
| Caching | `CachingDecorator` (measured above) and the 5 s cache of the database check in `/health` |
| Start-up | Model trained offline and loaded (0.8 ms) instead of trained at every start |
| Infrastructure | gunicorn 2 workers x 4 threads; Kubernetes Deployment with 2 replicas and an HPA up to 6 (`k8s/`) |

## 7. Limitations of these measurements

- One laptop, one run of each benchmark; numbers vary a few percent between runs (for example the training time
  of Logistic Regression went from 76 to 34 ms between runs with identical code). The conclusions rely on changes of
  x1.7 or more, well above that noise.
- The database is a local container, not Atlas: real network latency to Atlas would make the "one round trip"
  optimisations matter even more, but those numbers are not measured here.
- The load test reaches 10 concurrent users (the NFR-1 target), not a stress test to the breaking point.

# CI/CD pipeline (Milestone 3, criterion 4)

> *The goal of CI/CD is to ensure that only reliable software reaches production.*

**Continuous Integration** automatically integrates every change into the shared repository and verifies that the
application still works. **Continuous Delivery** automatically prepares the application for deployment once every
check has passed. Workflow file: [`.github/workflows/ci.yml`](../../../.github/workflows/ci.yml).
Runs: <https://github.com/David-Fuentes-IA/Student-Performance-Predictor/actions/workflows/ci.yml>

## 1. Why this project needs it

The situation the course uses to motivate CI/CD (several people merge separately; then the application will not start,
the model will not load, tests fail, library versions clash) is literally what happened here: the database and
administration work and the dashboard were developed apart and did not work together until they were unified by hand,
and the previous milestone's documentation cited a test command whose tests did not exist. A pipeline that runs on every
push turns "it works on my machine" into "it works on a clean machine, and here is the proof".

## 2. The pipeline

```
Developer ─► Push ─► 1. Build ─► 2. Automated testing ─► 3. AI model validation ─► 4. Container ─► 4b. Kubernetes ─► 5. Deliver (main only)
                     install       unit, integration,       quality gate on          build image,      kind cluster,       image published to
                     lint          system, memory           unseen students          start stack,      rollout, smoke      GitHub Container
                     train model   (real MongoDB)                                    smoke test        test, self-healing  Registry
```

Each stage `needs` the previous one: **if a stage fails, the pipeline stops and nothing after it runs**; in particular,
nothing is delivered.

| Stage | What it checks | How it makes the software more reliable |
|---|---|---|
| **1. Build** | dependencies install from `requirements*.txt` on a clean Linux machine; `ruff` finds no errors; the model trains from scratch; the fixed evaluation dataset still matches its generator | proves the project can be set up from the repository alone (no hidden local files, no "works on my machine"), and catches syntax errors, unused imports and similar mistakes before anything runs |
| **2. Automated testing** | every test level (unit, integration, system, memory profiling) with coverage, against a real, empty MongoDB started only for this job; **strict**: any failure *or any skipped test* fails the stage | the whole suite runs on every change, not only when someone remembers; the database tests cannot be silently skipped; the coverage and memory reports are kept as artefacts |
| **3. AI model validation** | `evaluate_models.py --gate` trains the configured model and measures it on 240 students it never saw: recall ≥ 0.60, precision ≥ 0.60, F1 ≥ 0.65, and no metric above 0.99 | software tests show the code works; this shows the **model** is still good. A change that makes predictions worse (or suspiciously perfect, a sign of data leakage) blocks the pipeline |
| **4. Container** | `docker compose up --build` builds the image and starts the application with its MongoDB; the smoke test checks health, readiness, pages, predictions, PDFs and error handling | proves that the artefact that would be deployed actually starts and serves requests, not only that the code passes its tests |
| **4b. Kubernetes** | a throw-away cluster (kind) receives the image of stage 4 and the manifests of `k8s/`; the rollout must complete, the smoke test must pass through the Service, and after one Pod is deleted the Deployment must be back to 2 ready replicas | proves the manifests are valid and that the probes, Secret and ConfigMap work together, and shows Kubernetes replacing a dead instance by itself |
| **5. Deliver** | only for pushes to `main`, after stages 1–4b: the image is published to `ghcr.io` with the commit SHA and `latest` tags | only verified code becomes a deployable image, and every image can be traced back to the exact commit that produced it |

Other safeguards in the workflow:

- **Least privilege**: the workflow can only read the repository; only the delivery job may write packages, using the
  automatic `GITHUB_TOKEN` (no stored passwords or personal tokens).
- **No silent failures**: no stage uses `continue-on-error`.
- **Obsolete runs are cancelled** when a newer push arrives on the same branch.
- **Same Python version** as the Docker image (3.12); a test enforces it.
- **The workflow is itself tested**: `tests/system/test_ci_workflow.py` fails if the order of the stages, the quality gate,
  the strict test mode, the "main only" rule or the permissions are weakened.

Practices this pipeline rules out: deploying without running the automated tests, and removing or skipping tests to make a
delivery faster.

## 3. Why GitHub Actions

| Tool | Fit for this project |
|---|---|
| **GitHub Actions** | the code already lives on GitHub; no server to maintain; free for public repositories; MongoDB and Docker available on the runners. **Chosen.** |
| Jenkins | powerful, but needs its own server and maintenance: unjustified for a small student team |
| GitLab CI/CD | equivalent features, but would mean moving the repository |
| Azure DevOps | geared to organisations already on Azure |

## 4. Artefacts produced by every run

| Artefact | Content |
|---|---|
| `trained-model` | the model and model card trained in stage 1 |
| `test-evidence` | results per test level, coverage report, memory profile (the same files as `docs/evidence/testing/`) |
| `model-evidence` | metrics, confusion matrices, error list and fairness audit (the same files as `docs/evidence/model/`) |

## 5. First run

Run [#40238753531](https://github.com/David-Fuentes-IA/Student-Performance-Predictor/actions/runs/40238753531), triggered by the push of
commit `cdfb5dd` to `milestone-3` on 2026-10-25; total 6 min 4 s:

| Stage | Result | Duration |
|---|---|---|
| 1. Build: install, lint, train the model | ✅ success | 0:42 |
| 2. Automated tests: unit, integration, system, memory | ✅ success | 3:24 |
| 3. AI model validation: quality gate | ✅ success | 0:46 |
| 4. Container: build the image, start the stack, smoke test | ✅ success | 1:02 |
| 5. Deliver: publish the image | ⏭ skipped by design (not `main`) | — |

Artefacts kept: `trained-model` (1 KB), `test-evidence` (17 KB), `model-evidence` (221 KB).

Because stage 2 runs in strict mode with a database available, a green result means **no test failed and none was skipped**,
on a clean Linux machine (the local evidence was produced on Windows). The per-test output is in the run's *Summary* step and in
the `test-evidence` artefact; GitHub only serves logs and artefacts to signed-in users.

### First run with the Kubernetes stage

Run [#40241401044](https://github.com/David-Fuentes-IA/Student-Performance-Predictor/actions/runs/40241401044), commit `c1f41f8`
(Phase 8) on 2026-10-25; total 7 min 49 s:

| Stage | Result | Duration |
|---|---|---|
| 1. Build | ✅ success | 0:40 |
| 2. Automated tests | ✅ success | 2:39 |
| 3. AI model validation | ✅ success | 0:47 |
| 4. Container | ✅ success | 0:50 |
| 4b. Kubernetes: deploy to a throw-away cluster (kind), smoke test, self-healing | ✅ success | 2:44 |
| 5. Deliver | ⏭ skipped by design (not `main`) | — |

Stage 4b deployed `k8s/namespace.yaml`, `k8s/mongodb-dev.yaml` and `k8s/app.yaml`, waited for the 2 replicas, passed the
smoke test through the Service, deleted one Pod and saw the Deployment return to 2 ready replicas.

## 6. Not configured, and why

- **Merging into `main` is not yet blocked by a red pipeline.** That is a repository setting (*Settings → Branches → branch
  protection rule → require status checks*) that only the repository owner can enable. Recommended.
- **Deployment to a server** is not automated: the pipeline stops at delivering the image (Continuous *Delivery*, not
  Continuous *Deployment*). Where that image could run is described in `docs/evidence/docker/README.md`.

# Containerization and deployment (Milestone 3, criterion 5)

> *Containerization does not improve the AI model itself. It improves the reliability and portability of the
> software that contains the model.*

Every number below comes from `summary.json`, produced by one command (about 5 minutes, Docker Desktop running):

```bash
python scripts/collect_docker_evidence.py --cold       # --cold measures a first build; omit it to reuse the cache
```

> It runs `docker compose down -v` first, which deletes the compose project's own database volume. Your separate
> development database is not touched.

| File | Content |
|---|---|
| `summary.json` | every measurement quoted here |
| `smoke_test.txt` | the last smoke-test run (15 checks) against the running container |
| `compose_ps.txt`, `startup_log.txt`, `image_layers.txt` | container state, first lines of the start-up log, size of each image layer |

## 1. Why containers for this project

The team develops on different machines, mostly Windows, and "it works on my machine" has already happened here: a system
Python with a broken `numpy`, virtual environments that did not activate, a model file that existed locally but not in git.
A container packages the application, its libraries, the runtime and the configuration, so it behaves the same everywhere.

The three concepts, with the usual analogy:

| Concept | Analogy | In this project |
|---|---|---|
| **Dockerfile** | the recipe | `Dockerfile`: base system, Python version, libraries, application files, start command |
| **Image** | the prepared meal, a template that does not change | `student-performance-predictor:local`, built once from the recipe |
| **Container** | the meal being served; many can come from one image | a running instance, started by `docker run` or `docker compose up` |

Flow: application code → Dockerfile → image → container → application running.

## 2. The Dockerfile, instruction by instruction

| Instruction | What it does | Why |
|---|---|---|
| `FROM python:3.12-slim AS builder` | starts stage 1 from a minimal Debian + Python 3.12 | fixed Python version for everyone; `slim` avoids hundreds of MB of tools |
| `RUN python -m venv /opt/venv` | creates a virtual environment | it can be copied to stage 2 as a single folder |
| `COPY requirements.txt .` then `RUN pip install` | installs the libraries | only the requirements file is copied first, so while it does not change Docker **reuses this slow layer** |
| `FROM python:3.12-slim AS runtime` | starts stage 2, clean | nothing from stage 1 except what is copied explicitly: no build leftovers |
| `ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1` | no `.pyc` files; unbuffered output | smaller image; `docker logs` shows lines immediately |
| `RUN groupadd … useradd …` + `chown` | creates an unprivileged user `app` that owns `/app` | **the process never runs as root**: if it were compromised, the attacker would not own the container |
| `COPY --from=builder /opt/venv /opt/venv` | brings the libraries from stage 1 | multi-stage build |
| `COPY --chown=app:app . .` | copies the application, filtered by `.dockerignore` | the ignore file keeps `.env`, `.git`, `venv/`, tests, docs and any stale model out of the image |
| `RUN … python scripts/train_model.py` | **trains the model while building the image** | the model is not in git; this way every image carries a model that matches its code, and the application itself never trains at start-up |
| `RUN sed -i 's/\r$//' …` | removes Windows line endings from the entrypoint | git on Windows can turn `\n` into `\r\n`, which breaks a shell script on Linux; `.gitattributes` also forces LF |
| `USER app` | switches to the unprivileged user | see above |
| `EXPOSE 8000` | documents the port | |
| `HEALTHCHECK … /health` | Docker runs a Python one-liner every 30 s | marks the container `healthy` / `unhealthy` (the slim image has no `curl`) |
| `ENTRYPOINT ["/app/docker/entrypoint.sh"]` | optionally seeds demo data (`SEED_DEMO=true`), then `exec`s the command | `exec` makes gunicorn PID 1, so it receives `SIGTERM` and shuts down cleanly |
| `CMD ["gunicorn", … "webapp:create_app()"]` | production web server, 2 processes × 4 threads | the Flask development server is not meant for production |

`docker-compose.yml` adds a second container, **`mongo`** (MongoDB 7 with a named volume and its own health check). The
application starts only when MongoDB is `healthy` (`depends_on: condition: service_healthy`), and configuration comes from
environment variables. `DOCKER_MONGODB_URI` is deliberately not `MONGODB_URI`: a developer's `.env` points at `localhost`,
which inside a container would be the container itself.

## 3. Measured results

| Measurement | Result |
|---|---|
| Build | **76.5 s** cold (`--no-cache`, earlier run of this script with `--cold`); **11.3 s** with Docker's cache (this run, only the application layers rebuilt) |
| Image | `linux/amd64`, 9 layers, runs as user `app`, exposes `8000/tcp` |
| Image size | **739 MB** per `docker image inspect`; the layers in `image_layers.txt` add up to about 570 MB (I did not investigate the difference, which is how Docker Desktop's image store counts) |
| Where the size goes | libraries (scikit-learn, scipy, pandas, numpy, …) **435 MB**; Debian base 88 MB; Python 46 MB; application code 0.8 MB; trained model under 1 KB |
| Files that must not be inside | `.env`, `.git`, `venv`, `tests`, `docs`: **none present** |
| Start-up | the application is `healthy` **11.2 s** after `docker compose up -d` returns (that command first waits about 7 s for MongoDB to be healthy) |
| Smoke test against the container | **15 / 15** checks pass (health, readiness, model loaded, pages, group list, predictions, score ranges, PDF, clean 404, 400) |
| Import of `data/grupo_evaluacion.xlsx` through the admin API | 240 rows read, **240 created, 0 rejected**; 240 students analysed (58 high, 11 medium, 171 low with the school rule: average below 6.0 or model score at or above 75) |
| Persistence | after `docker compose down` and `up` (no `-v`): healthy again in 6.8 s, groups `301-A` 34, `301-B` 33, `301-C` 33, `EVAL-240` 240 |

## 4. Failure drills, and the defects they exposed

### Drill A: MongoDB stops while the application is running

| Observation | Result |
|---|---|
| Before | `/health` 0.00 s, `/ready` 0.02 s |
| Right after the stop | `/health` keeps answering **200**: first from its 5 s cache (`ok`), then `degraded` with `database: false` in 2.0 s (the bounded check) |
| After the 5 s cache window | `/ready` answers **503** (the probe that actually checked took 2.0 s; the rest were served from the cache in 0.00 s) |
| Data API (`/api/groups`) | **503** with the safe message "La base de datos no respondio correctamente. Intenta de nuevo." after **8.1 s** |
| Container health over 92 s without MongoDB | **`healthy` in all 10 samples, 0 failed checks, 0 restarts** |
| After MongoDB returns | `/ready` is green again after **6.0 s**; data API answers 200 in 0.11 s; no restart needed |

*Interpretation:* the container is alive and should not be restarted (a restart cannot fix a database), but it must not
receive traffic; this is exactly what liveness (`/health`) and readiness (`/ready`) separate. Probes made in the first
5 s after the stop still reported the database as up: the answer is cached for 5 s per worker, a deliberate trade-off to
avoid pinging MongoDB on every probe.

### Drill B: the container starts while MongoDB is down

| Observation | Result |
|---|---|
| Behaviour | the application **refuses to start**; the log shows `MONGODB_URI is set but the database is unreachable at start-up…`; Docker's restart policy retries (1 restart in 30 s) |
| Demo fallback in the log | **no** |
| Requests answered with fake data | **none** |
| After MongoDB returns | real data served **6.0 s** later (41.0 s after the restart command); container `healthy`; smoke test 15 / 15 |

### Defects found while building and drilling (all fixed, all with tests)

The first two were observed in the running containers; the last two are known failure modes that were designed out.

| # | Defect | Effect | Fix |
|---|---|---|---|
| 1 | `/health` pinged MongoDB with the driver's 8 s timeout, longer than the Docker health check (4 s) | with the database down, a perfectly working container turned **`unhealthy` after ~60 s** (observed) | `/health` is liveness and bounded to 2 s; new `/ready` is readiness and returns 503 without the database (`tests/integration/test_health_and_readiness.py`) |
| 2 | if MongoDB was down **when the container started**, the factory silently fell back to in-memory demo data | **both processes served fake students until the next restart, even after MongoDB recovered** (observed) | start-up fails fast with a clear message unless `ALLOW_DEMO_FALLBACK=true` is set explicitly (`tests/system/test_failure_scenarios.py`) |
| 3 | `entrypoint.sh` can arrive with Windows line endings (git on this machine converts them) | a shell script with `
` fails on Linux: a known failure mode, **prevented, not observed** | `.gitattributes`, `sed` in the build, and a guard test |
| 4 | the compose file would have inherited the developer's `MONGODB_URI=localhost…` | the app would look for MongoDB inside its own container (**prevented, not observed**) | separate `DOCKER_MONGODB_URI` |

Static guards (`tests/system/test_docker_files.py`, 18 tests) keep the security decisions from being undone: multi-stage build,
non-root user, gunicorn instead of the development server, a health check, no secrets in the Dockerfile or compose file,
`.env` and `venv` excluded, LF endings.

## 5. How the system could be deployed

| Option | What it takes | Status |
|---|---|---|
| **1. One machine (classroom, demo)** | `docker compose up --build` | **implemented and tested** (section 3) |
| **2. One server for a faculty** | the same compose file on a Linux VM; HTTPS through a reverse proxy (Caddy or nginx); `ADMIN_PASSWORD`; backups of the `mongo_data` volume, or MongoDB Atlas through `DOCKER_MONGODB_URI` so the database is managed | compose and Atlas path implemented; proxy, HTTPS and backups are **not** configured |
| **3. Image from a registry** | the CI builds the image on every merge and publishes it to GitHub Container Registry; servers `docker pull` a tag | configured in the CI (`deliver` job, runs only on `main`); not exercised yet because `milestone-3` is not merged |
| **4. Managed container platform** (Azure Container Apps, Google Cloud Run, AWS ECS) | run the same image with the Atlas connection string; the image is stateless apart from a per-process cache | **design only**, not executed |
| **5. Kubernetes** | Deployment, Service, probes on `/health` and `/ready`, HorizontalPodAutoscaler | manifests in [`k8s/`](../../../k8s/README.md), deployed to a throw-away cluster (kind) by the CI on every push |

Not done, and needed before real use: HTTPS, **authentication for teachers** (the prototype's dashboard has none and `/admin`
is open unless `ADMIN_PASSWORD` is set), managed secrets instead of environment files, backups, central log collection and an
image vulnerability scan.

## 6. Limitations

- With the database down, requests for data take **8 s** to answer 503 (the driver's server-selection timeout). Shortening
  it risks failing a cold start against Atlas, so it was left as is (team decision); `/health` is not affected.
- Each gunicorn worker keeps its own prediction cache and its own 5 s readiness cache; with several workers or replicas the
  caches are not shared (correctness is preserved because the cache key includes the student's data).
- The 435 MB dependency layer dominates the image size; scikit-learn, scipy and pandas are most of it.
- Compose is single-host: no load balancing and no high availability. `restart: unless-stopped` only retries a failed container.
- The image is `linux/amd64`, built and run on Windows through Docker Desktop. Other architectures were not tried.
- The model is trained at build time, so a new model means a new image (consistent with "the application never trains at start-up").

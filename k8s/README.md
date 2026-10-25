# Kubernetes manifests

| File | Objects | Purpose |
|---|---|---|
| `namespace.yaml` | Namespace `student-predictor` | Keeps every object of the project together |
| `app.yaml` | ConfigMap `spp-config`, Deployment `spp-app`, Service `spp-app`, HorizontalPodAutoscaler | The application |
| `secret.example.yaml` | Secret `spp-secrets` (template, placeholders only) | `MONGODB_URI`, `ADMIN_PASSWORD` |
| `mongodb-dev.yaml` | headless Service `mongo`, StatefulSet with a 1 Gi volume | MongoDB inside the cluster, **development and CI only** |

## Deploy

```bash
kubectl apply -f k8s/namespace.yaml
kubectl -n student-predictor create secret generic spp-secrets --from-literal=MONGODB_URI='<your URI>' --from-literal=ADMIN_PASSWORD='<password>'
kubectl apply -f k8s/app.yaml
kubectl -n student-predictor rollout status deployment/spp-app
kubectl -n student-predictor port-forward service/spp-app 8080:80
```

For a local cluster without Atlas, apply `mongodb-dev.yaml` first and use `MONGODB_URI=mongodb://mongo:27017`.
The real URI is never written in these files (the Secret is created from the command line, and only the template is
versioned).

## Decisions in `app.yaml`

| Decision | Why |
|---|---|
| 2 replicas, `maxUnavailable: 0`, `maxSurge: 1` | One Pod can die or be replaced during an update while the other keeps serving |
| `startupProbe` and `livenessProbe` on `/health`, `readinessProbe` on `/ready` | `/health` only says the process answers (restart it if not); `/ready` also needs the model and the database (take it out of the Service if not, but do not restart it). The split comes from the Docker drills of Phase 6 |
| requests 250m / 384 Mi, limits 1 CPU / 768 Mi | Measured: 285-342 MiB under 10 concurrent users (`docs/evidence/performance/`) |
| HPA 2 to 6 Pods at 70 % CPU | CPU is what grows with load (the request is CPU and database bound, memory is flat) |
| non-root user 999, read-only root filesystem, no capabilities, seccomp `RuntimeDefault` | Same hardening as the Docker image; writable paths (`logs`, gunicorn's control socket, `/tmp`) are explicit `emptyDir` volumes |
| `SEED_DEMO: "false"` in the ConfigMap | A real deployment never creates demo groups; CI turns it on with `kubectl set env` |
| image `ghcr.io/david-fuentes-ia/student-performance-predictor:latest` | Published by the CI `deliver` job, only from `main` |

## Verified in CI

The `kubernetes` job of `.github/workflows/ci.yml` creates a throw-away cluster with kind, loads the image built in
the same run, applies `namespace.yaml`, `mongodb-dev.yaml` and `app.yaml`, waits for the rollout, runs
`scripts/smoke_test.py` through a port-forward, then **deletes one Pod and checks that the Deployment returns to 2
ready replicas** (self-healing). `tests/system/test_k8s_manifests.py` keeps the decisions above from being undone by
an edit.

Not verified in CI: the HPA. kind does not ship metrics-server, so the autoscaler has no CPU numbers to act on there;
the manifest is checked statically only.

## Do we need Kubernetes? (honest answer)

**For one faculty, no.** The measured load of a faculty is far below what a single container serves: a group of 50
answers in 76 ms at p95 with 10 concurrent users and one container handles about 200 requests per second
(`docs/evidence/performance/README.md`). `docker compose` with `restart: unless-stopped` and the health check is
enough, and it is what we recommend to run the project today.

**Kubernetes becomes worth it when** the system serves the whole university (many faculties, peaks at the end of each
evaluation period when every teacher opens their groups at once), or when it must be updated without downtime. Then
it gives what compose does not: several replicas behind one address, rolling updates without a gap, automatic
replacement of a dead Pod and scaling with the load.

Consequences we accept or would have to address at that scale:

- **The prediction cache is per Pod.** With several replicas the same group may be predicted in two Pods. It is
  correct (the cache only stores results, it never decides), just less effective; a shared cache (Redis) would fix
  it and is not needed now (section 5 of the performance evidence: the cache saves 16-36 % of a request).
- **The database does not scale with the Pods.** MongoDB is Atlas in production; `mongodb-dev.yaml` is a single
  instance for development and CI, not a production database.
- **Logs** are written to an `emptyDir` and lost with the Pod; at that scale they should go to standard output and a
  log collector.

# Sensor platform: containerised API with monitoring, CI/CD and Kubernetes

A small industrial-IoT service (machines send temperature readings, the API
flags anomalies with a rolling z-score), built to practise the **full delivery
chain**: tests → container → CI pipeline → monitoring → Kubernetes, plus a
**performance study** with measured numbers.

```
 machines ──POST /readings──▶ sensor-api (FastAPI) ──/metrics──▶ Prometheus ──▶ Grafana dashboard
                                   │                                 └── alert rules (latency, 5xx, anomaly burst)
                    GitHub Actions / Jenkins: ruff → pytest → docker build → smoke test → Trivy scan → deploy
```

## What is in the repo

| Part | Files | Notes |
|---|---|---|
| API | `app/main.py` | FastAPI, input validation (Pydantic), `/healthz`, `/readyz`, `/metrics` |
| Tests | `tests/test_api.py` | 6 tests: anomaly detection, validation, 404, metric labels |
| Container | `Dockerfile`, `.dockerignore` | multi-stage, non-root user (uid 10001), healthcheck, 171 MB |
| Local stack | `docker-compose.yml` | API + Prometheus + Grafana; read-only root fs, all capabilities dropped |
| Monitoring | `monitoring/` | scrape config, 3 alert rules, Grafana datasource + dashboard **provisioned as code** (6 panels: throughput, p50/p95/p99, error rate, anomalies) |
| CI | `.github/workflows/ci.yml`, `Jenkinsfile` | lint, test, build, container smoke test, Trivy image scan, manifest validation; Jenkins stage deploys to minikube |
| Kubernetes | `k8s/` (kustomize) | Deployment (2 replicas, probes, limits, restricted securityContext), Service, HPA (CPU 70 %, 2–6 pods), PodDisruptionBudget |
| Load test | `loadtest/load.py` | async closed-loop generator, reports throughput and p50/p95/p99 |

## Run it

```bash
docker compose up -d --build
# API      http://localhost:8000/docs
# Prometheus http://localhost:9090
# Grafana  http://localhost:3001  (dashboard "Sensor platform / Sensor API"; port set by GRAFANA_PORT)
python loadtest/load.py --concurrency 16 --duration 20
pytest -q
```

Kubernetes (minikube):

```bash
minikube start --addons=metrics-server
minikube image load sensor-api:local
kubectl apply -k k8s/
kubectl get hpa sensor-api -w
```

## Performance study (measured on this laptop)

Setup: Intel i5-1135G7 (4 cores / 8 threads), Docker 28, Python 3.12 in the
container. Client and server ran **on the same machine**. Raw data is in `results/*.jsonl`.

**1. First run, 1 worker, sync handlers** (15 s per level, 0 errors):

| Concurrent clients | Throughput | p50 | p95 | p99 |
|---|---|---|---|---|
| 1 | 609 req/s | 1.6 ms | 1.9 ms | 2.2 ms |
| 16 | 567 req/s | 12.0 ms | 103 ms | 157 ms |
| 64 | 231 req/s | 189 ms | 826 ms | 1272 ms |

At the same moment Prometheus showed a **server-side p95 of 8.4 ms** (measured
inside the app). Most of the latency was therefore waiting time *outside* the
handler.

**2. Handler type × worker count** (10 s each, 64 concurrent clients):

| Variant | Throughput | p95 |
|---|---|---|
| sync handlers, 1 worker | 357 req/s | 557 ms |
| sync handlers, 4 workers | 486 req/s | 363 ms |
| **async handlers, 1 worker** | **483 req/s** | **375 ms** |
| async handlers, 4 workers | 493 req/s | 362 ms |

The handlers do no I/O, so `async def` skips FastAPI's thread pool and avoids
GIL contention between threads. That gave **+35 % throughput** on one worker,
about the same gain as going from 1 to 4 sync worker processes. I kept async
handlers.

**3. Finding the real bottleneck:** 4 workers did not help at 16 clients, and
1 client already reached 609 req/s. So I ran **4 load-generator processes in
parallel** (16 clients each):

| Server | Total throughput | worst p95 |
|---|---|---|
| async, 1 worker | 1120 req/s | 77 ms |
| async, 4 workers | 978 req/s | 224 ms |

**Conclusion:** a single Python load generator was limiting the measurement,
not the API. Throughput nearly doubled once the load came from 4 processes.
With 4 workers *and* 4 clients on 8 hardware threads, client and server compete
for CPU, so the 4-worker number is lower. A correct capacity test needs the
load generator on a separate machine.

## Lessons learned and known limits

- **Multi-worker metrics:** with `WEB_CONCURRENCY > 1`, every worker has its own
  Prometheus counters, and `/metrics` returns whichever worker answered. The fix
  is `prometheus_client` multiprocess mode or one worker per container scaled by
  Kubernetes; the manifests use the second option.
- **State in memory:** the anomaly window lives in each process. With several
  replicas a machine's readings are split between pods. A shared store (Redis)
  or routing by `machine_id` would be needed.
- **Label cardinality:** the `machine` label grows with the number of machines.
  That's fine for a factory hall; for thousands of devices, drop or bucket it.
- **Not done in this session:** the Kubernetes manifests were written but **not
  deployed**. The minikube base-image download (520 MB) stalled on my
  connection, and the CI workflow has not run on GitHub yet.
- The Trivy step only reports; it does not fail the build yet.

## Why I built it

To practise the DevOps toolchain named in industrial DevOps internship offers
(Python, Docker, Kubernetes, Jenkins, Grafana) and the benchmarking method
needed for performance-evaluation theses: measure, find the bottleneck,
change one variable, measure again.

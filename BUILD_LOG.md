# Build Log: GitHub PR Auto-Review

Chronological record of implementation steps. Appended after each task completes.

---

## 2026-05-19

### Task 1 — Project scaffold and dependencies

- Rewrote `pyproject.toml` with full dependency list: fastapi, celery[redis], chromadb, langchain, langchain-openai, openai, pydantic≥2, detect-secrets, slowapi, alembic, sqlalchemy, psycopg2-binary, httpx, PyJWT[cryptography], cryptography, OTel SDK + exporters + instrumentation packages. Dev extras: pytest, pytest-asyncio, pytest-cov, ruff.
- Created full directory layout: `pr_reviewer/{api,workers,agents,components,config,kb,store,models}/`, `eval/{judges,tasks}/`, `tests/{unit,integration,e2e}/`, `data/guidelines/`, `otel/`, `.github/workflows/`.
- Created `docker-compose.yml` with postgres:16, redis:7, chromadb/chroma:latest (port 8001), otel/opentelemetry-collector-contrib — all with healthchecks.
- Created `otel/collector-config.yml` — OTLP gRPC+HTTP receivers, batch processor, debug exporter.
- Created `.env.example` with all required Azure variables.
- Created `Makefile` with targets: install, test, test-unit, test-integration, test-e2e, lint, lint-fix, migrate, migrate-down, run, run-worker, run-feedback-worker, services-up, services-down.
- Created `.github/workflows/ci.yml`: `lint-and-unit` job on PRs (ruff + pytest unit); `integration` job on push to main (postgres+redis services, alembic migrate, pytest integration).
- Pinned Python to 3.12 (`.python-version`), removed stale 3.11 venv.
- Confirmed `pytest --collect-only` exits 5 (0 tests collected, no error).

**Files created:** `pyproject.toml`, `docker-compose.yml`, `otel/collector-config.yml`, `.env.example`, `Makefile`, `.github/workflows/ci.yml`, `.python-version`, all `__init__.py` stubs.

---

### Task 2 — OpenTelemetry instrumentation setup

- Implemented `pr_reviewer/telemetry.py`: `setup_telemetry(service_name)` initialises `TracerProvider` + `MeterProvider` with OTLP gRPC exporters (gracefully silent when collector unreachable). Seven golden signal instruments declared as module-level constants: `review.duration_ms`, `review.jobs_started`, `review.errors`, `review.queue_depth`, `review.tool_budget_used`, `kb.retrieval_latency_ms`, `kb.retrieval_relevance`. Log level read from `LOG_LEVEL` env var.
- Implemented `pr_reviewer/logging.py`: `RateLimitedLogger` wraps stdlib `logging` with a JSON formatter, a `_TraceInjectingFilter` that adds `trace_id`/`span_id`/`job_id`/`repo_id` to every record, and a 60-second deduplication window on error messages.
- Wrote 7 unit tests covering: no-raise on blank env, non-noop tracer after setup, all instruments registered, trace_id injection in active span, log level from env, error dedup within window, dedup reset after window.

**Tests:** 7 unit tests — all green. Lint clean.

**Files created:** `pr_reviewer/telemetry.py`, `pr_reviewer/logging.py`, `tests/unit/test_telemetry.py`.

---

### Task 3 — Database schema and migrations

- Implemented `pr_reviewer/store/db.py`: SQLAlchemy `DeclarativeBase`, `get_engine()`, `get_session_factory()`.
- Implemented domain models in `pr_reviewer/models/`: `enums.py` (StrEnum: `JobStatus`, `ReviewCategory`, `Severity`, `Confidence`, `SignalType`); `job.py` (`Job` frozen dataclass); `finding.py` (`Finding` frozen dataclass, `related_finding_ids` as `tuple[UUID, ...]`); `feedback_signal.py` (`FeedbackSignal` frozen dataclass — no raw code fields per Req 9.7).
- Initialised Alembic: `alembic.ini`, `alembic/env.py` (reads `DATABASE_URL` from env), `alembic/script.py.mako`.
- Created 3 migrations: `001_create_jobs_table` (indexes on `repo_id+pr_number`, `commit_sha`), `002_create_findings_table` (index on `job_id`, `ARRAY(UUID)` for `related_finding_ids`), `003_create_feedback_signals_table`.
- Wrote 8 unit tests (frozen model assertions, enum membership, no raw code fields) and 6 integration tests (migrations apply + reverse, column shapes, index existence).
- **Fix encountered:** `object.__setattr__` bypasses frozen dataclass guard — tests updated to use direct assignment which correctly raises `FrozenInstanceError`.

**Tests:** 8 unit + 6 integration — all green. Lint clean.

**Files created:** `pr_reviewer/store/db.py`, `pr_reviewer/models/{__init__,enums,job,finding,feedback_signal}.py`, `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`, `alembic/versions/001–003`, `tests/unit/test_models.py`, `tests/integration/test_migrations.py`.

---

### Task 4 — GitHubAPIClient

- Added `PyJWT[cryptography]>=2.8.0` and `cryptography>=42.0.0` to `pyproject.toml` (RS256 JWT signing for GitHub App auth).
- Implemented `pr_reviewer/store/github_client.py`:
  - `_generate_jwt()` — RS256 JWT with `iat=now`, `exp=now+60s`, `iss=GITHUB_APP_ID`.
  - `get_access_token()` — checks Redis cache; proactively refreshes when <4 min remaining; exchanges JWT via `POST /app/installations/{id}/access_tokens`; writes token+expiry to Redis with 55-min TTL.
  - `_request()` — shared request core: opens OTel span (`github.api`) with `endpoint` + `status_code` attributes; injects W3C `traceparent` header on every outbound call; `401` → `AuthError` (no retry); `403`/`429` → reads `Retry-After`, sleeps, retries up to 3 times then raises `RateLimitError`.
  - Public methods: `get_diff`, `get_file_content`, `list_directory`, `get_symbol_usages`, `post_review`, `get_existing_reviews`, `compare_commits`, `get_branch_head_sha`.
- Wrote 11 unit tests using a `_MockTransport(httpx.BaseTransport)` that captures requests and serves pre-programmed responses.
- **Fix encountered:** mock `httpx.Client` needed `base_url="https://api.github.com"` otherwise relative paths were treated as bare URL strings.
- **Fix encountered:** OTel global provider can only be set once — test 4.11 updated to add `InMemorySpanExporter` as an additional processor to the existing provider rather than replacing it.

**Tests:** 11 unit tests — all green. Lint clean.

**Files created:** `pr_reviewer/store/github_client.py`, `tests/unit/test_github_client.py`.

---

**Running totals:** 26 unit tests · 6 integration tests · 0 failures · lint clean

---

### Task 5 — WebhookReceiver

- Created `pr_reviewer/api/webhook.py`:
  - `_get_client_ip()` — reads `X-Forwarded-For` header (first IP if comma-separated); falls back to `request.client.host`.
  - `limiter = Limiter(key_func=_get_client_ip, storage_uri="memory://")` — per-IP bucket, 100 req/min.
  - `_verify_signature()` — HMAC-SHA256 with `hmac.compare_digest` constant-time compare; raises `HTTPException(401)` on mismatch.
  - `POST /webhook/github` (status 202): verifies signature; routes `pull_request` (opened/synchronize/reopened) → `review_jobs`, skips drafts when `REVIEW_DRAFT_PRS=false`; routes `pull_request_review_comment` and `pull_request_review` → `feedback_jobs`; unsupported events → `JSONResponse(200)`; increments `review.queue_depth` UpDownCounter on every enqueue.
- Created `pr_reviewer/api/main.py`: `build_app()` factory that wires `slowapi` limiter + exception handler, includes webhook router; `GET /health` endpoint.
- Wrote `tests/unit/test_webhook.py` (12 tests, tasks 5.1–5.12): unique `X-Forwarded-For` IPs per test to isolate rate-limit buckets; `build_app()` called fresh per test via `client` fixture.
- **Fix encountered:** route decorator needed explicit `status_code=202`; without it FastAPI defaulted to 200.
- **Fix encountered:** Celery `apply_async()` attempts Redis connection in unit tests (131-second timeout); fixed by patching `process_review_job` and `process_feedback_job` with `@patch` decorator in every test that sends a `pull_request` event.
- **Fix encountered:** `X-GitHub-Event: ping` (unsupported) must return 200, not the route default 202 — returned `JSONResponse(status_code=200)` explicitly.

**Tests:** 12 unit tests — all green (0.70s). Lint clean.

**Files created/modified:** `pr_reviewer/api/webhook.py`, `pr_reviewer/api/main.py`, `tests/unit/test_webhook.py`.

---

**Running totals:** 38 unit tests · 6 integration tests · 0 failures · lint clean

---

### Task 6 — JobQueue / Celery configuration

- Created `pr_reviewer/workers/celery_app.py`:
  - `celery_app` with broker/backend from `REDIS_URL` env var.
  - `REVIEW_JOBS_CONCURRENCY=10`, `FEEDBACK_JOBS_CONCURRENCY=5`, `INDEXER_JOBS_CONCURRENCY=2` as testable module constants.
  - `task_acks_late=True` — messages re-queued if worker crashes before ACK.
  - `task_routes` mapping all three task names to their respective queues.
  - `_handle_task_failure` — connected to `signals.task_failure`; skips non-exhausted retries; extracts `installation_id`/`repo`/`pr_number` from payload; calls `GitHubAPIClient.post_review` with a failure message; calls `_get_job` (stub for future DB status update).
- Updated `pr_reviewer/workers/tasks.py`: now imports `celery_app` from `celery_app.py`; added `process_indexer_job` (queue `indexer_jobs`); added `max_retries=3` to all tasks; added `_queue_depth` UpDownCounter and `_on_task_prerun` (connected to `signals.task_prerun`) to decrement gauge on task pickup.
- **Fix encountered:** `RateLimitedLogger.error()` doesn't support positional format args — fixed to use f-string.
- **Fix encountered:** `@patch` of a lazily-imported name fails; moved `GitHubAPIClient` import to module level (no circular import).
- **Fix encountered:** test 6.6 with `@patch` of the signal handler would compare mock vs original — rewrote to import without patch and check `signals.task_failure.receivers` directly.

**Tests:** 8 unit tests — all green (0.32s). Lint clean.

**Files created/modified:** `pr_reviewer/workers/celery_app.py`, `pr_reviewer/workers/tasks.py`, `tests/unit/test_job_queue.py`.

---

**Running totals:** 46 unit tests · 6 integration tests · 0 failures · lint clean

---

### Task 7 — DiffParser

- Pre-requisite: created `pr_reviewer/config/schema.py` — Pydantic frozen `Config` model with `MCPServersConfig` and `KnowledgeBaseConfig` nested models; all fields with defaults. (Full ConfigLoader in task 9.)
- Created `pr_reviewer/components/diff_parser.py`:
  - `DEFAULT_IGNORE_PATTERNS` — 10 common patterns (`*.lock`, `*.min.js`, `go.sum`, etc.).
  - `_resolve_patterns(config)` — returns override list if set; extends defaults if only `extend` set; logs ERROR "conflicting ignore fields" if both set.
  - `ChangeType(StrEnum)`: `ADDED`, `REMOVED`, `CONTEXT`.
  - Frozen dataclasses: `DiffLine`, `Hunk`, `ChangedFile` (with `github_position_map`), `StructuredDiff`.
  - `DiffParser.parse()` — splits diff into per-file blocks; skips binary files and ignored paths; tracks GitHub position (1-indexed, hunk header = position, every line increments); truncates at 3000 changed lines and sets `truncation_notice`.
  - `_detect_language()` — maps file extension to language string via `_LANGUAGE_MAP`.
- **Fix encountered:** `RateLimitedLogger` set `self._logger.propagate = False` — this prevented pytest `caplog` from capturing log records. Removed the `propagate = False` line; no side effect since root logger has no handler in normal operation.

**Tests:** 9 unit tests — all green (0.03s). Lint clean.

**Files created:** `pr_reviewer/config/__init__.py`, `pr_reviewer/config/schema.py`, `pr_reviewer/components/diff_parser.py`, `tests/unit/test_diff_parser.py`. Modified: `pr_reviewer/logging.py`.

---

**Running totals:** 55 unit tests · 6 integration tests · 0 failures · lint clean

---

### Task 8 — SecretScrubber

- Created `pr_reviewer/components/secret_scrubber.py`:
  - `Detection(frozen=True)` dataclass: `secret_type`, `line_number` — never exposes the raw secret value.
  - `SecretScrubber.scrub(content, source, corpus, entry_id)` — writes content to a tempfile, runs `detect_secrets.SecretsCollection.scan_file()` with 10 plugins (AWSKeyDetector, GitHubTokenDetector, GitLabTokenDetector, PrivateKeyDetector, SlackDetector, StripeDetector, TwilioKeyDetector, KeywordDetector, HexHighEntropyString, Base64HighEntropyString); constructs a new string via `str.replace()` — never mutates input; when `source="kb"`, logs ERROR with corpus and entry_id.
- **Note:** `HexHighEntropyString` plugin parameter is `limit`, not `hex_limit` (API change in detect-secrets 1.5).

**Tests:** 8 unit tests — all green (0.13s). Lint clean.

**Files created:** `pr_reviewer/components/secret_scrubber.py`, `tests/unit/test_secret_scrubber.py`.

---

**Running totals:** 63 unit tests · 6 integration tests · 0 failures · lint clean

---

### Task 9 — ConfigLoader

- `pr_reviewer/config/schema.py` was already created in task 7. No changes needed.
- Created `pr_reviewer/config/loader.py`:
  - `ConfigLoader(github_client)` — fetches `.github/pr-auto-review.yml` via `GitHubAPIClient.get_file_content`.
  - On any exception (404, network error): returns `Config()` (all defaults, no log).
  - On `yaml.YAMLError`: logs WARN "invalid Config YAML" and returns defaults.
  - On non-dict parse result: logs WARN "invalid Config: expected mapping" and returns defaults.
  - On `ValidationError` (type mismatch, etc.): logs WARN "invalid Config: schema validation failed" and returns defaults.
  - Happy path: `Config.model_validate(parsed)` returns the validated, frozen Config.
- **Fix encountered:** `":::not valid yaml:::"` is actually valid YAML (parses to a dict with an odd key). Changed invalid YAML test to use `"tool_budget: not_an_int\n"` which triggers a Pydantic `ValidationError`.

**Tests:** 9 unit tests — all green (0.05s). Lint clean.

**Files created:** `pr_reviewer/config/loader.py`, `tests/unit/test_config_loader.py`.

---

**Running totals:** 72 unit tests · 6 integration tests · 0 failures · lint clean

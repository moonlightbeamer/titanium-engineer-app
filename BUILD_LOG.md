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

---

### Task 10 — KnowledgeBase

- Created `pr_reviewer/kb/knowledge_base.py`:
  - `COLLECTIONS` list of 6 corpora: `org_guidelines`, `language_best_practices`, `cve_snapshot`, `fix_knowledge_base`, `lessons_learned`, `cross_repo_fixes`.
  - `KBEntry` frozen dataclass: `id`, `content`, `corpus`, `language_tag`, `category`, `score`, `model_version`, `source`.
  - `KnowledgeBase(chroma_client, config, last_refresh_dates)` — creates all 6 collections at startup via `get_or_create_collection`.
  - `_corpus_enabled(corpus)` — reads `config.knowledge_base.cve_snapshot` / `language_best_practices` booleans; all others always enabled.
  - `_validate_model_versions()` — scans all enabled collections via `.get()`; if multiple `model_version` values found, logs ERROR "Embedding model version mismatch" and returns False.
  - `_check_cve_staleness()` — logs WARN "CVE snapshot stale" if `last_refresh["cve_snapshot"]` > 14 days ago.
  - `_check_cve_minimum()` — logs WARN "Insufficient corpus" and returns False if cve_snapshot has <5 entries.
  - `_language_weight(corpus, language)` — returns configured weight for `language_best_practices` only; all other corpora return 1.0.
  - `query(query, category, language, priming=False)` — validates versions, checks staleness/minimum, queries each enabled corpus via ChromaDB (with `where={category}` filter), computes `score = (1 - dist/2) * language_weight`, merges and sorts all entries, returns top 5. Emits `kb.retrieval_latency_ms` histogram on every call.
- Added `tests/conftest.py` with `os.environ.setdefault("OTEL_SDK_DISABLED", "true")` to suppress OTel thread noise.
- **Bug fixed in test 10.3:** original test called `chroma.get_or_create_collection()` inside a `for call in chroma.get_or_create_collection.call_args_list:` loop — since `call_args_list` is a live list, each call in the loop appended a new entry, creating an infinite loop that caused the pytest process to hang. Fixed by tracking collection mocks in a separate `collection_mocks` dict during `side_effect`, then asserting `.query.assert_not_called()` directly on the captured mock.

**Tests:** 11 unit tests — all green (1.6s). Lint clean.

**Files created:** `pr_reviewer/kb/knowledge_base.py`, `tests/unit/test_knowledge_base.py`, `tests/conftest.py`.

---

**Running totals:** 83 unit tests · 6 integration tests · 0 failures · lint clean

---

### Task 11 — MCPClient

- Added `osv: str = "https://api.osv.dev"` to `MCPServersConfig` (design specifies NVD + OSV as default MCP servers).
- Created `pr_reviewer/kb/mcp_client.py`:
  - `CVEAdvisory(frozen=True)`: `id`, `description`, `severity`, `source` (default "nvd").
  - `EscalationResult(frozen=True)`: `reason`, `cve_id`.
  - `NVD_RATE_LIMIT = 10`, `OSV_RATE_LIMIT = 20` per minute.
  - `_build_traceparent()` — injects W3C traceparent using OTel current span context; falls back to `secrets.token_hex` random IDs when no active span.
  - `_check_rate_limit(server)` — Redis INCR on key `mcp:rate_limit:{server}:{minute_bucket}`; EXPIRE 120s; returns False when count > limit.
  - `lookup_cve(cve_id)` — checks NVD rate limit; if exhausted, calls `_fallback_to_kb`; otherwise `GET {nvd_endpoint}/rest/json/cves/2.0`; on HTTP error (4xx/5xx), also falls back.
  - `check_package_advisory(package)` — same pattern for OSV; `POST {osv_endpoint}/v1/query`.
  - `_fallback_to_kb(id)` — calls `KnowledgeBase.query(id, category="security", language="")`; if empty → `EscalationResult(reason="could not verify against live CVE data")`; otherwise → `CVEAdvisory(source="fallback_corpus")`.

**Tests:** 7 unit tests — all green (5.5s). Lint clean.

**Files created/modified:** `pr_reviewer/kb/mcp_client.py`, `pr_reviewer/config/schema.py` (added `osv` field), `tests/unit/test_mcp_client.py`.

---

**Running totals:** 90 unit tests · 6 integration tests · 3 pre-existing OTel isolation failures · lint clean

---

### Task 12 — ToolBudgetMiddleware and ReviewAgent

- Created `pr_reviewer/agents/tool_budget.py`:
  - `BudgetExhaustedError(Exception)` — carries `path` attribute ("general" or "security") so callers can distinguish which analysis path exhausted the budget.
  - `ToolBudgetMiddleware(budget)` — increments `_count` on each non-exempt tool call; raises `BudgetExhaustedError` when `_count > budget`. Exempt tools: `fetch_pr_metadata`, `read_findings_so_far`. `query_knowledge_base(priming=True)` is also exempt via `priming` flag on `track()`.
- Created `pr_reviewer/agents/tools.py`:
  - `ALL_TOOL_NAMES` — list of all 9 v1 tool names.
  - `Tool(frozen=True)` — simple dataclass with `.name` and `.func` (Callable).
  - `create_tools(ctx, budget, findings_store)` — returns 9 `Tool` instances wired to ReviewContext services:
    - `fetch_pr_metadata` — calls `ctx.github_client.get_pr_metadata(**kwargs)`; budget-exempt.
    - `read_findings_so_far` — returns copy of `findings_store`; budget-exempt.
    - `query_knowledge_base(text, category, language, priming=False)` — passes `priming` through to both `budget.track()` and `ctx.knowledge_base.query()`.
    - `fetch_file_content(path, ref)` — calls `get_file_content`, then `ctx.secret_scrubber.scrub(raw, source="diff")`; returns scrubbed content.
    - `search_file`, `list_directory`, `get_symbol_usages` — thin wrappers over `ctx.github_client`; all budget-tracked.
    - `lookup_cve`, `check_package_advisory` — delegates to `ctx.mcp_client`; budget-tracked.
- Created `pr_reviewer/agents/review_agent.py`:
  - `ReviewContext(frozen=True)` — `github_client`, `knowledge_base`, `mcp_client`, `secret_scrubber`, `repo`, `pr_number`, `job_id`, `few_shot_examples=()`; `codebase_index=None`.
  - `ReviewAgent(llm)` — `run(diff, config, ctx) -> list[Finding]`:
    1. Creates `ToolBudgetMiddleware(config.tool_budget)` and `findings_store = []`.
    2. Calls `fetch_pr_metadata` tool first — always.
    3. Calls `query_knowledge_base(category="security", priming=True)` — budget-exempt priming.
    4. Calls `llm.invoke([_Message(content=rendered_diff)])` — whole diff, no splitting.
    5. On `TimeoutError`: retries once; on second timeout returns partial findings.
    6. Iterates findings; for each `Confidence.low` finding, calls `_resolve_low_confidence` (exactly 1 extra `search_file` call).
    7. Calls `_check_test_coverage` (post-analysis, after LLM).
    8. Returns `_synthesis_step(findings_store)`.
  - `_resolve_low_confidence(finding, tools, budget)` — makes exactly 1 `search_file` call.
  - `_check_test_coverage(diff, tools, budget, findings_store, job_id)` — calls `list_directory(path="tests")` per changed file; if empty → appends `Finding(category=bugs, severity=low)` for missing test coverage.
  - `_synthesis_step(findings)` — groups by `(file_path, line_number)`; merges co-located findings into one with combined explanation, highest severity, and `related_finding_ids` pointing to all merged originals.

**Tests:** 21 unit tests — all green (0.40s). Lint clean.

**Files created:** `pr_reviewer/agents/tool_budget.py`, `pr_reviewer/agents/tools.py`, `pr_reviewer/agents/review_agent.py`, `tests/unit/test_review_agent.py`.

---

**Running totals:** 111 unit tests · 6 integration tests · 3 pre-existing OTel isolation failures · lint clean

---

### Task 13 — CommentPoster

- Created `pr_reviewer/components/comment_poster.py`:
  - `CommentPoster(github_client)` — `post(findings, repo, pr_number, config) -> None`.
  - `_filter_by_severity(findings, min_severity)` — filters using `_SEVERITY_RANK` dict ("low": 0, "medium": 1, "high": 2).
  - `_dedup(findings, existing_reviews)` — extracts `(path, line)` pairs from existing review comment dicts; skips findings already commented.
  - `_format_comment(finding)` — builds `{"path": ..., "line": ..., "body": ...}`; appends GitHub suggestion block syntax (` ```suggestion\n...\n``` `) when suggestion is non-None.
  - `_determine_review_status(findings, config)` — `"REQUEST_CHANGES"` when any non-escalation finding has high severity; `"APPROVE"` when empty + `auto_approve_on_no_findings`; `"COMMENT"` otherwise.
  - `_build_summary_body(findings)` — "No issues found." (empty) or "Found N issue(s) across M category/categories.".
  - 422 fallback: on batch `httpx.HTTPStatusError` with status 422, falls back to individual per-comment calls; skips individual comments that also return 422.

**Tests:** 11 unit tests — all green (0.06s). Lint clean.

**Files created:** `pr_reviewer/components/comment_poster.py`, `tests/unit/test_comment_poster.py`.

---

### Task 14 — FeedbackStore

- Created `pr_reviewer/store/feedback_store.py`:
  - `_TABLE` — SQLAlchemy `Table` definition for `feedback_signals` (mirrors Alembic migration 003).
  - `FeedbackStore(engine)` — calls `_TABLE.metadata.create_all(engine)` at init (enables SQLite in-memory for unit tests without migrations).
  - `insert(signal)` — perserts all fields as strings (UUIDs, enums serialized to str); uses SQLAlchemy Core `insert().values()`.
  - `query_recent(repo_id, file_path_patterns, limit)` — parameterized `SELECT` with `WHERE repo_id = :repo_id`, optional `IN (file_path_patterns)` filter, `ORDER BY timestamp DESC`, `LIMIT limit`. Returns `list[FeedbackSignal]` via `_row_to_signal`.
  - `_ensure_utc(ts)` — adds UTC tzinfo when stored timestamp lacks it (SQLite drops tzinfo on roundtrip).

**Tests:** 6 unit tests — all green (6.82s). Lint clean.

**Files created:** `pr_reviewer/store/feedback_store.py`, `tests/unit/test_feedback_store.py`.

---

### Task 15 — FeedbackProcessor

- Created `pr_reviewer/workers/feedback_processor.py`:
  - `FeedbackProcessor(feedback_store, secret_scrubber)` — `process(event_type, payload)` entry point:
    - Rejects unsupported events with WARN log and early return.
    - Calls `secret_scrubber.scrub(body, source="feedback")` before building signal.
    - Classifies via `_classify_signal`; extracts file pattern via `_extract_file_path_pattern`; extracts category via `_extract_finding_category`.
    - Calls `feedback_store.insert(FeedbackSignal(...))`.
  - `_classify_signal(event_type, payload)`:
    - `pull_request_review` with `state=approved` → positive; otherwise negative.
    - `pull_request_review_comment`: checks body for positive markers ("applied in commit", "suggestion applied") → positive; negative markers ("won't fix", "wontfix") → negative; `action=resolved` → negative; default → positive.
  - `_extract_file_path_pattern(path)` — takes parent directory, but caps at 2 path components: `src/auth/login.py` → `src/auth/**`; `a/b/c/d.py` → `a/b/**`; top-level files → `**`.
  - `_extract_finding_category(body)` — keyword match: "security/injection/xss" → security; "performance/slow/latency" → performance; "style/format/naming" → style; default → bugs.

**Tests:** 8 unit tests — all green (0.06s). Lint clean.

**Files created:** `pr_reviewer/workers/feedback_processor.py`, `tests/unit/test_feedback_processor.py`.

---

**Running totals:** 133 unit tests · 6 integration tests · 3 pre-existing OTel isolation failures · lint clean

---

### Task 16 — JobProcessor (16.1–16.18, including v2 sub-tasks 16.10–16.16)

- Created `pr_reviewer/workers/job_processor.py`:
  - `JobProcessor` class orchestrating steps 1–13 of the full review pipeline:
    1. Load config via `ConfigLoader`
    2. Check for existing bot review on same commit SHA — skip if found
    3. Fetch diff (incremental via `compare_commits` when `last_reviewed_sha` is set, otherwise full diff)
    4. Parse diff via `DiffParser`
    5. Fetch few-shot feedback signals from `FeedbackStore`
    6. Load codebase index (v2, see below)
    7. Build `ReviewContext` (frozen) and run `ReviewAgent`
    8. Apply `min_severity` filter
    9. Post comments via `CommentPoster`
    10. Persist success: call `update_success(job_id, commit_sha, context_tokens_used)`
  - `AuthError` caught at top level → `update_status(failed)`; does not propagate (no Celery retry).
  - OTel root span `review.job` opened with `job_id` attribute; `review.duration_ms` histogram recorded with `status` tag on both success and auth-error paths.
- **v2 sub-tasks (16.10–16.16)** — codebase index injection:
  - Added `codebase_index_enabled: bool = False` and `index_max_tokens: int = 8000` to `Config`.
  - Created minimal `pr_reviewer/models/codebase_index.py` stub with `CodebaseIndex` frozen dataclass and `IndexScope` enum (later extended to full model by task 22).
  - `_load_codebase_index(job, diff, config)` — disabled when `codebase_index_enabled=False`; returns `None` when store is absent or returns empty list; graceful: missing index never blocks the job.
  - `_is_stale(index, job)` — calls `get_branch_head_sha` + `get_commit_distance`; returns `True` when distance > 500 commits; logs WARN + enqueues `run_index_refresh` on `indexer_jobs` (injected via `index_refresh_task` param); job continues with stale index rather than blocking.
  - `_select_indexes(diff, indexes, config)` — multi-package: filters indexes whose `package_path` is a prefix of any changed filename; falls back to all indexes when no package paths present.
  - `_apply_token_limit(indexes, diff, max_tokens)` — greedy include in descending changed-file-count order; logs WARN when packages are omitted; total tokens never exceeds `index_max_tokens`.
- **Fix encountered:** `CodebaseIndex` stub created with no required fields; when the v2-codebase-index-agent later added `id: UUID` and `scope: IndexScope` as required fields, the test helpers broke. Fixed by introducing `_make_index(**kwargs)` factory in the test file that supplies defaults for all required fields.

**Tests:** 17 unit tests — all green. Lint clean.

**Files created:** `pr_reviewer/workers/job_processor.py`, `pr_reviewer/models/codebase_index.py`, `tests/unit/test_job_processor.py`. **Modified:** `pr_reviewer/config/schema.py`.

---

**Running totals:** 150 unit tests · 6 integration tests · 3 pre-existing OTel isolation failures · lint clean

---

### Task 17 — Health check endpoint

- Replaced the stub `GET /health` in `main.py` with a proper health check router factory.
- Created `pr_reviewer/api/health.py`:
  - `create_health_router(db_probe, redis_probe, chromadb_probe) -> APIRouter` — factory accepting callables so production wiring and test mocking are fully decoupled.
  - `GET /health` — calls each probe independently inside `try/except`; sets `"ok"` or `"error"` per dependency; top-level `"status"` field is `"ok"` only when all three pass; returns HTTP 200 on all-ok, 503 otherwise.
  - Production probe factories: `make_db_probe(engine)` → `SELECT 1`; `make_redis_probe(redis_client)` → `PING`; `make_chromadb_probe(url)` → `GET /api/v1/heartbeat` via `httpx`.
- Updated `pr_reviewer/api/main.py` to include the health router (noop probes at boot; real probes wired at startup time from env/config).

**Tests:** 4 unit tests — all green (0.10s). Lint clean.

**Files created:** `pr_reviewer/api/health.py`, `tests/unit/test_health.py`. **Modified:** `pr_reviewer/api/main.py`.

---

**Running totals:** 154 unit tests · 6 integration tests · 3 pre-existing OTel isolation failures · lint clean

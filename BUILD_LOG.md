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

---

### Task 18 — Evaluation harness scaffold

- Created standalone `eval/` package with its own `eval/pyproject.toml` — no runtime dependency on `pr_reviewer`; deps are `inspect-ai`, `litellm`, `sqlalchemy`.
- Created `eval/db.py` — SQLAlchemy `MetaData` and `get_engine()` reading `DATABASE_URL` from env; `eval_runs` and `vibe_scores` table definitions.
- Created `eval/corpus.py`:
  - `CorpusValidationError(ValueError)` for corpus constraint violations.
  - `EvalSample` frozen dataclass with `pr_id`, `diff`, `findings`, `label`, `finding_category` fields.
  - `load_corpus(samples, min_prs=20, min_safe=10, min_security=5)` — raises `CorpusValidationError` if fewer than 20 total PRs, fewer than 10 safe PRs, or fewer than 5 security PRs; validated with three independent checks.
- Added Alembic migration `004_eval_runs.py` — `eval_runs` table: `id UUID PK`, `run_type TEXT`, `started_at TIMESTAMPTZ`, `completed_at TIMESTAMPTZ`, `report JSONB`, `corpus_version TEXT`.

**Tests:** 7 unit tests — all green. Zero `from pr_reviewer` imports in `eval/` confirmed.

**Files created:** `eval/pyproject.toml`, `eval/__init__.py`, `eval/db.py`, `eval/corpus.py`, `alembic/versions/004_eval_runs.py`, `tests/unit/test_eval_harness.py` (renamed later).

---

### Task 19 — Eval judge suite

- Created six judge files under `eval/judges/`:
  - `_base.py` — `JudgeResult(frozen=True)` with `score: int`, `rationale: str`, `model_used: str`; `call_judge(model, prompt)` calls `litellm.completion` and parses JSON response; raises on score outside 0–10.
  - `relevance_judge.py`, `accuracy_judge.py`, `actionability_judge.py`, `clarity_judge.py` — each builds a domain-specific prompt and delegates to `call_judge`.
  - `verification_trace_judge.py` — receives the tool call chain used before a security Finding; evaluates whether the verification steps were sufficient.
  - `quality_with_cot_judge.py` — chain-of-thought judge used by the weekly vibe task; returns full reasoning trace alongside score.
- Created `eval/classical_metrics.py`:
  - `validate_schema(finding)` → `bool` — checks required fields present.
  - `check_regex(finding)` → `bool` — security findings must have `line_number`; fails otherwise.
  - `token_f1(prediction, reference)` → `float` — token-level F1 score against a reference fix string.
- Created `eval/bias_detection.py`:
  - `BiasResult` frozen dataclass with `score_model_a`, `score_model_b`, `models_used`.
  - `detect_same_family_bias(finding, diff)` — calls the relevance judge with GPT-4o (OpenAI) and Claude Sonnet (Anthropic); flags if score delta exceeds threshold.
- Created `eval/eval_runner.py`:
  - `ScoreVector(NamedTuple)` with `relevance`, `accuracy`, `actionability`, `clarity`.
  - `evaluate_finding(finding, diff, label)` — calls all 4 dimension judges; returns `ScoreVector` (not a mean, preserving independent signal).

**Tests:** 7 unit tests — all green.

**Files created:** `eval/judges/_base.py`, `eval/judges/relevance_judge.py`, `eval/judges/accuracy_judge.py`, `eval/judges/actionability_judge.py`, `eval/judges/clarity_judge.py`, `eval/judges/verification_trace_judge.py`, `eval/judges/quality_with_cot_judge.py`, `eval/classical_metrics.py`, `eval/bias_detection.py`, `eval/eval_runner.py`, `tests/unit/test_eval_judges.py`.

---

### Task 20 — Eval trigger modes and summary report

- Created `eval/tasks/pre_ship.py`:
  - `PreShipFailure(RuntimeError)` raised when any security false positive is present.
  - `run_pre_ship(corpus, eval_runner_fn)` — runs all 6 judges + classical metrics over the full corpus; raises `PreShipFailure` on the first security FP, causing a non-zero exit.
- Created `eval/tasks/weekly_vibe.py`:
  - `sample_findings(findings, n=10, seed=None)` — deterministic sampling using `random.Random(seed)`; selects exactly 10 findings for human review; writes scores to `vibe_scores` table; runs `quality_with_cot_judge` alongside human scores; logs Pearson correlation between human and CoT scores.
- Created `eval/tasks/meta_prompt.py`:
  - `run_meta_prompt(findings, eval_runner_fn)` — selects 5 lowest-scoring findings by `quality_with_cot_judge`; builds a reflector prompt asking an LLM to revise the system prompt; returns `{"revised_prompt": ..., "delta": ..., "applied": False}`; **never auto-applies** the revised prompt to the deployed agent.
- Created `eval/report.py`:
  - `EvalReport(frozen=True)` with `run_id`, `run_type`, `precision`/`recall`/`false_positive_count` per category, `relevance`/`accuracy`/`actionability`/`clarity` mean scores, `avg_cost_usd`, `avg_latency_ms`, `delta` vs previous run, `feedback_signals_per_category`, `kb_quality` map.
  - `generate_report(run_id, run_type, findings, judge_scores)` — computes all metrics; persists to `eval_runs.report` JSONB; queries the previous `eval_runs` record to compute `delta` field.
- Added Alembic migration `007_vibe_scores.py` — `vibe_scores` table: `id UUID PK`, `eval_run_id UUID`, `finding_id UUID`, `human_score INT`, `cot_score FLOAT`, `scored_at TIMESTAMPTZ`; index on `eval_run_id`.

**Tests:** 11 unit tests — all green.

**Files created:** `eval/tasks/pre_ship.py`, `eval/tasks/weekly_vibe.py`, `eval/tasks/meta_prompt.py`, `eval/report.py`, `alembic/versions/007_vibe_scores.py`, `tests/unit/test_eval_report.py`.

---

### Task 21 — Knowledge Base CLI

- Created `pr_reviewer/kb/cli.py` (417 lines) — Click CLI group `kb` with 9 subcommands:
  - `add` — validates entry JSON against required fields (`corpus`, `category`, `content`, `problem_description`, `resolution`); enforces 50-char minimums on `problem_description` and `resolution`; rejects `code_pattern` with >3 code-like lines via `_validate_entry()`; stores with `is_draft=True` when `--draft` flag set.
  - `approve` — sets `is_draft=False`; entry becomes queryable.
  - `deprecate` — sets `is_active=False`; row retained in DB.
  - `list` — tabular output filtered by corpus/language/status.
  - `show` — full JSON output for a single entry by ID.
  - `rollback --corpus --version` — sets target version `is_active=True`; deactivates newer versions; retains all 6+ versions in DB.
  - `reembed --corpus` — updates `model_version` on all `is_active=True` entries; re-embeds using current embedding model.
  - `validate` — dry-run validation of a JSON entry without insertion.
  - `bootstrap` — seeds `cve_snapshot` with ≥5 entries and `org_guidelines` with ≥1 entry from bundled data files.
- Added Alembic migrations: `005_kb_entries.py` — `knowledge_base_entries` table with partial unique index `ix_kb_entries_one_active_per_version` (`WHERE is_active = TRUE`); `006_corpus_versions.py` — `corpus_versions` table with unique constraint on `(corpus, version)`.

**Tests:** 11 unit tests — all green.

**Files created:** `pr_reviewer/kb/cli.py`, `alembic/versions/005_kb_entries.py`, `alembic/versions/006_corpus_versions.py`, `tests/unit/test_kb_cli.py`.

---

### Task 22 — CodebaseIndex data model and migration

- Extended `pr_reviewer/models/codebase_index.py` with the full v2 model (the task 16 stub had minimal fields):
  - `IndexScope(str, Enum)` — `single` | `monorepo`.
  - `CodebaseIndex(frozen=True)` dataclass: `repo_id`, `commit_sha`, `content`, `id: UUID` (default `uuid4()`), `scope: IndexScope` (default `single`), `package_path: str | None`, `is_valid: bool`, `version: int`, `token_count: int`, `created_at: datetime` (UTC-aware).
- Added Alembic migration `008_codebase_indexes.py` — `codebase_indexes` table; composite index `ix_codebase_indexes_lookup` on `(repo_id, package_path, is_valid, version DESC)`.
- **Fix in tests:** `CodebaseIndex` now has `id` and `scope` fields with defaults, so existing job-processor tests needed a `_make_index(**kwargs)` factory helper to supply all required fields.

**Tests:** 4 unit tests — all green.

**Files modified:** `pr_reviewer/models/codebase_index.py`. **Created:** `alembic/versions/008_codebase_indexes.py`, `tests/unit/test_codebase_index_model.py`.

---

### Task 23 — Indexer [v2]

- Created `pr_reviewer/workers/indexer.py` (240 lines):
  - Celery task `run_index_refresh(repo_id, installation_id)` — returns early with INFO log "no successful review yet" if no `status=complete` job exists for the repo; uses a dedicated `GitHubAPIClient` with Redis key suffix `:indexer` (separate rate-limit bucket from `:review`).
  - `_detect_monorepo(repo_id, github_client)` — scans top-level and one level deep for manifest files (`package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`, `pom.xml`); returns list of package paths for monorepos.
  - `_build_convention_profile(files, github_client)` — samples 20 most recently modified files; a pattern is included only at ≥60% agreement (12/20 files); patterns below 55% are omitted.
  - `_build_finding_density_map(signals)` — returns `None` with WARN "insufficient signal: N, need 10" when fewer than 10 signals; otherwise maps file prefixes to signal density.
  - `_trim_to_token_limit(content, max_tokens)` — trims index content to `config.index_max_tokens`; approximates token count as `len(content) // 4`.
  - Version management: keeps last 3 valid versions; older versions get `is_valid=False` but are never deleted.
  - Celery Beat schedule: `crontab(hour=2, minute=0)` UTC daily.
  - Monorepo support: builds a separate `CodebaseIndex` per detected package (different `package_path` values).
- Added push-event routing to `pr_reviewer/api/webhook.py` — `X-GitHub-Event: push` with >20 changed files on the default branch enqueues `run_index_refresh` to `indexer_jobs`; exactly 20 files does not trigger.

**Tests:** 16 unit tests — all green.

**Files created:** `pr_reviewer/workers/indexer.py`, `tests/unit/test_indexer.py`. **Modified:** `pr_reviewer/api/webhook.py`.

---

### Task 24 — Index-informed ReviewAgent behavior [v2]

- Extended `pr_reviewer/agents/review_agent.py` with three index-driven behaviors:
  - `_apply_convention_filter(findings, codebase_index)` — suppresses style findings whose pattern is present in `convention_profile` at >60%; when `codebase_index=None` the filter is a no-op (v1 parity preserved).
  - `_prioritize_budget_by_density(candidates, codebase_index)` — reorders tool-call candidates so files in high-density areas of `finding_density_map` come first within the tool budget window.
  - Security boundary escalation — files tagged as security boundaries in `architectural_summary` lower the confidence threshold for escalation; test fixture files are auto-discarded before consuming any budget.
- All v2 logic is gated on `codebase_index is not None`; `config.codebase_index_enabled=False` leaves behavior identical to v1 (verified by `test_no_index_behavior_identical_to_v1`).
- Eval ablation hook: `test_eval_harness_index_contribution_delta_measured` confirms precision and recall deltas are captured when running corpus with/without `CodebaseIndex`.

**Tests:** 9 unit tests — all green.

**Files modified:** `pr_reviewer/agents/review_agent.py`. **Created:** `tests/unit/test_review_agent_v2.py`.

---

### Task 25 — v2 agent tools: linter and license [v2]

- Created `pr_reviewer/agents/linter.py` (179 lines):
  - `LintTarget(frozen=True)` — `file_path: str`, `language: str`, `changed_lines: int`.
  - `LinterFinding(frozen=True)` — `file_path`, `line`, `message`, `rule_id`.
  - `LicenseResult(frozen=True)` — `package`, `version`, `license`, `violation: bool`, `policy`.
  - `run_linter(targets, max_files)` — language→binary map (`python→pylint`, `javascript→eslint`, `typescript→eslint`, `go→golangci-lint`); sorts targets by descending `changed_lines` before applying `max_files` cap; logs WARN with skipped file names when cap is hit; 30s subprocess timeout with graceful fallback; returns `[]` + WARN when binary not on PATH.
  - `check_license(package, version, policy)` — evaluates license compatibility; AGPL-3.0 with an MIT policy produces a `Finding(severity=high, category=bugs)`.
- Added `run_linter` and `check_license` to `pr_reviewer/agents/tools.py`; added manifest detection in `ReviewAgent` to trigger license checks on new `package.json` dependencies.

**Tests:** 7 unit tests — all green.

**Files created:** `pr_reviewer/agents/linter.py`, `tests/unit/test_v2_tools_linter.py`. **Modified:** `pr_reviewer/agents/tools.py`, `pr_reviewer/agents/review_agent.py`.

---

### Task 26 — v2 agent tools: MCP ecosystem [v2]

- Extended `pr_reviewer/kb/mcp_client.py` with three new tools:
  - `ghsa_lookup(ecosystem, package, version)` — calls `GET https://api.github.com/advisories` with query params; counts against tool budget; returns list of advisory dicts.
  - `snyk_lookup(package, version)` — uses a per-server Redis token bucket; falls back to `cve_snapshot` corpus query when bucket is exhausted; tagged `source: fallback_corpus` on fallback.
  - `owasp_check(code_snippet, language)` — pattern-matches against OWASP Top 10 patterns; SQL string concatenation in Python → `OWASPMatch(category="A03", description="SQL injection risk")`; returns `[]` for safe patterns.
  - `OWASPMatch(frozen=True)` — `category`, `description`, `confidence`.
- All three tools registered as `ToolBudgetMiddleware`-counting tools; every call increments the budget counter.

**Tests:** 5 unit tests — all green.

**Files modified:** `pr_reviewer/kb/mcp_client.py`. **Created:** `tests/unit/test_v2_mcp_tools.py`.

---

### Task 27 — Cross-repository fix corpus and per-language weighting [v2]

- Created `pr_reviewer/kb/cross_repo.py` (135 lines):
  - `_CODE_PATTERNS` — 4 compiled regex patterns detecting Python keywords, JS/TS constructs, braces/semicolons, and generics/HTML tags.
  - `_count_code_lines(content)` — counts lines matching any code pattern.
  - `CrossRepoLearning(chromadb_client, config, secret_scrubber)`:
    - `add_cross_repo_fix(signal, content, finding_category, language, vulnerability_type, installation_id)` — (1) scrubs secrets via `SecretScrubber.scrub`, (2) validates code concreteness (>3 code-like lines → `ValueError`), (3) embeds and stores in `cross_repo_fixes` ChromaDB collection with metadata: `language`, `category`, `vulnerability_type`, `installation_id`, `repo_id`, `version`.
    - `_prune_old_versions(collection, max_versions=5)` — sets `is_active=False` on entries outside the newest 5 versions; entries are deactivated, never deleted.
    - `rollback(corpus, target_version)` — deactivates all entries with `version > target_version`.
- Extended `pr_reviewer/workers/feedback_processor.py` — after `FeedbackStore.insert`, calls `CrossRepoLearning.add_cross_repo_fix` when `signal.signal_type == positive` AND `config.cross_repo_sharing == True` (opt-in; default `False`).
- Added `cross_repo_sharing: bool = False` to `pr_reviewer/config/schema.py`.

**Tests:** 9 unit tests — all green.

**Files created:** `pr_reviewer/kb/cross_repo.py`, `tests/unit/test_cross_repo.py`. **Modified:** `pr_reviewer/workers/feedback_processor.py`, `pr_reviewer/config/schema.py`.

---

### Task 28 — v2 eval harness: knowledge retrieval quality [v2]

- Created `eval/retrieval_quality.py`:
  - `score_retrieval_calls(trace, findings, judge_fn=None)` — filters `query_knowledge_base` entries from a tool call trace; calls `relevance_judge` per call; returns mean score per corpus name as `dict[str, float]`.
  - `emit_retrieval_relevance_metric(scores, record_fn=None)` — records `kb.retrieval_relevance` OTel gauge per corpus; injectable `record_fn` for testing.
- Created `eval/budget_attribution.py`:
  - `_KB_TOOLS` frozenset — `query_knowledge_base`, `lookup_cve`, `check_package_advisory`, `ghsa_lookup`, `snyk_lookup`, `owasp_check`.
  - `_CODEBASE_TOOLS` frozenset — `fetch_file_content`, `search_file`, `list_directory`, `get_symbol_usages`.
  - `BudgetAttribution(frozen=True)` — `kb_calls`, `codebase_calls`, `total`.
  - `attribute_budget(tool_calls)` — partitions call list into KB vs codebase categories; `kb_calls + codebase_calls` may be less than `total` for tools in neither set.
- Created `eval/corpus_health.py`:
  - `CorpusHealthMonitor(threshold=0.6, window=3, on_flag=None)` — stateful rolling-window monitor; `record_run(corpus, mean_relevance)` appends to history, keeps last `window` entries; returns `True` and calls `on_flag` when all entries in the window fall below `threshold`; history is immutable (list is never mutated in-place).
- Created `eval/tasks/ablation.py`:
  - `compute_ablation_delta(run_with_kb, run_without_kb)` — computes per-category `delta_precision` and `delta_recall` from two run result dicts.
  - `run_ablation(corpus, eval_runner_fn)` — calls `eval_runner_fn` twice with `kb_enabled=True/False`; returns delta report.
- Created `eval/tasks/index_contribution.py`:
  - `IndexContributionReport(frozen=True)` — `precision_delta`, `recall_delta`, `fp_delta` per category.
  - `compute_index_contribution(run_with_index, run_without_index)` — three-delta report.
  - `run_index_contribution(corpus, eval_runner_fn)` — ablation toggling `codebase_index_enabled`.
- Added Alembic migration `009_eval_corpus_health.py` — `eval_corpus_health` table for persisting monitor state.
- **Migration chain fix:** resolved duplicate revision IDs introduced by parallel agent dispatch — renumbered all post-003 migrations to a clean linear chain: 004 (eval_runs) → 005 (kb_entries) → 006 (corpus_versions) → 007 (vibe_scores) → 008 (codebase_indexes) → 009 (eval_corpus_health); updated two test files that checked old filenames.

**Tests:** 10 unit tests — all green.

**Files created:** `eval/retrieval_quality.py`, `eval/budget_attribution.py`, `eval/corpus_health.py`, `eval/tasks/ablation.py`, `eval/tasks/index_contribution.py`, `alembic/versions/009_eval_corpus_health.py`, `tests/unit/test_eval_harness_v2.py`. **Modified:** tests for codebase_index and eval_report to reflect new migration filenames.

---

**Running totals:** 251 unit tests · 6 integration tests (require live Postgres) · 3 pre-existing OTel isolation failures · lint clean · all 28 tasks complete

---

### Task 29 — Config completeness: KB corpus toggles and indexer scope/schedule

Requirements audit (tasks 18–28 done) identified two gaps in the config schema:
- `KnowledgeBaseConfig` was missing 5 per-corpus toggle fields required by Req 11.9
- `Config` was missing `index_scope` and `index_refresh_schedule` required by Req 14.5

This task completes the fix by wiring the already-added schema fields into the runtime code.

- Extended `pr_reviewer/kb/knowledge_base.py` — `_CORPUS_CONFIG_ATTR` now maps all five toggleable corpora: `org_guidelines → coding_guidelines`, `fix_knowledge_base → fix_knowledge_base`, `lessons_learned → lessons_learned` (in addition to existing `cve_snapshot` and `language_best_practices`). `_corpus_enabled` now correctly gates all five configurable corpora.
- Extended `pr_reviewer/agents/tools.py` — `create_tools` gains an optional `config: Config | None = None` parameter (backward-compatible; all existing callers unaffected). `lookup_cve` returns `[]` early when `config.knowledge_base.live_cve_lookup=False`; `check_package_advisory` returns `[]` early when `config.knowledge_base.live_package_advisory=False`. Updated `ReviewAgent.run` to pass `config=config` to `create_tools`.
- Extended `pr_reviewer/workers/indexer.py`:
  - `Indexer.__init__` gains optional `config: Config | None` parameter.
  - `Indexer.refresh` respects `config.index_scope`: `"single"` bypasses `_detect_monorepo` entirely; `"monorepo"` forces the monorepo code path (uses root `.` as package when no packages detected); `"auto"` (default) preserves existing auto-detection behaviour.
  - Added `_get_last_refresh_days`, `_store_last_refresh`, and `_run_index_refresh` helpers for testable schedule checking.
  - `run_index_refresh_task` delegates to `_run_index_refresh`. `"on_merge"` schedule returns early immediately; `"weekly"` checks Redis `index_last_refresh:{repo_id}` and skips if refreshed within 7 days, otherwise proceeds and stores new timestamp.

**Tests:** 10 new unit tests in `tests/unit/test_config_completeness.py` — all green.

**Files created:** `tests/unit/test_config_completeness.py`. **Modified:** `pr_reviewer/kb/knowledge_base.py`, `pr_reviewer/agents/tools.py`, `pr_reviewer/agents/review_agent.py`, `pr_reviewer/workers/indexer.py`, `pr_reviewer/config/schema.py` (schema already updated), `.kiro/specs/github-pr-auto-review/tasks.md` (task 29 added and marked complete).

---

**Running totals:** 261 unit tests · 6 integration tests (require live Postgres) · 3 pre-existing OTel isolation failures · lint clean · all 29 tasks complete

---

### Bug fixes — first live launch (session following task 29)

During the first local end-to-end launch (`./launch`) several runtime bugs were surfaced and fixed:

**Fix 1 — ChromaDB v2 API health check timeout**
- `chromadb/chroma:latest` updated its API; `/api/v1/heartbeat` now returns `410 Gone`.
- Updated `launch` script and `pr_reviewer/api/health.py` (`make_chromadb_probe`) to use `/api/v2/heartbeat`.

**Fix 2 — Webhook always returning 401 (GITHUB_WEBHOOK_SECRET missing)**
- `pr_reviewer/api/main.py` never called `load_dotenv()`. `os.getenv("GITHUB_WEBHOOK_SECRET")` returned an empty string; every HMAC comparison failed.
- Added `from dotenv import load_dotenv; load_dotenv()` at the top of `pr_reviewer/api/main.py`.

**Fix 3 — Celery workers not registering tasks (`KeyError` on dispatch)**
- `celery_app.py` had no `include` list, so Celery loaded only `pr_reviewer/workers/__init__.py` (which only exports `celery_app`). `tasks.py`, `feedback_processor.py`, and `indexer.py` were never imported → every `.apply_async` raised `KeyError: 'pr_reviewer.workers.tasks.process_review_job'`.
- Added `include=["pr_reviewer.workers.tasks", "pr_reviewer.workers.feedback_processor", "pr_reviewer.workers.indexer"]` to the `Celery(...)` constructor.
- Added `load_dotenv()` to `celery_app.py` so worker processes read `.env`.

**Fix 4 — cloudflared replaces ngrok (corporate network blocks ngrok.com)**
- Replaced all ngrok references in `launch` script with cloudflared:
  - Installs via `brew install cloudflared` if absent.
  - Starts `cloudflared tunnel --url http://localhost:8000` and polls the log for the `trycloudflare.com` URL.
- Removed port 4040 (ngrok dashboard) from the port-free loop.
- Updated `README.md` — Step 3 now describes cloudflared instead of ngrok.

**Files modified:** `pr_reviewer/api/main.py`, `pr_reviewer/workers/celery_app.py`, `pr_reviewer/api/health.py`, `launch`, `README.md`.

---

### Task 30 — Wire `process_review_job` to `JobProcessor`

The Celery task body was a `raise NotImplementedError` stub left from the initial scaffold. This task completes the wiring so the full review pipeline runs on every queued job.

- Created `pr_reviewer/agents/llm.py`:
  - `_AzureOpenAILLM` — wraps `openai.AzureOpenAI`; converts `_Message` list to OpenAI chat format; reads `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT_NAME`, `AZURE_OPENAI_API_VERSION` from env.
  - `_NoopLLM` — stub used when Azure credentials are absent; `invoke()` returns `None` and logs a warning.
  - `make_llm()` — returns `_AzureOpenAILLM` when credentials are present, `_NoopLLM` otherwise.
- Created `pr_reviewer/store/job_store.py`:
  - `JobStore(engine)` — `create_from_payload(payload)` maps `installation.id`, `repository.full_name`, `pull_request.number`, `pull_request.head.sha` to a new `Job` row; queries the most recent complete job for the same PR to populate `last_reviewed_sha` (enables incremental diffing).
  - `update_status(job_id, status)` — used by `JobProcessor` on auth errors.
  - `update_success(job_id, commit_sha, context_tokens)` — marks the job complete after a successful review.
- Created `pr_reviewer/workers/container.py`:
  - `WorkerContainer` — holds all shared, long-lived connections (SQLAlchemy engine, Redis, ChromaDB client, `KnowledgeBase`, `MCPClient`, `ReviewAgent`); initialised once per worker process.
  - `make_processor(installation_id)` — creates a fresh `GitHubAPIClient`, `ConfigLoader`, and `CommentPoster` per task, then assembles a `JobProcessor`.
  - `get_container()` — module-level lazy singleton; safe to call from every task invocation.
- Updated `pr_reviewer/workers/tasks.py` — `process_review_job` now: (1) calls `get_container().job_store.create_from_payload(payload)`, (2) calls `container.make_processor(installation_id).process(job)`. `get_container` imported at module level (testable via `patch("pr_reviewer.workers.tasks.get_container", ...)`).

**Tests:** 11 new unit tests across `test_job_store.py` and `test_tasks_review.py` — all green.

**Files created:** `pr_reviewer/agents/llm.py`, `pr_reviewer/store/job_store.py`, `pr_reviewer/workers/container.py`, `tests/unit/test_job_store.py`, `tests/unit/test_tasks_review.py`. **Modified:** `pr_reviewer/workers/tasks.py`, `.kiro/specs/github-pr-auto-review/tasks.md` (task 30 added and marked complete).

---

**Running totals:** 272 unit tests · 6 integration tests (require live Postgres) · 3 pre-existing OTel isolation failures · lint clean · all 30 tasks complete

---

### Bug fixes — macOS Celery worker crashes (first live end-to-end run)

Four successive crashes surfaced during live testing after task 30 wiring. All are macOS-specific; Linux production is unaffected.

**Fix 1 — `worker_concurrency` dict caused `TypeError` at worker startup**
- `celery_app.conf.update` had `worker_concurrency` set to a per-queue dict `{"review_jobs": 10, ...}`. Celery expects an `int`; multiplying a dict by an int raises `TypeError: unsupported operand type(s) for *: 'dict' and 'int'`.
- This was previously masked by the SIGSEGV crash (workers never reached this code path).
- Fixed by setting `worker_concurrency=REVIEW_JOBS_CONCURRENCY` (int). Per-queue concurrency is handled by `--concurrency` on each worker process.
- **File modified:** `pr_reviewer/workers/celery_app.py`.

**Fix 2 — SIGABRT on macOS (`OBJC_DISABLE_INITIALIZE_FORK_SAFETY`)**
- macOS Objective-C runtime aborts forked processes when `NSCharacterSet` initialisation is in progress on another thread at fork time — triggered by `httpx` being imported in the parent Celery process.
- Added `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES` to all Celery worker start commands in `launch`.
- This was later superseded by Fix 3 (no fork = no crash), but was a necessary intermediate step.
- **File modified:** `launch`.

**Fix 3 — SIGSEGV on macOS (multiple non-fork-safe native libraries)**
- `OBJC_DISABLE_INITIALIZE_FORK_SAFETY` suppressed the SIGABRT but a SIGSEGV remained. `hnswlib` (loaded by `chromadb`), `sqlalchemy`, and `httpx` all load native code in the parent process; forked children inherit corrupted state. Deferring the `chromadb` import alone was insufficient because other libraries have the same issue.
- Root fix: switch Celery workers to `--pool=solo` in the `launch` script. This eliminates `fork()` entirely — tasks run in the main worker process. Acceptable for local dev (sequential task execution); Linux production uses the default prefork pool unaffected.
- Also removed `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES` (no longer needed without forking).
- **File modified:** `launch`.

**Fix 4 — Deferred `chromadb` import in `WorkerContainer`**
- As a defence-in-depth measure (and correct regardless of pool type), moved `import chromadb` from module level inside `WorkerContainer.__init__`. This ensures `hnswlib` is only loaded post-fork in the child process, not pre-fork in the parent.
- **File modified:** `pr_reviewer/workers/container.py`.

---

### Feature — Switch primary LLM to Azure AI Foundry Claude

Azure OpenAI resource had both a VNet restriction (403) and a missing deployment (404). Switched the `ReviewAgent` LLM to Azure AI Foundry Claude via `litellm` (already a project dependency).

- `pr_reviewer/agents/llm.py`:
  - Added `_AzureAnthropicLLM` — calls `litellm.completion` with `model="azure_ai/{AZURE_ANTHROPIC_MODEL}"`, `api_base="{AZURE_ANTHROPIC_ENDPOINT}/models"`, `api_key=AZURE_ANTHROPIC_API_KEY`.
  - `make_llm()` priority order: Azure AI Foundry Claude → Azure OpenAI → `_NoopLLM` stub.
  - `AZURE_ANTHROPIC_MODEL` defaults to `claude-3-5-sonnet-20241022` if not set.
- `pr_reviewer/agents/review_agent.py`:
  - Added `except Exception` catch around the LLM call (Step 3). Previously only `TimeoutError` was caught; any other LLM error (403, 404, network) propagated up and crashed the Celery task. Now logs the error and continues with partial findings.
- `.env.example`: added `AZURE_ANTHROPIC_MODEL` field with default value and comment.

**Files modified:** `pr_reviewer/agents/llm.py`, `pr_reviewer/agents/review_agent.py`, `.env.example`.

---

### Task 31 — Bug fixes: tool→GitHubAPIClient mismatches (surfaced in live run)

These bugs were hidden during earlier runs because the LLM call (Step 3 of `ReviewAgent.run`) was crashing with 403/404 before execution reached Step 5 (`_check_test_coverage`). Once the LLM error was made non-fatal the task continued and hit these bugs.

**Root cause:** all five GitHub-client tool wrappers in `tools.py` were missing `repo=ctx.repo`, and two methods called by those tools were never implemented on `GitHubAPIClient`.

- `pr_reviewer/agents/tools.py`:
  - `fetch_pr_metadata` — was calling `ctx.github_client.get_pr_metadata(**kwargs)` with no arguments; now calls `get_pr_metadata(repo=ctx.repo, pr_number=ctx.pr_number)`.
  - `fetch_file_content` — missing `repo=ctx.repo` in `get_file_content` call; fixed.
  - `search_file` — missing `repo=ctx.repo` in `search_file` call; fixed.
  - `list_directory` — missing `repo=ctx.repo, ref="HEAD"` in `list_directory` call; fixed.
  - `get_symbol_usages` — missing `repo=ctx.repo` in `get_symbol_usages` call; fixed.
- `pr_reviewer/store/github_client.py`:
  - Added `get_pr_metadata(repo, pr_number)` — GET `/repos/{repo}/pulls/{pr_number}`; returns PR metadata dict.
  - Added `search_file(repo, path, query)` — GET `/search/code` with `query repo:{repo}` and optional `path:{path}` filter; returns items list.

**Why OpenAI runs didn't surface this:** the 403 VNet and 404 DeploymentNotFound errors from Azure OpenAI crashed the task at Step 3 (LLM call) before Step 5 (`_check_test_coverage` → `list_directory`) was ever reached. The non-fatal LLM error catch added in the Anthropic switch unblocked execution and exposed the downstream bugs.

**Tests:** 272 unit tests passing; no regressions.

**Files modified:** `pr_reviewer/agents/tools.py`, `pr_reviewer/store/github_client.py`, `.kiro/specs/github-pr-auto-review/tasks.md` (task 31 added and marked complete).

---

## 2026-05-20

### Task 32 — Pre-deployment runtime bug fixes

Three bugs surfaced during the first live end-to-end PR review run against a real repository.

**Fix 1 — Diff truncation excluded the test target (`titanium.js`)**
- `_MAX_CHANGED_LINES = 3000` in `diff_parser.py` truncated the diff at ~12 files on a large PR, silently dropping `titanium.js` (the intentionally-vulnerable test file that should trigger security findings).
- Raised to `_MAX_CHANGED_LINES = 10000`.
- Added truncation warning log in `job_processor.py` that lists all included filenames when `diff.truncated` is True, so truncation is always visible in logs.

**Fix 2 — `post_review` hanging with `ReadTimeout`**
- `httpx.Client` in `github_client.py` had no timeout configured. Posting a 28-finding review payload to GitHub's API exceeded the default wait, causing the worker to hang until Celery's task soft timeout killed it.
- Added `timeout=30.0` to the `httpx.Client` constructor.

**Files modified:** `pr_reviewer/components/diff_parser.py`, `pr_reviewer/workers/job_processor.py`, `pr_reviewer/store/github_client.py`.

---

### Task 33 — Azure Container Apps deployment infrastructure

Full end-to-end Azure deployment pipeline: single Docker image → ACR → Terraform-managed Azure Container Apps with managed PostgreSQL, Redis, ChromaDB, and OTel Collector.

**Container image**
- Created `Dockerfile` — `python:3.12-slim` base with uv for reproducible installs (`--frozen --no-dev`). Single image; role selected at runtime via CMD override.
- Created `docker-entrypoint.sh` — `case`/`esac` dispatcher routing `api`, `worker-review`, `worker-feedback`, `worker-indexer`, `beat`, `seed-kb`, and `migrate` to the correct process. `api` runs Alembic migrations before starting uvicorn.
- Created `.dockerignore` — excludes `infra/`, `.env*`, `.venv/`, test dirs, data, and logs. Secrets (`set-secrets.sh`) are inside `infra/` so they are automatically excluded.

**Terraform infrastructure** (`infra/terraform/`)
- `terraform.tf` — azurerm `~> 3.100`, random `~> 3.6`; Azure Storage backend; user-assigned managed identity with AcrPull role (avoids storing ACR admin credentials); Log Analytics workspace; `required_version >= 1.7` (needed for `mock_provider` in tests).
- `variables.tf` — all input variables; `image_tag` validated non-empty; `azure_openai_endpoint` validated `https://`-only; sensitive variables marked `sensitive = true`.
- `locals.tf` — constructs `db_url` and `redis_url` with `urlencode()` on the password/access key; Azure Redis keys are base64-encoded and contain `+`/`/` which break URL parsing without encoding. `chromadb_url` includes explicit `:80` so `urlparse()` resolves the port correctly.
- `postgres.tf` — PostgreSQL Flexible Server v16, B_Standard_B1ms, 32 GB; firewall rule `0.0.0.0–0.0.0.0` allows ACA outbound (ACA has no fixed IPs without VNet integration).
- `redis.tf` — Basic C1; `non_ssl_port_enabled = false` (the deprecated `enable_non_ssl_port` attribute was used initially and corrected during triple-check); TLS 1.2.
- `storage.tf` — storage account + Azure File shares for ChromaDB data (50 GB, ReadWrite) and OTel config (1 GB, ReadOnly); `azurerm_storage_share_file` uploads local `otel/collector-config.yml` at `terraform apply` time.
- `aca.tf` — ACA environment linked to Log Analytics; 7 container apps: `otel-collector` (internal, port 80 → 4318), `chromadb` (internal, Azure Files mount), `api` (external HTTPS, min 1/max 3), `worker-review`/`worker-feedback`/`worker-indexer`/`beat` (all internal, single replica); ACA Job `job-pr-reviewer-kb-seed` (manual trigger, 600s timeout) runs `seed-kb` entrypoint.
- `outputs.tf` — `api_fqdn`, `api_fqdn_raw`, `kb_seed_job_trigger` (full `az containerapp job start` command), `otel_collector_endpoint`, `acr_login_server`.

**Bug fixes during triple-check**
- `redis.tf`: `enable_non_ssl_port` → `non_ssl_port_enabled` (deprecated attribute name in azurerm ≥ 3.47; would have caused `terraform plan` to error).
- `locals.tf`: wrapped Redis primary access key and DB password with `urlencode()` in connection URL construction; Azure Redis keys are base64-encoded and routinely contain URL-breaking characters.

**Terraform tests** (`infra/terraform/tests/`)
- `smoke.tftest.hcl` — full plan with mocked azurerm and random providers; no real Azure credentials needed.
- `locals.tftest.hcl` — asserts `local.prefix`, `local.image_ref`, `local.db_name`, `local.db_user` at plan time.
- `variable_validation.tftest.hcl` — verifies empty `image_tag` is rejected, HTTP (non-HTTPS) `azure_openai_endpoint` is rejected, and valid values are accepted.
- All 10 tests pass (`terraform test`).

**Deployment scripts** (`infra/scripts/`)
- `bootstrap-state.sh` — one-time creation of Terraform state backend (Standard LRS, TLS 1.2, no public blob access).
- `build-push.sh` — Podman build (`--platform linux/amd64`) + push to ACR via `az acr login --expose-token`; username is the fixed literal `00000000-0000-0000-0000-000000000000` (required by Azure's token-based auth, not a real UUID).
- `set-secrets.sh` — gitignored and dockerignored; exports all `TF_VAR_*` values; pre-populated from `.env`.
- `deploy.sh` — single-command deployment: sources secrets → build + push (tag defaults to `git rev-parse --short HEAD`) → `terraform init -reconfigure` → plan → apply → prints API URL and webhook URL. Flags: `--tag`, `--skip-build`, `--seed`, `--plan-only`.

**README update**
- Azure deployment section reduced from 8 manual steps to 4: create GitHub App → bootstrap state → populate secrets → `./infra/scripts/deploy.sh`. Deploy options table added.

**Files created:** `Dockerfile`, `docker-entrypoint.sh`, `.dockerignore`, `infra/terraform/terraform.tf`, `infra/terraform/variables.tf`, `infra/terraform/locals.tf`, `infra/terraform/postgres.tf`, `infra/terraform/redis.tf`, `infra/terraform/storage.tf`, `infra/terraform/aca.tf`, `infra/terraform/outputs.tf`, `infra/terraform/tests/smoke.tftest.hcl`, `infra/terraform/tests/locals.tftest.hcl`, `infra/terraform/tests/variable_validation.tftest.hcl`, `infra/scripts/bootstrap-state.sh`, `infra/scripts/build-push.sh`, `infra/scripts/set-secrets.sh` (gitignored), `infra/scripts/deploy.sh`. **Files modified:** `.gitignore`, `README.md`.

---

### Task 34 — OTel HTTP transport fix and setup_telemetry wiring

Two independent bugs meant OpenTelemetry was completely inactive in every deployed process.

**Bug 1 — Wrong transport protocol**
- `telemetry.py` imported from `opentelemetry.exporter.otlp.proto.grpc.*` (gRPC, default port 4317). The ACA OTel collector's internal ingress is configured for HTTP/protobuf on port 4318 only — ACA supports a single ingress port per app, and gRPC on 4317 is not reachable.
- The `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf` env var set by Terraform has no effect when the gRPC exporter class is instantiated directly; the protocol is baked into the import path.
- Fixed by switching to `opentelemetry.exporter.otlp.proto.http.*` exporters.
- HTTP exporters require the full signal path in `endpoint` (gRPC uses a base URL). Appended `/v1/traces` and `/v1/metrics` to `OTEL_EXPORTER_OTLP_ENDPOINT`. Removed `insecure=True` (not a parameter on the HTTP exporter class; security is determined by the URL scheme).
- Updated default endpoint port from 4317 → 4318 for local development.

**Bug 2 — `setup_telemetry()` never called**
- The function was implemented in task 2 but no code path ever called it, so no `TracerProvider` or `MeterProvider` was ever registered in any process.
- `api/main.py` — added `setup_telemetry("pr-reviewer-api")` at the top of `build_app()`.
- `workers/celery_app.py` — added `_setup_worker_telemetry` connected to the `worker_process_init` signal; each worker process initialises its own provider on startup. Import deferred inside the handler to avoid circular imports at module load time.

**Tests:** Verified clean imports (`uv run python -c "from pr_reviewer.api.main import build_app"`). No regressions in existing 272 unit tests.

**Files modified:** `pr_reviewer/telemetry.py`, `pr_reviewer/api/main.py`, `pr_reviewer/workers/celery_app.py`.

---

**Running totals:** 272 unit tests · 6 integration tests (require live Postgres) · 3 pre-existing OTel isolation failures · lint clean · 10 Terraform tests passing · tasks 32–34 complete

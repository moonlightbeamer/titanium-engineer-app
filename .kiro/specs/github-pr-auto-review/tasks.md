# Tasks: GitHub PR Auto-Review

## Overview

Implement an LLM-backed GitHub PR review service in phases: v1 delivers the complete review pipeline (webhook receiver, LangChain agent, RAG knowledge base, feedback loop, evaluation harness); v2 adds persistent codebase memory, expanded MCP ecosystem, and cross-repository learning. All tasks follow TDD — write failing tests first, then implement.

## Task List

- [x] 1. Project scaffold and dependencies
  - [x] 1.1 Create `pyproject.toml` with pinned dependencies: `fastapi`, `celery[redis]`, `chromadb`, `langchain`, `langchain-openai`, `openai`, `pydantic>=2`, `detect-secrets`, `slowapi`, `alembic`, `sqlalchemy`, `pytest`, `pytest-asyncio`, `httpx`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp`
  - [x] 1.2 Create directory layout: `pr_reviewer/{api,workers,agents,components,config,kb,store,models}/`, `eval/{judges,tasks}/`, `tests/{unit,integration,e2e}/`, `data/{guidelines/}`
  - [x] 1.3 Create `docker-compose.yml` with PostgreSQL 16, Redis 7, ChromaDB HTTP server (port 8001), OTel Collector
  - [x] 1.4 Create `.env.example` with all required variables: `GITHUB_APP_PRIVATE_KEY`, `GITHUB_APP_ID`, `GITHUB_WEBHOOK_SECRET`, `OPENAI_API_KEY`, `DATABASE_URL`, `REDIS_URL`, `CHROMADB_URL`, `LOG_LEVEL`
  - [x] 1.5 Create `Makefile` with `make test`, `make lint`, `make run`, `make migrate`
  - [x] 1.6 Create GitHub Actions CI: lint + unit tests on PR; integration tests on push to main
  - [x] 1.7 Confirm `pytest` collects 0 tests without error after scaffold

- [x] 2. OpenTelemetry instrumentation setup
  - [x] 2.1 Test: `test_setup_telemetry_does_not_raise` — `setup_telemetry("pr_reviewer")` on blank environment raises no exception
  - [x] 2.2 Test: `test_tracer_provider_available_globally` — after setup, `get_tracer("pr_reviewer")` returns a non-noop tracer
  - [x] 2.3 Test: `test_all_golden_signal_metrics_registered` — `MeterProvider` contains instruments named `review.duration_ms`, `review.jobs_started`, `review.errors`, `review.queue_depth`, `review.tool_budget_used`, `kb.retrieval_latency_ms`, `kb.retrieval_relevance`
  - [x] 2.4 Test: `test_structured_logger_includes_trace_id` — log record produced inside an active span contains `trace_id` and `span_id`
  - [x] 2.5 Test: `test_log_level_read_from_env` — `LOG_LEVEL=WARN` → root logger level is WARNING
  - [x] 2.6 Test: `test_rate_limited_logger_deduplicates_within_window` — same error message emitted 5× within 60s → only 1 log record emitted
  - [x] 2.7 Test: `test_rate_limited_logger_resets_after_window` — same error after 61s → emitted again
  - [x] 2.8 Implement `pr_reviewer/telemetry.py` — `setup_telemetry(service_name: str)` initialises TracerProvider + MeterProvider with OTLP exporters; all golden signal metrics declared as module-level constants
  - [x] 2.9 Implement `pr_reviewer/logging.py` — `get_logger(name: str) -> RateLimitedLogger`; JSON formatter; injects `job_id`, `repo_id`, `trace_id`, `span_id` from context vars; deduplicates identical errors within 60s window

- [x] 3. Database schema and migrations
  - [x] 3.1 Test: `test_v1_migrations_apply_to_blank_db` — `alembic upgrade head` on empty PostgreSQL → exits 0, all v1 tables present
  - [x] 3.2 Test: `test_v1_migrations_are_reversible` — `alembic downgrade -1` from each migration → succeeds
  - [x] 3.3 Test: `test_jobs_table_columns_match_model` — `jobs` table has all fields from `Job` dataclass with correct types
  - [x] 3.4 Test: `test_findings_table_columns_match_model` — matches `Finding` dataclass
  - [x] 3.5 Test: `test_feedback_signals_table_columns_match_model` — matches `FeedbackSignal` dataclass
  - [x] 3.6 Test: `test_indexes_created` — `EXPLAIN` on `WHERE repo_id = X AND pr_number = Y` uses index; same for `commit_sha`, `findings(job_id)`
  - [x] 3.7 Test: `test_job_model_is_frozen` — `Job(...)` instance raises `FrozenInstanceError` on field assignment (Property 6)
  - [x] 3.8 Test: `test_finding_model_is_frozen` — same for `Finding` (Property 6)
  - [x] 3.9 Implement Alembic setup in `alembic/`; migration 001: `jobs` table; migration 002: `findings` table; migration 003: `feedback_signals` table
  - [x] 3.10 Implement all model classes in `pr_reviewer/models/`: `Job`, `Finding`, `FeedbackSignal` as frozen dataclasses; `JobStatus`, `ReviewCategory`, `Severity`, `Confidence`, `SignalType` enums

- [x] 4. GitHubAPIClient
  - [x] 4.1 Test: `test_jwt_has_correct_claims` — generated JWT contains `iat`, `exp` (60s from now), `iss` = `GITHUB_APP_ID`
  - [x] 4.2 Test: `test_token_exchange_sends_jwt_as_bearer` — mocked POST `/app/installations/{id}/access_tokens`; `Authorization: Bearer <jwt>` present
  - [x] 4.3 Test: `test_token_cached_in_redis` — second call within expiry window → 0 additional HTTP calls, Redis hit
  - [x] 4.4 Test: `test_token_refreshed_4_min_before_expiry` — token expiring in 4 minutes → proactive refresh triggered
  - [x] 4.5 Test: `test_401_raises_auth_error_no_retry` — mock returns 401 → `AuthError` raised immediately; no retry (Property 4)
  - [x] 4.6 Test: `test_403_rate_limit_retries_with_retry_after_header` — mock returns 403 with `Retry-After: 2` → waits ~2s, retries; after 3 failures raises `RateLimitError`
  - [x] 4.7 Test: `test_429_rate_limit_same_behavior_as_403`
  - [x] 4.8 Test: `test_compare_commits_calls_correct_endpoint` — `compare_commits(repo, "sha1", "sha2")` → `GET /repos/{repo}/compare/sha1...sha2`
  - [x] 4.9 Test: `test_post_review_sends_correct_payload` — mock POST `/pulls/{n}/reviews` → request body matches expected shape
  - [x] 4.10 Test: `test_traceparent_header_on_every_outbound_call` — all HTTP calls carry `traceparent` in W3C format `00-{trace_id}-{span_id}-{flags}`
  - [x] 4.11 Test: `test_otel_span_created_per_api_call` — each method call produces a child span with `endpoint` and `status_code` attributes
  - [x] 4.12 Implement `pr_reviewer/store/github_client.py` — `GitHubAPIClient(installation_id: int, redis_client: Redis)` with methods: `get_access_token`, `get_diff`, `get_file_content`, `list_directory`, `get_symbol_usages`, `post_review`, `get_existing_reviews`, `compare_commits`, `get_branch_head_sha`
  _Requirements: 1.1, 1.5, 1.8, 1.9, 1.10, 1.11_

- [x] 5. WebhookReceiver
  - [x] 5.1 Test: `test_valid_hmac_returns_202` — signature computed from body with correct secret → 202 (Property 1)
  - [x] 5.2 Test: `test_missing_signature_header_returns_401` — no `X-Hub-Signature-256` → 401; body never touched (Property 1)
  - [x] 5.3 Test: `test_invalid_hmac_returns_401` — wrong secret → 401; body never deserialized (Property 1)
  - [x] 5.4 Test: `test_rate_limit_100_per_minute_returns_429` — 101 requests within 60s from same IP → 429
  - [x] 5.5 Test: `test_rate_limit_different_ips_have_separate_buckets` — 100 req from IP A + 1 from IP B → IP A returns 429, IP B is 202
  - [x] 5.6 Test: `test_pull_request_opened_enqueues_review_job` — `X-GitHub-Event: pull_request`, `action: opened` → task enqueued on `review_jobs`
  - [x] 5.7 Test: `test_pull_request_review_comment_enqueues_feedback_job` — routes to `feedback_jobs`
  - [x] 5.8 Test: `test_pull_request_review_event_enqueues_feedback_job` — `X-GitHub-Event: pull_request_review` → `feedback_jobs` (suggestion acceptance path)
  - [x] 5.9 Test: `test_draft_pr_not_enqueued_when_review_draft_prs_false` — payload `draft: true`, config `review_draft_prs: false` → no task enqueued, 202 returned
  - [x] 5.10 Test: `test_ack_time_under_3_seconds` — 202 returned before Celery task completes
  - [x] 5.11 Test: `test_queue_depth_gauge_incremented` — after enqueue, `review.queue_depth` gauge value is +1 from baseline
  - [x] 5.12 Test: `test_unsupported_event_returns_200_and_not_enqueued` — `X-GitHub-Event: ping` → 200, no task enqueued (note: `push` is handled in task 23)
  - [x] 5.13 Implement `pr_reviewer/api/webhook.py` — FastAPI router at `POST /webhook/github`; HMAC-SHA256 with constant-time compare; slowapi `Limiter` at 100 req/min per source IP; draft check; `review.queue_depth` gauge on enqueue
  _Requirements: 1.2, 1.3, 1.4, 1.14_

- [x] 6. JobQueue
  - [x] 6.1 Test: `test_review_task_routes_to_review_jobs_queue` — `process_review_job.apply_async(...)` → task visible on `review_jobs`
  - [x] 6.2 Test: `test_feedback_task_routes_to_feedback_jobs_queue`
  - [x] 6.3 Test: `test_indexer_task_routes_to_indexer_jobs_queue`
  - [x] 6.4 Test: `test_review_jobs_max_10_concurrent` — Celery worker config for `review_jobs` has `concurrency=10`
  - [x] 6.5 Test: `test_task_retried_up_to_3_times_on_failure` — task raises `RuntimeError` → retried exactly 3 times
  - [x] 6.6 Test: `test_dead_letter_status_set_after_exhausted_retries` — after 3 retries, `jobs.status` updated to `dead_letter`
  - [x] 6.7 Test: `test_failure_comment_posted_on_dead_letter` — dead-letter handler calls `GitHubAPIClient.post_review` with failure message
  - [x] 6.8 Test: `test_queue_depth_gauge_decremented_on_task_start` — `review.queue_depth` decremented when worker picks up task
  - [x] 6.9 Implement `pr_reviewer/workers/celery_app.py` — `celery_app` with three named queues (`review_jobs` concurrency 10, `feedback_jobs` concurrency 5, `indexer_jobs` concurrency 2); `task_acks_late=True`; dead-letter handler via `task_failure` signal
  _Requirements: 1.4, 1.12, 1.13, 8.3_

- [x] 7. DiffParser
  - [x] 7.1 Test: `test_added_line_has_correct_github_position_index` — `+` lines have monotonically increasing position offset matching GitHub's position numbering
  - [x] 7.2 Test: `test_binary_file_not_in_changed_files` — binary marker → in `skipped_files`, absent from `changed_files`
  - [x] 7.3 Test: `test_truncation_at_exactly_3000_changed_lines` — 3001 changed lines → `truncated=True`, exactly 3000 in output (Property 2)
  - [x] 7.4 Test: `test_truncation_notice_present_in_output` — `StructuredDiff.truncation_notice` is non-empty when `truncated=True`
  - [x] 7.5 Test: `test_override_wins_over_extend_with_warn` — both fields in Config → `override` list used, WARN logged containing "conflicting ignore fields" (Property 3)
  - [x] 7.6 Test: `test_extend_merged_with_defaults` — only `extend` present → default + extend patterns both applied
  - [x] 7.7 Test: `test_file_matching_ignore_pattern_excluded` — file path matches ignore glob → not in `changed_files`
  - [x] 7.8 Test: `test_language_detected_from_file_extension` — `.py` → `"python"`; `.ts` → `"typescript"`
  - [x] 7.9 Test: `test_github_position_map_key_is_line_number_value_is_position`
  - [x] 7.10 Implement `pr_reviewer/components/diff_parser.py` — `DiffParser` with `parse(raw_diff: str, config: Config) -> StructuredDiff`; frozen data classes: `StructuredDiff`, `ChangedFile`, `Hunk`, `DiffLine`; `ChangeType` enum; pure function, no I/O
  _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8_

- [x] 8. SecretScrubber
  - [x] 8.1 Test: `test_aws_access_key_redacted` — string containing `AKIA...` → `[REDACTED]` in output
  - [x] 8.2 Test: `test_github_token_redacted` — `ghp_...` token → `[REDACTED]`
  - [x] 8.3 Test: `test_clean_content_returned_byte_for_byte_identical` — no secrets → `output == input` (Property 5)
  - [x] 8.4 Test: `test_returns_new_string_not_in_place` — function is pure; input content unchanged (Property 5)
  - [x] 8.5 Test: `test_multiple_secrets_all_redacted` — two different secret patterns → both replaced
  - [x] 8.6 Test: `test_detection_list_length_matches_secret_count` — 2 secrets → `detections` list has 2 elements
  - [x] 8.7 Test: `test_kb_source_logs_error_with_corpus_and_entry_id` — `scrub(content, source="kb", corpus="cve_snapshot", entry_id="uuid")` with secret → ERROR log contains corpus and entry_id
  - [x] 8.8 Test: `test_empty_string_returns_empty_string_no_detections` — `scrub("")` → `("", [])`
  - [x] 8.9 Implement `pr_reviewer/components/secret_scrubber.py` — `SecretScrubber` with `scrub(content: str, source: str = "diff", corpus: str | None = None, entry_id: str | None = None) -> tuple[str, list[Detection]]`; uses `detect_secrets.SecretsCollection`; constructs new string, never mutates input
  _Requirements: 3.6, 3.11, 9.7, 11.7_

- [x] 9. ConfigLoader
  - [x] 9.1 Test: `test_valid_yaml_parsed_into_config` — YAML with all fields set → `Config` with correct values
  - [x] 9.2 Test: `test_missing_config_file_returns_defaults` — mock 404 → `Config` with all defaults
  - [x] 9.3 Test: `test_invalid_yaml_returns_defaults_and_logs_warn` — malformed YAML → defaults; WARN log contains "invalid Config"
  - [x] 9.4 Test: `test_config_is_frozen_instance` — `config.tool_budget = 99` raises `ValidationError` or `FrozenInstanceError` (Property 6)
  - [x] 9.5 Test: `test_max_linter_files_defaults_to_5` — not in YAML → `config.max_linter_files == 5`
  - [x] 9.6 Test: `test_mcp_servers_custom_nvd_endpoint_parsed` — `mcp_servers: {nvd: "http://proxy:9200"}` → `config.mcp_servers.nvd == "http://proxy:9200"`
  - [x] 9.7 Test: `test_mcp_servers_defaults_to_standard_endpoints_when_absent` — no `mcp_servers` block → `config.mcp_servers.nvd == "https://services.nvd.nist.gov"`
  - [x] 9.8 Test: `test_language_corpus_weights_parsed` — `language_corpus_weights: {python: 1.5}` → `config.knowledge_base.language_corpus_weights == {"python": 1.5}`
  - [x] 9.9 Test: `test_language_corpus_weights_defaults_to_empty_dict` — no key → `{}` (all languages weight 1.0)
  - [x] 9.10 Implement `pr_reviewer/config/loader.py` and `pr_reviewer/config/schema.py` — `ConfigLoader.load(repo_id, installation_id) -> Config`; `Config` Pydantic frozen model with `MCPServersConfig` and `KnowledgeBaseConfig` nested models; all fields with correct defaults
  _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 11.9, 11.10, 16.5_

- [x] 10. KnowledgeBase
  - [x] 10.1 Test: `test_query_returns_at_most_5_entries` — 10 entries in collection → at most 5 returned (Property 8)
  - [x] 10.2 Test: `test_query_filtered_by_category_tag` — security and style entries → `category="security"` returns only security-tagged
  - [x] 10.3 Test: `test_disabled_corpus_not_queried` — `config.knowledge_base.cve_snapshot=False` → ChromaDB never queried for that collection
  - [x] 10.4 Test: `test_cve_staleness_warn_after_14_days` — `last_refresh` 15 days ago → WARN log contains "CVE snapshot stale"
  - [x] 10.5 Test: `test_model_version_mismatch_returns_empty_and_refuses` — entries with two `model_version` values → `query` returns `[]` with WARN
  - [x] 10.6 Test: `test_below_minimum_corpus_returns_empty_with_warn` — fewer than 5 CVE entries → `[]` + WARN "insufficient corpus"
  - [x] 10.7 Test: `test_per_language_weight_boosts_language_best_practices_score` — `language_corpus_weights={"python": 2.0}`; two entries with same raw cosine similarity (one Python, one Go) → Python entry ranked higher
  - [x] 10.8 Test: `test_weight_applied_only_to_language_best_practices_corpus` — weight set for Python → only `language_best_practices` scores multiplied; `cve_snapshot` scores unchanged
  - [x] 10.9 Test: `test_retrieval_latency_metric_emitted` — query call → `kb.retrieval_latency_ms` histogram records a value
  - [x] 10.10 Test: `test_cross_repo_fixes_collection_queryable_when_enabled` — entry inserted into `cross_repo_fixes`; `query(...)` returns it in results (Property 8; Req 16.2)
  - [x] 10.11 Test: `test_cross_repo_fixes_excluded_when_not_in_active_collections` — collection empty → not included in merged results; no error
  - [x] 10.12 Implement `pr_reviewer/kb/knowledge_base.py` — `KnowledgeBase(chromadb_client, config: Config)` with `query(query, category, language, priming=False) -> list[KBEntry]` and `validate_model_versions() -> bool`; six collections pre-created at startup; per-language weighting applied to `language_best_practices` corpus only
  _Requirements: 11.1, 11.2, 11.5, 11.7, 11.8, 11.9, 16.5_

- [x] 11. MCPClient
  - [x] 11.1 Test: `test_lookup_cve_calls_default_nvd_endpoint` — no `mcp_servers` in Config → `GET https://services.nvd.nist.gov/...`
  - [x] 11.2 Test: `test_lookup_cve_calls_custom_endpoint_from_config` — `config.mcp_servers.nvd = "http://proxy:9200"` → HTTP call goes to `http://proxy:9200/...`
  - [x] 11.3 Test: `test_nvd_rate_limit_fallback_to_cve_snapshot` — NVD token bucket exhausted → `KnowledgeBase.query` called for `cve_snapshot`; result tagged `source: fallback_corpus`; WARN logged with server name
  - [x] 11.4 Test: `test_fallback_chain_mcp_unavailable_and_corpus_empty` — NVD returns 503 AND `KnowledgeBase.query` returns `[]` → returns `EscalationResult(reason="could not verify against live CVE data")`
  - [x] 11.5 Test: `test_traceparent_header_on_every_mcp_call` — all outbound HTTP calls include `traceparent` in W3C format
  - [x] 11.6 Test: `test_rate_limit_bucket_per_server_independent` — NVD bucket exhausted; OSV bucket still has capacity → OSV calls succeed while NVD falls back
  - [x] 11.7 Test: `test_nvd_rate_limit_bucket_is_10_per_minute` — 11 NVD calls within 60s → 11th triggers fallback
  - [x] 11.8 Implement `pr_reviewer/kb/mcp_client.py` — `MCPClient(knowledge_base, config, redis_client)`; `lookup_cve` and `check_package_advisory` reading endpoint URLs from Config; Redis token buckets per server; fallback chain; `CVEAdvisory` and `EscalationResult` frozen dataclasses
  _Requirements: 11.3, 11.4, 11.5, 11.6, 11.10_

- [x] 12. ToolBudgetMiddleware and ReviewAgent
  - [x] 12.1 Test: `test_budget_incremented_on_each_tool_call` — 3 non-exempt calls → counter == 3 (Property 4)
  - [x] 12.2 Test: `test_budget_exhausted_raises_on_next_call` — 20 calls → 21st raises `BudgetExhaustedError` (Property 4)
  - [x] 12.3 Test: `test_priming_true_call_not_counted` — `query_knowledge_base(priming=True)` called 5× → counter still 0 (Property 4)
  - [x] 12.4 Test: `test_read_findings_so_far_not_counted` — `read_findings_so_far()` → counter unchanged
  - [x] 12.5 Test: `test_fetch_pr_metadata_called_first` — `fetch_pr_metadata` is the first tool call in every job
  - [x] 12.6 Test: `test_security_priming_kb_query_called_on_security_analysis` — `query_knowledge_base(category="security", priming=True)` called before first security Finding
  - [x] 12.7 Test: `test_secret_scrubber_applied_to_fetch_file_content_result` — result of `fetch_file_content` passes through `SecretScrubber` before entering agent context (Property 5)
  - [x] 12.8 Test: `test_low_confidence_finding_triggers_one_extra_tool_call` — low-confidence Finding → one additional tool call attempted
  - [x] 12.9 Test: `test_budget_exhausted_on_general_path_returns_partial_findings` — `BudgetExhaustedError` during style analysis → partial Findings returned, no exception propagated
  - [x] 12.10 Test: `test_budget_exhausted_on_security_path_produces_escalation` — `BudgetExhaustedError` during security verification → `Finding(is_escalation=True)` in results
  - [x] 12.11 Test: `test_llm_timeout_retried_once` — LLM call times out → retried exactly once; on second timeout partial Findings returned
  - [x] 12.12 Test: `test_no_mechanical_chunking` — diff passed whole; agent never receives pre-chunked sub-diff
  - [x] 12.13 Test: `test_test_coverage_check_performed_after_main_analysis` — `list_directory` and `search_file` called after Findings produced
  - [x] 12.14 Test: `test_missing_test_coverage_produces_bugs_finding` — no test file found for modified function → `Finding(category=bugs)` with suggested test case
  - [x] 12.15 Test: `test_synthesis_merges_findings_at_same_file_and_line` — style Finding and security Finding both reference `auth.py:42` → exactly one merged Finding with combined explanation
  - [x] 12.16 Test: `test_synthesis_annotates_related_findings_across_categories` — bug Finding and security Finding share root cause → both have each other's ID in `related_finding_ids`; each explanation contains inline cross-category note
  - [x] 12.17 Test: `test_every_finding_has_required_fields` — each Finding has `category`, `file_path`, `line_number`, `explanation` (≥1 sentence), `severity`
  - [x] 12.18 Test: `test_medium_high_finding_has_suggestion` — severity medium/high → `suggestion` is non-None
  - [x] 12.19 Test: `test_explanation_present_alongside_valid_suggestion` — Finding with non-None `suggestion` also has non-empty `explanation` of at least one sentence
  - [x] 12.20 Test: `test_alternative_llm_provider_accepted` — instantiate `ReviewAgent` with a mock `BaseChatModel`; no `TypeError`; `run()` dispatches to the mock
  - [x] 12.21 Test: `test_all_v1_tools_registered_with_agent` — inspect agent tool registry; all 9 v1 tools present by name: `fetch_pr_metadata`, `read_findings_so_far`, `query_knowledge_base`, `fetch_file_content`, `search_file`, `list_directory`, `get_symbol_usages`, `lookup_cve`, `check_package_advisory`
  - [x] 12.22 Implement `pr_reviewer/agents/tool_budget.py` — `ToolBudgetMiddleware(budget: int)`; budget-exempt set; `BudgetExhaustedError`
  - [x] 12.23 Implement `pr_reviewer/agents/tools.py` — all v1 Agent_Tool implementations registered with LangChain; `fetch_file_content` runs result through `SecretScrubber` before return
  - [x] 12.24 Implement `pr_reviewer/agents/review_agent.py` — `ReviewAgent.run(diff, config, context) -> list[Finding]`; `ReviewContext` frozen dataclass; `_synthesis_step` method merging same-location Findings and populating `related_finding_ids`
  _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12, 3.13, 3.14, 3.15, 4.5_

- [x] 13. CommentPoster
  - [x] 13.1 Test: `test_single_review_payload_sent` — multiple Findings → one call to `POST /reviews`, not one per Finding
  - [x] 13.2 Test: `test_any_high_produces_request_changes` — one high-severity Finding → `"REQUEST_CHANGES"`
  - [x] 13.3 Test: `test_empty_findings_list_posts_no_issues_found_comment` — `findings=[]` → summary body `"No issues found."`, status `"COMMENT"`
  - [x] 13.4 Test: `test_all_filtered_by_min_severity_also_posts_no_issues_found` — 3 low Findings, `min_severity=medium` → all filtered → `"No issues found."`
  - [x] 13.5 Test: `test_auto_approve_when_no_findings_and_configured` — empty + `auto_approve_on_no_findings=True` → status `"APPROVE"`
  - [x] 13.6 Test: `test_suggestion_block_uses_github_syntax_for_medium` — medium Finding → body contains ` ```suggestion` block
  - [x] 13.7 Test: `test_invalid_suggestion_omits_block_retains_explanation` — `suggestion` malformed/None → no suggestion block; `explanation` present
  - [x] 13.8 Test: `test_422_skips_comment_and_continues` — mock returns 422 for second comment → first and third posted; second skipped; no exception
  - [x] 13.9 Test: `test_dedup_skips_finding_with_existing_comment` — existing comment at `auth.py:42` → Finding for `auth.py:42` not included in new payload
  - [x] 13.10 Test: `test_summary_body_found_n_issues` — 3 Findings across 2 categories → `"Found 3 issue(s) across 2 category/categories."`
  - [x] 13.11 Test: `test_min_severity_filter_applied_before_status_determination` — 2 high + 1 low, `min_severity=high` → low suppressed; status `"REQUEST_CHANGES"` based on 2 high
  - [x] 13.12 Implement `pr_reviewer/components/comment_poster.py` — `CommentPoster(github_client)`; `post(findings, pr, config) -> None`; `_format_suggestion_block`; `_determine_review_status` (ignores escalations from severity determination); applies `min_severity` filter; deduplicates; handles 422 gracefully
  _Requirements: 4.1, 4.2, 4.3, 4.4, 4.6, 5.1, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 5.10, 7.4_

- [x] 14. FeedbackStore
  - [x] 14.1 Test: `test_insert_then_query_returns_inserted_signal` — insert signal, query by `repo_id` → signal present
  - [x] 14.2 Test: `test_query_recent_respects_limit` — 10 signals, `limit=5` → exactly 5 returned
  - [x] 14.3 Test: `test_query_recent_returns_most_recent_first` — 3 signals at t1 < t2 < t3 → t3 first
  - [x] 14.4 Test: `test_query_filters_by_file_path_pattern` — signals with patterns `["src/auth/**", "src/db/**"]`; only `src/auth/**` matches → only auth signals returned
  - [x] 14.5 Test: `test_feedback_signal_has_no_code_fields` — `FeedbackSignal` dataclass has no `code`, `diff`, `content`, or `snippet` field (Property 7)
  - [x] 14.6 Test: `test_query_uses_parameterized_sql` — SQL contains `$1` or `:param` placeholders, not f-strings
  - [x] 14.7 Implement `pr_reviewer/store/feedback_store.py` — `FeedbackStore(db_engine: Engine)` with `insert(signal) -> None` and `query_recent(repo_id, file_path_patterns, limit=5) -> list[FeedbackSignal]`; SQLAlchemy Core only; no raw f-string SQL
  _Requirements: 9.1, 9.5, 9.6, 9.7_

- [x] 15. FeedbackProcessor
  - [x] 15.1 Test: `test_resolved_comment_without_suggestion_classified_negative` — `pull_request_review_comment` resolved, no suggestion → `SignalType.negative`
  - [x] 15.2 Test: `test_applied_suggestion_classified_positive` — suggestion-applied marker → `SignalType.positive`
  - [x] 15.3 Test: `test_wontfix_reply_classified_negative` — reply body "won't fix" → `SignalType.negative`
  - [x] 15.4 Test: `test_pull_request_review_submitted_suggestion_accepted_positive` — `pull_request_review` event with approved suggestion → `SignalType.positive`
  - [x] 15.5 Test: `test_secret_scrubber_called_before_building_signal` — payload with secret-like string → `SecretScrubber.scrub` called; scrubbed content used (Property 5)
  - [x] 15.6 Test: `test_feedback_signal_persisted_to_store` — signal classified → `FeedbackStore.insert` called with correct `FeedbackSignal`
  - [x] 15.7 Test: `test_unknown_event_type_logs_warn_and_returns_without_insert` — unrecognised event → WARN logged; `FeedbackStore.insert` never called
  - [x] 15.8 Test: `test_file_path_pattern_extracted_from_comment` — comment on `src/auth/login.py` → `file_path_pattern == "src/auth/**"`
  - [x] 15.9 Implement `pr_reviewer/workers/feedback_processor.py` — Celery task `process_feedback_job(event_type, payload)`; `_classify_signal`; `_extract_file_path_pattern`; `_extract_finding_category`
  _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7_

- [x] 16. JobProcessor
  - [x] 16.1 Test: `test_review_job_completes_end_to_end` — all components mocked at I/O boundaries; job runs steps 1–13; review posted; `last_reviewed_sha` updated
  - [x] 16.2 Test: `test_incremental_diff_fetched_when_last_sha_exists` — `last_reviewed_sha="abc123"` → `compare_commits("abc123", "new_sha")` called
  - [x] 16.3 Test: `test_last_reviewed_sha_updated_only_on_success` — `CommentPoster.post` raises → DB not updated; retry uses full delta
  - [x] 16.4 Test: `test_existing_review_for_commit_sha_skips_job` — `get_existing_reviews` returns bot review for same SHA → job skipped; no `ReviewAgent.run`
  - [x] 16.5 Test: `test_min_severity_filter_applied_after_review` — `min_severity=medium`, ReviewAgent returns 1 high + 2 low → `CommentPoster.post` receives only 1 high
  - [x] 16.6 Test: `test_few_shot_examples_in_review_context` — returned signals passed as `context.few_shot_examples` to `ReviewAgent`
  - [x] 16.7 Test: `test_auth_error_marks_job_failed_no_retry` — `get_access_token` raises `AuthError` → `jobs.status = failed`; Celery does NOT retry
  - [x] 16.8 Test: `test_root_span_created_with_job_id` — OTel root span has `job_id` as attribute
  - [x] 16.9 Test: `test_review_duration_recorded_on_success` — successful job → `review.duration_ms` histogram has a value, status tag `"success"`
  - [x] 16.10 Test: `test_codebase_index_injected_into_review_context_when_enabled` — `config.codebase_index_enabled=True` and valid `CodebaseIndex` in DB → `ReviewAgent.run` receives `context.codebase_index` that is not None **[v2]**
  - [x] 16.11 Test: `test_codebase_index_not_injected_when_disabled` — `config.codebase_index_enabled=False` → `context.codebase_index == None` **[v2]**
  - [x] 16.12 Test: `test_no_index_in_db_does_not_fail_job` — `codebase_index_enabled=True` but no index row → job proceeds with `context.codebase_index=None`; no exception **[v2]**
  - [x] 16.13 Test: `test_stale_index_triggers_out_of_schedule_refresh` — `CodebaseIndex.commit_sha` is 501 commits behind HEAD → WARN logged; `run_index_refresh` task enqueued on `indexer_jobs` **[v2]**
  - [x] 16.14 Test: `test_stale_index_does_not_block_job` — stale index detected → job continues using stale index; `ReviewAgent.run` still called **[v2]**
  - [x] 16.15 Test: `test_multi_package_pr_injects_only_modified_package_sections` — PR modifies `packages/api/` and `packages/db/`; indexes for all 3 packages exist → only api and db sections injected **[v2]**
  - [x] 16.16 Test: `test_multi_package_injection_respects_token_limit` — combined index exceeds `index_max_tokens=8000` → packages with most changed files prioritised; total token count ≤ 8000; WARN logged **[v2]**
  - [x] 16.17 Test: `test_context_tokens_used_recorded_after_successful_job` — after job completes, `context_tokens_used` in DB is non-NULL integer > 0
  - [x] 16.18 Implement `pr_reviewer/workers/job_processor.py` — Celery task `process_review_job(job_id: UUID)`; executes steps 1–13 from JobProcessor design; auth error halts without retry; OTel root span; all metrics emitted
  _Requirements: 1.5, 1.6, 1.7, 1.8, 1.13, 5.10, 7.2, 7.4, 8.1, 8.2, 12.10, 12.11, 14.2, 14.4_

- [x] 17. Health check endpoint
  - [x] 17.1 Test: `test_health_200_when_all_deps_reachable` — mock DB, Redis, ChromaDB all OK → 200 `{"status":"ok","db":"ok","redis":"ok","chromadb":"ok"}`
  - [x] 17.2 Test: `test_health_503_when_postgres_down` — DB ping raises → 503 with `"db": "error"`
  - [x] 17.3 Test: `test_health_checks_each_dependency_independently` — DB down, Redis up → response contains both statuses
  - [x] 17.4 Test: `test_health_status_field_ok_only_when_all_ok` — any one dep down → top-level `"status": "degraded"`
  - [x] 17.5 Implement `pr_reviewer/api/health.py` — `GET /health`; probes: `SELECT 1` on PostgreSQL, `PING` on Redis, `GET /api/v1/heartbeat` on ChromaDB; each in try/except; 200 when all pass, 503 when any fail

- [x] 18. Evaluation harness scaffold
  - [x] 18.1 Test: `test_eval_package_has_zero_pr_reviewer_imports` — `grep -r "from pr_reviewer" eval/` → empty output
  - [x] 18.2 Test: `test_inspect_task_suite_dry_runs_without_error` — `inspect eval --dry-run eval/tasks/` exits 0
  - [x] 18.3 Test: `test_eval_runs_table_created_by_migration` — `eval_runs` table present after `alembic upgrade head`
  - [x] 18.4 Test: `test_corpus_raises_if_fewer_than_20_prs` — `load_corpus()` with 19 labeled samples → raises `CorpusValidationError("corpus requires ≥20 PRs")`
  - [x] 18.5 Test: `test_corpus_raises_if_fewer_than_10_safe_prs` — corpus with only 9 labeled no-security → raises `CorpusValidationError`
  - [x] 18.6 Test: `test_corpus_raises_if_fewer_than_5_security_prs` — only 4 labeled with known security vulnerabilities → raises `CorpusValidationError`
  - [x] 18.7 Test: `test_corpus_valid_with_minimum_required_prs` — exactly 20 PRs, 10 safe, 5 with security → `load_corpus()` succeeds
  - [x] 18.8 Implement `eval/pyproject.toml` — standalone package; `pr_reviewer` not a dependency; deps: `inspect-ai`, `litellm`, `sqlalchemy`
  - [x] 18.9 Implement `eval/db.py`, `eval/corpus.py` — `load_corpus(min_prs=20) -> list[EvalSample]`; reads from `findings` table with ground-truth labels; raises `CorpusValidationError` below minimums
  - [x] 18.10 Add Alembic migration: `eval_runs` table — `id UUID PK`, `run_type TEXT`, `started_at TIMESTAMPTZ`, `completed_at TIMESTAMPTZ`, `report JSONB`, `corpus_version TEXT`
  _Requirements: 6.1, 6.2, 10.1, 10.2, 10.9, 10.10_

- [x] 19. Eval judge suite
  - [x] 19.1 Test: `test_relevance_judge_returns_score_and_rationale` — mocked LiteLLM → `JudgeResult(score=8, rationale="...")`; `0 ≤ score ≤ 10`
  - [x] 19.2 Test: `test_scores_returned_as_4_vector_not_mean` — `evaluate_finding(finding, diff, label)` returns `ScoreVector(relevance, accuracy, actionability, clarity)` as tuple; no single float
  - [x] 19.3 Test: `test_schema_validity_check_passes_for_complete_finding` — Finding with all required fields → `validate_schema(finding) == True`
  - [x] 19.4 Test: `test_regex_check_requires_line_number_for_security` — security Finding without `line_number` → `check_regex(finding) == False`
  - [x] 19.5 Test: `test_token_f1_computed_against_reference_fix` — reference "def validate(x): return x > 0"; prediction includes "x > 0" → F1 > 0
  - [x] 19.6 Test: `test_bias_detection_runs_security_judge_with_two_model_families` — `detect_same_family_bias(finding)` calls judge with at least 2 different model families
  - [x] 19.7 Test: `test_verification_trace_judge_receives_tool_call_chain` — judge receives list of tool calls used before security Finding
  - [x] 19.8 Implement six judge files: `eval/judges/{relevance,accuracy,actionability,clarity,verification_trace,quality_with_cot}_judge.py`; each returns `JudgeResult(score, rationale, model_used)`
  - [x] 19.9 Implement `eval/classical_metrics.py` — `validate_schema`, `check_regex`, `token_f1`
  - [x] 19.10 Implement `eval/bias_detection.py` — `detect_same_family_bias(finding, diff) -> BiasResult`; uses GPT-4o and Claude Sonnet (different families)
  _Requirements: 10.3, 10.4, 10.5, 10.7_

- [x] 20. Eval trigger modes and summary report
  - [x] 20.1 Test: `test_preshipmode_fails_when_any_security_fp_present` — corpus contains 1 security FP → run exits non-zero
  - [x] 20.2 Test: `test_weekly_mode_samples_exactly_10_findings` — DB has 50 findings → exactly 10 selected
  - [x] 20.3 Test: `test_weekly_mode_uses_stored_findings_not_raw_diff` — `eval/corpus.py` reads from `findings` table, not any raw diff column
  - [x] 20.4 Test: `test_summary_report_precision_recall_fp_per_category` — report JSON contains `precision`, `recall`, `false_positive_count` for each of the 4 categories
  - [x] 20.5 Test: `test_summary_report_includes_mean_per_dimension_scores` — report has `relevance`, `accuracy`, `actionability`, `clarity` score summaries
  - [x] 20.6 Test: `test_summary_report_includes_cost_and_latency_per_review` — report has `avg_cost_usd` and `avg_latency_ms`
  - [x] 20.7 Test: `test_summary_report_includes_delta_vs_previous_run` — second run report has `delta` field comparing to most recent prior `eval_runs` record
  - [x] 20.8 Test: `test_summary_report_includes_feedback_signal_counts` — report has `feedback_signals_per_category` map with count per `ReviewCategory` per repo
  - [x] 20.9 Test: `test_kb_quality_check_flags_security_finding_with_no_retrieval` — security Finding with no KB entry retrieved → flagged in `kb_quality.no_retrieval_findings`
  - [x] 20.10 Test: `test_meta_prompt_loop_reports_score_delta_before_applying` — reflector output not applied to deployment; delta reported only
  - [x] 20.11 Implement `eval/tasks/pre_ship.py` — full corpus Inspect AI task; all 6 judges + classical metrics; fails on any security FP
  - [x] 20.12 Implement `eval/tasks/weekly_vibe.py` — samples 10 Findings; human 1–5 score written to `vibe_scores` table; `quality_with_cot_judge` run alongside; Pearson correlation logged
  - [x] 20.13 Implement `eval/tasks/meta_prompt.py` — selects 5 lowest by `quality_with_cot_judge`; builds reflector prompt; reports revised prompt + delta; does NOT auto-apply
  - [x] 20.14 Implement `eval/report.py` — `generate_report(run_id, run_type, findings, judge_scores) -> EvalReport`; persists to `eval_runs.report` JSONB
  - [x] 20.15 Add Alembic migration: `vibe_scores` table
  _Requirements: 6.1, 6.3, 6.4, 6.5, 8.4, 8.5, 9.8, 10.6, 10.8, 10.10, 10.11, 10.12_

- [x] 21. Knowledge Base CLI
  - [x] 21.1 Test: `test_add_lessons_learned_requires_four_fields` — JSON missing `resolution` field → validation error; not inserted
  - [x] 21.2 Test: `test_add_lessons_learned_rejects_field_below_50_chars` — `problem_description` is 40 chars → error "minimum 50 characters"
  - [x] 21.3 Test: `test_add_lessons_learned_rejects_raw_code_in_code_pattern` — `code_pattern` has >3 lines of code syntax → rejected "abstract description required"
  - [x] 21.4 Test: `test_add_with_draft_flag_requires_approval` — `kb add --draft` → `is_draft=True`; `KnowledgeBase.query` does not return it
  - [x] 21.5 Test: `test_approve_sets_is_draft_false` — `kb approve {id}` → `is_draft=False`; entry now retrievable
  - [x] 21.6 Test: `test_deprecate_sets_is_active_false_entry_remains_in_db` — `kb deprecate {id}` → `is_active=False`; row still in DB
  - [x] 21.7 Test: `test_deprecated_entry_not_returned_by_kb_query` — deprecated entry excluded from query results
  - [x] 21.8 Test: `test_rollback_activates_target_version` — `kb rollback --corpus cve_snapshot --version 2` → version 2 `is_active=True`; version 3 `is_active=False`
  - [x] 21.9 Test: `test_rollback_retains_last_5_versions` — 6 versions exist → versions 2–6 all retained
  - [x] 21.10 Test: `test_reembed_updates_model_version_on_all_active_entries` — `kb reembed --corpus all` → all `is_active=True` entries get new `model_version`
  - [x] 21.11 Test: `test_bootstrap_seeds_min_cve_and_guidelines` — `kb bootstrap` on empty DB → `cve_snapshot` has ≥5 entries; `org_guidelines` has ≥1
  - [x] 21.12 Implement `pr_reviewer/kb/cli.py` — Click CLI group `kb` with subcommands: `add`, `approve`, `deprecate`, `list`, `show`, `rollback`, `reembed`, `validate`, `bootstrap`
  - [x] 21.13 Add Alembic migrations: `knowledge_base_entries` and `corpus_versions` tables; partial unique index enforcing one `is_active=True` per corpus
  _Requirements: 11.1, 11.5, 11.6, 11.7, 11.8, 11.9, 16.3, 16.4_

- [x] 22. CodebaseIndex data model and migration **[v2]**
  - [x] 22.1 Test: `test_codebase_indexes_migration_applies_and_rolls_back` — round-trip `alembic upgrade head` then `downgrade -1` → clean
  - [x] 22.2 Test: `test_codebase_index_model_is_frozen` — `CodebaseIndex(...)` raises `FrozenInstanceError` on field assignment (Property 6)
  - [x] 22.3 Test: `test_index_scope_enum_values` — `IndexScope` has exactly `single` and `monorepo`
  - [x] 22.4 Test: `test_package_path_nullable` — `CodebaseIndex(package_path=None, ...)` valid for single-repo
  - [x] 22.5 Add Alembic migration: `codebase_indexes` table with all columns from `CodebaseIndex` model; composite index on `(repo_id, package_path, is_valid, version DESC)`
  - [x] 22.6 Implement `pr_reviewer/models/codebase_index.py` — `CodebaseIndex` frozen dataclass; `IndexScope` enum
  _Requirements: 12.1, 12.2, 12.3, 12.7, 12.9, 14.1_

- [x] 23. Indexer **[v2]**
  - [x] 23.1 Test: `test_indexer_skips_repo_with_no_successful_review_job` — `jobs` table has no `status=complete` for repo → task returns early; INFO log "no successful review yet"
  - [x] 23.2 Test: `test_convention_profile_pattern_requires_60pct_agreement` — pattern in 11/20 files (55%) → omitted (Property 10)
  - [x] 23.3 Test: `test_convention_profile_pattern_at_exactly_60pct_included` — pattern in 12/20 files (60%) → included (Property 10)
  - [x] 23.4 Test: `test_convention_profile_samples_20_most_recently_modified_files` — 50 files in repo → exactly 20 fetched by most recent commit timestamp
  - [x] 23.5 Test: `test_finding_density_map_omitted_below_10_signals` — 9 signals → `finding_density_map=None`, WARN "insufficient signal: 9, need 10"
  - [x] 23.6 Test: `test_finding_density_map_included_at_10_signals` — exactly 10 signals → `finding_density_map` is not None
  - [x] 23.7 Test: `test_index_trimmed_to_max_tokens` — index content exceeds `index_max_tokens` → trimmed; `token_count <= config.index_max_tokens` (Property 9)
  - [x] 23.8 Test: `test_on_refresh_failure_last_valid_index_still_accessible` — Indexer raises mid-build → previous `is_valid=True` index unchanged
  - [x] 23.9 Test: `test_versioning_keeps_last_3_versions` — 4 successful refreshes → versions 1 and 2 get `is_valid=False`; versions 3 and 4 remain `is_valid=True`; version 1 not deleted
  - [x] 23.10 Test: `test_commit_sha_recorded_as_default_branch_head_at_build_time` — `commit_sha` == result of `get_branch_head_sha` at build start
  - [x] 23.11 Test: `test_monorepo_detection_finds_manifest_in_subdirectory` — `package.json` in `packages/api/` → `"packages/api"` in detected packages
  - [x] 23.12 Test: `test_monorepo_builds_separate_index_per_package` — 2 packages detected → 2 `CodebaseIndex` rows with different `package_path` values
  - [x] 23.13 Test: `test_indexer_uses_separate_rate_limit_bucket` — Indexer's `GitHubAPIClient` uses Redis key `{installation_id}:indexer` not `{installation_id}:review`
  - [x] 23.14 Test: `test_celery_beat_scheduled_at_02_utc_daily` — Beat schedule entry exists with `crontab(hour=2, minute=0)`
  - [x] 23.15 Test: `test_push_event_with_over_20_files_triggers_indexer_refresh` — WebhookReceiver receives `X-GitHub-Event: push` with payload listing 21 changed files on default branch → `run_index_refresh.apply_async(...)` called once; task enqueued on `indexer_jobs`
  - [x] 23.16 Test: `test_push_event_with_20_or_fewer_files_does_not_trigger_indexer` — push event with exactly 20 changed files → `run_index_refresh` not called
  - [x] 23.17 Implement `pr_reviewer/workers/indexer.py` — Celery task `run_index_refresh(repo_id, installation_id)`; `_detect_monorepo`, `_build_architectural_summary`, `_build_convention_profile`, `_build_finding_density_map`; dedicated `GitHubAPIClient` with `:indexer` Redis key suffix; Celery Beat entry at 02:00 UTC
  - [x] 23.18 Add push-event routing to `pr_reviewer/api/webhook.py` — `X-GitHub-Event: push` with >20 changed files enqueues `run_index_refresh` to `indexer_jobs`
  _Requirements: 12.1, 12.3, 12.4, 12.5, 12.6, 12.7, 12.8, 12.9, 12.10, 12.11, 14.1, 14.3, 14.5_

- [x] 24. Index-informed ReviewAgent behavior **[v2]**
  - [x] 24.1 Test: `test_style_finding_suppressed_for_pattern_in_convention_profile` — camelCase in `convention_profile` at >60% → camelCase-related style Finding removed by convention filter
  - [x] 24.2 Test: `test_style_finding_retained_when_no_codebase_index` — `codebase_index=None` → convention filter not applied; same behavior as v1
  - [x] 24.3 Test: `test_tool_budget_biases_toward_high_density_file` — `finding_density_map` shows `src/auth` as high-signal → `src/auth` files appear earlier in budget prioritisation list
  - [x] 24.4 Test: `test_security_candidate_in_security_boundary_lowered_threshold` — file tagged as security boundary in `architectural_summary` → agent escalates at confidence that would normally be suppressed
  - [x] 24.5 Test: `test_security_candidate_in_test_fixture_auto_discarded` — file tagged as test fixture → candidate removed without any tool call consumed
  - [x] 24.6 Test: `test_test_fixture_auto_discard_consumes_zero_budget` — fixture discard → `ToolBudgetMiddleware` counter unchanged
  - [x] 24.7 Test: `test_no_index_behavior_identical_to_v1` — `config.codebase_index_enabled=False` → no convention or density logic runs
  - [x] 24.8 Test: `test_eval_harness_index_contribution_delta_measured` — ablation: run corpus with/without `CodebaseIndex`; `precision_delta` and `recall_delta` in report
  - [x] 24.9 Extend `ReviewAgent.run` with `_apply_convention_filter`, `_prioritize_budget_by_density`; lower escalation threshold for security boundary files; auto-discard test fixture candidates
  _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5_

- [x] 25. v2 agent tools — linter and license **[v2]**
  - [x] 25.1 Test: `test_run_linter_invokes_correct_binary_for_language` — Python file → `pylint` subprocess; JS/TS → `eslint`; Go → `golangci-lint`
  - [x] 25.2 Test: `test_run_linter_subprocess_has_30s_timeout` — mock subprocess that hangs → `TimeoutExpired` caught; empty results returned; WARN logged
  - [x] 25.3 Test: `test_run_linter_returns_empty_when_binary_missing` — no `pylint` on PATH → `[]` + WARN "linter unavailable for python"
  - [x] 25.4 Test: `test_run_linter_respects_max_linter_files_cap` — 7 lintable files, `max_linter_files=5` → linter called 5 times; WARN logged with 2 skipped file names
  - [x] 25.5 Test: `test_run_linter_prioritizes_files_by_most_changed_lines` — files with 100, 50, 200 changed lines → ordered 200, 100, 50 before applying cap
  - [x] 25.6 Test: `test_check_license_triggered_on_new_package_json_dependency` — diff adds line to `package.json` `"dependencies"` block → `check_license` called for new package
  - [x] 25.7 Test: `test_check_license_violation_produces_high_severity_bugs_finding` — AGPL package with MIT policy → `Finding(severity=high, category=bugs)`
  - [x] 25.8 Add `run_linter` and `check_license` tools to `pr_reviewer/agents/tools.py`; manifest detection in ReviewAgent; `LinterFinding` and `LicenseResult` frozen dataclasses
  _Requirements: 15.1, 15.2, 15.3_

- [x] 26. v2 agent tools — MCP ecosystem **[v2]**
  - [x] 26.1 Test: `test_ghsa_lookup_calls_github_advisory_endpoint` — `GET https://api.github.com/advisories?...` called with ecosystem + package + version
  - [x] 26.2 Test: `test_snyk_lookup_falls_back_on_rate_limit_bucket_exhausted` — Snyk token bucket exhausted → fallback to `cve_snapshot`
  - [x] 26.3 Test: `test_owasp_check_matches_sql_injection_pattern` — SQL string concat pattern + Python → returns OWASP A03 match
  - [x] 26.4 Test: `test_owasp_check_no_match_returns_empty` — safe parameterized query → `[]`
  - [x] 26.5 Test: `test_v2_mcp_tools_count_against_tool_budget` — `ghsa_lookup`, `snyk_lookup`, `owasp_check` all increment `ToolBudgetMiddleware` counter (Property 4)
  - [x] 26.6 Add `ghsa_lookup`, `snyk_lookup`, `owasp_check` to `pr_reviewer/kb/mcp_client.py` with per-server token buckets; expose to ReviewAgent as Tool_Budget-counting tools; `OWASPMatch` frozen dataclass
  _Requirements: 15.1, 15.2_

- [x] 27. Cross-repository fix corpus and per-language weighting **[v2]**
  - [x] 27.1 Test: `test_positive_signal_with_cross_repo_enabled_calls_add_cross_repo` — `signal_type=positive`, `config.cross_repo_sharing=True` → `add_cross_repo_fix` called
  - [x] 27.2 Test: `test_cross_repo_sharing_false_does_not_call_add_cross_repo` — `config.cross_repo_sharing=False` (default) → `add_cross_repo_fix` never called
  - [x] 27.3 Test: `test_add_cross_repo_fix_stores_abstract_pattern_not_code` — entry `content` passes code-concreteness check; no raw code stored
  - [x] 27.4 Test: `test_code_concreteness_classifier_rejects_entry_with_4_code_lines` — input with 4 lines matching code syntax → `ValueError` raised; not persisted
  - [x] 27.5 Test: `test_code_concreteness_classifier_accepts_entry_with_3_code_lines` — exactly 3 lines → accepted
  - [x] 27.6 Test: `test_cross_repo_entry_tagged_with_language_category_and_type` — stored entry metadata includes `language`, `category`, `vulnerability_type`, `installation_id`
  - [x] 27.7 Test: `test_rollback_to_previous_version_excludes_newer_entries` — after rollback to v2, only v1 and v2 entries returned by `KnowledgeBase.query`
  - [x] 27.8 Test: `test_corpus_retains_last_5_versions` — 6 versions exist → version 1 deactivated; versions 2–6 retained
  - [x] 27.9 Test: `test_query_with_weight_produces_different_ranking_than_without` — same query, `python: 1.5` weight vs no weight → ranking differs for Python entries
  - [x] 27.10 Implement `pr_reviewer/kb/cross_repo.py` — `CrossRepoLearning` with `add_cross_repo_fix` and `_check_code_concreteness`; secret scrubbing; embeds and inserts into `cross_repo_fixes` collection; corpus versioning with retain-last-5 policy
  - [x] 27.11 Extend `pr_reviewer/workers/feedback_processor.py` — after `FeedbackStore.insert`, call `CrossRepoLearning.add_cross_repo_fix` when `signal.signal_type == positive` and `config.cross_repo_sharing == True`
  _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5_

- [x] 28. v2 evaluation harness — knowledge retrieval quality **[v2]**
  - [x] 28.1 Test: `test_ablation_run_computes_delta_precision_per_category` — two run results (KB enabled, disabled) → `delta_precision` per category in ablation report
  - [x] 28.2 Test: `test_retrieval_relevance_scored_per_kb_call` — eval trace with 3 `query_knowledge_base` calls → 3 relevance scores produced using `relevance_judge`
  - [x] 28.3 Test: `test_mean_relevance_computed_per_corpus` — 5 calls to `cve_snapshot`, 3 to `org_guidelines` → separate mean scores per corpus
  - [x] 28.4 Test: `test_tool_budget_attribution_separates_kb_from_codebase_calls` — attribution result has `kb_calls: int` and `codebase_calls: int` summing to total budget used
  - [x] 28.5 Test: `test_corpus_flagged_when_mean_relevance_below_0_6_for_3_runs` — 3 consecutive eval runs with `cve_snapshot` mean relevance 0.4 → corpus flagged; notification triggered
  - [x] 28.6 Test: `test_corpus_not_flagged_on_only_2_consecutive_low_runs` — 2 runs below threshold, then 1 above → not flagged
  - [x] 28.7 Test: `test_index_contribution_delta_reported` — eval with `CodebaseIndex` vs without → precision/recall/FP delta in `IndexContributionReport`
  - [x] 28.8 Test: `test_retrieval_relevance_written_to_kb_retrieval_relevance_metric` — after eval run, `kb.retrieval_relevance` OTel gauge updated per corpus
  - [x] 28.9 Implement `eval/tasks/ablation.py` — Inspect AI task; runs corpus twice (KB on/off); reports delta table per category
  - [x] 28.10 Implement `eval/tasks/index_contribution.py` — ablation toggling `codebase_index_enabled`; produces `IndexContributionReport`
  - [x] 28.11 Implement `eval/retrieval_quality.py` — `score_retrieval_calls(trace, findings) -> dict[str, float]` using `relevance_judge`
  - [x] 28.12 Implement `eval/budget_attribution.py` — `attribute_budget(tool_calls) -> BudgetAttribution(kb_calls, codebase_calls, total)`
  - [x] 28.13 Implement `eval/corpus_health.py` — `CorpusHealthMonitor` with 3-run rolling window; `check_and_flag` triggers hook at <0.6 mean relevance for 3 consecutive runs
  - [x] 28.14 Add Alembic migration: `eval_corpus_health` table
  _Requirements: 13.5, 17.1, 17.2, 17.3, 17.4_

- [x] 29. Config completeness — KB corpus toggles and indexer scope/schedule
  - [x] 29.1 Test: `test_corpus_toggle_coding_guidelines_disables_org_guidelines` — `KnowledgeBaseConfig(coding_guidelines=False)` → `_corpus_enabled("org_guidelines")` returns `False`
  - [x] 29.2 Test: `test_corpus_toggle_fix_knowledge_base_disables_collection` — `KnowledgeBaseConfig(fix_knowledge_base=False)` → `_corpus_enabled("fix_knowledge_base")` returns `False`
  - [x] 29.3 Test: `test_corpus_toggle_lessons_learned_disables_collection` — `KnowledgeBaseConfig(lessons_learned=False)` → `_corpus_enabled("lessons_learned")` returns `False`
  - [x] 29.4 Test: `test_lookup_cve_skipped_when_live_cve_lookup_false` — `config.knowledge_base.live_cve_lookup=False` → `lookup_cve(...)` returns `[]`; `mcp_client.lookup_cve` not called
  - [x] 29.5 Test: `test_check_package_advisory_skipped_when_live_package_advisory_false` — `config.knowledge_base.live_package_advisory=False` → `check_package_advisory(...)` returns `[]`; `mcp_client.check_package_advisory` not called
  - [x] 29.6 Test: `test_index_scope_single_skips_monorepo_detection` — `config.index_scope="single"` → `_detect_monorepo` never called; `IndexScope.single` used directly
  - [x] 29.7 Test: `test_index_scope_monorepo_forces_monorepo_path` — `config.index_scope="monorepo"` → monorepo code path taken even when `_detect_monorepo` returns empty list
  - [x] 29.8 Test: `test_index_refresh_schedule_on_merge_skips_beat_triggered_run` — `config.index_refresh_schedule="on_merge"` → `run_index_refresh_task` body returns early without calling `Indexer.refresh`
  - [x] 29.9 Test: `test_index_refresh_schedule_weekly_skips_if_refreshed_within_7_days` — last refresh 5 days ago, `index_refresh_schedule="weekly"` → task returns early
  - [x] 29.10 Test: `test_index_refresh_schedule_weekly_runs_if_refreshed_8_days_ago` — last refresh 8 days ago, `index_refresh_schedule="weekly"` → task proceeds to `Indexer.refresh`
  - [x] 29.11 Wire `_CORPUS_CONFIG_ATTR` in `pr_reviewer/kb/knowledge_base.py` — add `org_guidelines → coding_guidelines`, `fix_knowledge_base → fix_knowledge_base`, `lessons_learned → lessons_learned`
  - [x] 29.12 Wire config gates in `pr_reviewer/agents/tools.py` — `lookup_cve` returns `[]` when `live_cve_lookup=False`; `check_package_advisory` returns `[]` when `live_package_advisory=False`
  - [x] 29.13 Wire `index_scope` in `pr_reviewer/workers/indexer.py` `Indexer.refresh` — `"single"` bypasses `_detect_monorepo`; `"monorepo"` forces the monorepo path
  - [x] 29.14 Wire `index_refresh_schedule` in `run_index_refresh_task` — `"on_merge"` returns early; `"weekly"` checks last-refresh timestamp in Redis before proceeding
  _Requirements: 11.9, 12.4, 14.5_

- [x] 30. Wire `process_review_job` to `JobProcessor` — end-to-end task execution
  - [x] 30.1 Test: `test_creates_job_and_calls_processor` — `process_review_job(payload)` → `job_store.create_from_payload` called once; `processor.process(job)` called once
  - [x] 30.2 Test: `test_uses_installation_id_from_payload` — `payload["installation"]["id"] == 99` → `make_processor(99)` called
  - [x] 30.3 Test: `test_missing_installation_id_defaults_to_zero` — payload with no `installation.id` → `make_processor(0)` called
  - [x] 30.4 Test: `test_returns_job_with_payload_fields` — `JobStore.create_from_payload` maps `installation.id`, `repository.full_name`, `pull_request.number`, `pull_request.head.sha` to `Job`
  - [x] 30.5 Test: `test_last_reviewed_sha_set_when_previous_complete_exists` — prior complete job found → `Job.last_reviewed_sha` populated
  - [x] 30.6 Test: `test_job_id_is_unique_per_call` — two calls produce distinct `job.id` values
  - [x] 30.7 Test: `test_update_status_executes_update` — `update_status(id, failed)` executes a DB UPDATE
  - [x] 30.8 Test: `test_update_success_executes_update` — `update_success(id, sha, tokens)` executes a DB UPDATE
  - [x] 30.9 Create `pr_reviewer/agents/llm.py` — `make_llm()` returns `_AzureOpenAILLM` when `AZURE_OPENAI_API_KEY` and `AZURE_OPENAI_ENDPOINT` are set; falls back to `_NoopLLM` stub otherwise
  - [x] 30.10 Create `pr_reviewer/store/job_store.py` — `JobStore` with `create_from_payload`, `update_status`, `update_success`, `_get_last_reviewed_sha`
  - [x] 30.11 Create `pr_reviewer/workers/container.py` — `WorkerContainer` holding shared connections (engine, Redis, ChromaDB, KnowledgeBase, MCPClient, ReviewAgent); `make_processor(installation_id)` creates per-request `JobProcessor`; `get_container()` returns process-level singleton
  - [x] 30.12 Replace `raise NotImplementedError` stub in `tasks.py` — `process_review_job` calls `get_container().job_store.create_from_payload(payload)` then `container.make_processor(installation_id).process(job)`
  _Requirements: 6.1, 6.2, 6.3_

- [x] 31. Bug fixes surfaced during first live end-to-end run
  - [x] 31.1 Fix `tools.py` — `fetch_pr_metadata` was calling `ctx.github_client.get_pr_metadata(**kwargs)` with no `repo` or `pr_number`; now passes `repo=ctx.repo, pr_number=ctx.pr_number`
  - [x] 31.2 Fix `tools.py` — `fetch_file_content` missing `repo=ctx.repo` in `get_file_content` call
  - [x] 31.3 Fix `tools.py` — `search_file` missing `repo=ctx.repo` in `search_file` call
  - [x] 31.4 Fix `tools.py` — `list_directory` missing `repo=ctx.repo, ref="HEAD"` in `list_directory` call
  - [x] 31.5 Fix `tools.py` — `get_symbol_usages` missing `repo=ctx.repo` in `get_symbol_usages` call
  - [x] 31.6 Add `get_pr_metadata(repo, pr_number)` to `GitHubAPIClient` — GET `/repos/{repo}/pulls/{pr_number}`; was called by tools but not implemented
  - [x] 31.7 Add `search_file(repo, path, query)` to `GitHubAPIClient` — GET `/search/code` with `query repo:{repo} path:{path}`; was called by tools but not implemented
  - [x] 31.8 Fix `review_agent.py` — add `except Exception` catch around LLM call (Step 3) so network/auth errors log and continue rather than crashing the task; previously only `TimeoutError` was caught
  - [x] 31.9 Switch primary LLM to Azure AI Foundry Claude via `litellm` — `make_llm()` now tries `AZURE_ANTHROPIC_API_KEY` + `AZURE_ANTHROPIC_ENDPOINT` first, falls back to Azure OpenAI
  _Requirements: 6.1, 6.3_

- [x] 32. Pre-deployment runtime bug fixes (surfaced during live PR review run)
  - [x] 32.1 Fix `diff_parser.py` — raise `_MAX_CHANGED_LINES` from 3000 → 10000; the old limit truncated at ~12 files and excluded `titanium.js` (the intentionally-vulnerable test target)
  - [x] 32.2 Fix `job_processor.py` — add truncation warning log after `DiffParser.parse()` listing included filenames when `diff.truncated` is True
  - [x] 32.3 Fix `github_client.py` — add `timeout=30.0` to `httpx.Client`; no timeout caused `ReadTimeout` when posting large review payloads (28 findings) to GitHub

- [x] 33. Azure Container Apps deployment infrastructure
  - [x] 33.1 Create `Dockerfile` — python:3.12-slim base; uv for dependency install (`--frozen --no-dev`); copies `pr_reviewer/`, `alembic/`, `alembic.ini`; single image, role selected via CMD override in entrypoint
  - [x] 33.2 Create `docker-entrypoint.sh` — case/esac dispatcher: `api` (migrate + uvicorn), `worker-review`, `worker-feedback`, `worker-indexer`, `beat` (celery), `seed-kb` (kb bootstrap + sync), `migrate` (alembic only)
  - [x] 33.3 Create `.dockerignore` — excludes `.venv/`, `__pycache__`, test dirs, `infra/`, `.env*` (not `.env.example`), logs, data
  - [x] 33.4 Create `infra/terraform/terraform.tf` — azurerm ~> 3.100 + random ~> 3.6; Azure Storage backend (`sttfstateprreviewer/tfstate/pr-reviewer.tfstate`); data sources for RG and ACR; user-assigned managed identity for AcrPull; Log Analytics workspace; `required_version >= 1.7`
  - [x] 33.5 Create `infra/terraform/variables.tf` — all input variables with descriptions and sensitive markers; `image_tag` validation (non-empty); `azure_openai_endpoint` validation (must start with `https://`)
  - [x] 33.6 Create `infra/terraform/locals.tf` — `prefix`, `image_ref`, `db_url`, `redis_url`, `chromadb_url`, `otel_endpoint`; `urlencode()` applied to DB password and Redis access key in URL construction to handle base64 special characters
  - [x] 33.7 Create `infra/terraform/postgres.tf` — `azurerm_postgresql_flexible_server` (B_Standard_B1ms, v16, 32 GB); database resource; firewall rule allowing Azure-originated traffic (0.0.0.0–0.0.0.0)
  - [x] 33.8 Create `infra/terraform/redis.tf` — `azurerm_redis_cache` Basic C1; `non_ssl_port_enabled = false`; TLS 1.2 minimum
  - [x] 33.9 Create `infra/terraform/storage.tf` — storage account + share for ChromaDB data (50 GB, ReadWrite); share for OTel config (1 GB, ReadOnly); `azurerm_storage_share_file` uploads local `otel/collector-config.yml`; both shares mounted into the ACA environment
  - [x] 33.10 Create `infra/terraform/aca.tf` — ACA environment (Log Analytics linked); 7 container apps: `otel-collector` (internal, port 4318), `chromadb` (internal, Azure Files volume), `api` (external ingress, min 1/max 3 replicas), `worker-review`, `worker-feedback`, `worker-indexer`, `beat` (all internal, min/max 1); ACA Job `kb-seed` (manual trigger, 600s timeout)
  - [x] 33.11 Create `infra/terraform/outputs.tf` — `api_fqdn`, `api_fqdn_raw`, `postgres_fqdn`, `redis_hostname`, `chromadb_internal_fqdn`, `kb_seed_job_trigger`, `otel_collector_endpoint`, `acr_login_server`
  - [x] 33.12 Create `infra/scripts/bootstrap-state.sh` — one-time creation of Azure Storage account and container for Terraform state backend
  - [x] 33.13 Create `infra/scripts/build-push.sh` — Podman build (`--platform linux/amd64`) + push to ACR using `az acr login --expose-token` with fixed username `00000000-0000-0000-0000-000000000000`
  - [x] 33.14 Create `infra/scripts/set-secrets.sh` (gitignored + dockerignored) — exports all `TF_VAR_*` secrets; pre-populated from `.env`
  - [x] 33.15 Create `infra/scripts/deploy.sh` — single-command deployment: load secrets → build + push image (tag = git short SHA by default) → `terraform init -reconfigure` → `terraform plan` → `terraform apply`; flags: `--tag`, `--skip-build`, `--seed`, `--plan-only`; prints API URL and webhook URL on completion
  - [x] 33.16 Add Terraform tests in `infra/terraform/tests/` — `smoke.tftest.hcl` (full plan with mocked providers), `locals.tftest.hcl` (prefix, image_ref, db_name, db_user assertions), `variable_validation.tftest.hcl` (empty tag rejected, HTTP endpoint rejected, valid values accepted); all 10 tests pass
  - [x] 33.17 Update `.gitignore` — add Terraform state files, `.terraform/`, `.terraform.lock.hcl`, `set-secrets.sh`
  - [x] 33.18 Update `README.md` — replace 8-step Azure deployment section with 7-step flow where Step 4 is a single `./infra/scripts/deploy.sh` command; document all deploy flags; update prerequisites to Terraform ≥ 1.7 and Podman

- [x] 34. Fix OTel transport and wire setup_telemetry into all entrypoints
  - [x] 34.1 Fix `telemetry.py` — switch from `otlp.proto.grpc.*` to `otlp.proto.http.*` exporters; ACA internal ingress exposes port 4318 (HTTP/protobuf) only — gRPC on 4317 is not reachable; gRPC exporter class ignores `OTEL_EXPORTER_OTLP_PROTOCOL` env var
  - [x] 34.2 Fix `telemetry.py` — HTTP OTLP exporters require the full path in `endpoint`; append `/v1/traces` and `/v1/metrics` to `OTEL_EXPORTER_OTLP_ENDPOINT`; update default port from 4317 → 4318; remove `insecure=True` (not a parameter on the HTTP exporter)
  - [x] 34.3 Fix `api/main.py` — `setup_telemetry("pr-reviewer-api")` was never called; OTel was entirely inactive in the API process; call it inside `build_app()` before the FastAPI instance is created
  - [x] 34.4 Fix `workers/celery_app.py` — add `worker_process_init` signal handler `_setup_worker_telemetry` that calls `setup_telemetry("pr-reviewer-worker")`; OTel was never initialised in any worker process

- [x] 35. Bug fixes — Azure Redis SSL and post-deploy observations (2026-05-21)
  - [x] 35.1 Fix `celery_app.py`, `container.py`, `indexer.py` — pass `ssl.CERT_NONE` as kwarg to `redis.Redis.from_url()` for `rediss://` URLs; redis-py 5.x rejects `"CERT_NONE"` string from URL query params
  - [x] 35.2 Fix `container.py` (extracted `_make_redis_client` helper) — strip `ssl_cert_reqs` from URL before `from_url()` call; redis-py 5.x applies URL-parsed options after kwargs, overwriting the kwarg fix in 35.1; helper deduplicates logic across all three files
  - [x] 35.3 First live Azure deployment confirmed — PR #42 reviewed end-to-end in 31.3s; 24 findings posted; all resources reachable (Redis, PostgreSQL, ChromaDB, Azure OpenAI, GitHub API)
  - [x] 35.4 Fix `kb/cli.py` — `bootstrap` was non-idempotent; added `SELECT 1 ... LIMIT 1` existence check on `(corpus, content)` before each insert; re-running `seed-kb` now skips existing entries rather than creating duplicate vectors; added `test_bootstrap_is_idempotent`
  - [x] 35.5 Fix `diff_parser.py` — raise `_MAX_CHANGED_LINES` from 10,000 → 100,000 to support larger PRs

## Notes

- Tasks marked **[v2]** depend on all v1 tasks completing first; v2 may be deferred until the Feedback_Store has accumulated meaningful signal (3–6 months of reviews)
- All tasks follow TDD: write the failing tests first (RED), write minimum implementation to pass (GREEN), refactor while keeping tests green (IMPROVE)
- Never start a task before the previous one is marked complete; never edit files shared by two in-progress tasks simultaneously
- Requirements references use dot notation: `X.Y` means Requirement X, Acceptance Criterion Y
- Evaluation harness tasks (18–20, 28) must have zero runtime imports from `pr_reviewer` — enforced by `test_eval_package_has_zero_pr_reviewer_imports` in task 18
- OTel setup (task 2) must be the first implementation task; all subsequent tasks import from `pr_reviewer/telemetry.py` rather than re-creating instruments
- The `push` event in task 23 adds routing that task 5 deliberately excluded; update task 5's `test_unsupported_event_returns_200_and_not_enqueued` to use `X-GitHub-Event: ping` rather than `push` once task 23 is complete

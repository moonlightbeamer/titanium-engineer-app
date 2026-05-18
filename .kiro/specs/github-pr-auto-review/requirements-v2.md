# Requirements Document — Version 2

## Overview

This document captures the v2 vision for the GitHub PR Auto-Review tool. It builds directly on the v1 foundation (see `requirements.md`) and should be read in that context. The central theme of v2 is **persistent codebase memory**: the Review_Agent stops rebuilding its understanding from scratch on every PR and instead starts each review already knowing the codebase — its architecture, conventions, and historical problem areas.

v2 is intentionally deferred from v1 because its value compounds with real usage data. The Feedback_Store introduced in v1 (Req 9) is the primary input to the Codebase_Index. After 3–6 months of reviews, the index encodes learned knowledge rather than just static analysis. Building it before that data exists produces a weaker result.

**Prerequisite:** v1 must be live and the Feedback_Store must have accumulated meaningful signal before v2 indexing is built.

---

## New Glossary Terms

- **Codebase_Index**: A per-repository structured summary of architectural roles, inferred conventions, and historical finding density, built by the Indexer and injected into the Review_Agent's initial context at the start of each review job.
- **Indexer**: The scheduled background job that builds and refreshes the Codebase_Index for each active repository.
- **Index_Store**: The persistent storage layer for Codebase_Index artifacts, one record per repository, with versioning and staleness tracking.
- **Architectural_Summary**: The section of the Codebase_Index that identifies key files and their roles — security boundaries, hot paths, entry points, data models.
- **Convention_Profile**: The section of the Codebase_Index that captures inferred codebase conventions — naming patterns, error handling style, test structure — derived from sampling existing files.
- **Finding_Density_Map**: The section of the Codebase_Index that records historical finding rates per directory and file pattern, derived from the Feedback_Store, used to direct the Review_Agent's scrutiny.

---

## Requirements

### Requirement 10: Codebase Indexing

**User Story:** As a senior engineer, I want the Review_Agent to start each review already knowing our codebase architecture and conventions, so that its findings are calibrated to our specific codebase rather than generic patterns.

#### Acceptance Criteria

1. THE Indexer SHALL build a Codebase_Index for each repository that has processed at least one PR review, storing the result in the Index_Store.
2. THE Codebase_Index SHALL contain three sections: Architectural_Summary, Convention_Profile, and Finding_Density_Map.
3. THE Architectural_Summary SHALL identify key files and their roles by analyzing directory structure, entry points, and import graphs using the existing Agent_Tools (`list_directory`, `fetch_file_content`, `get_symbol_usages`).
4. THE Convention_Profile SHALL be derived by sampling 10–20 existing files across the repository and inferring patterns for: naming conventions, error handling structure, test file location and naming, and import organization.
5. THE Finding_Density_Map SHALL be derived from the Feedback_Store — directories and file patterns with high historical positive-signal rates SHALL be flagged for increased scrutiny; those with high negative-signal rates SHALL be flagged as low-signal areas.
6. THE Indexer SHALL refresh the Codebase_Index on a configurable schedule (default: daily) and additionally WHEN a pull request is merged to the default branch that modifies more than 20 files.
7. THE Codebase_Index SHALL be versioned; each refresh SHALL produce a new version without overwriting the previous, retaining the last 3 versions for rollback.
8. IF the Indexer fails to complete a refresh, THE PR_Reviewer SHALL continue using the most recent valid Codebase_Index and log a staleness warning.
9. THE Codebase_Index for a single repository SHALL not exceed a configurable size limit (default: 8,000 tokens) to ensure it fits within the Review_Agent's initial context without consuming the Tool_Budget.
10. WHERE `codebase_index_enabled` is set to `true` in the Config, THE PR_Reviewer SHALL inject the current Codebase_Index into the Review_Agent's initial context before the job starts, alongside the structured diff.
11. WHERE `codebase_index_enabled` is `false` or absent, THE PR_Reviewer SHALL behave identically to v1 — no index is injected and no Indexer runs for that repository.

---

### Requirement 11: Index-Informed Review Behavior

**User Story:** As a developer, I want the Review_Agent to use codebase knowledge to produce more relevant findings, so that I receive fewer generic comments and more findings specific to how our codebase actually works.

#### Acceptance Criteria

1. WHEN a Codebase_Index is present in the agent's initial context, THE Review_Agent SHALL use the Convention_Profile to suppress style Findings for patterns that are consistent with the existing codebase.
2. WHEN a Codebase_Index is present, THE Review_Agent SHALL use the Finding_Density_Map to allocate more of its Tool_Budget to files and directories with historically high positive-signal rates.
3. WHEN a Codebase_Index is present, THE Review_Agent SHALL use the Architectural_Summary to identify whether changed files are in the security boundary, and SHALL apply stricter verification (lower confidence threshold before escalating) to security candidates in those files.
4. WHEN a Codebase_Index is present and a security candidate is found in a file identified as a test fixture in the Architectural_Summary, THE Review_Agent SHALL automatically discard the candidate without consuming a Tool_Budget call for verification.
5. THE Evaluation_Harness SHALL run the agreed test suite with and without the Codebase_Index and report the delta in precision, recall, and false positive rate to measure index contribution.

---

### Requirement 12: Index Staleness and Monorepo Handling

**User Story:** As a repository maintainer, I want the Codebase_Index to stay accurate as the codebase evolves, so that the Review_Agent's knowledge doesn't drift from reality.

#### Acceptance Criteria

1. THE Codebase_Index SHALL record the commit SHA of the default branch at the time of the last refresh.
2. WHEN the Review_Agent starts a job, THE PR_Reviewer SHALL compare the recorded commit SHA against the current default branch HEAD. IF the index is more than 500 commits behind, THE PR_Reviewer SHALL log a staleness warning and trigger an out-of-schedule refresh.
3. FOR monorepos, THE Indexer SHALL build a separate Codebase_Index per top-level package or service directory, identified by the presence of a package manifest (`package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`, or equivalent) in a subdirectory.
4. WHEN a PR modifies files in multiple monorepo packages, THE PR_Reviewer SHALL inject only the Codebase_Index sections relevant to the modified packages, subject to the 8,000-token size limit.
5. THE Config SHALL support a `index_scope` field to override automatic monorepo detection:

```yaml
codebase_index_enabled: true
index_scope: monorepo   # auto | monorepo | single; default is auto
index_refresh_schedule: daily  # daily | weekly | on_merge; default is daily
index_max_tokens: 8000  # int; max tokens for injected index content
```

---

## v2 Design Constraints (Flagged for Solution Architect)

These are known hard problems that the design phase must address before implementation:

1. **Index size vs. context window**: The 8,000-token default must be validated against GPT-4o's context window after accounting for the diff, few-shot feedback examples (Req 9), and system prompt. The total initial context budget needs to be explicitly allocated across these inputs.

2. **Convention inference accuracy**: Sampling 10–20 files may not capture conventions in large, heterogeneous codebases. The design should specify which files are sampled (e.g., most recently modified, most frequently changed) and how conflicting patterns are resolved.

3. **Finding_Density_Map cold start**: On first index build, the Feedback_Store may have insufficient signal. The design should specify a minimum signal threshold before the Finding_Density_Map is included, and fallback behavior when below threshold.

4. **Indexer resource isolation**: The Indexer makes many GitHub API calls (file fetches, directory listings) and must not compete with live review jobs for rate limit quota. The design should specify separate rate limit budgets or scheduling windows.

5. **Privacy**: The Codebase_Index contains structural information about the repository. The design must specify whether the Index_Store is per-installation (on-premise) or centralized, and what data residency guarantees apply.

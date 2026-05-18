# Requirements Document

## Introduction

The GitHub PR Auto-Review tool is a developer tool that integrates with GitHub to automatically perform first-pass code reviews on pull requests. It identifies bugs, security anti-patterns, style issues, and performance problems, then posts line-level review comments as a bot reviewer — including corrected code suggestions with plain-English explanations. The goal is to reduce senior engineer review burden and shorten feedback cycles for junior developers.

## Glossary

- **PR_Reviewer**: The automated bot system that reads PR diffs and posts review comments to GitHub.
- **Diff_Parser**: The component responsible for parsing raw GitHub PR diffs into structured, line-addressable format.
- **Review_Engine**: The LLM-backed component that analyzes structured diff data and produces categorized review findings.
- **Comment_Poster**: The component that formats findings and posts them as review comments to the GitHub API.
- **Finding**: A single identified issue in the diff, including category, line reference, explanation, and optional code suggestion.
- **Review_Category**: One of four analysis dimensions: bugs, security, style, or performance.
- **GitHub_App**: The registered GitHub App that authenticates the PR_Reviewer and grants it permission to read PRs and post comments.
- **Evaluation_Harness**: The test suite used to measure false positive rates and review quality.
- **False_Positive**: A Finding flagged as a security issue that is not actually a security vulnerability.
- **Config**: The per-repository configuration file that controls PR_Reviewer behavior.
- **Installation_Access_Token**: A scoped, short-lived token (valid for 1 hour) issued by GitHub in exchange for a signed JWT, used to authenticate all GitHub REST API calls on behalf of the GitHub_App installation.
- **Job_Queue**: The async queue used to decouple webhook receipt from review processing.
- **Commit_SHA**: The full SHA-1 hash identifying a specific commit on a pull request branch.
- **Secret_Scrubber**: The pre-processing step that detects and redacts lines matching known secret patterns before diff content is sent to the LLM provider.

---

## Requirements

### Requirement 1: GitHub App Authentication and PR Access

**User Story:** As a repository maintainer, I want the PR_Reviewer to authenticate via a GitHub App, so that it can securely read PR diffs and post comments without using personal credentials.

#### Acceptance Criteria

1. THE GitHub_App SHALL authenticate with GitHub by first generating a signed JWT using the App's private key and App ID, then exchanging that JWT for an Installation_Access_Token via the GitHub Apps REST API, and then using the Installation_Access_Token for all subsequent GitHub REST API calls within that installation context.
2. WHEN a pull request is opened or updated, THE PR_Reviewer SHALL receive a webhook event from GitHub.
3. WHEN a webhook event is received, THE PR_Reviewer SHALL reject requests where the HMAC-SHA256 signature of the request body does not match the value in the `X-Hub-Signature-256` header.
4. WHEN a webhook event passes signature validation, THE PR_Reviewer SHALL enqueue the event on the Job_Queue and acknowledge receipt within 3 seconds.
5. WHEN a job is dequeued, THE PR_Reviewer SHALL retrieve the full diff for the pull request using the GitHub REST API.
6. WHEN a webhook event is received, THE PR_Reviewer SHALL check whether a review from the bot already exists for the same Commit_SHA before posting.
7. IF a review already exists for that Commit_SHA, THEN THE PR_Reviewer SHALL skip posting and log a deduplication notice.
8. WHEN a new commit is pushed to an open pull request, THE PR_Reviewer SHALL NOT re-post findings on lines that already have a comment from a prior bot review on the same file and line position.

   > Note: Computing per-commit diffs requires the GitHub compare endpoint and is flagged as a known complexity item for the design phase.

9. IF the GitHub API returns an authentication error, THEN THE PR_Reviewer SHALL log the error with the request context and halt processing for that event.
10. IF the GitHub API returns a rate-limit response, THEN THE PR_Reviewer SHALL retry the request after the duration specified in the `Retry-After` header, up to 3 times.
11. WHEN an Installation_Access_Token is within 5 minutes of expiry during job processing, THE PR_Reviewer SHALL refresh it before making the next API call.
12. IF a job fails processing, THEN THE PR_Reviewer SHALL retry it up to 3 times before moving it to the dead-letter queue.
13. WHEN a job is moved to the dead-letter queue after exhausting retries, THE PR_Reviewer SHALL post a top-level PR comment notifying the pull request author that automated review failed.
14. WHEN a webhook event is received for a pull request in draft state, THE PR_Reviewer SHALL skip processing unless the Config field `review_draft_prs` is set to true.

---

### Requirement 2: PR Diff Parsing

**User Story:** As a developer, I want PR diffs parsed into a structured format, so that the Review_Engine can reference specific files and line numbers when generating findings.

#### Acceptance Criteria

1. WHEN a raw unified diff is received, THE Diff_Parser SHALL produce a structured representation containing file path, hunk headers, and per-line change type (added, removed, context).
2. THE Diff_Parser SHALL preserve the GitHub pull request line position index for each changed line, enabling accurate comment placement via the GitHub API.
3. THE Diff_Parser SHALL skip files matching a default ignore list including: `package-lock.json`, `yarn.lock`, `*.lock`, `vendor/**`, `generated/**`, `*.pb.go`, `*.min.js`, and `*.min.css`.
4. WHERE a Config file is present, THE PR_Reviewer SHALL apply the `ignore_patterns_extend` field (a list of glob patterns added to the default ignore list) and the `ignore_patterns_override` field (a list of glob patterns that fully replaces the default ignore list when present) to control which files are skipped.
5. IF both `ignore_patterns_override` and `ignore_patterns_extend` are present in the Config, THEN `ignore_patterns_override` SHALL take precedence, `ignore_patterns_extend` SHALL be ignored, and THE PR_Reviewer SHALL log a warning about the conflicting fields.
6. IF a diff contains binary files, THEN THE Diff_Parser SHALL skip those files and record them in a skipped-files list.
7. IF a diff exceeds 3,000 changed lines, THEN THE Diff_Parser SHALL truncate to the first 3,000 changed lines and include a truncation notice in the structured output.
8. FOR ALL parsed diffs, the line position assigned to each changed line SHALL match the position index reported by the GitHub pull request diff API for that line.

---

### Requirement 3: Multi-Category Review Analysis

**User Story:** As a senior engineer, I want the Review_Engine to analyze PRs across four categories, so that routine issues are caught automatically without my manual review.

#### Acceptance Criteria

1. THE Review_Engine SHALL analyze each structured diff against four Review_Categories: bugs, security, style, and performance.
2. THE Review_Engine SHALL use OpenAI GPT-4o as the primary LLM provider, and the Review_Engine interface SHALL be designed to be provider-pluggable to allow substitution of other LLM providers.
3. THE Review_Engine SHALL use a separate prompt template for each Review_Category.
4. BEFORE sending diff content to the LLM provider for ANY Review_Category, THE Review_Engine SHALL scan the diff using the Secret_Scrubber and redact lines matching known secret patterns. THE PR_Reviewer SHALL treat Secret_Scrubber detections as the authoritative signal for committed secrets; the security Review_Category SHALL NOT be expected to produce Findings for lines that have been redacted.
5. WHEN the Review_Engine processes a diff, THE Review_Engine SHALL produce zero or more Findings per Review_Category.
6. WHEN a Finding is produced, THE Review_Engine SHALL assign it exactly one Review_Category.
7. WHEN a Finding is produced, THE Review_Engine SHALL include the file path, line number, a plain-English explanation of at least one sentence, and a severity level of low, medium, or high.
8. WHEN a diff exceeds a configurable token threshold, THE Review_Engine SHALL split the diff into chunks and analyze each chunk independently per Review_Category, then deduplicate Findings from multiple chunks by file path and line number before posting.
9. IF the LLM provider returns an error or timeout after 30 seconds, THEN THE Review_Engine SHALL retry the request once after a 1-second delay, and IF the retry fails, THEN THE Review_Engine SHALL record the failure and skip that Review_Category for the current diff.

---

### Requirement 4: Code Suggestion Generation

**User Story:** As a junior developer, I want each finding to include a corrected code snippet, so that I understand exactly what change is recommended without guessing.

#### Acceptance Criteria

1. WHEN a Finding of severity medium or high is produced, THE Review_Engine SHALL generate a corrected code suggestion for the flagged lines.
2. THE Review_Engine SHALL format code suggestions as valid GitHub suggestion blocks, compatible with GitHub's pull request suggestion API.
3. WHEN a Finding spans multiple lines, THE Review_Engine SHALL format the suggestion using GitHub's multi-line suggestion syntax with `start_line` and `line` fields.
4. WHEN a Finding spans a single line, THE Review_Engine SHALL use single-line suggestion syntax.
5. WHEN a code suggestion is generated, THE Review_Engine SHALL include a plain-English explanation describing what was changed and why.
6. IF the Review_Engine cannot generate a syntactically valid suggestion for a Finding, THEN THE Review_Engine SHALL omit the suggestion block and retain the plain-English explanation only.

---

### Requirement 5: Posting Review Comments to GitHub

**User Story:** As a developer, I want review findings posted as inline PR comments by the bot, so that I can see feedback directly in the GitHub pull request interface.

#### Acceptance Criteria

1. WHEN the Review_Engine produces one or more Findings, THE Comment_Poster SHALL submit them as a single GitHub pull request review via the GitHub Reviews API.
2. THE Comment_Poster SHALL post each Finding as an inline comment anchored to the specific file path and line position from the Finding.
3. WHEN all Findings have severity low, THE Comment_Poster SHALL submit the review with status `COMMENT`.
4. WHEN one or more Findings have severity medium and no Findings have severity high, THE Comment_Poster SHALL submit the review with status `COMMENT`.
5. WHEN one or more Findings have severity high, THE Comment_Poster SHALL submit the review with status `REQUEST_CHANGES`.
6. WHEN no Findings are produced for a pull request, THE Comment_Poster SHALL post a single top-level review comment stating that no issues were found, with status `COMMENT`.
7. WHERE the Config field `auto_approve_on_no_findings` is set to `true`, THE Comment_Poster SHALL submit the review with status `APPROVE` instead of `COMMENT` when no Findings are produced.
8. IF the GitHub Reviews API returns a 422 error for a specific comment, THEN THE Comment_Poster SHALL skip that comment, log the invalid line reference, and continue posting remaining comments.
9. WHEN THE Comment_Poster submits a review, THE Comment_Poster SHALL populate the top-level review body with a summary in the format: 'Found N issue(s) across M category/categories.' WHEN no Findings are produced, the body SHALL read: 'No issues found.'
10. BEFORE posting a review, THE Comment_Poster SHALL retrieve all existing review comments on the pull request from the GitHub API and use them to skip any Finding whose file path and line position already has a comment from a prior bot review.

---

### Requirement 6: Zero False Security Positives on Agreed Test Suite

**User Story:** As a VP of Engineering, I want the PR_Reviewer to produce zero false security positives on the agreed test suite, so that developers trust the security findings and do not ignore them.

#### Acceptance Criteria

1. THE Evaluation_Harness SHALL execute the PR_Reviewer against a defined set of test PRs with known ground-truth labels.
2. THE Evaluation_Harness test corpus SHALL consist of at least 20 test PRs sourced from open-source GitHub repositories, with ground-truth labels applied by the engineering team before implementation begins, each ground-truth label SHALL be reviewed and agreed upon by at least two engineers before the corpus is locked, and at least 10 of those PRs SHALL contain no security vulnerabilities.
3. WHEN the Evaluation_Harness runs, THE PR_Reviewer SHALL produce zero Findings categorized as security on test PRs that contain no security vulnerabilities.
4. THE Evaluation_Harness SHALL report precision, recall, and false positive count per Review_Category after each run.
5. WHEN the false positive count for the security Review_Category exceeds zero on the agreed test suite, THE Evaluation_Harness SHALL mark the run as failed and output the offending Findings.

---

### Requirement 7: Per-Repository Configuration

**User Story:** As a repository maintainer, I want to configure which review categories are enabled and set severity thresholds, so that the PR_Reviewer fits my team's workflow.

#### Acceptance Criteria

1. THE PR_Reviewer SHALL read a Config file from the path `.github/pr-auto-review.yml` in the target repository when processing a pull request.
2. WHERE a Config file is present, THE PR_Reviewer SHALL enable only the Review_Categories listed in the `enabled_categories` field.
3. WHERE a Config file is absent, THE PR_Reviewer SHALL enable all four Review_Categories with a default min_severity of low (all findings posted) and a default token_threshold of 6000.
4. WHERE a Config file is present, THE PR_Reviewer SHALL apply the `min_severity` field to suppress Findings below the specified severity level before posting.
5. IF the Config file contains invalid YAML or unrecognized fields, THEN THE PR_Reviewer SHALL log a warning, ignore the invalid Config, and apply default settings.
6. THE Config file SHALL support the following fields and types:

```yaml
enabled_categories: [bugs, security, style, performance]  # list of Review_Category values
min_severity: low        # low | medium | high; default is low (all findings posted)
auto_approve_on_no_findings: false  # bool; when true, post APPROVE instead of COMMENT on clean PRs
token_threshold: 6000    # int; max tokens per LLM chunk before splitting
review_draft_prs: false  # bool; when false, draft PRs are skipped
ignore_patterns_extend:
  - "vendor/**"          # list of glob patterns ADDED to the default ignore list
  - "*.min.js"
ignore_patterns_override:
  - "vendor/**"          # list of glob patterns that FULLY REPLACES the default ignore list
                         # when present, the default list is not applied
```

---

### Requirement 8: Review Latency SLO

**User Story:** As a developer, I want PR reviews posted promptly after I open or update a pull request, so that I can act on feedback without waiting.

#### Acceptance Criteria

1. THE PR_Reviewer SHALL use an async Job_Queue to decouple webhook receipt from review processing.
2. THE PR_Reviewer SHALL acknowledge webhook events within 3 seconds of receipt.
3. THE PR_Reviewer SHALL post a completed review within 5 minutes of receiving the webhook event with no more than 10 concurrent review jobs in the queue.
4. THE Evaluation_Harness SHALL measure and report end-to-end review latency per run, enforcing the condition of no more than 10 concurrent review jobs during latency measurement.

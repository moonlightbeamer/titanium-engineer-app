# Requirements Document

## Introduction

The GitHub PR Auto-Review tool is a developer tool that integrates with GitHub to automatically perform first-pass code reviews on pull requests. The tool is built around an LLM agent that reasons iteratively over PR diffs, fetching additional file context on demand before producing findings, rather than applying fixed prompt templates in a static pipeline. It identifies bugs, security anti-patterns, style issues, and performance problems, then posts line-level review comments as a bot reviewer — including corrected code suggestions with plain-English explanations. The goal is to reduce senior engineer review burden and shorten feedback cycles for junior developers.

## Glossary

- **PR_Reviewer**: The automated bot system that reads PR diffs and posts review comments to GitHub.
- **Diff_Parser**: The component responsible for parsing raw GitHub PR diffs into structured, line-addressable format.
- **Review_Engine** (deprecated — replaced by Review_Agent): see Review_Agent.
- **Review_Agent**: The LLM agent that orchestrates PR review by reasoning over diff content, invoking tools to gather additional context, and producing categorized Findings.
- **Tool_Budget**: The maximum number of tool calls the Review_Agent is permitted to make per PR review job, used to bound cost and latency.
- **Agent_Tool**: A discrete capability the Review_Agent can invoke during reasoning, such as fetching a full file, listing directory contents, or querying call sites of a modified function.
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
- **Feedback_Store**: The per-repository persistent store that records developer signals on bot findings — accepted suggestions, dismissed comments, and explicit corrections — used to inject few-shot examples into the Review_Agent's context on future reviews.
- **Escalation**: A special Finding type posted when a security candidate cannot be fully verified due to Tool_Budget exhaustion. Contains a human-readable question rather than a confirmed finding, and does not carry a severity level.

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

**User Story:** As a developer, I want PR diffs parsed into a structured format, so that the Review_Agent can reference specific files and line numbers when generating findings.

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

**User Story:** As a senior engineer, I want the Review_Agent to analyze PRs across four categories, so that routine issues are caught automatically without my manual review.

#### Acceptance Criteria

1. THE Review_Agent SHALL use OpenAI GPT-4o as the primary LLM provider, and the Review_Agent interface SHALL be designed to be provider-pluggable to allow substitution of other LLM providers.
2. THE Review_Agent SHALL have access to the following Agent_Tools during a review job. The structured diff is passed directly into the agent's initial context by the Diff_Parser before the job starts — the agent does not need to fetch it via a tool call:
   - `fetch_file_content(path, ref)`: retrieves the full content of a file at a given git ref from the repository
   - `fetch_pr_metadata(pr_number)`: returns the PR title, description, linked issues, and author; THE Review_Agent SHALL call this as its first tool call on every job to understand intent before analyzing code
   - `search_file(path, pattern)`: searches a file for lines matching a regex pattern
   - `list_directory(path, ref)`: lists files in a directory at a given git ref
   - `get_symbol_usages(symbol, path)`: returns lines in a file where a given symbol is referenced
   - `read_findings_so_far()`: returns all Findings the Review_Agent has produced so far in the current job, used for cross-category synthesis and deduplication
3. THE Review_Agent SHALL reason iteratively — it MAY invoke Agent_Tools to gather additional context before deciding whether to produce a Finding, rather than classifying based solely on the diff.
4. THE Review_Agent SHALL NOT exceed a configurable Tool_Budget of tool calls per PR review job. WHERE a Config file is absent, the default Tool_Budget SHALL be 20 tool calls per job. The mandatory `fetch_pr_metadata` call on job start is excluded from the Tool_Budget count, as it is infrastructure rather than agent reasoning. The mandatory `read_findings_so_far()` call during the synthesis step described in AC14 is also excluded from the Tool_Budget count.
5. WHEN the Review_Agent reaches the Tool_Budget limit, it SHALL finalize its current Findings and proceed to posting without further tool calls, logging that the budget was reached.
6. BEFORE invoking any Agent_Tool that fetches file content, THE Review_Agent SHALL pass the fetched content through the Secret_Scrubber before including it in the agent context.
7. THE Review_Agent SHALL analyze the diff across four Review_Categories: bugs, security, style, and performance. The agent MAY interleave reasoning across categories rather than processing them sequentially.
8. WHEN a Finding is produced, THE Review_Agent SHALL assign it exactly one Review_Category, include the file path, line number, a plain-English explanation of at least one sentence, and a severity level of low, medium, or high.
9. THE Review_Agent SHALL include a confidence score (low, medium, high) with each Finding. WHEN a Finding has confidence low, THE Review_Agent SHOULD attempt one additional tool call to gather supporting evidence before finalizing the Finding, subject to the Tool_Budget.
10. WHEN the Review_Agent produces a candidate security Finding, THE Review_Agent SHALL attempt to verify it by fetching the relevant file context using `fetch_file_content` before finalizing it as a Finding, subject to the Tool_Budget. IF the Tool_Budget is exhausted before verification completes, THE Review_Agent SHALL NOT silently discard the candidate; instead it SHALL post an Escalation comment in the format: "⚠️ Possible security concern on line {N} — could not fully verify due to context limits. Recommend a manual check: {reason the candidate was flagged}." Escalation comments SHALL be posted without a suggestion block and SHALL NOT count toward the severity-based review status determination.
11. BEFORE sending any diff or file content to the LLM provider, THE Review_Agent SHALL pass it through the Secret_Scrubber and redact lines matching known secret patterns. THE PR_Reviewer SHALL treat Secret_Scrubber detections as the authoritative signal for committed secrets; the security Review_Category SHALL NOT be expected to produce Findings for lines that have been redacted.
12. IF the LLM provider returns an error or timeout after 30 seconds, THEN THE Review_Agent SHALL retry the request once after a 1-second delay, and IF the retry fails, THEN THE Review_Agent SHALL record the failure, finalize any Findings produced so far, and proceed to posting.
13. THE Review_Agent SHALL NOT chunk diffs mechanically by token count. Instead, THE Review_Agent SHALL use fetch_file_content and related Agent_Tools to retrieve additional context on demand, bounded by the Tool_Budget.
14. BEFORE finalizing Findings for posting, THE Review_Agent SHALL call `read_findings_so_far()` and review all Findings produced across categories, merge Findings that reference the same file path and line number into a single Finding with a combined explanation, and annotate related Findings where a bug and a security issue share the same root cause. Cross-category relationship annotations SHALL be included inline in the plain-English explanation of the relevant Finding.
15. AFTER producing Findings, THE Review_Agent SHALL use `list_directory` and `search_file` to check whether functions modified in the diff have corresponding test coverage. WHERE a modified function has no identifiable test coverage, THE Review_Agent SHALL produce a Finding of Review_Category bugs with a suggested test case and an explanation of what behavior should be tested.

---

### Requirement 4: Code Suggestion Generation

**User Story:** As a junior developer, I want each finding to include a corrected code snippet, so that I understand exactly what change is recommended without guessing.

#### Acceptance Criteria

1. WHEN a Finding of severity medium or high is produced, THE Review_Agent SHALL generate a corrected code suggestion for the flagged lines.
2. THE Review_Agent SHALL format code suggestions as valid GitHub suggestion blocks, compatible with GitHub's pull request suggestion API.
3. WHEN a Finding spans multiple lines, THE Review_Agent SHALL format the suggestion using GitHub's multi-line suggestion syntax with `start_line` and `line` fields.
4. WHEN a Finding spans a single line, THE Review_Agent SHALL use single-line suggestion syntax.
5. WHEN a code suggestion is generated, THE Review_Agent SHALL include a plain-English explanation describing what was changed and why.
6. IF the Review_Agent cannot generate a syntactically valid suggestion for a Finding, THEN THE Review_Agent SHALL omit the suggestion block and retain the plain-English explanation only.

---

### Requirement 5: Posting Review Comments to GitHub

**User Story:** As a developer, I want review findings posted as inline PR comments by the bot, so that I can see feedback directly in the GitHub pull request interface.

#### Acceptance Criteria

1. WHEN the Review_Agent produces one or more Findings, THE Comment_Poster SHALL submit them as a single GitHub pull request review via the GitHub Reviews API.
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
2. THE Evaluation_Harness test corpus SHALL be defined and maintained as specified in Req 10 AC2.
3. WHEN the Evaluation_Harness runs, THE PR_Reviewer SHALL produce zero Findings categorized as security on test PRs that contain no security vulnerabilities.
4. THE Evaluation_Harness SHALL report precision, recall, and false positive count per Review_Category after each run.
5. WHEN the false positive count for the security Review_Category exceeds zero on the agreed test suite, THE Evaluation_Harness SHALL mark the run as failed and output the offending Findings.

---

### Requirement 7: Per-Repository Configuration

**User Story:** As a repository maintainer, I want to configure which review categories are enabled and set severity thresholds, so that the PR_Reviewer fits my team's workflow.

#### Acceptance Criteria

1. THE PR_Reviewer SHALL read a Config file from the path `.github/pr-auto-review.yml` in the target repository when processing a pull request.
2. WHERE a Config file is present, THE PR_Reviewer SHALL enable only the Review_Categories listed in the `enabled_categories` field.
3. WHERE a Config file is absent, THE PR_Reviewer SHALL enable all four Review_Categories with a default min_severity of low and a default Tool_Budget of 20 tool calls per job.
4. WHERE a Config file is present, THE PR_Reviewer SHALL apply the `min_severity` field to suppress Findings below the specified severity level before posting.
5. IF the Config file contains invalid YAML or unrecognized fields, THEN THE PR_Reviewer SHALL log a warning, ignore the invalid Config, and apply default settings.
6. THE Config file SHALL support the following fields and types:

```yaml
enabled_categories: [bugs, security, style, performance]  # list of Review_Category values
min_severity: low        # low | medium | high; default is low (all findings posted)
auto_approve_on_no_findings: false  # bool; when true, post APPROVE instead of COMMENT on clean PRs
tool_budget: 20          # int; max Agent_Tool calls per review job (replaces token_threshold — that field is not supported)
review_draft_prs: false  # bool; when false, draft PRs are skipped
codebase_index_enabled: false  # bool; reserved for v2 — when true, injects persistent codebase index into agent context
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
3. THE PR_Reviewer SHALL post a completed review within 10 minutes of receiving the webhook event with no more than 10 concurrent review jobs in the queue.
4. THE Evaluation_Harness SHALL measure and report end-to-end review latency per run, enforcing the condition of no more than 10 concurrent review jobs during latency measurement.
5. THE Evaluation_Harness SHALL report average Tool_Budget consumption per review job alongside latency metrics.

---

### Requirement 9: Feedback Loop and Continuous Improvement

**User Story:** As a VP of Engineering, I want the PR_Reviewer to learn from developer responses to its findings, so that review quality improves over time for each repository rather than plateauing at launch.

#### Acceptance Criteria

1. THE PR_Reviewer SHALL subscribe to GitHub webhook events for pull request review comment resolution, comment replies, and suggestion acceptance on comments posted by the bot.
2. WHEN a developer resolves a bot comment without applying the suggestion, THE PR_Reviewer SHALL record a negative signal in the Feedback_Store for that finding type, file path pattern, and repository.
3. WHEN a developer applies a bot suggestion block, THE PR_Reviewer SHALL record a positive signal in the Feedback_Store for that finding type, file path pattern, and repository.
4. WHEN a developer replies to a bot comment with text indicating disagreement (e.g., "not an issue", "false positive", "won't fix"), THE PR_Reviewer SHALL record a negative signal in the Feedback_Store for that finding type and repository.
5. BEFORE the Review_Agent begins analysis on a new PR, THE PR_Reviewer SHALL query the Feedback_Store for the repository and inject up to 5 relevant historical signals as few-shot examples in the agent's system prompt, prioritizing signals from the same file path patterns as the current diff.
6. THE Feedback_Store SHALL record, at minimum: repository ID, finding category, file path pattern, signal type (positive or negative), and timestamp.
7. THE Feedback_Store SHALL NOT store raw diff content, code snippets, or any content that passed through the Secret_Scrubber.
8. THE Evaluation_Harness SHALL report the number of accumulated feedback signals per repository and per Review_Category alongside precision and recall metrics.

---

### Requirement 10: Evaluation Harness (Separate Developer Tool)

**User Story:** As an engineer building the PR_Reviewer, I want a standalone evaluation harness that judges the agent's output quality and reports improvement or regression to the team, so that prompt changes and model updates are measurable rather than based on intuition.

#### Acceptance Criteria

1. THE Evaluation_Harness SHALL be a standalone system, separate from the PR_Reviewer app, with no runtime dependency on the live production service. It SHALL be runnable by any team member against any version of the PR_Reviewer.

2. THE Evaluation_Harness SHALL maintain a labeled test corpus of at least 20 pull requests sourced from open-source GitHub repositories, with ground-truth labels applied by at least two engineers before the corpus is locked. Each ground-truth label SHALL be reviewed and agreed upon by at least two engineers before the corpus is locked. The corpus SHALL include at least 10 PRs with no security vulnerabilities (for false-positive measurement) and at least 5 PRs with known security vulnerabilities (for recall measurement). For PRs in the corpus that contain known bugs, the ground-truth labels SHALL include a reference fix — the specific code change that correctly addresses the bug — used as the Token F1 reference in AC5.

3. THE Evaluation_Harness SHALL implement the following judge suite using LiteLLM-compatible judge calls, each returning a structured score and rationale:
   - `relevance_judge`: scores whether a Finding references something actually present in the diff (0–10)
   - `accuracy_judge`: scores whether the Finding's diagnosis is technically correct, using ground-truth labels as reference (0–10)
   - `actionability_judge`: scores whether the suggested fix is implementable as written (0–10)
   - `clarity_judge`: scores whether the plain-English explanation is clear to a junior developer (0–10)
   - `verification_trace_judge`: given the agent's tool call chain for a security candidate, scores whether the agent actually verified before deciding to confirm or discard (0–10)
   - `quality_with_cot_judge`: scores overall review quality with a chain-of-thought rationale, used for end-to-end coherence measurement (0–10)

4. THE Evaluation_Harness SHALL treat the four per-finding scores (relevance, accuracy, actionability, clarity) as a vector and SHALL NOT aggregate them into a single mean score. Each dimension SHALL be reported separately per Review_Category.

5. THE Evaluation_Harness SHALL implement classical metrics alongside LLM judges:
   - Schema validity: each Finding output SHALL conform to the defined Finding schema
   - Regex contains-check: security Findings SHALL reference a specific line number and file path
   - Token F1 against reference fixes for known bugs in the corpus

6. THE Evaluation_Harness SHALL track cost and latency per review job using `litellm.completion_cost`, reporting: total cost per review, tool calls consumed vs. Tool_Budget, and end-to-end latency from job start to review posted.

7. THE Evaluation_Harness SHALL detect same-family judge bias by running the security verification judge with at least two different LLM model families and reporting the score delta. The judge model used for the security category SHALL be a different model family than the Review_Agent's primary provider (GPT-4o).

8. THE Evaluation_Harness SHALL implement a meta-prompting improvement loop:
   - Identify the 5 lowest-scoring reviews by `quality_with_cot_judge`
   - Submit those reviews and the current Review_Agent system prompt to a reflector LLM
   - The reflector SHALL diagnose one specific failure mode and produce a revised system prompt
   - The Evaluation_Harness SHALL re-run the Review_Agent on the same inputs with the revised prompt and re-judge
   - The delta in scores SHALL be reported to the engineering team before the prompt change is approved for deployment

9. THE Evaluation_Harness SHALL be productionized as an Inspect AI task suite, enabling any team member to run `inspect eval` from the command line and view per-sample traces, judge rationales, and aggregate metrics in `inspect view` without reading notebook code.

10. THE Evaluation_Harness SHALL run on two triggers:
    - Before any prompt change or model update ships: full corpus run, must pass zero-false-positive gate on security (per Req 6) to proceed
    - Weekly on a random sample of 10 live reviews: human vibe check (1–5 score per review) logged to a dataframe alongside `quality_with_cot_judge` scores, with human-vs-judge correlation reported to track judge reliability over time
    Reviews sampled for human vibe check SHALL be sourced from the stored Findings output, not from raw diff content, and SHALL NOT contain any content that was redacted by the Secret_Scrubber during the original review job.

11. THE Evaluation_Harness SHALL report a summary to the engineering team after each run including: precision, recall, and false positive count per Review_Category; mean per-dimension finding scores; average cost and latency per review; Tool_Budget consumption distribution; and delta vs. the previous run for each metric.

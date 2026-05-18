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

---

## Requirements

### Requirement 1: GitHub App Authentication and PR Access

**User Story:** As a repository maintainer, I want the PR_Reviewer to authenticate via a GitHub App, so that it can securely read PR diffs and post comments without using personal credentials.

#### Acceptance Criteria

1. THE GitHub_App SHALL authenticate with GitHub using a private key and App ID via JWT-based authentication.
2. WHEN a pull request is opened or updated, THE PR_Reviewer SHALL receive a webhook event from GitHub.
3. WHEN a webhook event is received, THE PR_Reviewer SHALL retrieve the full diff for the pull request using the GitHub REST API.
4. IF the GitHub API returns an authentication error, THEN THE PR_Reviewer SHALL log the error with the request context and halt processing for that event.
5. IF the GitHub API returns a rate-limit response, THEN THE PR_Reviewer SHALL retry the request after the duration specified in the `Retry-After` header, up to 3 times.

---

### Requirement 2: PR Diff Parsing

**User Story:** As a developer, I want PR diffs parsed into a structured format, so that the Review_Engine can reference specific files and line numbers when generating findings.

#### Acceptance Criteria

1. WHEN a raw unified diff is received, THE Diff_Parser SHALL produce a structured representation containing file path, hunk headers, and per-line change type (added, removed, context).
2. THE Diff_Parser SHALL preserve the GitHub pull request line position index for each changed line, enabling accurate comment placement via the GitHub API.
3. IF a diff contains binary files, THEN THE Diff_Parser SHALL skip those files and record them in a skipped-files list.
4. IF a diff exceeds 3,000 changed lines, THEN THE Diff_Parser SHALL truncate to the first 3,000 changed lines and include a truncation notice in the structured output.
5. FOR ALL valid unified diffs, parsing the diff and re-serializing it to unified diff format SHALL produce output equivalent to the original input (round-trip property).

---

### Requirement 3: Multi-Category Review Analysis

**User Story:** As a senior engineer, I want the Review_Engine to analyze PRs across four categories, so that routine issues are caught automatically without my manual review.

#### Acceptance Criteria

1. THE Review_Engine SHALL analyze each structured diff against four Review_Categories: bugs, security, style, and performance.
2. THE Review_Engine SHALL use a separate prompt template for each Review_Category.
3. WHEN the Review_Engine processes a diff, THE Review_Engine SHALL produce zero or more Findings per Review_Category.
4. WHEN a Finding is produced, THE Review_Engine SHALL assign it exactly one Review_Category.
5. WHEN a Finding is produced, THE Review_Engine SHALL include the file path, line number, a plain-English explanation of at least one sentence, and a severity level of low, medium, or high.
6. IF the LLM provider returns an error or timeout after 30 seconds, THEN THE Review_Engine SHALL retry the request once, and IF the retry fails, THEN THE Review_Engine SHALL record the failure and skip that Review_Category for the current diff.

---

### Requirement 4: Code Suggestion Generation

**User Story:** As a junior developer, I want each finding to include a corrected code snippet, so that I understand exactly what change is recommended without guessing.

#### Acceptance Criteria

1. WHEN a Finding of severity medium or high is produced, THE Review_Engine SHALL generate a corrected code suggestion for the flagged lines.
2. THE Review_Engine SHALL format code suggestions as valid GitHub suggestion blocks, compatible with GitHub's pull request suggestion API.
3. WHEN a code suggestion is generated, THE Review_Engine SHALL include a plain-English explanation describing what was changed and why.
4. IF the Review_Engine cannot generate a syntactically valid suggestion for a Finding, THEN THE Review_Engine SHALL omit the suggestion block and retain the plain-English explanation only.

---

### Requirement 5: Posting Review Comments to GitHub

**User Story:** As a developer, I want review findings posted as inline PR comments by the bot, so that I can see feedback directly in the GitHub pull request interface.

#### Acceptance Criteria

1. WHEN the Review_Engine produces one or more Findings, THE Comment_Poster SHALL submit them as a single GitHub pull request review via the GitHub Reviews API.
2. THE Comment_Poster SHALL post each Finding as an inline comment anchored to the specific file path and line position from the Finding.
3. WHEN all Findings have severity low, THE Comment_Poster SHALL submit the review with status `COMMENT`.
4. WHEN one or more Findings have severity high, THE Comment_Poster SHALL submit the review with status `REQUEST_CHANGES`.
5. WHEN no Findings are produced for a pull request, THE Comment_Poster SHALL post a single top-level review comment stating that no issues were found, with status `APPROVE`.
6. IF the GitHub Reviews API returns a 422 error for a specific comment, THEN THE Comment_Poster SHALL skip that comment, log the invalid line reference, and continue posting remaining comments.

---

### Requirement 6: Zero False Security Positives on Agreed Test Suite

**User Story:** As a VP of Engineering, I want the PR_Reviewer to produce zero false security positives on the agreed test suite, so that developers trust the security findings and do not ignore them.

#### Acceptance Criteria

1. THE Evaluation_Harness SHALL execute the PR_Reviewer against a defined set of test PRs with known ground-truth labels.
2. WHEN the Evaluation_Harness runs, THE PR_Reviewer SHALL produce zero Findings categorized as security on test PRs that contain no security vulnerabilities.
3. THE Evaluation_Harness SHALL report precision, recall, and false positive count per Review_Category after each run.
4. WHEN the false positive count for the security Review_Category exceeds zero on the agreed test suite, THE Evaluation_Harness SHALL mark the run as failed and output the offending Findings.

---

### Requirement 7: Per-Repository Configuration

**User Story:** As a repository maintainer, I want to configure which review categories are enabled and set severity thresholds, so that the PR_Reviewer fits my team's workflow.

#### Acceptance Criteria

1. THE PR_Reviewer SHALL read a Config file from the path `.github/pr-auto-review.yml` in the target repository when processing a pull request.
2. WHERE a Config file is present, THE PR_Reviewer SHALL enable only the Review_Categories listed in the `enabled_categories` field.
3. WHERE a Config file is absent, THE PR_Reviewer SHALL enable all four Review_Categories with default severity thresholds.
4. WHERE a Config file is present, THE PR_Reviewer SHALL apply the `min_severity` field to suppress Findings below the specified severity level before posting.
5. IF the Config file contains invalid YAML or unrecognized fields, THEN THE PR_Reviewer SHALL log a warning, ignore the invalid Config, and apply default settings.

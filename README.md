# GitHub PR Auto-Review

An LLM-backed bot that automatically reviews GitHub pull requests and posts inline code comments with categorised findings — bugs, security issues, style violations, and performance problems. Includes corrected code suggestions developers can apply with one click.

---

## How it works

When a pull request is opened or updated, GitHub fires a webhook. The service validates the request, enqueues a review job, and a Celery worker runs the review pipeline: parse the diff, scrub secrets, fetch codebase context on demand, query a RAG knowledge base, and post findings as a GitHub review — all within 10 minutes.

There is **no UI and no login**. The GitHub pull request interface is the interface.

```
GitHub PR opened/updated
        │
        ▼
WebhookReceiver (FastAPI) — validates HMAC signature
        │
        ▼
Redis Job Queue
        │
        ▼
Celery Worker
  ├── Parse diff
  ├── Scrub secrets
  ├── Load repo config
  ├── Inject feedback history (few-shot)
  ├── ReviewAgent (GPT-4o) ── fetches file context, queries Knowledge Base
  └── Post findings via GitHub Reviews API
        │
        ▼
Inline comments on the PR with suggestions developers can apply
```

---

## Running locally

### Step 1 — Create a GitHub App (one-time)

The bot authenticates via a GitHub App. Create one at:
**GitHub → Settings → Developer settings → GitHub Apps → New GitHub App**

| Field | Value |
|---|---|
| GitHub App name | anything, e.g. `pr-auto-review-local` |
| Homepage URL | `http://localhost:8000` |
| Webhook URL | leave blank for now — you'll fill this in after `./launch` |
| Webhook secret | generate a random string, e.g. `openssl rand -hex 32` |
| Repository permissions | Contents: Read · Pull requests: Read & write |
| Subscribe to events | `Pull request` · `Pull request review` · `Pull request review comment` |

After creating the app:
1. Note your **App ID** (shown at the top of the app settings page)
2. Scroll to **Private keys** → **Generate a private key** → download the `.pem` file

### Step 2 — Configure `.env`

Copy `.env.example` to `.env` and fill in your values:

```bash
GITHUB_APP_ID=123456
GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n..."   # contents of the .pem file, newlines as \n
GITHUB_WEBHOOK_SECRET=your_webhook_secret                        # the secret you set in Step 1
OPENAI_API_KEY=sk-...
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/pr_reviewer
REDIS_URL=redis://localhost:6379/0
CHROMADB_URL=http://localhost:8001
LOG_LEVEL=INFO
```

### Step 3 — Launch

```bash
./launch
```

That's it. The script handles everything automatically:

1. **Kills any previous run** — cleans up stale processes from the last session so ports 8000 and 4040 are always free
2. Installs ngrok if not present
3. Starts the Podman machine
4. Starts PostgreSQL, Redis, ChromaDB, OTel Collector (with health checks)
5. Installs Python dependencies
6. Runs database migrations
7. Starts FastAPI + Celery workers
8. Opens an ngrok tunnel and prints your public webhook URL

Safe to run multiple times — each run stops the previous one cleanly before starting fresh.

At the end you'll see:

```
GitHub webhook URL : https://abc123.ngrok-free.app/webhook/github
→ Paste into: GitHub → Settings → Developer settings → GitHub Apps → Edit → Webhook URL
→ This URL changes on every restart (free ngrok). Re-paste it after each ./launch.
```

### Step 4 — Wire the webhook URL into GitHub

1. Copy the `https://…ngrok-free.app/webhook/github` URL printed by `./launch`
2. Go to: **GitHub → Settings → Developer settings → GitHub Apps → Edit**
3. Paste it into the **Webhook URL** field → **Save changes**

> **Free ngrok gives you a new URL on every restart.** Re-paste it into your GitHub App after each `./launch`. To get a stable URL, add an authtoken from [dashboard.ngrok.com](https://dashboard.ngrok.com) — free accounts get one static domain.

### Step 5 — Install the app on a repository

1. In your GitHub App settings, go to **Install App**
2. Click **Install** next to your account or organisation
3. Choose **Only select repositories** → select the repo you want reviewed
4. Click **Install**

### Step 6 — Open a pull request

Open or update a PR in the installed repository. Within 10 minutes the bot posts its review inline on the Files Changed tab.

To verify the webhook is firing: the ngrok dashboard at `http://localhost:4040` shows every request and response in real time.

---

## Using it day-to-day

Once installed, **you do nothing**. Open a PR — the bot reviews it automatically.

| What you see | Where |
|---|---|
| Inline findings with severity (low/medium/high) | GitHub PR → Files Changed tab |
| Corrected code suggestions you can apply with one click | Inline on the flagged line |
| Summary comment ("Found 3 issue(s) across 2 categories.") | PR timeline |
| Security escalations (unverified candidates) | PR timeline as ⚠️ comments |
| "No issues found." on clean PRs | PR timeline |

### Review status

| Findings | Review status |
|---|---|
| None | `COMMENT` (or `APPROVE` if `auto_approve_on_no_findings: true`) |
| Low severity only | `COMMENT` |
| Any medium, no high | `COMMENT` |
| Any high severity | `REQUEST_CHANGES` |

### Giving feedback

The bot learns from your responses:

- **Apply a suggestion** → recorded as a positive signal
- **Resolve a comment** without applying → recorded as a negative signal
- **Reply "not an issue" / "false positive" / "won't fix"** → recorded as a negative signal

These signals are injected as few-shot examples into future reviews on the same repository, improving relevance over time.

---

## Per-repository configuration

Add `.github/pr-auto-review.yml` to any repository to customise behaviour:

```yaml
enabled_categories: [bugs, security, style, performance]
min_severity: low           # suppress findings below this level (low | medium | high)
auto_approve_on_no_findings: false
tool_budget: 20             # max LLM tool calls per review job
review_draft_prs: false     # set true to review draft PRs
codebase_index_enabled: false  # v2 feature — persistent codebase memory

ignore_patterns_extend:     # add to default ignore list
  - "vendor/**"
  - "*.generated.ts"

ignore_patterns_override:   # fully replace the default ignore list
  - "vendor/**"

knowledge_base:
  coding_guidelines: true
  language_best_practices: true
  cve_snapshot: true
  fix_knowledge_base: true
  lessons_learned: true
  live_cve_lookup: true
  live_package_advisory: true
```

The default ignore list covers: `package-lock.json`, `yarn.lock`, `*.lock`, `vendor/**`, `generated/**`, `*.pb.go`, `*.min.js`, `*.min.css`.

---

## Operations

### Health check

```bash
curl http://localhost:8000/health
# {"status": "ok", "db": "ok", "redis": "ok", "chromadb": "ok"}
```

### Running the evaluation harness

The evaluation harness is a standalone tool in `eval/` that measures finding quality against a labelled test corpus. It has no runtime dependency on the live service — it reads stored `Finding` records directly from PostgreSQL.

**Prerequisites**

```bash
# Install Inspect AI (the eval runner)
pip install inspect-ai

# The app must have processed at least some PRs so findings are in the database,
# OR you seed the corpus manually (see eval/README.md once implemented)
```

**When to run it**

| Trigger | Command | Gate |
|---|---|---|
| Before any prompt change or model update | Full corpus run | Must pass zero security false-positives or the change does not ship |
| Weekly | Sample run on 10 live reviews | Human vibe-check (1–5) logged alongside judge scores |

**Full corpus run** — use before shipping any change:

```bash
inspect eval eval/tasks/
```

**Weekly sample run** — 10 live reviews, lighter and faster:

```bash
inspect eval eval/tasks/ --limit 10
```

**Browse results** — per-sample traces, judge rationales, and aggregate metrics:

```bash
inspect view
```

**What the report includes**

- Precision, recall, and false positive count per category (bugs, security, style, performance)
- Per-finding scores as a vector: relevance · accuracy · actionability · clarity
- Average cost and latency per review
- Tool_Budget consumption distribution
- Delta vs the previous run
- Knowledge base retrieval quality (flags security findings with no KB retrieval)

**Meta-prompting loop** — when quality is low, run the improvement loop to get a revised system prompt:

```bash
inspect eval eval/tasks/ --task meta-prompt-loop
```

This identifies the 5 lowest-scoring reviews, submits them to a reflector LLM, produces a revised prompt, re-runs, and reports the score delta before you decide whether to deploy the change.

### Knowledge base management

```bash
# Add a human-authored lessons-learned entry
kb add --corpus lessons_learned \
  --problem "..." \
  --pattern "..." \
  --root-cause "..." \
  --resolution "..."

# Roll back a corpus to a previous version
kb rollback --corpus cve_snapshot --version 3

# List active corpus versions
kb list-versions
```

---

## Complementary to Claude Code

Claude Code already gives individual developers powerful AI assistance during coding — including the `/ultrareview` command and the `code-reviewer` agent invoked during a session. This service is not a replacement for that. It operates at a different layer: the **team gate**, not the individual session.

| | Claude Code (`/ultrareview`, `@code-reviewer`) | PR Auto-Review (this service) |
|---|---|---|
| **When it runs** | When the developer explicitly invokes it | Automatically on every PR, no action required |
| **Who triggers it** | The developer writing the code | GitHub webhook — fires for the whole team |
| **Coverage** | PRs the developer remembers to review | Every PR, every team member, every repo |
| **Knowledge** | LLM training data + current context window | Org-specific RAG knowledge base, CVE snapshots, repo fix history |
| **Learns over time** | No — each session starts fresh | Yes — feedback loop improves findings per repo |
| **Security specialisation** | General | Live CVE/OSV lookups, zero-FP gate enforced by eval harness |
| **Audit trail** | Session output | All findings stored in PostgreSQL with history |
| **GitHub-native output** | Reported in terminal / Claude Code UI | Posted as native GitHub review with one-click apply suggestions |

### The practical workflow

A developer using Claude Code gets a first-pass review during coding — catching the obvious issues before they commit. By the time the PR is opened, the low-hanging fruit is already gone. This service then applies a second, independent pass at the PR stage:

1. **Developer opens a PR** — after already using Claude Code during coding
2. **PR Auto-Review fires automatically** — reviews the final diff with org-specific guidelines and CVE context the developer's Claude Code session didn't have
3. **Findings appear as GitHub inline comments** — visible to the whole team, not just the author
4. **Team members reviewing the PR** see the bot findings alongside their own review — surfaces issues they might have missed, lets them focus on architecture and intent rather than mechanical checks
5. **Accepted suggestions feed back** into the knowledge base — the bot gets better at catching the same class of issue in future PRs across the team

### When this adds the most value

- **Teams where not everyone uses Claude Code** — the bot gives consistent review coverage regardless of individual tooling choices
- **Security-sensitive codebases** — the zero-FP gate and live CVE lookup go beyond what a general-purpose code review session provides
- **High PR volume** — senior engineers stop being the bottleneck for routine first-pass review
- **Onboarding junior developers** — every PR gets a review even when senior bandwidth is low
- **Regulated environments** — the audit trail (findings stored in PostgreSQL, evaluation harness metrics) satisfies documentation requirements that ad-hoc session reviews cannot

---

## Architecture

The service is a single FastAPI application with Celery workers. See [`.kiro/specs/github-pr-auto-review/design.md`](.kiro/specs/github-pr-auto-review/design.md) for the full architecture, data models, and sequence diagrams.

**Stack:** Python 3.12 · FastAPI · Celery · Redis · PostgreSQL · ChromaDB · LangChain · OpenAI GPT-4o · OpenTelemetry

**v1** delivers the complete review pipeline with knowledge base, feedback loop, and evaluation harness.

**v2** (deferred until v1 feedback data accumulates) adds persistent codebase memory (`CodebaseIndex`), expanded MCP server ecosystem (Snyk, OWASP, linter integration, license checker), and cross-repository learning.

---

## Development

```bash
# Full local stack with public tunnel — safe to run multiple times
./launch

# Backing services only (no app, no tunnel) — useful when iterating on code
./launch --services-only

# Skip migrations on fast restarts
./launch --no-migrate

# Skip ngrok (if you have a stable public URL already)
./launch --no-tunnel
```

Each run automatically kills the previous session (app processes, ngrok) before starting fresh — no manual cleanup needed. Logs are written to `logs/` — `api.log`, `worker-review.log`, `worker-feedback.log`, `ngrok.log`.

```bash
# Run tests
make test

# Run linter
make lint
```

### Project layout

```
pr_reviewer/
├── api/          # FastAPI routes (webhook receiver, health)
├── workers/      # Celery tasks (job processor, feedback processor)
├── agents/       # ReviewAgent, ToolBudgetMiddleware
├── components/   # DiffParser, SecretScrubber, CommentPoster
├── config/       # ConfigLoader
├── kb/           # KnowledgeBase, MCPClient
├── store/        # GitHubAPIClient, FeedbackStore
└── models/       # Frozen dataclasses, enums
eval/             # Evaluation harness (Inspect AI tasks, LiteLLM judges)
tests/
├── unit/
├── integration/
└── e2e/
```

---

## Spec

Full specification in [`.kiro/specs/github-pr-auto-review/`](.kiro/specs/github-pr-auto-review/):

- [`requirements.md`](.kiro/specs/github-pr-auto-review/requirements.md) — user stories and EARS acceptance criteria (v1)
- [`requirements-v2.md`](.kiro/specs/github-pr-auto-review/requirements-v2.md) — v2 acceptance criteria
- [`design.md`](.kiro/specs/github-pr-auto-review/design.md) — architecture, data models, sequence diagrams
- [`tasks.md`](.kiro/specs/github-pr-auto-review/tasks.md) — implementation task list

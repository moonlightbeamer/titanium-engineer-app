# GitHub PR Auto-Review

An LLM-backed bot that automatically reviews GitHub pull requests and posts inline code comments with categorised findings — bugs, security issues, style violations, and performance problems. Includes corrected code suggestions developers can apply with one click.

## Installing the bot on your repository

The bot is already deployed and running at:

```
https://ca-pr-reviewer-api.blackmoss-99d6e960.eastus.azurecontainerapps.io
```

To add it to a repository:

1. Go to the GitHub App page: **[https://github.com/apps/pr-review-titanium-engineer](https://github.com/apps/pr-review-titanium-engineer)**
2. Click **Install** → select the account or organisation → choose **Only select repositories** → pick the repo → **Install**
3. Open a pull request — the bot reviews it automatically within 10 minutes.

That's all. No deployment, no secrets, no configuration required.

> **Optional per-repo config:** Add `.github/pr-auto-review.yml` to customise which categories are enabled, minimum severity, draft PR handling, and more. See [Per-repository configuration](#per-repository-configuration) below.

---

## Deployment modes

| Mode | Command | When to use |
|---|---|---|
| **Local** | `./launch` | Development, testing — everything runs on your machine via docker-compose; cloudflared tunnels GitHub webhooks to localhost |
| **Azure** | `./infra/scripts/deploy.sh` | Self-hosting — Azure Container Apps, managed PostgreSQL, Redis, and ChromaDB; stable webhook URL; no cloudflared needed |

The two modes are independent and use the same codebase.

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

## Running locally (development)

### Step 1 — Create a GitHub App (one-time)

The bot authenticates via a GitHub App. Create one at:
**GitHub → Settings → Developer settings → GitHub Apps → New GitHub App**

First, generate a webhook secret you'll use in the form:

```bash
openssl rand -hex 32
```

Copy the output — you'll need it in the form and again in `.env`.

| Field | Value |
|---|---|
| GitHub App name | anything, e.g. `pr-auto-review-local` |
| Homepage URL | `http://localhost:8000` |
| Webhook URL | leave blank for now — you'll fill this in after `./launch` |
| Webhook secret | paste the hex string you just generated |
| Repository permissions | Contents: Read · Pull requests: Read & write |
| Subscribe to events | `Pull request` · `Pull request review` · `Pull request review comment` · `Push` |

After creating the app:
1. Note your **App ID** (shown at the top of the app settings page)
2. Scroll to **Private keys** → **Generate a private key** → download the `.pem` file

### Step 2 — Configure `.env`

A `.env` file is already provided in the repo with the structure ready to fill in. Open it and complete the five blank fields:

| Variable | Where to find it |
|---|---|
| `GITHUB_APP_ID` | GitHub → Settings → Developer settings → GitHub Apps → your app (shown at top of page) |
| `GITHUB_APP_PRIVATE_KEY` | See below |
| `GITHUB_WEBHOOK_SECRET` | The hex string you generated in Step 1 |
| `AZURE_OPENAI_ENDPOINT` | Azure Portal → your Azure OpenAI resource → *Keys and Endpoint* |
| `AZURE_ANTHROPIC_ENDPOINT` | [Azure AI Foundry](https://ai.azure.com) → your project → *Overview* |

**Converting the private key** — the `.pem` file must become a single-line value with literal `\n` between each line. Run this command (adjust the filename to match your download):

```bash
awk 'NF {printf "%s\\n", $0}' ~/Downloads/your-app.private-key.pem
```

Copy the entire output and paste it as the value for `GITHUB_APP_PRIVATE_KEY` in `.env`, keeping the surrounding double quotes. The result must be on one line:

```
GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\nMIIEow...fxdfn/T\n-----END RSA PRIVATE KEY-----\n"
```

The API keys (`AZURE_OPENAI_API_KEY`, `AZURE_ANTHROPIC_API_KEY`) and backing service URLs (`DATABASE_URL`, `REDIS_URL`, `CHROMADB_URL`) are already populated. The deployment name defaults to `gpt-4o` — change it if your Azure deployment uses a different name.

> The `.env` file is git-ignored and never committed. Do not share it or check it in.

### Step 3 — Launch

```bash
./launch
```

That's it. The script handles everything automatically:

1. **Kills any previous run** — cleans up stale processes from the last session so port 8000 is always free
2. Installs cloudflared if not present
3. Starts the Podman machine
4. Starts PostgreSQL, Redis, ChromaDB, OTel Collector (with health checks)
5. Installs Python dependencies
6. Runs database migrations
7. Starts FastAPI + Celery workers
8. Opens a cloudflared tunnel and prints your public webhook URL

Safe to run multiple times — each run stops the previous one cleanly before starting fresh.

At the end you'll see:

```
GitHub webhook URL : https://abc123.trycloudflare.com/webhook/github
→ Paste into: GitHub → Settings → Developer settings → GitHub Apps → Edit → Webhook URL
→ This URL changes on every restart. Re-paste it after each ./launch.
```

### Step 4 — Wire the webhook URL into GitHub

1. Copy the `https://….trycloudflare.com/webhook/github` URL printed by `./launch`
2. Go to: **GitHub → Settings → Developer settings → GitHub Apps → Edit**
3. Paste it into the **Webhook URL** field → **Save changes**

> **cloudflared gives you a new URL on every restart.** Re-paste it into your GitHub App after each `./launch`.

### Step 5 — Install the app on a repository

1. In your GitHub App settings, go to **Install App**
2. Click **Install** next to your account or organisation
3. Choose **Only select repositories** → select the repo you want reviewed
4. Click **Install**

### Step 6 — Open a pull request

Open or update a PR in the installed repository. Within 10 minutes the bot posts its review inline on the Files Changed tab.

To verify the webhook is firing: check `logs/cloudflared.log` or watch `logs/api.log` for incoming requests.

---

## Deploying to Azure (self-hosting)

Follow this section only if you want to run your own instance. The bot is already deployed and available — most users should just [install the GitHub App](#installing-the-bot-on-your-repository) instead.

The Azure deployment targets **Azure Container Apps** with managed PostgreSQL, Redis, and ChromaDB, all provisioned by Terraform.

### Prerequisites

| Tool | Install |
|---|---|
| Azure CLI | `brew install azure-cli` then `az login` |
| Terraform ≥ 1.7 | `brew install terraform` |
| Podman | `brew install podman` then `podman machine init && podman machine start` |

### Step 1 — Create a GitHub App (one-time)

Follow the same GitHub App setup as the local instructions above, with these differences:

| Field | Value |
|---|---|
| GitHub App name | anything, e.g. `pr-reviewer-myorg` |
| Homepage URL | `https://<your-api-fqdn>` (fill in after first deploy) |
| Webhook URL | leave blank — fill in after first deploy |
| Where can this GitHub App be installed? | **Any account** (to allow other users to install it) |

After creating the app, note the **App ID** and generate + download a **private key**.

### Step 2 — Bootstrap Terraform state storage (one-time)

Creates the Azure Storage account that holds Terraform state. Run once per environment.

```bash
az login
./infra/scripts/bootstrap-state.sh
```

### Step 3 — Populate secrets

Fill in `infra/scripts/set-secrets.sh` (gitignored) with your GitHub App credentials, Azure OpenAI keys, and database password.

```bash
# Open the file and fill in all values before deploying
open infra/scripts/set-secrets.sh
```

### Step 4 — Deploy

```bash
podman machine start
./infra/scripts/deploy.sh
```

The script builds the Docker image, pushes it to ACR, runs `terraform plan`, and applies. The image tag defaults to the current git short SHA.

First deploy takes ~10 minutes (PostgreSQL and Redis provisioning). Subsequent deploys take under 2 minutes.

At the end you'll see:

```
============================================
 Deployment complete
 Image:  ttmt03c83eacr.azurecr.io/pr-reviewer:<sha>
 API:    https://ca-pr-reviewer-api.<...>.azurecontainerapps.io
 Webhook URL (set in GitHub App): https://ca-pr-reviewer-api.<...>.azurecontainerapps.io/webhook/github

 To seed the knowledge base:
   az containerapp job start --name job-pr-reviewer-kb-seed --resource-group titanium-team-03-rg
============================================
```

#### Deploy options

```bash
./infra/scripts/deploy.sh                  # build + apply (tag = git SHA)
./infra/scripts/deploy.sh --tag v1.2.3     # explicit image tag
./infra/scripts/deploy.sh --skip-build     # infra-only change, re-use current image
./infra/scripts/deploy.sh --seed           # build + apply + trigger KB seed job
./infra/scripts/deploy.sh --plan-only      # show terraform plan without applying
```

### Step 5 — Seed ChromaDB (first deploy only)

ChromaDB starts empty. Run the seed job to populate the CVE snapshot and all KB corpora:

```bash
az containerapp job start --name job-pr-reviewer-kb-seed --resource-group titanium-team-03-rg
```

Or pass `--seed` to the deploy command to do it automatically. Monitor progress:

```bash
az containerapp job execution list --name job-pr-reviewer-kb-seed --resource-group titanium-team-03-rg -o table
```

Re-run any time to refresh the CVE snapshot.

### Step 6 — Wire the webhook URL into your GitHub App

1. Copy the webhook URL printed at the end of the deploy script
2. Go to: **GitHub → Settings → Developer settings → GitHub Apps → your app → Edit**
3. Set **Webhook URL** to the printed URL → **Save changes**

This URL is **permanent** — it does not change on redeploy or restart, unlike the cloudflared local URL.

### Step 7 — Install the app on repositories

Go to your GitHub App settings → **Install App** → select account/org → choose repositories → **Install**.

To allow anyone to install it: in the GitHub App settings under **Advanced**, set **Where can this GitHub App be installed?** to **Any account** and save. Users can then install via `https://github.com/apps/<your-app-slug>`.

### Re-deploying after a code change

```bash
./infra/scripts/deploy.sh                  # rebuilds image + applies infra
./infra/scripts/deploy.sh --skip-build     # infra-only change, re-uses current image
```

No webhook URL changes, no GitHub App changes, no service interruption beyond a rolling container restart.

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
codebase_index_enabled: false  # persistent codebase memory (v2)
index_max_tokens: 8000      # token budget for injected codebase context
cross_repo_sharing: false   # contribute positive findings to cross-repo corpus (v2)
max_linter_files: 5         # max files passed to linter per review

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

**Local:**
```bash
curl http://localhost:8000/health
# {"status": "ok", "db": "ok", "redis": "ok", "chromadb": "ok"}
```

**Azure:**
```bash
curl https://ca-pr-reviewer-api.blackmoss-99d6e960.eastus.azurecontainerapps.io/health
```

### Viewing logs (Azure)

```bash
# API
az containerapp logs show --name ca-pr-reviewer-api --resource-group titanium-team-03-rg --follow

# Review worker
az containerapp logs show --name ca-pr-reviewer-worker-review --resource-group titanium-team-03-rg --follow
```

### Refreshing the CVE snapshot (Azure)

```bash
az containerapp job start --name job-pr-reviewer-kb-seed --resource-group titanium-team-03-rg
```

### Running the evaluation harness

The evaluation harness is a standalone tool in `eval/` that measures finding quality against a labelled test corpus. It has no runtime dependency on the live service — it reads stored `Finding` records directly from PostgreSQL.

**Prerequisites**

Everything the eval harness needs is installed automatically when you run `uv sync` inside the `eval/` directory — `inspect-ai`, `litellm`, and their dependencies are declared in `eval/pyproject.toml` (created in task 18). No separate manual installs needed.

```bash
cd eval && uv sync
```

One thing you do need to obtain separately: **a Claude endpoint via Azure AI Foundry**. The bias-detection judge must use a different model family than GPT-4o to avoid same-family scoring bias. Add it to your `.env`:

```bash
AZURE_ANTHROPIC_API_KEY=your_azure_anthropic_key
AZURE_ANTHROPIC_ENDPOINT=https://your-resource.services.ai.azure.com
```

The database must also be running — `./launch --services-only` is enough (no full app needed):

```bash
./launch --services-only   # starts PostgreSQL; eval harness reads findings from it
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
- Tool budget consumption distribution (`kb_calls` vs `codebase_calls`)
- Delta vs the previous run
- Knowledge base retrieval quality — mean relevance score per corpus; corpora sustaining <0.6 mean relevance for 3 consecutive runs are flagged automatically
- Index contribution delta — precision/recall shift with `CodebaseIndex` on vs off

**Meta-prompting loop** — when quality is low, run the improvement loop to get a revised system prompt:

```bash
inspect eval eval/tasks/ --task meta-prompt-loop
```

This identifies the 5 lowest-scoring reviews, submits them to a reflector LLM, produces a revised prompt, re-runs, and reports the score delta before you decide whether to deploy the change.

### Knowledge base management

```bash
# Seed the KB with minimal starter data
kb bootstrap

# Add a human-authored lessons-learned entry (draft — requires approval)
kb add --corpus lessons_learned --draft \
  '{"problem_description": "...", "resolution": "...", "category": "security"}'

# Review and approve the draft
kb list --status draft
kb approve <entry-id>

# Deprecate an outdated entry (row kept, excluded from queries)
kb deprecate <entry-id>

# Roll back a corpus to a previous version
kb rollback --corpus cve_snapshot --version 3

# Re-embed all active entries after an embedding model upgrade
kb reembed --corpus all
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

**Stack:** Python 3.12 · FastAPI · Celery · Redis · PostgreSQL · ChromaDB · LangChain · Azure OpenAI GPT-4o · Azure AI Foundry (Claude, eval judge) · OpenTelemetry

**Azure infrastructure:** Azure Container Apps · Azure Database for PostgreSQL Flexible Server · Azure Cache for Redis · Azure Container Registry · Azure Files (ChromaDB persistence + OTel config) · Terraform · Podman (image build)

**v1** delivers the complete review pipeline: webhook receiver, LangChain ReviewAgent, RAG knowledge base, feedback loop, and evaluation harness.

**v2** adds persistent codebase memory (`CodebaseIndex` built nightly by the `Indexer`), expanded MCP ecosystem (GHSA, Snyk, OWASP, linter, license checker), and cross-repository learning (opt-in via `cross_repo_sharing`). Both layers are fully implemented and gated by config flags — v2 features are off by default until codebase indexes have been populated.

---

## Development

```bash
# Full local stack with public tunnel — safe to run multiple times
./launch

# Backing services only (no app, no tunnel) — useful when iterating on code
./launch --services-only

# Skip migrations on fast restarts
./launch --no-migrate

# Skip cloudflared (if you have a stable public URL already)
./launch --no-tunnel
```

Each run automatically kills the previous session (app processes, cloudflared) before starting fresh — no manual cleanup needed. Logs are written to `logs/` — `api.log`, `worker-review.log`, `worker-feedback.log`, `worker-indexer.log`, `beat.log`, `cloudflared.log`.

```bash
# Run tests
make test

# Run linter
make lint
```

### Project layout

```
pr_reviewer/
├── api/          # FastAPI routes (webhook receiver, health check)
├── workers/      # Celery tasks (job processor, feedback processor, indexer)
├── agents/       # ReviewAgent, ToolBudgetMiddleware, linter/license tools
├── components/   # DiffParser, SecretScrubber, CommentPoster
├── config/       # ConfigLoader, Config schema
├── kb/           # KnowledgeBase, MCPClient, CLI, cross-repo corpus
├── store/        # GitHubAPIClient, FeedbackStore
└── models/       # Frozen dataclasses, enums (Job, Finding, CodebaseIndex, …)
eval/             # Evaluation harness (Inspect AI tasks, LiteLLM judges)
├── judges/       # 6 judge files (relevance, accuracy, actionability, clarity, …)
├── tasks/        # pre_ship, weekly_vibe, meta_prompt, ablation, index_contribution
└── …             # corpus loader, retrieval quality, budget attribution, corpus health
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

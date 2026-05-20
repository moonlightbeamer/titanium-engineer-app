#!/bin/bash
# Full deployment: build image → push to ACR → terraform apply.
#
# Usage:
#   ./infra/scripts/deploy.sh                  # build + apply, tag = git short SHA
#   ./infra/scripts/deploy.sh --tag v1.2.3     # explicit tag
#   ./infra/scripts/deploy.sh --skip-build     # re-deploy current image (infra changes only)
#   ./infra/scripts/deploy.sh --seed           # also trigger KB seed job after apply
#   ./infra/scripts/deploy.sh --plan-only      # terraform plan without applying
#
# Prerequisites:
#   az CLI logged in, podman installed, terraform >= 1.7 installed,
#   infra/scripts/set-secrets.sh populated.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TF_DIR="$REPO_ROOT/infra/terraform"
SECRETS_FILE="$SCRIPT_DIR/set-secrets.sh"

TAG=""
SKIP_BUILD=false
SEED=false
PLAN_ONLY=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag)        TAG="$2"; shift 2 ;;
    --skip-build) SKIP_BUILD=true; shift ;;
    --seed)       SEED=true; shift ;;
    --plan-only)  PLAN_ONLY=true; shift ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# Default tag: git short SHA for traceability
if [[ -z "$TAG" ]]; then
  TAG=$(git -C "$REPO_ROOT" rev-parse --short HEAD)
fi

echo "============================================"
echo " PR Reviewer Deployment"
echo " Tag:        $TAG"
echo " Skip build: $SKIP_BUILD"
echo " Plan only:  $PLAN_ONLY"
echo "============================================"

# ── 1. Load secrets ──────────────────────────────────────────────────────────
if [[ ! -f "$SECRETS_FILE" ]]; then
  echo ""
  echo "ERROR: $SECRETS_FILE not found."
  echo "       Create it from the example and populate with real values."
  exit 1
fi
echo ""
echo "--- Loading secrets ---"
# shellcheck source=set-secrets.sh
source "$SECRETS_FILE"

# ── 2. Build and push image ──────────────────────────────────────────────────
if [[ "$SKIP_BUILD" == "false" ]]; then
  echo ""
  echo "--- Building and pushing image ($TAG) ---"
  "$SCRIPT_DIR/build-push.sh" "$TAG"
fi

# ── 3. Terraform init ────────────────────────────────────────────────────────
echo ""
echo "--- Terraform init ---"
cd "$TF_DIR"
terraform init -reconfigure -input=false

# ── 4. Plan (always shown) ───────────────────────────────────────────────────
echo ""
echo "--- Terraform plan ---"
terraform plan -out=tfplan -input=false -var="image_tag=$TAG"

if [[ "$PLAN_ONLY" == "true" ]]; then
  echo ""
  echo "Plan-only mode — apply skipped."
  exit 0
fi

# ── 5. Apply ─────────────────────────────────────────────────────────────────
echo ""
echo "--- Terraform apply ---"
terraform apply -input=false tfplan

# ── 6. Optional KB seed ──────────────────────────────────────────────────────
SEED_CMD=$(terraform output -raw kb_seed_job_trigger)

if [[ "$SEED" == "true" ]]; then
  echo ""
  echo "--- Seeding knowledge base ---"
  eval "$SEED_CMD"
fi

# ── 7. Summary ───────────────────────────────────────────────────────────────
API_URL="https://$(terraform output -raw api_fqdn_raw)"
echo ""
echo "============================================"
echo " Deployment complete"
echo " Image:  $(terraform output -raw acr_login_server)/pr-reviewer:$TAG"
echo " API:    $API_URL"
echo " Webhook URL (set in GitHub App): $API_URL/webhook/github"
echo ""
echo " To seed the knowledge base:"
echo "   $SEED_CMD"
echo "============================================"

#!/bin/bash
# Build the Docker image for linux/amd64 using Podman and push to ACR.
# Usage: ./infra/scripts/build-push.sh [IMAGE_TAG]
set -euo pipefail

ACR="ttmt03c83eacr"
IMAGE="pr-reviewer"
TAG="${1:-latest}"
FULL_IMAGE="${ACR}.azurecr.io/${IMAGE}:${TAG}"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

echo "Logging into ACR..."
# az acr login doesn't support Podman directly — use expose-token instead
TOKEN=$(az acr login --name "$ACR" --expose-token --output tsv --query accessToken)
podman login "${ACR}.azurecr.io" \
  --username "00000000-0000-0000-0000-000000000000" \
  --password "$TOKEN"

echo "Building $FULL_IMAGE for linux/amd64..."
podman build \
  --platform linux/amd64 \
  --tag "$FULL_IMAGE" \
  "$REPO_ROOT"

echo "Pushing $FULL_IMAGE..."
podman push "$FULL_IMAGE"

echo "Done: $FULL_IMAGE"

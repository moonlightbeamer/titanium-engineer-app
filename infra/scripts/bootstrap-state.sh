#!/bin/bash
# Creates the Azure Storage account used by the Terraform azurerm backend.
# Run this ONCE before the first `terraform init`.
set -euo pipefail

RG="titanium-team-03-rg"
ACCOUNT="sttfstateprreviewer"
CONTAINER="tfstate"

echo "Creating Terraform state storage account: $ACCOUNT"
az storage account create \
  --name "$ACCOUNT" \
  --resource-group "$RG" \
  --sku Standard_LRS \
  --min-tls-version TLS1_2 \
  --allow-blob-public-access false

az storage container create \
  --name "$CONTAINER" \
  --account-name "$ACCOUNT" \
  --auth-mode login

echo "Done. Backend storage: $ACCOUNT/$CONTAINER"
echo "Now run: cd infra/terraform && terraform init"

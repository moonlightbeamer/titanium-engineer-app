#!/bin/bash
# Creates the Azure Storage account used by the Terraform azurerm backend.
# Run this ONCE before the first `terraform init`.
set -euo pipefail

RG="titanium-team-03-rg"
ACCOUNT="sttfstateprreviewer"
CONTAINER="tfstate"

MY_IP=$(curl -sf https://api.ipify.org)
echo "Your public IP: $MY_IP"

echo "Creating Terraform state storage account: $ACCOUNT"
az storage account create \
  --name "$ACCOUNT" \
  --resource-group "$RG" \
  --sku Standard_LRS \
  --min-tls-version TLS1_2 \
  --allow-blob-public-access false \
  --default-action Deny

echo "Adding IP $MY_IP to storage account firewall..."
az storage account network-rule add \
  --account-name "$ACCOUNT" \
  --resource-group "$RG" \
  --ip-address "$MY_IP"

az storage container create \
  --name "$CONTAINER" \
  --account-name "$ACCOUNT" \
  --auth-mode login

echo "Done. Backend storage: $ACCOUNT/$CONTAINER"
echo "NOTE: Only IP $MY_IP is whitelisted. Re-run network-rule add if deploying from a different machine."
echo "Now run: cd infra/terraform && terraform init"

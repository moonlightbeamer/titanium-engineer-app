terraform {
  required_version = ">= 1.7"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.100"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Remote backend temporarily disabled — network policy on Titanium Engineering subscription
  # blocks data-plane access to sttfstateprreviewer. Using local state until resolved.
  # To migrate back: restore the azurerm block and run: terraform init -migrate-state
  # backend "azurerm" {
  #   resource_group_name  = "titanium-team-03-rg"
  #   storage_account_name = "sttfstateprreviewer"
  #   container_name       = "tfstate"
  #   key                  = "pr-reviewer.tfstate"
  # }

  backend "local" {}
}

provider "azurerm" {
  features {}
  skip_provider_registration = true
}

data "azurerm_resource_group" "main" {
  name = var.resource_group_name
}

data "azurerm_container_registry" "acr" {
  name                = var.acr_name
  resource_group_name = var.acr_resource_group
}

# Managed identity for ACA → ACR pull (avoids storing ACR admin credentials)
resource "azurerm_user_assigned_identity" "acr_pull" {
  name                = "id-${local.prefix}-acr-pull"
  resource_group_name = data.azurerm_resource_group.main.name
  location            = data.azurerm_resource_group.main.location
}


resource "azurerm_log_analytics_workspace" "main" {
  name                = "log-${local.prefix}"
  resource_group_name = data.azurerm_resource_group.main.name
  location            = data.azurerm_resource_group.main.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

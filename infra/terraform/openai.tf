# ── Azure OpenAI ──────────────────────────────────────────────────────────────
# Imported from: az cognitiveservices account show --name oai-pr-reviewer
# Public network access is disabled — all traffic routes through the private
# endpoint in snet-private-endpoints. See vnet.tf for the endpoint definition.

resource "azurerm_cognitive_account" "openai" {
  name                = "oai-pr-reviewer-v2"
  resource_group_name = data.azurerm_resource_group.main.name
  location            = local.location
  kind                = "OpenAI"
  sku_name            = "S0"

  custom_subdomain_name         = "pr-reviewer-oai"
  public_network_access_enabled = false

  network_acls {
    default_action = "Deny"
    ip_rules       = []
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_cognitive_deployment" "gpt4o" {
  name                 = "gpt-4o"
  cognitive_account_id = azurerm_cognitive_account.openai.id
  rai_policy_name      = "Microsoft.DefaultV2"

  model {
    format  = "OpenAI"
    name    = "gpt-4o"
    version = "2024-11-20"
  }

  scale {
    type     = "Standard"
    capacity = 30
  }
}

resource "azurerm_cognitive_deployment" "embedding" {
  name                 = "text-embedding-3-large"
  cognitive_account_id = azurerm_cognitive_account.openai.id
  rai_policy_name      = "Microsoft.DefaultV2"

  model {
    format  = "OpenAI"
    name    = "text-embedding-3-large"
    version = "1"
  }

  scale {
    type     = "Standard"
    capacity = 120
  }
}

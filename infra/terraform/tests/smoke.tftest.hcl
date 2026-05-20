# Smoke test: full plan with mocked Azure providers.
# Run with: terraform test -filter=smoke
# Requires terraform >= 1.7 for mock_provider support.

mock_provider "azurerm" {
  mock_data "azurerm_resource_group" {
    defaults = {
      id       = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/titanium-team-03-rg"
      location = "westus2"
      name     = "titanium-team-03-rg"
    }
  }
  mock_data "azurerm_container_registry" {
    defaults = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/titanium-team-03-rg/providers/Microsoft.ContainerRegistry/registries/ttmt03c83eacr"
      login_server = "ttmt03c83eacr.azurecr.io"
      name         = "ttmt03c83eacr"
    }
  }
}

mock_provider "random" {}

variables {
  db_admin_password      = "TestP@ss007!"
  github_app_id          = "12345"
  github_app_private_key = "-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----"
  github_webhook_secret  = "test-webhook-secret"
  azure_openai_api_key   = "test-openai-key"
  azure_openai_endpoint  = "https://test.openai.azure.com"
}

run "plan_completes" {
  command = plan
}

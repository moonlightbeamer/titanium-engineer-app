# Tests for locally-computable values in locals.tf.
# Only variable-derived locals are asserted here — values that depend on
# resource outputs (chromadb_url, otel_endpoint) are known only after apply.

mock_provider "azurerm" {
  mock_data "azurerm_resource_group" {
    defaults = {
      id       = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-rg"
      location = "eastus"
    }
  }
  mock_data "azurerm_container_registry" {
    defaults = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-rg/providers/Microsoft.ContainerRegistry/registries/myacr"
      login_server = "myacr.azurecr.io"
    }
  }
}

mock_provider "random" {}

variables {
  acr_name               = "myacr"
  image_tag              = "v1.2.3"
  db_admin_password      = "TestP@ss007!"
  github_app_id          = "99999"
  github_app_private_key = "-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----"
  github_webhook_secret  = "secret"
  azure_openai_api_key   = "key"
  azure_openai_endpoint  = "https://test.openai.azure.com"
}

run "prefix_is_constant" {
  command = plan

  assert {
    condition     = local.prefix == "pr-reviewer"
    error_message = "prefix must always be 'pr-reviewer', got '${local.prefix}'"
  }
}

run "image_ref_combines_acr_prefix_and_tag" {
  command = plan

  assert {
    condition     = local.image_ref == "myacr.azurecr.io/pr-reviewer:v1.2.3"
    error_message = "image_ref must be '<acr>.azurecr.io/pr-reviewer:<tag>', got '${local.image_ref}'"
  }
}

run "db_name_is_pr_reviewer" {
  command = plan

  assert {
    condition     = local.db_name == "pr_reviewer"
    error_message = "db_name must be 'pr_reviewer', got '${local.db_name}'"
  }
}

run "db_user_matches_variable" {
  command = plan

  assert {
    condition     = local.db_user == "pradmin"
    error_message = "db_user must reflect var.db_admin_user default 'pradmin', got '${local.db_user}'"
  }
}

# Variable validation tests.
# Each expect_failures run confirms that an invalid value is rejected by the
# validation block on the variable before any plan is produced.

mock_provider "azurerm" {
  mock_data "azurerm_resource_group" {
    defaults = {
      id       = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-rg"
      location = "eastus"
    }
  }
  mock_data "azurerm_container_registry" {
    defaults = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-rg/providers/Microsoft.ContainerRegistry/registries/testacr"
      login_server = "testacr.azurecr.io"
    }
  }
}

mock_provider "random" {}

variables {
  db_admin_password      = "TestP@ss007!"
  github_app_id          = "12345"
  github_app_private_key = "-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----"
  github_webhook_secret  = "secret"
  azure_openai_api_key   = "key"
  azure_openai_endpoint  = "https://test.openai.azure.com"
}

run "rejects_empty_image_tag" {
  command = plan

  variables {
    image_tag = ""
  }

  expect_failures = [var.image_tag]
}

run "accepts_semver_image_tag" {
  command = plan

  variables {
    image_tag = "v1.0.0"
  }
}

run "accepts_latest_image_tag" {
  command = plan

  variables {
    image_tag = "latest"
  }
}

run "rejects_http_openai_endpoint" {
  command = plan

  variables {
    azure_openai_endpoint = "http://insecure.openai.azure.com"
  }

  expect_failures = [var.azure_openai_endpoint]
}

run "accepts_https_openai_endpoint" {
  command = plan

  variables {
    azure_openai_endpoint = "https://myresource.openai.azure.com"
  }
}

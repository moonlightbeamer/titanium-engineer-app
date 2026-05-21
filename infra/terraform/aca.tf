# ── OTel Collector (internal only, config mounted from Azure Files) ───────────

resource "azurerm_container_app" "otel_collector" {
  name                         = "otel-collector"
  resource_group_name          = data.azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"

  # Config is passed as an env var to avoid the azurerm v3 data-plane restriction
  # on Azure Files. The collector reads it via --config=env:OTEL_COLLECTOR_CONFIG_YAML.
  secret {
    name  = "otel-config-yaml"
    value = file("${path.module}/../../otel/collector-config.yml")
  }

  template {
    min_replicas = 1
    max_replicas = 1

    container {
      name   = "otel-collector"
      image  = "otel/opentelemetry-collector-contrib:latest"
      cpu    = 0.25
      memory = "0.5Gi"
      args   = ["--config=env:OTEL_COLLECTOR_CONFIG_YAML"]

      env {
        name        = "OTEL_COLLECTOR_CONFIG_YAML"
        secret_name = "otel-config-yaml"
      }
    }
  }

  # Internal only — app containers send OTLP/HTTP on port 4318; ACA proxies 80 → 4318
  ingress {
    external_enabled          = false
    allow_insecure_connections = true
    target_port               = 4318
    transport                 = "http"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }
}

resource "azurerm_container_app_environment" "main" {
  name                       = "cae-${local.prefix}"
  resource_group_name        = data.azurerm_resource_group.main.name
  location                   = local.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  # VNet integration gives containers a routable path to the Azure OpenAI
  # private endpoint. External ingress (webhook) remains internet-facing.
  infrastructure_subnet_id = azurerm_subnet.aca_infra.id

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [infrastructure_resource_group_name]
  }
}

# ── ChromaDB (internal only, Azure File mount for persistence) ────────────────

resource "azurerm_container_app" "chromadb" {
  name                         = "chromadb"
  resource_group_name          = data.azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"

  template {
    min_replicas = 1
    max_replicas = 1

    container {
      name   = "chromadb"
      image  = "chromadb/chroma:latest"
      cpu    = 0.5
      memory = "1Gi"

      env {
        name  = "IS_PERSISTENT"
        value = "FALSE"
      }
      env {
        name  = "ANONYMIZED_TELEMETRY"
        value = "FALSE"
      }
    }
  }

  ingress {
    external_enabled           = false
    allow_insecure_connections = true
    target_port                = 8000
    transport                  = "http"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }
}

# ── Shared secrets (referenced by all app containers) ────────────────────────
# Terraform can't share secret blocks across resources, so each container app
# declares the same set. Secrets are encrypted at rest by ACA.

# ── API (FastAPI + Uvicorn, external HTTPS ingress) ──────────────────────────

resource "azurerm_container_app" "api" {
  name                         = "ca-${local.prefix}-api"
  resource_group_name          = data.azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.acr_pull.id]
  }

  secret {
    name  = "acr-password"
    value = var.acr_admin_password
  }

  registry {
    server               = "${var.acr_name}.azurecr.io"
    username             = var.acr_name
    password_secret_name = "acr-password"
  }

  secret {
    name  = "db-url"
    value = local.db_url
  }
  secret {
    name  = "redis-url"
    value = local.redis_url
  }
  secret {
    name  = "chromadb-url"
    value = local.chromadb_url
  }
  secret {
    name  = "azure-openai-api-key"
    value = azurerm_cognitive_account.openai.primary_access_key
  }
  secret {
    name  = "github-app-id"
    value = var.github_app_id
  }
  secret {
    name  = "github-app-private-key"
    value = var.github_app_private_key
  }
  secret {
    name  = "github-webhook-secret"
    value = var.github_webhook_secret
  }

  template {
    min_replicas = 1
    max_replicas = 3

    container {
      name   = "api"
      image  = local.image_ref
      cpu    = 0.5
      memory = "1Gi"
      args   = ["api"]

      env {
        name  = "LOG_LEVEL"
        value = "INFO"
      }
      env {
        name  = "OTEL_EXPORTER_OTLP_ENDPOINT"
        value = local.otel_endpoint
      }
      env {
        name  = "OTEL_EXPORTER_OTLP_PROTOCOL"
        value = "http/protobuf"
      }
      env {
        name  = "AZURE_OPENAI_ENDPOINT"
        value = azurerm_cognitive_account.openai.endpoint
      }
      env {
        name  = "AZURE_OPENAI_DEPLOYMENT_NAME"
        value = var.azure_openai_deployment_name
      }
      env {
        name  = "AZURE_OPENAI_API_VERSION"
        value = var.azure_openai_api_version
      }
      env {
        name  = "AZURE_OPENAI_EMBEDDING_DEPLOYMENT"
        value = var.azure_openai_embedding_deployment
      }
      env {
        name        = "DATABASE_URL"
        secret_name = "db-url"
      }
      env {
        name        = "REDIS_URL"
        secret_name = "redis-url"
      }
      env {
        name        = "CHROMADB_URL"
        secret_name = "chromadb-url"
      }
      env {
        name        = "AZURE_OPENAI_API_KEY"
        secret_name = "azure-openai-api-key"
      }
      env {
        name        = "GITHUB_APP_ID"
        secret_name = "github-app-id"
      }
      env {
        name        = "GITHUB_APP_PRIVATE_KEY"
        secret_name = "github-app-private-key"
      }
      env {
        name        = "GITHUB_WEBHOOK_SECRET"
        secret_name = "github-webhook-secret"
      }
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "http"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  depends_on = [azurerm_container_app.chromadb]
}

# ── Worker: review_jobs ───────────────────────────────────────────────────────

resource "azurerm_container_app" "worker_review" {
  name                         = "ca-${local.prefix}-worker-review"
  resource_group_name          = data.azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.acr_pull.id]
  }

  secret {
    name  = "acr-password"
    value = var.acr_admin_password
  }

  registry {
    server               = "${var.acr_name}.azurecr.io"
    username             = var.acr_name
    password_secret_name = "acr-password"
  }

  secret {
    name  = "db-url"
    value = local.db_url
  }
  secret {
    name  = "redis-url"
    value = local.redis_url
  }
  secret {
    name  = "chromadb-url"
    value = local.chromadb_url
  }
  secret {
    name  = "azure-openai-api-key"
    value = azurerm_cognitive_account.openai.primary_access_key
  }
  secret {
    name  = "github-app-id"
    value = var.github_app_id
  }
  secret {
    name  = "github-app-private-key"
    value = var.github_app_private_key
  }
  secret {
    name  = "github-webhook-secret"
    value = var.github_webhook_secret
  }

  template {
    min_replicas = 1
    max_replicas = 1

    container {
      name   = "worker-review"
      image  = local.image_ref
      cpu    = 0.5
      memory = "1Gi"
      args   = ["worker-review"]

      env {
        name  = "LOG_LEVEL"
        value = "INFO"
      }
      env {
        name  = "OTEL_EXPORTER_OTLP_ENDPOINT"
        value = local.otel_endpoint
      }
      env {
        name  = "OTEL_EXPORTER_OTLP_PROTOCOL"
        value = "http/protobuf"
      }
      env {
        name  = "AZURE_OPENAI_ENDPOINT"
        value = azurerm_cognitive_account.openai.endpoint
      }
      env {
        name  = "AZURE_OPENAI_DEPLOYMENT_NAME"
        value = var.azure_openai_deployment_name
      }
      env {
        name  = "AZURE_OPENAI_API_VERSION"
        value = var.azure_openai_api_version
      }
      env {
        name  = "AZURE_OPENAI_EMBEDDING_DEPLOYMENT"
        value = var.azure_openai_embedding_deployment
      }
      env {
        name        = "DATABASE_URL"
        secret_name = "db-url"
      }
      env {
        name        = "REDIS_URL"
        secret_name = "redis-url"
      }
      env {
        name        = "CHROMADB_URL"
        secret_name = "chromadb-url"
      }
      env {
        name        = "AZURE_OPENAI_API_KEY"
        secret_name = "azure-openai-api-key"
      }
      env {
        name        = "GITHUB_APP_ID"
        secret_name = "github-app-id"
      }
      env {
        name        = "GITHUB_APP_PRIVATE_KEY"
        secret_name = "github-app-private-key"
      }
      env {
        name        = "GITHUB_WEBHOOK_SECRET"
        secret_name = "github-webhook-secret"
      }
    }
  }

  depends_on = [azurerm_container_app.chromadb]
}

# ── Worker: feedback_jobs ─────────────────────────────────────────────────────

resource "azurerm_container_app" "worker_feedback" {
  name                         = "ca-${local.prefix}-worker-feedback"
  resource_group_name          = data.azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.acr_pull.id]
  }

  secret {
    name  = "acr-password"
    value = var.acr_admin_password
  }

  registry {
    server               = "${var.acr_name}.azurecr.io"
    username             = var.acr_name
    password_secret_name = "acr-password"
  }

  secret {
    name  = "db-url"
    value = local.db_url
  }
  secret {
    name  = "redis-url"
    value = local.redis_url
  }
  secret {
    name  = "chromadb-url"
    value = local.chromadb_url
  }
  secret {
    name  = "azure-openai-api-key"
    value = azurerm_cognitive_account.openai.primary_access_key
  }
  secret {
    name  = "github-app-id"
    value = var.github_app_id
  }
  secret {
    name  = "github-app-private-key"
    value = var.github_app_private_key
  }
  secret {
    name  = "github-webhook-secret"
    value = var.github_webhook_secret
  }

  template {
    min_replicas = 1
    max_replicas = 1

    container {
      name   = "worker-feedback"
      image  = local.image_ref
      cpu    = 0.25
      memory = "0.5Gi"
      args   = ["worker-feedback"]

      env {
        name  = "LOG_LEVEL"
        value = "INFO"
      }
      env {
        name  = "OTEL_EXPORTER_OTLP_ENDPOINT"
        value = local.otel_endpoint
      }
      env {
        name  = "OTEL_EXPORTER_OTLP_PROTOCOL"
        value = "http/protobuf"
      }
      env {
        name  = "AZURE_OPENAI_ENDPOINT"
        value = azurerm_cognitive_account.openai.endpoint
      }
      env {
        name  = "AZURE_OPENAI_DEPLOYMENT_NAME"
        value = var.azure_openai_deployment_name
      }
      env {
        name  = "AZURE_OPENAI_API_VERSION"
        value = var.azure_openai_api_version
      }
      env {
        name  = "AZURE_OPENAI_EMBEDDING_DEPLOYMENT"
        value = var.azure_openai_embedding_deployment
      }
      env {
        name        = "DATABASE_URL"
        secret_name = "db-url"
      }
      env {
        name        = "REDIS_URL"
        secret_name = "redis-url"
      }
      env {
        name        = "CHROMADB_URL"
        secret_name = "chromadb-url"
      }
      env {
        name        = "AZURE_OPENAI_API_KEY"
        secret_name = "azure-openai-api-key"
      }
      env {
        name        = "GITHUB_APP_ID"
        secret_name = "github-app-id"
      }
      env {
        name        = "GITHUB_APP_PRIVATE_KEY"
        secret_name = "github-app-private-key"
      }
      env {
        name        = "GITHUB_WEBHOOK_SECRET"
        secret_name = "github-webhook-secret"
      }
    }
  }

  depends_on = [azurerm_container_app.chromadb]
}

# ── Worker: indexer_jobs ──────────────────────────────────────────────────────

resource "azurerm_container_app" "worker_indexer" {
  name                         = "ca-${local.prefix}-worker-indexer"
  resource_group_name          = data.azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.acr_pull.id]
  }

  secret {
    name  = "acr-password"
    value = var.acr_admin_password
  }

  registry {
    server               = "${var.acr_name}.azurecr.io"
    username             = var.acr_name
    password_secret_name = "acr-password"
  }

  secret {
    name  = "db-url"
    value = local.db_url
  }
  secret {
    name  = "redis-url"
    value = local.redis_url
  }
  secret {
    name  = "chromadb-url"
    value = local.chromadb_url
  }
  secret {
    name  = "azure-openai-api-key"
    value = azurerm_cognitive_account.openai.primary_access_key
  }
  secret {
    name  = "github-app-id"
    value = var.github_app_id
  }
  secret {
    name  = "github-app-private-key"
    value = var.github_app_private_key
  }
  secret {
    name  = "github-webhook-secret"
    value = var.github_webhook_secret
  }

  template {
    min_replicas = 1
    max_replicas = 1

    container {
      name   = "worker-indexer"
      image  = local.image_ref
      cpu    = 0.5
      memory = "1Gi"
      args   = ["worker-indexer"]

      env {
        name  = "LOG_LEVEL"
        value = "INFO"
      }
      env {
        name  = "OTEL_EXPORTER_OTLP_ENDPOINT"
        value = local.otel_endpoint
      }
      env {
        name  = "OTEL_EXPORTER_OTLP_PROTOCOL"
        value = "http/protobuf"
      }
      env {
        name  = "AZURE_OPENAI_ENDPOINT"
        value = azurerm_cognitive_account.openai.endpoint
      }
      env {
        name  = "AZURE_OPENAI_DEPLOYMENT_NAME"
        value = var.azure_openai_deployment_name
      }
      env {
        name  = "AZURE_OPENAI_API_VERSION"
        value = var.azure_openai_api_version
      }
      env {
        name  = "AZURE_OPENAI_EMBEDDING_DEPLOYMENT"
        value = var.azure_openai_embedding_deployment
      }
      env {
        name        = "DATABASE_URL"
        secret_name = "db-url"
      }
      env {
        name        = "REDIS_URL"
        secret_name = "redis-url"
      }
      env {
        name        = "CHROMADB_URL"
        secret_name = "chromadb-url"
      }
      env {
        name        = "AZURE_OPENAI_API_KEY"
        secret_name = "azure-openai-api-key"
      }
      env {
        name        = "GITHUB_APP_ID"
        secret_name = "github-app-id"
      }
      env {
        name        = "GITHUB_APP_PRIVATE_KEY"
        secret_name = "github-app-private-key"
      }
      env {
        name        = "GITHUB_WEBHOOK_SECRET"
        secret_name = "github-webhook-secret"
      }
    }
  }

  depends_on = [azurerm_container_app.chromadb]
}

# ── KB Seed Job (run once after first deploy, or after CVE refresh) ──────────
# Trigger manually: az containerapp job start --name job-pr-reviewer-kb-seed -g titanium-team-03-rg

resource "azurerm_container_app_job" "kb_seed" {
  name                         = "job-${local.prefix}-kb-seed"
  resource_group_name          = data.azurerm_resource_group.main.name
  location                     = local.location
  container_app_environment_id = azurerm_container_app_environment.main.id

  replica_timeout_in_seconds = 600
  replica_retry_limit        = 1

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.acr_pull.id]
  }

  secret {
    name  = "acr-password"
    value = var.acr_admin_password
  }

  registry {
    server               = "${var.acr_name}.azurecr.io"
    username             = var.acr_name
    password_secret_name = "acr-password"
  }

  secret {
    name  = "db-url"
    value = local.db_url
  }
  secret {
    name  = "redis-url"
    value = local.redis_url
  }
  secret {
    name  = "chromadb-url"
    value = local.chromadb_url
  }
  secret {
    name  = "azure-openai-api-key"
    value = azurerm_cognitive_account.openai.primary_access_key
  }
  secret {
    name  = "github-app-id"
    value = var.github_app_id
  }
  secret {
    name  = "github-app-private-key"
    value = var.github_app_private_key
  }
  secret {
    name  = "github-webhook-secret"
    value = var.github_webhook_secret
  }

  template {
    container {
      name   = "kb-seed"
      image  = local.image_ref
      cpu    = 0.5
      memory = "1Gi"
      args   = ["seed-kb"]

      env {
        name  = "LOG_LEVEL"
        value = "INFO"
      }
      env {
        name  = "AZURE_OPENAI_ENDPOINT"
        value = azurerm_cognitive_account.openai.endpoint
      }
      env {
        name  = "AZURE_OPENAI_DEPLOYMENT_NAME"
        value = var.azure_openai_deployment_name
      }
      env {
        name  = "AZURE_OPENAI_API_VERSION"
        value = var.azure_openai_api_version
      }
      env {
        name  = "AZURE_OPENAI_EMBEDDING_DEPLOYMENT"
        value = var.azure_openai_embedding_deployment
      }
      env {
        name        = "DATABASE_URL"
        secret_name = "db-url"
      }
      env {
        name        = "REDIS_URL"
        secret_name = "redis-url"
      }
      env {
        name        = "CHROMADB_URL"
        secret_name = "chromadb-url"
      }
      env {
        name        = "AZURE_OPENAI_API_KEY"
        secret_name = "azure-openai-api-key"
      }
      env {
        name        = "GITHUB_APP_ID"
        secret_name = "github-app-id"
      }
      env {
        name        = "GITHUB_APP_PRIVATE_KEY"
        secret_name = "github-app-private-key"
      }
      env {
        name        = "GITHUB_WEBHOOK_SECRET"
        secret_name = "github-webhook-secret"
      }
    }
  }

  depends_on = [
    azurerm_container_app.chromadb,
    azurerm_postgresql_flexible_server_database.main,
  ]
}

# ── Celery Beat (scheduler — must be single instance) ────────────────────────

resource "azurerm_container_app" "beat" {
  name                         = "ca-${local.prefix}-beat"
  resource_group_name          = data.azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.acr_pull.id]
  }

  secret {
    name  = "acr-password"
    value = var.acr_admin_password
  }

  registry {
    server               = "${var.acr_name}.azurecr.io"
    username             = var.acr_name
    password_secret_name = "acr-password"
  }

  secret {
    name  = "db-url"
    value = local.db_url
  }
  secret {
    name  = "redis-url"
    value = local.redis_url
  }
  secret {
    name  = "chromadb-url"
    value = local.chromadb_url
  }
  secret {
    name  = "azure-openai-api-key"
    value = azurerm_cognitive_account.openai.primary_access_key
  }
  secret {
    name  = "github-app-id"
    value = var.github_app_id
  }
  secret {
    name  = "github-app-private-key"
    value = var.github_app_private_key
  }
  secret {
    name  = "github-webhook-secret"
    value = var.github_webhook_secret
  }

  template {
    min_replicas = 1
    max_replicas = 1

    container {
      name   = "beat"
      image  = local.image_ref
      cpu    = 0.25
      memory = "0.5Gi"
      args   = ["beat"]

      env {
        name  = "LOG_LEVEL"
        value = "INFO"
      }
      env {
        name  = "OTEL_EXPORTER_OTLP_ENDPOINT"
        value = local.otel_endpoint
      }
      env {
        name  = "OTEL_EXPORTER_OTLP_PROTOCOL"
        value = "http/protobuf"
      }
      env {
        name  = "AZURE_OPENAI_ENDPOINT"
        value = azurerm_cognitive_account.openai.endpoint
      }
      env {
        name  = "AZURE_OPENAI_DEPLOYMENT_NAME"
        value = var.azure_openai_deployment_name
      }
      env {
        name  = "AZURE_OPENAI_API_VERSION"
        value = var.azure_openai_api_version
      }
      env {
        name  = "AZURE_OPENAI_EMBEDDING_DEPLOYMENT"
        value = var.azure_openai_embedding_deployment
      }
      env {
        name        = "DATABASE_URL"
        secret_name = "db-url"
      }
      env {
        name        = "REDIS_URL"
        secret_name = "redis-url"
      }
      env {
        name        = "CHROMADB_URL"
        secret_name = "chromadb-url"
      }
      env {
        name        = "AZURE_OPENAI_API_KEY"
        secret_name = "azure-openai-api-key"
      }
      env {
        name        = "GITHUB_APP_ID"
        secret_name = "github-app-id"
      }
      env {
        name        = "GITHUB_APP_PRIVATE_KEY"
        secret_name = "github-app-private-key"
      }
      env {
        name        = "GITHUB_WEBHOOK_SECRET"
        secret_name = "github-webhook-secret"
      }
    }
  }
}

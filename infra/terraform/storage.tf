resource "random_string" "storage_suffix" {
  length  = 6
  upper   = false
  special = false
}

# Storage account for ChromaDB persistent data
resource "azurerm_storage_account" "chroma" {
  name                     = "stchroma${random_string.storage_suffix.result}"
  resource_group_name      = data.azurerm_resource_group.main.name
  location                 = local.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  min_tls_version          = "TLS1_2"
}

resource "azurerm_storage_share" "chroma" {
  name                 = "chromadb-data"
  storage_account_name = azurerm_storage_account.chroma.name
  quota                = 50
}

# ── OTel Collector config ─────────────────────────────────────────────────────

resource "azurerm_storage_share" "otel" {
  name                 = "otel-config"
  storage_account_name = azurerm_storage_account.chroma.name
  quota                = 1
}

resource "azurerm_storage_share_file" "otel_config" {
  name             = "config.yml"
  storage_share_id = azurerm_storage_share.otel.id
  source           = "${path.module}/../../otel/collector-config.yml"
}

resource "azurerm_container_app_environment_storage" "otel" {
  name                         = "otel-config-storage"
  container_app_environment_id = azurerm_container_app_environment.main.id
  account_name                 = azurerm_storage_account.chroma.name
  share_name                   = azurerm_storage_share.otel.name
  access_key                   = azurerm_storage_account.chroma.primary_access_key
  access_mode                  = "ReadOnly"
}

# ── ChromaDB data ─────────────────────────────────────────────────────────────

# Mount the file share into the ACA environment so container apps can use it
resource "azurerm_container_app_environment_storage" "chroma" {
  name                         = "chromadb-storage"
  container_app_environment_id = azurerm_container_app_environment.main.id
  account_name                 = azurerm_storage_account.chroma.name
  share_name                   = azurerm_storage_share.chroma.name
  access_key                   = azurerm_storage_account.chroma.primary_access_key
  access_mode                  = "ReadWrite"
}

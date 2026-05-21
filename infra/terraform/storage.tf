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

  network_rules {
    default_action = "Deny"
    bypass         = ["AzureServices"]
    ip_rules       = ["52.191.238.235", "172.178.57.93"]
  }
}

# Shares are pre-created via ARM (az storage share-rm create) to bypass the
# data-plane network restriction in azurerm v3.x.
# chromadb-data (quota 50 GiB) and otel-config (quota 1 GiB) exist in
# stchroma${random_string.storage_suffix.result}.

# ── ChromaDB data ─────────────────────────────────────────────────────────────

resource "azurerm_container_app_environment_storage" "chroma" {
  name                         = "chromadb-storage"
  container_app_environment_id = azurerm_container_app_environment.main.id
  account_name                 = azurerm_storage_account.chroma.name
  share_name                   = "chromadb-data"
  access_key                   = azurerm_storage_account.chroma.primary_access_key
  access_mode                  = "ReadWrite"
}

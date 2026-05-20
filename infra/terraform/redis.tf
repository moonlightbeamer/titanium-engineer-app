resource "azurerm_redis_cache" "main" {
  name                = "redis-${local.prefix}"
  resource_group_name = data.azurerm_resource_group.main.name
  location            = local.location
  capacity            = 1
  family              = "C"
  sku_name            = "Basic"
  non_ssl_port_enabled = false
  minimum_tls_version = "1.2"
}

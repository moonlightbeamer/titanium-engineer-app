locals {
  prefix   = "pr-reviewer"
  location = data.azurerm_resource_group.main.location

  image_ref = "${var.acr_name}.azurecr.io/${local.prefix}:${var.image_tag}"

  db_name = "pr_reviewer"
  db_user = var.db_admin_user

  db_url = "postgresql://${local.db_user}:${urlencode(var.db_admin_password)}@${azurerm_postgresql_flexible_server.main.fqdn}:5432/${local.db_name}?sslmode=require"

  # Azure Cache for Redis only exposes SSL on port 6380; key is base64-encoded so urlencode() is required
  redis_url = "rediss://:${urlencode(azurerm_redis_cache.main.primary_access_key)}@${azurerm_redis_cache.main.hostname}:${azurerm_redis_cache.main.ssl_port}/0"

  # ChromaDB runs as an internal ACA app; port 80 is the ACA ingress layer that
  # proxies to the container's target_port (8000). Include :80 explicitly so
  # urlparse() in container.py resolves the port correctly.
  chromadb_url = "http://chromadb.internal.${azurerm_container_app_environment.main.default_domain}:80"

  # OTel collector is internal-only; ACA proxies port 80 → container port 4318 (HTTP/protobuf)
  otel_endpoint = "http://otel-collector.internal.${azurerm_container_app_environment.main.default_domain}"
}

output "api_fqdn" {
  description = "Public FQDN for the FastAPI webhook endpoint"
  value       = "https://${azurerm_container_app.api.ingress[0].fqdn}"
}

output "api_fqdn_raw" {
  description = "Raw FQDN (set this as your GitHub App webhook URL)"
  value       = azurerm_container_app.api.ingress[0].fqdn
}

output "postgres_fqdn" {
  description = "PostgreSQL Flexible Server FQDN"
  value       = azurerm_postgresql_flexible_server.main.fqdn
}

output "redis_hostname" {
  description = "Azure Cache for Redis hostname"
  value       = azurerm_redis_cache.main.hostname
}

output "chromadb_internal_fqdn" {
  description = "ChromaDB internal FQDN (accessible only within the ACA environment)"
  value       = local.chromadb_url
}

output "kb_seed_job_trigger" {
  description = "Command to seed ChromaDB after first deploy (or after a CVE refresh)"
  value       = "az containerapp job start --name ${azurerm_container_app_job.kb_seed.name} --resource-group ${var.resource_group_name}"
}

output "otel_collector_endpoint" {
  description = "OTel collector OTLP/HTTP endpoint (internal to ACA environment)"
  value       = local.otel_endpoint
}

output "acr_login_server" {
  description = "ACR login server for docker push"
  value       = data.azurerm_container_registry.acr.login_server
}

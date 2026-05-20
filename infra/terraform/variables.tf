variable "resource_group_name" {
  description = "Resource group to deploy into"
  type        = string
  default     = "titanium-team-03-rg"
}

variable "acr_name" {
  description = "Azure Container Registry name (without .azurecr.io)"
  type        = string
  default     = "ttmt03c83eacr"
}

variable "acr_resource_group" {
  description = "Resource group containing the ACR (defaults to same as app RG)"
  type        = string
  default     = "titanium-team-03-rg"
}

variable "image_tag" {
  description = "Docker image tag to deploy"
  type        = string
  default     = "latest"
  validation {
    condition     = length(var.image_tag) > 0
    error_message = "image_tag must not be empty."
  }
}

# ── Database ──────────────────────────────────────────────────────────────────

variable "db_admin_user" {
  description = "PostgreSQL administrator login name"
  type        = string
  default     = "pradmin"
}

variable "db_admin_password" {
  description = "PostgreSQL admin password (min 8 chars, needs uppercase, lowercase, digit, symbol)"
  type        = string
  sensitive   = true
}

# ── App secrets — pass as TF_VAR_* environment variables ─────────────────────

variable "github_app_id" {
  description = "GitHub App numeric ID"
  type        = string
  sensitive   = true
}

variable "github_app_private_key" {
  description = "GitHub App RSA private key in PEM format (actual newlines, not \\n)"
  type        = string
  sensitive   = true
}

variable "github_webhook_secret" {
  description = "GitHub webhook secret token"
  type        = string
  sensitive   = true
}

variable "azure_openai_api_key" {
  type      = string
  sensitive = true
}

variable "azure_openai_endpoint" {
  description = "Azure OpenAI endpoint URL (e.g. https://resource.openai.azure.com)"
  type        = string
  validation {
    condition     = startswith(var.azure_openai_endpoint, "https://")
    error_message = "azure_openai_endpoint must use HTTPS."
  }
}

variable "azure_openai_deployment_name" {
  type    = string
  default = "gpt-5.1"
}

variable "azure_openai_api_version" {
  type    = string
  default = "2024-08-01-preview"
}

variable "azure_openai_embedding_deployment" {
  type    = string
  default = "text-embedding-3-large"
}
